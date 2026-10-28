"""1.13.0 checks.

engine_fork_recorded   G1: a paper that runs a project-local engine fork keeps its diff against
                       the base current (.wf/engine_fork.diff) so the maintainer can upstream
                       it; shown at S25 (warning, never blocking).
"""
from __future__ import annotations

from . import Ctx, Result, check


@check("engine_fork_recorded")
def engine_fork_recorded(ctx: Ctx) -> Result:
    from .. import enginefork
    info = enginefork.info(ctx.project)
    if not info:
        return Result(True, "engine_fork_recorded", "no engine fork (the paper uses the global "
                                                    "engine read-only)")
    changes = enginefork.changed_files(ctx.project)
    diff = ctx.project / enginefork.DIFF_REL
    text = diff.read_text(encoding="utf-8", errors="replace") if diff.is_file() else ""
    stale = [rel for _s, rel in changes if f"b/{rel}" not in text and f"a/{rel}" not in text]
    if not diff.is_file() or stale:
        return Result(False, "engine_fork_recorded",
                      f"engine fork with {len(changes)} changed file(s); diff not recorded for: "
                      + ", ".join(stale[:5] or ["(no .wf/engine_fork.diff)"]),
                      ["Run `wf engine-fork diff` and give .wf/engine_fork.diff to the engine "
                       "maintainer (it is the only way the fix reaches other papers)."],
                      severity="warn")
    return Result(True, "engine_fork_recorded",
                  f"engine fork of {info.get('base_version')}: {len(changes)} changed file(s), "
                  "diff recorded in .wf/engine_fork.diff for the maintainer")
