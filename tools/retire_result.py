#!/usr/bin/env python3
"""1.14.0 (E): retire a superseded or erroneous analysis result instead of deleting it.

    python tools/retire_result.py --file 03_analysis/results/old_model.json --why "<reason>"
    python tools/retire_result.py --file 03_analysis/code/04_old_model.py --why "<reason>"

The file moves to 03_analysis/retired/<results|code>/ and the reason is appended to
03_analysis/retired/RETIRED.md. Retired results are never number provenance (only
03_analysis/results/*.json is) and are never re-run. Valid negative or contradictory results
are NOT retired - they stay and are reported. Retire the script that wrote a result together
with it, or the reproduction re-creates the file. After the scientific freeze (S19) science
changes go through tools/rework.py instead.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wfcore import paths, scifreeze  # noqa: E402

RETIRED = "03_analysis/retired"
ALLOWED = ("03_analysis/results/", "03_analysis/code/")


def retire(project: Path, rel: str, why: str) -> Path:
    rel = rel.replace("\\", "/").lstrip("./")
    if not rel.startswith(ALLOWED) or ".." in Path(rel).parts:
        raise ValueError(f"only files under {' or '.join(ALLOWED)} can be retired")
    if len(why.strip()) < 15:
        raise ValueError("--why must say why it is superseded or erroneous (>= 15 characters); "
                         "a valid negative or contradictory result is never retired")
    if scifreeze.is_frozen(project):
        raise ValueError("the scientific record is frozen; change the analysis through "
                         "tools/rework.py (it routes the science back to S19)")
    src = project / rel
    if not src.is_file():
        raise ValueError(f"{rel} does not exist")
    dst = project / RETIRED / rel[len("03_analysis/"):]
    if dst.exists():
        dst = dst.with_name(f"{dst.stem}.{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}{dst.suffix}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    log = project / RETIRED / "RETIRED.md"
    if not log.is_file():
        log.write_text("# Retired analysis files (never number provenance, never re-run)\n\n",
                       encoding="utf-8")
    with log.open("a", encoding="utf-8") as fh:
        fh.write(f"- {datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ} {rel} -> "
                 f"{dst.relative_to(project).as_posix()}: {why.strip()}\n")
    return dst


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="retire a superseded analysis result (1.14.0)")
    ap.add_argument("--file", required=True, help="paper-relative 03_analysis/results|code file")
    ap.add_argument("--why", required=True, help="why it is superseded or erroneous")
    ap.add_argument("--project", type=Path, default=None)
    args = ap.parse_args(argv)
    project = paths.paper_from_cli(args.project)
    try:
        dst = retire(project, args.file, args.why)
    except (OSError, ValueError) as exc:
        print(f"retire refused: {exc}", file=sys.stderr)
        return 2
    print(f"retired {args.file} -> {dst.relative_to(project).as_posix()} (reason logged in "
          f"{RETIRED}/RETIRED.md); it is no longer number provenance")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
