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

from wfcore import paths as wfpaths, readerreview, reviewguard, reviewrounds as rr  # noqa: E402
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
    ap.add_argument("command", choices=["start", "close", "ingest", "author", "decide", "export",
                                        "status"])
    ap.add_argument("--from", dest="from_file", type=Path, default=None,
                    help="ingest: the reviewer's saved reply or a host workflow-state JSON")
    ap.add_argument("answer", nargs="*")
    ap.add_argument("--scope", choices=sorted(rr.SCOPES))
    ap.add_argument("--project", type=Path, default=None)
    ap.add_argument("--delta", action="store_true")
    ap.add_argument("--findings", default="")
    ap.add_argument("--finding", nargs=4, action="append", default=[],
                    metavar=("ID", "CATEGORY", "STATUS", "SUMMARY"))
    ap.add_argument("--change", nargs=2, action="append", default=[], metavar=("FILE", "SUMMARY"))
    ap.add_argument("--kept", nargs=2, action="append", default=[], metavar=("ITEM", "REASON"))
    ap.add_argument("--preference-group", default="",
                    help="close: every finding the report tags PREFERENCE is kept as one group "
                         "with this one reason (1.15.0)")
    ap.add_argument("--words", default="")
    ap.add_argument("--words-file", help="UTF-8 file holding --words (avoids shell code pages)")
    ap.add_argument("--words-b64", help="base64 of the UTF-8 --words text")
    ap.add_argument("--report", type=Path, default=None,
                    help="the reviewer's saved full report; every numbered finding must be closed")
    from wfcore import argtext
    # 1.12.0 (C1): --words-file <utf-8 file> / --words-b64, and mis-decoded text repaired.
    args = ap.parse_args(argtext.fix_argv(sys.argv[1:]))
    project = wfpaths.paper_from_cli(args.project)
    state = State(project, ".wf").load()
    scope = args.scope or ("package" if state.current >= "S24" else "manuscript")
    try:
        if args.command == "start":
            rnd = rr.start(project, scope, state.current, delta=args.delta)
            bundle = rr.write_bundle(project, rnd)
            reviewguard.take(project, rnd["id"])  # 1.15.0 (E2): the review writes only its report
            print(f"review round {rnd['id']} ({rnd['mode']}) opened, {len(rnd['reviewed'])} file(s)."
                  + (f" Linked to {rnd['linked_to']} (awaiting the user)." if rnd.get("linked_to") else ""))
            print(f"Pass the medpaper-reviewer subagent this ONE path (it reads everything itself):\n"
                  f"  {bundle / 'MANIFEST.md'}")
            print("Brief to send unchanged - add nothing about known deviations, earlier "
                  "conclusions or what you expect:")
            print("  " + rr.brief(project, rnd, bundle).replace("\n", "\n  "))
            print(f"The reviewer writes its full report to {bundle / 'report.md'} (its only "
                  "writable file); then close with --report (defaults to that file). Do not "
                  "paraphrase the findings. If the host would not let it write: save its reply "
                  "and run review_round.py ingest --from <file> (text between <<<REPORT>>> and "
                  "<<<END>>> is copied verbatim; a workflow-state JSON works too).")
            print("Bundle contents (current files):")
            for rel in rnd["reviewed"]:
                print(f"  {rel}")
            if state.current.startswith("S18"):
                print("\nPaste this block unchanged into the S18 review report:")
                print(readerreview.evidence_block(project, delta=args.delta))
            return 0
        if args.command == "close":
            if args.report is None:  # 1.12.0 (E2): the reviewer's own file in the bundle
                last = rr.latest(project, scope)
                default = project / rr.BUNDLE_DIR / str((last or {}).get("id", "")) / "report.md"
                if last and default.is_file():
                    args.report = default
            last = rr.latest(project, scope)
            if last and args.report is not None and Path(args.report).is_file():
                bad = reviewguard.problems(project, str(last["id"]), Path(args.report),
                                           [f for f, _s in args.change])
                if bad:
                    raise ValueError("paper file(s) changed while the review was running and are "
                                     "not listed as your fixes (a review writes only its "
                                     "report): " + ", ".join(bad[:8]) + " - restore them (or "
                                     "list your own fix with --change) and close again")
            rnd = rr.close(project, scope, _counts(args.findings),
                           [{"file": f, "summary": s} for f, s in args.change],
                           [{"item": i, "reason": r} for i, r in args.kept],
                           [{"id": i, "category": c, "status": s, "summary": t}
                            for i, c, s, t in args.finding], report=args.report,
                           preference_reason=args.preference_group or "")
            print(f"closed {rnd['id']}: findings {rnd['findings']}; {len(rnd['changes'])} change(s)."
                  + (f" Preference group kept: {', '.join(rnd['preference_group']['ids'])}."
                     if rnd.get("preference_group") else ""))
            pend = rr.pending_author(rnd)
            if pend:
                print("List these as PENDING AUTHOR DECISIONS in the summary (the user decides each):")
                for f in pend:
                    print(f"  {f['id']} [{f['category']}] {f['summary']}")
            print("Now give the user ONE summary and ask: another review round, or confirm with "
                  f"the exact sentence '{rr.CONFIRM_PHRASES[0]}'?")
            return 0
        if args.command == "ingest":
            last = rr.latest(project, scope)
            if not last or last.get("closed_at"):
                raise ValueError("no open review round to attach a report to")
            if not argtext.wait_visible(args.from_file):
                raise ValueError("ingest needs --from <saved reviewer reply or workflow-state JSON>")
            dest = reviewguard.ingest(project, args.from_file,
                                      project / rr.BUNDLE_DIR / str(last["id"]) / "report.md")
            ids = rr.report_ids(dest.read_text(encoding="utf-8"))
            print(f"{last['id']}: report copied verbatim to {dest} ({len(ids)} numbered "
                  "finding(s)); close with --report (default)")
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
        # 1.12.0 (C6): always valid JSON - a compact per-round summary (never a truncated
        # dump), ASCII-escaped so no console code page or control character can break it.
        print(json.dumps(rr.status_summary(project, scope), indent=1, ensure_ascii=True))
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
