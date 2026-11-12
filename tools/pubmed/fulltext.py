#!/usr/bin/env python3
r"""Fetch full text for the deep-read papers - lawful routes only.

1.23.0 (S4) cascade, tried in order and recorded per paper (route): local cache -> Europe PMC /
PMC OA -> Unpaywall (best OA location; contact email NCBI_API_EMAIL / UNPAYWALL_EMAIL) ->
OpenAlex OA locations incl. repository author manuscripts -> Semantic Scholar openAccessPdf ->
CORE (only with the user's CORE_API_KEY) -> preprint versions linked by DOI relations
(medRxiv/bioRxiv/Research Square/SSRN, via Crossref) -> the publisher page in the visible
browser window with the user's own institutional or library login (the user logs in once; only
the listed papers, one at a time, within licence terms; then `register --route
browser-institutional --access authorized`) -> author-request e-mail drafts and a
document-delivery list for the library (`remaining`) -> ONE message listing the remaining
papers and the drop folder 06_refs/fulltext/drop/; PDFs placed there are ingested with the
same front-matter identity check (`ingest-drop`). Paywalled papers are recorded as paywalled;
they are never silently treated as read.

    .\.venv\Scripts\python.exe tools\pubmed\fulltext.py fetch --citekey smith2023
    .\.venv\Scripts\python.exe tools\pubmed\fulltext.py register --citekey smith2023 \
        --file paper.pdf --access oa --source-url https://example.org/article
    .\.venv\Scripts\python.exe tools\pubmed\fulltext.py remaining --all-deepread
    .\.venv\Scripts\python.exe tools\pubmed\fulltext.py ingest-drop
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
S2 = "https://api.semanticscholar.org/graph/v1/paper"
CORE = "https://api.core.ac.uk/v3/search/works"
CROSSREF = "https://api.crossref.org/works"
MANIFEST = "retrieval_manifest.json"
DROP = "drop"
REQUESTS = "requests"
CASCADE_ZH = ("本地缓存、PMC/Europe PMC、Unpaywall、OpenAlex（含机构库作者稿）、Semantic Scholar、"
              "CORE（如已配置）、预印本版本")


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
#   A PDF has no such position. Its text contains the DOIs of everything it CITES, so "our
#   DOI appears somewhere" is not evidence either: a different article that cites ours
#   contains it in its reference list. Identity is therefore read from the FRONT MATTER only
#   (the first pages, cut at the References/Bibliography heading) and needs two independent
#   signals: our DOI in the front matter AND (title similarity OR first-author surname + year).
#   Our DOI present only after the references heading means the file cites us - mismatch.
#   Anything weaker is indeterminate, which the S15 gate treats as unproven.
_DOI_RE = re.compile(rb"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+")
_DOI_TXT = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+")
_REFS_HEAD = re.compile(r"(?im)^\s*(?:\d+\.?\s*)?(references|bibliography|literature cited|"
                        r"works cited|reference list)\s*:?\s*$")
_REFS_INLINE = re.compile(r"(?i)\b(references|bibliography|literature cited)\b\s*[:\n]")
TITLE_MIN_OVERLAP = 0.8
FRONT_PAGES = 2


def _pdf_text(blob: bytes) -> tuple[str, str]:
    """(front_matter_text, full_text). pypdf when it can parse the file; otherwise the raw
    bytes decoded, which is what an uncompressed or synthetic PDF offers."""
    pages: list[str] = []
    try:
        import io
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(blob))
        pages = [(p.extract_text() or "") for p in reader.pages]
    except Exception:  # noqa: BLE001
        pages = []
    if any(p.strip() for p in pages):
        full = "\n".join(pages)
        front = "\n".join(pages[:FRONT_PAGES])
    else:
        full = blob[:8_000_000].decode("latin-1", errors="replace")
        front = full
    for rx in (_REFS_HEAD, _REFS_INLINE):
        m = rx.search(front)
        if m:
            front = front[:m.start()]
            break
    return front, full


def _norm_tokens(text: str) -> list[str]:
    return [t for t in re.sub(r"[^0-9a-z]+", " ", text.casefold()).split() if len(t) >= 3]


def title_overlap(title: str, text: str) -> float:
    """Share of the library title's content words that occur in `text`."""
    want = _norm_tokens(title)
    if not want:
        return 0.0
    have = set(_norm_tokens(text))
    return sum(1 for t in want if t in have) / len(want)


def _dois(text: str) -> set[str]:
    return {m.group(0).casefold().rstrip(".,;)") for m in _DOI_TXT.finditer(text)}


def _pdf_identity(entry: dict, blob: bytes, ext: str, want_doi: str) -> dict:
    front, full = _pdf_text(blob)
    # Line-wrapped DOIs ("10.1055/a-\n2669") are rejoined before matching.
    front_j = re.sub(r"-\s*\n\s*", "-", front)
    full_j = re.sub(r"-\s*\n\s*", "-", full)
    front_dois, all_dois = _dois(front_j), _dois(full_j)
    title = str(entry.get("title") or "")
    overlap = title_overlap(title, front_j)
    authors = entry.get("authors") or []
    surname = str(authors[0].get("last", "")) if authors and isinstance(authors[0], dict) else ""
    year = str(entry.get("year") or "")[:4]
    author_year = bool(surname and year and re.search(rf"(?i)\b{re.escape(surname)}\b", front_j)
                       and year in front_j)
    title_ok = overlap >= TITLE_MIN_OVERLAP
    signals = (f"title overlap {overlap:.2f} (need {TITLE_MIN_OVERLAP}); first author+year "
               f"{'found' if author_year else 'not found'}")
    if want_doi and want_doi in front_dois:
        if title_ok or author_year:
            return {"identity": "match", "identity_basis": "pdf-front-matter",
                    "identity_detail": f"library DOI {want_doi} in the front matter; {signals}"}
        return {"identity": "indeterminate", "identity_basis": "pdf-front-doi-only",
                "identity_detail": f"library DOI in the front matter but no second signal; "
                                   f"{signals}"}
    if want_doi and want_doi in all_dois:
        other = sorted(front_dois - {want_doi})[:2]
        return {"identity": "mismatch", "identity_basis": "pdf-doi-only-in-references",
                "identity_detail": f"library DOI {want_doi} occurs only after the front matter "
                                   f"(this file CITES the article)"
                                   + (f"; front matter names {', '.join(other)}" if other else "")
                                   + f"; {signals}"}
    return {"identity": "indeterminate", "identity_basis": f"{ext}-front-unverified",
            "identity_detail": f"library DOI not found in the front matter; {signals}. "
                               f"A PDF's cited DOIs are not evidence of identity"}


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
        return _pdf_identity(entry, blob, ext, want_doi)

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
    for k in ("routes_tried", "version", "preprint_doi", "next_step", "license"):  # 1.23.0 (S4)
        if result.get(k):
            record[k] = result[k]
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


def _download(entry: dict, url: str, route: str, **extra) -> dict | None:
    """GET one candidate URL; identity-checked like every other payload (None = no file)."""
    try:
        blob = eu.http_get(url)
    except Exception:  # noqa: BLE001
        return None
    if len(blob) < 2000:
        return None
    ext = "pdf" if blob[:4] == b"%PDF" else ("xml" if blob.lstrip()[:5] == b"<?xml" else "html")
    verdict = _guard_identity(entry, blob, ext, url)
    return {"route": route, "access": "oa", "fulltext": _save(f"{entry['citekey']}.{ext}", blob),
            "bytes": len(blob), "source_url": url, **extra, **verdict}


def try_cache(entry: dict) -> dict | None:
    """1.23.0 (S4): a file already retrieved for this paper and proven to be it."""
    path = out_dir() / MANIFEST
    try:
        recs = json.loads(path.read_text(encoding="utf-8")).get("retrievals", [])
    except (OSError, ValueError):
        return None
    for r in recs:
        if r.get("citekey") != entry.get("citekey") or r.get("identity") != "match":
            continue
        local = eu.project_root() / str(r.get("fulltext", ""))
        if r.get("fulltext") and local.is_file() and (not r.get("sha256")
                                                       or _sha256(local) == r["sha256"]):
            keep = ("route", "access", "fulltext", "source_url", "authorization_note", "identity",
                    "identity_basis", "identity_detail", "identity_confirmed_by")
            return {**{k: r.get(k, "") for k in keep}, "cache_hit": True}
    return None


def try_openalex(entry: dict) -> dict | None:
    """OpenAlex: the best OA location, then every other OA location (repository author
    manuscripts included), each identity-checked."""
    doi = entry.get("doi")
    if not doi:
        return None
    try:
        raw = eu.http_get(f"{OPENALEX}/doi:{urllib.parse.quote(doi)}",
                          {"mailto": eu.api_email() or ""})
        data = json.loads(raw)
    except Exception:  # noqa: BLE001
        return None
    locs = [data.get("best_oa_location") or {}] + [
        loc for loc in (data.get("locations") or []) if isinstance(loc, dict) and loc.get("is_oa")]
    link = None
    seen: set[str] = set()
    for loc in locs:
        url = loc.get("pdf_url")
        link = link or loc.get("landing_page_url") or url
        if not url or url in seen:
            continue
        seen.add(url)
        host = ((loc.get("source") or {}).get("type") or "") if isinstance(loc.get("source"), dict) else ""
        res = _download(entry, url, "openalex-repository" if host == "repository" else "openalex",
                        version=loc.get("version") or "", license=loc.get("license") or "")
        if res:
            return res
    if link:
        return {"route": "openalex-link", "access": "link-only", "fulltext": link,
                "source_url": link}
    return None


def try_semantic_scholar(entry: dict) -> dict | None:
    doi = entry.get("doi")
    if not doi:
        return None
    try:
        data = json.loads(eu.http_get(f"{S2}/DOI:{urllib.parse.quote(doi)}",
                                      {"fields": "openAccessPdf,externalIds"}))
    except Exception:  # noqa: BLE001
        return None
    url = ((data.get("openAccessPdf") or {}).get("url") or "") if isinstance(data, dict) else ""
    return _download(entry, url, "semantic-scholar") if url else None


def core_key() -> str:
    import os
    return os.environ.get("CORE_API_KEY", "").strip()


def try_core(entry: dict) -> dict | None:
    """CORE aggregator - only when the user configured their own CORE_API_KEY."""
    doi, key = entry.get("doi"), core_key()
    if not doi or not key:
        return None
    try:
        data = json.loads(eu.http_get(CORE, {"q": f'doi:"{doi}"', "limit": 3, "apiKey": key}))
    except Exception:  # noqa: BLE001
        return None
    for hit in (data.get("results") or []) if isinstance(data, dict) else []:
        url = hit.get("downloadUrl") or ""
        res = _download(entry, url, "core") if url else None
        if res:
            return res
    return None


def try_preprint(entry: dict) -> dict | None:
    """A preprint version linked to the article's DOI (Crossref relation has-preprint):
    medRxiv/bioRxiv/Research Square/SSRN. Recorded as a preprint, not the published version."""
    doi = entry.get("doi")
    if not doi:
        return None
    try:
        msg = json.loads(eu.http_get(f"{CROSSREF}/{urllib.parse.quote(doi)}")).get("message", {})
    except Exception:  # noqa: BLE001
        return None
    rel = (msg.get("relation") or {}).get("has-preprint") or []
    for r in rel if isinstance(rel, list) else []:
        pdoi = str(r.get("id", "")).strip()
        if r.get("id-type", "doi") != "doi" or not pdoi:
            continue
        pentry = {**entry, "doi": pdoi}
        try:
            data = json.loads(eu.http_get(f"{OPENALEX}/doi:{urllib.parse.quote(pdoi)}",
                                          {"mailto": eu.api_email() or ""}))
        except Exception:  # noqa: BLE001
            continue
        loc = data.get("best_oa_location") or {}
        url = loc.get("pdf_url")
        if not url:
            continue
        res = _download(pentry, url, "preprint", version="preprint", preprint_doi=pdoi,
                        note="preprint version (not the published article): check that the "
                             "numbers you cite match the published version")
        if res:
            return res
    return None


ROUTES = (try_cache, try_europepmc, try_unpaywall, try_openalex, try_semantic_scholar, try_core,
          try_preprint)


def fetch_one(entry: dict) -> dict:
    wrong: list[str] = []
    links: list[dict] = []
    tried: list[str] = []
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
        if res and res.get("access") == "link-only":
            links.append(res)  # 1.23.0: a landing page only - keep trying the later routes
            continue
        if res:
            res.setdefault("routes_tried", tried + [fn.__name__.replace("try_", "")])
            return res
        tried.append(fn.__name__.replace("try_", ""))
    if links and not wrong:
        return {**links[0], "routes_tried": tried, "next_step": "browser"}
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
        "route": "none", "access": "paywalled", "next_step": "browser",
        "fulltext": f"https://doi.org/{doi}" if doi else "",
        "source_url": f"https://doi.org/{doi}" if doi else "",
        "note": "no open-access copy on any lawful route. Next: the publisher page in the "
                "visible browser with the user's own institutional login (register --route "
                "browser-institutional --access authorized), then `fulltext.py remaining` "
                "(author-request drafts, library document delivery, the drop folder).",
    }


def _records() -> dict:
    try:
        data = json.loads((out_dir() / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {r.get("citekey"): r for r in data.get("retrievals", []) if r.get("citekey")}


def has_fulltext(rec: dict | None) -> bool:
    if not rec or rec.get("identity") != "match":
        return False
    rel = str(rec.get("fulltext", ""))
    return bool(rel) and not rel.startswith("http") and (eu.project_root() / rel).is_file()


def remaining_entries(entries: dict, keys: list[str]) -> list[dict]:
    """1.23.0 (S4): the papers still without a proven full text after the lawful cascade."""
    recs = _records()
    keys = keys or sorted(recs)
    return [entries[k] for k in dict.fromkeys(keys) if k in entries and not has_fulltext(recs.get(k))]


REQUEST_TEMPLATE = """Subject: Request for a copy of your article "{title}"

Dear Dr {surname},

I am preparing a clinical study on a closely related question and would be grateful for a copy of
your article, for my own research use only:

{cite}

Thank you very much for your help.

Kind regards,
[your name, position and institution]
"""


def _first_author(entry: dict) -> str:
    a = (entry.get("authors") or [{}])[0]
    return str(a.get("last") or a.get("name") or "Author") if isinstance(a, dict) else str(a)


def write_requests(rem: list[dict]) -> list[str]:
    """Author-request drafts (one per paper) and one document-delivery list for the library."""
    d = out_dir() / REQUESTS
    d.mkdir(parents=True, exist_ok=True)
    made = []
    for e in rem:
        doi = e.get("doi") or ""
        cite = (f"{_first_author(e)} et al. {e.get('title', '')}. {e.get('journal', '')} "
                f"{e.get('year', '')}." + (f" https://doi.org/{doi}" if doi else ""))
        p = d / f"{e['citekey']}_author_request.md"
        p.write_text(REQUEST_TEMPLATE.format(title=str(e.get("title", ""))[:200],
                                             surname=_first_author(e), cite=cite), encoding="utf-8")
        made.append(f"06_refs/fulltext/{REQUESTS}/{p.name}")
    rows = ["# Document delivery request (interlibrary loan)", "",
            "| # | Citekey | Title | Journal | Year | DOI | PMID |", "|---|---|---|---|---|---|---|"]
    rows += [f"| {i} | {e['citekey']} | {str(e.get('title', ''))[:120]} | {e.get('journal', '')} | "
             f"{e.get('year', '')} | {e.get('doi', '')} | {e.get('pmid', '')} |"
             for i, e in enumerate(rem, 1)]
    (d / "document_delivery.md").write_text("\n".join(rows) + "\n", encoding="utf-8")
    made.append(f"06_refs/fulltext/{REQUESTS}/document_delivery.md")
    (out_dir() / DROP).mkdir(exist_ok=True)
    return made


def remaining_message_zh(rem: list[dict]) -> list[str]:
    drop = out_dir() / DROP
    out = [f"以下 {len(rem)} 篇全文无法通过合法开放途径取得（已试：{CASCADE_ZH}）："]
    out += [f"  - {e.get('doi') or 'PMID ' + str(e.get('pmid', ''))}：{str(e.get('title', ''))[:90]}"
            for e in rem]
    out += ["请任选一种方式（只需回复一次）：",
            "  1 在可见的浏览器窗口里用您自己的机构/图书馆账号登录一次，我只下载上面这几篇；",
            f"  2 您自己取得 PDF 后放进文件夹：{drop}（我会核对首页确认是同一篇）；",
            f"  3 我已起草给通讯作者的索取邮件和给图书馆的文献传递清单：{out_dir() / REQUESTS}。",
            "仍取不到的，我只用摘要并在精读笔记里注明。"]
    return out


def ingest_drop(entries: dict, keys: list[str]) -> tuple[list[str], list[str]]:
    """Register every file in the drop folder that proves to be one of the library papers."""
    drop = out_dir() / DROP
    done, left = [], []
    pending = remaining_entries(entries, keys)
    order = pending + [e for k, e in sorted(entries.items()) if e not in pending]
    for f in sorted(drop.glob("*")) if drop.is_dir() else []:
        suffix = f.suffix.lower()
        if not f.is_file() or suffix not in (".pdf", ".xml", ".html", ".htm"):
            continue
        blob = f.read_bytes()
        hit = None
        for e in order:
            verdict = check_identity(e, blob, suffix.lstrip("."))
            if verdict["identity"] == "match":
                hit = (e, verdict)
                break
        if hit is None:
            left.append(f.name)
            continue
        e, verdict = hit
        dest = out_dir() / f"{e['citekey']}{suffix}"
        shutil.copy2(f, dest)
        doi = e.get("doi") or ""
        record_retrieval(e, {"route": "user-drop", "access": "authorized",
                             "fulltext": f"06_refs/fulltext/{dest.name}",
                             "source_url": f"https://doi.org/{doi}" if doi else "",
                             "authorization_note": "full text placed in the drop folder by the "
                                                   "user through their own access", **verdict})
        done.append(f"{f.name} -> {e['citekey']}")
    return done, left


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
    ap.add_argument("command", nargs="?", choices=("fetch", "register", "verify", "remaining",
                                                   "ingest-drop"), default="fetch")
    ap.add_argument("--citekey", action="append", default=[])
    ap.add_argument("--all-deepread", action="store_true",
                    help="fetch everything listed in deepread_index.json")
    ap.add_argument("--no-stub", action="store_true", help="do not create the notes stub")
    ap.add_argument("--file", type=Path, help="local PDF/XML/HTML to register")
    ap.add_argument("--access", choices=("oa", "authorized"),
                    help="legal access basis for a registered file")
    ap.add_argument("--source-url", help="landing page or authoritative source URL")
    ap.add_argument("--route", default="external",
                    help="acquisition route, e.g. browser-institutional (the user's own login)")
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
    if args.command == "remaining":  # 1.23.0 (S4): after the lawful cascade and the browser
        rem = remaining_entries(entries, keys)
        if not rem:
            print("every requested paper has a proven full text; nothing to ask the user")
            return 0
        made = write_requests(rem)
        print(f"{len(rem)} paper(s) without a full text; drafts: {', '.join(made[:3])}"
              + (" ..." if len(made) > 3 else ""))
        print("Send the user ONE message with these lines (Chinese, unchanged):")
        print("\n".join(f"  {x}" for x in remaining_message_zh(rem)))
        return 0
    if args.command == "ingest-drop":
        done, left = ingest_drop(entries, keys)
        for d in done:
            print(f"registered {d} (route user-drop, identity match)")
        for f in left:
            print(f"NOT registered {f}: it does not prove to be any library paper (front matter); "
                  "check the file, or `register --citekey KEY --file ... ` then `verify "
                  "--confirm-identity`")
        if not done and not left:
            print(f"the drop folder {out_dir() / DROP} is empty")
        return 0 if not left else 2
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
    absent = [k for k in dict.fromkeys(keys) if k not in results or not results[k].get("fulltext")]
    print(f"\n{oa}/{len(results)} available open access.")
    if unproven:
        print(f"{len(unproven)} file(s) NOT proven to be the requested article: "
              f"{', '.join(unproven)}")
        print("The S15 gate blocks on these. A hash proves the bytes, not the paper.")
    if absent:
        # Codex 1.11: a failed retrieval stops here; never deep-read the abstract instead.
        print(f"STOP: no full text for {', '.join(absent)} on any lawful open route. Do not write "
              "notes from the abstract. Next (1.23.0): the publisher page in the visible browser "
              "with the user's own institutional login (only these papers, one at a time; then "
              "`register --route browser-institutional --access authorized --authorization-note "
              "...`); still missing -> `fulltext.py remaining` and send its ONE message (drop "
              "folder, author-request drafts, library list); or choose another comparable paper.")
        return 2
    print("Fill in every notes file, then record them in 06_refs/deepread/deepread_index.json.")
    print("Notes under 400 characters are rejected by the S15 gate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
