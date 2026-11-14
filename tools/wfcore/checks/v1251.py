"""1.25.1 checks: the primary outcome first, unfavourable and null results reported, every
estimate with its interval, limitations present (helpers in wfcore/outcomereport.py).

prespecified_outcomes_reported  S09 (Results), S17 (Results + Abstract results): every primary
                                and secondary outcome of idea.json is reported with its interval
                                or a cited table/figure; the primary result is in the Abstract.
primary_first                   S16/S17 warn; S22 (block = true) blocks when the primary outcome
                                is null and a secondary result leads instead.
limitations_present             S16: a limitations paragraph with >= 2 specific limitations and
                                the design's essential caveat (reference/design_caveats.toml).
estimates_have_intervals        an extension of effects_with_intervals (v1100.py).

Blocking applies to papers on 1.25.1+ (`wf migrate --yes`, stages not yet completed); a paper
pinned earlier gets the same findings as warnings.
"""
from __future__ import annotations

from pathlib import Path

from . import Ctx, Result, check

SECTIONS = "07_manuscript/{}.md"


def _texts(ctx: Ctx) -> dict[str, str | None]:
    """abstract / results / discussion: the assembled manuscript (spec manuscript = true, the
    journal copy once open) or the section files."""
    from .. import crosscheck
    project = Path(ctx.project)
    if ctx.spec.get("manuscript"):
        rel, text = crosscheck.manuscript(project)
        sc = crosscheck.scopes(text)
        return {k: sc.get(k) for k in ("abstract", "results", "discussion")}
    out: dict[str, str | None] = {}
    for k in ("abstract", "results", "discussion"):
        p = project / SECTIONS.format(k)
        out[k] = p.read_text(encoding="utf-8", errors="replace") if p.is_file() else None
    return out


def _verdict(ctx: Ctx, name: str, probs: list[str], ok_detail: str, hint: list[str],
             block: bool = True) -> Result:
    from ..outcomereport import SINCE, since_1251
    if not probs:
        return Result(True, name, ok_detail)
    detail = "; ".join(probs[:6])
    if block and since_1251(ctx):
        return Result(False, name, detail, hint)
    tail = "" if not block else f" (blocks from engine {SINCE} after `wf migrate --yes`)"
    return Result(False, name, detail + tail, hint, severity="warn")


@check("prespecified_outcomes_reported")
def prespecified_outcomes_reported(ctx: Ctx) -> Result:
    from .. import outcomereport as orep
    name = "prespecified_outcomes_reported"
    t = _texts(ctx)
    if t["results"] is None:
        return Result(False, name, "07_manuscript/results.md missing")
    oc = orep.declared_outcomes(ctx.project)
    if not oc["primary"] and not oc["secondary"]:
        return Result(False, name, f"{orep.IDEA}: no outcomes.primary / outcomes.secondary - the "
                                   "pre-specified outcomes cannot be checked",
                      ["Record the primary and secondary outcomes in idea.json (S01 structure)."],
                      severity="warn")
    abstract = t["abstract"] if ctx.spec.get("abstract") else None
    probs = [m for _k, m in orep.outcome_problems(ctx.project, t["results"], abstract)]
    names = ", ".join(o["name"] for o in oc["primary"] + oc["secondary"])
    return _verdict(ctx, name, probs, f"every pre-specified outcome reported with its interval "
                                      f"or display ({names})",
                    ["Report every pre-specified outcome, favourable or not, with estimate and "
                     "95% CI (or cite the table/figure, also a supplementary one, that holds it); "
                     "the primary outcome first in the Results and in the Abstract results. "
                     "Never drop or demote a null or unfavourable outcome."])


@check("primary_first")
def primary_first(ctx: Ctx) -> Result:
    from .. import outcomereport as orep
    name = "primary_first"
    t = _texts(ctx)
    if not any(t.values()):
        return Result(True, name, "no Abstract or Discussion yet")
    probs, displaced = orep.lead_problems(ctx.project, t["abstract"], t["discussion"],
                                          t["results"] or "")
    hint = ["Lead with the main question and its answer: the primary outcome comes first in the "
            "Abstract results and in the Discussion's principal-findings paragraph, whatever its "
            "direction; a positive secondary or post hoc result never displaces a null primary "
            "result (post hoc = exploratory)."]
    if probs and displaced and ctx.spec.get("block"):
        return _verdict(ctx, name, probs, "", hint)
    if probs:
        return Result(False, name, "; ".join(probs[:4]), hint, severity="warn")
    return Result(True, name, "the primary outcome leads the Abstract results and the Discussion")


@check("limitations_present")
def limitations_present(ctx: Ctx) -> Result:
    from .. import outcomereport as orep
    name = "limitations_present"
    rel = ctx.spec.get("path", SECTIONS.format("discussion"))
    p = Path(ctx.project) / rel
    if not p.is_file():
        return Result(False, name, f"{rel} missing")
    probs = [m for _k, m in orep.limitation_problems(ctx.project, p.read_text(
        encoding="utf-8", errors="replace"))]
    key = orep.design_key(ctx.project)
    return _verdict(ctx, name, probs, f"limitations paragraph with specific items"
                                      f"{' and the ' + key.replace('_', ' ') + ' caveat' if key else ''}",
                    ["One limitations paragraph, stated plainly (no self-weakening, no "
                     "repetition), at least two specific limitations with the likely direction "
                     "of bias, and the design's essential caveat - always present."])
