"""1.25.0 checks (a paper pinned earlier gets the stricter parts after `wf migrate --yes`; stages
not yet completed then follow them).

display_plan_benchmarked     A4 (S07, in v1230.py): since 1.25.0 the benchmark is the 5-10 most
                             recent comparable papers from a dated search log (displaybench).
cross_section_consistent     B3 (S17 warn, S22): the cross-section report (crosscheck.py). A
                             redefined abbreviation, one used before its definition, or an
                             abstract number that is not a value in the Results text or tables
                             blocks at S22 for papers on 1.25.0+; everything else warns.
changed_paragraphs_polished  B2 (S22, S23): every prose paragraph of the assembled manuscript /
                             journal copy changed since its last polished receipt has been
                             through the medical editor (writer_bundle.py edit --section
                             manuscript); unchanged paragraphs are never sent again.
polish_log_headings          B1 (inside polish_complete): the S22 log records cross-section fixes,
                             journal adaptation, re-polished paragraphs, cuts and tier-B phrases
                             kept - no second full polish. Old headings stay valid for pinned papers.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import Ctx, Result, check

V = (1, 25, 0)
SINCE = "1.25.0"
LOG_HEADINGS = ("Cross-section consistency fixes", "Journal adaptation",
                "Re-polished paragraphs (editor receipts)", "Cut to meet journal limits",
                "Tier-B phrases kept")


def since_1250(ctx: Ctx) -> bool:
    from ..state import pin_for, version_tuple
    try:
        return version_tuple(pin_for(ctx.state, getattr(ctx.stage, "id", None))) >= V
    except Exception:  # noqa: BLE001
        return True


def since_1250_project(project: Path | None, stage: str | None = None) -> bool:
    """A paper created on 1.25.0+, migrated, or after a journal switch for S20-S25."""
    from ..state import version_tuple
    if project is None:
        return True
    try:
        st = json.loads((Path(project) / ".wf/state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return True
    if not isinstance(st, dict):
        return True
    pin = version_tuple(str(st.get("engine_pin") or st.get("pipeline_version") or "0"))
    jp = st.get("journal_gate_pin") or {}
    if stage and stage in (jp.get("stages") or []):
        pin = max(pin, version_tuple(str(jp.get("version", "0"))))
    return pin >= V


def _pinned(name: str) -> Result:
    return Result(True, name, f"applies from engine {SINCE} (`wf migrate --yes`); paper pinned "
                              "earlier")


@check("cross_section_consistent")
def cross_section_consistent(ctx: Ctx) -> Result:
    name = "cross_section_consistent"
    from .. import crosscheck
    try:
        data = crosscheck.report(ctx.project, write=False)
    except Exception as exc:  # noqa: BLE001
        return Result(False, name, f"cross-section report failed: {exc}", severity="warn")
    hint = ["`polish.py crosscheck` prints the report; fix only the paragraphs concerned and send "
            "the changed paragraphs to the medical editor (writer_bundle.py edit --section "
            "manuscript). The 'for the reviewer' items reach the S18 brief by themselves."]
    block = bool(ctx.spec.get("block")) and since_1250(ctx)
    n_rev = len(data["for_reviewer"])
    if data["blocking"] and block:
        return Result(False, name, f"{len(data['blocking'])} cross-section error(s): " + "; ".join(
            x["detail"] for x in data["blocking"][:5]), hint)
    items = data["blocking"] + data["warnings"]
    if items:
        return Result(False, name, f"{len(items)} cross-section finding(s): " + "; ".join(
            f"{x['kind']}: {x['detail']}" for x in items[:5]), hint, severity="warn")
    return Result(True, name, "terminology, abbreviations, near-duplicate sentences, abstract "
                              f"numbers and style consistent across sections; {n_rev} item(s) "
                              "for the reviewer")


@check("changed_paragraphs_polished")
def changed_paragraphs_polished(ctx: Ctx) -> Result:
    name = "changed_paragraphs_polished"
    if not since_1250(ctx):
        return _pinned(name)
    from .. import sectionpolish as sp
    rel = sp.manuscript_rel(ctx.project)
    if not (Path(ctx.project) / rel).is_file():
        return Result(True, name, f"{rel} not assembled yet")
    ch = sp.manuscript_changed(ctx.project)
    _known, basis = sp.polished_hashes(ctx.project)
    if ch:
        return Result(False, name, f"{rel}: {len(ch)} paragraph(s) changed after assembly without "
                                   f"an editor receipt (paragraph {', '.join(map(str, ch[:12]))}"
                                   f"{', ...' if len(ch) > 12 else ''}; baseline: {basis})",
                      ["writer_bundle.py edit --section manuscript (only these paragraphs go to "
                       "medpaper-medical-editor), then writer_bundle.py polished --section "
                       "manuscript. Unchanged paragraphs are never sent again."])
    return Result(True, name, f"{rel}: every paragraph changed after assembly has an editor "
                              f"receipt (baseline: {basis})")


def polish_log_problems(ctx: Ctx) -> list[str]:
    """B1: the 1.25.0 polish_log headings (pinned papers keep the old ones)."""
    if not since_1250(ctx):
        return []
    rel = ctx.src("07_manuscript/polish_log.md")
    p = ctx.p(rel)
    if not p.is_file():
        return [f"{rel} missing (headings: {'; '.join(LOG_HEADINGS)})"]
    text = p.read_text(encoding="utf-8", errors="replace")
    heads = {re.sub(r"\s+", " ", m.group(1)).strip().casefold()
             for m in re.finditer(r"(?m)^#{1,6}\s+(.+?)\s*$", text)}
    miss = [h for h in LOG_HEADINGS if h.casefold() not in heads]
    return [f"{rel} lacks heading(s): {'; '.join(miss)}"] if miss else []
