"""1.27.0 regression tests: figures carry little text - no title, subtitle or caption line in
the image, short panel headings, no explanatory sentences - and every table/figure string is
held to the prose rules (no AI phrasing, spin or data-processing wording).

rules    figuretext on synthetic inventory records and sidecars (positive and negative cases,
         data labels, forest-plot table text, flow boxes, pre-1.27.0 sidecars, a journal that
         asks for in-figure titles, a pinned paper).
gate     display_wording_clean at S10 (tables) and S11 (figures), display_text_resolved now
         carries the rules, first_reader_displays does not repeat them, the allowlist.
render   real renders: Python style.save() and R save_medpaper() classify figure title, panel
         heading, subtitle and caption (text_roles_version 2; QC schema accepts it).
release  version, one migration event, gate lines, cards, prompts, SKILL, README, changelog.
Synthetic fixtures only - no real paper, dataset, network or browser. Called from
tools/selftest.py (or `selftest.py --only v1270`).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from wfcore.state import version_tuple as _vt  # noqa: E402
from selftest_v1140 import _env, _envset, _gate, _out, _paper, _w  # noqa: E402
from selftest_v1250 import _pin  # noqa: E402

S10, S11 = "S10_tables", "S11_figures"
PLAN = {"main_tables": [{"id": "Table 1", "file": "04_tables/main/Table1.xlsx", "sheet": "Table 1"}],
        "main_figures": [
            {"id": "Figure 1", "file": "05_figures/out/Figure1.png", "archetype": "bar_dot"},
            {"id": "Figure 2", "file": "05_figures/out/Figure2.png", "archetype": "forest_plot"},
            {"id": "Figure 3", "file": "05_figures/out/Figure3.png", "archetype": "flow_diagram"}],
        "supp_figures": [
            {"id": "Figure S1", "file": "05_figures/out/FigureS1.png", "archetype": "bar_dot"},
            {"id": "Figure S2", "file": "05_figures/out/FigureS2.png", "archetype": "km_survival"}],
        "supp_tables": []}
LEGENDS = ("# Figure legends\n\n## Figure 1. Reporting odds ratios by exposure group.\n\nThe dashed "
           "line marks no association.\n\n## Figure 2. Subgroup analyses.\n\nSquares are point "
           "estimates.\n\n## Figure 3. Selection of reports.\n\nCounts are reports.\n\n"
           "## Figure S1. Reports by year.\n\nBars are counts.\n\n## Figure S2. Survival.\n\n"
           "Curves are Kaplan-Meier estimates.\n")
BAD_F1 = [("Reporting odds ratios across all sensitivity analyses", "title"),
          ("Adjusted for age and sex", "subtitle"), ("Data from FAERS 2004-2024", "caption"),
          ("Overall survival", "panel title"),
          ("Reports from patients treated with oxaliplatin-based adjuvant chemotherapy regimens", "panel title"),
          ("Dashed line indicates the null value", "annotation"),
          ("HR 0.82 (95% CI 0.70-0.96)", "annotation"), ("Favours treatment", "annotation"),
          ("Higher reporting in the exposed group overall", "annotation"), ("*", "annotation"),
          ("Patients who were treated with oxaliplatin", "legend key"),
          ("Hazard ratio (95% CI), log scale", "axis title"),
          ("Trend toward significance", "annotation")]
GOOD_F2 = [("HR (95% CI)", "panel title"), ("Prior myocardial infarction or stroke", "annotation"),
           ("0.82 (0.70-0.96)", "annotation"), ("Age \u226565 years", "tick label"),
           ("Hazard ratio (95% CI), log scale", "axis title")]
FLOW_F3 = [("Reports in FAERS 2004-2024 (n = 24,812,425)", "annotation"),
           ("Reports with the drug of interest recorded as primary or secondary suspect together "
            "with a colorectal cancer indication on the same report and complete age (n = 3,456)",
            "annotation")]


def run(tmp: Path, record, section, only: str = "") -> None:
    tmp.mkdir(parents=True, exist_ok=True)
    for name, fn in GROUPS:
        if not only or name in only.split():
            fn(tmp / name, record, section)


def _side(p: Path, stem: str, roles, version: int | None = 2, n_axes: int = 2,
          archetype: str = "bar_dot") -> None:
    side = {"figure": stem, "archetype": archetype, "n_axes": n_axes, "figure_text": [t for t, _ in roles],
            "text_roles": [{"text": t, "role": r} for t, r in roles], "axis_scales": {}}
    if version:
        side["text_roles_version"] = version
    _w(p, f"05_figures/qc/{stem}.artist.json", side)


def _table(p: Path, title: str, footnotes: list[str]) -> None:
    from tables import threeline as tl
    with _envset(MEDPAPER_PROJECT=str(p)):
        tl.write_table(p / "04_tables/main/Table1.xlsx", "Table 1", title,
                       ["Characteristic", "Overall (N = 1,000)"],
                       [["Age, years, median (IQR)", "61 (52-70)"], ["Male sex, n (%)", "512 (51.2)"]],
                       footnotes)


def _proj(path: Path, stage: str = S11, f1=BAD_F1, title: str = "Table 1. Baseline characteristics "
          "of 1,000 patients.", notes=("Data are n (%) unless stated otherwise.",)) -> Path:
    p = _paper(path, stage)
    _w(p, "01_protocol/artifact_plan.json", PLAN)
    _w(p, "05_figures/legends.md", LEGENDS)
    _w(p, "04_tables/table_captions.md", "# Table captions\n\n## Table 1. Baseline characteristics "
       "of 1,000 patients.\n\nData are n (%) unless stated otherwise.\n")
    _table(p, title, list(notes))
    _side(p, "Figure1", f1)
    _side(p, "Figure2", GOOD_F2, archetype="forest_plot")
    _side(p, "Figure3", FLOW_F3, n_axes=1, archetype="flow_diagram")
    _side(p, "FigureS1", [("Number of reports by year", "title"), ("Year", "axis title")],
          version=None, n_axes=1)  # pre-1.27.0 sidecar, one panel: the title is the figure's
    _side(p, "FigureS2", [("Number at risk", "title"), ("Overall survival, %", "axis title")],
          version=None, n_axes=2, archetype="km_survival")  # pre-1.27.0, two panels: a heading
    return p


def _by(finds, display=None):
    return {(f["role"], f["text"]): f for f in finds if display is None or f["display"] == display}


# ------------------------------------------------------------------------------ rules
def run_rules(tmp: Path, record, section) -> None:
    from wfcore import displaytext, figuretext as ft
    section("1.27.0 rules: titles, explanatory text and phrasing inside tables and figures")
    p = _proj(tmp / "p")
    inv = displaytext.inventory(p)
    finds = [f for d in inv["displays"].values() for f in ft.findings(p, d)]
    f1 = _by(finds, "Figure 1")
    fail = {k for k, f in f1.items() if f["severity"] == "fail"}
    record("i: a whole-figure title, a subtitle, a caption line and a 9-word panel heading are "
           "refused; a 2-word panel heading stays",
           {("title", BAD_F1[0][0]), ("subtitle", BAD_F1[1][0]), ("caption", BAD_F1[2][0]),
            ("panel title", BAD_F1[4][0])} <= fail and ("panel title", "Overall survival") not in f1
           and all(f1[k]["rule"] == "i" for k in (("title", BAD_F1[0][0]), ("subtitle", BAD_F1[1][0]))),
           str(sorted(fail)))
    record("j: explanatory sentences ('Dashed line indicates ...', 'Patients who were treated ...') "
           "and free text over 4 words are refused; data labels, 'Favours treatment' and '*' stay",
           {("annotation", BAD_F1[5][0]), ("legend key", BAD_F1[10][0]),
            ("annotation", BAD_F1[8][0])} <= fail
           and not {("annotation", "HR 0.82 (95% CI 0.70-0.96)"), ("annotation", "Favours treatment"),
                    ("annotation", "*"), ("axis title", "Hazard ratio (95% CI), log scale")} & set(f1),
           str(sorted(f1)))
    record("k: spin inside a figure ('Trend toward significance') is refused",
           f1.get(("annotation", "Trend toward significance"), {}).get("rule") == "k"
           and f1[("annotation", "Trend toward significance")]["severity"] == "fail", str(f1.keys()))
    f2, f3 = _by(finds, "Figure 2"), _by(finds, "Figure 3")
    record("forest-plot table text up to 8 words, its column header 'HR (95% CI)' and estimate "
           "cells pass; a 20+ word flow box is advisory only, the short one passes",
           not f2 and list(f3) == [("flow box", FLOW_F3[1][0])]
           and f3[("flow box", FLOW_F3[1][0])]["severity"] == "warn", str(f2) + str(f3))
    s1, s2 = _by(finds, "Figure S1"), _by(finds, "Figure S2")
    record("pre-1.27.0 sidecars: a single-panel title counts as the figure's title (refused); in a "
           "two-panel figure a short title counts as a panel heading (passes)",
           s1.get(("title", "Number of reports by year"), {}).get("severity") == "fail" and not s2,
           str(s1) + str(s2))
    q = _proj(tmp / "titles")
    _w(q, "01_protocol/journal_profile.json", {"status": "provisional", "in_figure_title": True})
    fq = _by([f for d in displaytext.inventory(q)["displays"].values() for f in ft.findings(q, d)],
             "Figure 1")
    record("a journal that asks for in-figure titles keeps a short title; subtitles and caption "
           "lines stay refused",
           ("title", BAD_F1[0][0]) not in fq and ("subtitle", BAD_F1[1][0]) in fq
           and ("caption", BAD_F1[2][0]) in fq, str(sorted(fq)))
    t = _proj(tmp / "table", title="Table 1. Factors that play a crucial role in outcome.",
              notes=["Data are n (%) unless stated otherwise.", "Missing rows dropped before modelling."])
    tf = _by([f for d in displaytext.inventory(t)["displays"].values() for f in ft.findings(t, d)],
             "Table 1")
    record("k on tables: tier-A AI phrasing in a table title blocks; data-processing wording in a "
           "footnote ('missing rows dropped') is advisory",
           tf.get(("title", "Table 1. Factors that play a crucial role in outcome."), {}).get("severity") == "fail"
           and tf.get(("footnote", "Missing rows dropped before modelling."), {}).get("severity") == "warn",
           str(tf))
    old = _proj(tmp / "pinned")
    _pin(old, "1.26.1")
    fo = [f for d in displaytext.inventory(old)["displays"].values() for f in ft.findings(old, d)]
    record("a paper pinned before 1.27.0 sees every finding as a warning (none blocks)",
           fo and all(f["severity"] == "warn" for f in fo), str(len(fo)))
    record("measures: words skip statistics; data labels and sentences are told apart",
           ft.words("HR (95% CI), log scale") == ["log", "scale"] and ft.is_data_label("P < 0.001")
           and ft.is_data_label("n = 1,234") and not ft.is_data_label("Overall survival")
           and ft.sentence_like("Error bars show 95% CIs") and not ft.sentence_like("Mean difference (95% CI)")
           and not ft.sentence_like("Age \u226565 years"))


# ------------------------------------------------------------------------------ gate
def run_gate(tmp: Path, record, section) -> None:
    from wfcore import displaytext
    section("1.27.0 gate: display_wording_clean at S10/S11; S09/S12/S23 through display_text_resolved")
    p = _proj(tmp / "bad")
    g11 = _gate(p, "display_wording_clean", S11, kinds=["figure"])
    record("S11 display_wording_clean blocks on the image's title, subtitle and explanatory text",
           not g11.ok and g11.severity == "fail" and "subtitle" in g11.detail
           and "Adjusted for age and sex" in g11.detail, g11.detail[:300])
    t = _proj(tmp / "tbad", stage=S10, f1=[("Overall survival", "panel title")],
              title="Table 1. Factors that play a crucial role in outcome.")
    g10 = _gate(t, "display_wording_clean", S10, kinds=["table"])
    record("S10 display_wording_clean blocks on AI phrasing in a table title (tables only)",
           not g10.ok and "crucial role" in g10.detail and "Figure" not in g10.detail, g10.detail[:300])
    good = _proj(tmp / "good", f1=[("Overall survival", "panel title"), ("Favours treatment", "annotation"),
                                   ("HR 0.82 (95% CI 0.70-0.96)", "annotation")])
    for stem in ("FigureS1", "FigureS2", "Figure3"):
        (good / f"05_figures/qc/{stem}.artist.json").unlink()
    gg = _gate(good, "display_wording_clean", S11, kinds=["figure"])
    record("clean figures pass (short panel heading, short label, data label)", gg.ok, gg.detail)
    res = _gate(p, "display_text_resolved", "S12_reconcile")
    fr = _gate(p, "first_reader_displays", S11, kinds=["figure"], include=["display_text"],
               severity="warn")
    record("display_text_resolved (S09/S12/S23) now carries rules i/j/k; first_reader_displays "
           "does not repeat them",
           not res.ok and "subtitle" in res.detail and "Adjusted for age and sex" not in fr.detail,
           res.detail[:200] + " | " + fr.detail[:200])
    old = _proj(tmp / "pinned")
    _pin(old, "1.26.1")
    go = _gate(old, "display_wording_clean", S11, kinds=["figure"])
    record("a pinned paper gets a warning naming wf migrate --yes",
           not go.ok and go.severity == "warn" and "wf migrate --yes" in go.detail, go.detail[:200])
    _w(p, ".wf/language_allowlist.json", {"terms": [
        {"term": "Trend toward significance", "reason": "quoted name of a published scale, not a claim",
         "scope": "display"}]})
    finds = displaytext.findings(p)
    record("the paper allowlist (exact string, reason) silences one string",
           not any(f["text"] == "Trend toward significance" for f in finds)
           and any(f["text"] == "Adjusted for age and sex" for f in finds))


# ------------------------------------------------------------------------------ render
def run_render(tmp: Path, record, section) -> None:
    from wfcore import displaytext
    section("1.27.0 render: Python and R sidecars tell title, panel heading, subtitle and caption apart")
    p = _proj(tmp / "py")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from figures import qc, style
    with _envset(MEDPAPER_PROJECT=str(p)):
        style.apply_style()
        fig = plt.figure(figsize=(6, 3), layout="constrained")
        sfa, sfb = fig.subfigures(1, 2)
        axa, axb = sfa.subplots(), sfb.subplots()
        axa.plot([1, 2], [1, 2]); axb.plot([1, 2], [2, 1])
        sfa.suptitle("Overall survival")
        axb.set_title("Hospitalisation")
        fig.suptitle("Reporting odds ratios by group")
        style.save(fig, p / "05_figures/out/Figure1", archetype="bar_dot")
        plt.close(fig)
        fig2, ax2 = plt.subplots(figsize=(3, 2))
        ax2.plot([1, 2], [1, 2])
        ax2.set_title("Number of reports by year")
        style.save(fig2, p / "05_figures/out/FigureS1", archetype="bar_dot")
        plt.close(fig2)
    side = json.loads((p / "05_figures/qc/Figure1.artist.json").read_text(encoding="utf-8"))
    side2 = json.loads((p / "05_figures/qc/FigureS1.artist.json").read_text(encoding="utf-8"))
    roles = {(t["role"], t["text"]) for t in side["text_roles"]}
    record("Python style.save(): fig.suptitle = figure title; subfigure suptitle and axes titles of "
           "a multi-panel figure = panel headings; a single-axes title = figure title; version 2; "
           "QC schema accepts it",
           {("title", "Reporting odds ratios by group"), ("panel title", "Overall survival"),
            ("panel title", "Hospitalisation")} <= roles and side.get("text_roles_version") == 2
           and ("title", "Number of reports by year") in {(t["role"], t["text"]) for t in side2["text_roles"]}
           and not qc._schema_problems(side, "Figure1"), str(sorted(roles)))
    if not shutil.which("Rscript"):
        record("R render: Rscript available", False, "Rscript missing")
        return
    script = p / "05_figures/code/fig_titles.R"
    _w(p, "05_figures/code/fig_titles.R", (
        'source(file.path(Sys.getenv("MEDPAPER_ROOT"), "tools/figures/R/medfig.R"))\n'
        'suppressPackageStartupMessages({library(ggplot2); library(patchwork)})\n'
        'd <- data.frame(x = 1:8, y = c(2, 3, 5, 4, 6, 7, 8, 9))\n'
        'a <- ggplot(d, aes(x, y)) + geom_point() + labs(title = "Overall survival", x = "Year", y = "Reports") + theme_medpaper()\n'
        'b <- ggplot(d, aes(x, y)) + geom_line() + labs(title = "Hospitalisation", subtitle = "Adjusted for age and sex", x = "Year", y = "Reports") + theme_medpaper()\n'
        'pw <- (a | b) + plot_annotation(title = "Reports over time", caption = "Data from FAERS", tag_levels = "A")\n'
        'save_medpaper(pw, "temp/rtitles", archetype = "bar_dot")\n'
        's <- ggplot(d, aes(x, y)) + geom_point() + labs(title = "Number of reports by year", x = "Year", y = "Reports") + theme_medpaper()\n'
        'save_medpaper(s, "temp/rsingle", archetype = "bar_dot")\n'))
    env = {**_env(p), "MEDPAPER_PROJECT": str(p), "MEDPAPER_ROOT": str(ROOT),
           "MEDPAPER_DISPLAY_LABELS": displaytext.relabel_env(p),
           "MEDPAPER_SCRIPT": "05_figures/code/fig_titles.R"}
    proc = subprocess.run(["Rscript", str(script)], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=env, cwd=str(p), timeout=600)
    out = proc.stdout + proc.stderr
    try:
        art = json.loads((p / "temp/qc/rtitles.artist.json").read_text(encoding="utf-8"))
        one = json.loads((p / "temp/qc/rsingle.artist.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        art, one = {}, {}
    rroles = {(t.get("role"), t.get("text")) for t in art.get("text_roles", [])}
    record("R save_medpaper(): patchwork component titles = panel headings; plot_annotation title = "
           "figure title; subtitle and caption told apart; single-plot title = figure title; the "
           "render prints a hint; version 2; QC schema accepts it",
           proc.returncode == 0 and {("panel title", "Overall survival"), ("panel title", "Hospitalisation"),
                                     ("subtitle", "Adjusted for age and sex"), ("title", "Reports over time"),
                                     ("caption", "Data from FAERS")} <= rroles
           and ("title", "Number of reports by year") in {(t.get("role"), t.get("text")) for t in one.get("text_roles", [])}
           and art.get("text_roles_version") == 2 and "in-figure" in out
           and not qc._schema_problems(art, "rtitles"), f"rc={proc.returncode} {sorted(rroles)} | {out[-400:]}")


# ------------------------------------------------------------------------------ release
def run_release(tmp: Path, record, section) -> None:
    import tomllib
    from wfcore import registry, reviewrounds, sectionpolish
    from wfcore.state import State
    section("1.27.0 release: one migration event, gate lines, cards, prompts, SKILL, README")
    q = tmp / "mig"
    q.mkdir(parents=True, exist_ok=True)
    st = State(q, ".wf").create("medpaper", "1.26.1", S11)
    before = sorted(x.name for x in q.rglob("*"))
    st.migrate_pipeline("1.27.0", [s.id for s in registry.load().stages])
    st.migrate_pipeline("1.27.0", [s.id for s in registry.load().stages])
    notes = [e for e in st.data["events"] if e["kind"] == "requirements_changed"
             and str(e.get("detail", "")).startswith("1.27.0")]
    pipe = registry.load()
    gates = {(s.id, g["check"]) for s in pipe.stages for g in s.gate if g.get("since") == "1.27.0"}
    record("pipeline 1.27.0+; a 1.26.1 paper gets one 1.27.0 event (warnings now, blocking after "
           "wf migrate --yes) and stays pinned; gate lines at S10 and S11",
           _vt(pipe.meta.get("version")) >= (1, 27, 0) and len(notes) == 1
           and "wf migrate --yes" in notes[0]["detail"] and st.engine_pin == "1.26.1"
           and before == sorted(x.name for x in q.rglob("*"))
           and gates == {(S10, "display_wording_clean"), (S11, "display_wording_clean")}, str(gates))
    inv = "\n".join(tomllib.loads((ROOT / "pipeline/pipeline.toml").read_text(encoding="utf-8"))
                    ["policy"]["invariants"])
    cards = {s.id: (ROOT / "pipeline" / s.card).read_text(encoding="utf-8") for s in pipe.stages}
    read = lambda rel: " ".join((ROOT / rel).read_text(encoding="utf-8").split())  # noqa: E731
    skill = read(".kiro/skills/medpaper-pipeline/SKILL.md")
    docs = read("README.md") + read("docs/CHANGELOG.md")
    record("docs: invariant, S10/S11 cards, figure standards, S07 legend planning, writer/editor/"
           "reviewer prompts, review brief and editor rubric, SKILL (<= 9000), README and changelog",
           "no figure title, subtitle or caption line inside the image" in inv
           and "display_wording_clean" in cards[S10] and "no figure title, subtitle or caption line" in cards[S11]
           and "1.27.0 - little text, no titles inside the image" in read("reference/figure-standards.md")
           and "the legend's title line is the figure's only title" in read("reference/stage_details/S07_artifacts.md")
           and "inside a figure there is no title, subtitle or note line" in read(".kiro/agents/medpaper-clinical-writer.md")
           and "Legends and table captions (1.27.0" in read(".kiro/agents/medpaper-medical-editor.md")
           and "a title, subtitle or note line inside a figure image" in read(".kiro/agents/medpaper-reviewer.md")
           and "no title, subtitle, note line" in reviewrounds.BRIEF and "Legends and table captions" in sectionpolish.RUBRIC
           and "No title, subtitle or explanatory text inside figures" in skill and len(skill) <= 9000
           and "## 1.27.0" in docs and "图内不放标题、副标题和说明文字" in docs
           and max(len(c) for c in cards.values()) <= registry.CARD_MAX_CHARS,
           str({k: len(v) for k, v in cards.items() if len(v) > 3900}) + f" skill={len(skill)}")


GROUPS = [("rules", run_rules), ("gate", run_gate), ("render", run_render), ("release", run_release)]
