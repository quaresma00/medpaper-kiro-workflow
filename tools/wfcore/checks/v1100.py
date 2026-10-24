"""1.10.0 checks: study basis, statistical reporting plan, variable crosswalk, raw spot check,
results written from final displays, argument-role coverage, library health, display plan vs
the chosen journal, figure text plan, declarations, explicit confirmation.

Every gate using these is declared with since = "1.10.0", so a paper pinned to an earlier engine
keeps its completed stages.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from . import Ctx, Result, check

CROSSWALK = "02_data/variable_crosswalk.json"
CROSSWALK_FIELDS = ("variable", "source_field", "definition", "unit", "coding", "time_window",
                    "missing_rule", "basis")
SPOT = "03_analysis/spot_check.json"
COVERAGE = "06_refs/coverage.json"
UNCITED = "06_refs/uncited_reasons.json"
REALLOC = "08_submission/display_reallocation.json"
PLAN = "01_protocol/artifact_plan.json"
ROLES = ("background", "gap", "methods", "comparison", "mechanism")
REPORTING_FIELDS = (("primary comparisons", r"\d+"), ("multiplicity", r".{3,}"),
                    ("effect measures", r".{3,}"), ("intervals", r".{3,}"))


def _json(ctx: Ctx, rel: str):
    try:
        return ctx.read_json(rel), None
    except FileNotFoundError:
        return None, f"{rel} missing"
    except (json.JSONDecodeError, OSError) as exc:
        return None, f"{rel} unreadable: {exc}"


# ---------------------------------------------------------------- item 5: study basis (S01/S03)
@check("study_basis_recorded")
def study_basis_recorded(ctx: Ctx) -> Result:
    from .. import declarations as dc
    idea, err = _json(ctx, dc.IDEA)
    if err:
        return Result(False, "study_basis_recorded", err)
    problems = dc.basis_problems(idea if isinstance(idea, dict) else {})
    if problems:
        return Result(False, "study_basis_recorded", "; ".join(problems[:6]),
                      ["Ask the user now for the study design and the data source (public "
                       "database / own-centre records / prospective collection / biospecimens / "
                       "third-party registry); ethics, consent and data availability are judged "
                       "from these later."])
    src = idea["data_source"]
    return Result(True, "study_basis_recorded",
                  f"study_design={idea['study_design']}; data_source={src.get('type')} ({src.get('name')})")


# ---------------------------------------------------- item 6: statistical reporting plan (S03/S06)
def _section(text: str, title: str) -> str | None:
    m = re.search(rf"(?mi)^(#+)\s+[^\n]*{re.escape(title)}[^\n]*$", text)
    if not m:
        return None
    level = len(m.group(1))
    rest = text[m.end():]
    nxt = re.search(rf"(?m)^#{{1,{level}}}\s", rest)
    return rest[: nxt.start()] if nxt else rest


@check("statistical_reporting_plan")
def statistical_reporting_plan(ctx: Ctx) -> Result:
    rel = ctx.spec["path"]
    if not ctx.p(rel).is_file():
        return Result(False, "statistical_reporting_plan", f"{rel} missing")
    block = _section(ctx.read(rel), "Statistical reporting plan")
    if block is None:
        return Result(False, "statistical_reporting_plan",
                      f"{rel}: no 'Statistical reporting plan' heading",
                      ["Add under the analysis plan: 'Primary comparisons: <n>', 'Multiplicity: "
                       "<method or none, why>', 'Effect measures: <OR/HR/RR/MD ...>', "
                       "'Intervals: <95% CI ...>'."])
    missing = [label for label, pat in REPORTING_FIELDS
               if not re.search(rf"(?mi)^\W*{label}\s*[:：]\s*{pat}", block)]
    if missing:
        return Result(False, "statistical_reporting_plan",
                      f"{rel}: reporting plan lacks " + ", ".join(missing))
    return Result(True, "statistical_reporting_plan",
                  f"{rel}: primary comparisons, multiplicity, effect measures and intervals stated")


_P_ONLY = re.compile(r"\b[Pp]\s*[<>=\u2264\u2265]\s*0?\.\d+")
_INTERVAL = re.compile(r"\b(?:CI|confidence interval|credible interval|IQR|SD|SE|range)\b|±|\u00b1", re.I)


@check("effects_with_intervals")
def effects_with_intervals(ctx: Ctx) -> Result:
    """Advisory: a sentence reporting a P value with no effect interval (P-value-only reporting)."""
    rel = ctx.spec["path"]
    if not ctx.p(rel).is_file():
        return Result(False, "effects_with_intervals", f"{rel} missing")
    text = re.sub(r"```.*?```", " ", ctx.read(rel), flags=re.S)
    bare = [s.strip()[:80] for s in re.split(r"(?<=[.;])\s+", text)
            if _P_ONLY.search(s) and not _INTERVAL.search(s)]
    if bare:
        return Result(False, "effects_with_intervals",
                      f"{len(bare)} sentence(s) report a P value without an effect interval: "
                      + " | ".join(bare[:3]),
                      ["Report the effect measure and interval named in the protocol's "
                       "Statistical reporting plan, then the P value."], severity="warn")
    return Result(True, "effects_with_intervals", f"{rel}: P values travel with an interval")


# ------------------------------------------------------- item 4: variable crosswalk (S04)
@check("variable_crosswalk_confirmed")
def variable_crosswalk_confirmed(ctx: Ctx) -> Result:
    data, err = _json(ctx, CROSSWALK)
    if err:
        return Result(False, "variable_crosswalk_confirmed", err,
                      ['Write {"analysis_variables": [...], "rows": [{"variable", "source_field", '
                       '"definition", "unit", "coding", "time_window", "missing_rule", "basis", '
                       '"confirmed": true}]} and confirm each row against the source documentation.'])
    wanted = [str(v) for v in (data or {}).get("analysis_variables", [])]
    rows = {str(r.get("variable", "")): r for r in (data or {}).get("rows", []) if isinstance(r, dict)}
    problems = []
    if not wanted:
        problems.append("analysis_variables is empty")
    problems += [f"{v}: no crosswalk row" for v in wanted if v not in rows]
    for v, r in rows.items():
        blank = [f for f in CROSSWALK_FIELDS if not str(r.get(f, "")).strip()]
        if blank:
            problems.append(f"{v}: empty " + ", ".join(blank))
        if r.get("confirmed") is not True:
            problems.append(f"{v}: not confirmed")
    if problems:
        return Result(False, "variable_crosswalk_confirmed", "; ".join(problems[:8]))
    return Result(True, "variable_crosswalk_confirmed",
                  f"{len(wanted)} analysis variable(s) mapped to source fields and confirmed")


# ---------------------------------------------------------- item 4: raw spot check (S06)
@check("raw_spot_check")
def raw_spot_check(ctx: Ctx) -> Result:
    data, err = _json(ctx, SPOT)
    if err:
        return Result(False, "raw_spot_check", err,
                      ["Write a script under 03_analysis/spot_check/ using "
                       "tools/analysis/spotcheck.py (sample_ids + write_spot_check) and run it "
                       "with `wf run-script`."])
    from analysis.spotcheck import K
    problems = []
    n = int(data.get("population_n", 0) or 0)
    sample = [str(x) for x in data.get("sample", [])]
    cases = data.get("cases", [])
    if n <= 0 or len(sample) != min(K, n) or len(cases) != len(sample):
        problems.append(f"need min({K}, population) cases; got {len(cases)} of population {n}")
    if "seed" not in data:
        problems.append("no seed recorded (the sample must be reproducible)")
    for case in cases:
        cid = str(case.get("id"))
        srcs = case.get("raw_source") or []
        if not srcs:
            problems.append(f"{cid}: no raw_source")
        for s in srcs:
            s = str(s)
            if s.startswith("external:"):
                continue
            if not s.replace("\\", "/").startswith("02_data/raw/") or not ctx.p(s).exists():
                problems.append(f"{cid}: raw_source {s} is not an existing file under 02_data/raw/")
        if not case.get("checks"):
            problems.append(f"{cid}: no variable compared")
        for chk in case.get("checks", []):
            if chk.get("match") is not True and len(str(chk.get("explanation", "")).strip()) < 20:
                problems.append(f"{cid}.{chk.get('variable')}: raw {chk.get('raw')!r} != derived "
                                f"{chk.get('derived')!r} without explanation")
    if problems:
        return Result(False, "raw_spot_check", "; ".join(problems[:8]),
                      ["A mismatch means the derivation or the definition is wrong: fix it at "
                       "S04/S05, or explain why the raw value legitimately differs."])
    return Result(True, "raw_spot_check",
                  f"{len(cases)} reproducible case(s) traced back to raw records; all match or explained")


# -------------------------------------------- item 1: Results written from final displays (S09)
def _ts(value) -> float | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(
            timezone.utc).timestamp()
    except (TypeError, ValueError):
        return None


@check("displays_final_for_results")
def displays_final_for_results(ctx: Ctx) -> Result:
    problems = []
    for sid, manifest in (("S10_tables", "04_tables/manifest.json"),
                          ("S11_figures", "05_figures/manifest.json")):
        if not ctx.state.is_done(sid):
            problems.append(f"{sid} is not complete")
            continue
        p = ctx.p(manifest)
        if not p.is_file():
            problems.append(f"{manifest} missing")
            continue
        done = _ts(ctx.state.stage_info(sid).get("completed_at"))
        # Only while Results are being written: a later journal re-render is presentation.
        if ctx.state.current == ctx.stage.id and done is not None and p.stat().st_mtime > done + 2:
            problems.append(f"{manifest} changed after {sid} closed (re-run {sid} first)")
    if problems:
        return Result(False, "displays_final_for_results", "; ".join(problems),
                      ["Results are written from the final tables and figures: finish S10 and "
                       "S11, then write the prose from the rendered files."])
    return Result(True, "displays_final_for_results",
                  "tables and figures are final; Results are written from them")


# ------------------------------------------------ item 8: argument roles, library health
def _library_keys(ctx: Ctx) -> set[str]:
    try:
        lib = ctx.read_json("06_refs/library.json")
    except (FileNotFoundError, json.JSONDecodeError):
        return set()
    return {str(e.get("citekey")) for e in lib.get("entries", []) if e.get("citekey")}


@check("argument_roles_covered")
def argument_roles_covered(ctx: Ctx) -> Result:
    data, err = _json(ctx, COVERAGE)
    if err:
        return Result(False, "argument_roles_covered", err,
                      ['Write {"roles": {"background": [keys], "gap": [...], "methods": [...], '
                       '"comparison": [...], "mechanism": [...]}, "not_applicable": {"role": '
                       '"reason"}}. The count is not a target; coverage is.'])
    keys = _library_keys(ctx)
    roles = data.get("roles", {}) or {}
    na = data.get("not_applicable", {}) or {}
    problems = []
    for role in ROLES:
        cited = [k for k in roles.get(role, []) if k in keys]
        unknown = [k for k in roles.get(role, []) if k not in keys]
        if unknown:
            problems.append(f"{role}: not in library: " + ", ".join(unknown[:4]))
        if not cited and len(str(na.get(role, "")).strip()) < 20:
            problems.append(f"{role}: no library entry (or a not_applicable reason >= 20 chars)")
    if problems:
        return Result(False, "argument_roles_covered", "; ".join(problems[:8]))
    return Result(True, "argument_roles_covered",
                  f"every argumentative role covered by the {len(keys)}-entry library")


@check("reference_library_health")
def reference_library_health(ctx: Ctx) -> Result:
    """S17: every library entry is cited or has a written reason; the 45-60 band only warns."""
    from .refs import citekeys
    rel = ctx.src("07_manuscript/full_manuscript.md")
    if not ctx.p(rel).is_file():
        return Result(False, "reference_library_health", f"{rel} missing")
    used = set(citekeys(ctx.read(rel)))
    supp = ctx.src("07_manuscript/supplementary_methods.md")
    if ctx.p(supp).is_file():
        used |= set(citekeys(ctx.read(supp)))
    keys = _library_keys(ctx)
    reasons = {}
    if ctx.p(UNCITED).is_file():
        try:
            reasons = ctx.read_json(UNCITED)
        except json.JSONDecodeError as exc:
            return Result(False, "reference_library_health", f"{UNCITED} invalid JSON: {exc}")
    orphan = sorted(k for k in keys - used if len(str(reasons.get(k, "")).strip()) < 15)
    if orphan:
        return Result(False, "reference_library_health",
                      f"{len(orphan)} library entr(y/ies) neither cited nor explained: "
                      + ", ".join(orphan[:8]),
                      [f'Cite it where it supports a claim, or add {{"<key>": "<why not cited>"}} '
                       f"to {UNCITED}."])
    lo, hi = int(ctx.target("reflib_min", 45)), int(ctx.target("reflib_max", 60))
    n = len(used & keys) if keys else len(used)
    if not lo <= n <= hi:
        return Result(False, "reference_library_health",
                      f"{n} distinct references cited (health band {lo}-{hi}); "
                      f"{len(keys - used)} uncited with reasons",
                      ["A health signal, not a quota: do not pad or cut to hit it."], severity="warn")
    return Result(True, "reference_library_health",
                  f"{n} distinct references cited (band {lo}-{hi}); {len(keys - used)} uncited with reasons")


# ----------------------------------------------- item 3: display count vs chosen journal (S20/S21)
@check("display_plan_fits_journal")
def display_plan_fits_journal(ctx: Ctx) -> Result:
    from .. import journalspec
    target = journalspec.load(ctx.project)
    caps, schema = journalspec.limits(target) if target else ({}, ["target_journal.json missing"])
    if schema:
        return Result(False, "display_plan_fits_journal", "; ".join(schema[:3]))
    plan, err = _json(ctx, PLAN)
    if err:
        return Result(False, "display_plan_fits_journal", err)
    figs = [str(e.get("id")) for e in plan.get("main_figures", [])]
    tabs = [str(e.get("id")) for e in plan.get("main_tables", [])]

    def over(nf: int, nt: int) -> list[str]:
        out = []
        for key, got in (("display_items", nf + nt), ("main_figures", nf), ("main_tables", nt)):
            if caps.get(key) is not None and got > caps[key]:
                out.append(f"{key} {got}/{caps[key]}")
        return out
    now = over(len(figs), len(tabs))
    if not now:
        return Result(True, "display_plan_fits_journal",
                      f"{len(figs)} main figure(s) + {len(tabs)} main table(s) fit the journal")
    moves, err = _json(ctx, REALLOC)
    hint = [f'Write {REALLOC}: {{"moves": [{{"id": "Figure 4", "to": "supplementary", '
            '"new_id": "Figure S3", "why": "..."}}]}}, then apply it (rework kind '
            "figure-layout/table-layout; facts unchanged = presentation)."]
    if err:
        return Result(False, "display_plan_fits_journal",
                      "over the journal's display limit without a reallocation plan: " + "; ".join(now), hint)
    moved = {str(m.get("id")) for m in moves.get("moves", [])
             if m.get("to") == "supplementary" and str(m.get("why", "")).strip()}
    unknown = sorted(moved - set(figs) - set(tabs))
    left = over(len([f for f in figs if f not in moved]), len([t for t in tabs if t not in moved]))
    if unknown or left:
        return Result(False, "display_plan_fits_journal",
                      "reallocation plan does not fit: " + "; ".join(
                          (["unknown id(s) " + ", ".join(unknown)] if unknown else []) + left), hint)
    return Result(True, "display_plan_fits_journal",
                  f"over the limit ({'; '.join(now)}); reallocation plan moves {len(moved)} item(s) "
                  "to the supplement")


# ------------------------------------------------------ item 10: figure text plan (S07)
@check("figure_text_planned")
def figure_text_planned(ctx: Ctx) -> Result:
    plan, err = _json(ctx, PLAN)
    if err:
        return Result(False, "figure_text_planned", err)
    problems = []
    for group in ("main_figures", "supp_figures"):
        for e in plan.get(group, []):
            tp = e.get("text_plan")
            if not isinstance(tp, dict) or not str(tp.get("in_figure", "")).strip() \
                    or not str(tp.get("legend", "")).strip():
                problems.append(str(e.get("id")))
    if problems:
        return Result(False, "figure_text_planned",
                      "no text_plan {in_figure, legend} for: " + ", ".join(problems[:8]),
                      ['Per figure: "text_plan": {"in_figure": "axis titles, units, group labels, '
                       'n at risk (or none)", "legend": "what the legend must explain"}.'])
    return Result(True, "figure_text_planned", "in-figure text and legend planned together per figure")


# ------------------------------------------------------- item 5: declarations (S21)
@check("declarations_assessed")
def declarations_assessed(ctx: Ctx) -> Result:
    from .. import declarations as dc
    data = dc.load(ctx.project)
    if not data:
        return Result(False, "declarations_assessed", f"{dc.REL} missing",
                      ["Run tools/declarations.py assess; ask the author only the printed questions."])
    problems = []
    if data.get("idea_sha256") != dc.idea_sha256(ctx.project):
        problems.append("idea.json changed after the assessment (re-run assess)")
    open_q = dc.pending(data)
    if open_q:
        problems.append("open author question(s): " + ", ".join(q["id"] for q in open_q))
    rel = ctx.src("07_manuscript/statements.md")
    text = ctx.read(rel) if ctx.p(rel).is_file() else ""
    low = text.casefold()
    if "ethic" not in low:
        problems.append(f"{rel}: no ethics statement")
    if "data availab" not in low and "availability of data" not in low:
        problems.append(f"{rel}: no data availability statement")
    for qid, ans in (data.get("answers") or {}).items():
        value = str((ans or {}).get("value", "")).strip()
        if qid in ("ethics_committee_and_number", "registry_approval") and value \
                and value.casefold() not in low:
            problems.append(f"{rel}: the author's {qid} answer is not in the statement")
    if problems:
        return Result(False, "declarations_assessed", "; ".join(problems[:6]))
    return Result(True, "declarations_assessed",
                  "ethics, consent and data availability judged from design/source; author asked "
                  f"{len(data.get('questions', []))} specific point(s)")


# --------------------------------------------------- item 13: explicit confirmation (S19/S24)
@check("explicit_confirmation")
def explicit_confirmation(ctx: Ctx) -> Result:
    from .. import reviewrounds as rr
    scope = ctx.spec.get("scope", "manuscript")
    rnd = rr.approved_round(ctx.project, scope)
    if rnd is None:
        return Result(False, "explicit_confirmation", f"no confirmed {scope} round",
                      [f"Ask the user to state exactly: {rr.CONFIRM_PHRASES[0]} "
                       f"(or '{rr.CONFIRM_PHRASES[1]}')."])
    problems = []
    if not rr.is_confirmation(rnd.get("user_words", "")):
        problems.append(f"{rnd['id']}: recorded words are not the explicit confirmation sentence")
    current = rr.inputs(ctx.project, scope)
    version = rr.version_id(current)
    if not rnd.get("confirmed_version"):
        problems.append(f"{rnd['id']}: no confirmed version id recorded")
    elif rnd["confirmed_version"] != version:
        # A later presentation delta (facts unchanged, 1.9.0) does not void the confirmation.
        drift = rr._changed_since(rnd, current, ctx.project)
        if drift:
            problems.append(f"{rnd['id']}: confirmed version {rnd['confirmed_version'][:12]} "
                            "differs from the current files: " + ", ".join(drift[:4]))
    if problems:
        return Result(False, "explicit_confirmation", "; ".join(problems),
                      [f"Show the user the current version and ask for: {rr.CONFIRM_PHRASES[0]}"])
    return Result(True, "explicit_confirmation",
                  f"{rnd['id']}: user stated '{rnd['user_words']}' for version {version[:12]}")
