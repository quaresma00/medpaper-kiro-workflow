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


# ------------------------------------------------------------------------------ S2
def _jats(title: str, doi: str, figs: list[str], tables: list[str], supp: int = 0) -> bytes:
    f = "".join(f"<fig id='f{i}'><label>{lab.split('|')[0]}</label><caption><title>{lab.split('|')[1]}"
                f"</title></caption></fig>" for i, lab in enumerate(figs))
    t = "".join(f"<table-wrap id='t{i}'><label>{lab.split('|')[0]}</label><caption><title>"
                f"{lab.split('|')[1]}</title></caption></table-wrap>" for i, lab in enumerate(tables))
    s = "".join(f"<supplementary-material id='s{i}'><label>Supplementary file {i + 1}</label>"
                "</supplementary-material>" for i in range(supp))
    return (f"<?xml version='1.0'?><article><front><article-meta><article-id pub-id-type='doi'>{doi}"
            f"</article-id><title-group><article-title>{title}</article-title></title-group>"
            f"</article-meta></front><body>{f}{t}{s}</body></article>").encode()


class _Http:
    """Mocked eutils.http_get: URL prefix -> bytes (or an exception); records every call."""

    def __init__(self, routes: dict):
        self.routes, self.calls = routes, []

    def __call__(self, url, params=None, retries=4, timeout=60):
        self.calls.append(url)
        for prefix, val in self.routes.items():
            if url.startswith(prefix):
                if isinstance(val, Exception):
                    raise val
                return val(params) if callable(val) else val
        raise RuntimeError(f"no network in selftests: {url}")


def _epmc(pmid: str, title: str, pmcid: str = "", oa: bool = False) -> bytes:
    return json.dumps({"resultList": {"result": [{"pmid": pmid, "pmcid": pmcid, "title": title,
                                                  "journalTitle": "Drug Saf", "pubYear": "2023",
                                                  "isOpenAccess": "Y" if oa else "N"}]}}).encode()


def run_bench(tmp: Path, record, section) -> None:
    from selftest_v1140 import _envset
    from wfcore import displaybench as db
    from pubmed import benchmark as bm
    section("1.23.0 S2: display benchmark from comparable papers (mocked Europe PMC)")
    x = _jats("Liver injury with drug X", "10.1/a",
              ["Figure 1|Flow chart of case selection", "Figure 2|Forest plot of reporting odds ratios",
               "Figure S1|Sensitivity analysis"], ["Table 1|Characteristics of the reports",
                                                   "Table 2|Time to onset of liver injury"], supp=1)
    got = db.jats_displays(x)
    record("S2 JATS captions: main figures/tables counted, a 'Figure S1' and supplementary files "
           "count as supplementary", got["main_figures"] == 2 and got["main_tables"] == 2
           and got["supplementary"] == 2, str({k: got[k] for k in ("main_figures", "main_tables",
                                                                    "supplementary")}))
    p = _paper(tmp / "p", "S07_artifacts")
    _pin(p, "1.24.0")  # the 1.23 rule; the 1.25.0 recency rule is tested in selftest_v1250
    http = _Http({"https://www.ebi.ac.uk/europepmc/webservices/rest/search": lambda prm: _epmc(
        prm["query"].split(":")[1].split()[0], "Comparable paper", "PMC1" if "111" in prm["query"]
        else "", "111" in prm["query"]),
        "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC1/fullTextXML": x})
    old = bm.eu.http_get
    bm.eu.http_get = http
    try:
        with _envset(MEDPAPER_PROJECT=str(p)):
            a = bm.add(p, "111", "disproportionality")
            try:
                bm.add(p, "222", "disproportionality")
                refused = "accepted"
            except ValueError as exc:
                refused = str(exc)
            b = bm.add(p, "222", "disproportionality", figures=3, tables=2, supplementary=4,
                       types=["flow_diagram", "forest_ror", "seriousness_outcome"], source="abstract")
            bm.add(p, "333", "disproportionality", figures=2, tables=1, supplementary=3,
                   types=["flow_diagram", "forest_ror", "time_to_onset"], source="abstract")
    finally:
        bm.eu.http_get = old
    s = db.summary(db.load(p))
    record("S2 benchmark.py add: open-access XML captions are classified (flow, ROR forest, time to "
           "onset); a closed paper without counts is refused; abstract counts are accepted; median "
           "and majority types computed", a["source"] == "jats"
           and {"flow_diagram", "forest_ror", "time_to_onset"} <= set(a["display_types"])
           and "no open-access XML" in refused and b["source"] == "abstract" and s["n"] == 3
           and s["median_main_items"] == 4
           and {"flow_diagram", "forest_ror", "time_to_onset"} <= set(s["majority_types"]),
           str(s)[:400] + refused[:200])
    plan = {"main_figures": [{"id": "Figure 1", "title": "Flow chart of case selection",
                              "archetype": "flow_diagram"}],
            "main_tables": [{"id": "Table 1", "title": "Characteristics of the reports"}],
            "supp_figures": [], "supp_tables": [], "supp_files": []}
    _w(p, "01_protocol/artifact_plan.json", plan)
    g1 = _gate(p, "display_plan_benchmarked", "S07_artifacts")
    plan["main_figures"] += [{"id": "Figure 2", "title": "Reporting odds ratios by subgroup",
                              "archetype": "forest_plot"},
                             {"id": "Figure 3", "title": "Distribution of the onset interval",
                              "display_type": "time_to_onset"}]
    _w(p, "01_protocol/artifact_plan.json", plan)
    g2 = _gate(p, "display_plan_benchmarked", "S07_artifacts")
    msg = db.message_zh(p)
    record("S2 gate: 2 main items against a median of 4 and missing majority types fail; the plan "
           "reaching the median and covering the types (display_type, archetype or wording) passes; "
           "the Chinese S07 lines show benchmark counts, types and the plan",
           not g1.ok and "median is 4" in g1.detail and "time_to_onset" in g1.detail and g2.ok
           and "同类论文图表基准（3 篇）" in msg[0] and "本文计划：正文图 3 张" in "".join(msg),
           g1.detail + " | " + g2.detail + " | " + " ".join(msg)[:300])
    plan["main_figures"] = plan["main_figures"][:2] + [{"id": "Figure 3", "title": "Annual reports"}]
    plan["benchmark_omissions"] = {"time_to_onset": "onset dates are missing in 90% of reports"}
    _w(p, "01_protocol/artifact_plan.json", plan)
    g3 = _gate(p, "display_plan_benchmarked", "S07_artifacts")
    old_p = _paper(tmp / "old", "S07_artifacts")
    _pin(old_p, "1.22.0")
    g4 = _gate(old_p, "display_plan_benchmarked", "S07_artifacts")
    record("S2 an omitted majority type with a one-line reason passes; a paper pinned to 1.22.0 is "
           "not judged", g3.ok and g4.ok and "pinned earlier" in g4.detail, g3.detail + g4.detail)


# ------------------------------------------------------------------------------ S4
def _pdf(title: str, doi: str) -> bytes:
    return (b"%PDF-1.4\n" + f"{title}\nSmith J, Lee K. 2021\nhttps://doi.org/{doi}\n".encode()
            + b" " * 3000)


def run_fulltext(tmp: Path, record, section) -> None:
    from selftest_v1140 import _envset
    from pubmed import fulltext as ft
    section("1.23.0 S4: lawful full-text cascade, browser step, requests and the drop folder "
            "(mocked HTTP)")
    p = _paper(tmp / "p", "S15_deepread")
    title = "Hepatotoxicity of drug X in a national pharmacovigilance database"
    e = {"citekey": "smith2021", "pmid": "31111111", "doi": "10.1000/xyz.1", "title": title,
         "journal": "Drug Saf", "year": 2021, "authors": [{"last": "Smith"}]}
    e2 = {"citekey": "lee2020", "pmid": "32222222", "doi": "10.1000/abc.2",
          "title": "Time to onset of liver injury with drug X", "journal": "Hepatology", "year": 2020,
          "authors": [{"last": "Lee"}]}
    _w(p, "06_refs/library.json", {"entries": [e, e2]})
    record("S4 the cascade order is cache -> PMC/Europe PMC -> Unpaywall -> OpenAlex -> Semantic "
           "Scholar -> CORE -> preprint (lawful routes only)",
           [f.__name__ for f in ft.ROUTES] == ["try_cache", "try_europepmc", "try_unpaywall",
                                               "try_openalex", "try_semantic_scholar", "try_core",
                                               "try_preprint"])
    oa_repo = json.dumps({"best_oa_location": None, "locations": [
        {"is_oa": True, "pdf_url": "https://repo.example.org/smith.pdf", "version": "acceptedVersion",
         "source": {"type": "repository"}}]}).encode()
    http = _Http({"https://www.ebi.ac.uk/europepmc/webservices/rest/search":
                  json.dumps({"resultList": {"result": []}}).encode(),
                  "https://api.openalex.org/works/doi:10.1000/xyz.1": oa_repo,
                  "https://repo.example.org/smith.pdf": _pdf(title, e["doi"])})
    old = ft.eu.http_get
    ft.eu.http_get = http
    try:
        with _envset(MEDPAPER_PROJECT=str(p), NCBI_API_EMAIL=None, PUBMED_API_EMAIL=None,
                     CORE_API_KEY=None):
            r1 = ft.fetch_one(e)
            ft.record_retrieval(e, r1)
            n_calls = len(http.calls)
            r2 = ft.fetch_one(e)
            record("S4 an OpenAlex repository author manuscript is found after PMC (identity "
                   "match, route and version recorded); a second fetch uses the local cache "
                   "without any request", r1["route"] == "openalex-repository"
                   and r1["identity"] == "match" and r1.get("version") == "acceptedVersion"
                   and r2.get("cache_hit") and len(http.calls) == n_calls,
                   str(r1)[:300] + str(r2)[:200])
            pre = json.dumps({"message": {"relation": {"has-preprint": [
                {"id": "10.1101/2020.01.01.111", "id-type": "doi"}]}}}).encode()
            http2 = _Http({"https://www.ebi.ac.uk/europepmc/webservices/rest/search":
                           json.dumps({"resultList": {"result": []}}).encode(),
                           "https://api.openalex.org/works/doi:10.1000/abc.2":
                               json.dumps({"best_oa_location": None}).encode(),
                           "https://api.semanticscholar.org/": json.dumps({"openAccessPdf": None}).encode(),
                           "https://api.crossref.org/works/10.1000": pre,
                           "https://api.openalex.org/works/doi:10.1101": json.dumps(
                               {"best_oa_location": {"pdf_url": "https://www.medrxiv.org/x.full.pdf"}}).encode(),
                           "https://www.medrxiv.org/x.full.pdf": _pdf(e2["title"], "10.1101/2020.01.01.111")})
            ft.eu.http_get = http2
            r3 = ft.fetch_one(e2)
            core_called = any("core.ac.uk" in u for u in http2.calls)
            record("S4 a preprint linked by the DOI's Crossref relation is used and recorded as a "
                   "preprint; CORE is not called without the user's key",
                   r3["route"] == "preprint" and r3.get("version") == "preprint"
                   and r3.get("preprint_doi") == "10.1101/2020.01.01.111" and not core_called,
                   str(r3)[:300] + str(http2.calls))
            http3 = _Http({"https://www.ebi.ac.uk/europepmc/webservices/rest/search":
                           json.dumps({"resultList": {"result": []}}).encode(),
                           "https://api.openalex.org/": json.dumps({"best_oa_location": None}).encode(),
                           "https://api.semanticscholar.org/": json.dumps({}).encode(),
                           "https://api.core.ac.uk/": json.dumps({"results": []}).encode(),
                           "https://api.crossref.org/": json.dumps({"message": {}}).encode()})
            ft.eu.http_get = http3
            with _envset(CORE_API_KEY="user-key"):
                r4 = ft.fetch_one(e2)
            record("S4 nothing on a lawful open route: paywalled with the next step 'browser' (the "
                   "user's own login); CORE is tried with the user's key",
                   r4["access"] == "paywalled" and r4.get("next_step") == "browser"
                   and "browser-institutional" in r4["note"]
                   and any("core.ac.uk" in u for u in http3.calls), str(r4)[:300])
            ft.record_retrieval(e2, r4)
            rem = ft.remaining_entries({"smith2021": e, "lee2020": e2}, [])
            made = ft.write_requests(rem)
            msg = "\n".join(ft.remaining_message_zh(rem))
            req = (p / "06_refs/fulltext/requests/lee2020_author_request.md").read_text(encoding="utf-8")
            record("S4 remaining: only the paper without a proven full text; author-request draft, "
                   "document-delivery list and ONE Chinese message with DOI, title and the drop folder",
                   [x["citekey"] for x in rem] == ["lee2020"] and len(made) == 2
                   and "Dear Dr Lee" in req and "10.1000/abc.2" in msg and "放进文件夹" in msg
                   and str(p / "06_refs/fulltext/drop") in msg, msg[:400])
            _w(p, "06_refs/fulltext/drop/downloaded.pdf", "")
            (p / "06_refs/fulltext/drop/downloaded.pdf").write_bytes(_pdf(e2["title"], e2["doi"]))
            (p / "06_refs/fulltext/drop/other.pdf").write_bytes(_pdf("Unrelated cardiology trial", "10.9/zz"))
            done, left = ft.ingest_drop({"smith2021": e, "lee2020": e2}, [])
            rec = ft._records().get("lee2020", {})
    finally:
        ft.eu.http_get = old
    record("S4 ingest-drop: the user's PDF is identified by its front matter and registered (route "
           "user-drop); an unrelated file is not", done == ["downloaded.pdf -> lee2020"]
           and left == ["other.pdf"] and rec.get("route") == "user-drop"
           and rec.get("identity") == "match", f"{done} {left} {rec}")
    cli = _run(p, "tools/pubmed/fulltext.py", "remaining")
    record("S4 `fulltext.py remaining` from the CLI: nothing left after the drop", cli.returncode == 0
           and "nothing to ask the user" in _out(cli), _out(cli)[-300:])


# ------------------------------------------------------------------------------ S3
def run_science(tmp: Path, record, section) -> None:
    from wfcore import reviewrounds as rr
    section("1.23.0 S3: independent science review after S11, before the Results are written")
    p = _paper(tmp / "p", "S09_results")
    _w(p, "01_protocol/protocol_final.md", "# Objective\n\nDrug X and liver injury.\n")
    _w(p, "07_manuscript/methods.md", "# Methods\n\nWe analysed reports from 2004 to 2023.\n")
    _w(p, "03_analysis/results/primary.json", {"ror": 2.1, "ci_low": 1.5, "ci_high": 2.9})
    _w(p, "03_analysis/analysis_manifest.json", {"scripts": [
        {"path": "03_analysis/code/01_primary.py", "role": "primary"},
        {"path": "03_analysis/code/02_sens.py", "role": "validity"}]})
    _w(p, "05_figures/legends.md", "# Figure legends\n\n## Figure 1.\n\nForest plot.\n")
    _w(p, "05_figures/out/Figure1.png", "png")
    _w(p, "05_figures/qc/displays_sheet.png", "sheet")
    g0 = _gate(p, "science_review_before_writing", "S09_results")
    st = _run(p, "tools/review_round.py", "start", "--project", p)
    rid = rr.latest(p, "science")["id"]
    bundle = p / rr.BUNDLE_DIR / rid
    man = (bundle / "MANIFEST.md").read_text(encoding="utf-8") if (bundle / "MANIFEST.md").is_file() else ""
    record("S3 at S09 the default review scope is science: the brief judges SCIE suitability, missing "
           "analyses vs comparable papers, robustness, bias, displays vs benchmark, overclaiming; the "
           "bundle has results in words, the analyses done, publishability evidence and the contact "
           "sheet instead of every figure", not g0.ok and st.returncode == 0
           and "Science review brief" in _out(st) and "article type" in man
           and "results_in_words.md" in man and "analyses_done.md" in man and "publishability.md" in man
           and "displays_sheet.png" in man and "05_figures__out__Figure1.png" not in man,
           _out(st)[-500:] + g0.detail)
    (bundle / "report.md").write_text(
        "# Science review\n\nF1 MUST-FIX [grouping] The legend does not say what the bars are; "
        "add a sensitivity analysis excluding reports from lawyers (cost: 1 script).\n\n"
        "Verdict: revise first\nRecommended article type: original article\n", encoding="utf-8")
    _w(p, "05_figures/legends.md", "# Figure legends\n\n## Figure 1.\n\nForest plot of reporting "
                                   "odds ratios with 95% confidence intervals.\n")
    cl = _run(p, "tools/review_round.py", "close", "--findings", "major=1", "--finding", "F1", "other",
              "changed", "legend explains the bars", "--change", "05_figures/legends.md",
              "legend explains the bars", "--report", bundle / "report.md", "--project", p)
    vague = _run(p, "tools/review_round.py", "decide", "no_further_review", "--words", "OK",
                 "--project", p)
    ok = _run(p, "tools/review_round.py", "decide", "no_further_review", "--words", "继续写作",
              "--project", p)
    g1 = _gate(p, "science_review_before_writing", "S09_results")
    record("S3 close prints ONE question (another round or proceed); 'OK' is not a decision, "
           "'继续写作' is; the gate then passes", cl.returncode == 0 and "继续写作" in _out(cl)
           and vague.returncode == 2 and "not a decision to proceed" in _out(vague)
           and ok.returncode == 0 and g1.ok, _out(cl)[-400:] + _out(vague)[-200:] + g1.detail)
    brief = rr.brief(p, {"id": "M001", "scope": "manuscript", "mode": "full"}, bundle)
    _w(p, "03_analysis/results/primary.json", {"ror": 2.2, "ci_low": 1.5, "ci_high": 2.9})
    g2 = _gate(p, "science_review_before_writing", "S09_results")
    brief2 = rr.brief(p, {"id": "M001", "scope": "manuscript", "mode": "full"}, bundle)
    record("S3 the S18 brief focuses on writing and does not reopen closed science items; a changed "
           "result makes the science decision stale (delta round) and the brief names the change",
           "focus this review on writing quality" in brief.lower() and "results and displays unchanged"
           in brief and not g2.ok and "--delta" in g2.detail
           and "03_analysis/results/primary.json" in brief2, g2.detail[:300])
    old = _paper(tmp / "old", "S09_results")
    _pin(old, "1.22.0")
    g3 = _gate(old, "science_review_before_writing", "S09_results")
    record("S3 a paper pinned to 1.22.0 is not judged; the reviewer agent has a science mode",
           g3.ok and "science mode" in (ROOT / ".kiro/agents/medpaper-reviewer.md").read_text(
               encoding="utf-8"), g3.detail)


# ------------------------------------------------------------------------------ S5
ENG = ("# Methods\n\nRaw FAERS quarterly files from 2004 to 2023 were parsed and merged on the case "
       "identifier [@fda2023].\n\nDuplicate rows were flagged and collapsed, and drug strings were "
       "normalised before codes were mapped.\n")
CLIN = ("# Methods\n\nWe analysed reports received by the FDA Adverse Event Reporting System from 2004 "
        "to 2023 [@fda2023].\n\nDuplicate reports were removed following the FDA-recommended approach, "
        "and drug names were standardised.\n")


def run_polish(tmp: Path, record, section) -> None:
    from wfcore import adapters, clinical, sectionpolish as sp
    section("1.23.0 S5: every section drafted by the clinical writer and polished at once by the "
            "medical editor")
    p = _paper(tmp / "p", "S08_methods")
    _w(p, "07_manuscript/methods.md", ENG)
    _w(p, ".wf/writer_bundle/S08_methods/MANIFEST.md", "# Writer bundle (S08_methods)\n\nWrite: "
                                                        "07_manuscript/methods.md\n")
    g0 = _gate(p, "section_polished", "S08_methods", sections=["methods", "supplementary_methods"],
               optional=["supplementary_methods"])
    eng = sp.language_problems(p, "methods", ENG)
    old_list = clinical.engineering_hits(ENG, {}, "all")
    rc = _run(p, "tools/manuscript/writer_bundle.py", "receipt", "--stage", "S08_methods",
              "--project", p)
    ed = _run(p, "tools/manuscript/writer_bundle.py", "edit", "--section", "methods", "--project", p)
    man = (p / ".wf/editor_bundle/methods/MANIFEST.md").read_text(encoding="utf-8")
    record("S5 an engineering-style Methods paragraph fails (no receipt; code narration flagged by "
           "the 1.23 list: parsed, merged on the identifier, flagged, collapsed, strings, mapped "
           "codes); receipt + editor bundle with the clinician rubric",
           not g0.ok and "no writer receipt" in g0.detail and len(eng) >= 5
           and any("flagged" in x for x in eng) and not any(t == "flagged" for t, _h, _s in old_list)
           and rc.returncode == 0 and ed.returncode == 0 and sp.EDITOR in _out(ed)
           and "a clinician who never saw the code" in man, str(eng)[:400] + _out(rc)[-200:])
    bad = CLIN.replace("2023", "2022", 1)
    _w(p, ".wf/editor_bundle/methods/polished.md", bad)
    r_bad = _run(p, "tools/manuscript/writer_bundle.py", "polished", "--section", "methods",
                 "--project", p)
    _w(p, ".wf/editor_bundle/methods/polished.md", CLIN)
    r_ok = _run(p, "tools/manuscript/writer_bundle.py", "polished", "--section", "methods",
                "--project", p)
    g1 = _gate(p, "section_polished", "S08_methods", sections=["methods", "supplementary_methods"],
               optional=["supplementary_methods"])
    record("S5 the editor's text is refused when a number changes; the polished text passes, the "
           "section file equals it and the receipt binds bundle -> draft -> polished",
           r_bad.returncode == 2 and "numbers changed" in _out(r_bad) and r_ok.returncode == 0
           and g1.ok and (p / "07_manuscript/methods.md").read_text(encoding="utf-8") == CLIN
           and all(sp.receipt(p, "methods").get(k) for k in ("bundle_sha256", "draft_sha256",
                                                             "polished_sha256")),
           _out(r_bad)[-300:] + g1.detail)
    _w(p, "07_manuscript/methods.md", CLIN.replace("standardised.", "standardised; rows with "
                                                   "missing values were dropped."))
    g2 = _gate(p, "section_polished", "S08_methods", sections=["methods"])
    sp.build_edit(p, "methods")
    man2 = (p / ".wf/editor_bundle/methods/MANIFEST.md").read_text(encoding="utf-8")
    old = _paper(tmp / "old", "S08_methods")
    _pin(old, "1.22.0")
    g3 = _gate(old, "section_polished", "S08_methods", sections=["methods"])
    agent = (ROOT / ".kiro/agents/medpaper-medical-editor.md").read_text(encoding="utf-8")
    record("S5 a section edited after polishing is detected (paragraph 3) and only that paragraph is "
           "sent back to the editor; a 1.22.0 pin is not judged; the medical editor agent writes only "
           "its polished.md and is installed with the other agents",
           not g2.ok and "edited after polishing (paragraph(s) 3)" in g2.detail
           and "Polish ONLY paragraphs 3" in man2 and g3.ok
           and not adapters.agent_scope_problems("medpaper-medical-editor", agent)
           and "medpaper-medical-editor.md" in adapters.GLOBAL_AGENTS, g2.detail + g3.detail)


# ------------------------------------------------------------------------------ S6
def run_avail(tmp: Path, record, section) -> None:
    from wfcore import dataavail as da, datasources
    section("1.23.0 S6: public facts checked before asking; data availability from verified records")
    p = _paper(tmp / "p", "S21_authors")
    for n in ("mimic", "eicu"):
        d = tmp / f"data_{n}"
        d.mkdir(parents=True, exist_ok=True)
        (d / "x.csv").write_text("a,b\n1,2\n", encoding="utf-8")
        datasources.add(p, d, n)
    g0 = _gate(p, "data_availability_verified", "S21_authors")
    da.record(p, "mimic", "PhysioNet Credentialed Health Data License 1.5.0", "credentialed",
              "https://physionet.org/content/mimiciv/", "https://physionet.org/content/mimiciv/",
              label="MIMIC-IV")
    rec = _run(p, "tools/wf.py", "data", "licence", "eicu", "--licence", "CC BY 4.0", "--access",
               "open", "--url", "https://example.org/eicu-demo", "--doi", "10.13026/xyz1",
               "--source", "https://example.org/eicu-demo/license", "--label", "eICU demo")
    _w(p, "07_manuscript/statements.md", "# Declarations\n\n## Data availability\n\nBoth datasets "
                                         "(MIMIC-IV and eICU demo) require credentialed access.\n")
    g1 = _gate(p, "data_availability_verified", "S21_authors")
    text = da.statement(p)
    _w(p, "07_manuscript/statements.md", f"# Declarations\n\n## Data availability\n\n{text}\n")
    g2 = _gate(p, "data_availability_verified", "S21_authors")
    record("S6 every data source needs a verified licence/access record; 'both datasets require "
           "credentialed access' fails when one is CC BY 4.0 open; the generated statement (DOI "
           "cited) passes", not g0.ok and "not verified" in g0.detail and rec.returncode == 0
           and not g1.ok and "eICU demo" in g1.detail and "open" in g1.detail
           and "https://doi.org/10.13026/xyz1" in text and "credentialed users" in text and g2.ok,
           g1.detail + " | " + text + " | " + g2.detail)
    v = _run(p, "tools/wf.py", "decisions", "verify", "transplant_statement", "--text",
             "No organs or tissues were procured from prisoners.", "--source",
             "https://journal.example.org/policies#transplant", "--fact",
             "the journal requires this statement for all transplant studies")
    show = _run(p, "tools/wf.py", "decisions", "show")
    card = _run(p, "tools/wf.py", "card")
    old = _paper(tmp / "old", "S21_authors")
    _pin(old, "1.22.0")
    g3 = _gate(old, "data_availability_verified", "S21_authors")
    record("S6 a journal-specific statement is self-verified with its source URL (no question to "
           "the user) and shown with the decisions; every card says to check public sources first; "
           "a 1.22.0 pin is not judged", v.returncode == 0 and "自行查证" in _out(show)
           and "journal.example.org" in _out(show) and "wf decisions verify" in _out(card) and g3.ok,
           _out(v)[-200:] + _out(show)[-300:])


# ------------------------------------------------------------------------------ release
NEW_1230 = ("publishability_checkpoint", "derived_units_checked", "imputation_pooled",
            "display_plan_benchmarked", "science_review_before_writing", "section_polished",
            "data_availability_verified")


def run_release(tmp: Path, record, section) -> None:
    from wfcore import registry
    from wfcore.state import State
    section("1.23.0 release: one migration event, new gates since 1.23.0, short cards")
    q = tmp / "mig"
    q.mkdir(parents=True, exist_ok=True)
    st = State(q, ".wf").create("medpaper", "1.22.0", "S09_results")
    before = sorted(x.name for x in q.rglob("*"))
    st.migrate_pipeline("1.23.0", [s.id for s in registry.load().stages])
    st.migrate_pipeline("1.23.0", [s.id for s in registry.load().stages])
    notes = [e for e in st.data["events"] if e["kind"] == "requirements_changed"
             and str(e.get("detail", "")).startswith("1.23.0")]
    after = sorted(x.name for x in q.rglob("*"))
    pipe = registry.load()
    gates = [(s.id, g["check"], g.get("since")) for s in pipe.stages for g in s.gate
             if g["check"] in NEW_1230]
    cards = {s.id: (ROOT / "pipeline" / s.card).read_text(encoding="utf-8") for s in pipe.stages}
    skill = (ROOT / ".kiro/skills/medpaper-pipeline/SKILL.md").read_text(encoding="utf-8")
    record("R pipeline 1.23.0; a 1.22.0 paper gets exactly one 1.23.0 event naming wf migrate --yes "
           "and stays pinned (no paper file touched); every new gate carries since 1.23.0",
           pipe.meta.get("version") in ("1.23.0", "1.24.0", "1.25.0") and len(notes) == 1 and "wf migrate --yes" in
           notes[0]["detail"] and st.engine_pin == "1.22.0" and before == after
           and {c for _s, c, _v in gates} == set(NEW_1230) and all(v == "1.23.0" for *_x, v in gates),
           str(gates)[:300])
    record("R cards <= the card limit name the new steps (publishability, benchmark, science "
           "review, full-text cascade, medical editor, data licence); SKILL names the editor and "
           "the science review", max(len(c) for c in cards.values()) <= registry.CARD_MAX_CHARS
           and "publishability record" in cards["S02_feasibility"]
           and "benchmark.py add" in cards["S07_artifacts"]
           and "--scope science" in cards["S09_results"] and "remaining" in cards["S15_deepread"]
           and "medpaper-medical-editor" in cards["S08_methods"]
           and "wf data licence" in cards["S21_authors"]
           and "medpaper-medical-editor" in skill and "--scope science" in skill,
           str({k: len(v) for k, v in cards.items() if len(v) > 3900}))


GROUPS = [("pub", run_pub), ("units", run_units), ("impute", run_impute), ("bench", run_bench),
          ("fulltext", run_fulltext), ("science", run_science), ("polish", run_polish),
          ("avail", run_avail), ("release", run_release)]
