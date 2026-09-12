#!/usr/bin/env python3
r"""Fetch open-access full text for the deep-read papers.

Legal open-access routes only, tried in order: Europe PMC / PMC OA -> Unpaywall ->
OpenAlex. Paywalled papers are recorded as paywalled; they are never
silently treated as read.

    .\.venv\Scripts\python.exe tools\pubmed\fulltext.py fetch --citekey smith2023
    .\.venv\Scripts\python.exe tools\pubmed\fulltext.py register --citekey smith2023 \
        --file paper.pdf --access oa --source-url https://example.org/article
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pubmed import eutils as eu  # noqa: E402

EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest"
UNPAYWALL = "https://api.unpaywall.org/v2"
OPENALEX = "https://api.openalex.org/works"
MANIFEST = "retrieval_manifest.json"


def out_dir() -> Path:
    d = eu.project_root() / "06_refs" / "fulltext"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _save(name: str, blob: bytes) -> str:
    p = out_dir() / name
    p.write_bytes(blob)
    return f"06_refs/fulltext/{name}"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# Identity: is this file actually the paper we asked for?
# ---------------------------------------------------------------------------
# A sha256 receipt proves the bytes did not change since download. It says nothing about
# whether those bytes are the requested article - a wrong PMCID fetches a different paper and
# its hash verifies perfectly. So the content is asked who it is, and the answer is compared
# with the library entry.
#
# The evidence is asymmetric on purpose:
#
#   XML and HTML expose identifiers in a STRUCTURED position that belongs to the article -
#   <article-id> in the JATS front matter, <meta name="citation_doi">. A contradiction there is
#   conclusive, so a mismatch refuses the file.
#
#   A PDF has no such position. Its raw bytes contain the DOIs of everything it CITES, so
#   "some other DOI appears in here" is not evidence of anything - treating it as evidence
#   would repeat the exact mistake that caused this bug (reading a bibliography as if it
#   described the article). For a PDF only positive evidence counts: our identifier present
#   means match, absent means indeterminate. Never mismatch.
_DOI_RE = re.compile(rb"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+")


def _jats_ids(blob: bytes) -> dict:
    """Identifiers from the article's own JATS front matter."""
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(blob)
    except ET.ParseError:
        return {}
    front = root.find(".//front/article-meta")
    if front is None:
        return {}
    found = {}
    for el in front.findall("./article-id"):
        kind = (el.get("pub-id-type") or "").lower()
        val = "".join(el.itertext()).strip()
        if kind and val and kind not in found:
            found[kind] = val
    title = front.find(".//title-group/article-title")
    if title is not None:
        found["title"] = re.sub(r"\s+", " ", "".join(title.itertext())).strip()
    return found


def _html_ids(blob: bytes) -> dict:
    """Identifiers from citation_* / dc.* meta tags, which describe the page's own article."""
    text = blob.decode("utf-8", errors="replace")
    found = {}
    for name, key in (("citation_doi", "doi"), ("citation_pmid", "pmid"),
                      ("citation_pmcid", "pmc"), ("citation_title", "title"),
                      ("dc.identifier", "doi")):
        m = re.search(
            rf'<meta[^>]+name=["\']{re.escape(name)}["\'][^>]+content=["\']([^"\']+)["\']',
            text, re.I)
        if not m:
            m = re.search(
                rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']{re.escape(name)}["\']',
                text, re.I)
        if m and key not in found:
            found[key] = m.group(1).strip()
    return found


def check_identity(entry: dict, blob: bytes, ext: str) -> dict:
    """Compare a downloaded payload against the library entry it was fetched for."""
    want_doi = str(entry.get("doi") or "").strip().casefold()
    want_pmid = str(entry.get("pmid") or "").strip()
    want_pmc = str(entry.get("pmcid") or "").strip().upper()

    if ext == "xml":
        found, conclusive = _jats_ids(blob), True
    elif ext in ("html", "htm"):
        found, conclusive = _html_ids(blob), True
    else:
        # PDF (or anything opaque): positive evidence only.
        raw = blob if len(blob) < 8_000_000 else blob[:8_000_000]
        hits = {m.group(0).decode("ascii", "replace").casefold().rstrip(".,;)")
                for m in _DOI_RE.finditer(raw)}
        if want_doi and want_doi in hits:
            return {"identity": "match", "identity_basis": "pdf-doi-present",
                    "identity_detail": f"library DOI {want_doi} occurs in the file"}
        return {"identity": "indeterminate", "identity_basis": f"{ext}-opaque",
                "identity_detail": "no identifier could be read from the payload; a PDF's "
                                   "cited DOIs are not evidence either way"}

    got_doi = str(found.get("doi") or "").strip().casefold()
    got_pmid = str(found.get("pmid") or "").strip()
    got_pmc = str(found.get("pmc") or "").strip().upper()
    if got_pmc and not got_pmc.startswith("PMC"):
        got_pmc = f"PMC{got_pmc}"
    got_title = str(found.get("title") or "").strip()

    agree, disagree = [], []
    for label, want, got in (("DOI", want_doi, got_doi), ("PMID", want_pmid, got_pmid),
                             ("PMCID", want_pmc, got_pmc)):
        if not want or not got:
            continue
        (agree if want == got else disagree).append(f"{label} {want} vs {got}")

    if disagree:
        return {"identity": "mismatch", "identity_basis": f"{ext}-metadata",
                "identity_detail": "; ".join(disagree)
                                   + (f'; payload title "{got_title[:70]}"' if got_title else ""),
                "identity_found": {k: v for k, v in found.items() if k != "title"}}
    if agree:
        return {"identity": "match", "identity_basis": f"{ext}-metadata",
                "identity_detail": "; ".join(agree)}
    if conclusive and got_title:
        # No shared identifier, but the payload names itself. Titles are fuzzy, so this is a
        # prompt to look rather than a verdict.
        return {"identity": "indeterminate", "identity_basis": f"{ext}-title-only",
                "identity_detail": f'no shared identifier; payload title "{got_title[:70]}" '
                                   f'vs library "{str(entry.get("title", ""))[:70]}"'}
    return {"identity": "indeterminate", "identity_basis": f"{ext}-no-metadata",
            "identity_detail": "payload exposed no identifier to compare"}


class WrongPaper(Exception):
    """Raised when a payload conclusively identifies as a different article."""


def _guard_identity(entry: dict, blob: bytes, ext: str, url: str) -> dict:
    verdict = check_identity(entry, blob, ext)
    if verdict["identity"] == "mismatch":
        raise WrongPaper(
            f"{entry['citekey']}: {url} returned a DIFFERENT article and was NOT saved.\n"
            f"    {verdict['identity_detail']}\n"
            f"    The library entry's locator is wrong, not the download. Rebuild library.json "
            f"from a fresh EFetch (tools/pubmed/build_library.py) rather than editing it."
        )
    return verdict


def record_retrieval(entry: dict, result: dict) -> dict:
    """Upsert a machine-verifiable provenance record for a retrieval result."""
    path = out_dir() / MANIFEST
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (json.JSONDecodeError, OSError):
        data = {}
    records = {r.get("citekey"): r for r in data.get("retrievals", []) if r.get("citekey")}
    record = {
        "citekey": entry["citekey"],
        "pmid": entry.get("pmid", ""),
        "doi": entry.get("doi", ""),
        "route": result.get("route", ""),
        "access": result.get("access", ""),
        "fulltext": result.get("fulltext", ""),
        "source_url": result.get("source_url", ""),
        "authorization_note": result.get("authorization_note", ""),
        "retrieved_at": _now(),
        # Who the payload says it is. Absent means never checked, which the gate treats as
        # unproven rather than fine.
        "identity": result.get("identity", ""),
        "identity_basis": result.get("identity_basis", ""),
        "identity_detail": result.get("identity_detail", ""),
        "identity_confirmed_by": result.get("identity_confirmed_by", ""),
    }
    if result.get("pmcid"):
        record["pmcid_used"] = result["pmcid"]
    source = record["fulltext"]
    if source and not str(source).startswith("http"):
        local = eu.project_root() / source
        if local.is_file():
            record["bytes"] = local.stat().st_size
            record["sha256"] = _sha256(local)
    records[entry["citekey"]] = record
    payload = {"schema": 1, "updated_at": _now(),
               "retrievals": [records[k] for k in sorted(records)]}
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return record


# ---------------------------------------------------------------------------
def try_europepmc(entry: dict) -> dict | None:
    pmid, pmcid = entry.get("pmid"), entry.get("pmcid")
    if not pmcid and pmid:
        try:
            raw = eu.http_get(f"{EPMC}/search",
                              {"query": f"EXT_ID:{pmid}", "format": "json", "resultType": "core"})
            hits = json.loads(raw).get("resultList", {}).get("result", [])
            if hits:
                pmcid = hits[0].get("pmcid") or ""
                if hits[0].get("isOpenAccess") != "Y" and not pmcid:
                    return None
        except Exception:  # noqa: BLE001
            return None
    if not pmcid:
        return None
    pmcid = pmcid if pmcid.upper().startswith("PMC") else f"PMC{pmcid}"
    for kind, url, ext in (
        ("xml", f"{EPMC}/{pmcid}/fullTextXML", "xml"),
        ("pdf", f"{EPMC}/{pmcid}/pdf", "pdf"),
    ):
        try:
            blob = eu.http_get(url)
        except Exception:  # noqa: BLE001
            continue
        if len(blob) < 2000:
            continue
        verdict = _guard_identity(entry, blob, ext, url)
        rel = _save(f"{entry['citekey']}.{ext}", blob)
        return {"route": f"europepmc-{kind}", "access": "oa", "fulltext": rel,
                "bytes": len(blob), "pmcid": pmcid, "source_url": url, **verdict}
    return None


def try_unpaywall(entry: dict) -> dict | None:
    doi, email = entry.get("doi"), eu.api_email()
    if not doi or not email:
        return None
    try:
        raw = eu.http_get(f"{UNPAYWALL}/{urllib.parse.quote(doi)}", {"email": email})
        data = json.loads(raw)
    except Exception:  # noqa: BLE001
        return None
    loc = data.get("best_oa_location") or {}
    url = loc.get("url_for_pdf") or loc.get("url")
    if not url:
        return None
    try:
        blob = eu.http_get(url)
    except Exception:  # noqa: BLE001
        return {"route": "unpaywall-link", "access": "link-only", "fulltext": url,
                "source_url": url,
                "note": "OA landing page found but the file could not be downloaded here"}
    ext = "pdf" if blob[:4] == b"%PDF" else "html"
    verdict = _guard_identity(entry, blob, ext, url)
    return {"route": "unpaywall", "access": "oa",
            "fulltext": _save(f"{entry['citekey']}.{ext}", blob), "bytes": len(blob),
            "license": loc.get("license"), "version": loc.get("version"),
            "source_url": url, **verdict}


def try_openalex(entry: dict) -> dict | None:
    doi = entry.get("doi")
    if not doi:
        return None
    try:
        raw = eu.http_get(f"{OPENALEX}/doi:{urllib.parse.quote(doi)}",
                          {"mailto": eu.api_email() or ""})
        data = json.loads(raw)
    except Exception:  # noqa: BLE001
        return None
    loc = data.get("best_oa_location") or {}
    url = loc.get("pdf_url") or loc.get("landing_page_url")
    if not url:
        return None
    try:
        blob = eu.http_get(url)
        ext = "pdf" if blob[:4] == b"%PDF" else "html"
        verdict = _guard_identity(entry, blob, ext, url)
        return {"route": "openalex", "access": "oa",
                "fulltext": _save(f"{entry['citekey']}.{ext}", blob), "bytes": len(blob),
                "source_url": url, **verdict}
    except WrongPaper:
        raise
    except Exception:  # noqa: BLE001
        return {"route": "openalex-link", "access": "link-only", "fulltext": url,
                "source_url": url}


ROUTES = (try_europepmc, try_unpaywall, try_openalex)


def fetch_one(entry: dict) -> dict:
    wrong: list[str] = []
    for fn in ROUTES:
        try:
            res = fn(entry)
        except WrongPaper as exc:
            # Do not fall through to the next route as if this were a network miss. The locator
            # is wrong, and a route that happens to succeed would hide that.
            res = None
            wrong.append(str(exc))
            print(f"    {exc}")
        except Exception as exc:  # noqa: BLE001
            res = None
            print(f"    {fn.__name__} raised {type(exc).__name__}: {exc}")
        if res:
            return res
    if wrong:
        return {
            "route": "none", "access": "wrong-article",
            "fulltext": "", "source_url": "",
            "identity": "mismatch", "identity_basis": "fetch-refused",
            "identity_detail": " | ".join(wrong)[:600],
            "note": "a route returned a different article, so nothing was saved. Fix the "
                    "library entry's PMCID/DOI by rebuilding from EFetch, then refetch.",
        }
    doi = entry.get("doi")
    return {
        "route": "none", "access": "paywalled",
        "fulltext": f"https://doi.org/{doi}" if doi else "",
        "source_url": f"https://doi.org/{doi}" if doi else "",
        "note": "no open-access copy found. Use your institutional access, or rely on the "
                "abstract and say so explicitly in the deep-read notes.",
    }


NOTES_TEMPLATE = """# {citekey} - {short_title}

Source: {source}
Access: {access} (route: {route})
PMID {pmid} | DOI {doi}

## Design and population

## What they did differently from us

## Their key numbers

## How this supports or contradicts our finding

## What a reviewer would take from this
"""


def main() -> int:
    ap = argparse.ArgumentParser(description="fetch open-access full text for deep reading")
    ap.add_argument("command", nargs="?", choices=("fetch", "register", "verify"),
                    default="fetch")
    ap.add_argument("--citekey", action="append", default=[])
    ap.add_argument("--all-deepread", action="store_true",
                    help="fetch everything listed in deepread_index.json")
    ap.add_argument("--no-stub", action="store_true", help="do not create the notes stub")
    ap.add_argument("--file", type=Path, help="local PDF/XML/HTML to register")
    ap.add_argument("--access", choices=("oa", "authorized"),
                    help="legal access basis for a registered file")
    ap.add_argument("--source-url", help="landing page or authoritative source URL")
    ap.add_argument("--route", default="external", help="acquisition route, e.g. scansci-pdf")
    ap.add_argument("--authorization-note",
                    help="required for institutionally authorized full text")
    ap.add_argument("--replace-existing", action="store_true",
                    help="replace a different previously registered file for this citekey")
    ap.add_argument("--all-retrieved", action="store_true",
                    help="verify: re-check every file in the retrieval manifest")
    ap.add_argument("--confirm-identity", metavar="TITLE",
                    help="verify: for an indeterminate payload only, record the article title "
                         "you read off the first page yourself")
    args = ap.parse_args()

    lib_path = eu.refs_dir() / "library.json"
    if not lib_path.exists():
        eu.die("06_refs/library.json missing. Build the library first (S13).")
    entries = {e["citekey"]: e for e in json.loads(lib_path.read_text(encoding="utf-8")).get("entries", [])}

    keys = list(args.citekey)
    dr_path = eu.project_root() / "06_refs" / "deepread" / "deepread_index.json"
    if args.all_deepread:
        if not dr_path.exists():
            eu.die("deepread_index.json missing; pass --citekey instead")
        keys += [i["citekey"] for i in json.loads(dr_path.read_text(encoding="utf-8")).get("selected", [])]
    if not keys:
        eu.die("give at least one --citekey (or --all-deepread)")

    if args.command == "verify":
        man_path = out_dir() / MANIFEST
        if not man_path.exists():
            eu.die(f"no {MANIFEST}; nothing has been retrieved yet")
        data = json.loads(man_path.read_text(encoding="utf-8"))
        records = {r.get("citekey"): r for r in data.get("retrievals", []) if r.get("citekey")}
        targets = sorted(records) if args.all_retrieved else keys
        if args.confirm_identity and len(targets) != 1:
            eu.die("--confirm-identity applies to exactly one --citekey")

        changed, bad = 0, []
        for key in targets:
            rec = records.get(key)
            if not rec:
                print(f"{key}: no retrieval record")
                continue
            rel = str(rec.get("fulltext", ""))
            if not rel or rel.startswith("http"):
                print(f"{key}: {rec.get('access', '?')} - no local file to check")
                continue
            local = eu.project_root() / rel
            if not local.is_file():
                print(f"{key}: MISSING FILE {rel}")
                bad.append(key)
                continue
            entry = entries.get(key)
            if not entry:
                print(f"{key}: not in library.json")
                bad.append(key)
                continue
            blob = local.read_bytes()
            verdict = check_identity(entry, blob, local.suffix.lstrip(".").lower())
            if verdict["identity"] == "indeterminate" and args.confirm_identity:
                seen = args.confirm_identity.strip()
                if len(seen) < 15:
                    eu.die("--confirm-identity needs the title you actually read, not a token")
                from difflib import SequenceMatcher
                sim = SequenceMatcher(
                    None, re.sub(r"\W+", " ", seen).casefold().strip(),
                    re.sub(r"\W+", " ", str(entry.get("title", ""))).casefold().strip()).ratio()
                if sim < 0.75:
                    eu.die(f'the title you read does not match the library entry (similarity '
                           f'{sim:.2f}).\n    you read : "{seen[:80]}"\n'
                           f'    library  : "{str(entry.get("title",""))[:80]}"\n'
                           f'    If the file really is a different paper, delete it and fix the '
                           f'library locator; do not confirm it.')
                verdict = {"identity": "match", "identity_basis": "human-read-title",
                           "identity_detail": f'title read from the file: "{seen[:120]}" '
                                              f'(similarity {sim:.2f})',
                           "identity_confirmed_by": "agent-read-first-page"}
            rec.update({k: verdict.get(k, "") for k in
                        ("identity", "identity_basis", "identity_detail",
                         "identity_confirmed_by")})
            rec["identity_checked_at"] = _now()
            rec["sha256"] = _sha256(local)
            rec["bytes"] = local.stat().st_size
            changed += 1
            tag = {"match": "OK  ", "mismatch": "WRONG", "indeterminate": "?   "}.get(
                verdict["identity"], "?   ")
            print(f"{tag} {key}: {verdict['identity']} ({verdict['identity_basis']})")
            print(f"        {verdict['identity_detail']}")
            if verdict["identity"] != "match":
                bad.append(key)

        if changed:
            payload = {"schema": 1, "updated_at": _now(),
                       "retrievals": [records[k] for k in sorted(records)]}
            man_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                                encoding="utf-8")
            print(f"\nupdated {changed} record(s) in 06_refs/fulltext/{MANIFEST}")
        if bad:
            print(f"\n{len(bad)} file(s) are not proven to be the requested article: "
                  f"{', '.join(bad)}")
            print("A sha256 receipt only proves the bytes are unchanged. For a mismatch, delete")
            print("the file and rebuild library.json from EFetch - the locator is what is wrong.")
            print("For an indeterminate PDF, open it and pass the title you read:")
            print('  fulltext.py verify --citekey KEY --confirm-identity "<title on page 1>"')
            return 2
        return 0

    if args.command == "register":
        if len(keys) != 1 or not args.file or not args.access or not args.source_url:
            eu.die("register requires one --citekey plus --file, --access and --source-url")
        if args.access == "authorized" and not (args.authorization_note or "").strip():
            eu.die("--authorization-note is required when --access authorized")
        if not re.match(r"^https?://", args.source_url, re.I):
            eu.die("--source-url must be an http(s) URL")
        key = keys[0]
        entry = entries.get(key)
        if not entry:
            eu.die(f"{key}: not in library.json - add and verify it before registration")
        source = args.file.expanduser().resolve()
        if not source.is_file():
            eu.die(f"file not found: {source}")
        suffix = source.suffix.lower()
        if suffix not in {".pdf", ".xml", ".html", ".htm"}:
            eu.die("registered full text must be PDF, XML or HTML")
        if source.stat().st_size < 1000:
            eu.die("registered full text is implausibly small (<1000 bytes)")
        if suffix == ".pdf":
            with source.open("rb") as stream:
                if stream.read(4) != b"%PDF":
                    eu.die("file has a .pdf suffix but no PDF signature")
        dest = out_dir() / f"{key}{suffix}"
        if dest.exists() and source != dest.resolve() and _sha256(dest) != _sha256(source):
            if not args.replace_existing:
                eu.die(f"{dest.name} already exists with different content; inspect it or pass "
                       "--replace-existing explicitly")
        # A hand-registered file gets the same interrogation as a downloaded one. Being handed
        # over by a person or a retrieval skill is not evidence of which paper it is.
        verdict = check_identity(entry, source.read_bytes(), suffix.lstrip("."))
        if verdict["identity"] == "mismatch":
            eu.die(f"refusing to register: this file identifies as a DIFFERENT article.\n"
                   f"    {verdict['identity_detail']}\n"
                   f"    Check the library entry's PMID/DOI and the file you meant to pass.")
        if source != dest.resolve():
            shutil.copy2(source, dest)
        result = {
            "route": args.route.strip() or "external",
            "access": args.access,
            "fulltext": f"06_refs/fulltext/{dest.name}",
            "source_url": args.source_url,
            "authorization_note": (args.authorization_note or "").strip(),
            **verdict,
        }
        record = record_retrieval(entry, result)
        print(f"{key}: registered {record['fulltext']}")
        print(f"    route={record['route']} access={record['access']} sha256={record['sha256']}")
        print(f"    identity={record['identity']} ({record['identity_basis']}): "
              f"{record['identity_detail']}")
        if record["identity"] != "match":
            print("    NOT proven to be the requested article. Open it, then either fix the "
                  "library entry or run:")
            print(f'      fulltext.py verify --citekey {key} --confirm-identity "<title on page 1>"')
        if not args.no_stub:
            notes = eu.project_root() / "06_refs" / "deepread" / f"{key}.md"
            notes.parent.mkdir(parents=True, exist_ok=True)
            if not notes.exists():
                notes.write_text(NOTES_TEMPLATE.format(
                    citekey=key,
                    short_title=re.sub(r"\s+", " ", entry.get("title", ""))[:80],
                    source=f"{entry.get('journal', '')} {entry.get('year', '')}",
                    access=result["access"], route=result["route"],
                    pmid=entry.get("pmid", ""), doi=entry.get("doi", ""),
                ), encoding="utf-8")
                print(f"    notes stub: 06_refs/deepread/{key}.md")
        return 0

    results = {}
    for key in dict.fromkeys(keys):
        entry = entries.get(key)
        if not entry:
            print(f"{key}: not in library.json - add it before deep-reading")
            continue
        print(f"{key}: {entry.get('title', '')[:70]}")
        res = fetch_one(entry)
        record_retrieval(entry, res)
        results[key] = res
        print(f"    -> {res['route']} / {res['access']} / {res.get('fulltext', '')}")
        if res.get("identity"):
            print(f"       identity={res['identity']} ({res.get('identity_basis','')}): "
                  f"{res.get('identity_detail','')}")
        if res.get("note"):
            print(f"       {res['note']}")

        if not args.no_stub:
            notes = eu.project_root() / "06_refs" / "deepread" / f"{key}.md"
            notes.parent.mkdir(parents=True, exist_ok=True)
            if not notes.exists():
                notes.write_text(NOTES_TEMPLATE.format(
                    citekey=key,
                    short_title=re.sub(r"\s+", " ", entry.get("title", ""))[:80],
                    source=f"{entry.get('journal', '')} {entry.get('year', '')}",
                    access=res["access"], route=res["route"],
                    pmid=entry.get("pmid", ""), doi=entry.get("doi", ""),
                ), encoding="utf-8")
                print(f"       notes stub: 06_refs/deepread/{key}.md")

    oa = sum(1 for r in results.values() if r["access"] == "oa")
    unproven = [k for k, r in results.items()
                if r.get("fulltext") and not str(r["fulltext"]).startswith("http")
                and r.get("identity") != "match"]
    print(f"\n{oa}/{len(results)} available open access.")
    if unproven:
        print(f"{len(unproven)} file(s) NOT proven to be the requested article: "
              f"{', '.join(unproven)}")
        print("The S15 gate blocks on these. A hash proves the bytes, not the paper.")
    print("Fill in every notes file, then record them in 06_refs/deepread/deepread_index.json.")
    print("Notes under 400 characters are rejected by the S15 gate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
