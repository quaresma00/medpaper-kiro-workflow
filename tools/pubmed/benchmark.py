#!/usr/bin/env python3
r"""1.23.0 (S2): display benchmark from comparable published papers (S07); 1.25.0 (A): the 5-10
most recent ones.

    .\.venv\Scripts\python.exe tools\pubmed\benchmark.py search [--design KEY] [--query "..."] [--extend --reason "..."]
    .\.venv\Scripts\python.exe tools\pubmed\benchmark.py skip --pmid 34567890 --reason not_comparable --note "single-centre cohort, not FAERS"
    .\.venv\Scripts\python.exe tools\pubmed\benchmark.py add --pmid 12345678 --design disproportionality
    .\.venv\Scripts\python.exe tools\pubmed\benchmark.py add --pmid 45678901 --design disproportionality --unknown-counts
    .\.venv\Scripts\python.exe tools\pubmed\benchmark.py add --pmid 56789012 --design disproportionality --exception "only comparable paper in the target journal (2019)" --figures 3 --tables 2 --supplementary 4 --source manual

`search` (1.25.0) builds the PubMed query from the structured study basis (01_protocol/idea.json:
design, data-source family) and the exposure/outcome labels of the display dictionary (--query
replaces that topical part), adds original-article, English and date filters (last 3 years; 5
when fewer than 5 candidates exist, or --extend with a reason), sorts by publication date (most
recent first; tools/pubmed/eutils.py, NCBI_API_KEY from the environment) and keeps metadata only
(esummary: PMID, date - electronic first -, journal, title) in 01_protocol/benchmark_search.json.
Take the candidates in order; `skip` records why a more recent one is passed over.
    .\.venv\Scripts\python.exe tools\pubmed\benchmark.py add --pmid 23456789 --design disproportionality --figures 4 --tables 2 --supplementary 6 --types forest_ror,time_to_onset --source abstract
    .\.venv\Scripts\python.exe tools\pubmed\benchmark.py show

`add` takes the paper's record from Europe PMC (title, journal, year, PMCID, open access).
Open access: the full-text XML is fetched and only its figure/table/supplementary captions are
counted and classified (cheap; no full reading). Otherwise a full text the cascade already
retrieved (06_refs/fulltext/, tools/pubmed/fulltext.py) is used; otherwise give the counts and
types you read from the abstract or the paper (--figures/--tables/--supplementary/--types,
--source abstract|manual). Writes 01_protocol/display_benchmark.json; `show` prints the Chinese
lines for the S07 message (benchmark counts and types, and the plan against them).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pubmed import eutils as eu  # noqa: E402
from wfcore import displaybench as db  # noqa: E402

EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest"


def record_of(pmid: str) -> dict:
    raw = eu.http_get(f"{EPMC}/search", {"query": f"EXT_ID:{pmid} AND SRC:MED", "format": "json",
                                         "resultType": "core"})
    hits = json.loads(raw).get("resultList", {}).get("result", [])
    if not hits:
        raise ValueError(f"PMID {pmid}: no Europe PMC record")
    h = hits[0]
    return {"pmid": str(pmid), "pmcid": h.get("pmcid") or "", "doi": h.get("doi") or "",
            "title": h.get("title") or "", "journal": (h.get("journalInfo") or {}).get(
                "journal", {}).get("title") or h.get("journalTitle") or "",
            "year": int(h["pubYear"]) if str(h.get("pubYear", "")).isdigit() else None,
            "open_access": h.get("isOpenAccess") == "Y" and bool(h.get("pmcid"))}


def _local_fulltext(project: Path, pmid: str) -> Path | None:
    man = project / "06_refs/fulltext/retrieval_manifest.json"
    try:
        recs = json.loads(man.read_text(encoding="utf-8")).get("retrievals", [])
    except (OSError, ValueError):
        return None
    for r in recs:
        if str(r.get("pmid")) == str(pmid) and r.get("identity") == "match":
            p = project / str(r.get("fulltext", ""))
            if p.is_file():
                return p
    return None


def esummary(ids: list[str]) -> list[dict]:
    """PubMed esummary metadata (PMID, dates, journal, title, publication types, language)."""
    out = []
    for i in range(0, len(ids), 200):
        raw = eu.http_get(f"{eu.EUTILS}/esummary.fcgi", {
            "db": "pubmed", "id": ",".join(ids[i:i + 200]), "retmode": "json", "tool": eu.TOOL,
            "email": eu.api_email(), "api_key": eu.api_key()})
        res = json.loads(raw).get("result", {})
        out += [res[u] for u in res.get("uids", []) if isinstance(res.get(u), dict)]
    return out


def search(project: Path, design: str = "", query: str = "", *, extend: bool = False,
           reason: str = "", retmax: int = 60) -> dict:
    """1.25.0 (A1): most recent comparable original articles -> 01_protocol/benchmark_search.json."""
    design = db.design_key(project, design)
    if design and design not in db.designs():
        raise ValueError(f"unknown design '{design}' (known: {', '.join(db.designs())})")
    if extend and len(reason.strip()) < 10:
        raise ValueError("--extend needs --reason (why fewer than 5 eligible papers exist in 3 years)")

    def run(years: int):
        q, start, end = db.build_query(project, design, query, years)
        hit = eu.esearch(q, retmax=retmax, sort="pub_date", record=False)
        recs = esummary(hit["ids"]) if hit["ids"] else []
        return q, start, end, hit["count"], recs

    years = db.WINDOW_EXTENDED if extend else db.WINDOW_YEARS
    q, start, end, count, recs = run(years)
    why = reason.strip() if extend else ""
    n_ok = sum(1 for r in recs if db.eligible_record(r, design))
    if not extend and n_ok < db.MIN_N:
        years = db.WINDOW_EXTENDED
        why = f"automatic: {n_ok} eligible candidate(s) in the last {db.WINDOW_YEARS} years (< {db.MIN_N})"
        q, start, end, count, recs = run(years)
    return db.record_search(project, query=q, design=design, years=years, start=start, end=end,
                            count=count, records=recs, extended_reason=why)


def add(project: Path, pmid: str, design: str, *, role: str = "", figures=None, tables=None,
        supplementary=None, types: list[str] | None = None, source: str = "",
        xml: Path | None = None, unknown_counts: bool = False, exception: str = "") -> dict:
    meta = record_of(pmid)
    counts = None
    if unknown_counts:  # 1.25.0 (A3): abstract only - listed, never in the median
        paper = {**meta, "main_figures": None, "main_tables": None, "supplementary": None,
                 "captions": [], "source": source or "abstract", "role": role,
                 "counts_known": False, "date": db.candidate_date(project, pmid)}
        if exception:
            paper["exception"] = exception
        return db.add_paper(project, design, paper)
    if xml is not None:
        counts, src = db.jats_displays(Path(xml).read_bytes()), "jats"
    elif meta["open_access"]:
        try:
            counts, src = db.jats_displays(eu.http_get(f"{EPMC}/{meta['pmcid']}/fullTextXML")), "jats"
        except Exception:  # noqa: BLE001 - fall through to the next route
            counts = None
    if counts is None:
        local = _local_fulltext(project, pmid)
        if local is not None:
            if local.suffix.lower() == ".xml":
                counts, src = db.jats_displays(local.read_bytes()), "jats"
            else:
                sys.path.insert(0, str(Path(__file__).resolve().parent))
                from fulltext import _pdf_text  # noqa: E402
                text, _how = _pdf_text(local.read_bytes()) if local.suffix.lower() == ".pdf" \
                    else (local.read_text(encoding="utf-8", errors="replace"), "html")
                counts, src = db.text_displays(text), "pdf"
    if counts is None or figures is not None:
        if figures is None or tables is None or supplementary is None:
            raise ValueError(f"PMID {pmid}: no open-access XML or retrieved full text; give "
                             "--figures, --tables, --supplementary and --types read from the "
                             "abstract or the paper (--source abstract|manual), or run the full-text "
                             "cascade first (tools/pubmed/fulltext.py)")
        counts = {"main_figures": int(figures), "main_tables": int(tables),
                  "supplementary": int(supplementary), "captions": []}
        src = source or "manual"
    paper = {**meta, **counts, "source": src, "role": role}
    if db.candidate_date(project, pmid):
        paper["date"] = db.candidate_date(project, pmid)
    if exception:  # 1.25.0 (A2): older than the window, recorded, outside the median
        paper["exception"] = exception
    if types:
        paper["display_types"] = sorted(set(types))
    paper["captions"] = [c for c in counts.get("captions", [])][:40]
    return db.add_paper(project, design, paper)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="display benchmark from comparable papers (1.23.0)")
    ap.add_argument("command", choices=("search", "skip", "add", "show", "types"))
    ap.add_argument("--query", default="", help="search: replaces the topical part of the query")
    ap.add_argument("--extend", action="store_true", help="search: 5-year window (needs --reason)")
    ap.add_argument("--reason", default="", help="search --extend: why; skip: " + "|".join(
        db.SKIP_REASONS))
    ap.add_argument("--note", default="", help="skip: one line saying why")
    ap.add_argument("--unknown-counts", action="store_true",
                    help="add: abstract only, display counts unknown (outside the median)")
    ap.add_argument("--exception", default="",
                    help="add: an older paper kept as a recorded exception (outside the median)")
    ap.add_argument("--pmid", default="")
    ap.add_argument("--design", default="")
    ap.add_argument("--role", default="", help="e.g. target_journal, same_tier, same_design")
    ap.add_argument("--figures", type=int, default=None)
    ap.add_argument("--tables", type=int, default=None)
    ap.add_argument("--supplementary", type=int, default=None)
    ap.add_argument("--types", default="", help="comma-separated display types (benchmark.py types)")
    ap.add_argument("--source", choices=("abstract", "manual"), default="")
    ap.add_argument("--xml", type=Path, default=None, help="a saved JATS XML of the paper")
    args = ap.parse_args(argv)
    project = eu.project_root()
    try:
        if args.command == "types":
            design = args.design or db.load(project).get("design", "")
            for key, spec in sorted(db.types_for(design).items()):
                print(f"{key}: {spec.get('label', '')} ({spec.get('kind', 'any')})")
            return 0
        if args.command == "search":
            s = search(project, args.design, args.query, extend=args.extend, reason=args.reason)
            print(f"search {s['searched_at']}: last {s['window_years']} years ({s['window_start']} "
                  f"to {s['window_end']}), {s['esearch_count']} hit(s), {s['n_candidates']} "
                  f"original-article candidate(s), most recent first -> {db.SEARCH_REL}"
                  + (f" [extended: {s['extended_reason']}]" if s.get("extended_reason") else ""))
            for i, c in enumerate(s["candidates"][:15], 1):
                print(f"  {i:>2}. {c['date']} PMID {c['pmid']} {c['journal']}: {c['title'][:90]}")
            print(f"Take them in this order: add the comparable ones (same design and data-source "
                  f"family; target {db.TARGET_N}, {db.MIN_N}-{db.MAX_N}), skip --pmid P --reason ... "
                  "--note ... for each more recent one you pass over.")
            return 0
        if args.command == "skip":
            if not args.pmid:
                raise ValueError("skip needs --pmid")
            db.skip(project, args.pmid, args.reason, args.note)
            print(f"PMID {args.pmid} skipped ({args.reason}): {args.note}")
            return 0
        if args.command == "add":
            if not args.pmid or not args.design:
                raise ValueError("add needs --pmid and --design")
            p = add(project, args.pmid, args.design, role=args.role, figures=args.figures,
                    tables=args.tables, supplementary=args.supplementary,
                    types=[t.strip() for t in args.types.split(",") if t.strip()],
                    source=args.source, unknown_counts=args.unknown_counts,
                    exception=args.exception)
            print(f"PMID {p['pmid']} ({p['source']}): {p['main_figures']} main figure(s), "
                  f"{p['main_tables']} main table(s), {p['supplementary']} supplementary item(s); "
                  f"types: {', '.join(p['display_types']) or '-'}")
            print(f"benchmark: {len(db.load(project)['papers'])} paper(s) in {db.REL}")
            return 0
        lines = db.message_zh(project)
        print("Send the user these lines in the S07 message (Chinese, unchanged):")
        print("\n".join(f"  {x}" for x in lines))
        from wfcore.checks.v1250 import since_1250_project
        for prob in db.plan_problems(project, v1250=since_1250_project(project, "S07_artifacts")):
            print(f"  TODO {prob}")
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"benchmark refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
