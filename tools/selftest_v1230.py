"""1.23.0 regression tests: science quality and medical readability before writing.

S1 publishability checkpoints, S2 display benchmark, S3 science review before writing, S4
full-text cascade, S5 per-section medical polish, S6 self-verified public facts and data
availability, S7 units of derived variables, S8 multiple-imputation pooling; release policy.
Synthetic fixtures only - no real paper, dataset, network or browser is used (HTTP mocked).
Called from tools/selftest.py.
"""
from __future__ import annotations

import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from selftest_v1140 import _env, _gate, _out, _paper, _run, _w  # noqa: E402,F401


def run(tmp: Path, record, section, only: str = "") -> None:
    tmp.mkdir(parents=True, exist_ok=True)
    for name, fn in GROUPS:
        if not only or name in only.split():
            fn(tmp / name, record, section)


def _pin(p: Path, version: str) -> None:
    st = json.loads((p / ".wf/state.json").read_text(encoding="utf-8"))
    st["engine_pin"] = version
    (p / ".wf/state.json").write_text(json.dumps(st), encoding="utf-8")


S02_EVIDENCE = {"novelty": {"query": "drug X AND hepatotoxicity AND FAERS", "count": 2, "years": 10,
                            "closest": [{"pmid": "11111111", "title": "Drug X liver injury in FAERS",
                                         "year": 2021}]},
                "data_sufficiency": "FAERS holds several hundred drug X reports with liver events.",
                "contribution": "First analysis by indication and time to onset for drug X."}


# ------------------------------------------------------------------------------ S1
def run_pub(tmp: Path, record, section) -> None:
    from wfcore import publishability as pb
    section("1.23.0 S1: publishability checkpoints at S02/S04/S06, one line before extra analyses")
    p = _paper(tmp / "p", "S02_feasibility")
    _w(p, "temp/ev.json", S02_EVIDENCE)
    rec = _run(p, "tools/wf.py", "publishability", "record", "--stage", "S02", "--verdict", "GO",
               "--article-type", "original_article", "--evidence", p / "temp/ev.json")
    g = _gate(p, "publishability_checkpoint", "S02_feasibility")
    record("S1 S02 GO: the Chinese lines are printed at once (count, closest paper, no question) "
           "and the gate passes", rec.returncode == 0 and "可发表性检查（S02）：GO" in _out(rec)
           and "近 10 年同类研究 2 篇" in _out(rec) and "不需要您回复" in _out(rec) and g.ok,
           _out(rec)[-500:] + g.detail)
    bad = _run(p, "tools/wf.py", "publishability", "record", "--stage", "S02", "--verdict", "GO",
               "--article-type", "original_article")
    record("S1 a checkpoint without evidence is refused (novelty search, sufficiency, contribution)",
           bad.returncode == 2 and "novelty.query" in _out(bad), _out(bad)[-300:])
    q = _paper(tmp / "q", "S04_data")
    _w(q, "03_analysis/results/dataset_summary.json", {"n_rows": 500})
    low = _run(q, "tools/wf.py", "publishability", "record", "--stage", "S04", "--verdict", "GO",
               "--article-type", "original_article", "--design", "disproportionality",
               "--count", "cases_per_drug_event_pair_min=2", "--count", "cases_per_subgroup_min=5")
    cond = _run(q, "tools/wf.py", "publishability", "record", "--stage", "S04", "--verdict",
                "CONDITIONAL", "--article-type", "brief_report", "--design", "disproportionality",
                "--count", "cases_per_drug_event_pair_min=2", "--count", "cases_per_subgroup_min=5")
    g1 = _gate(q, "publishability_checkpoint", "S04_data")
    record("S1 S04: a GO below the design floor is refused; CONDITIONAL asks ONE question with a "
           "recommendation and blocks until the user answers",
           low.returncode == 2 and "cases_per_drug_event_pair_min 2 < 3" in _out(low)
           and cond.returncode == 0 and "请您选一项" in _out(cond) and "我的建议：调整角度或文章类型" in _out(cond)
           and not g1.ok and "ask the user ONE question" in g1.detail, _out(low)[-300:] + _out(cond)[-400:])
    ans = _run(q, "tools/wf.py", "publishability", "answer", "--stage", "S04", "--choice", "continue",
               "--words", "按简报继续")
    g2 = _gate(q, "publishability_checkpoint", "S04_data")
    _w(q, "03_analysis/results/dataset_summary.json", {"n_rows": 501})
    g3 = _gate(q, "publishability_checkpoint", "S04_data")
    record("S1 the user's answer releases the checkpoint; a changed dataset summary makes it stale",
           ans.returncode == 0 and g2.ok and not g3.ok and "stale" in g3.detail, g2.detail + g3.detail)
    s = _paper(tmp / "s", "S06_protocol_final")
    _w(s, "03_analysis/results/primary.json", {"or": 1.1})
    pb.record(s, "S06", "NO-GO", "not_publishable",
              {"precision": "CI 0.5 to 2.6, far too wide to inform practice.",
               "duplication": "Three larger studies already report the same null finding.",
               "robustness": "Sensitivity analyses reverse the direction of the estimate."})
    pb.answer(s, "S06", "stop", "停止")
    g4 = _gate(s, "publishability_checkpoint", "S06_protocol_final")
    old = _paper(tmp / "old", "S06_protocol_final")
    _pin(old, "1.22.0")
    g5 = _gate(old, "publishability_checkpoint", "S06_protocol_final")
    record("S1 NO-GO + the user's 'stop' blocks the stage; a paper pinned to 1.22.0 is not judged",
           not g4.ok and "chose to stop" in g4.detail and g5.ok and "pinned earlier" in g5.detail,
           g4.detail + g5.detail)
    v = _run(s, "tools/wf.py", "publishability", "value", "--analysis", "E-value sensitivity",
             "--could-change", "whether residual confounding explains the signal", "--cost",
             "1 script, 20 min", "--benefit", "low")
    _w(s, "03_analysis/analysis_manifest.json", {"scripts": [
        {"path": "03_analysis/code/09_extra.py", "role": "additional",
         "decision": "whether residual confounding explains the signal", "cost": "20 min",
         "benefit": "low"}]})
    g6 = _gate(s, "additional_analyses_justified", "S05_analysis")
    record("S1 before an extra analysis one Chinese line names the conclusion it could change and "
           "its cost, and recommends skipping a low-benefit one (unless requested)",
           v.returncode == 0 and "可能改变的结论" in _out(v) and "建议跳过" in _out(v) and not g6.ok
           and "low benefit" in g6.detail, _out(v)[-300:] + g6.detail)


# ------------------------------------------------------------------------------ S7
def run_units(tmp: Path, record, section) -> None:
    from analysis import units
    section("1.23.0 S7: units and plausibility of derived variables")
    mgkg, unit = units.per_body_weight([700.0, 1400.0], "mg/day", [70.0, 70.0])
    try:
        units.per_body_weight(mgkg, unit, [70.0, 70.0])
        double = "accepted"
    except units.UnitError as exc:
        double = str(exc)
    record("S7 dose per body weight gives mg/kg/day; dividing a per-kg dose by weight again (the "
           "double division) is refused", unit == "mg/kg/day" and mgkg == [10.0, 20.0]
           and "already per kilogram" in double, double)
    try:
        units.derived("dose_mg_kg_day", [0.14, 0.29], "mg/kg/day", "daily dose divided by body weight",
                      plausible=(1, 50))
        rng = "accepted"
    except units.UnitError as exc:
        rng = str(exc)
    rec = units.derived("dose_mg_kg_day", mgkg, unit, "daily dose divided by body weight",
                        plausible=(1, 50))
    cr, cu = units.convert([1.0], "creatinine_mgdl_to_umoll")
    h, hu = units.convert(7.0, "hba1c_percent_to_mmolmol")
    try:
        units.convert(1.0, "made_up_factor")
        invented = "accepted"
    except units.UnitError as exc:
        invented = str(exc)
    record("S7 implausible values stop the analysis; tabulated factors carry a source "
           "(creatinine 88.42, HbA1c 7% = 53 mmol/mol); an unknown factor is never invented",
           "outside the plausible range" in rng and rec["range_check"] == "passed"
           and cr == [88.42] and cu == "umol/L" and round(h) == 53 and "never invent" in invented
           and units.factor("mme_oxycodone_oral")["citation"].startswith("Dowell D"),
           rng + invented)
    p = _paper(tmp / "p", "S05_analysis")
    _w(p, "03_analysis/results/dosing.json", {"median_dose_mg_kg_day": 12.0, "n": 40})
    g1 = _gate(p, "derived_units_checked", "S05_analysis")
    _w(p, "03_analysis/results/dosing.json", {"median_dose_mg_kg_day": 12.0, "n": 40,
                                              **units.derived_block(rec)})
    g2 = _gate(p, "derived_units_checked", "S06_protocol_final")
    bad = dict(rec, range_check="failed")
    _w(p, "03_analysis/results/dosing.json", {"median_dose_mg_kg_day": 12.0,
                                              "derived_variables": {"dose_mg_kg_day": bad}})
    g3 = _gate(p, "derived_units_checked", "S05_analysis")
    record("S7 gate: an undeclared per-kg dose in the results fails; declared with unit and a passed "
           "range check passes; a failed range check fails", not g1.ok and "median_dose_mg_kg_day"
           in g1.detail and g2.ok and not g3.ok, g1.detail + " | " + g2.detail + " | " + g3.detail)
    if shutil.which("Rscript"):
        code = ('source(file.path(Sys.getenv("MEDPAPER_ROOT"), "tools/R/medunits.R")); '
                'x <- medpaper_per_body_weight(c(700, 1400), "mg/day", c(70, 70)); '
                'r <- tryCatch(medpaper_per_body_weight(x$values, x$unit, c(70, 70)), '
                'error = function(e) conditionMessage(e)); '
                'cv <- medpaper_convert(1, "creatinine_mgdl_to_umoll"); '
                'cat(x$unit, "SEP", r, "SEP", cv$values, "\\n")')
        proc = subprocess.run(["Rscript", "-e", code], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", env=_env(), timeout=300)
        record("S7 R twin: mg/kg/day, the double division refused, tabulated factor",
               "mg/kg/day" in proc.stdout and "already per kilogram" in proc.stdout
               and "88.42" in proc.stdout, (proc.stdout + proc.stderr)[-300:])


# ------------------------------------------------------------------------------ S8
def run_impute(tmp: Path, record, section) -> None:
    from analysis import imputation as mi
    section("1.23.0 S8: multiple imputation pooled by default (Rubin's rules)")
    est, var = [0.50, 0.60, 0.55, 0.45, 0.65], [0.010, 0.012, 0.011, 0.009, 0.013]
    r = mi.rubin(est, var, n=200, k=4)
    qbar, ubar = sum(est) / 5, sum(var) / 5
    b = sum((x - qbar) ** 2 for x in est) / 4
    t = ubar + 1.2 * b
    record("S8 Rubin's rules: pooled estimate, total variance W + (1 + 1/m) B, Barnard-Rubin df "
           "below the complete-data df; m, method and df recorded",
           abs(r["estimate"] - qbar) < 1e-12 and abs(r["total_variance"] - t) < 1e-12
           and abs(r["se"] - math.sqrt(t)) < 1e-12 and r["m"] == 5 and r["pooling"] == "Rubin's rules"
           and 0 < r["df"] < 196 and r["df_method"].startswith("Barnard-Rubin") and r["ci_low"] < qbar,
           str(r)[:300])
    lg = mi.rubin([math.log(1.5), math.log(1.7)], [0.01, 0.012], log_scale=True)
    bw = mi.bootstrap_within([[1.0, 2.0, 3.0, 4.0], [1.5, 2.0, 3.5, 4.0]],
                             lambda d: sum(d) / len(d), n_boot=50, seed=1)
    record("S8 log-scale pooling returns ratios; bootstrap within imputations pools bootstrap "
           "variances", 1.5 < lg["estimate"] < 1.7 and lg["ci_low"] < lg["estimate"] < lg["ci_high"]
           and bw["m"] == 2 and "bootstrap" in bw["pooling"], str(lg)[:200] + str(bw)[:200])
    try:
        mi.single_imputation("short")
        short = "accepted"
    except ValueError as exc:
        short = str(exc)
    record("S8 a single imputed dataset needs a declared reason", "declared reason" in short, short)
    p = _paper(tmp / "p", "S05_analysis")
    _w(p, "03_analysis/code/01_primary.R", "imp <- mice(dat, m = 20)\nfit <- with(imp, glm(y ~ x))\n")
    _w(p, "03_analysis/results/primary.json", {"or": 1.4})
    g1 = _gate(p, "imputation_pooled", "S05_analysis")
    _w(p, "03_analysis/results/primary.json", {"or": 1.4, **mi.imputation_block(r)})
    g2 = _gate(p, "imputation_pooled", "S06_protocol_final")
    _w(p, "03_analysis/code/02_calibration.R", "d1 <- complete(imp, 1)\nfit <- lm(y ~ x, d1)\n")
    g3 = _gate(p, "imputation_pooled", "S05_analysis")
    _w(p, "03_analysis/results/calibration.json", {"slope": 0.9, **mi.single_imputation(
        "regression calibration needs one complete validation dataset", m_available=20,
        analysis="Regression calibration")})
    g4 = _gate(p, "imputation_pooled", "S05_analysis")
    record("S8 gate: imputation without a pooling record fails; pooled passes; complete(imp, 1) "
           "without a declaration fails; a declared single dataset passes",
           not g1.ok and "no results JSON records m" in g1.detail and g2.ok and not g3.ok
           and "only the first imputed dataset" in g3.detail and g4.ok,
           " | ".join(x.detail for x in (g1, g2, g3, g4)))
    _w(p, "01_protocol/display_dictionary.json", {"terms": []})
    import importlib.util
    spec = importlib.util.spec_from_file_location("wb1230", ROOT / "tools/manuscript/writer_bundle.py")
    wb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wb)
    sent = wb._required_methods_sentences(p)
    record("S8 the Methods sentence of the single-dataset analysis and the pooling statement reach "
           "the S08 writer bundle", any("single imputed dataset of the 20 generated" in s for s in sent)
           and any("pooled across 5 imputed datasets" in s for s in sent), str(sent))
    if shutil.which("Rscript"):
        code = ('source(file.path(Sys.getenv("MEDPAPER_ROOT"), "tools/R/medimpute.R")); '
                'r <- medpaper_rubin(c(0.50, 0.60, 0.55, 0.45, 0.65), '
                'c(0.010, 0.012, 0.011, 0.009, 0.013), n = 200, k = 4); '
                'cat(sprintf("%.10f %.6f", r$estimate, r$df), "\\n")')
        proc = subprocess.run(["Rscript", "-e", code], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", env=_env(), timeout=300)
        try:
            e_r, df_r = map(float, proc.stdout.split()[:2])
        except ValueError:
            e_r, df_r = float("nan"), float("nan")
        record("S8 R medpaper_rubin agrees with the Python pooling (estimate and df)",
               abs(e_r - r["estimate"]) < 1e-9 and abs(df_r - r["df"]) < 1e-2,
               (proc.stdout + proc.stderr)[-300:])


GROUPS = [("pub", run_pub), ("units", run_units), ("impute", run_impute)]
