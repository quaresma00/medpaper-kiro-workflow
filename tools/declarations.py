#!/usr/bin/env python3
"""1.10.0 declarations: the workflow judges ethics, consent and data availability.

    assess                 conclusion + basis from idea.json study_design/data_source
    answer ID "<value>"    record the author's answer to one open question
    show                   print conclusions, statement texts and still-open questions

Ask the author only the printed open questions, each once.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wfcore import declarations as dc, paths as wfpaths  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="ethics / consent / data availability assessment")
    ap.add_argument("command", choices=["assess", "answer", "show"])
    ap.add_argument("qid", nargs="?")
    ap.add_argument("value", nargs="?")
    ap.add_argument("--project", type=Path, default=None)
    args = ap.parse_args()
    project = wfpaths.paper_from_cli(args.project)
    try:
        if args.command == "assess":
            data = dc.write(project)
        elif args.command == "answer":
            if not args.qid or args.value is None:
                raise ValueError('answer needs ID and "<value>"')
            data = dc.answer(project, args.qid, args.value)
        else:
            data = dc.load(project)
            if not data:
                raise ValueError(f"{dc.REL} missing: run assess first")
        for key in ("ethics", "consent"):
            print(f"{key}: {data[key]['conclusion']}")
        print(f"data availability: {data['data_availability']['text']}")
        print("basis: " + "; ".join(data["ethics"]["basis"]))
        open_q = dc.pending(data)
        if open_q:
            print("ask the author ONLY these (one message):")
            for q in open_q:
                print(f"  {q['id']}: {q['ask']}")
        else:
            print("no open question; write the statements from the conclusions and answers")
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"declarations error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
