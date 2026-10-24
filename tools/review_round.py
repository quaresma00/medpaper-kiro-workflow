#!/usr/bin/env python3
"""Review rounds at S19 (scope manuscript) and S24 (scope package), 1.8.1 / 1.10.0.

    start  [--delta]   inventory + hash-bound text copies for the medpaper-reviewer subagent
    close  --findings critical=0,major=2,minor=3
           --finding ID CATEGORY STATUS "one line"   (one per finding; CATEGORY
               numbers|grouping|conclusion_strength|other, STATUS changed|kept|author)
           --change FILE "one line" ... --kept ID "why"
           --report FILE   (1.11.0: the reviewer's saved report; every F-numbered finding in
                            every section must be listed; each kept one needs --kept ID "why")
    author ID change|keep --words "<the author's words>"   (a finding handed to the author)
    decide another_round --words "<the user's answer>"
    decide no_further_review --words "我确认这一版"        (exact sentence, or "I confirm this version")
    export             ONLY when the user explicitly asks: read-only ZIP + one-page change summary
    status

numbers/grouping/conclusion_strength findings cannot be closed as "kept": change them or mark
them "author". `decide no_further_review` records the approval bound to the round id and the
version hash of the confirmed files.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wfcore import paths as wfpaths, readerreview, reviewrounds as rr  # noqa: E402
from wfcore.state import State  # noqa: E402


def _counts(raw: str) -> dict[str, int]:
    out = {}
    for part in filter(None, (x.strip() for x in raw.split(","))):
        key, _, val = part.partition("=")
        if key.strip() not in rr.SEVERITIES:
            raise ValueError(f"severity must be one of {', '.join(rr.SEVERITIES)}: {key}")
        out[key.strip()] = int(val)
    return out


def _main() -> int:
    ap = argparse.ArgumentParser(description="subagent review rounds (no review package)")
    ap.add_argument("command", choices=["start", "close", "author", "decide", "export", "status"])
    ap.add_argument("answer", nargs="*")
    ap.add_argument("--scope", choices=sorted(rr.SCOPES))
    ap.add_argument("--project", type=Path, default=None)
    ap.add_argument("--delta", action="store_true")
    ap.add_argument("--findings", default="")
    ap.add_argument("--finding", nargs=4, action="append", default=[],
                    metavar=("ID", "CATEGORY", "STATUS", "SUMMARY"))
    ap.add_argument("--change", nargs=2, action="append", default=[], metavar=("FILE", "SUMMARY"))
    ap.add_argument("--kept", nargs=2, action="append", default=[], metavar=("ITEM", "REASON"))
    ap.add_argument("--words", default="")
    ap.add_argument("--report", type=Path, default=None,
                    help="the reviewer's saved full report; every numbered finding must be closed")
    args = ap.parse_args()
    project = wfpaths.paper_from_cli(args.project)
    state = State(project, ".wf").load()
    scope = args.scope or ("package" if state.current >= "S24" else "manuscript")
    try:
        if args.command == "start":
            rnd = rr.start(project, scope, state.current, delta=args.delta)
            bundle = rr.write_bundle(project, rnd)
            print(f"review round {rnd['id']} ({rnd['mode']}) opened, {len(rnd['reviewed'])} file(s).")
            print(f"Pass the medpaper-reviewer subagent this ONE path (it reads everything itself):\n"
                  f"  {bundle / 'MANIFEST.md'}")
            print("Brief to send unchanged - add nothing about known deviations, earlier "
                  "conclusions or what you expect:")
            print("  " + rr.BRIEF.format(rid=rnd["id"], scope=scope, mode=rnd["mode"],
                                          bundle=bundle).replace("\n", "\n  "))
            print("Save its full report to a file and close with --report <file>.")
            print("Bundle contents (current files):")
            for rel in rnd["reviewed"]:
                print(f"  {rel}")
            if state.current.startswith("S18"):
                print("\nPaste this block unchanged into the S18 review report:")
                print(readerreview.evidence_block(project, delta=args.delta))
            return 0
        if args.command == "close":
            rnd = rr.close(project, scope, _counts(args.findings),
                           [{"file": f, "summary": s} for f, s in args.change],
                           [{"item": i, "reason": r} for i, r in args.kept],
                           [{"id": i, "category": c, "status": s, "summary": t}
                            for i, c, s, t in args.finding], report=args.report)
            print(f"closed {rnd['id']}: findings {rnd['findings']}; {len(rnd['changes'])} change(s).")
            pend = rr.pending_author(rnd)
            if pend:
                print("List these as PENDING AUTHOR DECISIONS in the summary (the user decides each):")
                for f in pend:
                    print(f"  {f['id']} [{f['category']}] {f['summary']}")
            print("Now give the user ONE summary and ask: another review round, or confirm with "
                  f"the exact sentence '{rr.CONFIRM_PHRASES[0]}'?")
            return 0
        if args.command == "author":
            if len(args.answer) != 2:
                raise ValueError("author needs ID and change|keep")
            hit = rr.author_decide(project, scope, args.answer[0], args.answer[1], args.words)
            print(f"{hit['id']}: author decided {hit['author_decision']['choice']}")
            return 0
        if args.command == "decide":
            answer = args.answer[0] if args.answer else ""
            if answer not in (rr.ANOTHER, rr.DONE):
                raise ValueError("decide needs another_round or no_further_review")
            rnd = rr.decide(project, scope, answer, args.words)
            if answer == rr.DONE:
                cfg = rr.SCOPES[scope]
                state.record_decision(cfg["decision"], cfg["value"],
                                      f"review round {rnd['id']}: user confirmed version "
                                      f"{rnd['confirmed_version'][:12]}: \"{rnd['user_words']}\"")
                print(f"{rnd['id']}: confirmed; {cfg['decision']}={cfg['value']} recorded")
            else:
                print(f"{rnd['id']}: user wants another round; run start again (--delta is fine)")
            return 0
        if args.command == "export":
            out = rr.export(project, scope)
            print(f"read-only review copy (user request only): {out}")
            return 0
        print(json.dumps(rr.load(project)[scope][-3:], indent=2, ensure_ascii=False)[:4000])
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print(f"review round error: {exc}", file=sys.stderr)
        return 2


def main() -> int:
    rc = None
    try:
        rc = _main()
        return rc
    finally:
        try:  # 1.11.0 (#3g): <paper>/.wf/progress.md stays current
            from wfcore import progress
            progress.write(wfpaths.paper_from_cli(progress.project_arg(sys.argv)), "review_round.py " + " ".join(sys.argv[1:3]), rc)
        except (Exception, SystemExit):  # noqa: BLE001
            pass


if __name__ == "__main__":
    raise SystemExit(main())
