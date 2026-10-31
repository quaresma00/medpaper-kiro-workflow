#!/usr/bin/env python3
"""Supplementary-file builders (1.15.0, E5).

    figures --number 3 --output 08_submission/bundle/ESM_3.pdf [--figure "Figure S1" ...]
        supplementary figures PDF: information page, then each figure with its legend
    xlsx --input 04_tables/supplementary/tables.xlsx --number 2 --output 08_submission/bundle/ESM_2.xlsx
        workbook with an "Info" sheet ("Online Resource 2", title, authors, journal)
    rebuild --receipt 08_submission/build_receipts/<name>.json   (used by `wf rebuild`)

Word supplementary files get the same header with build_docx.py build --kind supplementary
--esm-number <n>. Keep any helper script you need later in .wf/scripts/ (wf clean never
deletes it), never in temp/.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wfcore import paths as wfpaths, supplementary  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="supplementary figures PDF / workbook info sheet")
    ap.add_argument("command", choices=["figures", "xlsx", "rebuild"])
    ap.add_argument("--number", type=int, default=None, help="n in 'Online Resource n'")
    ap.add_argument("--figure", action="append", default=[],
                    help="figures: a planned figure id (default: every supplementary figure)")
    ap.add_argument("--input", type=Path, help="xlsx: the certified supplementary workbook")
    ap.add_argument("--output", type=Path, help="the upload file in 08_submission/bundle/")
    ap.add_argument("--receipt", type=Path, help="rebuild: a build receipt")
    ap.add_argument("--project", type=Path, default=None)
    args = ap.parse_args()
    project = wfpaths.paper_from_cli(args.project)
    try:
        if args.command == "rebuild":
            out = supplementary.rebuild_from(project, wfpaths.resolve_paper_path(args.receipt))
            print(f"rebuilt {out}")
            return 0
        if args.output is None:
            raise ValueError("--output is required")
        output = wfpaths.paper_output_path(args.output)
        if args.command == "figures":
            out, rec = supplementary.figures_pdf(project, output, args.number, args.figure or None)
        else:
            if args.input is None:
                raise ValueError("xlsx needs --input <workbook>")
            out, rec = supplementary.xlsx_info(project, wfpaths.resolve_paper_path(args.input),
                                               output, args.number)
    except (OSError, ValueError, KeyError) as exc:
        print(f"supplementary builder error: {exc}", file=sys.stderr)
        return 2
    print(f"built {out}\nbuild receipt -> {rec}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
