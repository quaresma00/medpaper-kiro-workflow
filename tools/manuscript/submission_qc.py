#!/usr/bin/env python3
"""Write or check the measured SUBMISSION_CHECKLIST.md and submission_qc.md block.

    .\\.venv\\Scripts\\python.exe tools\\manuscript\\submission_qc.py write   # after every rebuild
    .\\.venv\\Scripts\\python.exe tools\\manuscript\\submission_qc.py check
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from wfcore import paths, registry, submissionqc  # noqa: E402
from wfcore.checks import Ctx  # noqa: E402
from wfcore.state import State  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="measured submission checklist")
    ap.add_argument("command", choices=["write", "check"])
    ap.add_argument("--project", type=Path, default=None)
    args = ap.parse_args()
    project = paths.paper_from_cli(args.project)
    state = State(project, ".wf").load()
    pipe = registry.load(state.config())
    ctx = Ctx(pipe, state, project, pipe.stage(state.current), {"check": "submission_checklist_measured"})
    if args.command == "write":
        from wfcore.revision import guard_outputs
        try:
            guard_outputs(project, [project / submissionqc.CHECKLIST_REL, project / submissionqc.QC_REL])
        except ValueError as exc:
            print(f"submission_qc refused: {exc}", file=sys.stderr)
            return 2
        rows = submissionqc.write(ctx)
        for r in rows:
            print(f"  [{r['status']:<4}] {r['item']}: {r['evidence'][:110]}")
        failed = [r for r in rows if r["status"] == "FAIL"]
        print(f"wrote {submissionqc.CHECKLIST_REL} and the measured block of {submissionqc.QC_REL}"
              + (f"; {len(failed)} FAIL row(s) to fix" if failed else "; all rows pass"))
        return 2 if failed else 0
    problems = submissionqc.verify(ctx)
    for p in problems:
        print(f"  - {p}")
    print("submission checklist: " + ("PASS" if not problems else "FAIL"))
    return 2 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
