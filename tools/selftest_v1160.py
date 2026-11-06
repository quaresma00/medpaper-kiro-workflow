"""1.16.0 regression tests from a five-reviewer audit of engine 1.15.0 (clinical methodology,
medical statistics, SCI editor, medical graphics, workflow architecture). Counterexample first:
each N1/N2/N3/N5/N9 counterexample below passed the 1.15.0 gates; now it fails or is listed for
the reviewer, and the legitimate examples still pass. Synthetic fixtures only - no real paper or
dataset is read.

Called from tools/selftest.py.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from selftest_v1140 import _env, _envset, _gate, _out, _paper, _run, _w  # noqa: E402


def run(tmp: Path, record, section, only: str = "") -> None:
    tmp.mkdir(parents=True, exist_ok=True)
    for name, fn in GROUPS:
        if not only or name in only.split():
            fn(tmp / name, record, section)


def _pin(p: Path, version: str) -> None:
    st = json.loads((p / ".wf/state.json").read_text(encoding="utf-8"))
    st["engine_pin"] = version
    (p / ".wf/state.json").write_text(json.dumps(st), encoding="utf-8")


# ------------------------------------------------------------------------------ N1
DICT = {"terms": [
    {"internal": "dialysis", "label": "maintenance dialysis patients",
     "definition": "adults on maintenance haemodialysis or peritoneal dialysis"},
    {"internal": "transplant", "label": "kidney transplant recipients",
     "definition": "adults with a functioning kidney graft"},
    {"internal": "sglt2", "label": "SGLT2 inhibitor", "definition": "sodium-glucose cotransporter-2 inhibitor"},
    {"internal": "glp1", "label": "GLP-1 receptor agonist", "definition": "glucagon-like peptide-1 receptor agonist"},
    {"internal": "dpp4", "label": "DPP-4 inhibitor", "definition": "dipeptidyl peptidase-4 inhibitor"},
    {"internal": "death", "label": "all-cause death", "definition": "death from any cause"}]}
RES = {"estimates": [
    {"population": "dialysis", "exposure": "sglt2", "reference": "dpp4", "outcome": "death",
     "measure": "HR", "time": "1 year", "estimate": 0.78, "ci_low": 0.66, "ci_high": 0.92,
     "p": 0.003, "n": 4210},
    {"population": "transplant", "exposure": "glp1", "reference": "dpp4", "outcome": "death",
     "measure": "OR", "time": "5 years", "estimate": 1.31, "ci_low": 1.05, "ci_high": 1.64,
     "p": 0.017, "n": 1988}]}
CORRECT = ("Among maintenance dialysis patients, SGLT2 inhibitor use vs DPP-4 inhibitor use was "
           "associated with lower 1-year all-cause death (HR 0.78, 95% CI 0.66-0.92; P = 0.003).")
COMBINED = ("Lower 1-year all-cause death was seen in maintenance dialysis patients (HR 0.78, 95% "
            "CI 0.66-0.92), and higher 5-year all-cause death in kidney transplant recipients "
            "receiving a GLP-1 receptor agonist (OR 1.31, 95% CI 1.05-1.64).")


def run_n1(tmp: Path, record, section) -> None:
    from wfcore import reviewitems
    section("1.16.0 N1: a Results number keeps the context of the result it comes from")
    p = _paper(tmp / "ctx", "S09_results")
    _w(p, "01_protocol/display_dictionary.json", DICT)
    _w(p, "03_analysis/results/primary.json", RES)

    def gate(sentence: str, rel: str = "07_manuscript/results.md"):
        _w(p, rel, "# Results\n\n" + sentence + "\n")
        r = _gate(p, "numbers_have_provenance", "S09_results", path=rel)
        listed = [it for src, it in reviewitems.items(p) if src.endswith(rel)]
        return r, listed

    counter = CORRECT.replace("maintenance dialysis patients", "kidney transplant recipients") \
        .replace("SGLT2 inhibitor", "GLP-1 receptor agonist").replace("HR", "OR") \
        .replace("1-year", "5-year")
    swaps = {"population": CORRECT.replace("maintenance dialysis patients", "kidney transplant recipients"),
             "comparison": CORRECT.replace("SGLT2 inhibitor", "GLP-1 receptor agonist"),
             "measure": CORRECT.replace("HR 0.78", "OR 0.78"),
             "time window": CORRECT.replace("1-year", "5-year")}
    r, _ = gate(counter)
    record("N1 counterexample (transplant population, other comparison, OR, 5 years; numbers of the "
           "1-year dialysis HR) passed 1.15.0 and now fails", not r.ok and "another context" in r.detail,
           r.detail[:300])
    for what, s in swaps.items():
        r, _ = gate(s)
        record(f"N1 single swap of the {what} fails (explicit contradiction)",
               not r.ok and "another context" in r.detail, r.detail[:240])
    r, listed = gate(CORRECT)
    record("N1 the correct sentence passes and is not listed", r.ok and not listed, r.detail[:200])
    r, _ = gate("Among maintenance dialysis patients, SGLT2 inhibitor use was associated with lower "
                "all-cause death at 1 year (hazard ratio 0.78, 95% CI 0.66 to 0.92).")
    record("N1 synonyms pass ('hazard ratio' = HR, 'at 1 year' = 1-year)", r.ok, r.detail[:200])
    r, listed = gate(COMBINED)
    record("N1 a sentence combining two results, each in its own context, passes unlisted",
           r.ok and not listed, f"{r.detail[:160]} {listed}")
    r, listed = gate(COMBINED.replace("OR 1.31", "HR 1.31"))
    record("N1 a combined sentence with a contradiction goes to the reviewer list, not a failure",
           r.ok and len(listed) == 1 and "combines 2 results" in listed[0], str(listed)[:240])
    r, listed = gate("The estimate was 0.78 (0.66-0.92).")
    record("N1 a sentence without context words never fails", r.ok and not listed, r.detail[:160])
    r, listed = gate(CORRECT.replace("lower 1-year all-cause death",
                                     "lower all-cause death in maintenance dialysis patients and "
                                     "kidney transplant recipients"))
    record("N1 an extra label next to the right one is listed for the reviewer, not failed",
           r.ok and len(listed) == 1, str(listed)[:240])
    out = tmp / "bundle"
    out.mkdir(parents=True, exist_ok=True)
    written = reviewitems.write(p, out)
    record("N1 the listed sentences reach the next review bundle as reviewer_items.md",
           written is not None and "kidney transplant recipients" in written.read_text(encoding="utf-8"))
    _w(p, "07_manuscript/abstract.md", "# Abstract\n\n" + counter + "\n")
    r = _gate(p, "numbers_have_provenance", "S17_assemble", path="07_manuscript/abstract.md")
    record("N1 the Abstract is checked the same way", not r.ok and "another context" in r.detail,
           r.detail[:200])
    q = _paper(tmp / "pinned", "S09_results")
    _pin(q, "1.15.0")
    _w(q, "01_protocol/display_dictionary.json", DICT)
    _w(q, "03_analysis/results/primary.json", RES)
    _w(q, "07_manuscript/results.md", "# Results\n\n" + counter + "\n")
    r = _gate(q, "numbers_have_provenance", "S09_results", path="07_manuscript/results.md")
    record("N1 a paper pinned to 1.15.0 keeps the 1.15 rule until `wf migrate --yes`", r.ok, r.detail)


# ------------------------------------------------------------------------------ N2
def run_n2(tmp: Path, record, section) -> None:
    section("1.16.0 N2: small integers are conventions only outside result contexts")
    p = _paper(tmp / "small", "S09_results")
    _w(p, "03_analysis/results/primary.json", {"n": 42})
    _w(p, "07_manuscript/results.md",
       "# Results\n\nAmong 42 patients, n=3 had the event (OR=2, 95% CI 1-9).\n")
    r = _gate(p, "numbers_have_provenance", "S09_results", path="07_manuscript/results.md")
    record("N2 counterexample ('n=3', 'OR=2', 'CI 1-9' with only 42 in JSON) passed 1.15.0 and now "
           "fails on each small integer", not r.ok and all(f": {t}" in r.detail for t in "3219"),
           r.detail[:240])
    _w(p, "03_analysis/results/primary.json",
       {"n": 42, "events": 3, "or": 2.0, "ci_low": 1, "ci_high": 9})
    r = _gate(p, "numbers_have_provenance", "S09_results", path="07_manuscript/results.md")
    record("N2 the same sentence passes once the analysis wrote 3, 2, 1 and 9", r.ok, r.detail[:200])
    _w(p, "07_manuscript/results.md",
       "# Results\n\nAmong 42 patients (Figure 2, Table S3, Online Resource 2), P values were "
       "2-sided and 95% CIs are shown; analyses used version 1.14.1 at the 5% significance level.\n"
       "\n1. The primary analysis is described first.\n")
    r = _gate(p, "numbers_have_provenance", "S09_results", path="07_manuscript/results.md")
    record("N2 labels, sidedness, confidence and significance levels, versions and list markers stay "
           "exempt", r.ok, r.detail[:240])
    _w(p, "07_manuscript/methods.md", "# Methods\n\nPatients with at least 2 events and 3 visits "
       "were included; the alpha was 0.05 and follow-up lasted 5 years.\n")
    r = _gate(p, "numbers_have_provenance", "S08_methods", path="07_manuscript/methods.md")
    record("N2 protocol constants in Methods keep working (Methods is not a result context)", r.ok,
           r.detail[:200])


# ------------------------------------------------------------------------------ N3
def _table(p: Path, header, rows, name="Table1.xlsx", tid="Table 1", title=None):
    from tables.threeline import write_table
    with _envset(MEDPAPER_PROJECT=str(p)), redirect_stdout(io.StringIO()):
        write_table(p / f"04_tables/main/{name}", tid, title or f"{tid}. Characteristics.",
                    header, rows, ["Data are n (%)."])
    _w(p, "01_protocol/artifact_plan.json", {"main_tables": [
        {"id": tid, "file": f"04_tables/main/{name}"}], "main_figures": []})


def run_n3(tmp: Path, record, section) -> None:
    from analysis.results import proportion
    section("1.16.0 N3: table n (%) cells agree with their column denominator and population")
    p = _paper(tmp / "tab", "S10_tables")
    _w(p, "03_analysis/results/primary.json", {"women_n": 12, "other": 50.0, "N": 100,
                                               "pct": 12.0, "n": 200, "x": 15.0, "k": 30})

    def gate(header, rows, **spec):
        _table(p, header, rows)
        return _gate(p, "table_percent_denominators", "S10_tables", **spec)
    prov = None
    _table(p, ["Characteristic", "Overall (N = 100)"], [["Women", "12 (50.0%)"]])
    prov = _gate(p, "numbers_have_provenance", "S10_tables", source="tables")
    r = _gate(p, "table_percent_denominators", "S10_tables", missing="warn")
    record("N3 counterexample '12 (50.0%)' under 'N = 100' passed the 1.15.0 S10 gates and now "
           "fails (12/100 is 12.0%)", prov.ok and not r.ok and r.blocking and "12/100" in r.detail,
           r.detail[:200])
    r = gate(["Characteristic", "Overall (N = 100)"], [["Women", "12 (12.0%)"]], missing="warn")
    record("N3 a correct n (%) cell passes", r.ok, r.detail[:160])
    _w(p, "03_analysis/results/props.json", {"a": proportion(30, 200, "transplant"),
                                             "b": proportion(50, 200, "dialysis")})
    r = gate(["Characteristic", "Dialysis (N = 200)"], [["Diabetes", "30 (15.0%)"]], missing="warn")
    record("N3 the right percentage from another population's record fails (wrong population)",
           not r.ok and r.blocking and "transplant" in r.detail, r.detail[:200])
    (p / "03_analysis/results/props.json").unlink()
    r = gate(["Characteristic", "Value"], [["Women", "12 (12.0%)"]], missing="warn")
    record("N3 no denominator source: warning at S10", not r.ok and not r.blocking, r.detail[:160])
    r = _gate(p, "table_percent_denominators", "S12_reconcile", missing="fail")
    record("N3 no denominator source: failure at S12", not r.ok and r.blocking, r.detail[:160])
    r = gate(["Characteristic", "Overall (N = 100)"], [["Prevalence", "12.0 (10.1-14.2)"]],
             missing="fail")
    record("N3 a CI cell is not judged by this rule", r.ok, r.detail[:160])
    r = gate(["Characteristic", "Weighted (N = 100)"], [["Women", "12 (50.0%)"]], missing="fail")
    record("N3 a column flagged weighted is not judged by this rule", r.ok, r.detail[:160])
    r = gate(["Characteristic", "Overall"], [["Women", "12/100 (50.0%)"]], missing="fail")
    record("N3 an 'n/N (x%)' cell is checked against its own N", not r.ok and "12/100" in r.detail,
           r.detail[:160])


# ------------------------------------------------------------------------------ N4
def run_n4(tmp: Path, record, section) -> None:
    import pandas as pd
    from analysis.results import baseline_counts
    section("1.16.0 N4: baseline_counts counts None/NaN/NA/NaT as missing")
    df = pd.DataFrame({"visit": pd.to_datetime(["2025-01-01", None, "2025-01-01"]),
                       "sex": pd.array(["F", pd.NA, "M"], dtype="string"),
                       "lab": [1.5, float("nan"), None],
                       "empty": [None, None, None]})
    out = baseline_counts(df, ["visit", "sex", "lab", "empty"])
    o = {k: v["overall"] for k, v in out.items()}
    record("N4 NaT is missing, not a level (the reviewers' smoke test)",
           o["visit"]["missing"] == 1 and len(o["visit"]["levels"]) == 1
           and not any("NaT" in k for k in o["visit"]["levels"]), str(o["visit"]))
    record("N4 pd.NA and NaN/None are missing; an all-missing column has no levels",
           o["sex"]["missing"] == 1 and set(o["sex"]["levels"]) == {"F", "M"}
           and o["lab"]["missing"] == 2 and o["empty"] == {"denominator": 3, "missing": 3,
                                                           "levels": {}}, str(o)[:300])
    if not shutil.which("Rscript"):
        record("N4 R baseline_counts: Rscript available", False, "Rscript missing")
        return
    code = ('source(file.path(Sys.getenv("MEDPAPER_ROOT"), "tools/R/medresults.R")); '
            'd <- data.frame(dt = as.Date(c("2025-01-01", NA, "2025-01-01")), '
            'ts = as.POSIXct(c("2025-01-01 10:00", NA, NA), tz = "UTC"), '
            'f = factor(c("a", NA, "b"), exclude = NULL), x = c(1, NaN, NA), e = c(NA, NA, NA)); '
            'b <- baseline_counts(d, c("dt", "ts", "f", "x", "e")); '
            'cat(jsonlite::toJSON(lapply(b, function(v) list(m = v$overall$missing, '
            'l = names(v$overall$levels))), auto_unbox = TRUE))')
    proc = subprocess.run(["Rscript", "-e", code], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=_env(), timeout=300)
    try:
        got = json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        got = {}
    record("N4 R baseline_counts: NA for Date, POSIXct, factor and NaN is missing, never a level; "
           "an all-missing column has no levels",
           got.get("dt", {}).get("m") == 1 and got.get("ts", {}).get("m") == 2
           and got.get("f", {}).get("m") == 1 and sorted(got.get("f", {}).get("l") or []) == ["a", "b"]
           and got.get("x", {}).get("m") == 2 and not got.get("e", {}).get("l"),
           (proc.stdout + proc.stderr)[-300:])


# ------------------------------------------------------------------------------ N5
FIG_SCRIPT = '''import json
import matplotlib
matplotlib.use("Agg")
from wfcore import paths
from figures.style import apply_style, figure, save
P = paths.project_dir(check_engine=False)
res = json.loads((P / "03_analysis/results/fig.json").read_text(encoding="utf-8"))
apply_style()
fig, panels = figure(width="single", height_mm=60, panels=(1, 1), letters=False)
_, ax = panels[0]
ax.plot([0, 1, 2, 3], [1.0, 0.9, 0.8, 0.7])
ax.set_xlabel("Year of follow-up")
ax.set_ylabel("Survival")
LABEL_LINE
ax.text(0.95, 0.95, LABEL, transform=ax.transAxes, ha="right", va="top")
save(fig, P / "05_figures/out/Figure1", width="single", archetype="line_trend")
'''


def run_n5(tmp: Path, record, section) -> None:
    import hashlib
    section("1.16.0 N5: statistics printed in a figure match its own source_results; fresh receipt")
    p = _paper(tmp / "fig", "S11_figures")
    _w(p, "03_analysis/results/fig.json", {"hr": 1.87, "hr_low": 1.34, "hr_high": 2.61,
                                           "p": 0.00021, "n": 1284})
    _w(p, "03_analysis/results/other.json", {"hr": 1.99})
    _w(p, "01_protocol/artifact_plan.json", {"main_tables": [], "main_figures": [
        {"id": "Figure 1", "file": "05_figures/out/Figure1.png", "tiff": "05_figures/out/Figure1.tiff",
         "archetype": "line_trend", "source_results": ["03_analysis/results/fig.json"]}]})
    good = ('LABEL = f"HR {res[\'hr\']:.2f} (95% CI {res[\'hr_low\']:.2f}\\u2013{res[\'hr_high\']:.2f})'
            '\\nP < 0.001; n = {res[\'n\']}"\n')
    script = _w(p, "05_figures/code/fig1.py", FIG_SCRIPT.replace("LABEL_LINE\n", good))
    env = _env(p)

    def render():
        return _run(p, "tools/wf.py", "run-script", "05_figures/code/fig1.py", env=env, cwd=p)
    rr = render()
    side = json.loads((p / "05_figures/qc/Figure1.artist.json").read_text(encoding="utf-8")) \
        if (p / "05_figures/qc/Figure1.artist.json").is_file() else {}
    r = _gate(p, "figure_statistics_bound", "S11_figures")
    record("N5 Python figures carry the render receipt (script, source_results and output hashes)",
           rr.returncode == 0 and side.get("script") == "05_figures/code/fig1.py"
           and list(side.get("source_hashes", {})) == ["03_analysis/results/fig.json"]
           and "05_figures/out/Figure1.png" in side.get("render_hashes", {}), _out(rr)[-300:])
    record("N5 a correct figure passes (statistics from its own results; tick labels ignored)",
           r.ok, r.detail[:200])
    script.write_text(FIG_SCRIPT.replace("LABEL_LINE\n", good.replace("res['hr']:.2f", "1.99:.2f")),
                      encoding="utf-8")
    render()
    r = _gate(p, "figure_statistics_bound", "S11_figures")
    record("N5 counterexample: an HR label changed while the JSON is unchanged fails (1.99 exists "
           "only in another result file)", not r.ok and "1.99" in r.detail, r.detail[:240])
    script.write_text(FIG_SCRIPT.replace("LABEL_LINE\n", good), encoding="utf-8")
    render()
    _w(p, "03_analysis/results/fig.json", {"hr": 1.95, "hr_low": 1.34, "hr_high": 2.61,
                                           "p": 0.00021, "n": 1284})
    r = _gate(p, "figure_statistics_bound", "S11_figures")
    record("N5 counterexample: the source JSON replaced without re-rendering fails",
           not r.ok and "result changed after rendering" in r.detail, r.detail[:240])
    render()
    script.write_text(script.read_text(encoding="utf-8") + "# tweak\n", encoding="utf-8")
    r = _gate(p, "figure_statistics_bound", "S11_figures")
    record("N5 counterexample: the Python script changed without re-rendering fails",
           not r.ok and "plotting script changed" in r.detail, r.detail[:240])
    render()
    # An R sidecar (save_medpaper layout) is judged by the same receipt and statistic rules.
    png = p / "05_figures/out/Figure1.png"

    def sha(x):
        return hashlib.sha256(x.read_bytes()).hexdigest().upper()
    _w(p, "05_figures/code/fig_r.R", "# R plotting script\n")
    art = json.loads((p / "05_figures/qc/Figure1.artist.json").read_text(encoding="utf-8"))
    art.update(engine="R", script="05_figures/code/fig_r.R",
               script_sha256=sha(p / "05_figures/code/fig_r.R"),
               source_hashes={"03_analysis/results/fig.json": sha(p / "03_analysis/results/fig.json")},
               render_hashes={"05_figures/out/Figure1.png": sha(png)},
               figure_text=["A", "0", "1", "2", "2020", "HR 1.95 (1.34-2.61)", "Log-rank P < 0.001"])
    _w(p, "05_figures/qc/Figure1.artist.json", art)
    ok_r = _gate(p, "figure_statistics_bound", "S11_figures")
    art["figure_text"] = ["HR 1.95 (1.34-2.81)"]
    _w(p, "05_figures/qc/Figure1.artist.json", art)
    bad_r = _gate(p, "figure_statistics_bound", "S11_figures")
    record("N5 R figure texts (medfig audit sidecar) are bound the same way; panel letters, axis "
           "ticks and years are not statistics", ok_r.ok and not bad_r.ok and "2.81" in bad_r.detail,
           ok_r.detail[:120] + " | " + bad_r.detail[:160])


# ------------------------------------------------------------------------------ N6
def run_n6(tmp: Path, record, section) -> None:
    from wfcore import declarations as dc
    section("1.16.0 N6: PROSPERO registration by eligibility, never an invented ID")
    base = {"data_source": {"type": "published_studies", "name": "published trials",
                            "third_party": False, "redistributable": True, "deidentified": True,
                            "vulnerable_populations": []}}
    sr = dc.assess({**base, "study_design": "systematic_review"})
    scoping = dc.assess({**base, "study_design": "systematic_review", "review_type": "scoping_review"})
    guide = dc.assess({**base, "study_design": "systematic_review",
                       "review_type": "guideline_appraisal"})
    cohort = dc.assess({**base, "study_design": "cohort_retrospective",
                        "data_source": {**base["data_source"], "type": "public_database"}})
    record("N6 a systematic review with a health outcome: register as early as possible and before "
           "data extraction; the ID (or 'not registered' + reason) is asked from the author",
           sr["registration"]["eligible"] and "before data" in sr["registration"]["conclusion"]
           and "prospero_registration" in {q["id"] for q in sr["questions"]},
           sr["registration"]["conclusion"][:200])
    record("N6 a scoping review and a guideline appraisal: reason recorded, no ID asked",
           not scoping["registration"]["eligible"] and "scoping" in scoping["registration"]["statement"]
           and not guide["registration"]["eligible"] and "guideline" in guide["registration"]["statement"]
           and "prospero_registration" not in {q["id"] for q in scoping["questions"] + guide["questions"]})
    record("N6 non-review studies are unchanged (no registration)",
           not cohort["registration"]["applies"]
           and "prospero_registration" not in {q["id"] for q in cohort["questions"]})
    p = tmp / "sr"
    _w(p, dc.IDEA, {**base, "study_design": "meta_analysis"})
    dc.write(p)
    errors = []
    for bad in ("CRD123", "pending", "registered later"):
        try:
            dc.answer(p, "prospero_registration", bad)
        except ValueError:
            errors.append(bad)
    ok1 = dc.answer(p, "prospero_registration", "CRD42024123456")
    ok2 = dc.answer(p, "prospero_registration", "not registered: data extraction had started")
    record("N6 the answer is an ID as registered (CRD42...) or 'not registered: <reason>'",
           len(errors) == 3 and ok1 and ok2["answers"]["prospero_registration"]["value"].startswith("not"))


# ------------------------------------------------------------------------------ N7
def run_n7(tmp: Path, record, section) -> None:
    import pandas as pd
    from analysis.joinlog import JoinLog
    from wfcore import dataproof
    section("1.16.0 N7: joins declared complex carry consistent per-step counts")
    p = _paper(tmp / "join", "S04_data")
    st = SimpleNamespace(engine_pin="1.16.0")
    cj = {"relationship": "complex_join"}
    pts = pd.DataFrame({"pid": [1, 2, 3]})
    labs = pd.DataFrame({"pid": [1, 1, 2, 3, 3], "v": [5, 6, 7, 8, 9]})

    def log(steps):
        _w(p, dataproof.JOIN_LOG_REL, {"unit_key": "pid", "steps": steps})
        return dataproof.join_problems(p, cj, 3, st)
    jl = JoinLog("pid")
    m = jl.step("labs", pts, pts.merge(labs, on="pid"), "repeated_visits", "pid")
    jl.step("first lab", m, m.groupby("pid").first().reset_index(), "aggregation", "pid",
            aggregation="first laboratory value per patient")
    with _envset(MEDPAPER_PROJECT=str(p)):
        jl.save()
    good = dataproof.join_problems(p, cj, 3, st)
    record("N7 repeated visits aggregated to one row per patient (JoinLog helper) pass", not good,
           str(good))
    dup = JoinLog("pid")
    lookup = pd.DataFrame({"pid": [1, 1, 2, 3], "site": ["a", "b", "c", "d"]})
    dup.step("site lookup", pts, pts.merge(lookup, on="pid"), "many_to_one", "pid")
    probs = log(dup.steps)
    record("N7 duplicate keys in a many-to-one lookup fail (rows grew)",
           any("duplicate keys" in x for x in probs), str(probs)[:200])
    mm = JoinLog("pid")
    mm.step("drug x diagnosis", pts, pts.merge(labs, on="pid"), "many_to_many", "pid")
    probs = log(mm.steps)
    record("N7 a many-to-many step without its resolution rule fails",
           any("many_to_many needs" in x for x in probs), str(probs)[:200])
    lost = JoinLog("pid")
    inner = pts.merge(pd.DataFrame({"pid": [1, 2], "v": [1, 2]}), on="pid")
    lost.step("inner", pts, inner, "many_to_one", "pid")
    probs = log(lost.steps)
    lost.steps[0]["unmatched_units"] = 1
    _w(p, dataproof.JOIN_LOG_REL, {"unit_key": "pid", "steps": lost.steps})
    probs2 = dataproof.join_problems(p, cj, 2, st)
    record("N7 unmatched rows must be counted: 1 patient lost with unmatched = 0 fails, with "
           "unmatched = 1 passes", any("lost" in x for x in probs) and not probs2, str(probs)[:200])
    (p / dataproof.JOIN_LOG_REL).unlink()
    record("N7 a simple one-row-per-patient acquisition is not asked for a join log; a complex join "
           "without one is",
           not dataproof.join_problems(p, {"relationship": "one_record_per_analysis_row"}, 3, st)
           and dataproof.join_problems(p, cj, 3, st)
           and not dataproof.join_problems(p, cj, 3, SimpleNamespace(engine_pin="1.15.0")))
    if shutil.which("Rscript"):
        code = ('source(file.path(Sys.getenv("MEDPAPER_ROOT"), "tools/R/medjoin.R")); '
                'a <- data.frame(pid = 1:3); b <- merge(a, data.frame(pid = c(1, 1, 2, 3, 3)), by = "pid"); '
                'g <- join_log_step(NULL, "labs", a, b, unit_key = "pid", kind = "repeated_visits", key = "pid"); '
                'cat(jsonlite::toJSON(g, auto_unbox = TRUE))')
        proc = subprocess.run(["Rscript", "-e", code], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", env=_env(), timeout=300)
        try:
            g = json.loads(proc.stdout.strip().splitlines()[-1])
            s = g["steps"][0]
        except (ValueError, IndexError, KeyError):
            s = {}
        record("N7 the R helper join_log_step() writes the same fields",
               s.get("rows_before") == 3 and s.get("rows_after") == 5 and s.get("units_after") == 3,
               (proc.stdout + proc.stderr)[-200:])


# ------------------------------------------------------------------------------ N8
def run_n8(tmp: Path, record, section) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from figures import recipes
    from figures.style import apply_style
    section("1.16.0 N8: the Python KM recipe draws the exported curve (aligned with R)")
    apply_style()
    p = _paper(tmp / "km", "S11_figures")
    curve = {"n": 6, "time": [0, 2, 5, 0, 3, 6], "estimate": [1, 0.8, 0.5, 1, 0.9, 0.7],
             "lower": [1, 0.6, 0.3, 1, 0.7, 0.5], "upper": [1, 0.95, 0.8, 1, 0.99, 0.9],
             "strata": ["A", "A", "A", "B", "B", "B"], "censor": [False] * 6,
             "risk": {"time": [0, 5, 0, 5], "strata": ["A", "A", "B", "B"], "n_risk": [3, 1, 3, 2]}}
    with _envset(MEDPAPER_PROJECT=str(p)):
        fig, (ax, _t) = recipes.km_survival(curve=curve, logrank_p=0.04, time_points=[0, 5])
        marks = [ln for ln in ax.get_lines() if ln.get_marker() == "|"]
        pop = fig.medpaper_population
        plt.close(fig)
        errs = {}
        groups = [{"name": "A", "time": [1, 2, 3, 4], "event": [1, 1, 1, 1]},
                  {"name": "B", "time": [1, 2, 3, 4, 5], "event": [1, 0, 1, 1, 0]}]
        for key, kw in {"default": {}, "n": {"refit": True, "analysis_n": 8, "logrank_p": 0.3},
                        "p": {"refit": True, "analysis_n": 9}}.items():
            try:
                recipes.km_survival(groups, **kw)
                errs[key] = "none"
            except ValueError as exc:
                errs[key] = str(exc)
        fig2, (ax2, _t2) = recipes.km_survival(groups, refit=True, analysis_n=9, logrank_p=0.3,
                                               time_points=[0, 2, 4])
        marks2 = [ln for ln in ax2.get_lines() if ln.get_marker() == "|"]
        xlim = ax2.get_xlim()
        plt.close(fig2)
    record("N8 the default draws the exported curve; no censoring -> no censoring marks; the "
           "population (censored = 0) reaches the sidecar",
           not marks and pop.get("mode") == "results" and pop.get("censored") == 0, str(pop))
    record("N8 refitting needs refit=True and analysis_n equal to the rows used; a missing "
           "log-rank P is an error asking to export it from the analysis",
           "off by default" in errs["default"] and "N = 9" in errs["n"]
           and "logrank_p is missing" in errs["p"], str(errs)[:300])
    record("N8 refit: censoring marks only for the group with censoring; no sparse-tail truncation "
           "by default", len(marks2) == 1 and abs(xlim[1] - 4) < 1e-9, f"{len(marks2)} {xlim}")
    q = _paper(tmp / "km_old", "S11_figures")
    _pin(q, "1.15.0")
    buf = io.StringIO()
    with _envset(MEDPAPER_PROJECT=str(q)), redirect_stdout(buf):
        try:
            fig3, _ = recipes.km_survival(groups)
            legacy = fig3.medpaper_population.get("mode") == "legacy_refit"
            plt.close(fig3)
        except Exception as exc:  # noqa: BLE001
            legacy = f"{type(exc).__name__}: {exc}"
    record("N8 a paper pinned before 1.16.0 keeps the old km_survival(groups) default with a "
           "warning", legacy is True and "pinned before engine 1.16.0" in buf.getvalue(),
           str(legacy) + buf.getvalue()[-200:])
    if shutil.which("Rscript"):
        code = ('source(file.path(Sys.getenv("MEDPAPER_ROOT"), "tools/figures/R/medfig.R")); '
                'source(file.path(Sys.getenv("MEDPAPER_ROOT"), "tools/figures/R/recipes.R")); '
                'd <- data.frame(time = c(1, 2, 3, 4, 5, 6), status = 1, arm = c("A", "A", "A", "B", "B", "B")); '
                'k <- recipe_km(d, "time", "status", "arm", times = c(0, 3, 6), refit = TRUE, analysis_n = 6); '
                'cat("CENSORED", attr(k, "medpaper_population")$censored, "\\n")')
        proc = subprocess.run(["Rscript", "-e", code], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", env=_env(q), timeout=300)
        record("N8 R recipe_km: no censoring -> no censoring marks (population censored = 0)",
               "CENSORED 0" in proc.stdout, (proc.stdout + proc.stderr)[-200:])


# ------------------------------------------------------------------------------ N9
def run_n9(tmp: Path, record, section) -> None:
    from wfcore import cli, gates, overrides
    from wfcore.checks import Result
    from wfcore.state import State
    section("1.16.0 N9: the S24/S25 final-package boundaries cannot be forced")
    st_new = SimpleNamespace(engine_pin="1.16.0")
    st_old = SimpleNamespace(engine_pin="1.15.0")
    record("N9 the final-package gates are non-overridable on S24/S25 only, from engine 1.16.0, and "
           "protected from paper overrides",
           all(cli.non_overridable(c, "S25_submission_audit", st_new) for c in (
               "bundle_matches_freeze", "submission_audit_matches_freeze", "decision_recorded",
               "final_copy_verified", "package_content_matches_baseline"))
           and cli.non_overridable("decision_recorded", "S24_package_human_review", st_new)
           and not cli.non_overridable("decision_recorded", "S03_protocol", st_new)
           and not cli.non_overridable("decision_recorded", "S25_submission_audit", st_old)
           and all(set(v) <= overrides.PROTECTED_CHECKS for v in cli.FINAL_BOUNDARY_GATES.values()))
    for decision in ("REVISE", "BLOCKED"):
        p = _paper(tmp / f"s25_{decision}", "S25_submission_audit")
        _w(p, "08_submission/independent_submission_audit.md", "# Verdict\n\nREVISE\n")
        State(p, ".wf").load().record_decision("submission_package_independent_audit", decision,
                                               "the independent audit asked for corrections first")
        proc = _run(p, "tools/wf.py", "advance", "--force", "--note", "forced", cwd=p)
        text = _out(proc)
        record(f"N9 --force cannot advance S25 with a {decision} decision or an audit bound to "
               "another freeze",
               proc.returncode == 2 and "final-package boundary" in text
               and "decision_recorded" in text and "submission_audit_matches_freeze" in text
               and State(p, ".wf").load().current == "S25_submission_audit", text[-400:])
    p = _paper(tmp / "s24", "S24_package_human_review")
    _w(p, "08_submission/package_human_review.md", "# Package presented\n")
    _w(p, "08_submission/package_review_freeze.json", {"files": {}})
    proc = _run(p, "tools/wf.py", "advance", "--force", "--note", "forced", cwd=p)
    record("N9 --force cannot advance S24 without the user's package confirmation",
           proc.returncode == 2 and "final-package boundary" in _out(proc)
           and "decision_recorded" in _out(proc), _out(proc)[-300:])

    # A legitimate PASS advances (gate results stubbed: the full S25 package is tested elsewhere).
    p = _paper(tmp / "s25_pass", "S25_submission_audit")
    st = State(p, ".wf").load()
    st.record_decision("submission_package_independent_audit", "PASS",
                       "the independent audit found no issue requiring correction")
    real = gates.run_stage
    outcomes = {}
    try:
        for label, failing in (("pass", None), ("revise", "decision_recorded")):
            gates.run_stage = (lambda *a, _f=failing, **k: [
                Result(_f != c, c, "stub") for c in ("decision_recorded", "bundle_matches_freeze")])
            with _envset(MEDPAPER_PROJECT=str(p)), redirect_stdout(io.StringIO()):
                outcomes[label] = cli.cmd_advance(SimpleNamespace(force=True, note="audit PASS"))
            if label == "pass":
                outcomes["after"] = State(p, ".wf").load().status_of("S25_submission_audit")
                stt = State(p, ".wf").load()
                stt.data["current"] = "S25_submission_audit"
                stt.stage_info("S25_submission_audit")["status"] = "active"
                stt.save()
    finally:
        gates.run_stage = real
    record("N9 a legitimate PASS advances; the same --force with a failing audit decision does not",
           outcomes.get("pass") == 0 and outcomes.get("after") == "done"
           and outcomes.get("revise") == 2, str(outcomes))


# ------------------------------------------------------------------------------ N10
def run_n10(tmp: Path, record, section) -> None:
    import importlib.util
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from wfcore.checks.v1160 import display_hashes
    from wfcore.state import State
    section("1.16.0 N10: Python 3.12 floor, the look before Results bound to display hashes")
    spec = importlib.util.spec_from_file_location("mp_bootstrap", ROOT / "bootstrap.py")
    boot = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(boot)
    req = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    boot.VENV = tmp / "no_venv"
    boot.sys = SimpleNamespace(version_info=(3, 11, 9), version="3.11.9 (test)",
                               executable=sys.executable)
    buf = io.StringIO()
    with redirect_stdout(buf):
        made = boot.create_venv(None)
    record("N10a without uv, Python < 3.12 is refused with a clear message (NumPy 2.5 / SciPy 1.18 "
           "need 3.12+)", boot.SCIENCE_PYTHON == (3, 12) and "numpy==2.5" in req
           and "scipy==1.18" in req and made is False and "3.12+" in buf.getvalue(), buf.getvalue())

    p = _paper(tmp / "look", "S09_results")
    _w(p, "01_protocol/artifact_plan.json", {"main_tables": [], "main_figures": [
        {"id": "Figure 1", "file": "05_figures/out/Figure1.png"}]})
    png = p / "05_figures/out/Figure1.png"
    png.parent.mkdir(parents=True, exist_ok=True)
    plt.imsave(png, np.zeros((40, 60, 3)))
    from figures import qc
    with _envset(MEDPAPER_PROJECT=str(p)), redirect_stdout(io.StringIO()):
        qc.contact_sheet(with_tables=True)
    State(p, ".wf").load().record_decision("displays_seen_before_results", "YES",
                                           "looked at every display on one contact sheet")
    first = _gate(p, "displays_seen_current", "S09_results")
    plt.imsave(png, np.ones((40, 60, 3)))
    stale = _gate(p, "displays_seen_current", "S09_results")
    buf = io.StringIO()
    with _envset(MEDPAPER_PROJECT=str(p)), redirect_stdout(buf):
        qc.contact_sheet(with_tables=True)
    sheet = json.loads((p / "05_figures/qc/displays_sheet.json").read_text(encoding="utf-8"))
    State(p, ".wf").load().record_decision("displays_seen_before_results", "YES",
                                           "looked again at the changed figure on the new sheet")
    again = _gate(p, "displays_seen_current", "S09_results")
    record("N10b the look before Results is bound to the display hashes: a changed display makes "
           "it stale, one new contact sheet (changed displays marked) and decision refresh it",
           first.ok and not stale.ok and "Figure 1" in stale.detail and sheet["changed"] == ["Figure 1"]
           and "CHANGED" in buf.getvalue() and again.ok
           and sheet["displays"] == display_hashes(p), f"{first.detail} | {stale.detail} | {again.detail}")


GROUPS = [("n1", run_n1), ("n2", run_n2), ("n3", run_n3), ("n4", run_n4), ("n5", run_n5),
          ("n6", run_n6), ("n7", run_n7), ("n8", run_n8), ("n9", run_n9), ("n10", run_n10)]


if __name__ == "__main__":  # quick subset run: python tools/selftest_v1160.py [groups]
    import tempfile
    os.environ.setdefault("MEDPAPER_STDOUT_ENCODING", "utf-8")
    fails = []

    def _record(name, ok, detail=""):
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail and not ok else ""))
        if not ok:
            fails.append(name)
        return ok
    with tempfile.TemporaryDirectory(prefix="mp_v1160_") as d:
        run(Path(d), _record, lambda t: print(f"\n{t}\n" + "-" * len(t)), " ".join(sys.argv[1:]))
    print(f"\n{len(fails)} failure(s)")
    sys.exit(1 if fails else 0)
