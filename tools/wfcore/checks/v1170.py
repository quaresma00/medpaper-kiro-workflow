"""1.17.0 checks (a paper pinned earlier gets them after `wf migrate --yes`; `wf journal switch`
adopts the current gate set for S20-S25).

journal_layer_clean   J2: in a later journal epoch nothing under 08_submission/ (archives
                      excluded) predates the epoch start; the guideline snapshot, the official
                      guide date and the SCIE/JCR/integrity evidence are fresh for this epoch;
                      target_journal.json carries the epoch; the one restore question about the
                      previous journal's display/presentation changes is answered (and applied).
csl_check             J6: the CSL in use belongs to the journal (own ISSN, or the parent style
                      the vendored ISSN index gives it) or carries a recorded reason; the
                      existing render checks (tools/manuscript/csl_check.py) pass.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from . import Ctx, Result, check


def since_1170(ctx: Ctx) -> bool:
    """Stricter 1.17.0 checks reach a paper pinned earlier only after `wf migrate --yes`, or
    for S20-S25 after `wf journal switch` adopted the current gate set."""
    from ..state import pin_for, version_tuple
    try:
        return version_tuple(pin_for(ctx.state, getattr(ctx.stage, "id", None))) >= (1, 17, 0)
    except Exception:  # noqa: BLE001
        return True


def _pinned(name: str) -> Result:
    return Result(True, name, "applies from engine 1.17.0 (`wf migrate --yes` or `wf journal "
                              "switch`); paper pinned earlier")


def _json(path: Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


@check("journal_layer_clean")
def journal_layer_clean(ctx: Ctx) -> Result:
    name = "journal_layer_clean"
    if not since_1170(ctx):
        return _pinned(name)
    from .. import guideingest, journalepoch, scifreeze
    start = journalepoch.started_at(ctx.project)
    if start is None:
        return Result(True, name, "first journal of this paper; no earlier journal epoch")
    ep = journalepoch.number(ctx.project)
    root = ctx.p("08_submission")
    meta = scifreeze.variant_meta(ctx.project)
    fresh_variant = (journalepoch.seconds(meta.get("opened_at")) or 0) >= start - 1
    variant_files = {f"08_submission/manuscript/{f}" for f in meta.get("files", [])} \
        if fresh_variant else set()
    stale = []
    for p in sorted(root.rglob("*")) if root.is_dir() else []:
        rel = p.relative_to(ctx.project).as_posix()
        if not p.is_file() or rel.startswith(scifreeze.ARCHIVE_DIR + "/") or rel in variant_files:
            continue
        if p.stat().st_mtime < start - 1:
            stale.append(rel)
    problems = []
    if stale:
        problems.append(f"{len(stale)} file(s) under 08_submission/ predate journal epoch {ep}: "
                        + ", ".join(stale[:6]) + " - previous-journal residue; `wf journal "
                        "switch` archives it, otherwise regenerate the file for this journal")
    snaps = guideingest.entries(ctx.project, "guidelines", ep)
    legacy = [p for p in ctx.glob("08_submission/cache/*") if p.name != "index.json"
              and p.stat().st_mtime >= start - 1]
    if not snaps and not legacy:
        problems.append("no guideline snapshot taken in this journal epoch (wf journal lookup, or "
                        "wf guidelines ingest --from <saved page> --url <official URL>)")
    tj = _json(ctx.p("08_submission/target_journal.json"))
    start_day = start - (start % 86400)
    for key in ("guidelines_fetched_at", "scie_verified_at", "jcr_verified_at",
                "integrity_checked_at"):
        t = journalepoch.seconds(str(tj.get(key, ""))[:10])
        if t is not None and t < start_day:
            problems.append(f"{key} {tj.get(key)} predates journal epoch {ep}: verify again "
                            "with fresh evidence (an archived shortlist is only a starting point)")
    if journalepoch.current(ctx.project) and tj and tj.get("journal_epoch") != ep:
        problems.append(f"target_journal.json journal_epoch must be {ep}")
    problems += journalepoch.restore_pending(ctx.project)
    if problems:
        return Result(False, name, "; ".join(problems[:6]),
                      ["After a rejection: `wf journal switch --to ... --confirm-old ... --why ...` "
                       "archives the previous journal's layer; rebuild everything else for the new "
                       "journal from its own guide."])
    return Result(True, name, f"journal epoch {ep}: submission layer, guideline snapshot and "
                              "evidence are all from this epoch")
