#!/usr/bin/env python3
"""Review rounds at S19 (scope manuscript) and S24 (scope package), 1.8.1.

    start  [--delta]   inventory + hash-bound text copies for the medpaper-reviewer subagent
    close  --findings critical=0,major=2,minor=3 --change FILE "one line" ... --kept ITEM "why"
    decide another_round|no_further_review --words "<the user's answer>"
    status

`decide no_further_review` also records the stage's approval decision naming the round id.
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


def main() -> int:
    ap = argparse.ArgumentParser(description="subagent review rounds (no review package)")
    ap.add_argument("command", choices=["start", "close", "decide", "status"])
    ap.add_argument("answer", nargs="?", choices=[rr.ANOTHER, rr.DONE])
    ap.add_argument("--scope", choices=sorted(rr.SCOPES))
    ap.add_argument("--project", type=Path, default=None)
    ap.add_argument("--delta", action="store_true")
    ap.add_argument("--findings", default="")
    ap.add_argument("--change", nargs=2, action="append", default=[], metavar=("FILE", "SUMMARY"))
    ap.add_argument("--kept", nargs=2, action="append", default=[], metavar=("ITEM", "REASON"))
    ap.add_argument("--words", default="")
    args = ap.parse_args()
    project = wfpaths.paper_from_cli(args.project)
    state = State(project, ".wf").load()
    scope = args.scope or ("package" if state.current >= "S24" else "manuscript")
    try:
        if args.command == "start":
            rnd = rr.start(project, scope, state.current, delta=args.delta)
            print(f"review round {rnd['id']} ({rnd['mode']}) opened. Invoke the medpaper-reviewer "
                  "subagent with exactly these current files:")
            for rel in rnd["reviewed"]:
                print(f"  {project / rel}")
            for rel in readerreview.write_text_copies(project, rnd["reviewed"]):
                print(f"  {project / rel}   (hash-bound text copy, regenerated now)")
            if state.current.startswith("S18"):
                print("\nPaste this block unchanged into the S18 review report:")
                print(readerreview.evidence_block(project, delta=args.delta))
            return 0
        if args.command == "close":
            rnd = rr.close(project, scope, _counts(args.findings),
                           [{"file": f, "summary": s} for f, s in args.change],
                           [{"item": i, "reason": r} for i, r in args.kept])
            print(f"closed {rnd['id']}: findings {rnd['findings']}; {len(rnd['changes'])} change(s). "
                  "Now give the user ONE summary and ask: another review round, or none?")
            return 0
        if args.command == "decide":
            if not args.answer:
                raise ValueError("decide needs another_round or no_further_review")
            rnd = rr.decide(project, scope, args.answer, args.words)
            if args.answer == rr.DONE:
                cfg = rr.SCOPES[scope]
                state.record_decision(cfg["decision"], cfg["value"],
                                      f"review round {rnd['id']}: user said no further review: "
                                      f"\"{rnd['user_words']}\"")
                print(f"{rnd['id']}: no further review; {cfg['decision']}={cfg['value']} recorded")
            else:
                print(f"{rnd['id']}: user wants another round; run start again (--delta is fine)")
            return 0
        print(json.dumps(rr.load(project)[scope][-3:], indent=2, ensure_ascii=False)[:4000])
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print(f"review round error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
