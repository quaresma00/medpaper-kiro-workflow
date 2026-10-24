"""1.12.0 checks: earlier, cheap, deterministic detection (group F).

first_reader_displays   F1: what a first-time clinical reader needs from each table/figure on
                        its own - units, denominators/population, complete sentences in
                        legends/footnotes, no in-figure title when the journal forbids one;
                        at S12 also self-contained abbreviations, engineering language and
                        flow-diagram units (reused 1.11 functions, one gate line).
display_items_justified F2: every display item after the first in its group says in one line
                        what it adds that the existing items do not (artifact plan field
                        `non_redundancy`).
"""
from __future__ import annotations

import json
import re

from .. import clinical
from . import Ctx, Result, check

_SENT_END = re.compile(r"[.!?][)\]\"'”’]*\s*$")
_DENOM = re.compile(r"(?i)\b(?:n\s*=|N\s*=|denominator|number of|of all|of the|among|percentages?\s+"
                    r"(?:are|were|use|of)|patients|reports|cases|participants|subjects|"
                    r"individuals|population|cohort|events|women|men|children|adults)\b")
_UNIT_VARS = re.compile(r"(?i)^\s*(age|weight|height|body mass index|bmi|duration|follow-up|"
                        r"follow up|time to [\w-]+|dose|interval|latency|length of stay)\b")
_UNIT = re.compile(r"(?i)(,|\(|\byears?\b|\bmonths?\b|\bweeks?\b|\bdays?\b|\bhours?\b|\bkg\b|"
                   r"\bmg\b|\bml\b|\bmmol\b|\bcm\b|m2|m²|%|/)")


def _paragraphs(text: str) -> list[str]:
    body = "\n".join(ln for ln in text.splitlines()[1:] if not ln.lstrip().startswith("#"))
    return [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n", body) if p.strip()]


def _forbids_title(ctx: Ctx) -> bool:
    from .. import presentparams
    return presentparams.params(ctx.project).get("in_figure_title") is False


def _title_words(caption: str) -> str:
    first = caption.splitlines()[0] if caption else ""
    return re.sub(r"\s+", " ", first).strip(" .:")


@check("first_reader_displays")
def first_reader_displays(ctx: Ctx) -> Result:
    kinds = set(ctx.spec.get("kinds", ["table", "figure"]))
    include = set(ctx.spec.get("include", []))
    problems: list[str] = []
    no_title = _forbids_title(ctx)
    allowed = clinical.allowlist(ctx.project)
    items = [d for d in clinical.display_items(ctx.project) if d["kind"] in kinds]
    for d in items:
        cap, notes, cells, ftext = d["caption"], d["footnotes"], d["cells"], d["figure_text"]
        if not cap.strip():
            problems.append(f"{d['id']}: no legend/caption")
            continue
        for para in _paragraphs(cap) + [re.sub(r"\s+", " ", n).strip() for n in notes if n.strip()]:
            if not _SENT_END.search(para):
                problems.append(f"{d['id']}: legend/footnote sentence lacks end punctuation "
                                f"('...{para[-30:]}')")
                break
        visible = "\n".join([cap, *cells, *ftext, *notes])
        if "%" in visible and not _DENOM.search("\n".join([cap, *notes, *(cells[:1])])):
            problems.append(f"{d['id']}: percentages without a stated population or denominator "
                            "in the title or footnote")
        for c in cells:
            if _UNIT_VARS.match(c) and not _UNIT.search(c) and len(c) < 60:
                problems.append(f"{d['id']}: unit not stated for '{c.strip()[:30]}'")
                break
        if d["kind"] == "figure" and no_title and ftext:
            title = _title_words(cap).casefold()
            if any(re.match(r"(?i)^\s*fig(?:ure|\.)?\s*S?\d", t) or
                   (title and len(title.split()) >= 3 and t.strip().casefold() in title
                    and len(t.split()) >= 3) for t in ftext):
                problems.append(f"{d['id']}: in-figure title, but the journal puts titles in the "
                                "legend only")
        if "abbreviations" in include:
            used = clinical.used_abbreviations(visible)
            missing = sorted(used - clinical.defined_abbreviations("\n".join([cap, *notes, *ftext])))
            if missing:
                problems.append(f"{d['id']}: abbreviation(s) not defined locally: "
                                + ", ".join(missing[:6]))
        if "engineering" in include:
            hits = clinical.engineering_hits(visible, allowed, "display")
            if hits:
                problems.append(f"{d['id']}: engineering term '{hits[0][1]}' -> {hits[0][2]}")
        if "flow_units" in include and d["kind"] == "figure" and d.get("archetype") == "flow_diagram":
            problems += [f"{d['id']}: {p}" for p in clinical.flow_unit_problems(ftext)][:2]
    if "non_redundancy" in include:  # F2 re-checked whenever the plan changed, same line
        just = display_items_justified(ctx)
        if not just.ok:
            problems.append(just.detail)
    hints = ["Each display must read on its own: units in row labels (e.g. 'Age, years'), the "
             "population/denominator in the title or footnote, full sentences ending with a "
             "full stop, and abbreviations defined in its own footnote/legend.",
             "This is the first-clinical-reader check: a warning while drafting (S10/S11), "
             "blocking at S12."]
    if problems:
        return Result(False, "first_reader_displays", f"{len(problems)} problem(s): "
                      + "; ".join(problems[:8]), hints)
    return Result(True, "first_reader_displays",
                  f"{len(items)} display item(s) read on their own (units, denominators, "
                  "punctuation" + (", abbreviations, language, flow units" if include else "") + ")")


@check("display_items_justified")
def display_items_justified(ctx: Ctx) -> Result:
    rel = ctx.spec.get("path", "01_protocol/artifact_plan.json")
    try:
        plan = json.loads(ctx.read(rel))
    except (OSError, ValueError) as exc:
        return Result(False, "display_items_justified", f"{rel} unreadable: {exc}")
    missing = []
    for group in ("main_figures", "main_tables", "supp_figures", "supp_tables"):
        for e in (plan.get(group) or [])[1:]:
            if len(str(e.get("non_redundancy", "")).strip()) < 15:
                missing.append(str(e.get("id", "?")))
    if missing:
        return Result(False, "display_items_justified",
                      "no one-line non-redundancy justification for: " + ", ".join(missing[:8]),
                      ['Add to each such plan entry: "non_redundancy": "<what this item shows that '
                       'the existing items do not>" (>= 15 characters). A new figure or table '
                       "that repeats an existing one is merged or moved to the supplement instead."])
    return Result(True, "display_items_justified",
                  "every additional display item states what it adds")
