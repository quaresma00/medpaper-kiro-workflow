"""1.20.0 regression tests: the visible text of tables and figures, for a clinical reader.
V2 inventory, V3 rules (both ways), V4 build-time relabelling (tables, Python, a real R
render), V5 writer bundle + apply + gate, V6 reviewer bundle, V7 cards/prompts, V8 rebuild /
render parameters, release policy for pinned papers. Counterexample first: the 1.19.0 gates
passed the analysis-report strings below. Synthetic fixtures only - no real paper, dataset or
network is used.

Called from tools/selftest.py.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from selftest_v1140 import _env, _envset, _gate, _paper, _run, _w  # noqa: E402

PLAN = {"main_figures": [{"id": "Figure 1", "file": "05_figures/out/Figure1.png", "archetype": "forest_plot"}],
        "main_tables": [{"id": "Table 1", "file": "04_tables/main/Table1.xlsx"},
                        {"id": "Table 2", "file": "04_tables/main/Table2.xlsx", "non_redundancy": "adjusted associations"}],
        "supp_figures": [], "supp_tables": []}
DICT = {"terms": [
    {"internal": "sexM", "label": "Male sex", "definition": "male compared with female sex"},
    {"internal": "age_grp>=65", "label": "Age \u226565 years", "definition": "age 65 years or older"},
    {"internal": "exposure_strict", "label": "Strict exposure definition", "definition": "two or more prescriptions within 90 days"},
    {"internal": "age", "label": "Age", "unit": "years", "definition": "age at baseline"},
    {"internal": "site_a", "label": "Hospital A", "definition": "the first hospital"},
    {"internal": "site_b", "label": "Hospital B", "definition": "the second hospital"},
    {"internal": "site", "label": "Hospital", "definition": "the treating hospital"}]}
BAD_HEADER = ["term", "estimate", "std.error", "statistic", "p.value", "conf.low", "conf.high"]
BAD_ROWS = [["age_grp<65", "1.00 (1.00-1.00)", "", "", "", "", ""],
            ["sexM", 0.19, 0.05, 3.8, 1.2e-05, 0.09, 0.29],
            ["age_grp>=65", 0.123456, 0.04, 2.9, "<2e-16", 0.04, 0.2],
            ["trt:time", 0.05, 0.02, 2.1, 0.03, 0.01, 0.09],
            ["factor(stage)III", 0.74, 0.11, 6.7, 0.02, 0.52, 0.96],
            ["Diabetes", "TRUE", "FALSE", "", "", "", ""]]
CLINICAL_ROWS = [["Age, years", "61.2 (10.3)", "62.0 (9.8)"], ["Male sex, n (%)", "512 (51.2)", "210 (52.5)"],
                 ["HbA1c, %", "7.1 (1.2)", "7.3 (1.1)"], ["eGFR, mL/min/1.73 m2", "78.4 (15.2)", "76.0 (14.8)"],
                 ["COVID-19 vaccination, n (%)", "640 (64.0)", "251 (62.8)"], ["T2DM, n (%)", "301 (30.1)", "130 (32.5)"],
                 ["BRCA1 mutation, n (%)", "12 (1.2)", "5 (1.3)"], ["Hypertension (ICD-10 I10), n (%)", "455 (45.5)", "190 (47.5)"],
                 ["Prior osimertinib (AZD9291), n (%)", "20 (2.0)", "9 (2.3)"], ["Cholesterol, mg/dL", "190.2 (35.1)", "188.7 (34.0)"],
                 ["Body mass index, kg/m2", "27.1 (4.2)", "27.5 (4.0)"], ["Blood pressure, mmHg", "132 (15)", "131 (14)"],
                 ["Median follow-up (IQR), months", "24 (12-36)", "25 (13-37)"]]
CLINICAL_NOTES = ["Values are mean (SD), median (IQR) or n (%).",
                  "Abbreviations: SD, standard deviation; IQR, interquartile range; HbA1c, glycated haemoglobin; "
                  "eGFR, estimated glomerular filtration rate; T2DM, type 2 diabetes mellitus; BRCA1, breast "
                  "cancer gene 1; ICD-10, International Classification of Diseases, 10th revision; COVID-19, "
                  "coronavirus disease 2019."]


def run(tmp: Path, record, section, only: str = "") -> None:
    tmp.mkdir(parents=True, exist_ok=True)
    for name, fn in GROUPS:
        if not only or name in only.split():
            fn(tmp / name, record, section)


def _pin(p: Path, version: str) -> None:
    st = json.loads((p / ".wf/state.json").read_text(encoding="utf-8"))
    st["engine_pin"] = version
    (p / ".wf/state.json").write_text(json.dumps(st), encoding="utf-8")


def _fixture(p: Path, kind: str = "bad", relabel: str | None = "false") -> Path:
    from tables import threeline as tl
    _paper(p, "S12_reconcile")
    _w(p, "01_protocol/artifact_plan.json", PLAN)
    _w(p, "01_protocol/display_dictionary.json", DICT)
    if relabel is not None:
        _w(p, ".wf/config.toml", f'[targets]\ndisplay_relabel = "{relabel}"\n')
    with _envset(MEDPAPER_PROJECT=str(p)):
        if kind == "bad":
            tl.write_table(p / "04_tables/main/Table1.xlsx", "Table 1", "Table 1. Baseline by exposure_strict",
                           ["Characteristic", "Overall", "exposure_strict"],
                           [["Age", "61.2 (10.3)", "62.0 (9.8)"], ["sexM", "512 (51.2%)", "210 (52.5%)"]],
                           ["Values are mean (SD) or n (%)."])
            tl.write_table(p / "04_tables/main/Table2.xlsx", "Table 2", "Table 2. Model 3 estimates with IPTW",
                           BAD_HEADER, BAD_ROWS, ["Estimates from the logistic model."])
        else:
            tl.write_table(p / "04_tables/main/Table1.xlsx", "Table 1",
                           "Table 1. Baseline characteristics of 1,000 patients",
                           ["Characteristic", "Overall (N = 1,000)", "Strict exposure (n = 400)"],
                           CLINICAL_ROWS, CLINICAL_NOTES)
            tl.write_table(p / "04_tables/main/Table2.xlsx", "Table 2",
                           "Table 2. Factors associated with the outcome in 1,000 patients",
                           ["Characteristic", "OR (95% CI)", "P value"],
                           [["Age <65 years", "Reference", ""], ["Age \u226565 years", "1.13 (1.04 to 1.22)", "0.004"],
                            ["Male sex", "1.21 (1.09 to 1.34)", "<0.001"]],
                           ["ORs were weighted by the inverse probability of treatment (IPTW; each patient "
                            "weighted so that the groups are comparable).",
                            "Abbreviations: OR, odds ratio; CI, confidence interval; IPTW, inverse "
                            "probability of treatment weighting."])
    side = {"figure": "Figure1", "archetype": "forest_plot", "figure_text": [],
            "axis_scales": {"x": "log-10", "y": "identity"}}
    if kind == "bad":
        side["text_roles"] = [{"text": t, "role": r, **({"axis": a} if a else {})} for t, r, a in (
            ("log(ROR)", "axis title", "x"), ("term", "axis title", "y"), ("sexM", "tick label", "y"),
            ("value", "legend title", None), ("group: A", "strip", None), ("Model 2", "legend key", None),
            ("1.2e-05", "annotation", None))]
        leg = "## Figure 1. Forest plot of model terms.\n\nEstimates from the model.\n"
    else:
        side["text_roles"] = [{"text": t, "role": r, **({"axis": a} if a else {})} for t, r, a in (
            ("Reporting odds ratio (95% CI), log scale", "axis title", "x"), ("Male sex", "tick label", "y"),
            ("Model 2", "legend key", None), ("0.5", "tick label", "x"), ("ROR 1.85 (1.20 to 2.85)", "annotation", None))]
        leg = ("## Figure 1. Factors associated with the outcome.\n\nModel 2: adjusted for age and sex. "
               "Abbreviations: ROR, reporting odds ratio (how much more often the event is reported with this drug "
               "than with all other drugs); CI, confidence interval.\n")
    side["figure_text"] = sorted({t["text"] for t in side["text_roles"]})
    _w(p, "05_figures/qc/Figure1.artist.json", side)
    _w(p, "05_figures/legends.md", leg)
    _w(p, "04_tables/table_captions.md", "## Table 1. Baseline.\n\n## Table 2. Factors.\n" if kind == "bad" else
       "## Table 1. Baseline characteristics.\n\n## Table 2. Factors associated with the outcome.\n")
    return p


# ------------------------------------------------------------------------------ V1/V3
def run_rules(tmp: Path, record, section) -> None:
    from wfcore import displaytext
    section("1.20.0 V1/V3: analysis-report text in tables and figures (counterexample first)")
    bad = _fixture(tmp / "bad", "bad")
    old = {name: _gate(bad, name, stage, **spec) for name, stage, spec in (
        ("engineering_language_clean", "S10_tables", {"displays": "tables"}),
        ("display_values_presented", "S10_tables", {"displays": "tables"}))}
    record("V1 counterexample: the 1.19.0 display gates pass p.value / std.error headers, sexM, "
           "1.2e-05 and '1.00 (1.00-1.00)'",
           all(r.ok for r in old.values()), " | ".join(r.detail[:80] for r in old.values()))
    inv = displaytext.inventory(bad)
    finds = displaytext.findings(bad, inv)
    got = {(f["display"], f["text"]): f["rule"] for f in finds}
    want = {("Table 2", "p.value"): "c", ("Table 2", "std.error"): "c", ("Table 2", "estimate"): "c",
            ("Table 2", "term"): "b", ("Table 2", "sexM"): "a", ("Table 2", "trt:time"): "a",
            ("Table 2", "factor(stage)III"): "a", ("Table 2", "age_grp>=65"): "a",
            ("Table 2", "1.00 (1.00-1.00)"): "d", ("Table 2", "1.2e-05"): "d", ("Table 2", "0.123456"): "d",
            ("Table 2", "<2e-16"): "d", ("Table 2", "TRUE"): "a", ("Table 1", "Age"): "e",
            ("Table 1", "exposure_strict"): "a", ("Table 2", "Table 2. Model 3 estimates with IPTW"): "f",
            ("Table 2", "IPTW"): "g", ("Figure 1", "log(ROR)"): "a", ("Figure 1", "term"): "b",
            ("Figure 1", "value"): "b", ("Figure 1", "group: A"): "a", ("Figure 1", "Model 2"): "f",
            ("Figure 1", "1.2e-05"): "d", ("Figure 1", "sexM"): "a"}
    missing = {k: v for k, v in want.items() if got.get(k) != v}
    record("V3 rules a-g flag every counterexample string with its display, role and rule",
           not missing, f"missing/mismatched: {missing}; got {sorted(got.items())[:40]}")
    roles = {(s["role"], s["text"]) for s in inv["displays"]["Table 2"]["strings"]}
    record("V2 inventory roles: title, column header, row label, cell, cell text, footnote, caption",
           {("title", "Table 2. Model 3 estimates with IPTW"), ("column header", "p.value"),
            ("row label", "sexM"), ("cell", "0.123456"), ("cell text", "TRUE"),
            ("footnote", "Estimates from the logistic model.")} <= roles
           and any(r == "caption" for r, _ in roles), str(sorted(roles))[:400])
    sugg = [f for f in finds if f["text"] == "p.value"][0]["suggest"]
    record("V3 messages suggest the clinical layout or the dictionary entry",
           "OR (95% CI)" in sugg and any("display_dictionary.json" in f["suggest"] for f in finds), sugg)
    good = _fixture(tmp / "good", "clinical")
    gf = displaytext.findings(good)
    review: list[str] = []
    displaytext.findings(good, None, review)
    record("V3 legitimate clinical text passes: n (%), median (IQR), P value, CI, HbA1c, eGFR, "
           "T2DM, COVID-19, BRCA1, ICD-10, AZD9291, mg/dL, kg/m2, mmHg, defined Model 2, ROR and "
           "IPTW spelled out", not gf, "; ".join(displaytext.line(f) for f in gf)[:600])
    record("V3 a spelled-out technical term goes to the reviewer list (undecidable plain wording)",
           any("IPTW" in r for r in review) and any("ROR" in r for r in review), str(review))
    abbr = _gate(good, "display_abbreviations_defined", "S11_figures")
    record("V3 abbreviation check: plural ORs/CIs, ICD from ICD-10 and a code defined in a cell "
           "count as defined", abbr.ok, abbr.detail[:300])
    wide = tmp / "wide"
    _fixture(wide, "clinical")
    from tables import threeline as tl
    with _envset(MEDPAPER_PROJECT=str(wide)):
        tl.write_table(wide / "04_tables/main/Table2.xlsx", "Table 2", "Table 2. Factors in 1,000 patients",
                       ["Characteristic"] + [f"Site {i}, n (%)" for i in range(1, 10)],
                       [["Male sex"] + ["5 (50.0)"] * 9], ["Values are n (%)."])
    wf_ = displaytext.findings(wide)
    record("V3 h: a main table with more than 8 data columns is advisory (warn)",
           any(f["rule"] == "h" and f["severity"] == "warn" for f in wf_), str(wf_)[:200])
    _w(bad, ".wf/language_allowlist.json", {"terms": [
        {"term": "std.error", "reason": "methods paper reports model output", "scope": "all"}]})
    after = {f["text"] for f in displaytext.findings(bad)}
    record("V3 a paper-local allowlist entry with a reason exempts that exact string",
           "std.error" not in after and "p.value" in after)


# ------------------------------------------------------------------------------ V2/V5 gate
def run_gates(tmp: Path, record, section) -> None:
    from wfcore import displaytext, registry
    section("1.20.0 V2/V5: inventory, gates, writer bundle, apply")
    p = _fixture(tmp / "g", "bad")
    s09 = _gate(p, "display_text_resolved", "S09_results")
    s10 = _gate(p, "first_reader_displays", "S10_tables", kinds=["table"], include=["display_text"],
                severity="warn")
    record("V3/V5 display_text_resolved blocks at S09 (bound to the inventory hash); S10 "
           "first_reader_displays carries the findings", not s09.ok and s09.severity == "fail"
           and "inventory" in s09.detail and not s10.ok and "[column header]" in s10.detail,
           s09.detail[:200] + " | " + s10.detail[:300])
    pipe = registry.load()
    specs = {(s.id, g["check"]): g for s in pipe.stages for g in s.gate}
    record("V5 the gate sits at S09 (next to displays_seen_before_results), S12 and S23 with "
           "since = 1.20.0; S10/S11 warn",
           all(specs.get((sid, "display_text_resolved"), {}).get("since") == "1.20.0"
               for sid in ("S09_results", "S12_reconcile", "S23_package"))
           and specs[("S10_tables", "first_reader_displays")].get("severity") == "warn"
           and "display_text" in specs[("S11_figures", "first_reader_displays")].get("include", []))
    q = _fixture(tmp / "pinned", "bad")
    _pin(q, "1.19.0")
    pr = _gate(q, "display_text_resolved", "S23_package")
    record("V5 a paper pinned before 1.20.0 keeps its gate set (pass with a note); `wf displays "
           "text` still works on it", pr.ok and "1.20.0" in pr.detail, pr.detail)
    inv_path = p / displaytext.INV_REL
    h1 = json.loads(inv_path.read_text(encoding="utf-8"))
    leg = p / "05_figures/legends.md"
    leg.write_text(leg.read_text(encoding="utf-8") + "\nModel 2: adjusted for age.\n", encoding="utf-8")
    inv2 = displaytext.inventory(p)
    record("V2 the inventory is incremental: an edited legend re-extracts that figure only",
           inv2["displays"]["Table 2"]["hash"] == h1["displays"]["Table 2"]["hash"]
           and inv2["displays"]["Figure 1"]["hash"] != h1["displays"]["Figure 1"]["hash"]
           and inv2["hash"] != h1["hash"])
    r = _run(p, "tools/wf.py", "displays", "text", "--md")
    out = r.stdout + r.stderr
    man = (p / displaytext.BUNDLE_REL / "MANIFEST.md").read_text(encoding="utf-8")
    record("V2/V5 `wf displays text --md` writes the inventory, the Markdown copy and the writer "
           "bundle (strings with context, no code or JSON)", r.returncode == 2 and "p.value" in out
           and (p / displaytext.INV_MD).is_file() and "The display shows" in man and "Where:" in man
           and ".py" not in man and "03_analysis" not in man, out[-300:])
    r2 = _run(p, "tools/wf.py", "displays", "text")
    man2 = (p / displaytext.BUNDLE_REL / "MANIFEST.md").read_text(encoding="utf-8")
    record("V5 the bundle is incremental: unchanged strings are listed as still open, not re-sent",
           "## New or changed (0)" in man2 and "Still open" in man2, (r2.stdout or "")[-200:])
    ids = json.loads((p / displaytext.STATE_REL).read_text(encoding="utf-8"))["ids"]
    by_text = {v["text"]: k for k, v in ids.items()}
    rows = [f"| {by_text['exposure_strict']} | Strict exposure definition |  | two or more prescriptions | |",
            f"| {by_text['Age']} | Age | years | age at baseline | |",
            f"| {by_text['term']} | Characteristic | | | |",
            f"| {by_text['IPTW']} | | | | IPTW, inverse probability of treatment weighting (patients weighted so the groups are comparable). |"]
    _w(p, displaytext.REPLY_REL, "| ID | Clinical wording | Unit | Definition (one line) | Footnote/legend sentence |\n|---|---|---|---|---|\n"
       + "\n".join(rows) + "\n")
    ap = _run(p, "tools/wf.py", "displays", "apply")
    d = json.loads((p / "01_protocol/display_dictionary.json").read_text(encoding="utf-8"))
    age = [t for t in d["terms"] if t["internal"] == "age"][0]
    notes = (p / displaytext.NOTES_REL).read_text(encoding="utf-8") if (p / displaytext.NOTES_REL).is_file() else ""
    record("V5 `wf displays apply`: labels/units into the dictionary, other wording listed for the "
           "scripts and legends", ap.returncode == 0 and age.get("unit") == "years"
           and any(t["internal"] == "exposure_strict" for t in d["terms"])
           and "Characteristic" in notes and "IPTW, inverse probability" in notes,
           (ap.stdout + ap.stderr)[-300:])


# ------------------------------------------------------------------------------ V4
def run_relabel(tmp: Path, record, section) -> None:
    import openpyxl
    from tables import threeline as tl
    from wfcore import displaytext
    section("1.20.0 V4: dictionary-driven relabelling at build time")
    p = _fixture(tmp / "on", "clinical", relabel=None)
    with _envset(MEDPAPER_PROJECT=str(p)):
        tl.write_table(p / "04_tables/main/Table1.xlsx", "Table 1", "Table 1. Baseline in 1,000 patients",
                       ["Characteristic", "Overall (N = 1,000)", "exposure_strict"],
                       [["age", 61.25, "62.0 (9.8)"], ["sexM", "512 (51.2)", "210 (52.5)"],
                        ["  site_a", "300 (30.0)", "120 (30.0)"]], ["Values are mean (SD) or n (%)."])
        err = ""
        try:
            tl.write_table(p / "temp/x.xlsx", "T", "Table 9. Probe", ["term", "std.error"], [["x_y", "1"]], ["Probe."])
        except ValueError as exc:
            err = str(exc)
    ws = openpyxl.load_workbook(p / "04_tables/main/Table1.xlsx").active
    vals = [[c.value for c in r] for r in ws.iter_rows()]
    record("V4 the table builder maps headers, row labels (with unit) and levels; numbers untouched",
           vals[1][2] == "Strict exposure definition" and vals[2][0] == "Age, years" and vals[2][1] == 61.25
           and vals[3][0] == "Male sex" and vals[4][0] == "  Hospital A", str(vals[:5]))
    record("V4 a header or row label that stays code-like fails with the exact string and the "
           "suggested entry / clinical layout", "std.error" in err and "OR (95% CI)" in err, err)
    q = _fixture(tmp / "pinned", "clinical", relabel=None)
    _pin(q, "1.19.0")
    on_q = displaytext.relabel_enabled(q)
    _w(q, ".wf/config.toml", '[targets]\ndisplay_relabel = "true"\n')
    record("V4 relabelling is off for a paper pinned before 1.20.0 until display_relabel = true "
           "(or `wf migrate --yes`); on by default for new papers",
           displaytext.relabel_enabled(p) and not on_q and displaytext.relabel_enabled(q))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from figures import style
    with _envset(MEDPAPER_PROJECT=str(p)):
        style.apply_style()
        fig, ax = plt.subplots(figsize=(3.4, 2.4))
        ax.bar(["site_a", "site_b"], [120, 80], label="exposure_strict")
        ax.set_xlabel("site")
        ax.set_ylabel("Number of patients")
        ax.legend(title="site")
        style.save(fig, p / "05_figures/out/Figure1", archetype="forest_plot")
        plt.close(fig)
        fig2, ax2 = plt.subplots(figsize=(3, 2))
        ax2.bar(["grp_x", "grp_y"], [1, 2])
        perr = ""
        try:
            style.save(fig2, p / "temp/probe", archetype="other")
        except ValueError as exc:
            perr = str(exc)
        plt.close(fig2)
    side = json.loads((p / "05_figures/qc/Figure1.artist.json").read_text(encoding="utf-8"))
    roles = {(t["role"], t["text"]) for t in side.get("text_roles", [])}
    record("V4/V2 Python style.save() relabels axis title, ticks, legend title and keys; the sidecar "
           "records each string's role and the axis scales",
           {("axis title", "Hospital"), ("tick label", "Hospital A"), ("legend title", "Hospital"),
            ("legend key", "Strict exposure definition")} <= roles and side.get("axis_scales", {}).get("x") == "linear"
           and side.get("presentation", {}).get("display_labels") not in (None, "off")
           and "grp_x" in perr, f"{sorted(roles)} | {perr}")
    if not shutil.which("Rscript"):
        record("V4 R relabel: Rscript available", False, "Rscript missing")
        return
    script = p / "05_figures/code/fig_r.R"
    _w(p, "05_figures/code/fig_r.R", (
        'source(file.path(Sys.getenv("MEDPAPER_ROOT"), "tools/figures/R/medfig.R"))\n'
        'suppressPackageStartupMessages(library(ggplot2))\n'
        'd <- data.frame(def = rep(c("exposure_strict", "sexM"), each = 2), site = rep(c("site_a", "site_b"), 2),\n'
        '                n = c(120, 80, 95, 60), est = c(1.2, 1.5, 0.8, 2.1))\n'
        'p <- ggplot(d, aes(def, n, fill = site)) + geom_col(position = "dodge") +\n'
        '  scale_fill_manual(values = c(site_a = "#0072B2", site_b = "#E69F00")) + facet_wrap(~site) +\n'
        '  labs(x = NULL, y = "Number of patients") + theme_medpaper()\n'
        'save_medpaper(p, "05_figures/out/Figure1", archetype = "bar_dot")\n'
        'q <- ggplot(d, aes(est, def)) + geom_point() + scale_x_log10() + labs(x = "Odds ratio (95% CI), log scale", y = NULL) + theme_medpaper()\n'
        'save_medpaper(q, "temp/forest", archetype = "forest_plot")\n'
        'bad <- ggplot(data.frame(g = c("grp_x", "grp_y"), v = 1:2), aes(g, v)) + geom_col() + theme_medpaper()\n'
        'res <- tryCatch({ save_medpaper(bad, "temp/bad", archetype = "bar_dot"); "no error" }, error = function(e) conditionMessage(e))\n'
        'cat("BADRESULT:", res, "\\n")\n'))
    env = {**_env(p), "MEDPAPER_PROJECT": str(p), "MEDPAPER_ROOT": str(ROOT),
           "MEDPAPER_DISPLAY_LABELS": displaytext.relabel_env(p), "MEDPAPER_SCRIPT": "05_figures/code/fig_r.R"}
    proc = subprocess.run(["Rscript", str(script)], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=env, cwd=str(p), timeout=600)
    out = proc.stdout + proc.stderr
    try:
        art = json.loads((p / "05_figures/qc/Figure1.artist.json").read_text(encoding="utf-8"))
        fart = json.loads((p / "temp/qc/forest.artist.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        art, fart = {}, {}
    rroles = {(t.get("role"), t.get("text")) for t in art.get("text_roles", [])}
    record("V4 real R render: save_medpaper() relabels ticks, legend title/keys (manual scale keyed "
           "by internal names), facet strips; the sidecar has text roles, log axis and the relabel hash",
           proc.returncode == 0 and {("tick label", "Strict exposure definition"), ("tick label", "Male sex"),
                                     ("legend title", "Hospital"), ("legend key", "Hospital A"),
                                     ("strip", "Hospital B"), ("axis title", "Number of patients")} <= rroles
           and "log" in str(fart.get("axis_scales", {}).get("x", ""))
           and art.get("presentation", {}).get("display_labels") == json.loads(env["MEDPAPER_DISPLAY_LABELS"])["hash"]
           and "BADRESULT: figure text without a clinical label: 'grp_x'" in out,
           f"rc={proc.returncode} {sorted(rroles)} | {out[-400:]}")
    from wfcore import displaytext as dt
    inv = dt.inventory(p)
    fr = [f for f in dt.findings(p, inv) if f["display"] == "Figure 1"]
    record("V4 after relabelling the R figure's visible text passes the display-text rules",
           not fr, "; ".join(dt.line(f) for f in fr))


# ------------------------------------------------------------------------------ V6/V8/R
def run_release(tmp: Path, record, section) -> None:
    from wfcore import displaytext, registry, renderparams, reviewrounds
    from wfcore.state import State
    section("1.20.0 V6/V7/V8 and the release policy")
    p = _fixture(tmp / "rv", "bad")
    _w(p, "05_figures/qc/displays_sheet.png", "png")
    out = p / ".wf/review_bundle/R1"
    (out / "files").mkdir(parents=True, exist_ok=True)
    lines = reviewrounds._display_text_files(p, out)
    txt = (out / "files/display_text.md").read_text(encoding="utf-8")
    rev = (ROOT / ".kiro/agents/medpaper-reviewer.md").read_text(encoding="utf-8")
    wri = (ROOT / ".kiro/agents/medpaper-clinical-writer.md").read_text(encoding="utf-8")
    record("V6 the review bundle carries the display sheet and the inventory with flagged strings; "
           "the reviewer rubric asks whether each display is understandable on its own",
           len(lines) == 2 and "[column header] p.value" in txt and "Strings the checks still flag" in txt
           and "understandable on its own by a" in rev and "understandable on its own" in reviewrounds.BRIEF
           and "display_wording.md" in wri, str(lines))
    snap = renderparams.snapshot(renderparams.TAB_KEYS, p)
    _w(p, ".wf/config.toml", '[targets]\ndisplay_relabel = "true"\n')
    snap_on = renderparams.snapshot(renderparams.TAB_KEYS, p)
    d = json.loads((p / "01_protocol/display_dictionary.json").read_text(encoding="utf-8"))
    d["terms"].append({"internal": "trt:time", "label": "Treatment by time interaction", "definition": "x" * 12})
    _w(p, "01_protocol/display_dictionary.json", d)
    snap_new = renderparams.snapshot(renderparams.TAB_KEYS, p)
    record("V8 render parameters record the relabel map ('off' or its hash): a dictionary change "
           "makes the displays stale, so `wf rebuild` re-renders them (presentation, no science)",
           snap.get("display_labels") == "off" and snap_on["display_labels"] not in ("off", None)
           and snap_new["display_labels"] != snap_on["display_labels"])
    st = State(p, ".wf").load()
    st.data["pipeline_version"] = "1.19.0"
    st.data["engine_pin"] = "1.19.0"
    st.migrate_pipeline("1.20.0", [s.id for s in registry.load().stages])
    st.migrate_pipeline("1.20.0", [s.id for s in registry.load().stages])
    notes = [e for e in st.data.get("events", []) if e.get("kind") == "requirements_changed"
             and str(e.get("detail", "")).startswith("1.20.0")]
    cards = {c.stem: len(c.read_text(encoding="utf-8")) for c in (ROOT / "pipeline/stages").glob("S*.md")}
    s10 = (ROOT / "pipeline/stages/S10_tables.md").read_text(encoding="utf-8")
    s11 = (ROOT / "pipeline/stages/S11_figures.md").read_text(encoding="utf-8")
    s09 = (ROOT / "pipeline/stages/S09_results.md").read_text(encoding="utf-8")
    skill = (ROOT / ".kiro/skills/medpaper-pipeline/SKILL.md").read_text(encoding="utf-8")
    record("R pipeline 1.20.0; a 1.19.0 paper gets one 1.20.0 event and stays pinned; cards <= "
           "limit carry the display-writing guidance; SKILL names the display wording pass",
           registry.load().meta.get("version") in ("1.20.0", "1.21.0", "1.22.0", "1.23.0") and len(notes) == 1 and st.engine_pin == "1.19.0"
           and max(cards.values()) <= registry.CARD_MAX_CHARS and "wf displays text" in s10
           and "log" in s11 and "displays/MANIFEST.md" in s09 and "wf displays text" in skill,
           f"{len(notes)} {max(cards.values())}")


GROUPS = [("rules", run_rules), ("gates", run_gates), ("relabel", run_relabel), ("release", run_release)]


if __name__ == "__main__":
    import tempfile
    results = []

    def _rec(name, ok, detail=""):
        results.append(ok)
        print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"\n     {detail}"))
        return ok

    with tempfile.TemporaryDirectory() as t:
        run(Path(t), _rec, lambda s: print(f"== {s}"), " ".join(sys.argv[1:]))
    print(f"{sum(results)}/{len(results)}")
