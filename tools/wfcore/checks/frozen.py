"""Gates that keep the settled science settled while a journal variant is adapted.

Journal requirements are presentation requirements. Before the freeze existed they were applied
by editing 07_manuscript/ in place, so picking a second journal re-edited text that review had
already closed on. These checks make that impossible: the scientific record is hashed when the
user releases S19, and every stage after it refuses to proceed if those bytes moved.
"""
from __future__ import annotations

from .. import scifreeze
from . import Ctx, Result, check


@check("scientific_freeze_captured")
def scientific_freeze_captured(ctx: Ctx) -> Result:
    """S19 close: the settled text must be hashed before a journal is allowed to influence it."""
    if not scifreeze.is_frozen(ctx.project):
        return Result(
            False,
            "scientific_freeze_captured",
            f"{scifreeze.FREEZE_REL} missing; the scientific record was never frozen",
            [".venv/Scripts/python.exe tools/manuscript/scientific_freeze.py capture",
             "Run this only once the user has said the science needs no further change. It "
             "records the exact text review closed on, so journal work cannot silently alter it."],
        )
    try:
        freeze = scifreeze.load_freeze(ctx.project)
    except SystemExit as exc:
        return Result(False, "scientific_freeze_captured", str(exc))
    entries = freeze.get("files", {})
    missing = scifreeze.uncovered_required(entries)
    if missing:
        return Result(
            False,
            "scientific_freeze_captured",
            "freeze does not cover: " + ", ".join(missing),
            ["Re-capture after the missing sources exist: scientific_freeze.py capture --force"],
        )
    ok, problems, count = scifreeze.verify_freeze(ctx.project)
    if not ok:
        return Result(
            False,
            "scientific_freeze_captured",
            "the freeze was captured but the files have already changed: " + "; ".join(problems[:4]),
            ["Either restore the frozen text, or re-capture if the change was a genuine "
             "rework: scientific_freeze.py capture --force"],
        )
    return Result(True, "scientific_freeze_captured",
                  f"{count} scientific file(s) frozen at {freeze.get('frozen_at', '?')}")


@check("scientific_freeze_intact")
def scientific_freeze_intact(ctx: Ctx) -> Result:
    """S20 onward: the frozen science has not been edited to satisfy a journal."""
    s19_done = ctx.state.status_of("S19_human_review") == "done"
    if not scifreeze.is_frozen(ctx.project):
        if s19_done:
            # S19 closed, so the freeze must exist. A missing (or deleted) freeze would
            # otherwise let every journal stage pass while editing the reviewed text.
            return Result(
                False, "scientific_freeze_intact",
                f"S19 is complete but {scifreeze.FREEZE_REL} is missing; the reviewed science "
                "is not frozen",
                ["Restore the freeze file if it was deleted. If S19 closed without one, loop to "
                 "S19 and run tools/manuscript/scientific_freeze.py capture after the user's "
                 "explicit no-further-review confirmation."])
        # Nothing frozen yet: the paper is still upstream of S19. Say so rather than
        # reporting a pass that was never tested.
        return Result(True, "scientific_freeze_intact",
                      "no scientific freeze on record; nothing to hold to (pre-S19 project)")
    ok, problems, count = scifreeze.verify_freeze(ctx.project)
    if ok and s19_done:
        binding = _approval_binding_problems(ctx)
        if binding:
            return Result(
                False, "scientific_freeze_intact", "; ".join(binding),
                ["The freeze must be the text the user released at S19. Loop to S19, present "
                 "a review round (tools/review_round.py), record the user's no-further-review "
                 "answer with review_round.py decide, then re-capture the freeze."])
    if ok:
        return Result(True, "scientific_freeze_intact",
                      f"{count} frozen scientific file(s) unchanged since review closed")
    return Result(
        False,
        "scientific_freeze_intact",
        "; ".join(problems[:6]),
        [
            "A journal requirement is never a reason to edit the frozen manuscript. Word caps, "
            f"abstract shape, reference style and statements are adapted in {scifreeze.VARIANT_DIR}/.",
            ".venv/Scripts/python.exe tools/manuscript/scientific_freeze.py verify",
            "If this really is a scientific change, it belongs to an earlier stage: route it "
            "with tools/rework.py, rebuild, and re-freeze with `capture --force`.",
        ],
    )


def _approval_binding_problems(ctx: Ctx) -> list[str]:
    """Bind the freeze to the user's explicit S19 release (as far as the record allows).

    Every freeze must sit under a NO_FURTHER_REVIEW decision. Freezes captured by 1.6.0+ also
    record the review package ID, so the decision rationale must name it and the freeze must
    not predate the decision. Older freezes carry no package ID and are held to the decision
    alone, so papers frozen before 1.6.0 keep working.
    """
    decision = ctx.state.decision("manuscript_human_reviewed")
    if not decision or decision.get("value") != "NO_FURTHER_REVIEW":
        return ["the scientific freeze is not backed by an explicit S19 "
                "manuscript_human_reviewed=NO_FURTHER_REVIEW decision"]
    try:
        freeze = scifreeze.load_freeze(ctx.project)
    except SystemExit as exc:
        return [str(exc)]
    round_id = str(freeze.get("review_round_id", ""))  # 1.8.1 subagent review rounds
    package_id = str(freeze.get("review_package_id", ""))  # legacy review ZIP (1.6.0-1.8.0)
    if not round_id and not package_id:
        return []
    token = round_id or package_id[:12]
    problems = []
    if token not in str(decision.get("rationale", "")):
        problems.append(f"the freeze is bound to S19 review {'round' if round_id else 'package'} "
                        f"{token}, which the approval decision does not name")
    if str(freeze.get("frozen_at", "")) < str(decision.get("at", "")):
        problems.append("the scientific freeze predates the current S19 approval")
    return problems


@check("journal_variant_ready")
def journal_variant_ready(ctx: Ctx) -> Result:
    """The journal-adaptation copy exists and was taken from the current freeze."""
    if not scifreeze.is_frozen(ctx.project):
        return Result(True, "journal_variant_ready",
                      "no scientific freeze on record; journal work happens in place "
                      "(pre-freeze project)")
    if not scifreeze.variant_exists(ctx.project):
        return Result(
            False,
            "journal_variant_ready",
            f"{scifreeze.VARIANT_DIR}/full_manuscript.md missing; no journal variant opened",
            ['.venv/Scripts/python.exe tools/manuscript/scientific_freeze.py open-variant '
             '--journal "<chosen journal>"',
             "This copies the frozen manuscript into the submission area. Everything the journal "
             "requires is applied to that copy."],
        )
    meta = scifreeze.variant_meta(ctx.project)
    if not meta.get("journal"):
        return Result(False, "journal_variant_ready",
                      f"{scifreeze.VARIANT_DIR}/variant.json does not name a journal",
                      ["Re-open the variant so it records which journal it is for."])
    live = scifreeze._sha256(scifreeze.freeze_path(ctx.project))
    if meta.get("freeze_sha256") and meta["freeze_sha256"] != live:
        return Result(
            False,
            "journal_variant_ready",
            "the variant was taken from a different scientific freeze than the one on disk",
            ["The manuscript was re-frozen after this variant was opened, so the variant no "
             "longer traces to the reviewed text.",
             'Re-open it: scientific_freeze.py open-variant --journal "<name>" --force'],
        )
    return Result(True, "journal_variant_ready",
                  f"variant for {meta['journal']} opened {meta.get('opened_at', '?')} "
                  f"({len(meta.get('files', []))} file(s))")


@check("variant_preserves_science")
def variant_preserves_science(ctx: Ctx) -> Result:
    """Journal adaptation may tighten prose. It may not drop a result to fit a word cap."""
    if not (scifreeze.is_frozen(ctx.project) and scifreeze.variant_exists(ctx.project)):
        return Result(True, "variant_preserves_science",
                      "no journal variant in use; nothing to compare")
    ok, problems, summary = scifreeze.variant_delta(ctx.project)
    words = "; ".join(
        f"{name} {info['words_before']}->{info['words_after']}"
        for name, info in sorted(summary.items()) if info.get("words_before"))
    if ok:
        return Result(True, "variant_preserves_science",
                      f"no numbers, citations or artifact references lost in adaptation"
                      + (f" ({words})" if words else ""))
    # A deliberate, user-authorised cut is legitimate; an unrecorded one is not.
    rec = ctx.state.decision("journal_trim_authorised")
    if rec and str(rec.get("value", "")).strip() == "YES":
        return Result(True, "variant_preserves_science",
                      f"content dropped to fit the journal, authorised by the user: "
                      f"{'; '.join(problems[:3])}",
                      )
    return Result(
        False,
        "variant_preserves_science",
        "; ".join(problems[:6]),
        [
            ".venv/Scripts/python.exe tools/manuscript/scientific_freeze.py delta",
            "Prefer tightening prose so the number survives. Fitting a word cap by deleting a "
            "result changes what the paper reports.",
            'If the user decides the cut is right: tools/wf.py decide journal_trim_authorised '
            'YES --why "<what was dropped, why it is acceptable, and where it now lives>"',
        ],
    )
