"""1.22.0 checks (a paper pinned earlier gets them after `wf migrate --yes`; `wf journal switch`
adopts the current gate set for S20-S25).

journal_traces_clean       J6 (S20, S23): after a journal switch no current journal-layer file or
                           the manuscript copy names the old journal (names, abbreviations,
                           ISSNs) or repeats its guideline quotes, cover letter or journal-
                           specific abstract sentences; each hit fails with file and line.
journal_difference_listed  J7 (S20): the journal difference list (`wf journal diff`) exists for
                           this epoch and the current target_journal.json.
guideline_requirements_mapped (v1180) gains J2 for 1.22.0: every guide sentence that refers to
                           another page for rules is ingested (--append) or marked n.a.
"""
from __future__ import annotations

from . import Ctx, Result, check

V = (1, 22, 0)


def since_1220(ctx: Ctx) -> bool:
    from ..state import pin_for, version_tuple
    try:
        return version_tuple(pin_for(ctx.state, getattr(ctx.stage, "id", None))) >= V
    except Exception:  # noqa: BLE001
        return True


def _pinned(name: str) -> Result:
    return Result(True, name, "applies from engine 1.22.0 (`wf migrate --yes` or `wf journal "
                              "switch`); paper pinned earlier")


@check("journal_traces_clean")
def journal_traces_clean(ctx: Ctx) -> Result:
    name = "journal_traces_clean"
    if not since_1220(ctx):
        return _pinned(name)
    from .. import journaldiff, journalepoch
    if journalepoch.number(ctx.project) < 2:
        return Result(True, name, "first journal epoch: nothing to compare")
    hits = journaldiff.traces(ctx.project)
    if hits:
        return Result(False, name, f"{len(hits)} trace(s) of the previous journal: "
                      + "; ".join(hits[:10]),
                      ["Rewrite each line for the new journal (journal layer only; the frozen "
                       "science is unchanged), then wf rebuild."])
    return Result(True, name, "no name, abbreviation, ISSN, guideline quote, cover-letter or "
                              "abstract sentence of an earlier journal in the journal layer")


@check("journal_difference_listed")
def journal_difference_listed(ctx: Ctx) -> Result:
    name = "journal_difference_listed"
    if not since_1220(ctx):
        return _pinned(name)
    from .. import journaldiff
    probs = journaldiff.listed_problems(ctx.project)
    if probs:
        return Result(False, name, "; ".join(probs))
    return Result(True, name, "journal difference list current (shown to the user once at S20)")
