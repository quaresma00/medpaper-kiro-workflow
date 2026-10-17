#!/usr/bin/env python3
"""Build 06_refs/library.json and export refs.bib / refs.ris.

Records without a retrievable abstract are dropped, not summarized. Citekeys already
used anywhere in the project are pulled in automatically so no citation is orphaned.

    .venv/Scripts/python.exe tools/pubmed/build_library.py --topic "..." --target 50
    .venv/Scripts/python.exe tools/pubmed/build_library.py --add-query "..." --target 50
    .venv/Scripts/python.exe tools/pubmed/build_library.py --add-ids 12345678,23456789
    .venv/Scripts/python.exe tools/pubmed/build_library.py --export
    .venv/Scripts/python.exe tools/pubmed/build_library.py --report
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pubmed import eutils as eu  # noqa: E402

LIB = "library.json"
MANUSCRIPT_GLOBS = [
    "01_protocol/*.md", "03_analysis/*.md", "07_manuscript/*.md",
]
CITE_RE = re.compile(r"@([A-Za-z][\w:.#$%&+?<>~/-]*)")


def lib_path() -> Path:
    return eu.refs_dir() / LIB


def load_library() -> dict:
    p = lib_path()
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"built_at": eu.now(), "queries": [], "entries": []}


def save_library(lib: dict) -> None:
    lib["updated_at"] = eu.now()
    lib_path().write_text(json.dumps(lib, indent=2, ensure_ascii=False), encoding="utf-8")


def used_citekeys() -> set[str]:
    """Citekeys already referenced in project prose - these must stay in the library."""
    out: set[str] = set()
    for pattern in MANUSCRIPT_GLOBS:
        for p in eu.project_root().glob(pattern):
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for m in re.finditer(r"\[([^\]]*@[^\]]*)\]", text):
                out.update(CITE_RE.findall(m.group(1)))
    return out


def _entry_from_record(rec: dict, taken: set[str]) -> dict:
    key = eu.make_citekey(rec, taken)
    taken.add(key)
    return {
        "citekey": key,
        "pmid": rec.get("pmid", ""),
        "doi": rec.get("doi", ""),
        "pmcid": rec.get("pmcid", ""),
        "title": rec.get("title", ""),
        "abstract": rec.get("abstract", ""),
        "authors": rec.get("authors", []),
        "journal": rec.get("journal", ""),
        "journal_abbrev": rec.get("journal_abbrev", ""),
        "year": rec.get("year", ""),
        "volume": rec.get("volume", ""),
        "issue": rec.get("issue", ""),
        "pages": rec.get("pages", ""),
        "elocator": rec.get("elocator", ""),
        "publication_types": rec.get("publication_types", []),
        "mesh": rec.get("mesh", [])[:15],
        "flags": rec.get("flags", []),
        "source": rec.get("source", "pubmed"),
        "cache_file": rec.get("cache_file", ""),
        "retrieved_at": rec.get("retrieved_at", eu.now()),
    }


def add_records(lib: dict, records: list[dict]) -> tuple[int, int, int]:
    by_pmid = {e.get("pmid"): e for e in lib["entries"] if e.get("pmid")}
    by_doi = {e.get("doi"): e for e in lib["entries"] if e.get("doi")}
    taken = {e["citekey"] for e in lib["entries"]}
    added = dropped = dup = 0
    for rec in records:
        if not (rec.get("abstract") or "").strip():
            dropped += 1
            continue
        if rec.get("pmid") and rec["pmid"] in by_pmid:
            dup += 1
            continue
        if rec.get("doi") and rec["doi"] in by_doi:
            dup += 1
            continue
        entry = _entry_from_record(rec, taken)
        lib["entries"].append(entry)
        if entry["pmid"]:
            by_pmid[entry["pmid"]] = entry
        if entry["doi"]:
            by_doi[entry["doi"]] = entry
        added += 1
    return added, dropped, dup


# ---------------------------------------------------------------------------
# exporters
# ---------------------------------------------------------------------------
BIB_ESCAPE = {"&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_"}


def _bib_escape(s: str) -> str:
    out = []
    for ch in s or "":
        out.append(BIB_ESCAPE.get(ch, ch))
    return "".join(out)


COLON_COMMON = {
    "a", "an", "the", "results", "findings", "evidence", "lessons", "insights", "implications",
    "analysis", "study", "review", "protocol", "rationale", "design", "update", "report",
    "experience", "outcomes", "comparison", "assessment", "evaluation", "association", "role",
    "impact", "effect", "effects", "risk", "trends", "challenges", "current", "new", "is", "does",
    "do", "are", "can", "should", "what", "when", "how", "why", "who", "where", "from", "toward",
    "towards", "beyond", "time", "more", "less", "no", "not", "one", "two", "three",
}


def protect_title(title: str) -> str:
    """Brace proper nouns and acronyms so a sentence-case CSL cannot lowercase them.

    PubMed titles are sentence case, so any capital after the first word marks a proper noun
    (da {Vinci}, {Food} and {Drug} {Administration}) and any internal capital an acronym
    ({MAUDE}, {COVID}-19, {mRNA}).
    """
    out = []
    after_colon = False
    for i, tok in enumerate(re.split(r"(\s+)", title)):
        core = tok.strip("()[]:;,.\"'")
        if tok.isspace() or not core or "{" in tok:
            out.append(tok)
            continue
        upper_inside = any(ch.isupper() for ch in core[1:])
        # 1.9.0 (#14): the capital PubMed puts after a colon is style, not a proper noun; leave
        # an ordinary word unbraced so the journal's CSL decides its case consistently.
        colon_word = after_colon and core.casefold() in COLON_COMMON
        after_colon = tok.rstrip().endswith(":")
        if colon_word and not upper_inside:
            out.append(tok)
        elif (i > 0 and core[:1].isupper()) or upper_inside:
            start = tok.find(core)
            out.append(tok[:start] + "{" + core + "}" + tok[start + len(core):])
        else:
            out.append(tok)
    return "".join(out)


def expand_pages(pages: str) -> str:
    """'123-9' -> '123--129'; keep article numbers ('e12345') and full ranges consistent."""
    pages = (pages or "").strip()
    m = re.fullmatch(r"([A-Za-z]?)(\d+)\s*[-\u2013]+\s*([A-Za-z]?)(\d+)", pages)
    if not m:
        return pages
    p1, a, p2, b = m.groups()
    if len(b) < len(a):
        b = a[:len(a) - len(b)] + b
    return f"{p1}{a}--{p2 or p1}{b}"


def bib_name(author: dict) -> str:
    last = author.get("last", "")
    if author.get("collective"):
        return "{" + last + "}"
    first = author.get("first") or author.get("initials", "")
    # Particles (de, van der, da) belong to the family name; brace so BibTeX/CSL keep "de Souza".
    if " " in last.strip() or re.match(r"^[a-z]", last):
        last = "{" + last + "}"
    return f"{last}, {first}".strip(", ")


def to_bibtex(entries: list[dict]) -> str:
    chunks = ["% Generated from library.json. Do not edit by hand - regenerate with --export.\n"]
    for e in entries:
        authors = " and ".join(bib_name(a) for a in e.get("authors", []) if a.get("last"))
        eloc = str(e.get("elocator", "") or "")
        pages = expand_pages(e.get("pages", "") or "") or (
            eloc if re.fullmatch(r"[A-Za-z]?\d{1,8}", eloc) else "")
        fields = [
            ("author", authors),
            ("title", protect_title(_bib_escape(e.get("title", "")))),
            ("journal", _bib_escape(e.get("journal", ""))),
            ("shortjournal", _bib_escape(e.get("journal_abbrev", "") or e.get("journal", ""))),
            ("year", e.get("year", "")),
            ("volume", e.get("volume", "")),
            ("number", e.get("issue", "")),
            ("pages", pages),
            ("doi", e.get("doi", "")),
            ("pmid", e.get("pmid", "")),
        ]
        body = ",\n".join(f"  {k} = {{{v}}}" for k, v in fields if v)
        note = ""
        if e.get("flags"):
            note = f",\n  note = {{FLAGS: {', '.join(e['flags'])}}}"
        chunks.append(f"@article{{{e['citekey']},\n{body}{note}\n}}\n")
    return "\n".join(chunks)


def to_ris(entries: list[dict]) -> str:
    out = []
    for e in entries:
        lines = ["TY  - JOUR"]
        for a in e.get("authors", []):
            if a.get("last"):
                name = a["last"] if a.get("collective") else f"{a['last']}, {a.get('first') or a.get('initials', '')}".strip(", ")
                lines.append(f"AU  - {name}")
        lines += [
            f"TI  - {e.get('title', '')}",
            f"JO  - {e.get('journal', '')}",
            f"PY  - {e.get('year', '')}",
        ]
        for tag, key in (("VL", "volume"), ("IS", "issue"), ("SP", "pages"), ("DO", "doi")):
            if e.get(key):
                lines.append(f"{tag}  - {e[key]}")
        if e.get("abstract"):
            lines.append(f"AB  - {e['abstract']}")
        if e.get("pmid"):
            lines.append(f"AN  - {e['pmid']}")
        lines.append(f"ID  - {e['citekey']}")
        lines.append("ER  - ")
        out.append("\n".join(lines))
    return "\n\n".join(out) + "\n"


def export(lib: dict) -> None:
    entries = sorted(lib["entries"], key=lambda e: e["citekey"])
    (eu.refs_dir() / "refs.bib").write_text(to_bibtex(entries), encoding="utf-8")
    (eu.refs_dir() / "refs.ris").write_text(to_ris(entries), encoding="utf-8")
    print(f"exported {len(entries)} entries -> 06_refs/refs.bib, 06_refs/refs.ris")


def report(lib: dict) -> None:
    entries = lib["entries"]
    print(f"library: {len(entries)} entries")
    no_abs = [e["citekey"] for e in entries if not (e.get("abstract") or "").strip()]
    flagged = [(e["citekey"], e["flags"]) for e in entries if e.get("flags")]
    years = sorted(int(e["year"]) for e in entries if str(e.get("year", "")).isdigit())
    if years:
        recent = sum(1 for y in years if y >= years[-1] - 4)
        print(f"years  : {years[0]}-{years[-1]}  ({recent} from the last 5 years)")
    print(f"with abstract : {len(entries) - len(no_abs)}/{len(entries)}")
    if no_abs:
        print(f"  !! must be removed: {', '.join(no_abs)}")
    if flagged:
        print("flagged records (do not cite as evidence):")
        for k, f in flagged:
            print(f"  {k}: {', '.join(f)}")
    orphans = used_citekeys() - {e["citekey"] for e in entries}
    if orphans:
        print(f"!! cited in the project but absent from the library: {', '.join(sorted(orphans))}")
    print("\njournals:")
    from collections import Counter
    for name, n in Counter(e.get("journal", "?") for e in entries).most_common(15):
        print(f"  {n:>3}  {name}")


# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="build and export the verified reference library")
    ap.add_argument("--topic", help="primary topic; runs a small family of queries")
    ap.add_argument("--add-query", action="append", default=[], help="one extra query (repeatable)")
    ap.add_argument("--add-ids", help="comma-separated PMIDs to add directly")
    ap.add_argument("--target", type=int, default=50, help="stop searching once this many entries exist")
    ap.add_argument("--retmax", type=int, default=60, help="records to pull per query")
    ap.add_argument("--years", type=int, help="restrict searches to the last N years")
    ap.add_argument("--export", action="store_true", help="regenerate refs.bib and refs.ris")
    ap.add_argument("--report", action="store_true", help="audit the current library")
    ap.add_argument("--drop", action="append", default=[], help="remove a citekey")
    args = ap.parse_args()

    lib = load_library()

    for key in args.drop:
        before = len(lib["entries"])
        lib["entries"] = [e for e in lib["entries"] if e["citekey"] != key]
        print(f"dropped {key}" if len(lib["entries"]) < before else f"{key} not in library")

    queries: list[str] = []
    if args.topic:
        queries += [
            args.topic,
            f"{args.topic} AND (epidemiology OR prevalence OR incidence)",
            f"{args.topic} AND (cohort OR cross-sectional OR case-control)",
            f"{args.topic} AND (systematic review OR meta-analysis)",
            f"{args.topic} AND (guideline OR consensus OR definition)",
        ]
    queries += args.add_query

    for q in queries:
        if len(lib["entries"]) >= args.target:
            print(f"target of {args.target} reached; skipping remaining queries")
            break
        res = eu.esearch(q, retmax=args.retmax, years=args.years)
        recs = eu.efetch(res["ids"])
        added, dropped, dup = add_records(lib, recs)
        lib.setdefault("queries", []).append(
            {"query": q, "at": eu.now(), "hits": res["count"], "added": added,
             "dropped_no_abstract": dropped, "duplicates": dup,
             "cache_file": res["cache_file"]}
        )
        print(f"[{q[:60]}] hits={res['count']} +{added} added, "
              f"{dropped} dropped for having no abstract, {dup} duplicate(s)")

    if args.add_ids:
        ids = [x for x in args.add_ids.replace(" ", "").split(",") if x]
        recs = eu.efetch(ids)
        added, dropped, dup = add_records(lib, recs)
        print(f"[--add-ids] +{added} added, {dropped} without abstract dropped, {dup} already present")

    missing = used_citekeys() - {e["citekey"] for e in lib["entries"]}
    if missing:
        print(f"\n!! {len(missing)} citekey(s) are cited in the project but not in the library:")
        print("   " + ", ".join(sorted(missing)))
        print("   Add them with --add-ids <pmid>, or fix the citation. Never leave a dangling key.")

    save_library(lib)
    if args.export or queries or args.add_ids or args.drop:
        export(lib)
    if args.report:
        report(lib)

    n = len(lib["entries"])
    print(f"\nlibrary now holds {n} entr{'y' if n == 1 else 'ies'} "
          f"-> next: .venv/Scripts/python.exe tools/pubmed/verify.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
