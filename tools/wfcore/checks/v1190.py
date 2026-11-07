"""1.19.0 checks (a paper pinned earlier gets them after `wf migrate --yes`; `wf journal switch`
adopts the current gate set for S20-S25).

layout_from_guideline   M1/M2/M4 (S23): title-page, figure and table placement and the
                        supplementary naming pattern come from typed fields; a non-default
                        value needs a guideline requirement (quote + lines); the manifest, the
                        file names and the cover letter follow the decisions.
discussion_outline_ready M3 (S16): the writer's outline (.wf/writer/discussion_outline.md) has
                        the six labels, <= 200 words, and every key finding is compared with a
                        verified study (or states that none exists).
The Discussion checks themselves run inside section_language_clean (discussion_checks = true).
"""
from __future__ import annotations

from . import Ctx, Result, check


def _pinned(name: str) -> Result:
    return Result(True, name, "applies from engine 1.19.0 (`wf migrate --yes` or `wf journal "
                              "switch`); paper pinned earlier")


@check("layout_from_guideline")
def layout_from_guideline(ctx: Ctx) -> Result:
    from .. import journalspec, layout
    name = "layout_from_guideline"
    target = journalspec.load(ctx.project)
    if not layout.since_1190(ctx) and not layout.applies(ctx.project, target):
        return _pinned(name)
    probs = layout.problems(ctx.project)
    if probs:
        return Result(False, name, "; ".join(probs[:6]),
                      ["Placement and file names follow target_journal.json typed fields "
                       "(title_page.placement, figures.placement, tables.placement, "
                       "supplementary_file_pattern) or the engine defaults; `wf compliance "
                       "layout` shows each decision and its basis; then `wf rebuild`."])
    rows = layout.decisions(ctx.project)
    return Result(True, name, "; ".join(f"{r['item']}={r['value'] or '-'}" for r in rows))


@check("discussion_outline_ready")
def discussion_outline_ready(ctx: Ctx) -> Result:
    from .. import discussion, layout
    name = "discussion_outline_ready"
    if not layout.since_1190(ctx):
        return _pinned(name)
    probs = discussion.outline_problems(ctx.project)
    if probs:
        return Result(False, name, "; ".join(probs[:6]),
                      ["The medpaper-clinical-writer writes the outline first (labels: "
                       + "; ".join(discussion.LABELS) + "), each key finding F1, F2 ... with a "
                       "verified citekey in the comparison part or 'no prior study'; it is a "
                       "working file, never exported."])
    return Result(True, name, f"{discussion.OUTLINE}: six labels, every key finding compared")
