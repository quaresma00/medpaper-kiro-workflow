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
    ap.add_argument("command", choices=["assess", "answer", "show", "ai-rule", "ai"])
    ap.add_argument("qid", nargs="?")
    ap.add_argument("value", nargs="?")
    ap.add_argument("--used", choices=["yes", "no"], help="ai: did the authors use AI/LLM tools")
    ap.add_argument("--tool", default="", help="ai: tool name and version")
    ap.add_argument("--purpose", default="", help="ai: what it was used for")
    ap.add_argument("--words", default="", help="ai: the author's answer, verbatim")
    ap.add_argument("--words-file", help="UTF-8 file holding --words")
    ap.add_argument("--words-b64", help="base64 of the UTF-8 --words text")
    ap.add_argument("--project", type=Path, default=None)
    from wfcore import argtext
    args = ap.parse_args(argtext.fix_argv(sys.argv[1:]))
    project = wfpaths.paper_from_cli(args.project)
    try:
        if args.command == "ai-rule":  # 1.15.0 (E10): show this to the author when asking
            rule = dc.ai_requirement(project)
            print("journal AI/LLM-use requirement (guidelines_extract.md):\n" + (
                rule or "(the guideline snapshot says nothing about AI/LLM use)"))
            fact = dc.ai_fact(project)
            print("recorded author answer: " + (json.dumps(fact, ensure_ascii=False) if fact
                                                 else "none yet - ask the author once"))
            return 0
        if args.command == "ai":
            if args.used is None:
                raise ValueError('ai needs --used yes|no [--tool "..." --purpose "..."] --words "..."')
            fact = dc.record_ai(project, args.used == "yes", args.tool, args.purpose, args.words)
            print("recorded the author's AI/LLM-use fact; statement for the declarations:\n  "
                  + fact["statement"])
            return 0
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
        fact = dc.ai_fact(project)
        if fact:
            print(f"AI/LLM use (author's fact): {'used' if fact['used'] else 'not used'}; "
                  f"statement: {fact['statement']}")
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
