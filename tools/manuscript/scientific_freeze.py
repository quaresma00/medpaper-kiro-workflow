#!/usr/bin/env python3
r"""Freeze the settled scientific manuscript, and open/inspect the journal variant.

    # S19 close, once the user says the science needs no further change
    .\.venv\Scripts\python.exe tools\manuscript\scientific_freeze.py capture

    # S20, once the journal is chosen
    .\.venv\Scripts\python.exe tools\manuscript\scientific_freeze.py open-variant --journal "Endoscopy"

    # any time: has the frozen science drifted?
    .\.venv\Scripts\python.exe tools\manuscript\scientific_freeze.py verify

    # S22/S23: what did journal adaptation change?
    .\.venv\Scripts\python.exe tools\manuscript\scientific_freeze.py delta
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wfcore import scifreeze  # noqa: E402


def project_root() -> Path:
    env = os.environ.get("MEDPAPER_PROJECT")
    if env:
        return Path(env)
    repo = Path(__file__).resolve().parents[2]
    return repo / "project"


def main() -> int:
    ap = argparse.ArgumentParser(description="scientific freeze and journal variant")
    ap.add_argument("command",
                    choices=("capture", "verify", "open-variant", "delta", "show"))
    ap.add_argument("--journal", default="", help="target journal, for open-variant")
    ap.add_argument("--force", action="store_true",
                    help="re-freeze after a genuine rework, or replace an existing variant")
    args = ap.parse_args()
    proj = project_root()

    if args.command == "capture":
        path = scifreeze.write_freeze(proj, force=args.force)
        freeze = scifreeze.load_freeze(proj)
        print(f"scientific record frozen: {scifreeze.FREEZE_REL}")
        for rel in sorted(freeze["files"]):
            print(f"  {rel}")
        print(f"\n{len(freeze['files'])} file(s) frozen at {freeze['frozen_at']}.")
        print("Journal requirements are now applied to a copy, never to these files:")
        print(f"  tools/manuscript/scientific_freeze.py open-variant --journal \"<name>\"")
        _ = path
        return 0

    if args.command == "verify":
        ok, problems, count = scifreeze.verify_freeze(proj)
        if ok:
            print(f"all {count} frozen scientific file(s) unchanged since review closed")
            return 0
        print(f"{len(problems)} frozen scientific file(s) changed:")
        for p in problems:
            print(f"  {p}")
        print("\nA journal requirement is never a reason to edit these. Adapt the variant:")
        print(f"  {scifreeze.VARIANT_DIR}/")
        print("A genuine scientific change routes through tools/rework.py to its owning stage.")
        return 2

    if args.command == "open-variant":
        if not args.journal.strip():
            raise SystemExit("--journal is required: the variant records which journal it is for")
        dest, copied = scifreeze.open_variant(proj, args.journal.strip(), force=args.force)
        print(f"journal variant opened for {args.journal.strip()}: {scifreeze.VARIANT_DIR}/")
        for name in copied:
            print(f"  {name}")
        print("\nAdapt these for the journal. S21 writes the title page and statements here,")
        print("S22 polishes here, S23 renders these to DOCX. 07_manuscript/ stays frozen.")
        _ = dest
        return 0

    if args.command == "delta":
        ok, problems, summary = scifreeze.variant_delta(proj)
        meta = scifreeze.variant_meta(proj)
        if meta:
            print(f"variant for: {meta.get('journal', '?')}  (opened {meta.get('opened_at', '?')})")
        for name, info in sorted(summary.items()):
            if info.get("origin"):
                print(f"  {name:<28} {info['words_after']} words ({info['origin']})")
                continue
            print(f"  {name:<28} {info['words_before']} -> {info['words_after']} words "
                  f"({info['words_delta']:+d})")
            for field in ("numbers", "citekeys", "artifacts"):
                if info.get(f"{field}_lost"):
                    print(f"      {field} LOST: {info[f'{field}_lost']}")
        if ok:
            print("\nno numbers, citations or artifact references were lost in adaptation")
            return 0
        print(f"\n{len(problems)} problem(s): content was dropped, not just tightened.")
        print("Dropping a result to fit a word cap is a scientific decision. Either restore it")
        print("and tighten prose instead, or get the user's explicit authorisation and record it:")
        print('  tools/wf.py decide journal_trim_authorised YES --why "<what was dropped and why>"')
        return 2

    freeze = scifreeze.load_freeze(proj) if scifreeze.is_frozen(proj) else {}
    print(f"frozen        {'yes' if freeze else 'no'}")
    if freeze:
        print(f"frozen_at     {freeze.get('frozen_at')}")
        print(f"files         {len(freeze.get('files', {}))}")
    meta = scifreeze.variant_meta(proj)
    print(f"variant       {meta.get('journal') if meta else 'not opened'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
