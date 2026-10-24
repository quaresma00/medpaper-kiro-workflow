"""Checks that read the run state rather than the filesystem."""
from __future__ import annotations

import json

from . import Ctx, Result, check

# Visual review of a rendered artifact is expensive: the image itself enters the context.
# Two modes, selected by the `visual_review_mode` target:
#
#   "inline"    look at every artifact at the stage that renders it (S10, S11).
#   "deferred"  record DEFER at the rendering stage and discharge the whole backlog in one
#               consolidated pass at S23, once the journal is known and the figures are final.
#
# Deferring moves the obligation; it never removes it. `visual_debts_cleared` is a
# non-overridable S23 gate, so a DEFER left outstanding blocks the submission package.
VISUAL_MODES = ("inline", "deferred")
DEFER = "DEFER"
QC_REPORT = "05_figures/qc/qc_report.json"


def _visual_mode(ctx: Ctx) -> str:
    mode = str(ctx.target("visual_review_mode", "inline") or "inline").strip().lower()
    return mode if mode in VISUAL_MODES else "inline"


def parked_visual(pipeline, state, mode: str) -> list[tuple[str, str, bool]]:
    """Outstanding visual looks: (decision, stage, explicit DEFER?).

    Explicit: a recorded DEFER. Implicit (1.12.0 B2): in deferred mode a visual decision
    whose rendering stage was completed without recording anything."""
    out: list[tuple[str, str, bool]] = []
    decisions = state.data.get("decisions") or {}
    for name, rec in sorted(decisions.items()):
        if str(rec.get("value", "")).strip() == DEFER:
            out.append((name, str(rec.get("stage", "?")), True))
    if mode == "deferred":
        for st in getattr(pipeline, "stages", []):
            for g in st.gate:
                name = g.get("check") == "visual_confirmation" and g.get("name")
                if (name and name not in decisions and state.status_of(st.id) == "done"
                        and all(n != name for n, _, _ in out)):
                    out.append((name, st.id, False))
    return out


@check("decision_recorded")
def decision_recorded(ctx: Ctx) -> Result:
    name = ctx.spec["name"]
    allowed = ctx.spec.get("allowed")
    rec = ctx.state.decision(name)
    if not rec:
        hint = f".venv/Scripts/python.exe tools/wf.py decide {name} <VALUE> --why \"...\""
        if allowed:
            hint = f".venv/Scripts/python.exe tools/wf.py decide {name} {'|'.join(allowed)} --why \"...\""
        return Result(
            False,
            "decision_recorded",
            f"decision '{name}' has not been recorded",
            [hint, "The rationale is written to state and to the handoff log, so it survives a context reset."],
        )
    value = rec.get("value")
    if allowed and value not in allowed:
        return Result(
            False,
            "decision_recorded",
            f"decision '{name}' is '{value}'; this stage requires one of {allowed}",
            ["A STOP or PIVOT verdict means the pipeline should not advance. Talk to the user."],
        )
    why = (rec.get("rationale") or "").strip()
    if len(why) < 40:
        return Result(
            False,
            "decision_recorded",
            f"decision '{name}'={value} has a {len(why)}-char rationale",
            ["Record why, in enough detail that a reviewer could challenge it. At least 40 characters."],
        )
    return Result(True, "decision_recorded", f"{name} = {value} (rationale on record)")


@check("visual_confirmation")
def visual_confirmation(ctx: Ctx) -> Result:
    """`decision_recorded` for a look-at-the-render decision, with a deferral path.

    In "inline" mode this is exactly decision_recorded(allowed=["YES"]). In "deferred" mode
    DEFER is also accepted, which parks the obligation until S23 instead of discharging it
    here. The parked obligation is enforced by `visual_debts_cleared`.
    """
    name = ctx.spec["name"]
    artifact = ctx.spec.get("artifact", name.replace("_visually_confirmed", ""))
    mode = _visual_mode(ctx)
    deferrable = mode == "deferred"
    rec = ctx.state.decision(name)

    if not rec and deferrable:
        # 1.12.0 (B2): deferral is the default and needs no recorded decision. The look stays
        # owed: visual_debts_cleared (S23, non-overridable) counts this unrecorded decision.
        return Result(True, "visual_confirmation",
                      f"{name}: {artifact} look deferred to the S23 consolidated pass (default; "
                      "no decision needed - outstanding until S23)")
    if not rec:
        hints = [f'.venv/Scripts/python.exe tools/wf.py decide {name} YES --why "<per item: what you saw>"']
        if deferrable:
            hints.append(
                f'.venv/Scripts/python.exe tools/wf.py decide {name} {DEFER} '
                f'--why "<deterministic QC state, and why the look waits for S23>"'
            )
            hints.append(
                f"visual_review_mode = deferred, so DEFER is allowed here. It parks the {artifact} "
                "look until S23, where visual_debts_cleared refuses to let the package through "
                "until it is done. Deterministic QC must still be green now."
            )
        else:
            hints.append(
                "visual_review_mode = inline. To batch every look into one pass at S23 instead: "
                ".venv/Scripts/python.exe tools/wf.py config set visual_review_mode deferred"
            )
        return Result(False, "visual_confirmation", f"visual decision '{name}' has not been recorded", hints)

    value = str(rec.get("value", "")).strip()
    why = (rec.get("rationale") or "").strip()

    if value == DEFER and not deferrable:
        return Result(
            False,
            "visual_confirmation",
            f"'{name}' is {DEFER} but visual_review_mode = {mode}",
            ["Either look now and record YES, or switch the mode: "
             ".venv/Scripts/python.exe tools/wf.py config set visual_review_mode deferred"],
        )
    if value not in ("YES", DEFER):
        return Result(
            False,
            "visual_confirmation",
            f"'{name}' is '{value}'; this stage requires YES" + (f" or {DEFER}" if deferrable else ""),
            ["A visual review that found defects is not a verdict. Fix the source, re-render, then decide."],
        )
    if len(why) < 40:
        return Result(
            False,
            "visual_confirmation",
            f"'{name}'={value} has a {len(why)}-char rationale",
            ["At least 40 characters. For YES: what you saw per item. "
             f"For {DEFER}: the deterministic QC state you are relying on until S23."],
        )
    if value == DEFER:
        return Result(
            True,
            "visual_confirmation",
            f"{name} = {DEFER} - {artifact} look parked for the S23 consolidated pass "
            "(outstanding; visual_debts_cleared will block S23 until discharged)",
        )
    return Result(True, "visual_confirmation", f"{name} = YES (looked at; rationale on record)")


@check("visual_debts_cleared")
def visual_debts_cleared(ctx: Ctx) -> Result:
    """Refuse to build a submission package while any deferred visual review is outstanding.

    Two independent ledgers, because they can drift apart: the DEFER decisions in run state,
    and the per-figure `visual_reviewed` flags in the QC report. Both must be clean.
    """
    outstanding: list[str] = []

    for name, where, explicit in parked_visual(ctx.pipeline, ctx.state, _visual_mode(ctx)):
        outstanding.append(f"decision {name} is still {DEFER} (parked at {where})" if explicit
                           else f"decision {name} not recorded yet (look deferred by default at {where})")

    unseen: list[str] = []
    if ctx.p(QC_REPORT).exists():
        try:
            report = ctx.read_json(QC_REPORT)
        except json.JSONDecodeError as exc:
            return Result(False, "visual_debts_cleared", f"{QC_REPORT} invalid JSON: {exc}")
        for fig in report.get("figures", []):
            if not fig.get("visual_reviewed"):
                unseen.append(str(fig.get("id", "?")))
    if unseen:
        outstanding.append(f"never visually reviewed: {', '.join(unseen)}")

    if outstanding:
        return Result(
            False,
            "visual_debts_cleared",
            "; ".join(outstanding),
            [
                "This is the consolidated visual pass. Do it now, once, on the final renders:",
                "  .venv/Scripts/python.exe tools/figures/qc.py --contact-sheet",
                "  read_file project/05_figures/qc/contact_sheet.png     (one image, all figures)",
                "Crop in only on a panel the sheet makes you suspicious of:",
                '  .venv/Scripts/python.exe tools/figures/qc.py --crop "Figure 1" --cell B',
                "Then record what you saw:",
                '  .venv/Scripts/python.exe tools/figures/qc.py --confirm "Figure 1" --note "<what you saw>"',
                '  .venv/Scripts/python.exe tools/wf.py decide figures_visually_confirmed YES --why "<per figure>"',
                "Deferring was permission to batch the look, never permission to skip it. "
                "This gate is non-overridable.",
            ],
        )

    mode = _visual_mode(ctx)
    return Result(True, "visual_debts_cleared",
                  f"no outstanding visual reviews (visual_review_mode = {mode})")


@check("final_copy_verified")
def final_copy_verified(ctx: Ctx) -> Result:
    """1.9.0 (#24): S25 may end on the author's hand-edited upload copy, once it is checked."""
    rec = ctx.state.decision("submission_package_independent_audit") or {}
    if rec.get("value") != "PASS_AUTHOR_FINAL_COPY":
        return Result(True, "final_copy_verified", "no author final copy in use")
    from .. import finalcopy
    problems = finalcopy.verified(ctx.project)
    if problems:
        return Result(False, "final_copy_verified", "; ".join(problems),
                      ["tools/final_copy.py record --edit ... --words ...; then final_copy.py check"])
    edits = finalcopy.load(ctx.project).get("edits", [])
    return Result(True, "final_copy_verified",
                  f"author final copy accepted: {len(edits)} recorded manual edit(s); numbers, "
                  "citations and display references unchanged")
