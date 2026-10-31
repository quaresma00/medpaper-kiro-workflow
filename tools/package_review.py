#!/usr/bin/env python3
"""Freeze or verify the submission package approved for independent review."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wfcore import paths as wfpaths  # noqa: E402
from wfcore.packagefreeze import FREEZE_REL, verify_freeze, write_freeze  # noqa: E402

FREEZE_RE_REL = Path(FREEZE_REL).as_posix()


def main() -> int:
    parser = argparse.ArgumentParser(description="freeze and verify final submission-review inputs")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("freeze", "verify", "reader-copies", "audit-start", "audit-save"):
        command = sub.add_parser(name)
        command.add_argument("--project", type=Path, default=None)
        command.add_argument("--freeze", type=Path)
        command.add_argument("--from", dest="from_file", type=Path, default=None,
                             help="audit-save: the reviewer's saved reply / workflow-state JSON")
    args = parser.parse_args()
    project = wfpaths.paper_from_cli(args.project)
    if args.command in ("audit-start", "audit-save"):
        # 1.15.0 (E4): full first audit, then re-audits of the previous findings + new BLOCKING.
        from wfcore import audit
        try:
            if args.command == "audit-save":
                dest = audit.save(project, args.from_file)
                print(f"saved the reviewer's report verbatim -> {dest}")
                return 0
            ok, problems, _count = verify_freeze(project, project / Path(FREEZE_RE_REL))
            if not ok:
                raise ValueError("the package changed after the user's confirmation; return to "
                                 "S24: " + "; ".join(problems[:4]))
            import json
            manifest = json.loads((project / "08_submission/bundle/manifest.json")
                                  .read_text(encoding="utf-8"))
            from wfcore.readerreview import write_text_copies
            copies = write_text_copies(project, [str(i.get("file", "")) for i in manifest.get("items", [])])
            files = [FREEZE_RE_REL, *[str(i.get("file", "")) for i in manifest.get("items", [])],
                     "08_submission/target_journal.json", "08_submission/guidelines_extract.md",
                     "08_submission/bundle/manifest.json", "08_submission/bundle/SUBMISSION_CHECKLIST.md",
                     "08_submission/submission_qc.md", *copies]
            out, mode = audit.start(project, list(dict.fromkeys(files)))
        except (OSError, ValueError) as exc:
            print(f"package review error: {exc}", file=sys.stderr)
            return 2
        print(f"S25 audit bundle ({mode}): pass the medpaper-reviewer agent this ONE path and "
              f"nothing else:\n  {out / 'MANIFEST.md'}")
        print(f"It writes {out / 'report.md'}; then run package_review.py audit-save (or "
              "audit-save --from <saved reply> when it could not write).")
        return 0
    if args.command == "reader-copies":
        # S25: read-only auditors get hash-bound text copies of every DOCX/XLSX upload.
        import json
        from wfcore.readerreview import write_text_copies
        try:
            manifest = json.loads((project / "08_submission/bundle/manifest.json")
                                  .read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"package review error: {exc}", file=sys.stderr)
            return 2
        for rel in write_text_copies(project, [str(i.get("file", "")) for i in manifest.get("items", [])]):
            print(project / rel)
        return 0
    try:
        freeze = (wfpaths.output_within(project, args.freeze) if args.freeze
                  else project / Path(FREEZE_REL))
    except ValueError as exc:
        print(f"package review error: {exc}", file=sys.stderr)
        return 2
    try:
        if args.command == "freeze":
            output = write_freeze(project, freeze)
            ok, problems, count = verify_freeze(project, output)
            if not ok:
                raise ValueError("; ".join(problems))
            print(f"froze {count} final-review file(s) -> {output}")
            return 0
        ok, problems, count = verify_freeze(project, freeze)
        if not ok:
            print("submission package changed after user confirmation:", file=sys.stderr)
            for problem in problems:
                print(f"  - {problem}", file=sys.stderr)
            return 2
        print(f"verified {count} frozen final-review file(s); no changes detected")
        return 0
    except (OSError, ValueError) as exc:
        print(f"package review error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
