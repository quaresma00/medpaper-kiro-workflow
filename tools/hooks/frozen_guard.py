#!/usr/bin/env python3
"""PreToolUse guard for file writes: stop an edit to a frozen or round-certified source.

A figure-layout tweak at S23 used to edit the frozen 05_figures/code script directly; the drift
only surfaced at the next S19 gate. This hook refuses the write the moment it is attempted
and names the command that opens a controlled layout round instead. Stdlib only.

Exit 2 (blocked, reason on stderr) when every condition holds:
  - the payload names a file inside the selected paper,
  - that file is frozen (scientific freeze) or certified by the newest closed revision round,
  - no open scoped round lists it in its allowed scope.
Anything else - no paper, unparseable payload, an uncertified file - exits 0 silently.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(os.environ.get("MEDPAPER_ROOT") or Path(__file__).resolve().parents[2])
sys.path.insert(0, str(ROOT / "tools"))


def _paths(payload: str) -> list[str]:
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, TypeError):
        return []
    found: list[str] = []

    def walk(node, key=""):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, k)
        elif isinstance(node, list):
            for v in node:
                walk(v, key)
        elif isinstance(node, str) and key.lower() in {"path", "file", "file_path", "filepath",
                                                       "target_file", "targetfile"}:
            found.append(node)
    walk(data)
    return found


def blocked(payload: str) -> str | None:
    try:
        from wfcore import paths, revision, scifreeze
        project = paths.project_dir(check_engine=False).resolve()
    except (Exception, SystemExit):  # noqa: BLE001 - no paper selected: nothing to guard
        return None
    rels = []
    for raw in _paths(payload):
        p = Path(raw)
        p = (p if p.is_absolute() else Path.cwd() / p).resolve()
        try:
            rels.append(p.relative_to(project).as_posix())
        except ValueError:
            continue
    if not rels:
        return None
    guarded = set(revision.certified_hashes(project))
    if scifreeze.is_frozen(project):
        try:
            guarded |= set(scifreeze.load_freeze(project).get("files", {}))
        except SystemExit:
            pass
    open_round = revision.active(project)
    sealed = revision.is_scoped(open_round) and open_round.get("status") == "active"
    allowed = set(open_round.get("allowed_files", [])) if sealed else set()
    # 1.11.0 (#2e): while a sealed round is open, ANY paper file outside its scope is refused
    # at write time (not discovered by `rework.py check` afterwards).
    outside = revision.out_of_scope(open_round, rels) if sealed else []
    if outside:
        return ("BLOCKED by the medpaper pipeline: " + ", ".join(outside[:6]) + " is outside the "
                f"open revision round {open_round.get('round_id')} (rework.py status lists the "
                "scope). Add it: python tools/rework.py batch --merge --plan <plan.json>, or edit "
                "only the listed files.")
    # 1.11.0 (#3a): in the journal stage (S20+) the frozen presentation layer (legend/footnote
    # phrasing, labels) may be edited directly; scientific_freeze_intact compares its facts.
    try:
        from wfcore.state import State
        journal_stage = State(project, ".wf").load().current >= "S20"
    except (Exception, SystemExit):  # noqa: BLE001
        journal_stage = False
    if journal_stage:
        allowed |= {r for r in rels if scifreeze.presentation_editable(project, r)}
    hits = sorted(r for r in rels if r in guarded and r not in allowed)
    if not hits:
        return None
    layout = all(r.startswith(("05_figures/", "04_tables/")) for r in hits)
    hint = ("python tools/rework.py layout " + " ".join(f"--source {r}" for r in hits)
            + ' --why "<what moves and why>"') if layout else \
        "python tools/rework.py batch --plan <plan.json> (add --merge/--priority if a round is open)"
    return ("BLOCKED by the medpaper pipeline: " + ", ".join(hits) + " is frozen or certified by a "
            "closed revision round. Open a revision round first:\n  " + hint)


def main() -> int:
    payload = "" if sys.stdin.isatty() else sys.stdin.read()
    reason = blocked(payload)
    if reason:
        print(reason, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
