#!/usr/bin/env python3
r"""1.23.0 (S2): display benchmark from 3-5 comparable published papers (S07).

    .\.venv\Scripts\python.exe tools\pubmed\benchmark.py add --pmid 12345678 --design disproportionality
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


def add(project: Path, pmid: str, design: str, *, role: str = "", figures=None, tables=None,
        supplementary=None, types: list[str] | None = None, source: str = "",
        xml: Path | None = None) -> dict:
    meta = record_of(pmid)
    counts = None
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
    if types:
        paper["display_types"] = sorted(set(types))
    paper["captions"] = [c for c in counts.get("captions", [])][:40]
    return db.add_paper(project, design, paper)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="display benchmark from comparable papers (1.23.0)")
    ap.add_argument("command", choices=("add", "show", "types"))
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
        if args.command == "add":
            if not args.pmid or not args.design:
                raise ValueError("add needs --pmid and --design")
            p = add(project, args.pmid, args.design, role=args.role, figures=args.figures,
                    tables=args.tables, supplementary=args.supplementary,
                    types=[t.strip() for t in args.types.split(",") if t.strip()],
                    source=args.source)
            print(f"PMID {p['pmid']} ({p['source']}): {p['main_figures']} main figure(s), "
                  f"{p['main_tables']} main table(s), {p['supplementary']} supplementary item(s); "
                  f"types: {', '.join(p['display_types']) or '-'}")
            print(f"benchmark: {len(db.load(project)['papers'])} paper(s) in {db.REL}")
            return 0
        lines = db.message_zh(project)
        print("Send the user these lines in the S07 message (Chinese, unchanged):")
        print("\n".join(f"  {x}" for x in lines))
        for prob in db.plan_problems(project):
            print(f"  TODO {prob}")
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"benchmark refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
