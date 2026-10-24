#!/usr/bin/env python3
"""Author's final manual edits on the upload copy (1.9.0): record the edits, then check them.

    .\\.venv\\Scripts\\python.exe tools/final_copy.py record --edit "Renamed Methods heading" \\
        --edit "Keywords separated by semicolons" --words "<the author's authorisation>"
    .\\.venv\\Scripts\\python.exe tools/final_copy.py check
    .\\.venv\\Scripts\\python.exe tools/wf.py decide submission_package_independent_audit \\
        PASS_AUTHOR_FINAL_COPY --why "<audit verdict + final-copy check passed>"

See tools/wfcore/finalcopy.py for what is compared.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wfcore import finalcopy, paths  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="author final-copy end state")
    ap.add_argument("command", choices=("record", "check", "status"))
    ap.add_argument("--edit", action="append", default=[], help="one manual edit (repeatable)")
    ap.add_argument("--words", default="", help="the author's authorisation, verbatim")
    ap.add_argument("--words-file", help="UTF-8 file holding --words (avoids shell code pages)")
    ap.add_argument("--words-b64", help="base64 of the UTF-8 --words text")
    ap.add_argument("--project", type=Path, default=None)
    from wfcore import argtext  # 1.12.0 (C1): --words-file/--words-b64, mojibake repaired
    args = ap.parse_args(argtext.fix_argv(sys.argv[1:] if argv is None else argv))
    project = paths.paper_from_cli(args.project)
    try:
        if args.command == "record":
            argtext.verify(args.words, "--words")
            data = finalcopy.record(project, args.edit, args.words)
            print(f"recorded {len(data['edits'])} manual edit(s); now run: final_copy.py check")
            return 0
        if args.command == "status":
            data = finalcopy.load(project)
            for e in data.get("edits", []):
                print(f"- {e}")
            chk = data.get("check") or {}
            print(f"check: {'PASS' if chk.get('ok') else 'not passed'} {chk.get('at', '')}")
            return 0
        ok, problems = finalcopy.check(project)
    except ValueError as exc:
        print(f"final_copy: {exc}", file=sys.stderr)
        return 2
    for p in problems:
        print(f"  FAIL {p}")
    print("final copy: PASS - numbers, citations and display references unchanged; blinding OK"
          if ok else f"final copy: {len(problems)} problem(s)")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
