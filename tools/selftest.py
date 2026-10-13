#!/usr/bin/env python3
"""End-to-end self test. Builds a throwaway project, exercises the toolchain against the
real gate checks, then deletes everything it made.

    .venv/Scripts/.venv/Scripts/python.exe tools/selftest.py
    .venv/Scripts/.venv/Scripts/python.exe tools/selftest.py --keep     # leave the temp project for inspection
    .venv/Scripts/.venv/Scripts/python.exe tools/selftest.py --online   # also hit PubMed, Crossref

Run this after changing the style module, the table writer, the QC script or any check.
It is the regression test for the parts of the pipeline that code can verify.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

PASS, FAIL = "PASS", "FAIL"
results: list[tuple[str, str, str]] = []


def record(name: str, ok: bool, detail: str = "") -> bool:
    results.append((name, PASS if ok else FAIL, detail))
    print(f"  [{PASS if ok else FAIL}] {name}" + (f"  {detail}" if detail else ""))
    return ok


def section(title: str) -> None:
    print(f"\n{title}\n" + "-" * len(title))


# ---------------------------------------------------------------------------
def build_fixture(proj: Path) -> None:
    """A minimal but structurally complete project: results JSON, tables, a figure,
    an artifact plan, legends, captions and a Results section that cites them."""
    import numpy as np
    from figures.style import PALETTE, apply_style, figure, save, significance
    from tables.threeline import ci, fmt, p_value, write_table, write_workbook

    for sub in ("03_analysis/results", "04_tables/main", "04_tables/supplementary",
                "05_figures/out", "05_figures/qc", "01_protocol", "07_manuscript", "temp"):
        (proj / sub).mkdir(parents=True, exist_ok=True)

    res = {
        "analysis": "primary_model", "script": "03_analysis/code/03_primary.py",
        "n_eligible": 1380, "n_analysed": 1284, "n_excluded": 96,
        "groups": {"a": {"n": 642, "age_mean": 62.14, "age_sd": 11.42},
                   "b": {"n": 642, "age_mean": 61.73, "age_sd": 12.05}},
        "estimates": [{"term": "exposure", "estimate": 1.87, "ci_low": 1.34,
                       "ci_high": 2.61, "p": 0.00021, "scale": "HR"}],
        "age_p": 0.62,
        "roc": {"auc": 0.781, "auc_low": 0.742, "auc_high": 0.820},
    }
    (proj / "03_analysis/results/primary.json").write_text(
        json.dumps(res, indent=2), encoding="utf-8")

    g = res["groups"]
    write_table(
        path=proj / "04_tables/main/Table1.xlsx", sheet="Table 1",
        title="Table 1. Baseline characteristics of the study population.",
        header=["Characteristic", f"Group A (n={g['a']['n']})",
                f"Group B (n={g['b']['n']})", "P value"],
        rows=[["Age, years, mean (SD)",
               f"{fmt(g['a']['age_mean'])} ({fmt(g['a']['age_sd'])})",
               f"{fmt(g['b']['age_mean'])} ({fmt(g['b']['age_sd'])})",
               p_value(res["age_p"])],
              ["Exposure, HR (95% CI)", ci(1.87, 1.34, 2.61), "reference",
               p_value(0.00021)]],
        footnotes=["Data are mean (SD) unless stated otherwise.",
                   "Abbreviations: SD, standard deviation; HR, hazard ratio; "
                   "CI, confidence interval.",
                   "P values from the two-sided t test."],
    )
    write_workbook(
        path=proj / "04_tables/supplementary/supplementary_tables.xlsx",
        tables=[{"sheet": "Table S1", "title": "Table S1. Sensitivity analyses.",
                 "header": ["Model", "HR (95% CI)", "P value"],
                 "rows": [["Complete case", ci(1.87, 1.34, 2.61), p_value(0.00021)]],
                 "footnotes": ["Abbreviations: HR, hazard ratio; CI, confidence interval."]},
                {"sheet": "Table S2", "title": "Table S2. Discrimination.",
                 "header": ["Model", "AUC (95% CI)"],
                 "rows": [["Primary", ci(0.781, 0.742, 0.820, 3)]],
                 "footnotes": ["Abbreviations: AUC, area under the curve."]}],
    )

    apply_style()
    fig, panels = figure(width="double", height_mm=75, panels=(1, 2))
    (sfA, axA), (sfB, axB) = panels
    rng = np.random.default_rng(7)
    fpr = np.linspace(0, 1, 200)
    axA.plot(fpr, fpr ** 0.42, color=PALETTE[0], label=f"Primary (AUC {res['roc']['auc']:.3f})")
    axA.plot([0, 1], [0, 1], ls="--", lw=0.6, color="#4D4D4D")
    axA.set_xlabel("1 - specificity"); axA.set_ylabel("Sensitivity")
    axA.set_xlim(0, 1); axA.set_ylim(0, 1); axA.legend(loc="lower right")
    sfA.suptitle("Discrimination")

    vals = [rng.normal(m, 1.0, 60) for m in (3.1, 4.4)]
    bp = axB.boxplot(vals, widths=0.5, patch_artist=True, showfliers=False)
    for patch, col in zip(bp["boxes"], PALETTE):
        patch.set_facecolor(col); patch.set_alpha(0.35); patch.set_edgecolor("black")
    for key in ("medians", "whiskers", "caps"):
        for art in bp[key]:
            art.set_color("black"); art.set_linewidth(0.6)
    axB.set_xticks([1, 2]); axB.set_xticklabels(["Group A", "Group B"])
    axB.set_ylabel("Grip strength (kg)")
    significance(axB, 1, 2, max(v.max() for v in vals) + 0.3, "***")
    sfB.suptitle("Grip strength by group")
    save(fig, proj / "05_figures/out/Figure1", width="double")

    plan = {
        "main_figures": [{"id": "Figure 1", "slug": "primary",
                          "title": "Discrimination and grip strength",
                          "content": "ROC curve and grip strength by group",
                          "archetype": "other",
                          "archetype_rationale": "composite plate: panel A is a ROC curve, "
                                                 "panel B a box plot; no single archetype fits",
                          "panels": ["A", "B"], "width": "double",
                          "script": "05_figures/code/fig1_primary.py",
                          "renderer": "Python",
                          "renderer_reason": "fixture figure drawn with matplotlib to exercise "
                                             "the Python QC path",
                          "file": "05_figures/out/Figure1.png",
                          "tiff": "05_figures/out/Figure1.tiff",
                          "source_results": ["03_analysis/results/primary.json"]}],
        "main_tables": [{"id": "Table 1", "slug": "baseline",
                         "title": "Baseline characteristics", "content": "cohort by group",
                         "file": "04_tables/main/Table1.xlsx", "sheet": "Table 1",
                         "source_results": ["03_analysis/results/primary.json"]}],
        "supp_figures": [],
        "supp_tables": [
            {"id": "Table S1", "slug": "sens", "title": "Sensitivity analyses",
             "content": "robustness",
             "file": "04_tables/supplementary/supplementary_tables.xlsx",
             "sheet": "Table S1", "source_results": ["03_analysis/results/primary.json"]},
            {"id": "Table S2", "slug": "disc", "title": "Discrimination", "content": "AUC",
             "file": "04_tables/supplementary/supplementary_tables.xlsx",
             "sheet": "Table S2", "source_results": ["03_analysis/results/primary.json"]}],
        "supp_files": [],
    }
    (proj / "01_protocol/artifact_plan.json").write_text(
        json.dumps(plan, indent=2), encoding="utf-8")
    (proj / "05_figures/code").mkdir(parents=True, exist_ok=True)
    (proj / "05_figures/code/fig1_primary.py").write_text("# fixture\n", encoding="utf-8")

    (proj / "05_figures/legends.md").write_text(
        "# Figure legends\n\n## Figure 1.\nDiscrimination and grip strength. (A) Receiver "
        "operating characteristic curve for the primary model; the dashed line marks chance "
        "performance. (B) Grip strength by group as box plots (median, interquartile range, "
        "whiskers to 1.5x IQR, outliers omitted). n=1284. ***P<0.001, two-sided Wilcoxon "
        "rank-sum test. Abbreviations: AUC, area under the curve; IQR, interquartile range.\n",
        encoding="utf-8")
    (proj / "04_tables/table_captions.md").write_text(
        "# Table captions\n\n## Table 1.\nBaseline characteristics of the study population. "
        "Data are mean (SD) unless stated otherwise. Abbreviations: SD, standard deviation.\n\n"
        "## Table S1.\nSensitivity analyses. Abbreviations: HR, hazard ratio.\n\n"
        "## Table S2.\nDiscrimination. Abbreviations: AUC, area under the curve.\n",
        encoding="utf-8")
    (proj / "07_manuscript/results.md").write_text(
        "# Results\n\nOf 1380 eligible participants, 96 were excluded and 1284 were "
        "analysed. Mean age was 62.14 (SD 11.42) years in group A and 61.73 (SD 12.05) "
        "years in group B (P=0.62) (Table 1).\n\nExposure was associated with the outcome "
        "(HR 1.87, 95% CI 1.34 to 2.61; P<0.001). The primary model discriminated moderately "
        "(AUC 0.781, 95% CI 0.742 to 0.820) (Figure 1A). Grip strength differed between "
        "groups (Figure 1B). Results were unchanged in the complete-case analysis "
        "(Table S1), and discrimination was similar (Table S2).\n",
        encoding="utf-8")


# ---------------------------------------------------------------------------
def run_checks(proj: Path) -> None:
    from wfcore import gates, registry
    from wfcore.checks import Ctx, Result, get, load_all
    from wfcore.state import State

    load_all()
    pipe = registry.load()
    st = State(proj, ".wf")
    st.create(pipe.meta["name"], pipe.meta["version"], pipe.first().id)

    def run(check_name: str, stage_id: str, **spec) -> Result:
        fn = get(check_name)
        ctx = Ctx(pipeline=pipe, state=st, project=proj,
                  stage=pipe.stage(stage_id), spec={"check": check_name, **spec})
        return fn(ctx)

    section("structural checks (expected to pass)")
    for name, stage, spec in [
        ("tables_threeline", "S10_tables", {}),
        ("tables_match_plan", "S10_tables", {}),
        ("artifact_plan_sane", "S07_artifacts", {"path": "01_protocol/artifact_plan.json"}),
        ("legends_cover_plan", "S07_artifacts", {}),
        ("legend_no_results_restatement", "S07_artifacts", {}),
        ("forbidden_symbols_absent", "S07_artifacts",
         {"paths": ["05_figures/legends.md", "04_tables/table_captions.md"]}),
        ("figures_match_plan", "S11_figures", {}),
        ("numbers_have_provenance", "S10_tables", {"source": "tables"}),
        ("numbers_have_provenance", "S09_results", {"path": "07_manuscript/results.md"}),
        ("artifact_refs_consistent", "S09_results",
         {"paths": ["07_manuscript/results.md"], "require_all_cited": True}),
        ("no_ai_boilerplate", "S09_results", {"path": "07_manuscript/results.md"}),
        ("temp_clean", "S10_tables", {}),
    ]:
        r = run(name, stage, **spec)
        record(f"{name}({spec.get('source') or spec.get('path') or 'plan'})", r.ok, r.detail)

    section("negative controls (checks must catch injected faults)")

    bad = proj / "07_manuscript/bad.md"
    bad.write_text("# Results\n\nThe hazard ratio was 4.44 (95% CI 2.01 to 9.87).\n",
                   encoding="utf-8")
    r = run("numbers_have_provenance", "S09_results", path="07_manuscript/bad.md")
    record("invented statistic is rejected", not r.ok, r.detail[:110])

    bad.write_text("# Results\n\nSee Figure 9 and Table 7 for details.\n", encoding="utf-8")
    r = run("artifact_refs_consistent", "S09_results", paths=["07_manuscript/bad.md"])
    record("citation to an unplanned artifact is rejected", not r.ok, r.detail[:110])

    bad.write_text("# Results\n\nThe adjusted estimate was TODO and warrants attention.\n",
                   encoding="utf-8")
    r = run("no_ai_boilerplate", "S09_results", path="07_manuscript/bad.md")
    record("placeholder text is rejected", not r.ok, r.detail[:110])

    bad.write_text("# Results\n\nWe cite [@fabricated2021smith] here.\n", encoding="utf-8")
    r = run("citekeys_resolve", "S08_methods", paths=["07_manuscript/bad.md"])
    record("citekey with no bib entry is rejected", not r.ok, r.detail[:110])
    bad.unlink()

    legends = proj / "05_figures/legends.md"
    legend_good = legends.read_text(encoding="utf-8")
    legends.write_text("# Figure legends\n\n## Figure 1.\n" +
                       ("Repeated implementation detail that belongs in supplementary Methods. " * 35),
                       encoding="utf-8")
    r = run("legends_cover_plan", "S07_artifacts")
    record("overlong figure legend is rejected", not r.ok, r.detail[:110])
    legends.write_text(legend_good, encoding="utf-8")

    legends.write_text(
        "# Figure legends\n\n## Figure 1.\nExposure was significantly associated with "
        "the outcome (HR 1.87). Panel A displays the model and panel B displays groups.\n",
        encoding="utf-8")
    r = run("legend_no_results_restatement", "S07_artifacts")
    record("figure legend result restatement is rejected", not r.ok, r.detail[:110])
    legends.write_text(
        "# Figure legends\n\n## Figure 1.\nThe lower and upper whiskers represent the "
        "limits of the confidence interval. Error bars show SD or 95% CI. "
        "The reference line marks HR = 1; shading identifies the reference group.\n",
        encoding="utf-8")
    r = run("legend_no_results_restatement", "S07_artifacts")
    record("legend decoding terms are not mistaken for results", r.ok, r.detail[:110])
    legends.write_text(legend_good, encoding="utf-8")

    legends.write_text(legend_good.replace("Discrimination", "\u2193 Discrimination", 1),
                       encoding="utf-8")
    r = run("forbidden_symbols_absent", "S07_artifacts",
            paths=["05_figures/legends.md", "04_tables/table_captions.md"])
    record("literal down arrow is rejected in source", not r.ok, r.detail[:110])
    legends.write_text(legend_good, encoding="utf-8")

    (proj / "03_analysis/code").mkdir(parents=True, exist_ok=True)
    plot = proj / "03_analysis/code/oops.py"
    plot.write_text("import matplotlib.pyplot as plt\nplt.plot([1,2])\n", encoding="utf-8")
    r = run("no_plot_calls", "S05_analysis", glob="03_analysis/code/*.*")
    record("plotting during exploratory analysis is rejected", not r.ok, r.detail[:110])
    plot.unlink()

    scratch = proj / "temp/scratch.csv"
    scratch.write_text("a,b\n1,2\n", encoding="utf-8")
    r = run("temp_clean", "S10_tables")
    record("leftover scratch file is rejected", not r.ok, r.detail[:110])
    scratch.unlink()

    r = run("decision_recorded", "S11_figures",
            name="figures_visually_confirmed", allowed=["YES"])
    record("unrecorded decision is rejected", not r.ok, r.detail[:110])

    st.record_decision("figures_visually_confirmed", "YES", "too short")
    r = run("decision_recorded", "S11_figures",
            name="figures_visually_confirmed", allowed=["YES"])
    record("decision with a thin rationale is rejected", not r.ok, r.detail[:110])

    section("three-line writer rejects malformed input")
    from tables.threeline import write_table
    for label, kwargs in [
        ("missing footnotes", dict(footnotes=[])),
        ("title without a Table N prefix", dict(title="Baseline characteristics")),
        ("prose dumped into a cell", dict(rows=[["x", "y" * 400, "z", "w"]])),
    ]:
        base = dict(path=proj / "temp/bad.xlsx", sheet="Table 9",
                    title="Table 9. Fixture.", header=["a", "b", "c", "d"],
                    rows=[["1", "2", "3", "4"]], footnotes=["Abbreviations: none."])
        base.update(kwargs)
        try:
            write_table(**base)
            record(label, False, "writer accepted it")
        except ValueError as exc:
            record(label, True, str(exc)[:90])
    (proj / "temp/bad.xlsx").unlink(missing_ok=True)

    section("gate runner over every stage (must not raise)")
    raised = []
    for stage in pipe.stages:
        for r in gates.run_stage(pipe, st, proj, stage):
            if "check raised" in r.detail:
                raised.append(f"{stage.id}/{r.check}: {r.detail}")
    record("no check raised an exception", not raised, "; ".join(raised[:3]))

    migration_root = proj / "temp/migration_fixture"
    legacy = State(migration_root, ".wf")
    legacy.create("medpaper", "1.2.0", "S18_journal")
    changed = legacy.migrate_pipeline(
        pipe.meta["version"], [s.id for s in pipe.stages],
        {"S17_frontmatter": "S17_assemble", "S18_journal": "S17_assemble",
         "S19_polish": "S17_assemble", "S20_package": "S17_assemble"})
    record("legacy tail state migrates without resetting project artifacts",
           changed and legacy.current == "S17_assemble" and
           legacy.data["pipeline_version"] == pipe.meta["version"],
           f"current={legacy.current}; version={legacy.data['pipeline_version']}")
    shutil.rmtree(migration_root, ignore_errors=True)

    decision_root = proj / "temp/decision_invalidation_fixture"
    revisited = State(decision_root, ".wf")
    revisited.create("medpaper", pipe.meta["version"], "S24_package_human_review")
    revisited.record_decision(
        "submission_package_user_confirmed", "OK",
        "The user reviewed the frozen package and explicitly approved independent audit.")
    revisited.complete("S24_package_human_review", "S25_submission_audit")
    revisited.record_decision(
        "submission_package_independent_audit", "REVISE",
        "The reviewer found a material mismatch that requires a corrected package revision.")
    revisited.clear_decisions_for(["S24_package_human_review", "S25_submission_audit"])
    record("loop invalidates package confirmation and audit decisions",
           revisited.decision("submission_package_user_confirmed") is None and
           revisited.decision("submission_package_independent_audit") is None)
    shutil.rmtree(decision_root, ignore_errors=True)


def run_data_proof(proj: Path) -> None:
    """Full acquisition must be proved; a synchronized partial payload still fails."""
    from wfcore import dataproof, registry
    from wfcore.checks import Ctx, get, load_all
    from wfcore.state import State

    section("data acquisition completeness and anti-truncation")
    scoped = proj / "temp/data_proof"
    raw = scoped / "02_data/raw"
    acquisition = scoped / "02_data/acquisition"
    results_dir = scoped / "03_analysis/results"
    raw.mkdir(parents=True)
    acquisition.mkdir(parents=True)
    results_dir.mkdir(parents=True)
    data_path = raw / "cohort.csv"
    count_path = raw / "source_total.txt"
    code_path = acquisition / "fetch.py"
    data_path.write_text("id,value\n1,10\n2,20\n3,30\n4,40\n5,50\n", encoding="utf-8")
    count_path.write_text("5\n", encoding="utf-8")
    code_path.write_text("# API cursor loop runs until next_cursor is empty\n", encoding="utf-8")

    manifest = {
        "schema_version": dataproof.SCHEMA_VERSION,
        "requested_scope": dataproof.FULL_SCOPE,
        "status": dataproof.COMPLETE,
        "protocol_population": "Every record returned by the pre-specified eligible cohort query.",
        "acquisition_method": "scripted",
        "pilot": {"used": False},
        "protocol_sampling": None,
        "sources": [{
            "id": "eligible_cohort",
            "type": "database",
            "locator": "fixture://eligible-cohort?release=2026-09-01",
            "retrieved_at": "2026-09-07T10:00:00+08:00",
            "source_total_expected": 5,
            "records_requested": 5,
            "records_received": 5,
            "source_total_evidence": {
                "path": "02_data/raw/source_total.txt", "kind": "text_integer"
            },
            "received_count_evidence": [{
                "path": "02_data/raw/cohort.csv", "kind": "delimited_rows", "header": True
            }],
            "complete": True,
            "truncation_applied": False,
            "pagination": {
                "applicable": True, "pages_expected": 2, "pages_received": 2,
                "terminal_reached": True, "next_cursor_at_end": None,
            },
        }],
        "analysis_dataset": {
            "primary_source_id": "eligible_cohort", "n_rows": 4,
            "excluded_after_acquisition": 1,
            "relationship": "one_record_per_analysis_row",
        },
    }

    def synchronize() -> None:
        current_raw = dataproof.inventory(scoped, "02_data/raw")
        manifest["raw_files"] = current_raw
        manifest["acquisition_files"] = dataproof.inventory(scoped, "02_data/acquisition")
        manifest["raw_bundle_sha256"] = dataproof.bundle_sha256(current_raw)
        (scoped / dataproof.MANIFEST_REL).write_text(
            json.dumps(manifest, indent=2), encoding="utf-8")
        summary = {
            "n_rows": manifest["analysis_dataset"]["n_rows"], "n_cols": 2,
            "variables": [], "missingness": {},
            "source_hash": manifest["raw_bundle_sha256"],
            "acquisition_scope": dataproof.FULL_SCOPE,
            "acquisition_status": manifest["status"],
            "built_by": "03_analysis/code/build.py",
        }
        (scoped / dataproof.SUMMARY_REL).write_text(
            json.dumps(summary, indent=2), encoding="utf-8")

    synchronize()
    load_all()
    pipe = registry.load()
    state = State(scoped, ".wf")
    state.create("medpaper", pipe.meta["version"], "S04_data")

    def gate():
        return get("data_acquisition_complete")(Ctx(
            pipeline=pipe, state=state, project=scoped, stage=pipe.stage("S04_data"),
            spec={"check": "data_acquisition_complete"},
        ))

    outcome = gate()
    record("full payload, source total, received count and terminal cursor pass",
           outcome.ok, outcome.detail[:140])

    # Updating hashes and the claimed received count still cannot turn a first-four
    # payload into the independently preserved source total of five.
    data_path.write_text("id,value\n1,10\n2,20\n3,30\n4,40\n", encoding="utf-8")
    manifest["sources"][0]["records_received"] = 4
    manifest["analysis_dataset"]["n_rows"] = 3
    synchronize()
    outcome = gate()
    record("synchronized partial payload is rejected against source-total evidence",
           not outcome.ok and "claims complete" in outcome.detail, outcome.detail[:140])

    data_path.write_text("id,value\n1,10\n2,20\n3,30\n4,40\n5,50\n", encoding="utf-8")
    manifest["sources"][0]["records_received"] = 5
    manifest["analysis_dataset"]["n_rows"] = 4
    code_path.write_text("records = pandas.read_csv(path).head(2)\n", encoding="utf-8")
    synchronize()
    outcome = gate()
    record("unapproved head/sample/LIMIT-style acquisition cap is rejected",
           not outcome.ok and "unapproved acquisition cap" in outcome.detail,
           outcome.detail[:140])

    env = {**os.environ, "MEDPAPER_PROJECT": str(scoped), "MEDPAPER_ROOT": str(ROOT),
           "PYTHONIOENCODING": "utf-8"}
    forced = subprocess.run(
        [sys.executable, str(ROOT / "tools/wf.py"), "advance", "--force", "--note",
         "Attempted force advance must remain blocked by incomplete or capped acquisition."],
        capture_output=True, text=True, env=env, encoding="utf-8", errors="replace")
    record("--force cannot bypass full-data acquisition proof",
           forced.returncode != 0 and State(scoped, ".wf").load().current == "S04_data",
           ((forced.stdout or "") + (forced.stderr or "")).strip()[:140])

    code_path.write_text(
        "preview = pandas.read_csv(path).head(2)  # MEDPAPER_PILOT_ONLY\n",
        encoding="utf-8")
    manifest["pilot"] = {
        "used": True, "excluded_from_analysis": True,
        "full_acquisition_completed_after_pilot": True,
    }
    synchronize()
    outcome = gate()
    record("non-analytic pilot is allowed only after the full acquisition completes",
           outcome.ok, outcome.detail[:140])

    code_path.write_text(
        "sample = frame.sample(n=5)  # MEDPAPER_PROTOCOL_SAMPLING\n",
        encoding="utf-8")
    manifest["protocol_sampling"] = {
        "pre_specified": True,
        "protocol_path": "01_protocol/protocol_v1.md#population-and-eligibility",
        "explanation": "Probability sampling was fixed before retrieval for the scientific design.",
    }
    synchronize()
    outcome = gate()
    record("agent cannot silently replace a census with protocol sampling",
           not outcome.ok and "protocol_sampling_authorized" in outcome.detail,
           outcome.detail[:140])
    state.record_decision(
        "protocol_sampling_authorized", "YES",
        "The user explicitly approved this pre-specified probability-sampling design and its tradeoffs.")
    outcome = gate()
    record("user-authorized pre-specified scientific sampling can pass",
           outcome.ok, outcome.detail[:140])
    shutil.rmtree(scoped, ignore_errors=True)


def run_reference_proof(proj: Path) -> None:
    """A boolean or forged DOI must not satisfy any citation gate."""
    from unittest.mock import patch

    from wfcore import refproof, registry
    from wfcore.checks import Ctx, get, load_all
    from wfcore.state import State

    section("reference provenance and anti-forgery")
    scoped = proj / "temp/reference_proof"
    refs = scoped / "06_refs"
    cache = refs / "cache"
    manuscript = scoped / "07_manuscript"
    cache.mkdir(parents=True)
    manuscript.mkdir(parents=True)
    key, pmid, real_doi = "smith2025integrity", "40123456", "10.1000/real-doi"
    raw_real = f"""<?xml version="1.0" encoding="UTF-8"?>
<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>{pmid}</PMID><Article>
<ArticleTitle>Integrity safeguards for clinical reference verification</ArticleTitle>
<Abstract><AbstractText>Reference provenance was evaluated using independent source records.</AbstractText></Abstract>
<AuthorList><Author><LastName>Smith</LastName><ForeName>Alice</ForeName></Author></AuthorList>
<Journal><JournalIssue><PubDate><Year>2025</Year></PubDate></JournalIssue><Title>Journal of Evidence Integrity</Title></Journal>
<ELocationID EIdType="doi">{real_doi}</ELocationID><PublicationTypeList><PublicationType>Journal Article</PublicationType></PublicationTypeList>
</Article></MedlineCitation><PubmedData><ArticleIdList><ArticleId IdType="doi">{real_doi}</ArticleId></ArticleIdList></PubmedData>
</PubmedArticle></PubmedArticleSet>"""
    library = {
        "entries": [{
            "citekey": key, "pmid": pmid, "doi": real_doi,
            "title": "Integrity safeguards for clinical reference verification",
            "abstract": "Reference provenance was evaluated using independent source records.",
            "authors": [{"last": "Smith", "first": "Alice"}],
            "journal": "Journal of Evidence Integrity", "year": "2025",
            "source": "pubmed",
        }]
    }
    library_path = refs / "library.json"
    library_path.write_text(json.dumps(library, indent=2), encoding="utf-8")
    (refs / "refs.bib").write_text(
        f"@article{{{key}, title={{Integrity safeguards for clinical reference verification}}, "
        f"author={{Smith, Alice}}, journal={{Journal of Evidence Integrity}}, year={{2025}}, "
        f"doi={{{real_doi}}}, pmid={{{pmid}}}}}\n", encoding="utf-8")
    cited = manuscript / "proof.md"
    cited.write_text(f"# Introduction\n\nA verified source is cited [@{key}].\n", encoding="utf-8")
    (refs / "verified.json").write_text(
        json.dumps({"records": {key: {"verified": True, "doi": "10.9999/fabricated"}}}, indent=2),
        encoding="utf-8")

    load_all()
    pipe = registry.load()
    state = State(scoped, ".wf")
    state.create("medpaper", pipe.meta["version"], "S13_reflib")

    def gate(name: str, **spec):
        return get(name)(Ctx(pipeline=pipe, state=state, project=scoped,
                             stage=pipe.stage("S13_reflib"), spec={"check": name, **spec}))

    outcome = gate("citekeys_resolve", paths=["07_manuscript/proof.md"])
    record("verified=true without raw PubMed proof is rejected", not outcome.ok,
           outcome.detail[:120])
    force_env = {**os.environ, "MEDPAPER_PROJECT": str(scoped),
                 "MEDPAPER_ROOT": str(ROOT), "PYTHONIOENCODING": "utf-8"}
    forced = subprocess.run(
        [sys.executable, str(ROOT / "tools/wf.py"), "advance", "--force", "--note",
         "Attempted forced advance must remain blocked by bibliographic provenance."],
        capture_output=True, text=True, env=force_env, encoding="utf-8", errors="replace")
    record("--force cannot bypass reference-integrity gates",
           forced.returncode != 0 and State(scoped, ".wf").load().current == "S13_reflib",
           ((forced.stdout or "") + (forced.stderr or "")).strip()[:120])

    cache_rel = "06_refs/cache/verify_efetch_pubmed_fixture.xml"
    cache_path = scoped / cache_rel
    cache_path.write_text(raw_real, encoding="utf-8")
    source = refproof.parse_pubmed_payload(raw_real)[pmid]
    verified = {
        "schema": refproof.SCHEMA,
        "generator": {"tool": refproof.GENERATOR, "mode": "fresh_ncbi_pubmed_efetch",
                      "source": "NCBI PubMed EFetch"},
        "verified_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "strict": False,
        "library_sha256": refproof.file_sha256(library_path),
        "n_entries": 1, "n_verified": 1,
        "records": {key: {
            "verified": True, "via": "pubmed", "pmid": pmid, "doi": real_doi,
            "evidence": {"source": refproof.SOURCE, "cache_file": cache_rel,
                         "payload_sha256": refproof.file_sha256(cache_path),
                         "record_sha256": refproof.record_sha256(source),
                         "fresh_fetch": True},
        }},
    }
    verified_path = refs / "verified.json"
    verified_path.write_text(json.dumps(verified, indent=2), encoding="utf-8")
    outcome = gate("citekeys_resolve", paths=["07_manuscript/proof.md"])
    record("hashed reparsed PubMed proof satisfies citekey gate", outcome.ok, outcome.detail[:120])

    library["entries"][0]["doi"] = "10.9999/fabricated"
    library_path.write_text(json.dumps(library, indent=2), encoding="utf-8")
    verified["library_sha256"] = refproof.file_sha256(library_path)
    verified["records"][key]["doi"] = "10.9999/fabricated"
    verified_path.write_text(json.dumps(verified, indent=2), encoding="utf-8")
    outcome = gate("citekeys_resolve", paths=["07_manuscript/proof.md"])
    record("forged DOI fails even after booleans and library hash are patched", not outcome.ok,
           outcome.detail[:120])

    # Even a fully forged local XML/hash bundle cannot pass S13: that gate performs
    # its own fresh PubMed fetch and compares the authoritative response.
    raw_fake = raw_real.replace(real_doi, "10.9999/fabricated")
    cache_path.write_text(raw_fake, encoding="utf-8")
    forged_source = refproof.parse_pubmed_payload(raw_fake)[pmid]
    evidence = verified["records"][key]["evidence"]
    evidence["payload_sha256"] = refproof.file_sha256(cache_path)
    evidence["record_sha256"] = refproof.record_sha256(forged_source)
    verified_path.write_text(json.dumps(verified, indent=2), encoding="utf-8")
    live_record = {
        "pmid": pmid, "doi": real_doi,
        "title": "Integrity safeguards for clinical reference verification",
        "abstract": "Reference provenance was evaluated using independent source records.",
        "authors": [{"last": "Smith", "first": "Alice"}],
        "journal": "Journal of Evidence Integrity", "year": "2025", "flags": [],
    }
    with patch("pubmed.eutils.efetch", return_value=[live_record]):
        outcome = gate("reference_provenance", live=True)
    record("independent live S13 gate rejects a locally forged XML receipt", not outcome.ok,
           outcome.detail[:120])

    shutil.rmtree(scoped, ignore_errors=True)


def run_qc(proj: Path) -> None:
    section("figure QC (subprocess, as the agent runs it)")
    env = {**os.environ, "MEDPAPER_PROJECT": str(proj), "MEDPAPER_ROOT": str(ROOT),
           "PYTHONIOENCODING": "utf-8"}
    p = subprocess.run([sys.executable, str(ROOT / "tools/figures/qc.py"), "--all"],
                       capture_output=True, text=True, env=env, encoding="utf-8", errors="replace")
    out = (p.stdout or "") + (p.stderr or "")
    for line in out.splitlines():
        if line.strip().startswith("[") or "pass deterministic" in line:
            print("  " + line.strip())
    record("all deterministic figure QC checks pass", "1/1 figure(s) pass" in out,
           "" if "1/1 figure(s) pass" in out else "see output above")
    rep = proj / "05_figures/qc/qc_report.json"
    record("qc_report.json written", rep.exists())
    if rep.exists():
        data = json.loads(rep.read_text(encoding="utf-8"))
        fig = data["figures"][0]
        record("visual_reviewed defaults to false", fig.get("visual_reviewed") is False,
               "QC alone must never satisfy the visual-verification gate")


SLOP = """# Discussion

In today's rapidly evolving landscape of modern clinical care, sarcopenia plays a crucial
role in patient outcomes. It is worth noting that we utilized a robust and comprehensive
approach to delve into this multifaceted problem, and our cutting-edge analysis paves the
way for a comprehensive understanding of the intricate interplay involved.

Our primary finding was an association between exposure and the outcome (HR 1.87, 95% CI
1.34 to 2.61; P<0.001), which aligns with previous work [@smith2020cohort]. Furthermore,
the effect was seamlessly consistent across strata. Moreover, discrimination was moderate
(AUC 0.781) (Figure 1A). Additionally, results held in sensitivity analyses (Table S1).

The data was analyzed in 3 centers, and 10-20 participants per site were characterised
using a 5mg dose. P-value thresholds were applied and P = 0.000 was observed in one
subgroup. This finding may potentially suggest that the exposure could possibly cause the
outcome, and underscores the importance of further work. Further studies are warranted.
"""

CLEAN = """# Discussion

Sarcopenia was associated with mortality in this cohort. We analysed a single prospective
cohort with prespecified exposure and outcome definitions.

The primary finding was an association between exposure and the outcome (HR 1.87, 95% CI
1.34 to 2.61; P<0.001), consistent with the earlier cohort of Smith and colleagues
[@smith2020cohort]. The effect was stable across strata, discrimination was moderate
(AUC 0.781) (Figure 1A), and the estimate was unchanged in sensitivity analyses (Table S1).

Data were collected at 3 centres, with 10\u201320 participants per site characterised after a
5 mg dose. One subgroup reached P < 0.001. Because the design is observational, these data
support an association rather than a causal effect; the direction of residual confounding
cannot be established from these data.
"""


REF_LIST_XML = """<?xml version="1.0" encoding="UTF-8"?>
<PubmedArticleSet><PubmedArticle>
<MedlineCitation><PMID>40932817</PMID><Article>
<ArticleTitle>Fully covered self-expandable metal stents in benign biliary stricture</ArticleTitle>
<Abstract><AbstractText>Post-market outcomes were assessed.</AbstractText></Abstract>
<AuthorList><Author><LastName>DePretis</LastName><ForeName>Nicolo</ForeName></Author></AuthorList>
<Journal><JournalIssue><PubDate><Year>2025</Year></PubDate></JournalIssue><Title>Endoscopy International Open</Title></Journal>
<ELocationID EIdType="doi">10.1055/a-2669-5801</ELocationID>
<PublicationTypeList><PublicationType>Journal Article</PublicationType></PublicationTypeList>
</Article>
<CommentsCorrectionsList><CommentsCorrections RefType="Cites"><PMID>11111111</PMID></CommentsCorrections></CommentsCorrectionsList>
</MedlineCitation>
<PubmedData>
<ArticleIdList>
<ArticleId IdType="pubmed">40932817</ArticleId>
<ArticleId IdType="pmc">PMC12417772</ArticleId>
<ArticleId IdType="doi">10.1055/a-2669-5801</ArticleId>
</ArticleIdList>
<ReferenceList>
<Reference><Citation>Weigt J. Anatomy-shaped design of a fully-covered biliary stent. 2016.</Citation>
<ArticleIdList><ArticleId IdType="pubmed">26793789</ArticleId>
<ArticleId IdType="pmc">PMC4713183</ArticleId>
<ArticleId IdType="doi">10.1055/s-0034-1393583</ArticleId></ArticleIdList></Reference>
<Reference><Citation>Lam R. Fully covered metal biliary stents: a review. 2021.</Citation>
<ArticleIdList><ArticleId IdType="pubmed">34720527</ArticleId>
<ArticleId IdType="pmc">8517778</ArticleId>
<ArticleId IdType="doi">10.3748/wjg.v27.i38.6357</ArticleId></ArticleIdList></Reference>
</ReferenceList>
</PubmedData>
</PubmedArticle></PubmedArticleSet>"""


def run_reference_identity(proj: Path) -> None:
    """A cited reference's identifiers must never be mistaken for the article's own.

    Regression control for a real failure: `.//ArticleIdList/ArticleId` swept in every
    <Reference>, the loop had no break, and the LAST cited reference's PMCID replaced the
    article's. Full texts of four unrelated papers were downloaded, and every sha256 receipt
    verified clean, because a hash certifies the bytes that arrived rather than the article that
    was requested. Both halves are asserted here: the parser, and the identity check that
    catches it even if a parser regresses.
    """
    import hashlib

    sys.path.insert(0, str(ROOT / "tools"))
    from pubmed import eutils as eu
    from pubmed import fulltext as ft
    from wfcore import refproof

    section("reference identity: a bibliography is not the article")

    recs = eu.parse_pubmed_xml(REF_LIST_XML)
    record("parser returns exactly one article from a record with 2 references",
           len(recs) == 1, f"{len(recs)} record(s)")
    got = recs[0]
    record("PMCID is the article's own, not the last cited reference's",
           got["pmcid"] == "PMC12417772",
           f"got {got['pmcid']!r}, reference PMCIDs were PMC4713183 / 8517778")
    record("DOI is the article's own",
           got["doi"] == "10.1055/a-2669-5801", f"got {got['doi']!r}")
    record("PMID is the article's own, not a CommentsCorrections PMID",
           got["pmid"] == "40932817", f"got {got['pmid']!r}")

    # A bare accession in a reference was the source of the "malformed, no PMC prefix" entries.
    record("a PMC accession is normalised to the PMC-prefixed form",
           got["pmcid"].startswith("PMC"), got["pmcid"])

    # refproof re-derives independently; both parsers must agree, and it must now carry pmcid.
    src = refproof.parse_pubmed_payload(REF_LIST_XML)["40932817"]
    record("the independent verifier reads the same PMCID",
           src["pmcid"] == "PMC12417772", f"refproof got {src['pmcid']!r}")
    record("PMCID stays out of the receipt hash, so existing receipts remain valid",
           "pmcid" not in refproof.canonical_source(src),
           "it is a download locator, not part of the citation")

    base = {"citekey": "depretis2025fully", "pmid": "40932817", "pmcid": "PMC12417772",
            "doi": "10.1055/a-2669-5801",
            "title": "Fully covered self-expandable metal stents in benign biliary stricture"}
    forged = dict(base, pmcid="PMC4713183")
    issues = refproof.compare_entry_to_source(forged, src)
    record("a reference's PMCID in the library is caught as a mismatch",
           any("PMCID differs" in i for i in issues), "; ".join(issues) or "no issue raised")
    record("the correct entry raises no PMCID complaint",
           not any("PMCID" in i for i in
                   refproof.compare_entry_to_source(dict(base, abstract="x"), src)),
           "no false positive on a good entry")

    # ---- identity of the payload itself ------------------------------------
    def jats(pmid, pmcid, doi, title):
        return (f'<article><front><article-meta>'
                f'<article-id pub-id-type="pmid">{pmid}</article-id>'
                f'<article-id pub-id-type="pmc">{pmcid}</article-id>'
                f'<article-id pub-id-type="doi">{doi}</article-id>'
                f'<title-group><article-title>{title}</article-title></title-group>'
                f'</article-meta></front><body><p>text</p></body></article>').encode()

    right = jats("40932817", "PMC12417772", "10.1055/a-2669-5801", base["title"])
    wrong = jats("26793789", "PMC4713183", "10.1055/s-0034-1393583",
                 "Anatomy-shaped design of a fully-covered biliary stent")

    v = ft.check_identity(base, right, "xml")
    record("the correct full text is confirmed as a match", v["identity"] == "match",
           f"{v['identity']}: {v['identity_detail']}")
    v = ft.check_identity(base, wrong, "xml")
    record("the wrong paper's full text is caught as a mismatch", v["identity"] == "mismatch",
           f"{v['identity']}: {v['identity_detail']}")
    try:
        ft._guard_identity(base, wrong, "xml", "http://example.test/x")
        refused = False
    except ft.WrongPaper:
        refused = True
    record("a mismatching payload is refused and never written to disk", refused,
           "fetch raises WrongPaper instead of saving")

    html_ok = (b'<html><head><meta name="citation_doi" content="10.1055/a-2669-5801">'
               b'<meta name="citation_pmid" content="40932817"></head></html>')
    html_bad = (b'<html><head><meta name="citation_doi" content="10.1093/jamia/ocv153">'
                b'<meta name="citation_pmid" content="26644398"></head></html>')
    record("HTML citation meta tags are read for identity",
           ft.check_identity(base, html_ok, "html")["identity"] == "match")
    record("HTML naming another article is a mismatch",
           ft.check_identity(base, html_bad, "html")["identity"] == "mismatch")

    # The asymmetry that matters: a PDF's cited DOIs are not evidence of anything.
    pdf_self = (b"%PDF-1.7\nEndoscopy 2025. doi:10.1055/a-2669-5801\n"
                b"Fully covered self-expandable metal stents in benign biliary stricture\n"
                b"Abstract ... body\nReferences\n1. Other. doi:10.1055/s-0034-1393583\n")
    pdf_cites_others = (b"%PDF-1.7 ... References: 10.1055/s-0034-1393583, "
                        b"10.3748/wjg.v27.i38.6357 ... body")
    pdf_doi_in_refs_only = (b"%PDF-1.7\nAn unrelated cohort of hepatic outcomes\nAbstract body\n"
                            b"References\n1. De Pretis. Fully covered self-expandable metal stents"
                            b" in benign biliary stricture. doi:10.1055/a-2669-5801\n")
    pdf_wrong_cites_target = (b"%PDF-1.7\nAnatomy-shaped design of a fully-covered biliary stent\n"
                              b"doi:10.1055/s-0034-1393583\nAbstract body\nReferences\n"
                              b"7. doi:10.1055/a-2669-5801\n")
    pdf_doi_no_title = b"%PDF-1.7\ndoi:10.1055/a-2669-5801\nAbstract body\n"
    record("a PDF whose front matter has our DOI and title counts as a match",
           ft.check_identity(base, pdf_self, "pdf")["identity"] == "match",
           ft.check_identity(base, pdf_self, "pdf")["identity_detail"])
    v = ft.check_identity(base, pdf_doi_in_refs_only, "pdf")
    record("a PDF with our DOI only in its reference list is a mismatch",
           v["identity"] == "mismatch" and v["identity_basis"] == "pdf-doi-only-in-references",
           v["identity_detail"])
    v = ft.check_identity(base, pdf_wrong_cites_target, "pdf")
    record("a different article that cites ours is a mismatch, not a match",
           v["identity"] == "mismatch", v["identity_detail"])
    v = ft.check_identity(base, pdf_doi_no_title, "pdf")
    record("our DOI in the front matter without title/author evidence is only indeterminate",
           v["identity"] == "indeterminate", v["identity_detail"])
    v = ft.check_identity(base, pdf_cites_others, "pdf")
    record("a PDF citing OTHER DOIs is indeterminate, never a match",
           v["identity"] == "indeterminate",
           "treating a bibliography as identity is the original bug; it must not be repeated")
    record("the indeterminate verdict says why the cited DOIs were ignored",
           "cited DOIs are not evidence" in v["identity_detail"], v["identity_detail"])

    # ---- the gate ----------------------------------------------------------
    from wfcore import registry
    from wfcore.checks import Ctx, get, load_all
    from wfcore.state import State
    load_all()
    pipe = registry.load()
    scoped = proj / "temp/refidentity"
    (scoped / "06_refs/fulltext").mkdir(parents=True, exist_ok=True)
    (scoped / "06_refs/deepread").mkdir(parents=True, exist_ok=True)
    # The gate wants roughly `deepread_count` papers, so build enough to clear its floor and
    # vary only the first one's identity verdict.
    keys = ["depretis2025fully", "second2025paper", "third2025paper", "fourth2025paper"]
    lib, sel = [], []
    for n, ck in enumerate(keys):
        (scoped / f"06_refs/fulltext/{ck}.pdf").write_bytes(pdf_self)
        (scoped / f"06_refs/deepread/{ck}.md").write_text(
            "# notes\n" + ("substantive deep-read content. " * 30), encoding="utf-8")
        lib.append(dict(base, citekey=ck, pmid=str(40932817 + n)))
        sel.append({"citekey": ck, "pmid": str(40932817 + n), "reason": "closest prior study",
                    "access": "oa", "fulltext": f"06_refs/fulltext/{ck}.pdf",
                    "notes": f"06_refs/deepread/{ck}.md"})
    (scoped / "06_refs/library.json").write_text(json.dumps({"entries": lib}), encoding="utf-8")
    (scoped / "06_refs/deepread/deepread_index.json").write_text(
        json.dumps({"selected": sel}), encoding="utf-8")

    def gate(identity: str, basis: str = ""):
        """Set the first paper's identity verdict; the other two always verify."""
        recs = []
        for n, ck in enumerate(keys):
            f = scoped / f"06_refs/fulltext/{ck}.pdf"
            rec = {"citekey": ck, "access": "oa", "fulltext": f"06_refs/fulltext/{ck}.pdf",
                   "sha256": hashlib.sha256(f.read_bytes()).hexdigest()}
            verdict = identity if n == 0 else "match"
            if verdict:
                rec["identity"] = verdict
                if n == 0 and basis:
                    rec["identity_basis"] = basis
                if verdict == "mismatch":
                    rec["identity_detail"] = "DOI mismatch; payload is Weigt 2016"
            recs.append(rec)
        (scoped / "06_refs/fulltext/retrieval_manifest.json").write_text(
            json.dumps({"retrievals": recs}), encoding="utf-8")
        shutil.rmtree(scoped / ".wf", ignore_errors=True)
        st = State(scoped, ".wf")
        st.create(pipe.meta["name"], pipe.meta["version"], pipe.first().id)
        return get("deepread_complete")(Ctx(pipeline=pipe, state=st, project=scoped,
                                            stage=pipe.stage("S15_deepread"),
                                            spec={"check": "deepread_complete"}))

    r = gate("match")
    record("S15 passes when the file is proven to be the requested article", r.ok, r.detail)
    r = gate("mismatch")
    record("S15 blocks a file that is a different article",
           not r.ok and "DIFFERENT article" in r.detail, r.detail)
    r = gate("")
    record("S15 blocks a file whose identity was never checked",
           not r.ok and "never proven" in r.detail, r.detail)
    r = gate("indeterminate")
    record("an indeterminate identity is unproven, not acceptable",
           not r.ok, r.detail)
    r = gate("match", "pdf-doi-present")
    record("a match accepted by the pre-1.7.1 DOI-anywhere rule must be re-verified",
           not r.ok and "re-verify from the front matter" in r.detail, r.detail)

    from wfcore import cli
    record("deepread_complete cannot be bypassed with --force",
           "deepread_complete" in cli.NON_OVERRIDABLE_GATES,
           "a deep read of the wrong paper reaches the Discussion as a sourced claim")
    record("the invariant states that a hash is not proof of identity",
           any("never that they are the right paper" in inv
               for inv in pipe.policy.get("invariants", [])),
           "must survive context compaction")
    shutil.rmtree(scoped, ignore_errors=True)


def run_scientific_freeze(proj: Path) -> None:
    """A journal requirement must never re-edit the manuscript review already settled.

    Before the freeze, S21 and S22 applied journal requirements by editing 07_manuscript/ in
    place, so choosing a second journal churned the reviewed text and nothing recorded what had
    drifted. These assertions cover the whole contract: the freeze is taken, it holds, the
    variant derives from it, path resolution follows the variant, switching journals discards
    only the variant, and content cannot be dropped to fit a word cap without authorisation.
    """
    from wfcore import gates, packagecontent, registry, scifreeze
    from wfcore.checks import Ctx, get, load_all
    from wfcore.state import State

    load_all()
    section("scientific freeze: journals adapt a copy, never the reviewed text")
    scoped = proj / "temp/scifreeze"
    for sub in ("07_manuscript", "06_refs", "05_figures", "08_submission"):
        (scoped / sub).mkdir(parents=True, exist_ok=True)
    body = ("# Introduction\n\nPrior work reported a hazard ratio of 1.87 [@smith2020cohort].\n\n"
            "# Methods\n\nWe analysed 412 patients.\n\n"
            "# Results\n\nMortality was 23.4% (Figure 1). Discrimination reached 0.781 (Table 2).\n\n"
            "# Discussion\n\nThe estimate agrees with earlier data [@lee2021trial].\n")
    (scoped / "07_manuscript/full_manuscript.md").write_text(body, encoding="utf-8")
    (scoped / "07_manuscript/supplementary_methods.md").write_text(
        "# Supplementary Methods\n\nModel fitting used penalised likelihood.\n", encoding="utf-8")
    (scoped / "07_manuscript/statements.md").write_text(
        "# Declarations and Statements\n\nFunding: none.\n", encoding="utf-8")
    (scoped / "06_refs/refs.bib").write_text("@article{smith2020cohort, title={x}}\n",
                                             encoding="utf-8")
    (scoped / "06_refs/library.json").write_text('{"entries": []}', encoding="utf-8")
    (scoped / "03_analysis/results").mkdir(parents=True, exist_ok=True)
    (scoped / "03_analysis/results/primary.json").write_text(
        '{"hr": 1.87, "n": 412, "mortality_pct": 23.4, "auc": 0.781}', encoding="utf-8")

    pipe = registry.load()

    def run(check_name: str, stage_id: str, **spec):
        st = State(scoped, ".wf")
        if not st.exists():
            st.create(pipe.meta["name"], pipe.meta["version"], pipe.first().id)
        else:
            st.load()
        return get(check_name)(Ctx(pipeline=pipe, state=st, project=scoped,
                                   stage=pipe.stage(stage_id),
                                   spec={"check": check_name, **spec}))

    # ---- before the freeze, everything behaves as it always did ------------
    r = run("scientific_freeze_captured", "S19_human_review")
    record("S19 refuses to close without freezing the settled science", not r.ok, r.detail)
    r = run("scientific_freeze_intact", "S20_journal")
    record("an unfrozen project is not reported as verified",
           r.ok and "no scientific freeze" in r.detail, r.detail)
    record("path resolution is the identity function before a variant exists",
           scifreeze.resolve(scoped, "07_manuscript/full_manuscript.md")
           == "07_manuscript/full_manuscript.md",
           "projects that predate the freeze must keep working unchanged")

    # ---- capture ------------------------------------------------------------
    scifreeze.write_freeze(scoped)
    r = run("scientific_freeze_captured", "S19_human_review")
    record("the freeze covers the scientific record", r.ok, r.detail)
    freeze = scifreeze.load_freeze(scoped)
    record("the freeze hashes the manuscript, refs, library and results JSON",
           not scifreeze.uncovered_required(freeze["files"])
           and "03_analysis/results/primary.json" in freeze["files"],
           f"{len(freeze['files'])} file(s)")
    record("re-capturing identical science needs no --force (1.8.0)",
           not _raises(lambda: scifreeze.write_freeze(scoped)))
    held = scoped / "07_manuscript/full_manuscript.md"
    held_text = held.read_text(encoding="utf-8")
    held.write_text(held_text + "\nA changed sentence.\n", encoding="utf-8")
    record("re-freezing changed science without --force is refused",
           _raises(lambda: scifreeze.write_freeze(scoped)),
           "it would discard the record of what review closed on")
    held.write_text(held_text, encoding="utf-8")

    r = run("scientific_freeze_intact", "S20_journal")
    record("the freeze holds immediately after capture", r.ok, r.detail)

    # ---- the thing the user actually complained about ----------------------
    (scoped / "07_manuscript/full_manuscript.md").write_text(
        body.replace("412 patients", "412 patients enrolled consecutively"), encoding="utf-8")
    r = run("scientific_freeze_intact", "S22_polish")
    record("editing the reviewed manuscript for a journal is blocked",
           not r.ok and "full_manuscript.md" in r.detail, r.detail)
    record("the block points at the variant instead of just refusing",
           any("08_submission/manuscript" in h for h in r.hints), "; ".join(r.hints)[:100])
    (scoped / "07_manuscript/full_manuscript.md").write_text(body, encoding="utf-8")
    record("restoring the frozen text clears the block",
           run("scientific_freeze_intact", "S22_polish").ok)

    from wfcore import cli
    record("freeze and journal-variant boundaries cannot be bypassed with --force",
           {"scientific_freeze_captured", "scientific_freeze_intact",
            "journal_variant_ready", "variant_preserves_science"}
           <= cli.NON_OVERRIDABLE_GATES,
           "capture, immutable source, required variant and content-preservation all hold")

    # ---- the variant --------------------------------------------------------
    freeze_env = {**os.environ, "MEDPAPER_PROJECT": str(scoped), "MEDPAPER_ROOT": str(ROOT),
                  "PYTHONIOENCODING": "utf-8"}
    docx_tool = ROOT / "tools/manuscript/build_docx.py"
    p = subprocess.run([
        sys.executable, str(docx_tool), "build", "--kind", "manuscript",
        "--input", "project/07_manuscript/full_manuscript.md",
        "--output", "project/08_submission/bundle/prevariant.docx",
        "--style-config", "project/08_submission/missing_style.json"],
        capture_output=True, text=True, env=freeze_env, encoding="utf-8", errors="replace")
    record("a frozen-source DOCX is refused even before the S20 variant exists",
           p.returncode != 0 and "scientific source is frozen" in
           ((p.stdout or "") + (p.stderr or ""))
           and not (scoped / "08_submission/bundle/prevariant.docx").exists(),
           ((p.stdout or "") + (p.stderr or "")).strip()[-160:])

    r = run("journal_variant_ready", "S20_journal")
    record("S20 requires a journal variant once the science is frozen", not r.ok, r.detail)
    scifreeze.open_variant(scoped, "Endoscopy International Open")
    r = run("journal_variant_ready", "S20_journal")
    record("opening the variant satisfies S20", r.ok, r.detail)
    record("the variant records which journal it is for",
           scifreeze.variant_meta(scoped).get("journal") == "Endoscopy International Open")
    record("the variant starts as a byte-identical copy of the frozen manuscript",
           (scoped / "08_submission/manuscript/full_manuscript.md").read_bytes()
           == (scoped / "07_manuscript/full_manuscript.md").read_bytes())
    record("opening a second variant over the first needs --force",
           _raises(lambda: scifreeze.open_variant(scoped, "Gut")),
           "switching journals discards the previous adaptation deliberately")

    record("path resolution follows the variant once it exists",
           scifreeze.resolve(scoped, "07_manuscript/full_manuscript.md")
           == "08_submission/manuscript/full_manuscript.md",
           "so word caps and structure are checked on what is actually submitted")
    record("scientific-only files still resolve to the frozen copy",
           scifreeze.resolve(scoped, "07_manuscript/results.md") == "07_manuscript/results.md",
           "only the journal-variable files move")
    record("polish evidence resolves beside the journal variant, not under frozen science",
           scifreeze.resolve(scoped, "07_manuscript/polish_report.json")
           == "08_submission/manuscript/polish_report.json"
           and scifreeze.resolve(scoped, "07_manuscript/prepolish/facts.json")
           == "08_submission/manuscript/prepolish/facts.json")

    polish_tool = ROOT / "tools/text/polish.py"
    p = subprocess.run([sys.executable, str(polish_tool), "snapshot"], capture_output=True,
                       text=True, env=freeze_env, encoding="utf-8", errors="replace")
    record("the S22 snapshot is written into the journal variant",
           p.returncode == 0
           and (scoped / "08_submission/manuscript/prepolish/facts.json").is_file()
           and not (scoped / "07_manuscript/prepolish").exists(),
           ((p.stdout or "") + (p.stderr or "")).strip()[-120:])
    subprocess.run([sys.executable, str(polish_tool), "lint"], capture_output=True,
                   text=True, env=freeze_env, encoding="utf-8", errors="replace")
    record("the S22 polish report is written into the journal variant",
           (scoped / "08_submission/manuscript/polish_report.json").is_file()
           and not (scoped / "07_manuscript/polish_report.json").exists())

    # Once a variant exists, the DOCX builder must refuse the frozen source even if somebody
    # copies an old command from a previous run.
    docx_tool = ROOT / "tools/manuscript/build_docx.py"
    p = subprocess.run([
        sys.executable, str(docx_tool), "build", "--kind", "manuscript",
        "--input", "project/07_manuscript/full_manuscript.md",
        "--output", "project/08_submission/bundle/should_not_exist.docx",
        "--style-config", "project/08_submission/missing_style.json"],
        capture_output=True, text=True, env=freeze_env, encoding="utf-8", errors="replace")
    record("S23 cannot build a journal DOCX directly from the frozen manuscript",
           p.returncode != 0 and "scientific source is frozen" in
           ((p.stdout or "") + (p.stderr or ""))
           and not (scoped / "08_submission/bundle/should_not_exist.docx").exists(),
           ((p.stdout or "") + (p.stderr or "")).strip()[-160:])
    bundle = scoped / "08_submission/bundle"
    bundle.mkdir(parents=True, exist_ok=True)
    (bundle / "dummy.docx").write_bytes(b"not parsed because source binding fails first")
    (bundle / "manifest.json").write_text(json.dumps({"items": [{
        "role": "manuscript", "file": "08_submission/bundle/dummy.docx",
        "source": "07_manuscript/full_manuscript.md"}]}), encoding="utf-8")
    try:
        packagecontent.build_baseline(scoped)
        rejected_source = False
    except ValueError as exc:
        rejected_source = "must bind to the journal variant" in str(exc)
    record("the S23 content baseline rejects a manifest bound to frozen source",
           rejected_source,
           "a package must hash the exact 08_submission/manuscript source it rendered")
    (bundle / "dummy.docx").unlink()
    (bundle / "manifest.json").unlink()

    # Gate specs are written against 07_manuscript; the runner must repoint them.
    rewritten = gates._resolve_manuscript_paths(
        {"check": "forbidden_symbols_absent",
         "paths": ["07_manuscript/full_manuscript.md", "04_tables/table_captions.md"]}, scoped)
    record("the gate runner repoints manuscript paths without editing pipeline.toml",
           rewritten["paths"] == ["08_submission/manuscript/full_manuscript.md",
                                  "04_tables/table_captions.md"],
           str(rewritten["paths"]))

    # ---- adaptation is allowed; losing content is not ----------------------
    var = scoped / "08_submission/manuscript/full_manuscript.md"
    var.write_text(body.replace("We analysed 412 patients.",
                                "We analysed 412 patients consecutively."), encoding="utf-8")
    r = run("variant_preserves_science", "S22_polish")
    record("tightening prose in the variant is allowed", r.ok, r.detail)

    var.write_text(body.replace("Discrimination reached 0.781 (Table 2).", ""), encoding="utf-8")
    r = run("variant_preserves_science", "S22_polish")
    record("dropping a result to fit a word cap is blocked",
           not r.ok and "0.781" in r.detail, r.detail)
    ok, problems, summary = scifreeze.variant_delta(scoped)
    record("the delta report names the lost number and the word change",
           not ok and any("0.781" in p for p in problems)
           and summary["full_manuscript.md"]["words_delta"] < 0,
           f"{summary['full_manuscript.md']}")

    st = State(scoped, ".wf").load()
    st.record_decision("journal_trim_authorised", "YES",
                       "user agreed to drop the secondary discrimination statistic to meet the "
                       "3000-word cap; it now appears in supplementary Methods")
    r = run("variant_preserves_science", "S22_polish")
    record("an authorised cut is accepted and says so", r.ok and "authorised" in r.detail, r.detail)

    # ---- switching journals must not touch the science or inherit journal A -----------
    before = (scoped / "07_manuscript/full_manuscript.md").read_bytes()
    variant_dir = scoped / "08_submission/manuscript"
    (variant_dir / "title_page.md").write_text("Journal A title-page format", encoding="utf-8")
    (variant_dir / "polish_log.md").write_text("Journal A house-style pass", encoding="utf-8")
    submission = scoped / "08_submission"
    (submission / "target_journal.json").write_text(
        '{"journal":"Endoscopy International Open"}', encoding="utf-8")
    (submission / "cover_letter.md").write_text("old cover letter", encoding="utf-8")
    (submission / "bundle").mkdir(parents=True, exist_ok=True)
    (submission / "bundle/old.docx").write_bytes(b"old journal bundle")
    (submission / "build_receipts").mkdir(parents=True, exist_ok=True)
    (submission / "build_receipts/old.json").write_text("{}", encoding="utf-8")
    (submission / "package_content_baseline.json").write_text("{}", encoding="utf-8")
    (submission / "package_human_review.md").write_text("old approval", encoding="utf-8")
    # polish_report.json and prepolish/ were created above; all of these are journal-A residue.
    record("open-variant refuses to switch journal names without a full reset",
           _raises(lambda: scifreeze.open_variant(scoped, "Gut", force=True)),
           "a different journal must clear S20 metadata/cache as well as manuscript/")
    scifreeze.open_variant(scoped, "Endoscopy International Open", force=True)
    record("rebuilding the current journal leaves the frozen manuscript byte-identical",
           (scoped / "07_manuscript/full_manuscript.md").read_bytes() == before,
           "this is the whole point of the split")
    record("a rebuilt variant is taken from frozen text, not the previous adaptation",
           (variant_dir / "full_manuscript.md").read_bytes() == before)
    record("rebuilding deletes every old variant file before copying",
           all(not (variant_dir / rel).exists() for rel in
               ("title_page.md", "polish_log.md", "polish_report.json", "prepolish")),
           "--force is replace-from-freeze, never an in-place overwrite")
    record("rebuilding a variant clears every S21+ downstream package artifact",
           all(not (submission / rel).exists() for rel in (
               "cover_letter.md", "bundle", "build_receipts",
               "package_content_baseline.json", "package_human_review.md")),
           "no cover letter, bundle, baseline, receipt or approval can cross variants")
    archived = sorted((submission / "journal_archives").glob("*/cover_letter.md"))
    record("the replaced variant and package are archived, not deleted",
           len(archived) == 1 and archived[0].read_text(encoding="utf-8") == "old cover letter"
           and (archived[0].parent / "manuscript/title_page.md").is_file()
           and archived[0].parent.name.startswith("endoscopy-international-open-"),
           str([p.relative_to(scoped).as_posix() for p in archived]))
    record("same-journal rebuild preserves the current S20 metadata",
           (submission / "target_journal.json").is_file())

    removed = scifreeze.reset_journal(scoped)
    live_tree = [p for p in submission.iterdir() if p.name != "journal_archives"]
    record("a full journal switch clears S20 metadata/cache and every downstream file",
           "08_submission/target_journal.json" in removed
           and not live_tree, f"removed {len(removed)} file(s)")
    record("reset-journal archives the old submission tree instead of deleting it",
           any((d / "target_journal.json").is_file()
               for d in (submission / "journal_archives").iterdir()),
           "a rejected journal's variant and package stay recoverable")
    orphan = run("no_orphans", "S20_journal")
    record("no_orphans ignores 08_submission/journal_archives/",
           not any("journal_archives" in part for part in orphan.detail.split(", ")),
           orphan.detail[:120])
    (submission / "target_journal.json").write_text('{"journal":"Gut"}', encoding="utf-8")
    scifreeze.open_variant(scoped, "Gut")
    record("the new journal starts from the same frozen text",
           (variant_dir / "full_manuscript.md").read_bytes() == before
           and scifreeze.variant_meta(scoped).get("journal") == "Gut")
    record("the frozen record still verifies after two journal cycles",
           run("scientific_freeze_intact", "S25_submission_audit").ok)

    # ---- a variant taken from stale science is refused ---------------------
    (scoped / "07_manuscript/full_manuscript.md").write_text(body + "\n# Extra\n\nx\n",
                                                             encoding="utf-8")
    record("a variant cannot be opened from drifted science",
           _raises(lambda: scifreeze.open_variant(scoped, "Gut", force=True)),
           "otherwise the submitted text stops tracing to what was reviewed")
    (scoped / "07_manuscript/full_manuscript.md").write_bytes(before)

    # ---- declared outputs follow the variant too ---------------------------
    # S21 declares 07_manuscript/title_page.md but must write it into the variant, so
    # outputs_exist has to look where the file actually belongs.
    for name in ("full_manuscript.md", "supplementary_methods.md", "statements.md"):
        src = scoped / "07_manuscript" / name
        if src.is_file():
            shutil.copy2(src, scoped / "08_submission/manuscript" / name)
    (scoped / "00_input").mkdir(parents=True, exist_ok=True)
    (scoped / "00_input/author_info.json").write_text('{"authors": []}', encoding="utf-8")
    r = run("outputs_exist", "S21_authors")
    record("a title page written only in 07_manuscript no longer satisfies S21",
           not r.ok and "title_page.md" in r.detail, r.detail)
    (scoped / "08_submission/manuscript/title_page.md").write_text(
        "# Title page\n\nAuthors: A B.\n", encoding="utf-8")
    r = run("outputs_exist", "S21_authors")
    record("writing it into the journal variant does satisfy S21", r.ok, r.detail)

    (scoped / "08_submission/manuscript/polish_report.json").write_text("{}", encoding="utf-8")
    (scoped / "08_submission/manuscript/polish_log.md").write_text(
        "# Polish log\n\nJournal-specific wording changes.\n", encoding="utf-8")
    r = run("outputs_exist", "S22_polish")
    record("S22 declared outputs are satisfied only by variant-side polish evidence",
           r.ok and not (scoped / "07_manuscript/polish_log.md").exists(), r.detail)

    (scoped / "08_submission/cache").mkdir(parents=True, exist_ok=True)
    (scoped / "08_submission/cache/old-journal.html").write_text("old", encoding="utf-8")
    removed = scifreeze.reset_journal(scoped)
    record("reset-journal clears the entire old submission tree before a new S20 run",
           "08_submission/cache/old-journal.html" in removed
           and not [p for p in (scoped / "08_submission").iterdir()
                    if p.name != "journal_archives"],
           f"removed {len(removed)} file(s)")
    record("reset-journal leaves the scientific freeze and manuscript unchanged",
           scifreeze.verify_freeze(scoped)[0]
           and (scoped / "07_manuscript/full_manuscript.md").read_bytes() == before)

    record("the invariant explains the freeze so it survives compaction",
           any("frozen when the user releases S19" in inv
               for inv in pipe.policy.get("invariants", [])))
    shutil.rmtree(scoped, ignore_errors=True)


def _raises(fn) -> bool:
    try:
        fn()
        return False
    except SystemExit:
        return True


def run_paper_overrides(proj: Path) -> None:
    """Paper-specific workflow shape lives with the paper and cannot weaken integrity gates."""
    import hashlib
    from unittest.mock import patch

    from wfcore import cli, gates, overrides, paths, registry
    from wfcore.checks import Ctx, get, load_all
    from wfcore.state import State

    section("paper-local overrides: customise one paper without mutating the master")
    scoped = proj / "temp/paper_overrides"
    scoped.mkdir(parents=True, exist_ok=True)
    master = registry.load()
    st = State(scoped, ".wf")
    st.create(master.meta["name"], master.meta["version"], master.first().id)

    def engine_snapshot() -> dict[str, str]:
        result = {}
        for dirname in ("pipeline", "tools", "reference", ".kiro"):
            root = ROOT / dirname
            if not root.exists():
                continue
            for path in root.rglob("*"):
                if (not path.is_file() or "__pycache__" in path.parts
                        or path.suffix in {".pyc", ".pyo"}):
                    continue
                result[path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
        return result

    before = engine_snapshot()
    env = {**os.environ, "MEDPAPER_PROJECT": str(scoped), "MEDPAPER_ROOT": str(ROOT),
           "PYTHONIOENCODING": "utf-8"}
    wf_tool = ROOT / "tools/wf.py"

    p = subprocess.run([sys.executable, str(wf_tool), "override", "init"],
                       capture_output=True, text=True, env=env, encoding="utf-8", errors="replace")
    local_file = scoped / ".wf/overrides.toml"
    record("wf override init writes inside the paper, not the engine",
           p.returncode == 0 and local_file.is_file()
           and not (ROOT / ".wf/overrides.toml").exists(),
           ((p.stdout or "") + (p.stderr or "")).strip()[-120:])
    record("the generated file is a no-op commented template",
           overrides.load(st.dir).get("schema") == 1
           and not overrides.load(st.dir).get("stage_override"),
           "uncomment only what this paper needs")
    p = subprocess.run([sys.executable, str(wf_tool), "override", "validate"],
                       capture_output=True, text=True, env=env, encoding="utf-8", errors="replace")
    record("the blank template validates without changing the workflow",
           p.returncode == 0 and "(none" in (p.stdout or ""), (p.stdout or "").strip()[-100:])

    stages = master.stages
    reason = ("This paper's design makes this stage structurally inapplicable while every "
              "protected integrity and review gate remains in force.")

    def invalid(name: str, data: dict, phrase: str) -> None:
        problems = overrides.validate(data, stages)
        record(name, any(phrase.casefold() in p.casefold() for p in problems), "; ".join(problems)[:180])

    invalid("a protected review stage cannot be skipped",
            {"schema": 1, "stage_override": [{"stage": "S18_independent_review",
                                               "skip": True, "reason": reason}]},
            "cannot be skipped")
    invalid("a protected review stage cannot have its gates relaxed",
            {"schema": 1, "stage_override": [{"stage": "S18_independent_review",
                                               "relax_gate": ["outputs_exist"],
                                               "reason": reason}]},
            "gates cannot be relaxed")
    invalid("a stage owning an integrity gate cannot be skipped",
            {"schema": 1, "stage_override": [{"stage": "S15_deepread",
                                               "skip": True, "reason": reason}]},
            "protected gate")
    invalid("a protected gate cannot be relaxed",
            {"schema": 1, "stage_override": [{"stage": "S19_human_review",
                                               "relax_gate": ["scientific_freeze_captured"],
                                               "reason": reason}]},
            "cannot be relaxed")
    invalid("a misspelled gate is refused instead of silently relaxing zero",
            {"schema": 1, "stage_override": [{"stage": "S07_artifacts",
                                               "relax_gate": ["md_section_typo"],
                                               "reason": reason}]},
            "not on this stage")
    invalid("weakening with a stub reason is refused",
            {"schema": 1, "stage_override": [{"stage": "S01_intake",
                                               "skip": True, "reason": "not needed"}]},
            "at least 40")
    invalid("an output cannot escape the paper directory",
            {"schema": 1, "stage_override": [{"stage": "S07_artifacts",
                                               "extra_outputs": ["../engine.txt"]}]},
            "inside the paper")
    invalid("an added gate cannot read outside the paper",
            {"schema": 1, "stage_override": [{"stage": "S07_artifacts",
                                               "add_gate": [{"check": "md_sections",
                                                             "path": "../../secret.md"}]}]},
            "inside the paper")
    invalid("freeform widening needs a substantive reason",
            {"schema": 1, "freeform": {"reason": "misc", "globs": ["extras/*.pdf"]}},
            "reason of at least")
    invalid("targets are kept in config.toml, not duplicated in overrides.toml",
            {"schema": 1, "targets": {"intro_words_max": 600}},
            "targets belong")
    invalid("skip cannot pretend to produce extra outputs",
            {"schema": 1, "stage_override": [{"stage": "S01_intake", "skip": True,
                                               "reason": reason,
                                               "extra_outputs": ["00_input/x.md"]}]},
            "cannot be combined")

    # A real overlay: two paper-specific skips plus one strengthened/relaxed future stage.
    valid_text = f'''schema = 1

[[stage_override]]
stage = "S01_intake"
skip = true
reason = "{reason}"

[[stage_override]]
stage = "S03_protocol"
skip = true
reason = "{reason}"

[[stage_override]]
stage = "S07_artifacts"
relax_gate = ["md_sections"]
extra_outputs = ["01_protocol/site_specific_artifact.md"]
reason = "This paper uses a machine-readable site form instead of the generic prose section, while all artifact integrity checks remain active."

[[stage_override.add_gate]]
check = "temp_clean"

[freeform]
reason = "The institution issues approval PDFs with server-generated filenames that cannot be declared one by one before retrieval."
globs = ["01_protocol/site_approvals/*.pdf"]
'''
    local_file.write_text(valid_text, encoding="utf-8")
    data = overrides.load(st.dir)
    problems = overrides.validate(data, stages)
    record("a documented paper-local overlay validates", not problems, "; ".join(problems))

    effective = registry.load(st.config(), data)
    record("the overlay marks only the named stages",
           effective.stage("S01_intake").skipped
           and effective.stage("S03_protocol").skipped
           and not effective.stage("S02_feasibility").skipped)
    record("a strengthening adds an output and a gate only to this paper",
           "01_protocol/site_specific_artifact.md" in effective.stage("S07_artifacts").outputs
           and any(g.get("check") == "temp_clean" for g in effective.stage("S07_artifacts").gate)
           and "01_protocol/site_specific_artifact.md" not in master.stage("S07_artifacts").outputs)
    record("the named non-protected gate is relaxed, while other gates remain",
           not any(g.get("check") == "md_sections" for g in effective.stage("S07_artifacts").gate)
           and any(g.get("check") == "artifact_plan_sane"
                   for g in effective.stage("S07_artifacts").gate))
    record("every effective change is printed for context-reset recovery",
           len(effective.override_notes) == 6
           and sum("SKIPPED" in note for note in effective.override_notes) == 2
           and any("relaxed" in note for note in effective.override_notes)
           and any("added" in note for note in effective.override_notes)
           and any("extra output" in note for note in effective.override_notes)
           and any("freeform" in note for note in effective.override_notes),
           " | ".join(effective.override_notes))
    record("all --force-resistant gates are also protected from config relaxation",
           cli.NON_OVERRIDABLE_GATES <= overrides.PROTECTED_CHECKS,
           str(sorted(cli.NON_OVERRIDABLE_GATES - overrides.PROTECTED_CHECKS)))

    # The current stage is skipped without fake outputs, a fake gate or a fake handoff.
    p = subprocess.run([sys.executable, str(wf_tool), "status", "--brief"],
                       capture_output=True, text=True, env=env, encoding="utf-8", errors="replace")
    record("status announces that the workflow is customised",
           p.returncode == 0 and "PAPER-LOCAL WORKFLOW OVERRIDES" in (p.stdout or "")
           and "S01_intake: SKIPPED" in (p.stdout or ""), (p.stdout or "").strip()[-180:])
    p = subprocess.run([sys.executable, str(wf_tool), "advance"],
                       capture_output=True, text=True, env=env, encoding="utf-8", errors="replace")
    st.load()
    record("advance records the active skip and moves to the next runnable stage",
           p.returncode == 0 and st.status_of("S01_intake") == "skipped"
           and st.current == "S02_feasibility",
           (p.stdout or "").strip()[-140:])
    record("the exact override that governed the skip is fingerprinted in state",
           st.stage_info("S01_intake").get("paper_override_fingerprint")
           == effective.stage("S01_intake").override_fingerprint)
    p = subprocess.run([sys.executable, str(wf_tool), "override", "init", "--force"],
                       capture_output=True, text=True, env=env, encoding="utf-8", errors="replace")
    record("--force cannot erase an override that is already workflow history",
           p.returncode != 0 and "already governed" in (p.stdout or ""),
           (p.stdout or "").strip()[-130:])

    # Simulate S02 becoming green: normal completion crosses consecutive paper-local skips.
    nxt, skipped = effective.transition_after("S02_feasibility")
    st.complete("S02_feasibility", nxt.id if nxt else None,
                [(s.id, s.skip_reason, s.override_fingerprint) for s in skipped],
                effective.stage("S02_feasibility").override_fingerprint)
    record("normal completion crosses a following skipped stage",
           nxt is not None and nxt.id == "S04_data"
           and st.status_of("S03_protocol") == "skipped" and st.current == "S04_data",
           f"next={nxt.id if nxt else None}; S03={st.status_of('S03_protocol')}")
    record("unchanged completed overrides remain valid",
           not overrides.validate_against_state(data, st))

    changed = json.loads(json.dumps(data))
    changed["stage_override"][1]["reason"] += " Retrospectively changed."
    issues = overrides.validate_against_state(changed, st)
    record("a completed stage's override cannot be edited retrospectively",
           any("changed after" in issue for issue in issues), "; ".join(issues))
    removed = {"schema": 1, "stage_override": data["stage_override"][2:],
               "freeform": data["freeform"]}
    issues = overrides.validate_against_state(removed, st)
    record("a completed stage's override cannot be silently removed",
           any("was removed" in issue or "changed after" in issue for issue in issues),
           "; ".join(issues))
    changed_freeform = json.loads(json.dumps(data))
    changed_freeform["freeform"]["globs"] = ["01_protocol/different/*.pdf"]
    issues = overrides.validate_against_state(changed_freeform, st)
    record("global freeform allowances are immutable after they governed a stage",
           any("changed after" in issue for issue in issues), "; ".join(issues))

    # A loop legitimately permits returning a stage from an overridden shape to the master.
    loop_root = scoped / "loop_override_to_master"
    loop_state = State(loop_root, ".wf")
    loop_state.create(master.meta["name"], master.meta["version"], master.first().id)
    one_override = {"schema": 1, "stage_override": [{
        "stage": "S01_intake", "extra_outputs": ["00_input/local.md"]}]}
    one_pipe = registry.load(None, one_override)
    loop_state.complete("S01_intake", "S02_feasibility", override_fingerprint=
                        one_pipe.stage("S01_intake").override_fingerprint)
    loop_state.rewind("S01_intake", "returning this stage to the master definition")
    record("an active rewound stage may remove its old override",
           not overrides.validate_against_state({}, loop_state))
    loop_state.complete("S01_intake", "S02_feasibility", override_fingerprint="")
    record("completion under the master clears the stale override fingerprint",
           "paper_override_fingerprint" not in loop_state.stage_info("S01_intake")
           and not overrides.validate_against_state({}, loop_state))

    # Simple targets already had a safe paper-local home; prove it remains separate.
    p = subprocess.run([sys.executable, str(wf_tool), "config", "set",
                        "intro_words_max", "601"], capture_output=True, text=True, env=env,
                       encoding="utf-8", errors="replace")
    record("wf config set writes only this paper's config.toml",
           p.returncode == 0 and (scoped / ".wf/config.toml").is_file()
           and "intro_words_max = 601" in (scoped / ".wf/config.toml").read_text(encoding="utf-8"))

    # In-process helpers must inherit the selected paper; this is the class of bug that leaked
    # 68 EFetch payloads into <engine>/project before _export_paper_env existed.
    old_project = os.environ.get("MEDPAPER_PROJECT")
    old_root = os.environ.get("MEDPAPER_ROOT")
    try:
        os.environ.pop("MEDPAPER_PROJECT", None)
        cli._export_paper_env(scoped)
        from pubmed import eutils as eu
        record("in-process PubMed helpers resolve to the active paper",
               eu.project_root().resolve() == scoped.resolve(), str(eu.project_root()))
        record("their cache directory is inside the paper, never <engine>/project",
               eu.cache_dir().resolve().is_relative_to(scoped.resolve()), str(eu.cache_dir()))
    finally:
        if old_project is None:
            os.environ.pop("MEDPAPER_PROJECT", None)
        else:
            os.environ["MEDPAPER_PROJECT"] = old_project
        if old_root is None:
            os.environ.pop("MEDPAPER_ROOT", None)
        else:
            os.environ["MEDPAPER_ROOT"] = old_root

    # Paper-owned scripts are also fenced: they must consume the selected root, and the wrapper
    # gives them that root even when invoked from the mother engine directory.
    code_dir = scoped / "03_analysis/code"
    code_dir.mkdir(parents=True, exist_ok=True)
    bad_script = code_dir / "bad_root.py"
    bad_script.write_text(
        "from pathlib import Path\nPath('project/03_analysis/results/x.txt').write_text('x')\n",
        encoding="utf-8")
    load_all()
    scoped_pipe = registry.load(st.config(), data)
    ctx = Ctx(pipeline=scoped_pipe, state=st, project=scoped,
              stage=scoped_pipe.stage("S05_analysis"),
              spec={"check": "paper_scripts_scoped",
                    "patterns": ["03_analysis/code/**/*.py"]})
    result = get("paper_scripts_scoped")(ctx)
    record("a paper script using Path('project') is blocked", not result.ok, result.detail)

    bad_script.write_text(
        "from pathlib import Path\n"
        "from wfcore.paths import project_dir\n"
        "PROJECT = project_dir()  # real call, but the write below ignores it\n"
        "open('project/03_analysis/results/x.txt', 'w').write('x')\n",
        encoding="utf-8")
    result = get("paper_scripts_scoped")(ctx)
    record("an unused safe-root call cannot hide a literal project/ write",
           not result.ok and "literal project/" in result.detail, result.detail)
    bad_r = code_dir / "bad_root.R"
    bad_r.write_text(
        'PROJECT <- Sys.getenv("MEDPAPER_PROJECT")\nwrite.csv(data.frame(x=1), "project/out.csv")\n',
        encoding="utf-8")
    ctx.spec["patterns"] = ["03_analysis/code/**/*.py", "03_analysis/code/**/*.R"]
    result = get("paper_scripts_scoped")(ctx)
    record("R scripts are covered by the same literal project/ protection",
           not result.ok and "bad_root.R" in result.detail, result.detail)
    bad_r.unlink()
    ctx.spec["patterns"] = ["03_analysis/code/**/*.py"]

    legacy_state = State(scoped / "legacy_state", ".wf")
    legacy_state.create(master.meta["name"], "1.3.9", "S05_analysis")
    legacy_state.migrate_pipeline(master.meta["version"], [s.id for s in master.stages])
    legacy_ctx = Ctx(pipeline=scoped_pipe, state=legacy_state, project=scoped,
                     stage=scoped_pipe.stage("S05_analysis"),
                     spec={"check": "paper_scripts_scoped",
                           "patterns": ["03_analysis/code/**/*.py"]})
    legacy_result = get("paper_scripts_scoped")(legacy_ctx)
    record("legacy origin does not soften paper_scripts_scoped",
           not legacy_result.ok and legacy_result.severity == "fail"
           and not any("Legacy paper migration" in hint for hint in legacy_result.hints),
           legacy_result.detail)
    migrated = State(scoped / "legacy_state2", ".wf")
    migrated.create(master.meta["name"], master.meta["version"], "S05_analysis")
    migrated.data["events"] = [{"kind": "pipeline_migration", "detail": "1.2.0 -> 1.4.0"}]
    migrated.data.pop("pipeline_origin_version", None)
    mig_result = get("paper_scripts_scoped")(Ctx(pipeline=scoped_pipe, state=migrated,
                                                 project=scoped,
                                                 stage=scoped_pipe.stage("S05_analysis"),
                                                 spec=legacy_ctx.spec))
    record("a 1.2 migration event does not soften paper_scripts_scoped either",
           not mig_result.ok and mig_result.severity == "fail", mig_result.detail[:100])

    bad_script.unlink()
    good_script = code_dir / "good_root.py"
    good_script.write_text(
        "from pathlib import Path\n"
        "from wfcore.paths import project_dir\n"
        "p = project_dir() / '03_analysis/results/run_script_marker.txt'\n"
        "p.parent.mkdir(parents=True, exist_ok=True)\n"
        "p.write_text('inside paper', encoding='utf-8')\n"
        "Path('cwd_marker.txt').write_text('paper cwd', encoding='utf-8')\n",
        encoding="utf-8")
    result = get("paper_scripts_scoped")(ctx)
    record("a paper script resolving project_dir passes the isolation gate", result.ok,
           result.detail)
    p = subprocess.run([sys.executable, str(wf_tool), "run-script",
                        "03_analysis/code/good_root.py"], capture_output=True, text=True,
                       env=env, encoding="utf-8", errors="replace")
    marker = scoped / "03_analysis/results/run_script_marker.txt"
    record("wf run-script executes with the selected paper as cwd",
           p.returncode == 0 and marker.is_file()
           and marker.read_text(encoding="utf-8") == "inside paper"
           and (scoped / "cwd_marker.txt").is_file()
           and (scoped / "cwd_marker.txt").read_text(encoding="utf-8") == "paper cwd",
           ((p.stdout or "") + (p.stderr or "")).strip()[-140:])
    p = subprocess.run([sys.executable, str(wf_tool), "run-script", "../outside.py"],
                       capture_output=True, text=True, env=env, encoding="utf-8", errors="replace")
    record("wf run-script refuses a path outside the paper",
           p.returncode != 0 and "outside the paper" in (p.stdout or ""),
           (p.stdout or "").strip()[-100:])
    with patch.dict(os.environ, {"MEDPAPER_PROJECT": str(scoped)}):
        try:
            paths.resolve_paper_path("project/../../project/engine-write.txt")
            escaped = False
        except ValueError:
            escaped = True
    record("the logical project/ alias rejects traversal out of the paper", escaped)
    with patch.dict(os.environ, {"MEDPAPER_PROJECT": str(scoped)}):
        try:
            paths.paper_output_path(ROOT / "project/engine-write.txt")
            absolute_output_rejected = False
        except ValueError:
            absolute_output_rejected = True
    record("engine helpers reject an explicit output outside the selected paper",
           absolute_output_rejected)

    # Standalone engine tools (not launched through wf.py) follow the user-level `wf use`
    # marker. Since 1.5.0 the marker lives under MEDPAPER_HOME (here a temp dir), holds the
    # paper's absolute path, and the papers root is outside the engine.
    st_root = Path(os.environ["MEDPAPER_SELFTEST_ROOT"])
    fake_paper = st_root / "papers2/selected"
    (fake_paper / ".wf").mkdir(parents=True)
    State(fake_paper, ".wf").create(master.meta["name"], master.meta["version"], master.first().id)
    home2 = st_root / "home2"
    home2.mkdir(parents=True)
    (home2 / "active").write_text(str(fake_paper.resolve()) + "\n", encoding="utf-8")
    standalone_env = {k: v for k, v in env.items() if k != "MEDPAPER_PROJECT"}
    standalone_env.update({"MEDPAPER_ROOT": str(ROOT), "PYTHONPATH": str(ROOT / "tools"),
                           "MEDPAPER_HOME": str(home2),
                           "MEDPAPER_PAPERS_ROOT": str(st_root / "papers2")})
    p = subprocess.run([sys.executable, "-c",
                        "from pubmed import eutils; print(eutils.project_root()); "
                        "print(eutils.cache_dir())"], capture_output=True, text=True,
                       env=standalone_env, cwd=st_root, encoding="utf-8", errors="replace")
    record("standalone PubMed tools follow the paper selected with wf use",
           p.returncode == 0 and str(fake_paper) in (p.stdout or "")
           and (fake_paper / "06_refs/cache").is_dir(),
           ((p.stdout or "") + (p.stderr or "")).strip()[-140:])
    p = subprocess.run([sys.executable, str(ROOT / "tools/data_manifest.py"), "init"],
                       capture_output=True, text=True, env=standalone_env, cwd=st_root,
                       encoding="utf-8", errors="replace")
    record("standalone data_manifest writes to the selected paper without --project",
           p.returncode == 0
           and (fake_paper / "02_data/acquisition_manifest.json").is_file(),
           ((p.stdout or "") + (p.stderr or "")).strip()[-140:])
    table_code = (
        "from tables.threeline import write_table; "
        "write_table('project/04_tables/main/Table1.xlsx','Table 1','Table 1. Test.',"
        "['Item','Value'],[['n','1']],['Data are counts.'])")
    p = subprocess.run([sys.executable, "-c", table_code], capture_output=True, text=True,
                       env=standalone_env, cwd=st_root, encoding="utf-8", errors="replace")
    record("the documented project/... alias maps table output into the selected paper",
           p.returncode == 0 and (fake_paper / "04_tables/main/Table1.xlsx").is_file(),
           ((p.stdout or "") + (p.stderr or "")).strip()[-120:])
    record("standalone tools did not create an engine project/ folder",
           not (ROOT / "project").exists(), str(ROOT / "project"))
    p = subprocess.run([sys.executable, "-c",
                        "from pubmed import eutils; print(eutils.project_root())"],
                       capture_output=True, text=True, env=standalone_env, cwd=ROOT,
                       encoding="utf-8", errors="replace")
    record("standalone tools refuse to resolve a paper from the engine cwd",
           p.returncode != 0 and "ENGINE workspace" in ((p.stdout or "") + (p.stderr or "")),
           ((p.stdout or "") + (p.stderr or "")).strip()[-120:])
    (home2 / "active").write_text(str(st_root / "papers2/missing-paper") + "\n", encoding="utf-8")
    p = subprocess.run([sys.executable, "-c",
                        "from pubmed import eutils; print(eutils.project_root())"],
                       capture_output=True, text=True, env=standalone_env, cwd=st_root,
                       encoding="utf-8", errors="replace")
    record("a stale active marker fails closed instead of guessing a paper",
           p.returncode != 0 and "state is missing" in ((p.stdout or "") + (p.stderr or ""))
           and not (ROOT / "project").exists(),
           ((p.stdout or "") + (p.stderr or "")).strip()[-150:])

    # Doctor hygiene: any paper artifact or unknown top-level entry in the engine is BROKEN.
    fake_engine = st_root / "fake_engine"
    fake_engine.mkdir(parents=True)
    engine_files = {".gitignore", "bootstrap.py", "LICENSE", "README.md", "requirements.txt",
                    "workflow.md"}
    for name in sorted(cli.ENGINE_TOP_LEVEL):
        if name in engine_files:
            (fake_engine / name).write_text("x", encoding="utf-8")
        else:
            (fake_engine / name).mkdir(parents=True, exist_ok=True)

    def hygiene() -> str:
        with patch.object(cli.paths, "repo_root", return_value=fake_engine):
            return cli._engine_hygiene_rows()[0][1]

    record("doctor hygiene: a clean engine is ok", hygiene() == "ok", hygiene())
    for rel, is_dir in (("papers", True), ("project", True), (".wf", True),
                        (".review_stash/f", False), ("temp/f", False), ("temp/.gitkeep", False),
                        ("foo.csv", False), ("stray_dir", True), ("tools/sub/.wf", True)):
        target = fake_engine / rel
        if is_dir:
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("x", encoding="utf-8")
        record(f"doctor hygiene: engine {rel} is BROKEN", hygiene() == "BROKEN")
        top = fake_engine / rel.split("/")[0] if rel.split("/")[0] not in ("tools",) else target
        shutil.rmtree(top, ignore_errors=True) if top.is_dir() else top.unlink(missing_ok=True)
    for cache in (".ruff_cache", ".mypy_cache", ".vscode", ".idea", "__pycache__"):
        (fake_engine / cache).mkdir(exist_ok=True)
    record("doctor hygiene: local tool caches are tolerated", hygiene() == "ok", hygiene())
    shutil.rmtree(fake_engine, ignore_errors=True)
    shutil.rmtree(st_root / "papers2", ignore_errors=True)
    shutil.rmtree(home2, ignore_errors=True)

    after = engine_snapshot()
    record("a full paper-local customisation cycle leaves every engine file byte-identical",
           before == after,
           f"before={len(before)} after={len(after)} changed="
           f"{sorted(set(before) ^ set(after))[:4]}")
    shutil.rmtree(scoped, ignore_errors=True)


def run_visual_deferral(proj: Path) -> None:
    """Deferring the visual pass must move the obligation to S23, never cancel it.

    The risk this section exists to disprove: that `visual_review_mode = "deferred"` is just a
    quality gate with the teeth pulled out. So every assertion here is about the *debt*
    surviving - through the S11 gate, through a re-render, and through `--force`.
    """
    from wfcore import cli, registry
    from wfcore.checks import Ctx, get, load_all
    from wfcore.state import State

    load_all()
    section("visual review: deferral moves the look, never drops it")

    pipe = registry.load()
    st = State(proj, ".wf")
    st.load()
    qc_rel = "05_figures/qc/qc_report.json"
    qc_path = proj / qc_rel

    def run(check_name: str, stage_id: str, mode: str, **spec):
        pipe.targets["visual_review_mode"] = mode
        ctx = Ctx(pipeline=pipe, state=st, project=proj,
                  stage=pipe.stage(stage_id), spec={"check": check_name, **spec})
        return get(check_name)(ctx)

    def set_reviewed(flag: bool) -> None:
        data = json.loads(qc_path.read_text(encoding="utf-8"))
        for f in data.get("figures", []):
            f["visual_reviewed"] = flag
        qc_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    record("engine default is deferred",
           str(registry.load().targets.get("visual_review_mode")) == "deferred",
           "the user asked for the look to wait until submission is in sight")

    # ---- the S11 decision gate ----------------------------------------------
    # An earlier section may already have recorded this decision; drop it so the
    # never-recorded path is what actually gets exercised here.
    st.data.get("decisions", {}).pop("figures_visually_confirmed", None)
    st.save()
    r = run("visual_confirmation", "S11_figures", "deferred", name="figures_visually_confirmed")
    record("unrecorded visual decision still blocks S11",
           not r.ok and "has not been recorded" in r.detail, r.detail)
    record("the block explains that DEFER is available in deferred mode",
           any("DEFER" in h for h in r.hints), "; ".join(r.hints)[:110])

    why = ("deterministic QC green for 1 figure: dpi, margins, fonts, overlap, glyphs and "
           "archetype elements all pass; judgement of colour and clutter deferred to S23")
    st.record_decision("figures_visually_confirmed", "DEFER", why)

    r = run("visual_confirmation", "S11_figures", "deferred", name="figures_visually_confirmed")
    record("DEFER passes S11 when mode is deferred", r.ok, r.detail)
    record("DEFER is reported as outstanding, not as verified",
           "outstanding" in r.detail.lower() and "parked" in r.detail.lower(), r.detail)

    r = run("visual_confirmation", "S11_figures", "inline", name="figures_visually_confirmed")
    record("DEFER is rejected when mode is inline", not r.ok, r.detail)

    st.record_decision("figures_visually_confirmed", "DEFER", "too short")
    r = run("visual_confirmation", "S11_figures", "deferred", name="figures_visually_confirmed")
    record("DEFER with a stub rationale is rejected", not r.ok, r.detail)
    st.record_decision("figures_visually_confirmed", "MAYBE", why)
    r = run("visual_confirmation", "S11_figures", "deferred", name="figures_visually_confirmed")
    record("a value that is neither YES nor DEFER is rejected", not r.ok, r.detail)
    st.record_decision("figures_visually_confirmed", "DEFER", why)

    # ---- S11's QC gate must not be softened beyond the visual flag ----------
    set_reviewed(False)
    r = run("figures_qc_pass", "S11_figures", "inline")
    record("inline mode: an unlooked-at figure blocks S11", not r.ok, r.detail)
    r = run("figures_qc_pass", "S11_figures", "deferred")
    record("deferred mode: an unlooked-at figure does not block S11", r.ok, r.detail)
    record("deferred pass message says the look is outstanding",
           "defer" in r.detail.lower(), r.detail)

    broken = json.loads(qc_path.read_text(encoding="utf-8"))
    broken["figures"][0]["checks"].append(
        {"name": "effective_dpi", "ok": False, "severity": "fail", "detail": "injected"})
    qc_path.write_text(json.dumps(broken, indent=2, ensure_ascii=False), encoding="utf-8")
    r = run("figures_qc_pass", "S11_figures", "deferred")
    record("deferring does NOT excuse a deterministic QC failure", not r.ok, r.detail)
    broken["figures"][0]["checks"] = [c for c in broken["figures"][0]["checks"]
                                      if c.get("detail") != "injected"]
    qc_path.write_text(json.dumps(broken, indent=2, ensure_ascii=False), encoding="utf-8")

    # ---- the S23 debt gate ---------------------------------------------------
    r = run("visual_debts_cleared", "S23_package", "deferred")
    record("S23 is blocked while the DEFER decision stands", not r.ok, r.detail)
    record("S23 failure names the parked decision",
           "figures_visually_confirmed" in r.detail, r.detail)
    record("S23 failure hands over the one-load contact sheet",
           any("contact-sheet" in h for h in r.hints), "; ".join(r.hints)[:120])

    st.record_decision("figures_visually_confirmed", "YES",
                       "loaded the contact sheet and Figure 1 at full size; axis units, legend "
                       "placement and greyscale contrast all acceptable; no changes needed")
    r = run("visual_debts_cleared", "S23_package", "deferred")
    record("clearing the decision alone is not enough - the QC flag is a second ledger",
           not r.ok, r.detail)

    set_reviewed(True)
    r = run("visual_debts_cleared", "S23_package", "deferred")
    record("S23 clears once both ledgers agree the figures were seen", r.ok, r.detail)

    record("visual_debts_cleared cannot be bypassed with --force",
           "visual_debts_cleared" in cli.NON_OVERRIDABLE_GATES,
           "a deferred look must not be droppable by an override")

    # ---- the debt is visible after a context reset --------------------------
    st.record_decision("tables_visually_confirmed", "DEFER", why)
    import io
    from contextlib import redirect_stdout
    buf = io.StringIO()
    with redirect_stdout(buf):
        cli._print_visual_debts(pipe, st)
    shown = buf.getvalue()
    record("wf status reprints parked reviews so a compaction cannot lose them",
           "tables_visually_confirmed" in shown and "S23_package" in shown, shown.strip()[:90])

    # ---- the contact sheet and the confirm receipt --------------------------
    env = {**os.environ, "MEDPAPER_PROJECT": str(proj), "MEDPAPER_ROOT": str(ROOT),
           "PYTHONIOENCODING": "utf-8"}
    qc = str(ROOT / "tools/figures/qc.py")
    p = subprocess.run([sys.executable, qc, "--contact-sheet"],
                       capture_output=True, text=True, env=env, encoding="utf-8", errors="replace")
    sheet = proj / "05_figures/qc/contact_sheet.png"
    record("contact sheet renders every planned figure into one image",
           p.returncode == 0 and sheet.exists(),
           ((p.stdout or "") + (p.stderr or "")).strip()[-160:])
    if sheet.exists():
        import matplotlib.image as mpimg
        arr = mpimg.imread(str(sheet))
        record("contact sheet is a real raster, not an empty canvas",
               arr.ndim == 3 and arr.shape[0] > 100 and arr.shape[1] > 100,
               f"{arr.shape}")

    set_reviewed(False)
    p = subprocess.run([sys.executable, qc, "--confirm", "Figure 1", "--note", "too short"],
                       capture_output=True, text=True, env=env, encoding="utf-8", errors="replace")
    record("--confirm refuses a note that says nothing", p.returncode != 0,
           ((p.stdout or "") + (p.stderr or "")).strip()[-90:])

    p = subprocess.run([sys.executable, qc, "--confirm", "Figure 1", "--note",
                        "axis units, legend placement and greyscale contrast all fine"],
                       capture_output=True, text=True, env=env, encoding="utf-8", errors="replace")
    data = json.loads(qc_path.read_text(encoding="utf-8"))
    record("--confirm records the look without hand-editing the report",
           p.returncode == 0 and data["figures"][0].get("visual_reviewed") is True,
           ((p.stdout or "") + (p.stderr or "")).strip()[-90:])
    record("--confirm keeps a dated note of what was seen",
           bool(data["figures"][0].get("review_log")),
           str(data["figures"][0].get("review_log"))[:90])

    # A re-render must invalidate the confirmation, or a stale look could ship.
    png = proj / data["figures"][0]["png"]
    if png.exists():
        # The binding is the PNG's SHA-256 (1.6.0): changed bytes, not a touched mtime.
        original_png = png.read_bytes()
        png.write_bytes(original_png + b"\0")
        p = subprocess.run([sys.executable, qc, "--confirm", "Figure 1", "--note",
                            "trying to confirm against a stale QC report on purpose"],
                           capture_output=True, text=True, env=env, encoding="utf-8",
                           errors="replace")
        record("--confirm refuses a report made stale by a re-render", p.returncode != 0,
               ((p.stdout or "") + (p.stderr or "")).strip()[-100:])
        png.write_bytes(original_png)

    # Leave the fixture as later sections expect it.
    set_reviewed(True)
    pipe.targets["visual_review_mode"] = "deferred"


def run_archetypes(proj: Path) -> None:
    """The archetype gate must detect mandatory elements, not take the plan's word for it."""
    import tomllib

    import matplotlib.pyplot as plt
    import numpy as np
    from figures import elements as el
    from figures.style import apply_style, figure, save
    from wfcore import registry
    from wfcore.checks import Ctx, get, load_all
    from wfcore.state import State

    section("archetypes: registry")
    reg = tomllib.loads((ROOT / "reference/archetypes.toml").read_text(encoding="utf-8"))
    arches = reg.get("archetype", {})
    record("registry parses", bool(arches), f"{len(arches)} archetype(s)")
    unknown = sorted({k for a in arches.values()
                      for k in list(a.get("requires", [])) + list(a.get("forbids", []))}
                     - set(el.DETECTORS))
    record("every requires/forbids element has a detector", not unknown,
           f"undetectable: {unknown}" if unknown else
           f"{len(el.DETECTORS)} detectors cover all mandatory elements")
    universal = reg.get("meta", {}).get("universal_requires", [])
    record("universal requires are detectable",
           all(u in el.DETECTORS for u in universal), f"{universal}")

    section("archetypes: element detection on constructed figures")
    apply_style()
    rng = np.random.default_rng(3)

    # a compliant bar_dot: points, error bars, baseline at zero
    fig, panels = figure(width="single", height_mm=60, panels=(1, 1), letters=False)
    _, ax = panels[0]
    ax.bar([1, 2], [3.0, 4.2], yerr=[0.4, 0.5], capsize=2.5, color=["C0", "C1"], alpha=0.35,
           edgecolor="black", linewidth=0.6)
    for i, m in ((1, 3.0), (2, 4.2)):
        ax.scatter(np.full(5, i) + rng.normal(0, 0.05, 5), rng.normal(m, 0.3, 5),
                   s=6, color="black", zorder=3)
    ax.set_ylim(0, 5.5)
    ax.set_xticks([1, 2]); ax.set_xticklabels(["Control", "Treated"])
    ax.set_xlabel("Group"); ax.set_ylabel("Relative expression")
    found = el.detect_all(fig)
    for key in reg["archetype"]["bar_dot"]["requires"]:
        record(f"bar_dot detects {key}", found[key]["found"], found[key]["evidence"][:70])
    plt.close(fig)

    # the same figure with a truncated baseline must fail
    fig, panels = figure(width="single", height_mm=60, panels=(1, 1), letters=False)
    _, ax = panels[0]
    ax.bar([1, 2], [3.0, 4.2], color="C0")
    ax.set_ylim(2.5, 4.5)
    ax.set_xlabel("Group"); ax.set_ylabel("Relative expression")
    found = el.detect_all(fig)
    record("truncated bar baseline is detected", not found["baseline_zero"]["found"],
           found["baseline_zero"]["evidence"][:70])
    record("missing individual points are detected", not found["individual_points"]["found"])
    plt.close(fig)

    # missing axis labels
    fig, panels = figure(width="single", height_mm=50, panels=(1, 1), letters=False)
    _, ax = panels[0]
    ax.plot([0, 1], [0, 1])
    found = el.detect_all(fig)
    record("missing axis labels are detected", not found["axis_labels"]["found"],
           found["axis_labels"]["evidence"][:70])
    plt.close(fig)

    # a missing glyph must be caught during rasterization
    fig, panels = figure(width="single", height_mm=40, panels=(1, 1), letters=False)
    _, ax = panels[0]
    ax.plot([0, 1], [0, 1]); ax.set_xlabel("x"); ax.set_ylabel("y")
    ax.text(0.4, 0.5, "\u2f00\u2f01\u4e2d\u6587")     # glyphs absent from the Latin stack
    warns = el.glyph_warnings(fig)
    record("missing font glyphs are caught", bool(warns),
           (warns[0][:70] if warns else "no warning raised - font may cover these glyphs"))
    plt.close(fig)

    # tick labels forced to collide
    fig, panels = figure(width="single", height_mm=40, panels=(1, 1), letters=False)
    _, ax = panels[0]
    ax.plot(range(40), range(40))
    ax.set_xticks(range(40))
    ax.set_xticklabels([f"label{i}" for i in range(40)])
    ax.set_xlabel("x"); ax.set_ylabel("y")
    fig.canvas.draw()
    coll = el.tick_label_collisions(fig, fig.canvas.get_renderer())
    record("tick-label collisions are caught", bool(coll),
           f"{len(coll)} collision(s)" if coll else "none detected")
    plt.close(fig)

    # a deliberate dead band between panels
    fig, panels = figure(width="single", height_mm=90, panels=(1, 1), letters=False)
    sf, ph = panels[0]
    ph.remove()
    a1, a2 = sf.subplots(2, 1, gridspec_kw={"hspace": 1.4})
    for a in (a1, a2):
        a.plot([0, 1], [0, 1]); a.set_xlabel("x"); a.set_ylabel("y")
    fig.canvas.draw()
    voids = el.interior_voids(fig, fig.canvas.get_renderer())
    record("interior dead band is caught", bool(voids),
           f"{voids[0]['gap_pct']}% gap" if voids else "none detected")
    plt.close(fig)

    section("archetypes: gate rejects a plan without an archetype")
    load_all()
    pipe = registry.load()
    st = State(proj, ".wf").load()
    plan_path = proj / "01_protocol/artifact_plan.json"
    original = plan_path.read_text(encoding="utf-8")
    plan = json.loads(original)

    def plan_check():
        fn = get("artifact_plan_sane")
        return fn(Ctx(pipeline=pipe, state=st, project=proj, stage=pipe.stage("S07_artifacts"),
                      spec={"check": "artifact_plan_sane", "path": "01_protocol/artifact_plan.json"}))

    plan["main_figures"][0].pop("archetype", None)
    plan_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    r = plan_check()
    record("figure without an archetype is rejected", not r.ok, r.detail[:90])

    plan["main_figures"][0]["archetype"] = "not_a_real_archetype"
    plan_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    r = plan_check()
    record("unknown archetype is rejected", not r.ok, r.detail[:90])

    plan["main_figures"][0]["archetype"] = "other"
    plan["main_figures"][0].pop("archetype_rationale", None)
    plan_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    r = plan_check()
    record("archetype 'other' without a rationale is rejected", not r.ok, r.detail[:90])

    plan["main_figures"][0]["archetype"] = "roc_curve"
    plan_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    r = plan_check()
    record("valid archetype is accepted", r.ok, r.detail[:90])
    plan_path.write_text(original, encoding="utf-8")

    section("archetypes: journal palettes")
    for name in ("okabe_ito", "nejm", "lancet", "jama", "jco", "nature"):
        colors = apply_style(palette=name)
        ok = isinstance(colors, list) and len(colors) >= 5 and all(
            c.startswith("#") and len(c) == 7 for c in colors)
        record(f"palette {name}", ok, f"{len(colors)} colours")
    try:
        apply_style(palette="nope")
        record("unknown palette is rejected", False, "accepted silently")
    except ValueError as exc:
        record("unknown palette is rejected", True, str(exc)[:60])
    apply_style()
    import matplotlib
    record("axes.unicode_minus disabled", matplotlib.rcParams["axes.unicode_minus"] is False,
           "a negative sign cannot render as a missing-glyph box")


def run_codex_integration() -> None:
    """Repository-local Kiro integration must be complete and internally consistent."""
    import tomllib

    section("Kiro integration")
    required = [
        ROOT / ".kiro/steering/medpaper-pipeline.md",
        ROOT / ".kiro/skills/medpaper-pipeline/SKILL.md",
        ROOT / ".kiro/hooks/medpaper-status.json",
        ROOT / ".kiro/hooks/medpaper-skill-guard.json",
        ROOT / "tools/install_adapters.py",
        ROOT / "tools/hooks/skill_guard.py",
        ROOT / "reference/skill_policy.toml",
        ROOT / "reference/methods-structure.md",
        ROOT / "reference/rework-routing.md",
        ROOT / "tools/rework.py",
        ROOT / "tools/manuscript/review_package.py",
        ROOT / "tools/wfcore/reviewpackage.py",
        ROOT / "tools/package_content.py",
        ROOT / "tools/wfcore/refproof.py",
        ROOT / "tools/wfcore/dataproof.py",
        ROOT / "tools/data_manifest.py",
        ROOT / "reference/data-acquisition-integrity.md",
    ]
    record("repository Kiro files exist", all(p.is_file() for p in required),
           ", ".join(str(p.relative_to(ROOT)) for p in required if not p.is_file()))

    steering = required[0].read_text(encoding="utf-8")
    skill = required[1].read_text(encoding="utf-8")
    pipe = tomllib.loads((ROOT / "pipeline/pipeline.toml").read_text(encoding="utf-8"))
    record("skill identity is valid",
           skill.startswith("---\nname: medpaper-pipeline\n") and
           "description:" in skill.split("---", 2)[1],
           "frontmatter name/description")
    record("steering is always-included and points at the driver",
           steering.startswith("---\ninclusion: always\n") and
           "tools/wf.py status" in steering,
           "inclusion: always + wf status entrypoint")
    record("skill and steering describe 25 stages",
           "25-stage" in skill and "25 stages" in steering,
           "stage count stated in both adapters")
    for name, path in (("status", required[2]), ("skill guard", required[3])):
        hook = json.loads(path.read_text(encoding="utf-8"))
        spec = hook["hooks"][0]
        record(f"{name} hook is wired",
               spec["action"]["type"] == "command" and spec["trigger"] in
               ("SessionStart", "PreToolUse"),
               f'{spec["trigger"]} -> {spec["action"]["command"]}')

    other_agents = [ROOT / "AGENTS.md", ROOT / "CLAUDE.md", ROOT / ".agents",
                    ROOT / ".claude", ROOT / ".agent", ROOT / "INSTALL-CODEX.md",
                    ROOT / "reference/codex-integration.md"]
    present = [str(p.relative_to(ROOT)) for p in other_agents if p.exists()]
    record("no other-agent adapters left to drift", not present, ", ".join(present))

    # Delegated review agents. A reviewer that can write files or advance a stage is not a
    # reviewer, so read-only is the property under test, not merely their existence.
    for name, stages in (("medpaper-reviewer", "S18/S25"), ("medpaper-deepreader", "S15")):
        path = ROOT / f".kiro/agents/{name}.md"
        if not path.is_file():
            record(f"{name} agent exists", False, f"missing .kiro/agents/{name}.md")
            continue
        text = path.read_text(encoding="utf-8")
        record(f"{name} is read-only", 'tools: ["read"]' in text,
               f"used at {stages}; tools must be read-only")
        denied = [cap for cap in ("fs_write", "shell", "mcp", "subagent")
                  if f"capability: {cap}" not in text]
        record(f"{name} denies write/shell/mcp/subagent", not denied,
               f"not denied: {denied}" if denied else "defence in depth beyond tools list")
        record(f"{name} refuses to drive the pipeline",
               "does not apply to you" in text,
               "explicitly disowns workspace pipeline instructions")

    steering_text = (ROOT / ".kiro/steering/medpaper-pipeline.md").read_text(encoding="utf-8")
    record("steering exempts delegated subagents",
           "delegated subagent" in steering_text and "do not advance a stage" in steering_text,
           "steering is shared with subagents and is not isolated, so it must disown them")

    for stage_id, agent in (("S15_deepread", "medpaper-deepreader"),
                            ("S18_independent_review", "medpaper-reviewer"),
                            ("S25_submission_audit", "medpaper-reviewer")):
        card = (ROOT / f"pipeline/stages/{stage_id}.md").read_text(encoding="utf-8")
        record(f"{stage_id} names its delegate", agent in card,
               f"card must name `{agent}` so the work is not done in the main context")

    record("pipeline and skill versions agree",
           pipe["meta"]["version"] == "1.8.0" and 'version: "2.1.0"' in skill,
           f'pipeline={pipe["meta"]["version"]}, skill=2.1.0 (Kiro adapter revision)')
    record("all 25 stage cards exist",
           len(pipe["stage"]) == 25 and
           all((ROOT / "pipeline" / s["card"]).is_file() for s in pipe["stage"]),
           f'{len(pipe["stage"])} stage(s)')

    stage_ids = [s["id"] for s in pipe["stage"]]
    record("manuscript review precedes authors and packaging",
           stage_ids.index("S17_assemble") < stage_ids.index("S18_independent_review") <
           stage_ids.index("S19_human_review") < stage_ids.index("S20_journal") <
           stage_ids.index("S21_authors") < stage_ids.index("S23_package") <
           stage_ids.index("S24_package_human_review") < stage_ids.index("S25_submission_audit"),
           "assemble -> publishability review -> user manuscript review -> journal -> authors -> package -> user package OK -> final audit")
    independent = next(s for s in pipe["stage"] if s["id"] == "S18_independent_review")
    human = next(s for s in pipe["stage"] if s["id"] == "S19_human_review")
    authors = next(s for s in pipe["stage"] if s["id"] == "S21_authors")
    package_human = next(s for s in pipe["stage"] if s["id"] == "S24_package_human_review")
    final_audit = next(s for s in pipe["stage"] if s["id"] == "S25_submission_audit")
    review_card = (ROOT / "pipeline/stages/S18_independent_review.md").read_text(encoding="utf-8")
    package_card = (ROOT / "pipeline/stages/S23_package.md").read_text(encoding="utf-8")
    package_human_card = (ROOT / "pipeline/stages/S24_package_human_review.md").read_text(encoding="utf-8")
    human_card = (ROOT / "pipeline/stages/S19_human_review.md").read_text(encoding="utf-8")
    journal_card = (ROOT / "pipeline/stages/S20_journal.md").read_text(encoding="utf-8")
    final_audit_card = (ROOT / "pipeline/stages/S25_submission_audit.md").read_text(encoding="utf-8")
    record("independent reviewer is singular, read-only, and before author intake",
           independent.get("needs_user", False) is False and human.get("needs_user") is True and
           authors.get("needs_user") is True and "exactly one independent subagent" in review_card and
           "must not edit files" in review_card and "Do not ask for authors" in
           (ROOT / "pipeline/stages/S19_human_review.md").read_text(encoding="utf-8"),
           "one frozen-package review, then user review, then authors")
    record("final package audit waits for explicit user OK and is independent",
           package_human.get("needs_user") is True and
           final_audit.get("needs_user", False) is False and
           "是否确认 OK" in package_human_card and
           "tools/package_review.py freeze" in package_human_card and
           "exactly one independent read-only subagent" in final_audit_card and
           "Freeze ID: <freeze_id>" in final_audit_card and
           "allowed = [\"PASS\"]" in
           (ROOT / "pipeline/pipeline.toml").read_text(encoding="utf-8") and
           "loop --to S24_package_human_review" in final_audit_card,
           "user confirmation -> immutable freeze -> one guideline audit -> PASS or S24 loop")
    final_headings = next(g for g in final_audit["gate"]
                          if g["check"] == "md_sections")["headings"]
    record("final independent audit includes reader and editor lenses",
           "ordinary scientific reader" in final_audit_card and
           "Editorial screening" in final_audit_card and
           "low-level errors" in final_audit_card and
           "Reader comprehension" in final_headings and
           "Editorial screening and low-level errors" in final_headings and
           "objective low-level error" in final_audit_card and
           "never edits the frozen package" in final_audit_card,
           "first-time comprehension + editorial error screen + journal compliance")
    human_checks = {gate["check"] for gate in human["gate"]}
    package_checks = {gate["check"] for gate in package_human["gate"]}
    package_stage = next(s for s in pipe["stage"] if s["id"] == "S23_package")
    record("user revisions are source-routed and mechanically gated",
           "assembly_matches_sources" in human_checks and
           "package_content_matches_baseline" in package_checks and
           "revision_rounds_closed" in human_checks and
           "revision_rounds_closed" in package_checks and
           any(gate["check"] == "revision_rounds_closed" for gate in final_audit["gate"]) and
           "08_submission/package_content_baseline.json" in package_stage["outputs"] and
           "tools/rework.py batch" in package_human_card and
           "tools/rework.py status" in package_human_card and
           "Never recapture at S24" in package_human_card,
           "persisted S19/S24 rounds + component equality + visible-text enforcement")
    record("S19 requires a current third-party ZIP and explicit no-further-review decision",
           "manuscript_review_package_current" in human_checks and
           "s19_review_release_explicit" in human_checks and
           "tools/manuscript/review_package.py build" in human_card and
           "无需继续审核，可以进入下一步" in human_card and
           "05_figures/out/" in human_card and "exact ZIP" in human_card and
           '"s19_review_release_explicit"' in
           (ROOT / "tools/wfcore/cli.py").read_text(encoding="utf-8"),
           "versioned review ZIP + exact paths + package-bound non-overridable stop")
    journal = next(s for s in pipe["stage"] if s["id"] == "S20_journal")
    polish = next(s for s in pipe["stage"] if s["id"] == "S22_polish")
    journal_stages = {s["id"]: {g["check"] for g in s["gate"]}
                      for s in pipe["stage"] if s["id"] in {
                          "S20_journal", "S21_authors", "S22_polish", "S23_package",
                          "S24_package_human_review", "S25_submission_audit"}}
    record("S19 freezes science and every journal stage keeps that boundary",
           "scientific_freeze_captured" in human_checks
           and all({"scientific_freeze_intact", "journal_variant_ready"}.issubset(checks_)
                   for checks_ in journal_stages.values())
           and all("variant_preserves_science" in journal_stages[sid] for sid in {
               "S22_polish", "S23_package", "S24_package_human_review",
               "S25_submission_audit"})
           and "07_manuscript/scientific_freeze.json" in human["outputs"],
           "S19 capture -> S20 variant -> S22/S23/S24/S25 intact/delta checks")
    record("S23 renders the journal variant, never the frozen manuscript",
           "--input project/08_submission/manuscript/full_manuscript.md" in package_card
           and "--input project/08_submission/manuscript/title_page.md" in package_card
           and "--input project/07_manuscript/full_manuscript.md" not in package_card,
           "the Word source lives inside the submission integration area")
    record("journal switching clears the old submission tree before rebuilding S20",
           "reset-journal --confirm-journal" in journal_card
           and "loop --to S20_journal" in journal_card
           and "not merely call `open-variant --force`" in journal_card,
           "old cache, cover letter, bundle and approvals cannot survive")
    record("Word package contract covers reported defects",
           all(term in package_card for term in ("all text black", "external hyperlinks",
                                                  "supplementary Methods", "Figure legends",
                                                  "collapsible heading")),
           "typography, links, supplementary Word file, legends and heading behavior")
    reflib = next(s for s in pipe["stage"] if s["id"] == "S13_reflib")
    live_reference_stages = {
        stage["id"] for stage in pipe["stage"]
        if any(gate.get("check") == "reference_provenance" and gate.get("live") is True
               for gate in stage.get("gate", []))
    }
    required_live_stages = {
        "S13_reflib", "S14_introduction", "S16_discussion", "S17_assemble",
        "S18_independent_review", "S19_human_review", "S21_authors", "S22_polish",
        "S23_package", "S24_package_human_review", "S25_submission_audit",
    }
    record("reference verification is live, evidence-bound and non-overridable",
           any(g.get("check") == "reference_provenance" and g.get("live") is True
               for g in reflib["gate"]) and
           required_live_stages.issubset(live_reference_stages) and
           "verified: true` by itself has no authority" in
           (ROOT / "pipeline/stages/S13_reflib.md").read_text(encoding="utf-8") and
           "NON_OVERRIDABLE_GATES" in
           (ROOT / "tools/wfcore/cli.py").read_text(encoding="utf-8"),
           "fresh EFetch + raw XML/library hashes + repeated live checks through final audit")
    acquisition_stages = {
        stage["id"] for stage in pipe["stage"]
        if any(gate.get("check") == "data_acquisition_complete"
               for gate in stage.get("gate", []))
    }
    record("full data acquisition is evidence-bound and non-overridable",
           {"S04_data", "S05_analysis", "S06_protocol_final", "S17_assemble",
            "S23_package", "S25_submission_audit"}.issubset(acquisition_stages) and
           "02_data/acquisition_manifest.json" in
           next(s for s in pipe["stage"] if s["id"] == "S04_data")["outputs"] and
           '"data_acquisition_complete"' in
           (ROOT / "tools/wfcore/cli.py").read_text(encoding="utf-8") and
           "full_protocol_defined_universe" in
           (ROOT / "pipeline/stages/S04_data.md").read_text(encoding="utf-8"),
           "source total + received counts + pagination + raw/code hashes + anti-cap scan")

    legacy = [
        ROOT / ".agents", ROOT / ".claude", ROOT / ".agent",
        ROOT / "AGENTS.md", ROOT / "CLAUDE.md", ROOT / ".medpaper-target",
    ]
    record("obsolete multi-agent adapters are absent", not any(p.exists() for p in legacy),
           ", ".join(str(p.relative_to(ROOT)) for p in legacy if p.exists()))

    policy_text = "\n".join(p.read_text(encoding="utf-8") for p in required)
    cards_text = "\n".join(
        (ROOT / "pipeline" / s["card"]).read_text(encoding="utf-8") for s in pipe["stage"])
    record("AI disclosure remains user-controlled",
           "Do not draft or insert an AI-use disclosure" in
           "\n".join(pipe["policy"]["invariants"]) and
           "Disclose AI assistance honestly" not in cards_text,
           "no autonomous disclosure instruction")
    record("capability arbitration is documented",
           "sole workflow orchestrator" in policy_text and
           "must be registered" in policy_text.lower(),
           "pipeline owns state/gates; helpers remain stage-scoped")

    methods_stage = next(s for s in pipe["stage"] if s["id"] == "S08_methods")
    outputs_gate = next(g for g in methods_stage["gate"] if g["check"] == "outputs_exist")
    methods_card = (ROOT / "pipeline/stages/S08_methods.md").read_text(encoding="utf-8")
    methods_guide = (ROOT / "reference/methods-structure.md").read_text(encoding="utf-8")
    record("supplementary Methods is declared but optional",
           "07_manuscript/supplementary_methods.md" in methods_stage["outputs"] and
           outputs_gate.get("optional") == ["07_manuscript/supplementary_methods.md"] and
           any(g.get("path") == "07_manuscript/supplementary_methods.md" and
               g.get("optional") is True for g in methods_stage["gate"]) and
           not any("exactly ONE manuscript section file" in rule
                   for rule in pipe.get("policy", {}).get("invariants", [])),
           "S08 optional output contract")
    record("Methods architecture prevents subsection inflation",
           "Do not append automatic standalone headings" in methods_card and
           "Statistical analysis" in methods_guide and
           "not a mandatory template" in methods_guide,
           "flexible core structure plus supplement boundary")
    record("supplementary Methods cannot absorb display tables or Markdown rules",
           any(g.get("check") == "supplementary_methods_clean"
               for g in methods_stage["gate"]) and
           "three-line supplementary workbook" in methods_guide and
           "do not embed Markdown" in methods_card,
           "supplement prose only; Table S* stays in the S10 workbook")
    record("ImageGen is review-only for scientific figures",
           "second visual critic" in policy_text and
           "must not redraw" in policy_text,
           "S11 preserves data geometry and requires a fresh render")

    # ---- the external figure skill, and the conflict table that keeps it honest -------
    import tomllib as _toml
    from wfcore import registry as _reg
    policy = _toml.loads((ROOT / "reference/skill_policy.toml").read_text(encoding="utf-8"))
    entries = {s["name"]: s for s in policy.get("skill", [])}
    figskill = entries.get("medical-sci-figure-skill")
    record("the external figure skill is registered, not left to default-allow",
           figskill is not None and figskill.get("verdict") == "gated",
           str(figskill.get("verdict") if figskill else "missing"))
    record("its entry says the pipeline still renders and judges",
           bool(figskill) and "tools/figures/style.py" in figskill["reason"]
           and "tools/figures/qc.py" in figskill["reason"]
           and "not as the renderer" in figskill["reason"],
           "reading and styling only; qc.py remains the judge")

    auth = policy.get("figure_authority", {})
    conflicts = auth.get("conflict", [])
    record("every figure-authority conflict is resolved in the pipeline's favour",
           len(conflicts) >= 5 and all(c.get("governs") == "pipeline" for c in conflicts),
           f"{len(conflicts)} conflict(s) recorded")
    # Prose that counts the conflicts must not drift from the table it describes.
    counted = {5: "five", 6: "six", 7: "seven", 8: "eight"}.get(len(conflicts), "")
    record("prose citing the conflict count matches the table",
           bool(counted) and counted in figskill["reason"]
           and counted in (ROOT / "pipeline/stages/S11_figures.md").read_text(encoding="utf-8"),
           f"{len(conflicts)} conflicts -> '{counted}'")

    # The table quotes pipeline numbers. If a target moves and the table does not, it lies.
    tgt = _reg.load().targets
    quoted = {c["item"]: c["pipeline_says"] for c in conflicts}
    record("the conflict table still matches the live targets",
           str(int(tgt["column_width_mm_single"])) in quoted.get("single-column width", "")
           and str(int(tgt["column_width_mm_double"])) in quoted.get("double-column width", "")
           and str(tgt["figure_font_pt_min"]) in quoted.get("minimum font size", ""),
           f"single={tgt['column_width_mm_single']} double={tgt['column_width_mm_double']} "
           f"font_min={tgt['figure_font_pt_min']}")
    record("the table warns against running the skill's own audit on a pipeline figure",
           any("audit_medical_figure" in c.get("resolution", "") for c in conflicts),
           "it flags the pipeline's SubFigure panel titles as critical")

    fig_card = (ROOT / "pipeline/stages/S11_figures.md").read_text(encoding="utf-8")
    record("S11 tells the agent to activate the figure skill",
           "medical-sci-figure-skill" in fig_card and "figure_atlas.md" in fig_card,
           "card must name the skill and the atlas file to read")
    record("S11 forbids the skill from becoming the renderer",
           "never the renderer" in fig_card and "medfigure/recipes/" in fig_card,
           "a figure drawn outside style.py save() leaves no sidecar for QC")

    fig_std = (ROOT / "reference/figure-standards.md").read_text(encoding="utf-8")
    record("the retired global rule's machine facts survived in the engine",
           "Pillow is *not* installed" in fig_std
           and "stored dpi tag is not its resolution" in fig_std
           and "known false positive" in fig_std,
           "toolchain, effective-dpi and grey-detector facts kept out of trial-and-error")

    from rework import resolve_route
    from wfcore import registry
    route_pipe = registry.load()
    record("revision router chooses the earliest owning stage",
           resolve_route("analysis", "S24_package_human_review", route_pipe) == "S05_analysis" and
           resolve_route("references", "S19_human_review", route_pipe) == "S13_reflib" and
           resolve_route("discussion", "S19_human_review", route_pipe) == "S16_discussion" and
           resolve_route("manuscript-copyedit", "S19_human_review", route_pipe) ==
           "S19_human_review" and
           resolve_route("manuscript-copyedit", "S24_package_human_review", route_pipe) ==
           "S22_polish" and
           resolve_route("word-format-only", "S25_submission_audit", route_pipe) ==
           "S24_package_human_review",
           "analysis/reference/discussion/copyedit/Word-format routes")

    from wfcore.state import State
    owned_root = os.environ.get("MEDPAPER_SELFTEST_ROOT")
    if owned_root:
        route_root = Path(owned_root) / "rework_route"
        route_root.mkdir(parents=True, exist_ok=False)
    else:
        route_root = Path(tempfile.mkdtemp(prefix="medpaper_rework_route_"))
    route_project = route_root / "project"
    route_state = State(route_project, ".wf")
    route_state.create("medpaper", route_pipe.meta["version"], "S24_package_human_review")
    route_state.record_decision(
        "submission_package_user_confirmed", "OK",
        "The fixture user approved the package before requesting a substantive revision.")
    route_env = {**os.environ, "MEDPAPER_PROJECT": str(route_project),
                 "MEDPAPER_ROOT": str(ROOT), "PYTHONIOENCODING": "utf-8"}
    routed = subprocess.run(
        [sys.executable, str(ROOT / "tools/rework.py"), "start", "--kind", "discussion",
         "--why", "Revise the interpretation requested by the user in the Discussion section.",
         "--project", str(route_project)], capture_output=True, text=True, env=route_env,
        encoding="utf-8", errors="replace")
    routed_state = State(route_project, ".wf").load()
    record("revision router rewinds state and invalidates downstream approval",
           routed.returncode == 0 and routed_state.current == "S16_discussion" and
           routed_state.decision("submission_package_user_confirmed") is None,
           ((routed.stdout or "") + (routed.stderr or "")).strip()[:140])
    shutil.rmtree(route_root, ignore_errors=True)

    if owned_root:
        batch_root = Path(owned_root) / "revision_batch"
        batch_root.mkdir(parents=True, exist_ok=False)
    else:
        batch_root = Path(tempfile.mkdtemp(prefix="medpaper_revision_batch_"))
    batch_project = batch_root / "project"
    manuscript = batch_project / "07_manuscript"
    manuscript.mkdir(parents=True)
    (manuscript / "methods.md").write_text("# Methods\n\nOriginal methods source.\n", encoding="utf-8")
    (manuscript / "discussion.md").write_text("# Discussion\n\nOriginal discussion source.\n", encoding="utf-8")
    batch_state = State(batch_project, ".wf")
    batch_state.create("medpaper", route_pipe.meta["version"], "S24_package_human_review")
    batch_state.record_decision(
        "manuscript_human_reviewed", "NO_FURTHER_REVIEW",
        "The scientific manuscript was approved before journal-specific package revision.")
    batch_state.record_decision(
        "submission_package_user_confirmed", "OK",
        "The package was approved before the user submitted a new multi-item feedback batch.")
    plan_path = batch_root / "revision_plan.json"
    plan_path.write_text(json.dumps({
        "feedback_verbatim": "Please shorten Methods and clarify the causal interpretation in Discussion.",
        "interpretation": "Revise both canonical manuscript sources without changing unsupported facts or bypassing downstream validation.",
        "ambiguous_or_requires_user_decision": [],
        "items": [
            {
                "kind": "methods",
                "request": "Shorten the Methods while preserving every necessary reproducibility detail.",
                "affected_sources": ["07_manuscript/methods.md"],
                "acceptance_criteria": ["Main Methods is concise and complete", "No supported detail is lost"],
            },
            {
                "kind": "discussion",
                "request": "Clarify the causal interpretation and keep claims within the study design.",
                "affected_sources": ["07_manuscript/discussion.md"],
                "acceptance_criteria": ["Claims match the design limitations", "Interpretation is clear to a reader"],
            },
        ],
    }, indent=2), encoding="utf-8")
    batch_env = {**os.environ, "MEDPAPER_PROJECT": str(batch_project),
                 "MEDPAPER_ROOT": str(ROOT), "PYTHONIOENCODING": "utf-8"}
    opened = subprocess.run(
        [sys.executable, str(ROOT / "tools/rework.py"), "batch", "--rewind", "--plan", str(plan_path),
         "--project", str(batch_project)], capture_output=True, text=True, env=batch_env,
        encoding="utf-8", errors="replace")
    batch_state = State(batch_project, ".wf").load()
    round_path = batch_project / ".wf/revisions/R001.json"
    round_payload = json.loads(round_path.read_text(encoding="utf-8")) if round_path.exists() else {}
    record("explicit full-rewind fallback (batch --rewind) rewinds once to earliest owner",
           opened.returncode == 0 and batch_state.current == "S08_methods" and
           batch_state.data.get("active_revision_round") == "R001" and
           round_payload.get("earliest_stage") == "S08_methods" and
           len(round_payload.get("items", [])) == 2 and
           batch_state.decision("manuscript_human_reviewed") is not None and
           batch_state.decision("submission_package_user_confirmed") is None,
           ((opened.stdout or "") + (opened.stderr or "")).strip()[:180])
    status = subprocess.run(
        [sys.executable, str(ROOT / "tools/rework.py"), "status", "--project", str(batch_project)],
        capture_output=True, text=True, env=batch_env, encoding="utf-8", errors="replace")
    record("revision status restores atomic work after context compaction",
           status.returncode == 0 and "R001-01" in status.stdout and "R001-02" in status.stdout and
           "acceptance:" in status.stdout and "sources:" in status.stdout,
           status.stdout.strip()[:160])

    from wfcore.checks import Ctx, get, load_all
    load_all()
    revision_gate = get("revision_rounds_closed")
    review_stage = route_pipe.stage("S24_package_human_review")
    blocked = revision_gate(Ctx(route_pipe, batch_state, batch_project, review_stage, {}))
    record("review gate blocks an unfinished revision round", not blocked.ok, blocked.detail)

    (manuscript / "methods.md").write_text("# Methods\n\nConcise revised methods source.\n", encoding="utf-8")
    (manuscript / "discussion.md").write_text("# Discussion\n\nRevised interpretation within the design.\n", encoding="utf-8")
    batch_state = State(batch_project, ".wf").load()
    batch_state.data["current"] = "S24_package_human_review"
    batch_state.stage_info("S24_package_human_review")["status"] = "active"
    batch_state.save()
    mark_outputs = []
    for item_id, rel, summary in [
        ("R001-01", "07_manuscript/methods.md",
         "Condensed the canonical Methods source while retaining reproducibility details."),
        ("R001-02", "07_manuscript/discussion.md",
         "Clarified the canonical Discussion interpretation within the study design."),
    ]:
        mark_outputs.append(subprocess.run(
            [sys.executable, str(ROOT / "tools/rework.py"), "mark", "--item", item_id,
             "--changed-file", rel, "--validated-by", "fixture source validation passed",
             "--summary", summary, "--project", str(batch_project)], capture_output=True,
            text=True, env=batch_env, encoding="utf-8", errors="replace"))
    closed = subprocess.run(
        [sys.executable, str(ROOT / "tools/rework.py"), "close", "--summary",
         "All requested source revisions were completed and validated through the workflow.",
         "--project", str(batch_project)], capture_output=True, text=True, env=batch_env,
        encoding="utf-8", errors="replace")
    batch_state = State(batch_project, ".wf").load()
    closed_gate = revision_gate(Ctx(route_pipe, batch_state, batch_project, review_stage, {}))
    record("completed revision round closes only at its review node with evidence",
           all(proc.returncode == 0 for proc in mark_outputs) and closed.returncode == 0 and
           batch_state.data.get("active_revision_round") is None and closed_gate.ok,
           ((closed.stdout or "") + (closed.stderr or "") + " " + closed_gate.detail).strip()[:180])
    (manuscript / "methods.md").write_text("# Methods\n\nUntracked post-close drift.\n", encoding="utf-8")
    drift_gate = revision_gate(Ctx(route_pipe, batch_state, batch_project, review_stage, {}))
    record("closed-round hash detects untracked source drift", not drift_gate.ok, drift_gate.detail[:150])

    # A later completed round may legitimately supersede an older receipt for the same path.
    import hashlib
    newer = dict(round_payload)
    newer["round_id"] = "R002"
    newer["status"] = "complete"
    newer["completed_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    newer["items"] = [{
        "id": "R002-01", "kind": "methods", "status": "done",
        "validated_by": ["fixture second-round validation passed"],
        "changed_files": [{
            "path": "07_manuscript/methods.md",
            "sha256": hashlib.sha256((manuscript / "methods.md").read_bytes()).hexdigest(),
        }],
    }]
    (batch_project / ".wf/revisions/R002.json").write_text(
        json.dumps(newer, indent=2), encoding="utf-8")
    superseded_gate = revision_gate(Ctx(route_pipe, batch_state, batch_project, review_stage, {}))
    record("latest completed round supersedes an older hash for the same source",
           superseded_gate.ok, superseded_gate.detail)
    shutil.rmtree(batch_root, ignore_errors=True)


def run_fulltext_registration(proj: Path) -> None:
    """Legal external full text must be registered and hash-bound before deep reading."""
    from wfcore import registry
    from wfcore.checks import Ctx, get, load_all
    from wfcore.state import State

    section("full-text registration and deep-read gate")
    refs = proj / "06_refs"
    deep = refs / "deepread"
    deep.mkdir(parents=True, exist_ok=True)
    entries = [
        {"citekey": f"fixture{i}", "pmid": str(90000000 + i),
         "doi": f"10.0000/fixture.{i}", "title": f"Fixture paper {i}",
         "journal": "Fixture Journal", "year": "2025"}
        for i in range(1, 5)
    ]
    (refs / "library.json").write_text(
        json.dumps({"entries": entries}, indent=2), encoding="utf-8")

    env = {**os.environ, "MEDPAPER_PROJECT": str(proj), "MEDPAPER_ROOT": str(ROOT),
           "PYTHONIOENCODING": "utf-8"}
    tool = ROOT / "tools/pubmed/fulltext.py"
    selected = []
    registrations_ok = True
    for i, entry in enumerate(entries, 1):
        source = proj / "temp" / f"fixture{i}.pdf"
        # Most publisher PDFs carry their own DOI in the text, which is what lets a registered
        # file prove it is the requested paper. fixture4 deliberately does not, so the
        # indeterminate path and its explicit confirmation step are exercised too.
        body = bytes([64 + i]) * 1800
        if i < 4:
            # 1.7.1: identity needs the DOI AND the title (or first author + year) on page 1.
            body = f"{entry['title']}\ndoi:{entry['doi']}\n".encode() + body
        source.write_bytes(b"%PDF-1.4\n" + body)
        p = subprocess.run(
            [sys.executable, str(tool), "register", "--citekey", entry["citekey"],
             "--file", str(source), "--access", "oa",
             "--source-url", f"https://example.org/articles/{i}", "--route", "selftest"],
            capture_output=True, text=True, env=env, encoding="utf-8", errors="replace")
        registrations_ok = registrations_ok and p.returncode == 0
        notes = deep / f'{entry["citekey"]}.md'
        notes.write_text(
            f'# {entry["citekey"]}\n\n## Design and population\n' +
            ("Substantive fixture note describing population, methods, estimates, bias, "
             "comparability, limitations and implications for the Discussion. " * 5),
            encoding="utf-8")
        selected.append({
            "citekey": entry["citekey"], "pmid": entry["pmid"],
            "reason": "Needed to benchmark the primary finding against a comparable design.",
            "access": "oa", "fulltext": f'06_refs/fulltext/{entry["citekey"]}.pdf',
            "notes": f'06_refs/deepread/{entry["citekey"]}.md',
        })
    record("four legal local full texts register", registrations_ok)

    manifest_path = refs / "fulltext/retrieval_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    record("retrieval manifest records hashes and sources",
           len(manifest.get("retrievals", [])) == 4 and
           all(len(r.get("sha256", "")) == 64 and
               str(r.get("source_url", "")).startswith("https://")
               for r in manifest.get("retrievals", [])),
           f'{len(manifest.get("retrievals", []))} record(s)')

    (deep / "deepread_index.json").write_text(
        json.dumps({"selected": selected}, indent=2), encoding="utf-8")
    load_all()
    pipe = registry.load()
    state = State(proj, ".wf").load()
    gate = get("deepread_complete")

    def check_deepread():
        return gate(Ctx(pipeline=pipe, state=state, project=proj,
                        stage=pipe.stage("S15_deepread"),
                        spec={"check": "deepread_complete"}))

    # A registered file is not trusted just because a person handed it over. Three prove
    # themselves from their own DOI; the fourth cannot, and must block until someone opens it.
    ident = {r["citekey"]: r.get("identity") for r in manifest.get("retrievals", [])}
    record("a registered PDF carrying its own DOI proves its identity",
           all(ident.get(f"fixture{i}") == "match" for i in (1, 2, 3)), str(ident))
    record("a registered PDF that cannot identify itself is indeterminate, not accepted",
           ident.get("fixture4") == "indeterminate", str(ident.get("fixture4")))

    outcome = check_deepread()
    record("deep-read gate blocks while one file is unproven",
           not outcome.ok and "fixture4" in outcome.detail, outcome.detail[:110])

    p = subprocess.run(
        [sys.executable, str(tool), "verify", "--citekey", "fixture4",
         "--confirm-identity", "Totally unrelated paper about something else"],
        capture_output=True, text=True, env=env, encoding="utf-8", errors="replace")
    record("confirming with a title that does not match the entry is refused",
           p.returncode != 0 and "does not match" in ((p.stdout or "") + (p.stderr or "")),
           ((p.stdout or "") + (p.stderr or "")).strip()[-90:])

    p = subprocess.run(
        [sys.executable, str(tool), "verify", "--citekey", "fixture4",
         "--confirm-identity", "Fixture paper 4"],
        capture_output=True, text=True, env=env, encoding="utf-8", errors="replace")
    record("reading the title off the file discharges an indeterminate identity",
           p.returncode == 0, ((p.stdout or "") + (p.stderr or "")).strip()[-90:])

    outcome = check_deepread()
    record("registered local full texts satisfy deep-read gate", outcome.ok, outcome.detail)

    changed = refs / "fulltext/fixture1.pdf"
    changed.write_bytes(changed.read_bytes() + b"changed")
    outcome = check_deepread()
    record("post-registration file mutation is rejected", not outcome.ok, outcome.detail[:100])

    replacement = proj / "temp/replacement.pdf"
    replacement.write_bytes(b"%PDF-1.4\n" + b"Z" * 1800)
    p = subprocess.run(
        [sys.executable, str(tool), "register", "--citekey", "fixture2",
         "--file", str(replacement), "--access", "oa",
         "--source-url", "https://example.org/replacement"],
        capture_output=True, text=True, env=env, encoding="utf-8", errors="replace")
    record("different existing full text is not overwritten implicitly",
           p.returncode != 0 and "already exists" in ((p.stdout or "") + (p.stderr or "")))

    shutil.rmtree(refs, ignore_errors=True)
    for source in (proj / "temp").glob("fixture*.pdf"):
        source.unlink(missing_ok=True)
    replacement.unlink(missing_ok=True)


def run_journal_eligibility(proj: Path) -> None:
    """The journal gate must reject unverified indexing, quartile, and integrity."""
    from wfcore import registry
    from wfcore.checks import Ctx, get, load_all
    from wfcore.state import State

    section("journal eligibility gate")
    target_dir = proj / "08_submission"
    (target_dir / "cache").mkdir(parents=True, exist_ok=True)
    guidelines_url = "https://journal.example/authors"
    today = date.today().isoformat()
    meta = {
        "journal": "Fixture Clinical Journal", "issn": "1234-5678",
        "publisher": "Fixture Publisher", "scie_indexed": True,
        "scie_source_url": "https://clarivate.example/master-journal-list",
        "scie_verified_at": today, "jcr_quartile": "Q3",
        "jcr_source": "Journal Citation Reports", "jcr_verified_at": today,
        "integrity_status": "clear", "integrity_checked_at": today,
        "integrity_sources": ["https://clarivate.example/journal",
                              "https://publisher.example/journal"],
        "guidelines_url": guidelines_url, "guidelines_fetched_at": today,
        "abbreviation_placement": "central",
        "abbreviation_rule_source": f"Journal is silent; central policy. {guidelines_url}",
        "chosen_by_user": True,
    }
    target = target_dir / "target_journal.json"
    target.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    (target_dir / "guidelines_extract.md").write_text(
        f"# Guidelines\n\nSource: {guidelines_url}\n\n"
        "## Word limits\n3500\n## Reference style\nVancouver\n"
        "## Figure requirements\nTIFF\n## Table requirements\nEditable\n"
        "## Required statements\nEthics and funding\n## Submission items\nDOCX and figures\n",
        encoding="utf-8")
    (target_dir / "cache/guidelines.html").write_text("<html>fixture</html>", encoding="utf-8")

    load_all()
    pipe = registry.load()
    state = State(proj, ".wf").load()
    gate = get("guidelines_sourced")

    def check_journal():
        return gate(Ctx(pipeline=pipe, state=state, project=proj,
                        stage=pipe.stage("S20_journal"),
                        spec={"check": "guidelines_sourced"}))

    outcome = check_journal()
    record("eligible sourced journal passes", outcome.ok, outcome.detail)
    meta["scie_verified_at"] = (date.today() - timedelta(days=91)).isoformat()
    target.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    outcome = check_journal()
    record("stale SCIE verification is rejected", not outcome.ok, outcome.detail[:100])
    meta["scie_verified_at"] = today
    meta["integrity_status"] = "warning"
    target.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    outcome = check_journal()
    record("integrity warning is rejected", not outcome.ok, outcome.detail[:100])
    shutil.rmtree(target_dir, ignore_errors=True)


def run_manuscript_docx(proj: Path) -> None:
    """Canonical assembly and Word normalization must be deterministic and auditable."""
    from wfcore import registry
    from wfcore.checks import Ctx, get, load_all
    from wfcore.state import State

    section("canonical manuscript and Word package")
    manuscript = proj / "07_manuscript"
    submission = proj / "08_submission"
    bundle = submission / "bundle"
    bundle.mkdir(parents=True, exist_ok=True)
    (manuscript / "title.md").write_text(
        "# Exposure and Clinical Outcome in a Multicentre Cohort Study\n", encoding="utf-8")
    (manuscript / "abstract.md").write_text(
        "# Abstract\n\n## Background\nWe evaluated the association.\n\n"
        "## Methods\nWe analysed 1284 participants.\n\n## Results\nExposure was associated "
        "with outcome (HR 1.87, 95% CI 1.34 to 2.61).\n\n## Conclusions\nThe exposure "
        "was associated with outcome.\n", encoding="utf-8")
    (manuscript / "keywords.md").write_text(
        "Keywords: cohort studies, exposure, prognosis, survival analysis\n", encoding="utf-8")
    (manuscript / "introduction.md").write_text(
        "# Introduction\n\nThe clinical association requires evaluation [@fixture2025].\n",
        encoding="utf-8")
    (manuscript / "methods.md").write_text(
        "# Methods\n\n## Study design and participants\nWe studied 1284 participants.\n\n"
        "## Statistical analysis\nThe primary model estimated an HR with a 95% CI.\n",
        encoding="utf-8")
    (manuscript / "discussion.md").write_text(
        "# Discussion\n\nExposure was associated with outcome (HR 1.87, 95% CI 1.34 to "
        "2.61) (Figure 1).\n", encoding="utf-8")
    (manuscript / "supplementary_methods.md").write_text(
        "# Supplementary Methods\n\nExtended variable coding details are provided here.  \n"
        "Definitions follow without a manual Word line-break control.\n",
        encoding="utf-8")
    env = {**os.environ, "MEDPAPER_PROJECT": str(proj), "MEDPAPER_ROOT": str(ROOT),
           "PYTHONIOENCODING": "utf-8"}
    refs = proj / "06_refs"
    refs.mkdir(parents=True, exist_ok=True)
    bib = refs / "refs.bib"
    bib.write_text("@article{fixture2025, title={Fixture cohort report}, "
                   "author={Author, Alice}, journal={Fixture Journal}, year={2025}}\n",
                   encoding="utf-8")
    (refs / "refs.ris").write_text(
        "TY  - JOUR\nID  - fixture2025\nTI  - Fixture cohort report\nPY  - 2025\nER  - \n",
        encoding="utf-8")
    assembler = ROOT / "tools/manuscript/assemble.py"
    proc = subprocess.run([sys.executable, str(assembler)], capture_output=True, text=True,
                          env=env, encoding="utf-8", errors="replace")
    record("full manuscript assembles", proc.returncode == 0,
           ((proc.stdout or "") + (proc.stderr or "")).strip()[:100])

    load_all()
    pipe = registry.load()
    state = State(proj, ".wf").load()

    def gate(check_name: str, stage: str, **spec):
        return get(check_name)(Ctx(pipeline=pipe, state=state, project=proj,
                                   stage=pipe.stage(stage),
                                   spec={"check": check_name, **spec}))

    # S19 must produce a current, versioned package that can be handed to a third party.
    review_report = manuscript / "independent_publishability_review.md"
    review_report.write_text(
        "# Independent publishability review\n\n## Verdict\nREADY.\n\n"
        "## Critical barriers\nNone.\n\n## Scientific validity\nAcceptable.\n\n"
        "## Reporting completeness\nComplete.\n\n"
        "## Tables and supplementary material\nConsistent.\n\n"
        "## Journal suitability\nA realistic SCIE journal is plausible.\n\n"
        "## Required revisions\nNone before user review.\n\n"
        "## Post-revision outlook\nProceed after explicit user review.\n",
        encoding="utf-8",
    )
    prior_state = json.loads(json.dumps(state.data))
    state.data["current"] = "S19_human_review"
    state.stage_info("S19_human_review")["status"] = "active"
    state.save()
    review_tool = ROOT / "tools/manuscript/review_package.py"
    first_review_zip = subprocess.run(
        [sys.executable, str(review_tool), "build", "--project", str(proj)],
        capture_output=True, text=True, env=env, encoding="utf-8", errors="replace")
    review_manifest_path = manuscript / "review_packages/latest_review_package.json"
    review_manifest = (json.loads(review_manifest_path.read_text(encoding="utf-8"))
                       if review_manifest_path.is_file() else {})
    review_archive = proj / review_manifest.get("archive_path", "missing")
    members = set()
    if review_archive.is_file():
        with zipfile.ZipFile(review_archive) as zf:
            members = set(zf.namelist())
    outcome = gate("manuscript_review_package_current", "S19_human_review")
    record("S19 builds a verified third-party review ZIP with exact review materials",
           first_review_zip.returncode == 0 and outcome.ok and
           review_manifest.get("package_revision") == 1 and
           {"07_manuscript/full_manuscript.md",
            "07_manuscript/supplementary_methods.md",
            "07_manuscript/independent_publishability_review.md",
            "06_refs/refs.bib", "06_refs/refs.ris",
            "REVIEW_README.txt", "review_manifest.json"}.issubset(members) and
           any(name.startswith("04_tables/main/") for name in members) and
           any(name.startswith("04_tables/supplementary/") for name in members) and
           any(name.startswith("05_figures/out/") and name.endswith(".png") for name in members) and
           not any(name.startswith(("02_data/", "03_analysis/", "06_refs/fulltext/"))
                   for name in members),
           ((first_review_zip.stdout or "") + (first_review_zip.stderr or "") +
            outcome.detail).strip()[:180])
    unchanged_review_zip = subprocess.run(
        [sys.executable, str(review_tool), "build", "--project", str(proj)],
        capture_output=True, text=True, env=env, encoding="utf-8", errors="replace")
    unchanged_manifest = json.loads(review_manifest_path.read_text(encoding="utf-8"))
    record("unchanged S19 sources reuse the verified ZIP without duplicate versions",
           unchanged_review_zip.returncode == 0 and "reused unchanged" in unchanged_review_zip.stdout and
           unchanged_manifest.get("archive_path") == review_manifest.get("archive_path") and
           unchanged_manifest.get("package_revision") == 1,
           unchanged_review_zip.stdout.strip()[:140])

    state.record_decision(
        "manuscript_human_reviewed", "YES",
        "The fixture intentionally records an old ambiguous approval value for rejection.")
    wrong_approval = gate("s19_review_release_explicit", "S19_human_review")
    state.record_decision(
        "manuscript_human_reviewed", "NO_FURTHER_REVIEW",
        "The user explicitly stated that no further scientific review was needed after ZIP "
        f"v001 package {review_manifest['package_id'][:12]}.")
    explicit_approval = gate("s19_review_release_explicit", "S19_human_review")
    record("S19 rejects generic approval and accepts only explicit no-further-review state",
           not wrong_approval.ok and explicit_approval.ok,
           f"old={wrong_approval.detail}; explicit={explicit_approval.detail}")

    review_report.write_text(
        review_report.read_text(encoding="utf-8") +
        "\nThe reviewer clarified one editorial point for the revised version.\n",
        encoding="utf-8",
    )
    stale_review = gate("manuscript_review_package_current", "S19_human_review")
    rebuilt_review_zip = subprocess.run(
        [sys.executable, str(review_tool), "build", "--project", str(proj)],
        capture_output=True, text=True, env=env, encoding="utf-8", errors="replace")
    revised_manifest = json.loads(review_manifest_path.read_text(encoding="utf-8"))
    revised_review = gate("manuscript_review_package_current", "S19_human_review")
    stale_approval = gate("s19_review_release_explicit", "S19_human_review")
    record("changed S19 review material invalidates v001 and creates verified v002",
           not stale_review.ok and rebuilt_review_zip.returncode == 0 and revised_review.ok and
           not stale_approval.ok and
           revised_manifest.get("package_revision") == 2 and
           revised_manifest.get("archive_path") != review_manifest.get("archive_path") and
           review_archive.is_file() and (proj / revised_manifest["archive_path"]).is_file(),
           ((rebuilt_review_zip.stdout or "") + revised_review.detail).strip()[:180])
    state.data = prior_state
    state.save()

    outcome = gate("abbreviations_centralized", "S21_authors")
    record("short display abbreviation lists may remain local", outcome.ok, outcome.detail)
    captions = proj / "04_tables/table_captions.md"
    captions_good = captions.read_text(encoding="utf-8")
    captions.write_text(captions_good +
                        "\nAbbreviations: BMI, body mass index; eGFR, estimated glomerular "
                        "filtration rate; HbA1c, glycated haemoglobin; SBP, systolic blood pressure; "
                        "DBP, diastolic blood pressure; CKD, chronic kidney disease.\n",
                        encoding="utf-8")
    outcome = gate("abbreviations_centralized", "S21_authors")
    record("crowded display abbreviations require centralization", not outcome.ok,
           outcome.detail[:100])
    captions.write_text(captions_good, encoding="utf-8")

    # A realistic centralized glossary must pass without redefining panel/table labels.
    scoped = proj / "temp/abbreviations_case"
    (scoped / "05_figures").mkdir(parents=True)
    (scoped / "04_tables").mkdir(parents=True)
    (scoped / "07_manuscript").mkdir(parents=True)
    (scoped / "05_figures/legends.md").write_text(
        "# Figure legends\n\n## Figure 1.\nModels for eGFR and HbA1c. "
        "Abbreviations are listed in Declarations and Statements.\n", encoding="utf-8")
    (scoped / "04_tables/table_captions.md").write_text(
        "# Table captions\n\n## Table S1.\nClinical characteristics. "
        "Abbreviations are listed in Declarations and Statements.\n", encoding="utf-8")
    central = ("# Declarations and Statements\n\n## Abbreviations\n\n"
               "eGFR, estimated glomerular filtration rate; HbA1c, glycated haemoglobin.\n")
    (scoped / "07_manuscript/statements.md").write_text(central, encoding="utf-8")
    scoped_full = scoped / "07_manuscript/full_manuscript.md"
    scoped_full.write_text("# Discussion\n\nClinical interpretation.\n\n" + central +
                           "\n# References\n", encoding="utf-8")
    ctx = Ctx(pipeline=pipe, state=state, project=scoped, stage=pipe.stage("S17_assemble"),
              spec={"check": "abbreviations_centralized"})
    outcome = get("abbreviations_centralized")(ctx)
    record("central glossary accepts mixed-case terms and table labels", outcome.ok, outcome.detail)
    scoped_full.write_text("# Discussion\n\nClinical interpretation.\n", encoding="utf-8")
    outcome = get("abbreviations_centralized")(ctx)
    record("central glossary cannot be omitted from full manuscript", not outcome.ok,
           outcome.detail[:100])
    shutil.rmtree(scoped)

    outcome = gate("manuscript_structure", "S17_assemble")
    record("canonical order and keywords pass", outcome.ok, outcome.detail)
    outcome = gate("assembly_matches_sources", "S17_assemble")
    record("canonical manuscript exactly matches source sections", outcome.ok, outcome.detail)
    full = manuscript / "full_manuscript.md"
    good = full.read_text(encoding="utf-8")
    full.write_text(good.replace("cohort studies, exposure", "cohort studies; exposure"),
                    encoding="utf-8")
    outcome = gate("manuscript_structure", "S17_assemble")
    record("malformed keyword separators are rejected", not outcome.ok, outcome.detail[:100])
    full.write_text(good, encoding="utf-8")

    # S17 can assemble abbreviation definitions before author/admin collection.
    statement_source = manuscript / "statements.md"
    statement_source.write_text(central, encoding="utf-8")
    assembled = subprocess.run([sys.executable, str(assembler)], capture_output=True, text=True,
                               env=env, encoding="utf-8", errors="replace")
    with_glossary = full.read_text(encoding="utf-8")
    record("assembly includes glossary before References without author intake",
           assembled.returncode == 0 and
           with_glossary.index("# Discussion") < with_glossary.index("# Declarations and Statements") <
           with_glossary.index("# References"))
    statement_source.unlink()
    full.write_text(good, encoding="utf-8")
    full.write_text(good.replace("clinical association", "clinical relationship", 1),
                    encoding="utf-8")
    outcome = gate("assembly_matches_sources", "S17_assemble")
    record("source-section omission or divergence is rejected", not outcome.ok,
           outcome.detail[:100])
    outcome = gate("assembly_matches_sources", "S19_human_review")
    record("S19 rejects a detached full-manuscript edit", not outcome.ok,
           outcome.detail[:100])
    full.write_text("# Exposure and Clinical Outcome in a Multicentre Cohort Study\n\n" +
                    good.split("\n\n", 1)[1].split("# Figure legends", 1)[0] +
                    "# Figure legends\n\n", encoding="utf-8")
    outcome = gate("manuscript_structure", "S17_assemble")
    record("empty planned figure legend is rejected", not outcome.ok, outcome.detail[:100])
    full.write_text(good, encoding="utf-8")

    # A title-page count is optional, but when present it must be derived from the
    # distinct citekeys used by the canonical manuscript rather than library size.
    title_page = manuscript / "title_page.md"
    title_page.write_text(
        "# Exposure and Clinical Outcome in a Multicentre Cohort Study\n\n"
        "Fixture Author\n\nNumber of references: 50\n", encoding="utf-8")
    outcome = gate("title_page_reference_count", "S21_authors")
    record("incorrect title-page reference count is rejected", not outcome.ok,
           outcome.detail[:110])
    counter = ROOT / "tools/manuscript/reference_count.py"
    synced = subprocess.run(
        [sys.executable, str(counter), "sync", "--project", str(proj)],
        capture_output=True, text=True, env=env, encoding="utf-8", errors="replace")
    record("actual citation count synchronizes title page",
           synced.returncode == 0 and "Number of references: 1" in
           title_page.read_text(encoding="utf-8"),
           ((synced.stdout or "") + (synced.stderr or "")).strip()[:110])
    outcome = gate("title_page_reference_count", "S21_authors")
    record("title-page reference count gate passes after synchronization", outcome.ok,
           outcome.detail)

    title_page.write_text(
        "# Exposure and Clinical Outcome in a Multicentre Cohort Study\n\nFixture Author\n",
        encoding="utf-8")
    outcome = gate("title_page_reference_count", "S21_authors")
    record("reference count remains optional when journal does not request it", outcome.ok,
           outcome.detail)
    added = subprocess.run(
        [sys.executable, str(counter), "sync", "--add", "--project", str(proj)],
        capture_output=True, text=True, env=env, encoding="utf-8", errors="replace")
    record("reference count field is added only on explicit request",
           added.returncode == 0 and title_page.read_text(encoding="utf-8").count(
               "Number of references: 1") == 1,
           ((added.stdout or "") + (added.stderr or "")).strip()[:110])

    style = {
        "font_family": "Times New Roman", "body_font_pt": 12, "title_font_pt": 14,
        "section_heading_font_pt": 12, "subsection_heading_font_pt": 12,
        "line_spacing": 2.0, "paragraph_spacing_after_pt": 0, "margins_in": 1.0,
        "paper_size": "A4", "all_text_black": True, "external_hyperlinks": False,
        "source": "Fixture journal is silent; documented medical-manuscript fallback.",
        "fallbacks": ["font_family", "body_font_pt", "title_font_pt",
                      "section_heading_font_pt", "subsection_heading_font_pt",
                      "line_spacing", "paragraph_spacing_after_pt", "margins_in",
                      "paper_size"],
    }
    style_path = submission / "docx_style.json"
    style_path.write_text(json.dumps(style, indent=2), encoding="utf-8")
    outcome = gate("docx_style_config", "S20_journal")
    record("journal Word style configuration passes", outcome.ok, outcome.detail)
    bad_style = dict(style)
    bad_style["font_family"] = "Arial"
    style_path.write_text(json.dumps(bad_style, indent=2), encoding="utf-8")
    outcome = gate("docx_style_config", "S20_journal")
    record("journal-silent non-Times font is rejected", not outcome.ok, outcome.detail[:100])
    style_path.write_text(json.dumps(style, indent=2), encoding="utf-8")

    cover = submission / "cover_letter.md"
    cover.write_text("# Cover letter\n\nDear Editor,\n\nPlease consider this cohort study.\n",
                     encoding="utf-8")
    builder = ROOT / "tools/manuscript/build_docx.py"

    def build(kind: str, source: Path, name: str) -> bool:
        command = [sys.executable, str(builder), "build", "--kind", kind,
                   "--input", str(source), "--output", str(bundle / name),
                   "--style-config", str(style_path)]
        if kind == "manuscript":
            command += ["--bibliography", str(bib)]
        proc_ = subprocess.run(
            command, capture_output=True, text=True,
            env=env, encoding="utf-8", errors="replace")
        record(f"{kind} DOCX builds and self-audits", proc_.returncode == 0,
               ((proc_.stdout or "") + (proc_.stderr or "")).strip()[:120])
        return proc_.returncode == 0

    builds_ok = all([
        build("manuscript", full, "manuscript.docx"),
        build("title_page", manuscript / "title_page.md", "title_page.docx"),
        build("cover_letter", cover, "cover_letter.docx"),
        build("supplementary", manuscript / "supplementary_methods.md", "supplementary_methods.docx"),
    ])
    receipt_dir = submission / "build_receipts"
    receipts = sorted(receipt_dir.glob("*.json")) if receipt_dir.is_dir() else []
    record("every built DOCX has a deterministic source/output receipt",
           builds_ok and len(receipts) == 4
           and all(json.loads(p.read_text(encoding="utf-8")).get("output_sha256")
                   for p in receipts),
           f"{len(receipts)} receipt(s)")
    word_xmls = []
    for name in ("manuscript.docx", "title_page.docx", "cover_letter.docx",
                 "supplementary_methods.docx"):
        with zipfile.ZipFile(bundle / name) as zf:
            word_xmls.extend(zf.read(item) for item in zf.namelist()
                             if item.startswith("word/") and item.endswith(".xml"))
    forbidden_controls = (b"<w:outlineLvl", b"<w:keepNext", b"<w:keepLines",
                          b"<w:pageBreakBefore", b"<w:pBdr")
    record("all Word XML parts remove black-square and folding controls",
           builds_ok and not any(tag in blob for tag in forbidden_controls for blob in word_xmls))
    with zipfile.ZipFile(bundle / "manuscript.docx") as zf:
        manuscript_xml = zf.read("word/document.xml")
    record("visible section headings are flattened to SectionHeading",
           b'w:val="SectionHeading"' in manuscript_xml and
           b'w:val="Heading1"' not in manuscript_xml and b'w:val="Heading2"' not in manuscript_xml)
    manuscript_text = "\n".join(
        paragraph.text for paragraph in __import__("docx").Document(bundle / "manuscript.docx").paragraphs)
    record("Figure legends section title appears exactly once in Word",
           sum(line.strip().casefold() == "figure legends"
               for line in manuscript_text.splitlines()) == 1)

    supplement_source = manuscript / "supplementary_methods.md"
    supplement_good = supplement_source.read_text(encoding="utf-8")
    supplement_source.write_text(
        "# Supplementary Methods\n\n| Variable | Definition |\n|---|---|\n| A | B |\n\n---\n",
        encoding="utf-8")
    outcome = gate("supplementary_methods_clean", "S08_methods")
    record("supplementary Methods rejects embedded tables and Markdown rules",
           not outcome.ok, outcome.detail[:120])
    invalid_supplement = bundle / "invalid_supplement.docx"
    invalid_proc = subprocess.run(
        [sys.executable, str(builder), "build", "--kind", "supplementary",
         "--input", str(supplement_source), "--output", str(invalid_supplement),
         "--style-config", str(style_path)], capture_output=True, text=True, env=env,
        encoding="utf-8", errors="replace")
    record("Word builder refuses a supplementary-Methods table bypass",
           invalid_proc.returncode != 0 and not invalid_supplement.exists(),
           ((invalid_proc.stdout or "") + (invalid_proc.stderr or "")).strip()[:120])
    supplement_source.write_text(supplement_good, encoding="utf-8")

    duplicate_source = submission / "duplicate_legend_source.md"
    duplicate_source.write_text(full.read_text(encoding="utf-8") +
                                "\n# Figure legends\n", encoding="utf-8")
    duplicate_output = bundle / "duplicate_legend.docx"
    duplicate_proc = subprocess.run(
        [sys.executable, str(builder), "build", "--kind", "manuscript",
         "--input", str(duplicate_source), "--output", str(duplicate_output),
         "--style-config", str(style_path), "--bibliography", str(bib)],
        capture_output=True, text=True, env=env, encoding="utf-8", errors="replace")
    record("Word builder refuses duplicate Figure legends titles",
           duplicate_proc.returncode != 0 and not duplicate_output.exists(),
           ((duplicate_proc.stdout or "") + (duplicate_proc.stderr or "")).strip()[:120])
    duplicate_source.unlink(missing_ok=True)

    with zipfile.ZipFile(bundle / "supplementary_methods.docx") as zf:
        supplement_xml = zf.read("word/document.xml")
    record("manual Word line-break controls are removed",
           b"<w:br" not in supplement_xml and b"<w:cr" not in supplement_xml)
    from docx import Document
    from docx.enum.text import WD_BREAK
    from manuscript.build_docx import audit_docx, normalize_docx
    tampered_supplement = bundle / "tampered_supplement.docx"
    shutil.copy2(bundle / "supplementary_methods.docx", tampered_supplement)
    tampered_doc = Document(tampered_supplement)
    tampered_doc.add_table(rows=2, cols=2)
    tampered_doc.save(tampered_supplement)
    record("Word audit rejects an embedded supplementary-Methods table",
           any("supplementary Methods contains a table" in issue for issue in
               audit_docx(tampered_supplement, style, "supplementary")))
    tampered_supplement.unlink()
    raw_breaks = bundle / "line_break_fixture.docx"
    raw_doc = Document()
    paragraph = raw_doc.add_paragraph("First address line")
    paragraph.add_run().add_break()
    paragraph.add_run("Second address line").italic = True
    paragraph.add_run().add_break(WD_BREAK.PAGE)
    paragraph.add_run("After page break")
    cell = raw_doc.add_table(rows=1, cols=1).cell(0, 0)
    cell.text = "First cell line\nSecond cell line"
    raw_doc.save(raw_breaks)
    normalize_docx(raw_breaks, style, "cover_letter")
    normalized = Document(raw_breaks)
    record("line-break conversion preserves paragraphs, italics and table lines",
           normalized.paragraphs[0].text == "First address line" and
           normalized.paragraphs[1].text.startswith("Second address line") and
           any(run.italic for run in normalized.paragraphs[1].runs) and
           [p.text for p in normalized.tables[0].cell(0, 0).paragraphs] ==
           ["First cell line", "Second cell line"])
    with zipfile.ZipFile(raw_breaks) as zf:
        record("explicit page breaks survive manual-break cleanup",
               b'w:type="page"' in zf.read("word/document.xml"))
    raw_breaks.unlink()

    arrow_source = submission / "arrow_source.md"
    arrow_source.write_text("# Cover letter\n\nA downward marker \u2193 must not survive.\n",
                            encoding="utf-8")
    arrow_output = bundle / "arrow_output.docx"
    arrow_proc = subprocess.run(
        [sys.executable, str(builder), "build", "--kind", "cover_letter",
         "--input", str(arrow_source), "--output", str(arrow_output),
         "--style-config", str(style_path)], capture_output=True, text=True, env=env,
        encoding="utf-8", errors="replace")
    record("Word builder rejects a literal down arrow",
           arrow_proc.returncode != 0 and not arrow_output.exists(),
           ((arrow_proc.stdout or "") + (arrow_proc.stderr or "")).strip()[:100])
    arrow_source.unlink(missing_ok=True)
    (bundle / "SUBMISSION_CHECKLIST.md").write_text("# Submission checklist\n\n- Complete\n",
                                                     encoding="utf-8")
    shutil.copy2(proj / "05_figures/out/Figure1.tiff", bundle / "Figure1.tiff")
    shutil.copy2(proj / "04_tables/main/Table1.xlsx", bundle / "Table1.xlsx")
    items = [
        ("manuscript", "manuscript.docx"), ("title_page", "title_page.docx"),
        ("cover_letter", "cover_letter.docx"),
        ("supplementary", "supplementary_methods.docx"),
        ("figures", "Figure1.tiff"), ("tables", "Table1.xlsx"),
        ("checklist", "SUBMISSION_CHECKLIST.md"),
    ]
    manifest = {"built_at": "2026-09-04", "journal": "Fixture Clinical Journal",
                "items": [{"role": role, "file": f"08_submission/bundle/{name}",
                           "required_by": "guidelines_extract.md > Submission items"}
                          for role, name in items]}
    manifest_path = bundle / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    outcome = gate("docx_bundle_ready", "S23_package")
    record("Word bundle gate accepts normalized DOCX files", builds_ok and outcome.ok,
           outcome.detail)
    outcome = gate("title_page_reference_count", "S23_package")
    record("Word title-page reference count matches canonical manuscript", outcome.ok,
           outcome.detail)
    title_page_docx = bundle / "title_page.docx"
    approved_title_page = title_page_docx.read_bytes()
    altered_title = Document(title_page_docx)
    for paragraph in altered_title.paragraphs:
        if "Number of references:" in paragraph.text:
            paragraph.text = "Number of references: 50"
    altered_title.save(title_page_docx)
    outcome = gate("title_page_reference_count", "S23_package")
    record("manually altered Word reference count is rejected", not outcome.ok,
           outcome.detail[:110])
    title_page_docx.write_bytes(approved_title_page)

    from wfcore.packagecontent import build_receipt_path, write_baseline
    title_receipt = build_receipt_path(proj, title_page_docx)
    held_receipt = title_receipt.with_suffix(".held")
    title_receipt.replace(held_receipt)
    try:
        write_baseline(proj)
        missing_receipt_rejected = False
    except ValueError as exc:
        missing_receipt_rejected = "build receipt missing" in str(exc)
    finally:
        held_receipt.replace(title_receipt)
    record("S23 baseline refuses a DOCX with no deterministic build receipt",
           missing_receipt_rejected)
    baseline_path = write_baseline(proj)
    outcome = gate("package_content_matches_baseline", "S23_package")
    record("S23 captures a valid submission visible-text baseline",
           baseline_path.is_file() and outcome.ok, outcome.detail)
    title_receipt = build_receipt_path(proj, title_page_docx)
    approved_receipt = title_receipt.read_bytes()
    title_receipt.write_text("{}", encoding="utf-8")
    outcome = gate("package_content_matches_baseline", "S24_package_human_review")
    record("tampering with a deterministic DOCX build receipt is rejected",
           not outcome.ok and "build receipt changed" in outcome.detail, outcome.detail[:120])
    title_receipt.write_bytes(approved_receipt)
    baseline_cli = ROOT / "tools/package_content.py"
    blocked_capture = subprocess.run(
        [sys.executable, str(baseline_cli), "capture", "--replace", "--project", str(proj)],
        capture_output=True, text=True, env=env, encoding="utf-8", errors="replace")
    record("content baseline cannot be recaptured outside S23",
           blocked_capture.returncode != 0 and "allowed only at S23_package" in
           (blocked_capture.stderr or ""), (blocked_capture.stderr or "").strip()[:110])

    format_only_doc = Document(title_page_docx)
    format_only_doc.paragraphs[1].runs[0].bold = True
    format_only_doc.save(title_page_docx)
    outcome = gate("package_content_matches_baseline", "S24_package_human_review")
    record("Word formatting-only edits preserve the content baseline",
           outcome.ok and "formatting-only" in outcome.detail, outcome.detail)
    title_page_docx.write_bytes(approved_title_page)

    text_changed_doc = Document(title_page_docx)
    text_changed_doc.paragraphs[1].text = "Different Author"
    text_changed_doc.save(title_page_docx)
    outcome = gate("package_content_matches_baseline", "S24_package_human_review")
    record("direct Word text edits are rejected", not outcome.ok, outcome.detail[:110])
    title_page_docx.write_bytes(approved_title_page)

    approved_cover_source = cover.read_text(encoding="utf-8")
    cover.write_text(approved_cover_source + "\nA detached source edit.\n", encoding="utf-8")
    outcome = gate("package_content_matches_baseline", "S24_package_human_review")
    record("source edits without an S23 rebuild are rejected", not outcome.ok,
           outcome.detail[:110])
    cover.write_text(approved_cover_source, encoding="utf-8")
    outcome = gate("package_content_matches_baseline", "S24_package_human_review")
    record("restoring Word text and sources restores the content baseline", outcome.ok,
           outcome.detail)

    proc = subprocess.run(
        [sys.executable, str(builder), "audit", "--manifest", str(manifest_path),
         "--style-config", str(style_path)], capture_output=True, text=True, env=env,
        encoding="utf-8", errors="replace")
    record("standalone Word manifest audit passes", proc.returncode == 0,
           ((proc.stdout or "") + (proc.stderr or "")).strip()[:120])

    # Freeze the exact package the user approved and reject any post-confirmation mutation.
    today = date.today().isoformat()
    guidelines_url = "https://journal.example/authors"
    (submission / "target_journal.json").write_text(json.dumps({
        "journal": "Fixture Clinical Journal", "guidelines_url": guidelines_url,
        "guidelines_fetched_at": today,
    }, indent=2), encoding="utf-8")
    (submission / "guidelines_extract.md").write_text(
        f"# Guidelines\n\nSource: {guidelines_url}\n\n## Submission items\nAll fixture files.\n",
        encoding="utf-8")
    (submission / "submission_qc.md").write_text(
        "# Submission QC\n\n## Rendered files inspected\nAll.\n", encoding="utf-8")
    (submission / "cache").mkdir(exist_ok=True)
    (submission / "cache/guidelines.html").write_text("<html>fixture</html>", encoding="utf-8")
    freezer = ROOT / "tools/package_review.py"
    frozen = subprocess.run(
        [sys.executable, str(freezer), "freeze", "--project", str(proj)],
        capture_output=True, text=True, env=env, encoding="utf-8", errors="replace")
    outcome = gate("bundle_matches_freeze", "S24_package_human_review")
    record("user-approved submission package freezes and verifies",
           frozen.returncode == 0 and outcome.ok,
           ((frozen.stdout or "") + (frozen.stderr or "") + outcome.detail).strip()[:140])
    manuscript_docx = bundle / "manuscript.docx"
    approved_bytes = manuscript_docx.read_bytes()
    manuscript_docx.write_bytes(approved_bytes + b"post-confirmation-change")
    changed = subprocess.run(
        [sys.executable, str(freezer), "verify", "--project", str(proj)],
        capture_output=True, text=True, env=env, encoding="utf-8", errors="replace")
    outcome = gate("bundle_matches_freeze", "S25_submission_audit")
    record("post-confirmation package mutation is rejected",
           changed.returncode != 0 and not outcome.ok,
           ((changed.stderr or "") + outcome.detail).strip()[:140])
    manuscript_docx.write_bytes(approved_bytes)
    verified = subprocess.run(
        [sys.executable, str(freezer), "verify", "--project", str(proj)],
        capture_output=True, text=True, env=env, encoding="utf-8", errors="replace")
    record("restoring the approved package clears freeze gate", verified.returncode == 0,
           ((verified.stdout or "") + (verified.stderr or "")).strip()[:120])
    freeze_payload = json.loads((submission / "package_review_freeze.json").read_text(encoding="utf-8"))
    record("final freeze includes the S23 content baseline",
           any(item.get("path") == "08_submission/package_content_baseline.json"
               for item in freeze_payload.get("files", [])))
    record("final freeze includes every deterministic DOCX build receipt",
           sum(str(item.get("path", "")).startswith("08_submission/build_receipts/")
               for item in freeze_payload.get("files", [])) == 4)
    audit_path = submission / "independent_submission_audit.md"
    audit_path.write_text("# Verdict\n\nPASS\n", encoding="utf-8")
    outcome = gate("submission_audit_matches_freeze", "S25_submission_audit")
    record("stale or unbound independent audit is rejected", not outcome.ok, outcome.detail[:120])
    audit_path.write_text(
        "# Verdict\n\nPASS\n\nFreeze ID: " + freeze_payload["freeze_id"] +
        "\n\n# Guideline compliance\n\nPass.\n\n# Required files and omissions\n\nNone.\n"
        "\n# Cross-file consistency\n\nPass.\n\n# Formatting and technical checks\n\nPass.\n"
        "\n# Issues requiring correction\n\nNone.\n\n# Final recommendation\n\nReady.\n",
        encoding="utf-8")
    outcome = gate("submission_audit_matches_freeze", "S25_submission_audit")
    record("independent audit binds to the exact approved freeze", outcome.ok, outcome.detail)

    missing_supp = dict(manifest)
    missing_supp["items"] = [item for item in manifest["items"]
                              if item["role"] != "supplementary"]
    manifest_path.write_text(json.dumps(missing_supp, indent=2), encoding="utf-8")
    outcome = gate("docx_bundle_ready", "S23_package")
    record("missing supplementary Methods DOCX is rejected", not outcome.ok,
           outcome.detail[:100])

    def make_blue_docx(source: Path, destination: Path) -> bool:
        with zipfile.ZipFile(source, "r") as src:
            entries = [(info, src.read(info.filename)) for info in src.infolist()]
        changed = False
        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as out:
            for info, blob in entries:
                if info.filename == "word/document.xml":
                    replaced = blob.replace(b'w:val="000000"', b'w:val="0000FF"', 1)
                    changed = replaced != blob
                    blob = replaced
                out.writestr(info, blob)
        return changed

    blue = bundle / "manuscript_blue.docx"
    changed = make_blue_docx(bundle / "manuscript.docx", blue)
    bad_manifest = json.loads(json.dumps(manifest))
    next(item for item in bad_manifest["items"] if item["role"] == "manuscript")["file"] = (
        "08_submission/bundle/manuscript_blue.docx")
    manifest_path.write_text(json.dumps(bad_manifest, indent=2), encoding="utf-8")
    outcome = gate("docx_bundle_ready", "S23_package")
    record("blue Word text is rejected", changed and not outcome.ok, outcome.detail[:100])
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    blue.unlink(missing_ok=True)

    if os.environ.get("MEDPAPER_SELFTEST_KEEP_ARTIFACTS") == "1":
        qa_docs = proj.parent / "word_qa"
        qa_docs.mkdir(parents=True, exist_ok=True)
        for name in ("manuscript.docx", "supplementary_methods.docx"):
            shutil.copy2(bundle / name, qa_docs / name)
    shutil.rmtree(submission, ignore_errors=True)
    for name in ("title.md", "abstract.md", "keywords.md", "introduction.md", "methods.md",
                 "discussion.md", "supplementary_methods.md", "full_manuscript.md", "title_page.md"):
        (manuscript / name).unlink(missing_ok=True)
    bib.unlink(missing_ok=True)

def run_polish(proj: Path) -> None:
    from wfcore import registry
    from wfcore.checks import Ctx, get, load_all
    from wfcore.state import State

    load_all()
    pipe = registry.load()
    st = State(proj, ".wf").load()
    tool = ROOT / "tools/text/polish.py"
    env = {**os.environ, "MEDPAPER_PROJECT": str(proj), "MEDPAPER_ROOT": str(ROOT),
           "PYTHONIOENCODING": "utf-8"}

    def polish(*argv):
        return subprocess.run([sys.executable, str(tool), *argv], capture_output=True,
                              text=True, env=env, encoding="utf-8", errors="replace")

    def gate(name: str, stage: str = "S22_polish", **spec):
        fn = get(name)
        return fn(Ctx(pipeline=pipe, state=st, project=proj,
                      stage=pipe.stage(stage), spec={"check": name, **spec}))

    disc = proj / "07_manuscript/discussion.md"
    abstract = proj / "07_manuscript/abstract.md"

    section("polish: linting AI slop")
    disc.write_text(SLOP, encoding="utf-8")
    abstract.write_text("# Abstract\n\nExposure was associated with the outcome "
                        "(HR 1.87, 95% CI 1.34 to 2.61).\n", encoding="utf-8")
    p = polish("snapshot")
    record("snapshot taken", p.returncode == 0 and (proj / "07_manuscript/prepolish/facts.json").exists())
    record("snapshot refuses to overwrite silently", polish("snapshot").returncode == 1)

    p = polish("lint")
    out = p.stdout or ""
    counts = json.loads((proj / "07_manuscript/polish_report.json").read_text(encoding="utf-8"))["counts"]
    record("tier-A AI phrases detected", counts["ai_tier_a"] >= 10, f"{counts['ai_tier_a']} found")
    record("structural tells detected", counts["structure_blocking"] >= 1,
           f"{counts['structure_blocking']} blocking")
    record("house-style defects detected", counts["style_blocking"] >= 4,
           f"{counts['style_blocking']} blocking")
    for want, label in [("utilize", "inflated verb"), ("range_dash", "hyphen numeric range"),
                        ("unit_spacing", "value glued to unit"), ("data_agreement", "'data was'"),
                        ("p_zero", "P = 0.000"), ("causal_overclaim", "causal overclaim"),
                        ("hedge_stacking", "stacked hedges")]:
        record(f"caught: {label}", want in out, "" if want in out else f"{want!r} absent from report")

    r = gate("ai_tells_clean")
    record("ai_tells_clean rejects the slop", not r.ok, r.detail[:100])
    r = gate("style_consistent")
    record("style_consistent rejects the slop", not r.ok, r.detail[:100])

    section("polish: fact preservation")
    disc.write_text(CLEAN, encoding="utf-8")
    p = polish("diff")
    record("polished text preserves every fact", p.returncode == 0,
           (p.stdout or "").strip().splitlines()[-1][:90])
    polish("lint")
    r = gate("ai_tells_clean")
    record("ai_tells_clean accepts the polished text", r.ok, r.detail[:100])
    r = gate("style_consistent")
    record("style_consistent accepts the polished text", r.ok, r.detail[:100])

    disc.write_text(CLEAN.replace("HR 1.87, 95% CI\n1.34 to 2.61", "HR 1.90, 95% CI\n1.40 to 2.60"),
                    encoding="utf-8")
    p = polish("diff")
    record("altered statistic is caught by diff", p.returncode == 2,
           next((ln.strip() for ln in (p.stdout or "").splitlines() if "LOST" in ln), "")[:90])
    r = gate("polish_preserves_facts")
    record("polish_preserves_facts gate rejects it", not r.ok, r.detail[:100])

    disc.write_text(CLEAN.replace("[@smith2020cohort]", ""), encoding="utf-8")
    record("dropped citation is caught by diff", polish("diff").returncode == 2)

    disc.write_text(CLEAN.replace("(Figure 1A)", ""), encoding="utf-8")
    record("dropped figure reference is caught by diff", polish("diff").returncode == 2)

    disc.write_text(CLEAN, encoding="utf-8")
    record("restoring the text clears diff", polish("diff").returncode == 0)

    section("polish: journal limits")
    (proj / "08_submission").mkdir(parents=True, exist_ok=True)
    tj = proj / "08_submission/target_journal.json"
    tj_before = tj.read_text(encoding="utf-8") if tj.is_file() else None
    tj_data = json.loads(tj_before) if tj_before else {}

    def limits(**caps):
        tj.write_text(json.dumps({**tj_data, "limits": {"source": "guide URL; quoted rule",
                                                        **caps}}), encoding="utf-8")
    limits(abstract_words=250, main_text_words=3500, reference_limit=50)
    polish("lint")
    r = gate("journal_limits_met")
    record("journal_limits_met reads the typed caps and passes", r.ok, r.detail[:110])
    limits(abstract_words=250, main_text_words=100, reference_limit=50)
    r = gate("journal_limits_met")
    record("journal_limits_met rejects an over-limit manuscript", not r.ok, r.detail[:110])
    tj.write_text(json.dumps(tj_data), encoding="utf-8")
    r = gate("journal_limits_met")
    record("journal_limits_met rejects a journal without typed limits", not r.ok, r.detail[:110])
    if tj_before is None:
        tj.unlink()
    else:
        tj.write_text(tj_before, encoding="utf-8")

    section("polish: allowlist escape hatch")
    disc.write_text(CLEAN + "\nThe guideline states that screening plays a crucial role.\n",
                    encoding="utf-8")
    polish("lint")
    record("allowlist absent -> phrase blocks", not gate("ai_tells_clean").ok)
    (proj / "07_manuscript/polish_allowlist.tsv").write_text(
        "plays a crucial role\tquoted verbatim from the 2023 guideline\n", encoding="utf-8")
    polish("lint")
    record("allowlisted phrase stops blocking", gate("ai_tells_clean").ok)

    for f in (disc, abstract, proj / "07_manuscript/polish_allowlist.tsv"):
        f.unlink(missing_ok=True)
    shutil.rmtree(proj / "07_manuscript/prepolish", ignore_errors=True)
    (proj / "07_manuscript/polish_report.json").unlink(missing_ok=True)


def run_online(proj: Path) -> None:
    section("live API (network)")
    env = {**os.environ, "MEDPAPER_PROJECT": str(proj), "MEDPAPER_ROOT": str(ROOT),
           "PYTHONIOENCODING": "utf-8"}
    p = subprocess.run([sys.executable, str(ROOT / "tools/pubmed/client.py"),
                        "fetch", "--ids", "32150289", "--with-abstract"],
                       capture_output=True, text=True, env=env, encoding="utf-8", errors="replace")
    record("PubMed efetch returns a real record",
           "Sarcopenia Definition" in (p.stdout or ""), (p.stderr or "")[:100])
    p = subprocess.run([sys.executable, str(ROOT / "tools/pubmed/build_library.py"),
                        "--add-ids", "32150289,34315158", "--export"],
                       capture_output=True, text=True, env=env, encoding="utf-8", errors="replace")
    record("library builds and exports", (proj / "06_refs/refs.bib").exists(),
           (p.stderr or "")[:100])
    p = subprocess.run([sys.executable, str(ROOT / "tools/pubmed/verify.py")],
                       capture_output=True, text=True, env=env, encoding="utf-8", errors="replace")
    record("verification confirms every entry against the source",
           "verified 2/2" in (p.stdout or ""), (p.stdout or "").strip()[-90:])
    from wfcore import registry
    from wfcore.checks import Ctx, get, load_all
    from wfcore.state import State

    load_all()
    pipe = registry.load()
    state = State(proj, ".wf").load()
    outcome = get("reference_provenance")(Ctx(
        pipeline=pipe,
        state=state,
        project=proj,
        stage=pipe.stage("S13_reflib"),
        spec={"check": "reference_provenance", "live": True},
    ))
    record("independent S13 gate re-fetches verified records live", outcome.ok,
           outcome.detail[:120])


# ---------------------------------------------------------------------------
# 1.5.0: engine purity, Python/R split, R figures, receipts, re-execution, checklists
# ---------------------------------------------------------------------------
WF = ROOT / "tools/wf.py"


def _env(**extra) -> dict:
    env = {k: v for k, v in os.environ.items() if k != "MEDPAPER_PROJECT"}
    env.pop("MEDPAPER_ROOT", None)
    env["PYTHONIOENCODING"] = "utf-8"
    for k, v in extra.items():
        if v is None:
            env.pop(k, None)
        else:
            env[k] = str(v)
    return env


def _run(cmd, env=None, cwd=None, timeout=600) -> subprocess.CompletedProcess:
    return subprocess.run([str(c) for c in cmd], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env or _env(),
                          cwd=str(cwd) if cwd else None, timeout=timeout)


def _out(p) -> str:
    return (p.stdout or "") + (p.stderr or "")


def _wf(*args, env=None, cwd=None) -> subprocess.CompletedProcess:
    return _run([sys.executable, WF, *args], env=env, cwd=cwd)


def _sha(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _new_paper(path: Path) -> Path:
    from wfcore import registry
    from wfcore.state import State
    pipe = registry.load()
    path.mkdir(parents=True, exist_ok=True)
    State(path, ".wf").create(pipe.meta["name"], pipe.meta["version"], pipe.first().id)
    return path


def run_engine_purity(tmp: Path) -> None:
    import json as _json
    from unittest.mock import patch

    from wfcore import adapters, cli, paths, runner

    section("engine purity: papers live outside the engine")
    papers = Path(os.environ["MEDPAPER_PAPERS_ROOT"])
    home = Path(os.environ["MEDPAPER_HOME"])
    for name in ("project", "papers", "temp", ".wf"):
        if (ROOT / name).exists():
            record(f"precondition: engine has no {name}/", False, str(ROOT / name))
    p = _wf("new", "demo", cwd=tmp)
    demo = papers / "demo"
    marker = home / "active"
    record("wf new creates the paper under the papers root with paper-local adapters",
           p.returncode == 0 and (demo / ".wf/state.json").is_file()
           and (demo / ".kiro/steering/medpaper-pipeline.md").is_file()
           and (demo / ".kiro/hooks/medpaper-status.json").is_file()
           and (demo / ".kiro/hooks/medpaper-skill-guard.json").is_file(), _out(p)[-160:])
    record("the user-level marker holds the paper's absolute path",
           marker.is_file() and Path(marker.read_text(encoding="utf-8").strip()) == demo.resolve(),
           marker.read_text(encoding="utf-8").strip() if marker.is_file() else "no marker")
    eng = ROOT.as_posix()
    steering = (demo / ".kiro/steering/medpaper-pipeline.md").read_text(encoding="utf-8")
    hooks = [_json.loads((demo / f".kiro/hooks/{n}").read_text(encoding="utf-8"))
             for n in ("medpaper-status.json", "medpaper-skill-guard.json")]
    record("paper adapters call the engine by absolute path",
           f'python "{eng}/tools/wf.py" status' in steering
           and hooks[0]["hooks"][0]["action"]["command"] == f'python "{eng}/tools/wf.py" status --brief'
           and hooks[1]["hooks"][0]["action"]["command"] == f'python "{eng}/tools/hooks/skill_guard.py"'
           and "delegated subagent" in steering and "do not advance a stage" in steering,
           hooks[0]["hooks"][0]["action"]["command"])

    p = _wf("new", "x", "--root", ROOT / "papers", cwd=tmp)
    record("wf new --root inside the engine is refused and creates nothing",
           p.returncode != 0 and not (ROOT / "papers").exists(), _out(p)[-120:])
    p = _wf("new", "x", env=_env(MEDPAPER_PAPERS_ROOT=ROOT / "papers"), cwd=tmp)
    record("a papers root inside the engine is refused",
           p.returncode != 0 and not (ROOT / "papers").exists(), _out(p)[-120:])
    p = _wf("status", env=_env(MEDPAPER_PROJECT=ROOT / "project"), cwd=tmp)
    record("MEDPAPER_PROJECT pointing into the engine is refused",
           p.returncode != 0 and not (ROOT / "project").exists(), _out(p)[-120:])
    p = _wf("init", cwd=ROOT)
    record("wf init in the engine is refused", p.returncode != 0
           and not (ROOT / ".wf").exists() and not (ROOT / "00_input").exists(), _out(p)[-120:])
    standalone = tmp / "standalone"
    standalone.mkdir()
    p = _wf("init", cwd=standalone)
    record("wf init outside the engine creates state and adapters",
           p.returncode == 0 and (standalone / ".wf/state.json").is_file()
           and (standalone / ".kiro/steering/medpaper-pipeline.md").is_file(), _out(p)[-120:])

    p = _wf("status", cwd=ROOT)
    record("wf status in the engine prints the maintenance banner and exits 0",
           p.returncode == 0 and "ENGINE WORKSPACE" in p.stdout and "papers root" in p.stdout
           and "open its folder" in p.stdout, p.stdout[:120])
    p = _wf("status", "--json", cwd=ROOT)
    try:
        js = _json.loads(p.stdout)
    except ValueError:
        js = {}
    record("wf status --json in the engine reports engine_workspace", js.get("engine_workspace") is True)
    p = _wf("check", cwd=ROOT)
    record("paper-driving commands exit 2 in the engine", p.returncode == 2
           and "ENGINE workspace" in p.stdout, _out(p)[-100:])
    p = _wf("card", "S05", cwd=ROOT)
    card = (ROOT / "pipeline/stages/S05_analysis.md").read_text(encoding="utf-8").rstrip()
    record("wf card <stage> in the engine prints the master card unchanged",
           p.returncode == 0 and p.stdout.rstrip("\n") == card)
    p = _wf("card", cwd=ROOT)
    record("wf card without a stage needs a paper", p.returncode == 2)
    p = _wf("status", "--brief", cwd=demo)
    record("wf status from the paper resolves it from the working directory",
           p.returncode == 0 and "found at or above" in p.stdout, p.stdout[:160])

    marker.unlink()
    p = _wf("use", "demo", cwd=ROOT)
    record("wf use from the engine writes only the user-level marker",
           p.returncode == 0 and marker.is_file() and not (ROOT / ".wf").exists(), _out(p)[-100:])
    p = _wf("papers", cwd=tmp)
    record("wf papers lists the selected paper and the root source",
           "* demo" in p.stdout and "MEDPAPER_PAPERS_ROOT" in p.stdout, p.stdout[:160])
    marker.write_text(str(papers / "gone") + "\n", encoding="utf-8")
    p = _wf("status", cwd=tmp)
    record("a stale marker fails closed", p.returncode != 0 and "state is missing" in _out(p))
    marker.write_text(str(demo.resolve()) + "\n", encoding="utf-8")

    with patch.dict(os.environ, {"MEDPAPER_PROJECT": str(demo)}):
        refused = []
        for target in (ROOT / "tools/x.png", ROOT / "x"):
            try:
                paths.paper_output_path(target)
                refused.append(False)
            except ValueError:
                refused.append(True)
        from tables.threeline import write_table
        try:
            write_table(ROOT / "x.xlsx", "Table 1", "Table 1. X.", ["a", "b"], [["1", "2"]],
                        ["Abbreviations: none."])
            refused.append(False)
        except ValueError:
            refused.append(True)
    record("writers refuse every output inside the engine",
           all(refused) and not (ROOT / "x.xlsx").exists(), str(refused))
    checks_ = []
    for cand in (ROOT, ROOT / "tools", ROOT.parent):
        try:
            paths.check_paper_location(cand, "test")
            checks_.append(False)
        except paths.PaperLocationError:
            checks_.append(True)
    record("check_paper_location refuses the engine, a child and a parent", all(checks_))

    fake = tmp / "fake_engine_snap"
    for d in ("tools", ".venv", ".git", "tools/__pycache__"):
        (fake / d).mkdir(parents=True, exist_ok=True)
    with patch.object(paths, "engine_roots", return_value=(fake,)):
        before = runner.engine_snapshot()
        (fake / "new_top.txt").write_text("x", encoding="utf-8")
        (fake / ".venv/x").write_text("x", encoding="utf-8")
        (fake / ".git/x").write_text("x", encoding="utf-8")
        (fake / "tools/__pycache__/x.pyc").write_text("x", encoding="utf-8")
        changes = runner.diff_snapshots(before, runner.engine_snapshot())
    record("runner tripwire covers the whole engine tree but ignores .venv/.git/caches",
           len(changes) == 1 and changes[0].endswith("new_top.txt"), str(changes))

    # localisation of card text and hints
    old = Path.cwd()
    try:
        os.chdir(tmp)
        a = paths.localize_commands(".\\.venv\\Scripts\\python.exe tools/wf.py check")
        b = paths.localize_commands("python tools/rework.py status")
        c = paths.localize_commands("Run `tools/text/polish.py lint` and read reference/figure-standards.md")
        os.chdir(demo)
        d = paths.localize_commands("`project/05_figures/out/Figure1.png`", demo)
        keep = [paths.localize_commands(s, demo) for s in
                ("G:/t/project/07_x.md", "subproject/x", "--project project")]
        os.chdir(ROOT)
        ident = paths.localize_commands(".\\.venv\\Scripts\\python.exe tools/wf.py check")
    finally:
        os.chdir(old)
    record("localize_commands makes engine commands absolute outside the engine",
           f"{eng}/.venv/Scripts/python.exe {eng}/tools/wf.py check" in a
           and f'python "{eng}/tools/rework.py" status' in b
           and f'python "{eng}/tools/text/polish.py" lint' in c
           and f"{eng}/reference/figure-standards.md" in c, a + " | " + c)
    record("localize_commands strips the project/ alias at the paper root only",
           d == "`05_figures/out/Figure1.png`"
           and keep == ["G:/t/project/07_x.md", "subproject/x", "--project project"], str(keep))
    record("localize_commands is the identity in the engine without a paper",
           ident == ".\\.venv\\Scripts\\python.exe tools/wf.py check")
    import re as _re
    bare = _re.compile(r'(?<![\w/\\.\-"])tools[/\\]\S+\.py')
    bad_cards = []
    for stage in sorted((ROOT / "pipeline/stages").glob("S*.md")):
        p = _wf("card", stage.stem.split("_")[0], cwd=demo)
        text = p.stdout.replace(f"{eng}/tools/", "")
        if bare.search(text) or _re.search(r"(?<![\w/\\.\-])project/", p.stdout):
            bad_cards.append(stage.stem)
    record("every stage card rendered in a paper has absolute engine commands and no project/",
           not bad_cards, ", ".join(bad_cards[:6]))
    p = _wf("invariants", cwd=demo)
    record("wf invariants rendered in a paper has no bare tools/*.py",
           not bare.search(p.stdout.replace(f"{eng}/tools/", "")))
    p = _wf("card", "S08", cwd=demo)
    q = _wf("card", "S08", cwd=demo / "03_analysis")
    record("cards address paper files relative to the paper root, absolute from a subfolder",
           "07_manuscript/methods.md" in p.stdout and "project/07_manuscript" not in p.stdout
           and f"{demo.resolve().as_posix()}/07_manuscript/methods.md" in q.stdout)
    eng_env = _env(MEDPAPER_PROJECT=demo)
    p = _wf("card", "S08", env=eng_env, cwd=ROOT)
    s = _wf("status", env=eng_env, cwd=ROOT)
    record("driving a paper from the engine cwd rewrites project/ to the absolute paper path",
           f"{demo.resolve().as_posix()}/07_manuscript/methods.md" in p.stdout
           and not _re.search(r"(?<![\w/\\.\-])project/07_manuscript", p.stdout)
           and "!! driving paper" in s.stdout.splitlines()[0]
           and not _re.search(r"(?<![\w/\\.\-])project/", s.stdout.split("DECLARED OUTPUTS")[-1].split("STAGE CARD")[0]),
           s.stdout.splitlines()[0][:120] if s.stdout else _out(s)[-100:])
    s = _wf("status", "--brief", cwd=demo)
    block = s.stdout.split("DECLARED OUTPUTS")[-1]
    record("wf status from the paper root prints DECLARED OUTPUTS without project/",
           "project/" not in block and "01_protocol/idea.json" in block, block[:120])

    p = _run([sys.executable, ROOT / "tools/install_adapters.py", "--check"], cwd=ROOT)
    record("engine adapters are in sync with adapters.engine_adapters()", p.returncode == 0, _out(p)[-100:])
    nonpaper = tmp / "not_a_paper"
    nonpaper.mkdir()
    p = _run([sys.executable, ROOT / "tools/install_adapters.py", "--paper", nonpaper], cwd=tmp)
    record("install_adapters --paper refuses a folder that is not a paper",
           p.returncode != 0 and not (nonpaper / ".kiro").exists(), _out(p)[-100:])
    p = _wf("clean", cwd=demo)
    record("no_orphans/wf clean never report the paper's .kiro/", ".kiro" not in p.stdout, p.stdout[-120:])

    bad_project = ROOT / "project"
    clis = [
        [ROOT / "tools/rework.py", "status", "--project", bad_project],
        [ROOT / "tools/data_manifest.py", "verify", "--project", bad_project],
        [ROOT / "tools/package_content.py", "verify", "--project", bad_project],
        [ROOT / "tools/package_review.py", "verify", "--project", bad_project],
        [ROOT / "tools/manuscript/reference_count.py", "show", "--project", bad_project],
        [ROOT / "tools/manuscript/review_package.py", "build", "--project", bad_project],
        [ROOT / "tools/reproduce.py", "run", "--project", bad_project],
    ]
    refused = [_run([sys.executable, *c], cwd=tmp).returncode != 0 for c in clis]
    p = _run([sys.executable, ROOT / "tools/manuscript/review_package.py", "build"],
             env=_env(MEDPAPER_PROJECT=bad_project), cwd=tmp)
    refused.append(p.returncode != 0)
    record("every --project CLI refuses a paper inside the engine",
           all(refused) and not bad_project.exists(), str(refused))
    with patch.dict(os.environ, {"MEDPAPER_PROJECT": str(demo)}):
        ok_ = (paths.paper_from_cli(None) == paths.project_dir()
               and paths.paper_from_cli("project") == demo.resolve()
               and paths.paper_from_cli("project/03_analysis") == demo.resolve()
               and paths.paper_from_cli(str(standalone)) == standalone.resolve())
        try:
            paths.paper_from_cli(str(nonpaper))
            ok_ = False
        except SystemExit:
            pass
    record("paper_from_cli accepts the alias and real papers, refuses non-papers", ok_)

    p = _wf("use", "demo", env=_env(MEDPAPER_HOME=ROOT / "h"), cwd=ROOT)
    q = _wf("use", "demo", env=_env(MEDPAPER_HOME=ROOT.parent), cwd=tmp)
    record("MEDPAPER_HOME inside or over the engine is refused",
           p.returncode != 0 and q.returncode != 0 and not (ROOT / "h").exists())
    fake_eng = tmp / "fake_engine_root"
    fake_eng.mkdir()
    p = _wf("status", env=_env(MEDPAPER_ROOT=fake_eng, MEDPAPER_PROJECT=ROOT / "project"), cwd=tmp)
    with patch.dict(os.environ, {"MEDPAPER_ROOT": str(fake_eng)}):
        still = paths.in_engine(ROOT / "tools")
    record("redirecting MEDPAPER_ROOT never unprotects the physical engine",
           p.returncode != 0 and still and not (ROOT / "project").exists(), _out(p)[-100:])
    p = _wf("papers", env=_env(MEDPAPER_PAPERS_ROOT=ROOT.parent), cwd=tmp)
    q = _wf("new", ROOT.name, "--root", ROOT.parent, cwd=tmp)
    record("a papers root containing the engine is refused", p.returncode != 0 and q.returncode != 0)
    p = _wf("new", "demo2", "--root", "rel/dir", cwd=tmp)
    record("wf new --root resolves a relative root against the cwd",
           p.returncode == 0 and (tmp / "rel/dir/demo2/.wf/state.json").is_file(), _out(p)[-100:])
    marker.write_text(str(demo.resolve()) + "\n", encoding="utf-8")

    p = _run([sys.executable, ROOT / "tools/package_review.py", "freeze", "--project", demo,
              "--freeze", ROOT / "x.json"], cwd=tmp)
    q = _run([sys.executable, ROOT / "tools/package_review.py", "freeze", "--project", demo,
              "--freeze", tmp / "elsewhere.json"], cwd=tmp)
    try:
        inside = paths.output_within(demo, "project/08_submission/f.json") == \
            (demo / "08_submission/f.json").resolve()
        for bad in (ROOT / "x", tmp / "y"):
            try:
                paths.output_within(demo, bad)
                inside = False
            except ValueError:
                pass
    except ValueError:
        inside = False
    record("package_review --freeze stays inside its paper",
           p.returncode != 0 and q.returncode != 0 and not (ROOT / "x.json").exists() and inside)
    p = _run([sys.executable, ROOT / "tools/selftest.py", "--workdir", ROOT / "temp/st"], cwd=ROOT)
    record("selftest --workdir inside the engine is refused before any mkdir",
           p.returncode == 1 and "inside the engine" in _out(p) and not (ROOT / "temp").exists(),
           _out(p)[-100:])

    nested = [_wf("init", cwd=demo / "03_analysis").returncode,
              _wf("init", cwd=papers).returncode,
              _wf("init", cwd=tmp).returncode,
              _wf("new", "inner", "--root", demo, cwd=tmp).returncode,
              _wf("init", "--force", cwd=demo / "03_analysis").returncode]
    record("papers cannot be nested (inside a paper, the papers root, or around one)",
           all(c == 2 for c in nested) and not (demo / "03_analysis/.wf").exists()
           and not (demo / "inner").exists(), str(nested))

    (demo / "project").mkdir()
    p = _wf("doctor", cwd=demo)
    (demo / "project").rmdir()
    q = _wf("doctor", cwd=demo)
    record("doctor reports a literal project/ inside a paper as BROKEN",
           "paper layout" in p.stdout and "BROKEN" in p.stdout.split("paper layout")[1][:30]
           and "paper layout" in q.stdout and " ok " in q.stdout.split("paper layout")[1][:30])
    p = _wf("doctor", cwd=ROOT)
    record("wf doctor on the pure engine is OK", p.returncode == 0 and "papers root" in p.stdout
           and "doctor: OK" in p.stdout, p.stdout[-200:])


def run_language_policy() -> None:
    import tomllib
    from wfcore import cli, registry
    section("Python/R language policy")
    data = tomllib.loads((ROOT / "reference/language_policy.toml").read_text(encoding="utf-8"))
    probs = cli.validate_language_policy(data)
    record("language_policy.toml parses and validates", not probs, "; ".join(probs[:3]))
    record('"data.table" is a quoted key of [r.optional]',
           "data.table" in data["r"]["optional"] and "data" not in data["r"]["optional"])
    bad = tomllib.loads('[r]\nmin_version = "4.3.0"\n[r.optional]\ndata.table = "0"\n')
    record("an unquoted dotted package name is reported",
           any("must be quoted" in p for p in cli.validate_language_policy(bad)))
    cards = [ROOT / f"pipeline/stages/{c}.md" for c in ("S04_data", "S05_analysis", "S10_tables",
                                                        "S11_figures")]
    cards.append(ROOT / ".kiro/skills/medpaper-pipeline/SKILL.md")
    missing = [c.name for c in cards if "reference/language_policy.toml" not in c.read_text(encoding="utf-8")]
    record("S04/S05/S10/S11 and SKILL.md point at the language policy", not missing, str(missing))
    record("figures default to R", str(registry.load().targets.get("figure_engine")) == "R")

    # 1.7.1: doctor requires the engine core plus what the paper's own scripts use, not the
    # whole statistics catalogue.
    import tempfile
    tp = Path(tempfile.mkdtemp(prefix="medpaper_rpk_"))
    try:
        (tp / "03_analysis/code").mkdir(parents=True)
        (tp / "03_analysis/code/01_m.R").write_text(
            "library(survival)\nx <- meta::metagen(1, 1)\n# library(commentedpkg)\n"
            "p <- recipe_cif(curve = r$cif, times = 0:3)\nlibrary(notapkg456)\n",
            encoding="utf-8")
        used = cli.r_packages_used(tp)
        record("paper R package scan: library(), pkg::, engine helpers; comments ignored",
               {"survival", "meta", "tidycmprsk", "ggsurvfit", "notapkg456"} <= set(used)
               and "commentedpkg" not in used, str(sorted(used)))
        if shutil.which("Rscript"):
            pol = {"r": {"min_version": "4.3.0", "required": {"jsonlite": "0",
                                                             "notapkg123": "0"}},
                   "task": [{"id": "figures", "packages": ["jsonlite"]}]}
            rows = {n.strip(): (s, d) for n, s, d in cli._r_rows(pol, tp)}
            record("an unused catalogue package is info; a package the paper uses is MISSING",
                   rows.get("notapkg123", ("",))[0] == "absent"
                   and "not used" in rows.get("notapkg123", ("", ""))[1]
                   and rows.get("notapkg456", ("",))[0] == "MISSING"
                   and "01_m.R" in rows.get("notapkg456", ("", ""))[1], str(rows)[:300])
    finally:
        shutil.rmtree(tp, ignore_errors=True)


def run_paper_header(tmp: Path) -> None:
    from wfcore import cli, paths as wp
    section("1.7.1 resolved-paper header and global-marker warning")
    a, b = _new_paper(tmp / "paper_a"), _new_paper(tmp / "paper_b")
    real_marker, real_cwd = wp.active_paper, Path.cwd()
    saved_env = os.environ.pop("MEDPAPER_PROJECT", None)
    try:
        wp.active_paper = lambda: b
        os.chdir(a)
        lines = cli.paper_header(a, "found at or above the working directory")
        record("every command names the paper it acts on, and the cwd paper beats the marker",
               lines[0].startswith("[medpaper] paper: ") and str(a) in lines[0]
               and any("global `wf use` marker points at" in x for x in lines), str(lines))
        lines = cli.paper_header(b, "MEDPAPER_PROJECT")
        record("acting on another paper than the cwd's is a WARNING",
               any("WARNING: the working directory is inside paper" in x for x in lines),
               str(lines))
        os.chdir(tmp)
        lines = cli.paper_header(b, "selected with wf use")
        record("a marker-only selection says how to pin the paper",
               any("chosen by the global `wf use` marker" in x for x in lines), str(lines))
    finally:
        os.chdir(real_cwd)
        wp.active_paper = real_marker
        if saved_env is not None:
            os.environ["MEDPAPER_PROJECT"] = saved_env


def run_no_plot_calls_r() -> None:
    from wfcore.checks.text import plot_calls
    section("no_plot_calls covers R and Python")
    flagged = ["plot(x)", "hist(x)", "graphics::barplot(x)", "boxplot(y ~ g)", 'png("a.png")',
               'pdf("a.pdf")', "dev.off()", "ggplot(df)", 'ggsave("a.png")',
               "survminer::ggsurvplot(fit)", "ggsurvfit(fit)", "metafor::forest(m)",
               "lines(x, y)", "abline(h = 0)", "par(mfrow = c(1, 2))", "pheatmap::pheatmap(m)",
               "pROC::ggroc(r)", "grid::grid.draw(g)", "qplot(x)", "cobalt::love.plot(w)",
               "densityplot(imp)", "funnel(m)", "plot.roc(r)"]
    missed = [s for s in flagged if not plot_calls("a.R", s + "\n")]
    missed += [s for s in ("df.plot()\n", "import seaborn\n", "kmf.plot_survival_function()\n")
               if not plot_calls("a.py", s)]
    record("R and Python plotting calls are flagged", not missed, str(missed))
    clean_r = ["plot_data <- df", "my.plot(x)", "my.lines(x)", "outlines(x)",
               "plot_layout(ncol = 2)", "df$points", "randomForest(y ~ .)",
               "survfit(Surv(t, e) ~ 1)", "readLines(f)", "library(ggplot2)", "# plot(x)",
               'msg <- "plot(x)"', "forest_df <- 1"]
    clean_py = ["plot_data = 1", "# plt.plot", 'x = "matplotlib"', "progress.bar(1)",
                'print(f"wrote plt.png")']
    wrong = [s for s in clean_r if plot_calls("a.R", s + "\n")]
    wrong += [s for s in clean_py if plot_calls("a.py", s + "\n")]
    record("non-plot code, comments and strings are not flagged", not wrong, str(wrong))


def _gate(name: str, proj: Path, stage: str = "S05_analysis", **spec):
    from wfcore import registry
    from wfcore.checks import Ctx, get, load_all
    from wfcore.state import State
    load_all()
    pipe = registry.load()
    st = State(proj, ".wf").load()
    return get(name)(Ctx(pipeline=pipe, state=st, project=proj, stage=pipe.stage(stage),
                         spec={"check": name, **spec}))


R_HELPER = 'source(file.path(Sys.getenv("MEDPAPER_ROOT"), "tools/R/medresults.R"))\n'


def run_results_environment(tmp: Path) -> None:
    import json as _json
    section("environment receipts in results JSON")
    if not shutil.which("Rscript"):
        record("results environment: Rscript available", False, "Rscript missing")
        return
    P = _new_paper(tmp / "envpaper")
    code = P / "03_analysis/code"
    code.mkdir(parents=True)
    env = _env(MEDPAPER_PROJECT=P)
    (code / "01_py.py").write_text(
        "import numpy\nfrom analysis.results import set_seed, write_results\n"
        "set_seed(20240917)\nwrite_results('py_primary', {'hr': 1.87432198765, 'n': 1284, "
        "'draw': float(numpy.random.random())})\n", encoding="utf-8")
    (code / "02_r.R").write_text(
        R_HELPER + "medpaper_seed(42)\n"
        'write_results(list(hr = 1.87432198765, n = 1284L, covariates = I("age"), '
        'third = 1/3, long = 0.1234567890123456789, tiny = 1e-20, big = 2^53, '
        'p = 0.000123456789012345), "r_primary")\n',
        encoding="utf-8")
    p1 = _wf("run-script", "03_analysis/code/01_py.py", env=env, cwd=tmp)
    p2 = _wf("run-script", "03_analysis/code/02_r.R", env=env, cwd=tmp)
    res = P / "03_analysis/results"
    py = _json.loads((res / "py_primary.json").read_text(encoding="utf-8")) if (res / "py_primary.json").is_file() else {}
    rr = _json.loads((res / "r_primary.json").read_text(encoding="utf-8")) if (res / "r_primary.json").is_file() else {}
    pe, re_ = py.get("environment", {}), rr.get("environment", {})
    record("Python write_results keeps full precision and records the environment",
           p1.returncode == 0 and py.get("hr") == 1.87432198765 and pe.get("language") == "python"
           and pe.get("seed") == 20240917 and "numpy" in pe.get("packages", {})
           and pe.get("script") == "03_analysis/code/01_py.py"
           and pe.get("script_sha256") == _sha(code / "01_py.py"), _out(p1)[-160:])
    record("R write_results round-trips doubles exactly (digits = I(17), not 15 digits)",
           rr.get("third") == 1 / 3 and rr.get("long") == 0.1234567890123456789
           and rr.get("tiny") == 1e-20 and rr.get("big") == 2 ** 53
           and rr.get("p") == 0.000123456789012345,
           str({k: rr.get(k) for k in ("third", "long", "tiny", "big", "p")}))
    record("R write_results keeps 1.87432198765 and I() arrays",
           p2.returncode == 0 and rr.get("hr") == 1.87432198765 and rr.get("n") == 1284
           and rr.get("covariates") == ["age"] and re_.get("language") == "R"
           and re_.get("version") == "4.5.2" and "jsonlite" in re_.get("packages", {})
           and re_.get("seed") == 42, _out(p2)[-200:])
    record("no .tmp file is left beside the results", not list(res.glob("*.tmp")))
    g = _gate("results_have_environment", P)
    record("results_have_environment passes real receipts", g.ok, g.detail[:120])

    bare = res / "hand.json"
    bare.write_text('{"hr": 2.5}', encoding="utf-8")
    g = _gate("results_have_environment", P)
    record("N: a results file without a receipt fails", not g.ok and "hand.json" in g.detail)
    bare.unlink()
    orig = (code / "01_py.py").read_text(encoding="utf-8")
    (code / "01_py.py").write_text(orig + "# edited\n", encoding="utf-8")
    g = _gate("results_have_environment", P)
    record("N: editing the script after it wrote results fails", not g.ok and "changed" in g.detail)
    (code / "01_py.py").write_text(orig, encoding="utf-8")
    fake = dict(py)
    fake["environment"] = dict(pe, script="04_tables/code/x.py")
    (P / "04_tables/code").mkdir(parents=True)
    (P / "04_tables/code/x.py").write_text("x = 1\n", encoding="utf-8")
    fake["environment"]["script_sha256"] = _sha(P / "04_tables/code/x.py")
    (res / "fake.json").write_text(_json.dumps(fake), encoding="utf-8")
    g = _gate("results_have_environment", P)
    record("N: a receipt naming a non-analysis script fails", not g.ok and "fake.json" in g.detail)
    sub = dict(py)
    (code / "sub").mkdir()
    (code / "sub/run.py").write_text("x = 1\n", encoding="utf-8")
    sub["environment"] = dict(pe, script="03_analysis/code/sub/run.py", script_sha256=_sha(code / "sub/run.py"))
    (res / "fake.json").write_text(_json.dumps(sub), encoding="utf-8")
    g = _gate("results_have_environment", P)
    record("N: a receipt naming a subdirectory script fails", not g.ok and "top-level" in g.detail)
    (res / "fake.json").unlink()
    shutil.rmtree(code / "sub")

    cases = {
        "03_analysis/code/03_envkey.py": "from analysis.results import write_results\nwrite_results('k', {'environment': 1})\n",
        "03_analysis/code/04_nan.py": "from analysis.results import write_results\nwrite_results('nan', {'x': float('nan')})\n",
        "03_analysis/code/05_nan.R": R_HELPER + 'write_results(list(x = NaN), "nanr")\n',
        "05_figures/code/fig.R": R_HELPER + 'write_results(list(x = 1), "fromfig")\n',
        "02_data/acquisition/a.py": "from analysis.results import write_results\nwrite_results('other', {'x': 1})\n",
        "02_data/acquisition/a.R": R_HELPER + 'write_results(list(x = 1), "other")\n',
        "03_analysis/code/sub/run2.py": "from analysis.results import write_results\nwrite_results('subpy', {'x': 1})\n",
        "03_analysis/code/sub/run2.R": R_HELPER + 'write_results(list(x = 1), "subr")\n',
        "03_analysis/code/06_env.R": R_HELPER + 'write_results(list(x = 1, e = new.env()), "unser")\n',
    }
    for rel, text in cases.items():
        (P / rel).parent.mkdir(parents=True, exist_ok=True)
        (P / rel).write_text(text, encoding="utf-8")
    codes = {rel: _wf("run-script", rel, env=env, cwd=tmp) for rel in cases}
    written = [n for n in ("k", "nan", "nanr", "fromfig", "other", "subpy", "subr", "unser")
               if (res / f"{n}.json").exists() or (res / f"{n}.json.tmp").exists()]
    record("writers refuse a top-level environment key, NaN, wrong directories and acquisition names",
           all(c.returncode != 0 for c in codes.values()) and not written,
           f"rc={[c.returncode for c in codes.values()]} written={written}")
    record("the acquisition refusal names the rule",
           "acquisition writes raw files verbatim" in _out(codes["02_data/acquisition/a.py"])
           and "acquisition writes raw files verbatim" in _out(codes["02_data/acquisition/a.R"]))
    record("subdirectory scripts are refused with 'only top-level'",
           "only top-level" in _out(codes["03_analysis/code/sub/run2.py"])
           and "only top-level" in _out(codes["03_analysis/code/sub/run2.R"]))
    a1 = _wf("run-script", "03_analysis/code/01_py.py", "extra", env=env, cwd=tmp)
    a2 = _wf("run-script", "03_analysis/code/02_r.R", "extra", env=env, cwd=tmp)
    record("analysis scripts run with arguments are refused",
           a1.returncode != 0 and a2.returncode != 0 and "without arguments" in _out(a1)
           and "without arguments" in _out(a2))
    for rel in cases:
        (P / rel).unlink()
    shutil.rmtree(code / "sub", ignore_errors=True)
    (P / "02_data/acquisition/s.py").write_text(
        "from analysis.results import write_results\nwrite_results('dataset_summary', {'n_rows': 3})\n",
        encoding="utf-8")
    ok_acq = _wf("run-script", "02_data/acquisition/s.py", env=env, cwd=tmp)
    record("acquisition may write dataset_summary", ok_acq.returncode == 0
           and (res / "dataset_summary.json").is_file(), _out(ok_acq)[-100:])
    (res / "dataset_summary.json").unlink()
    (code / "lib").mkdir()
    (code / "lib/h.py").write_text(
        "from analysis.results import write_results\ndef go():\n    write_results('viahelper', {'x': 2})\n",
        encoding="utf-8")
    (code / "07_main.py").write_text(
        "import sys, os\nsys.path.insert(0, os.path.dirname(__file__))\nfrom lib.h import go\ngo()\n",
        encoding="utf-8")
    h = _wf("run-script", "03_analysis/code/07_main.py", env=env, cwd=tmp)
    record("a helper module called from a top-level script may write results",
           h.returncode == 0 and (res / "viahelper.json").is_file(), _out(h)[-120:])
    (code / "07_main.py").unlink()
    (res / "viahelper.json").unlink()
    shutil.rmtree(code / "lib")

    def scoped(rel: str, text: str, patterns=None):
        (P / rel).parent.mkdir(parents=True, exist_ok=True)
        (P / rel).write_text(text, encoding="utf-8")
        r = _gate("paper_scripts_scoped", P, patterns=patterns or [
            "02_data/acquisition/**/*.py", "02_data/acquisition/**/*.R",
            "03_analysis/code/**/*.py", "03_analysis/code/**/*.R",
            "05_figures/code/**/*.R"])
        (P / rel).unlink()
        return r
    r1 = scoped("03_analysis/code/w1.R", R_HELPER + 'jsonlite::write_json(x, "a.json")\n')
    r2 = scoped("03_analysis/code/w2.R", R_HELPER + "y <- toJSON(x)\n")
    r3 = scoped("03_analysis/code/w3.R", R_HELPER + "# toJSON(x)\ny <- jsonlite::fromJSON('a.json')\n")
    record("R scripts may not write JSON directly; comments and fromJSON are fine",
           not r1.ok and not r2.ok and "writes JSON directly" in r1.detail and r3.ok, r3.detail[:100])
    r4 = scoped("05_figures/code/f.R", 'source(file.path(Sys.getenv("MEDPAPER_ROOT"), "tools/figures/R/medfig.R"))\n')
    r5 = scoped("03_analysis/code/analysis.py", "from wfcore.paths import project_dir\np = project_dir()\n")
    record("sourcing medfig.R scopes an R script; analysis.py shadows the engine package",
           r4.ok and not r5.ok and "shadows the engine package" in r5.detail, r4.detail[:80])
    (code / "analysis").mkdir()
    (code / "analysis/__init__.py").write_text("", encoding="utf-8")
    r6 = _gate("paper_scripts_scoped", P, patterns=["03_analysis/code/*.py"])
    shutil.rmtree(code / "analysis")
    (P / "05_figures/code/Figures").mkdir(parents=True)
    (P / "05_figures/code/Figures/a.txt").write_text("x", encoding="utf-8")
    r7 = _gate("paper_scripts_scoped", P, patterns=["03_analysis/code/*.py"])
    shutil.rmtree(P / "05_figures/code/Figures")
    (code / "lib").mkdir()
    r8 = _gate("paper_scripts_scoped", P, patterns=["03_analysis/code/*.py"])
    (code / "lib").rmdir()
    record("package directories shadowing engine packages fail; lib/ passes",
           not r6.ok and not r7.ok and "shadows" in r7.detail and r8.ok, r8.detail[:80])
    absolute = [scoped("03_analysis/code/a1.R", R_HELPER + 'd <- read.csv("C:/data/x.csv")\n'),
                scoped("03_analysis/code/a2.py", "from wfcore.paths import project_dir\np = project_dir()\nopen(r'\\\\server\\share\\x')\n"),
                scoped("03_analysis/code/a3.py", "from wfcore.paths import project_dir\np = project_dir()\nx = '/home/u/x.csv'\n"),
                scoped("03_analysis/code/a4.py", "from wfcore.paths import project_dir\np = project_dir()\nimport pandas as pd\nname = 'x'\npd.read_csv(f'C:/data/{name}.csv')\n")]
    fine = [scoped("03_analysis/code/b1.R", R_HELPER + 'p <- paste0(a, "/", b)\nq <- gsub("/+$", "", p)\nu <- "https://example.org/a/b"\n# "C:/data/x.csv"\n'),
            scoped("02_data/acquisition/b2.py", "from wfcore.paths import project_dir\np = project_dir()\nu = '/esearch.fcgi/x/'\n")]
    record("absolute path literals in re-executed code are refused (f-strings included)",
           all(not r.ok and "absolute path literal" in r.detail for r in absolute)
           and all(r.ok for r in fine), " | ".join(r.detail[:60] for r in absolute + fine))

    from wfcore.state import State
    st = State(P, ".wf").load()
    st.data["pipeline_origin_version"] = "1.3.0"
    st.save()
    r9 = scoped("03_analysis/code/w9.R", R_HELPER + 'jsonlite::write_json(x, "a.json")\n')
    record("legacy origin 1.3.0 does not soften the R JSON rule", not r9.ok and r9.severity == "fail")

    (P / "07_manuscript").mkdir(exist_ok=True)
    (P / "07_manuscript/x.md").write_text("# Results\n\nWe enrolled 20240917 participants using version 4.5.\n", encoding="utf-8")
    n1 = _gate("numbers_have_provenance", P, stage="S09_results", path="07_manuscript/x.md")
    (P / "07_manuscript/x.md").write_text("# Results\n\nThe HR was 1.87 in 1284 participants.\n", encoding="utf-8")
    n2 = _gate("numbers_have_provenance", P, stage="S09_results", path="07_manuscript/x.md")
    record("the environment receipt never counts as number provenance; the payload does",
           not n1.ok and n2.ok, n1.detail[:80] + " | " + n2.detail[:60])


def run_reproduce(tmp: Path) -> None:
    import json as _json
    section("analysis re-execution (reproduce.py, analysis_reproduces)")
    if not shutil.which("Rscript"):
        record("reproduce: Rscript available", False, "Rscript missing")
        return
    P = _new_paper(tmp / "repro")
    (P / "02_data/raw").mkdir(parents=True)
    (P / "02_data/raw/data.csv").write_text("x,y\n1,2\n2,4\n3,7\n", encoding="utf-8")
    acq = P / "02_data/acquisition/fetch.py"
    acq.parent.mkdir(parents=True)
    acq.write_text("from pathlib import Path\nPath('ACQ_RAN').write_text('x')\nraise SystemExit(9)\n",
                   encoding="utf-8")
    code = P / "03_analysis/code"
    (code / "lib").mkdir(parents=True)
    (code / "lib/helper.py").write_text("def slope(xs, ys):\n    return sum(ys) / sum(xs)\n", encoding="utf-8")
    (code / "01_clean.py").write_text(
        "from wfcore.paths import project_dir\nP = project_dir()\n"
        "(P / '02_data/derived').mkdir(parents=True, exist_ok=True)\n"
        "(P / '02_data/derived/clean.csv').write_text((P / '02_data/raw/data.csv').read_text())\n",
        encoding="utf-8")
    model = ("import sys, os, random\nsys.path.insert(0, os.path.dirname(__file__))\n"
             "from lib.helper import slope\nfrom wfcore.paths import project_dir\n"
             "from analysis.results import set_seed, write_results\nset_seed(7)\n"
             "rows = (project_dir() / '02_data/derived/clean.csv').read_text().split()[1:]\n"
             "xs = [int(r.split(',')[0]) for r in rows]; ys = [int(r.split(',')[1]) for r in rows]\n"
             "write_results('primary', {'slope': slope(xs, ys), 'n': len(xs), 'draw': random.random(), "
             "'meta': {'timestamp': 'fixed'}})\n")
    (code / "02_model.py").write_text(model, encoding="utf-8")
    (code / "03_r.R").write_text(R_HELPER + "medpaper_seed(3)\nwrite_results(list(u = runif(1)), \"r_res\")\n",
                                 encoding="utf-8")
    env = _env(MEDPAPER_PROJECT=P)
    for s in ("01_clean.py", "02_model.py", "03_r.R"):
        _wf("run-script", f"03_analysis/code/{s}", env=env, cwd=tmp)
    # acquisition-written dataset_summary with a real receipt
    ds = {"n_rows": 3, "environment": {"schema": 1, "language": "python", "version": "3.13",
          "packages": {}, "seed": None, "script": "02_data/acquisition/fetch.py",
          "script_sha256": _sha(acq), "written_at": "2026-01-01T00:00:00Z",
          "writer": "tools/analysis/results.py"}}
    (P / "03_analysis/results/dataset_summary.json").write_text(_json.dumps(ds), encoding="utf-8")
    (P / "03_analysis/notes.md").write_text("notes\n", encoding="utf-8")
    RP = [sys.executable, ROOT / "tools/reproduce.py"]

    def snapshot():
        return {p.relative_to(P).as_posix(): _sha(p) for p in P.rglob("*") if p.is_file()
                and not p.relative_to(P).as_posix().startswith((".wf/", "03_analysis/reproducibility_report"))}
    before = snapshot()
    r = _run([*RP, "run", "--project", P], cwd=tmp)
    report = P / "03_analysis/reproducibility_report.json"
    rep = _json.loads(report.read_text(encoding="utf-8")) if report.is_file() else {}
    statuses = {e["file"]: e["status"] for e in rep.get("results", [])}
    record("reproduce.py run re-executes and matches", r.returncode == 0 and rep.get("all_match") is True
           and len(rep.get("scripts", [])) == 3
           and statuses.get("03_analysis/results/dataset_summary.json") == "not_rerun_acquisition"
           and not (P / "ACQ_RAN").exists(), _out(r)[-200:])
    record("the run changed nothing in the paper except the report and .wf/repro",
           snapshot() == before and "do not edit the paper" in r.stdout)
    rerun = P / ".wf/repro/rerun"
    record("re-run evidence is retained with matching hashes",
           all(e.get("rerun_sha256") == _sha(rerun / Path(e["file"]).name)
               for e in rep.get("results", []) if e.get("rerun_sha256")) and rerun.is_dir())
    inputs = [i["path"] for i in rep.get("inputs", [])]
    record("inputs include helpers and raw data, never derived/ or caches",
           "03_analysis/code/lib/helper.py" in inputs and "02_data/raw/data.csv" in inputs
           and not any(i.startswith("02_data/derived") or "__pycache__" in i for i in inputs))
    g = _gate("analysis_reproduces", P, stage="S06_protocol_final")
    record("analysis_reproduces passes after a clean run", g.ok, g.detail[:120])
    (P / "03_analysis/notes.md").write_text("notes edited\n", encoding="utf-8")
    (P / "00_input").mkdir(exist_ok=True)
    (P / "00_input/author_info.json").write_text("{}", encoding="utf-8")
    g2 = _gate("analysis_reproduces", P, stage="S06_protocol_final")
    record("prose and 00_input edits do not invalidate the proof", g2.ok, g2.detail[:100])

    helper = code / "lib/helper.py"
    old = helper.read_text(encoding="utf-8")
    helper.write_text(old + "# edit\n", encoding="utf-8")
    g = _gate("analysis_reproduces", P, stage="S06_protocol_final")
    record("N: editing a helper invalidates the proof",
           not g.ok and "input changed since the proof: 03_analysis/code/lib/helper.py" in g.detail)
    helper.write_text(old, encoding="utf-8")
    m = code / "02_model.py"
    m.write_text(model + "# comment\n", encoding="utf-8")
    g = _gate("analysis_reproduces", P, stage="S06_protocol_final")
    record("N: editing an analysis script invalidates the proof", not g.ok)
    m.write_text(model, encoding="utf-8")
    pj = P / "03_analysis/results/primary.json"
    orig = pj.read_text(encoding="utf-8")
    pj.write_text(orig.replace('"n": 3', '"n": 4'), encoding="utf-8")
    g = _gate("analysis_reproduces", P, stage="S06_protocol_final")
    record("N: editing a results value invalidates the proof", not g.ok)
    pj.write_text(orig, encoding="utf-8")
    ret = rerun / "primary.json"
    rorig = ret.read_text(encoding="utf-8")
    ret.write_text(rorig.replace('"n": 3', '"n": 5'), encoding="utf-8")
    g = _gate("analysis_reproduces", P, stage="S06_protocol_final")
    record("N: editing the retained re-run evidence fails",
           not g.ok and "retained re-run evidence missing or edited" in g.detail)
    ret.write_text(rorig, encoding="utf-8")

    # cwd outside the paper and inside a subfolder both write the paper's own report
    report.unlink()
    r2 = _run([*RP, "run", "--project", P], cwd=P / "03_analysis")
    record("the report is anchored to --project, whatever the cwd",
           r2.returncode == 0 and report.is_file()
           and not (P / "03_analysis/03_analysis").exists(), _out(r2)[-100:])

    bad = [_run([*RP, "run", "--timeout", t, "--project", P], cwd=tmp).returncode
           for t in ("0", "-5", "nan", "90000")]
    record("invalid --timeout values are refused", all(c == 1 for c in bad), str(bad))

    unseeded = model.replace("set_seed(7)\n", "random.seed()\n")
    m.write_text(unseeded, encoding="utf-8")
    _wf("run-script", "03_analysis/code/02_model.py", env=env, cwd=tmp)
    r3 = _run([*RP, "run", "--project", P], cwd=tmp)
    rep3 = _json.loads(report.read_text(encoding="utf-8"))
    prim = next(e for e in rep3["results"] if e["file"].endswith("primary.json"))
    record("N: an unseeded script is reported as a mismatch at its JSON path",
           r3.returncode == 2 and prim["status"] == "mismatch" and prim["first_difference"] == "$.draw",
           str(prim.get("first_difference")))
    for e in rep3["results"]:
        e["status"] = "match" if e["status"] == "mismatch" else e["status"]
        e["first_difference"] = None
    rep3["all_match"] = True
    report.write_text(_json.dumps(rep3), encoding="utf-8")
    g = _gate("analysis_reproduces", P, stage="S06_protocol_final")
    record("N: a forged report cannot turn a mismatch into a pass",
           not g.ok and "report claims match" in g.detail and "$.draw" in g.detail, g.detail[:160])
    m.write_text(model, encoding="utf-8")
    _wf("run-script", "03_analysis/code/02_model.py", env=env, cwd=tmp)

    tol = P / "03_analysis/reproducibility.toml"
    tol.write_text('schema = 1\n[[tolerance]]\nfile = "03_analysis/results/primary.json"\nabs = 1e-8\nrel = 0.0\nreason = "too short"\n', encoding="utf-8")
    r4 = _run([*RP, "run", "--project", P], cwd=tmp)
    tol.write_text('schema = 1\n[[tolerance]]\nfile = "03_analysis/results/primary.json"\nabs = 1e-3\nrel = 0.0\nreason = "bootstrap reduction order varies between runs on this machine"\n', encoding="utf-8")
    r5 = _run([*RP, "run", "--project", P], cwd=tmp)
    record("N: a short reason or a tolerance above 1e-6 is refused", r4.returncode == 1 and
           r5.returncode == 1 and "above 1e-6" in r5.stdout, r5.stdout[-100:])
    tol.unlink()

    escape = code / "04_escape.py"
    escape.write_text("import os\nfrom pathlib import Path\nfrom wfcore.paths import project_dir\n"
                      "Path(os.environ['ORIG_PAPER'], 'x.txt').write_text('x')\n", encoding="utf-8")
    r6 = _run([*RP, "run", "--project", P], env=_env(ORIG_PAPER=P), cwd=tmp)
    rep6 = _json.loads(report.read_text(encoding="utf-8"))
    record("N: a script writing into the original paper is caught",
           r6.returncode == 2 and rep6.get("paper_changes") == ["x.txt"], str(rep6.get("paper_changes")))
    escape.unlink()
    (P / "x.txt").unlink(missing_ok=True)
    failing = code / "05_fail.py"
    failing.write_text("raise SystemExit(1)\n", encoding="utf-8")
    r7 = _run([*RP, "run", "--project", P], cwd=tmp)
    rep7 = _json.loads(report.read_text(encoding="utf-8"))
    g = _gate("analysis_reproduces", P, stage="S06_protocol_final")
    record("N: a failing script is recorded and the gate fails",
           r7.returncode == 2 and rep7.get("failed_script") == "03_analysis/code/05_fail.py" and not g.ok)
    failing.unlink()
    r8 = _run([*RP, "run", "--project", P], cwd=tmp)
    g = _gate("analysis_reproduces", P, stage="S23_package")
    record("the gate passes again after a clean re-run (S23 declaration)", r8.returncode == 0 and g.ok,
           g.detail[:100])
    record("without a manifest the filename order is used and flagged",
           _json.loads(report.read_text(encoding="utf-8")).get("order_source") == "filename"
           and "FILENAME order" in r8.stdout)

    # ---- 1.7.1: declared order and scoped re-execution ---------------------
    man = P / "03_analysis/analysis_manifest.json"
    C = "03_analysis/code/"
    entries = [
        {"path": C + "03_r.R", "outputs": ["03_analysis/results/r_res.json"]},
        {"path": C + "02_model.py", "inputs": ["02_data/derived/clean.csv"],
         "outputs": ["03_analysis/results/primary.json"]},
        {"path": C + "01_clean.py", "inputs": ["02_data/raw/data.csv"],
         "outputs": ["02_data/derived/clean.csv"]}]
    man.write_text(_json.dumps({"schema": 1, "scripts": entries}), encoding="utf-8")
    from wfcore import reproproof as _rpf
    order, src, probs = _rpf.ordered_scripts(P)
    names = [p.name for p in order]
    record("the manifest's input/output edges order the scripts, not their names",
           src == "manifest" and not probs and names.index("01_clean.py") < names.index("02_model.py"),
           str(names))
    man.write_text(_json.dumps({"schema": 1, "scripts": entries[:2]}), encoding="utf-8")
    r9 = _run([*RP, "run", "--project", P], cwd=tmp)
    record("N: a manifest that omits a top-level script is refused",
           r9.returncode == 1 and "is not listed" in r9.stdout, r9.stdout[-160:])
    cyc = [dict(entries[0], after=[C + "02_model.py"]), dict(entries[1], after=[C + "03_r.R"]),
           entries[2]]
    man.write_text(_json.dumps({"schema": 1, "scripts": cyc}), encoding="utf-8")
    r9 = _run([*RP, "run", "--project", P], cwd=tmp)
    record("N: a dependency cycle is refused", r9.returncode == 1 and "cycle" in r9.stdout,
           r9.stdout[-160:])
    man.write_text(_json.dumps({"schema": 1, "scripts": entries}), encoding="utf-8")
    r10 = _run([*RP, "run", "--project", P], cwd=tmp)
    rep10 = _json.loads(report.read_text(encoding="utf-8"))
    record("a full run follows the manifest order",
           r10.returncode == 0 and rep10.get("order_source") == "manifest"
           and [s["path"] for s in rep10["scripts"]].index(C + "01_clean.py")
           < [s["path"] for s in rep10["scripts"]].index(C + "02_model.py"), _out(r10)[-160:])
    rs = code / "03_r.R"
    rs_old = rs.read_text(encoding="utf-8")
    rs.write_text(rs_old + "# comment only\n", encoding="utf-8")
    _wf("run-script", "03_analysis/code/03_r.R", env=env, cwd=tmp)
    r11 = _run([*RP, "run", "--affected-only", "--project", P], cwd=tmp)
    rep11 = _json.loads(report.read_text(encoding="utf-8"))
    carried_rows = {s["path"] for s in rep11["scripts"] if s.get("carried")}
    g = _gate("analysis_reproduces", P, stage="S06_protocol_final")
    record("--affected-only re-runs only the changed script and carries the rest",
           r11.returncode == 0 and rep11.get("mode") == "affected-only"
           and carried_rows == {C + "01_clean.py", C + "02_model.py"}
           and "03_analysis/results/primary.json" in rep11.get("carried_results", {}), _out(r11)[-200:])
    record("the gate accepts a scoped proof whose carried evidence is intact", g.ok, g.detail[:160])
    (P / "02_data/raw/data.csv").write_text("x,y\n1,2\n2,4\n3,7\n\n", encoding="utf-8")
    r12 = _run([*RP, "run", "--affected-only", "--project", P], cwd=tmp)
    rep12 = _json.loads(report.read_text(encoding="utf-8"))
    record("a data change reaches every script (nothing carried)",
           not any(s.get("carried") for s in rep12["scripts"]), _out(r12)[-200:])
    (P / "02_data/raw/data.csv").write_text("x,y\n1,2\n2,4\n3,7\n", encoding="utf-8")
    rs.write_text(rs_old, encoding="utf-8")
    _wf("run-script", "03_analysis/code/03_r.R", env=env, cwd=tmp)
    man.unlink()
    _run([*RP, "run", "--project", P], cwd=tmp)
    report.unlink()
    g = _gate("analysis_reproduces", P, stage="S06_protocol_final")
    record("N: a missing report fails", not g.ok)


def _r_script(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        'source(file.path(Sys.getenv("MEDPAPER_ROOT"), "tools/figures/R/medfig.R"))\n'
        'source(file.path(Sys.getenv("MEDPAPER_ROOT"), "tools/figures/R/recipes.R"))\n'
        "suppressPackageStartupMessages(library(patchwork))\n" + body, encoding="utf-8")


def run_r_figures(tmp: Path) -> None:
    import json as _json
    import struct
    import zlib
    section("R figures: save_medpaper renders what qc.py judges")
    if not shutil.which("Rscript"):
        record("R figures: Rscript available", False, "Rscript missing; R is the default figure engine")
        return
    from figures import qc
    P = _new_paper(tmp / "figpaper")
    (P / "03_analysis/results").mkdir(parents=True)
    (P / "03_analysis/results/primary.json").write_text(_json.dumps(
        {"hr": 1.87, "hr_low": 1.20, "hr_high": 2.91, "p": 0.00021}), encoding="utf-8")
    plan = {"main_figures": [
        {"id": "Figure 1", "archetype": "km_survival", "width": "single",
         "file": "05_figures/out/Figure1.png", "tiff": "05_figures/out/Figure1.tiff"},
        {"id": "Figure 2", "archetype": "forest_plot", "width": "double",
         "file": "05_figures/out/Figure2.png", "tiff": "05_figures/out/Figure2.tiff"},
        {"id": "Figure 3", "archetype": "box_jitter", "width": "double",
         "file": "05_figures/out/Figure3.png", "tiff": "05_figures/out/Figure3.tiff"}],
        "supp_figures": []}
    (P / "01_protocol").mkdir(exist_ok=True)
    (P / "01_protocol/artifact_plan.json").write_text(_json.dumps(plan), encoding="utf-8")
    _r_script(P / "05_figures/code/fig_r.R", r'''
res <- jsonlite::fromJSON(medpaper_path("03_analysis/results/primary.json"), simplifyVector = FALSE)
set.seed(1)
dat <- data.frame(time = rexp(150, 0.05), status = rbinom(150, 1, 0.7), arm = sample(c("A", "B"), 150, TRUE))
source(file.path(Sys.getenv("MEDPAPER_ROOT"), "tools/R/medresults.R"))
km <- curve_table_km(survival::survfit(survival::Surv(time, status) ~ arm, data = dat), times = c(0, 10, 20, 30))
p1 <- recipe_km(curve = km, times = c(0, 10, 20, 30), hr = res$hr, hr_ci = c(res$hr_low, res$hr_high), p = res$p)
save_medpaper(p1, "05_figures/out/Figure1", width = "single")
g1 <- tryCatch({ recipe_km(dat, "time", "status", "arm", times = c(0, 10, 20, 30)); "none" }, error = function(e) conditionMessage(e))
dna <- dat; dna$time[1:3] <- NA
g2 <- tryCatch({ recipe_km(dna, "time", "status", "arm", times = c(0, 10, 20, 30), refit = TRUE, analysis_n = 150); "none" }, error = function(e) conditionMessage(e))
g3 <- attr(recipe_km(dna, "time", "status", "arm", times = c(0, 10, 20, 30), refit = TRUE, analysis_n = 147), "medpaper_population")
cat("REFIT_GUARD", grepl("off by default", g1), grepl("N = 147 complete cases", g2), g3$n_dropped_na == 3 && g3$n_used == 147, "\n")
rows <- data.frame(label = c("Overall", "Age < 65", "Age >= 65", "Women"), estimate = c(res$hr, 1.5, 2.1, 1.7),
                   ci_low = c(res$hr_low, 0.9, 1.3, 1.0), ci_high = c(res$hr_high, 2.5, 3.4, 2.9))
save_medpaper(recipe_forest(rows), "05_figures/out/Figure2", width = "double", height_mm = 60)
fa <- ggplot(mtcars, aes(wt, mpg)) + geom_point() + facet_wrap(~cyl) + labs(x = "Weight", y = "MPG") + theme_medpaper()
fb <- ggplot(mtcars, aes(factor(cyl), mpg)) + geom_boxplot() + geom_jitter(width = 0.1) + labs(x = "Cylinders", y = "MPG") + theme_medpaper()
save_medpaper(fa + fb + plot_layout(widths = c(3, 1)) + plot_annotation(tag_levels = "A"), "05_figures/out/Figure3", width = "double", height_mm = 70, archetype = "box_jitter")
q <- ggplot(mtcars, aes(wt, mpg, colour = factor(cyl))) + geom_point() + labs(x = "Weight", y = "MPG", colour = "Cylinders") + theme_medpaper() + theme(legend.position = "top")
save_medpaper(q, "05_figures/out/Single", width = "single")
library(survival)
fit <- ggsurvfit::survfit2(Surv(time, status) ~ arm, data = dat)
raw <- ggsurvfit::ggsurvfit(fit) + ggsurvfit::add_censor_mark() + ggsurvfit::add_risktable() + theme_medpaper()
save_medpaper(raw, "05_figures/out/RawKM", width = "single", archetype = "km_survival")
d2 <- data.frame(time = rexp(150, 0.05), status = factor(sample(c("censor", "event", "death"), 150, TRUE), levels = c("censor", "event", "death")), arm = sample(c("A", "B"), 150, TRUE))
save_medpaper(recipe_cif(d2, "time", "status", "arm", times = c(0, 10, 20, 30), refit = TRUE, analysis_n = 150), "05_figures/out/CIF", width = "single")
ci <- tidycmprsk::cuminc(survival::Surv(time, status) ~ arm, data = d2)
save_medpaper(recipe_cif(curve = curve_table_cif(ci, "event", times = c(0, 10, 20, 30)), times = c(0, 10, 20, 30)), "temp/CIFtab", width = "single")
w <- tryCatch({ medpaper_palette("nejm"); "none" }, warning = function(w) conditionMessage(w))
w2 <- tryCatch({ medpaper_palette("okabe_ito"); "none" }, warning = function(w) conditionMessage(w))
same <- identical(suppressWarnings(medpaper_palette("nature")), suppressWarnings(medpaper_palette("npg")))
cat("PALETTE_WARN", grepl("red/green", w), "OKABE_WARN", w2 != "none", "NATURE_NPG", same, "\n")
cat("RISKY", paste(sort(.MF_RISKY), collapse = ","), "\n")
cat("TMPPNG", length(list.files(tempdir(), "\\.png$")), "\n")
t <- medpaper_targets(); cat("TARGETS", t$column_width_mm_single, t$column_width_mm_double, t$column_width_mm_1_5, "\n")
''')
    env = _env(MEDPAPER_PROJECT=P)
    p = _wf("run-script", "05_figures/code/fig_r.R", env=env, cwd=tmp)
    out_dir = P / "05_figures/out"
    record("a real Rscript render through wf run-script succeeds", p.returncode == 0, _out(p)[-300:])

    def png_size(path: Path):
        b = path.read_bytes()
        return struct.unpack(">II", b[16:24])
    def png_pixels(path: Path) -> bytes:
        b = path.read_bytes(); i = 8; data = b""; ihdr = b""
        while i < len(b):
            n = struct.unpack(">I", b[i:i + 4])[0]; kind = b[i + 4:i + 8]
            if kind == b"IHDR":
                ihdr = b[i + 8:i + 8 + n]
            if kind == b"IDAT":
                data += b[i + 8:i + 8 + n]
            i += 12 + n
        return ihdr + zlib.decompress(data)
    def tiff_info(path: Path):
        b = path.read_bytes()
        end = "<" if b[:2] == b"II" else ">"
        off = struct.unpack(end + "I", b[4:8])[0]
        n = struct.unpack(end + "H", b[off:off + 2])[0]
        tags = {}
        for k in range(n):
            e = b[off + 2 + 12 * k: off + 14 + 12 * k]
            tag, typ, cnt = struct.unpack(end + "HHI", e[:8])
            val = struct.unpack(end + ("H" if typ == 3 else "I"), e[8:10] if typ == 3 else e[8:12])[0]
            tags[tag] = val
        return tags

    if p.returncode == 0:
        w1, _ = png_size(out_dir / "Figure1.png")
        w2, _ = png_size(out_dir / "Figure2.png")
        record("PNG width is the physical column width at 600 dpi (within 1 px)",
               abs(w1 - 90 / 25.4 * 600) < 1 and abs(w2 - 180 / 25.4 * 600) < 1, f"{w1}, {w2}")
        tags = tiff_info(out_dir / "Figure1.tiff")
        record("TIFF master exists, same width, LZW compressed",
               tags.get(256) == w1 and tags.get(259) == 5, str({k: tags.get(k) for k in (256, 259)}))
    side = {n: _json.loads((P / f"05_figures/qc/{n}.artist.json").read_text(encoding="utf-8"))
            for n in ("Figure1", "Figure2", "Figure3", "Single", "RawKM", "CIF")
            if (P / f"05_figures/qc/{n}.artist.json").is_file()}
    record("sidecar keys are qc.SIDECAR_KEYS plus engine = R, at 05_figures/qc/<stem>.artist.json",
           len(side) == 6 and all(set(s) == set(qc.SIDECAR_KEYS) | set(qc.SIDECAR_OPTIONAL_KEYS)
                                  and s["engine"] == "R"
                                  and s["figure"] == n for n, s in side.items())
           and not (P / "05_figures/qc/05_figures").exists(), str(list(side)))
    from figures import elements as el
    record("every sidecar carries all 25 detector keys",
           all(set(el.DETECTORS) <= set(s["elements"]) for s in side.values()))
    n_axes = {n: s["n_axes"] for n, s in side.items()}
    record("n_axes is measured from the grob tree (single 1, facet+box 4, recipe_km 2, raw ggsurvfit 3)",
           n_axes.get("Single") == 1 and n_axes.get("Figure3") == 4 and n_axes.get("Figure1") == 2
           and n_axes.get("RawKM") == 3, str(n_axes))
    record("no positive R fixture reports a panel overlap",
           not any(s["axes_tightbbox_overlaps"] for s in side.values()),
           str({n: s["axes_tightbbox_overlaps"][:1] for n, s in side.items() if s["axes_tightbbox_overlaps"]}))
    e1, er, ec = side.get("Figure1", {}).get("elements", {}), side.get("RawKM", {}).get("elements", {}), side.get("CIF", {}).get("elements", {})
    record("KM elements are detected for recipe_km and raw ggsurvfit + add_risktable",
           all(e1.get(k, {}).get("found") for k in ("step_curve", "censoring_marks", "risk_table", "legend_present", "figure_statistics"))
           and all(er.get(k, {}).get("found") for k in ("step_curve", "censoring_marks", "risk_table")),
           str({k: er.get(k, {}).get("found") for k in ("step_curve", "censoring_marks", "risk_table")}))
    record("recipe_cif finds its step curve and risk table",
           ec.get("step_curve", {}).get("found") and ec.get("risk_table", {}).get("found"))
    pop1, popc = side.get("Figure1", {}).get("population", {}), side.get("CIF", {}).get("population", {})
    record("recipe_km draws the exported curve table and records its population in the sidecar",
           pop1.get("mode") == "results" and pop1.get("n_used") == 150 == pop1.get("analysis_n"),
           str(pop1))
    record("refit is opt-in, refuses an N that differs from results, and records NA rows dropped",
           "REFIT_GUARD TRUE TRUE TRUE" in p.stdout and popc.get("mode") == "refit"
           and popc.get("n_used") == 150,
           [l for l in p.stdout.splitlines() if l.startswith("REFIT")].__str__() + str(popc))
    tab = P / "temp/qc/CIFtab.artist.json"
    tabpop = _json.loads(tab.read_text(encoding="utf-8")).get("population", {}) if tab.is_file() else {}
    record("recipe_cif draws an exported cuminc table without refitting",
           tabpop.get("mode") == "results" and tabpop.get("n_used") == 150, str(tabpop))
    (P / "03_analysis/results/km.json").write_text(_json.dumps({"n": 150, "km": {"n": 150}}),
                                                     encoding="utf-8")
    pp_ok = qc.population_problems({"mode": "results", "n_used": 150, "analysis_n": 150},
                                   ["03_analysis/results/km.json"], P)
    pp_bad = qc.population_problems({"mode": "refit", "n_used": 147, "analysis_n": 150},
                                    ["03_analysis/results/km.json"], P)
    pp_absent = qc.population_problems({"mode": "refit", "n_used": 140, "analysis_n": 140},
                                       ["03_analysis/results/km.json"], P)
    record("qc flags a figure N that differs from, or is absent in, its source results",
           not pp_ok and any("analysis N is 150" in x for x in pp_bad)
           and any("not an N recorded" in x for x in pp_absent), str((pp_ok, pp_bad, pp_absent)))
    (P / "03_analysis/results/km.json").unlink()
    record("palettes: nejm warns, okabe_ito does not, nature == npg, risky set parity",
           "PALETTE_WARN TRUE OKABE_WARN FALSE NATURE_NPG TRUE" in p.stdout
           and f"RISKY {','.join(sorted(__import__('figures.style', fromlist=['x']).RISKY_PAIRS | {'npg'}))}" in p.stdout,
           [l for l in p.stdout.splitlines() if l.startswith(("PALETTE", "RISKY"))].__str__())
    record("the audit device leaves no PNG in R's tempdir", "TMPPNG 0" in p.stdout)

    q = _run([sys.executable, ROOT / "tools/figures/qc.py", "--all"], env=env, cwd=P)
    rep = _json.loads((P / "05_figures/qc/qc_report.json").read_text(encoding="utf-8")) if (P / "05_figures/qc/qc_report.json").is_file() else {"figures": []}
    figs = {f["id"]: {c["name"]: c for c in f["checks"]} for f in rep["figures"]}
    wanted = ("not_clipped", "no_excess_whitespace", "margins_symmetric", "artist_audit_schema",
              "min_font_size", "min_line_width", "no_panel_overlap", "no_text_clipped",
              "no_missing_glyphs", "no_tick_label_collision", "no_interior_void")
    bad = {fid: [n for n in wanted if not c.get(n, {}).get("ok")] for fid, c in figs.items()}
    bad = {k: v for k, v in bad.items() if v}
    record("qc.py --all passes every R figure (pixel margins included)",
           q.returncode == 0 and len(figs) == 3 and not bad, str(bad)[:300] + _out(q)[-200:] if bad or q.returncode else "")
    record("element:figure_statistics passes for recipe_km and recipe_forest",
           figs.get("Figure 1", {}).get("element:figure_statistics", {}).get("ok")
           and figs.get("Figure 2", {}).get("element:figure_statistics", {}).get("ok")
           and figs.get("Figure 2", {}).get("element:null_line", {}).get("ok")
           and figs.get("Figure 2", {}).get("element:error_bars", {}).get("ok"))
    record("element checks for km_survival all pass",
           all(figs.get("Figure 1", {}).get(f"element:{k}", {}).get("ok") for k in
               ("step_curve", "censoring_marks", "risk_table", "legend_present", "figure_statistics")))

    # determinism and width parity
    _r_script(P / "05_figures/code/again.R", 'p <- ggplot(mtcars, aes(wt, mpg)) + geom_point() + labs(x = "W", y = "M") + theme_medpaper()\n'
              'save_medpaper(p, "05_figures/out/Det1", width = "single")\nsave_medpaper(p, "05_figures/out/Det2", width = "single")\n')
    _wf("config", "set", "column_width_mm_single", "85", env=env, cwd=tmp)
    pa = _wf("run-script", "05_figures/code/again.R", env=env, cwd=tmp)
    if pa.returncode == 0:
        record("rendering the same plot twice gives identical pixels",
               png_pixels(out_dir / "Det1.png") == png_pixels(out_dir / "Det2.png"))
        wd, _ = png_size(out_dir / "Det1.png")
        record("width parity: column_width_mm_single = 85 renders 85 mm at 600 dpi",
               abs(wd - 85 / 25.4 * 600) < 1, str(wd))
        with __import__("unittest.mock", fromlist=["patch"]).patch.dict(os.environ, {"MEDPAPER_PROJECT": str(P)}):
            from wfcore import registry
            tg = registry.effective_targets(P)
            res_e = qc.qc_figure({"id": "D", "file": "05_figures/out/Det1.png", "width": "single",
                                  "tiff": "05_figures/out/Det1.tiff"}, tg, qc.load_archetypes())
        record("qc's effective dpi uses the paper's column width (~600, not ~567)",
               abs(res_e["effective_dpi"] - 600) < 2, str(res_e["effective_dpi"]))
    else:
        record("determinism render", False, _out(pa)[-200:])
    _wf("config", "set", "column_width_mm_single", "90", env=env, cwd=tmp)

    # known-defect negatives, one Rscript run
    _r_script(P / "05_figures/code/defects.R", r'''
base <- ggplot(mtcars, aes(wt, mpg)) + geom_point() + labs(x = "Weight", y = "MPG")
save_medpaper(base + theme_medpaper() + theme(axis.text = element_text(size = 4)), "05_figures/out/Font", width = "single")
save_medpaper(base + theme_medpaper() + theme(axis.line = element_line(linewidth = pt_to_linewidth(0.2))), "05_figures/out/Line", width = "single")
save_medpaper(base + theme_medpaper() + coord_cartesian(clip = "off") + annotate("text", x = 30, y = 20, hjust = 0, label = "far outside label"), "05_figures/out/Clip", width = "single")
bars <- data.frame(g = c("a", "b", "c"), v = c(70, 80, 90))
save_medpaper(ggplot(bars, aes(g, v)) + geom_col() + coord_cartesian(ylim = c(50, 100)) + labs(x = "G", y = "V") + theme_medpaper(), "05_figures/out/Base", width = "single")
save_medpaper(base + theme_medpaper() + annotate("text", x = 3, y = 30, label = "\u4e2d"), "05_figures/out/Glyph", width = "single")
lab <- data.frame(g = paste("a very long category label", 1:30), v = 1:30)
save_medpaper(ggplot(lab, aes(g, v)) + geom_point() + labs(x = "G", y = "V") + theme_medpaper(), "05_figures/out/Tick", width = "single")
save_medpaper(base + theme_medpaper() + inset_element(base + theme_medpaper(), 0.3, 0.3, 0.9, 0.9), "05_figures/out/Inset", width = "single")
save_medpaper(ggplot(data.frame(t = c(0, 1, 2, 3), s = c(1, 0.8, 0.6, 0.5)), aes(t, s)) + geom_step() + labs(x = "T", y = "S") + theme_medpaper(), "05_figures/out/NoRisk", width = "single", archetype = "km_survival")
nums <- ggplot(mtcars, aes(wt, mpg)) + geom_point() + labs(x = "Weight", y = "Miles") + theme_medpaper()
save_medpaper(nums, "05_figures/out/TicksOnly", width = "single")
''')
    pd_ = _wf("run-script", "05_figures/code/defects.R", env=env, cwd=tmp)
    expected = {"Font": "min_font_size", "Line": "min_line_width", "Clip": "no_text_clipped",
                "Base": "bar_baseline_zero", "Glyph": "no_missing_glyphs",
                "Tick": "no_tick_label_collision", "Inset": "no_panel_overlap",
                "NoRisk": "element:risk_table"}
    missed = []
    with __import__("unittest.mock", fromlist=["patch"]).patch.dict(os.environ, {"MEDPAPER_PROJECT": str(P)}):
        from wfcore import registry
        tg = registry.effective_targets(P)
        arch = qc.load_archetypes()
        for stem, check in expected.items():
            entry = {"id": stem, "file": f"05_figures/out/{stem}.png", "width": "single",
                     "tiff": f"05_figures/out/{stem}.tiff",
                     "archetype": "km_survival" if stem == "NoRisk" else None}
            r = qc.qc_figure(entry, tg, arch)
            c = {x["name"]: x for x in r["checks"]}
            if c.get(check, {}).get("ok", True):
                missed.append(stem)
    record("known R defects are each caught by qc.py (font, line, clipping, baseline, glyph, ticks, overlap, risk table)",
           pd_.returncode == 0 and not missed, f"missed={missed} " + _out(pd_)[-200:])
    ticks_only = _json.loads((P / "05_figures/qc/TicksOnly.artist.json").read_text(encoding="utf-8")) if (P / "05_figures/qc/TicksOnly.artist.json").is_file() else {}
    record("tick labels never count as figure statistics",
           ticks_only.get("elements", {}).get("figure_statistics", {}).get("found") is False)

    # the normaliser is what makes margins pass: a raw agg_png render fails margins_symmetric
    raw = P / "05_figures/code/raw.R"
    raw.write_text('library(ggplot2)\nPROJECT <- Sys.getenv("MEDPAPER_PROJECT")\n'
                   'p <- ggplot(mtcars, aes(wt, mpg)) + geom_point() + theme_classic(7) + theme(plot.margin = margin(1.3, 1.3, 1.3, 1.3, "mm"))\n'
                   'ragg::agg_png(file.path(PROJECT, "05_figures/out/Raw.png"), width = 90, height = 64.8, units = "mm", res = 600, background = "white")\n'
                   'print(p)\ninvisible(dev.off())\n', encoding="utf-8")
    pr = _wf("run-script", "05_figures/code/raw.R", env=env, cwd=tmp)
    if (P / "05_figures/qc/Single.artist.json").is_file():
        hand = dict(side.get("Single", {}))
        hand["figure"] = "Raw"
        (P / "05_figures/qc/Raw.artist.json").write_text(_json.dumps(hand), encoding="utf-8")
    with __import__("unittest.mock", fromlist=["patch"]).patch.dict(os.environ, {"MEDPAPER_PROJECT": str(P)}):
        r = qc.qc_figure({"id": "Raw", "file": "05_figures/out/Raw.png", "width": "single"}, tg, arch)
    c = {x["name"]: x for x in r["checks"]}
    record("N: the same plot rendered without save_medpaper fails margins_symmetric",
           pr.returncode == 0 and c.get("margins_symmetric", {}).get("ok") is False,
           c.get("margins_symmetric", {}).get("detail", _out(pr)[-100:]))

    # refusals: nothing written
    refusals = {
        "outside": 'save_medpaper(ggplot(), "../outside/X")\n',
        "engine": f'save_medpaper(ggplot(), "{ROOT.as_posix()}/tools/X")\n',
        "alias": 'save_medpaper(ggplot(), "project/05_figures/out/X")\n',
        "character": 'recipe_km(data.frame(time = 1:5, status = 1, arm = "a"), "time", "status", "arm", times = 0:4, hr = "1.87")\n',
        "gtable": 'save_medpaper(ggplotGrob(ggplot()), "05_figures/out/G")\n',
        "palette": 'medpaper_palette("rainbow")\n',
    }
    rc = {}
    for k, body in refusals.items():
        _r_script(P / f"05_figures/code/ref_{k}.R", body)
        rc[k] = _wf("run-script", f"05_figures/code/ref_{k}.R", env=env, cwd=tmp).returncode
    _r_script(P / "05_figures/code/ref_unset.R", 'save_medpaper(ggplot(), "05_figures/out/U")\n')
    unset = _run(["Rscript", P / "05_figures/code/ref_unset.R"],
                 env=_env(MEDPAPER_ROOT=ROOT, MEDPAPER_PROJECT=None), cwd=tmp)
    rc["unset"] = unset.returncode
    _r_script(P / "05_figures/code/ref_inengine.R", 'save_medpaper(ggplot(), "05_figures/out/E")\n')
    ie = _run(["Rscript", P / "05_figures/code/ref_inengine.R"],
              env=_env(MEDPAPER_ROOT=ROOT, MEDPAPER_PROJECT=ROOT / "project"), cwd=tmp)
    rc["MEDPAPER_PROJECT in engine"] = ie.returncode
    fake = tmp / "fake_r_engine"
    (fake / "pipeline").mkdir(parents=True)
    (fake / "pipeline/pipeline.toml").write_text("[targets]\n", encoding="utf-8")
    only_recipes = P / "05_figures/code/ref_recipes.R"
    only_recipes.write_text(f'source("{ROOT.as_posix()}/tools/figures/R/recipes.R")\n'
                            'save_medpaper(ggplot(), "05_figures/out/F")\n', encoding="utf-8")
    fr = _run(["Rscript", only_recipes], env=_env(MEDPAPER_ROOT=fake, MEDPAPER_PROJECT=ROOT / "x"), cwd=tmp)
    rc["recipes.R with fake MEDPAPER_ROOT"] = fr.returncode
    mr = P / "05_figures/code/ref_results.R"
    mr.write_text(f'source("{ROOT.as_posix()}/tools/R/medresults.R")\nwrite_results(list(a = 1), "z")\n', encoding="utf-8")
    rc["write_results into engine"] = _run(["Rscript", mr], env=_env(MEDPAPER_ROOT=fake, MEDPAPER_PROJECT=ROOT / "x"), cwd=tmp).returncode
    stray = [n for n in ("X", "G", "U", "E", "F") if (out_dir / f"{n}.png").exists()]
    record("save_medpaper/recipes/write_results refuse bad stems, the engine, strings, gtables, unknown palettes",
           all(v != 0 for v in rc.values()) and not stray and not (ROOT / "project").exists()
           and not (ROOT / "x").exists() and not (P / "05_figures/outside").exists()
           and not (tmp / "figpaper/../outside").exists(), f"{rc} stray={stray}")
    record("no Rplots.pdf is left in the paper or the cwd",
           not (P / "Rplots.pdf").exists() and not (tmp / "Rplots.pdf").exists())

    # Python sidecar schema and engine policy
    with __import__("unittest.mock", fromlist=["patch"]).patch.dict(os.environ, {"MEDPAPER_PROJECT": str(P)}):
        legacy = dict(side.get("Single", {}))
        legacy.pop("engine", None)
        legacy["figure"] = "Single"
        (P / "05_figures/qc/Single.artist.json").write_text(_json.dumps(legacy), encoding="utf-8")
        r = qc.qc_figure({"id": "S", "file": "05_figures/out/Single.png", "width": "single"}, tg, arch)
        c = {x["name"]: x for x in r["checks"]}
        legacy_ok = c.get("artist_audit_schema", {}).get("ok") and c.get("engine_matches_policy", {}).get("severity") == "warn"
        broken = dict(legacy); broken.pop("interior_voids")
        (P / "05_figures/qc/Single.artist.json").write_text(_json.dumps(broken), encoding="utf-8")
        r = qc.qc_figure({"id": "S", "file": "05_figures/out/Single.png", "width": "single"}, tg, arch)
        miss = not {x["name"]: x for x in r["checks"]}["artist_audit_schema"]["ok"]
        extra = dict(legacy); extra["surprise"] = 1
        (P / "05_figures/qc/Single.artist.json").write_text(_json.dumps(extra), encoding="utf-8")
        r = qc.qc_figure({"id": "S", "file": "05_figures/out/Single.png", "width": "single"}, tg, arch)
        ext = not {x["name"]: x for x in r["checks"]}["artist_audit_schema"]["ok"]
    record("a legacy sidecar without engine passes the schema and only warns on engine policy", bool(legacy_ok))
    record("N: a sidecar missing a key or with an extra key fails artist_audit_schema", miss and ext)

    # 1.6.0: render receipt, vector master, staged publish and warn = 2
    section("R figures: render receipt, PDF master, failed render keeps the old figure")
    prov_entry = {"id": "Figure S1", "file": "05_figures/out/Prov.png", "width": "single",
                  "tiff": "05_figures/out/Prov.tiff", "script": "05_figures/code/prov.R",
                  "source_results": ["03_analysis/results/primary.json"]}
    plan2 = dict(plan, supp_figures=[prov_entry])
    (P / "01_protocol/artifact_plan.json").write_text(_json.dumps(plan2), encoding="utf-8")
    _r_script(P / "05_figures/code/prov.R",
              'res <- jsonlite::fromJSON(medpaper_path("03_analysis/results/primary.json"))\n'
              'p <- ggplot(data.frame(x = 1:5, y = c(2, 3, 5, 4, res$hr)), aes(x, y)) + geom_point() +'
              ' labs(x = "X", y = "Y") + theme_medpaper()\n'
              'save_medpaper(p, "05_figures/out/Prov", width = "single")\n')
    pp = _wf("run-script", "05_figures/code/prov.R", env=env, cwd=tmp)
    prov_side = (_json.loads((P / "05_figures/qc/Prov.artist.json").read_text(encoding="utf-8"))
                 if (P / "05_figures/qc/Prov.artist.json").is_file() else {})
    record("save_medpaper records script, script_sha256, source_hashes and render_hashes",
           pp.returncode == 0 and prov_side.get("script") == "05_figures/code/prov.R"
           and set(prov_side.get("source_hashes", {})) == {"03_analysis/results/primary.json"}
           and {"05_figures/out/Prov.png", "05_figures/out/Prov.tiff", "05_figures/out/Prov.pdf"}
           <= set(prov_side.get("render_hashes", {})), _out(pp)[-200:])
    pdf_path = out_dir / "Prov.pdf"
    record("a vector PDF master is written beside PNG/TIFF",
           pdf_path.is_file() and pdf_path.read_bytes()[:4] == b"%PDF")

    def prov_check():
        with __import__("unittest.mock", fromlist=["patch"]).patch.dict(
                os.environ, {"MEDPAPER_PROJECT": str(P)}):
            r = qc.qc_figure(prov_entry, tg, arch)
        return {x["name"]: x for x in r["checks"]}.get("r_render_provenance", {})
    record("an unchanged render passes r_render_provenance", prov_check().get("ok") is True,
           prov_check().get("detail", ""))
    res_path = P / "03_analysis/results/primary.json"
    original = res_path.read_bytes()
    res_path.write_bytes(original + b"\n")
    c = prov_check()
    record("N: a changed result file fails r_render_provenance",
           c.get("ok") is False and "result changed" in c.get("detail", ""), c.get("detail", ""))
    res_path.write_bytes(original)
    script_path = P / "05_figures/code/prov.R"
    script_text = script_path.read_text(encoding="utf-8")
    script_path.write_text(script_text + "# edited\n", encoding="utf-8")
    c = prov_check()
    record("N: an edited plotting script fails r_render_provenance",
           c.get("ok") is False and "script changed" in c.get("detail", ""), c.get("detail", ""))
    script_path.write_text(script_text, encoding="utf-8")

    before = (out_dir / "Prov.png").read_bytes()
    _r_script(P / "05_figures/code/prov_bad.R",
              'p <- ggplot(data.frame(x = c(1, 2, NA), y = c(1, 2, 3)), aes(x, y)) + geom_point() +'
              ' labs(x = "X", y = "Y") + theme_medpaper()\n'
              'save_medpaper(p, "05_figures/out/Prov", width = "single")\n')
    pb = _wf("run-script", "05_figures/code/prov_bad.R", env=env, cwd=tmp)
    record("N: a ggplot warning (rows silently dropped) fails the render (warn = 2)",
           pb.returncode != 0, _out(pb)[-160:])
    record("a failed render keeps the previous figure byte-identical and leaves no staging files",
           (out_dir / "Prov.png").read_bytes() == before
           and not list(out_dir.glob("*.render-tmp.*")), str(list(out_dir.glob("*render-tmp*"))))
    (P / "01_protocol/artifact_plan.json").write_text(_json.dumps(plan), encoding="utf-8")


def run_v160(tmp: Path) -> None:
    """1.6.0: live-reference cache, gate stop + receipts, freeze binding, renderer rule,
    R provenance check, P thresholds, reader-review coverage."""
    import copy
    import time
    from unittest.mock import patch

    from wfcore import gatecache, gates, liverefs, readerreview, refproof, registry, scifreeze
    from wfcore import checks as checks_mod
    from wfcore.checks import Ctx, get, load_all
    from wfcore.checks import numbers as nums
    from wfcore.state import State

    load_all()
    pipe = registry.load()

    # ---- PubMed live-verification cache ---------------------------------------------------
    section("1.6.0 live PubMed check: hash-bound 24 h reuse, S13/S25 always live")
    P = _new_paper(tmp / "liverefs")
    refs = P / "06_refs"
    (refs / "cache").mkdir(parents=True)
    key, pmid, doi = "smith2025cache", "40123457", "10.1000/cache-doi"
    title = "Caching independent reference verification"
    abstract = "Independent live verification results were reused within a freshness window."
    raw = f"""<?xml version="1.0" encoding="UTF-8"?>
<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>{pmid}</PMID><Article>
<ArticleTitle>{title}</ArticleTitle>
<Abstract><AbstractText>{abstract}</AbstractText></Abstract>
<AuthorList><Author><LastName>Smith</LastName><ForeName>Alice</ForeName></Author></AuthorList>
<Journal><JournalIssue><PubDate><Year>2025</Year></PubDate></JournalIssue><Title>Journal of Evidence Integrity</Title></Journal>
<ELocationID EIdType="doi">{doi}</ELocationID><PublicationTypeList><PublicationType>Journal Article</PublicationType></PublicationTypeList>
</Article></MedlineCitation><PubmedData><ArticleIdList><ArticleId IdType="doi">{doi}</ArticleId></ArticleIdList></PubmedData>
</PubmedArticle></PubmedArticleSet>"""
    entry = {"citekey": key, "pmid": pmid, "doi": doi, "title": title, "abstract": abstract,
             "authors": [{"last": "Smith", "first": "Alice"}],
             "journal": "Journal of Evidence Integrity", "year": "2025", "source": "pubmed"}
    lib_path = refs / "library.json"
    lib_path.write_text(json.dumps({"entries": [entry]}, indent=2), encoding="utf-8")
    vrel = "06_refs/cache/verify_efetch_pubmed_fixture.xml"
    (P / vrel).write_text(raw, encoding="utf-8")
    source = refproof.parse_pubmed_payload(raw)[pmid]
    (refs / "verified.json").write_text(json.dumps({
        "schema": refproof.SCHEMA,
        "generator": {"tool": refproof.GENERATOR, "mode": "fresh_ncbi_pubmed_efetch",
                      "source": "NCBI PubMed EFetch"},
        "verified_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "strict": False, "library_sha256": refproof.file_sha256(lib_path),
        "n_entries": 1, "n_verified": 1,
        "records": {key: {"verified": True, "via": "pubmed", "pmid": pmid, "doi": doi,
                          "evidence": {"source": refproof.SOURCE, "cache_file": vrel,
                                       "payload_sha256": refproof.file_sha256(P / vrel),
                                       "record_sha256": refproof.record_sha256(source),
                                       "fresh_fetch": True}}}}, indent=2), encoding="utf-8")
    grel = "06_refs/cache/gate_efetch_pubmed_fixture.xml"
    (P / grel).write_text(raw, encoding="utf-8")
    live = {"pmid": pmid, "doi": doi, "title": title, "abstract": abstract,
            "authors": [{"last": "Smith", "first": "Alice"}],
            "journal": "Journal of Evidence Integrity", "year": "2025", "flags": [],
            "cache_file": grel}
    st = State(P, ".wf").load()

    def prov(stage_id: str):
        return get("reference_provenance")(Ctx(pipeline=pipe, state=st, project=P,
                                               stage=pipe.stage(stage_id),
                                               spec={"check": "reference_provenance",
                                                     "live": True}))
    offline = patch("pubmed.eutils.efetch", side_effect=OSError("NCBI unreachable"))
    with patch("pubmed.eutils.efetch", return_value=[live]) as fetch:
        first = prov("S14_introduction")
    record("cache miss: the live gate fetches, passes and stores a hash-bound receipt",
           first.ok and fetch.call_count == 1 and (P / liverefs.REL).is_file(), first.detail[:100])
    with offline:
        hit = prov("S16_discussion")
    record("cache hit: an unchanged library passes from the receipt without NCBI",
           hit.ok and "reused" in hit.detail, hit.detail[:100])
    with offline:
        forced = [prov(s) for s in ("S13_reflib", "S25_submission_audit")]
    record("S13 and S25 never use the cache (forced live, fail closed offline)",
           all(not r.ok and "failed closed" in r.detail for r in forced),
           "; ".join(r.detail[:50] for r in forced))
    changed = dict(entry, title=title + " revisited")
    record("a changed library entry misses the cache",
           liverefs.cached_sources(P, [changed]) is None
           and liverefs.cached_sources(P, [entry]) is not None)
    receipt = json.loads((P / liverefs.REL).read_text(encoding="utf-8"))
    (P / grel).write_text(raw.replace(title, title + "!"), encoding="utf-8")
    tampered = liverefs.cached_sources(P, [entry]) is None
    (P / grel).write_text(raw, encoding="utf-8")
    receipt["at"] = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    (P / liverefs.REL).write_text(json.dumps(receipt), encoding="utf-8")
    record("a tampered gate XML or an expired (>24 h) receipt misses the cache",
           tampered and liverefs.cached_sources(P, [entry]) is None)
    record("a mocked record without a gate EFetch payload cannot seed the cache",
           liverefs.store_sources(P, [dict(live, cache_file="")]) is False)
    record("the receipt lives in the paper's .wf/, never in the engine",
           liverefs.REL.startswith(".wf/") and not (ROOT / ".wf").exists())

    # ---- gate stop + receipts ---------------------------------------------------------------
    section("1.6.0 gates: stop after missing outputs, 120 s receipts for pure checks only")
    G = _new_paper(tmp / "gates")
    gst = State(G, ".wf").load()
    stage = copy.copy(pipe.stage("S02_feasibility"))
    (G / "notes.md").write_text("# A\n\nx\n\n# B\n\ny\n", encoding="utf-8")
    stage.gate = [{"check": "outputs_exist"},
                  {"check": "md_sections", "path": "notes.md", "headings": ["A", "B"]},
                  {"check": "reference_provenance", "live": True}]
    res = gates.run_stage(pipe, gst, G, stage)
    record("a missing output stops the gate; dependents are reported pending, not run",
           [r.check for r in res] == ["outputs_exist", "dependent_checks_pending"]
           and res[-1].blocking, str([r.check for r in res]))
    from wfcore import cli
    record("pending dependents cannot be forced past",
           "dependent_checks_pending" in cli.NON_OVERRIDABLE_GATES)
    stage.gate = [{"check": "md_sections", "path": "notes.md", "headings": ["A", "B"]}]
    calls = {"n": 0}
    real = checks_mod.REGISTRY["md_sections"]

    def counting(ctx):
        calls["n"] += 1
        return real(ctx)
    with patch.dict(checks_mod.REGISTRY, {"md_sections": counting}):
        r1 = gates.run_stage(pipe, gst, G, stage, record=True)
        r2 = gates.run_stage(pipe, gst, G, stage, reuse=True)
        reused_once = calls["n"] == 1
        (G / "notes.md").write_text("# A\n\nx changed\n\n# B\n\ny\n", encoding="utf-8")
        r3 = gates.run_stage(pipe, gst, G, stage, reuse=True)
    record("wf check -> wf advance reuses an unchanged pure-check PASS",
           r1[0].ok and r2[0].ok and reused_once, f"calls={calls}")
    record("a changed input re-executes the check (content-hash identity)",
           r3[0].ok and calls["n"] == 2, f"calls={calls}")
    rc = gatecache.Receipts(G, pipe, gst)
    never = ("reference_provenance", "scientific_freeze_intact", "decision_recorded",
             "s19_review_release_explicit", "data_acquisition_complete", "analysis_reproduces",
             "bundle_matches_freeze", "reader_review_coverage")
    record("integrity, approval, freeze and live checks are never cached",
           all(rc.identity(stage, {"check": c}) is None for c in never))
    ov = gst.dir / "overrides.toml"
    id_before = rc.identity(stage, stage.gate[0])
    ov.write_text("schema = 1\n", encoding="utf-8")
    record("the identity includes the paper's overrides fingerprint",
           gatecache.Receipts(G, pipe, gst).identity(stage, stage.gate[0]) != id_before)
    ov.unlink()
    data = json.loads((gst.dir / gatecache.REL).read_text(encoding="utf-8"))
    for row in data.values():
        row["at"] = time.time() - gatecache.TTL_SECONDS - 1
    (gst.dir / gatecache.REL).write_text(json.dumps(data), encoding="utf-8")
    with patch.dict(checks_mod.REGISTRY, {"md_sections": counting}):
        gates.run_stage(pipe, gst, G, stage, reuse=True)
    record("an expired receipt (> 120 s) re-executes", calls["n"] == 3, f"calls={calls}")

    # ---- freeze after S19 ---------------------------------------------------------------------
    section("1.6.0 freeze: missing after S19 fails, bound to the S19 approval")
    F = _new_paper(tmp / "freeze")
    for rel, text in (("07_manuscript/full_manuscript.md", "# Results\n\n412 patients.\n"),
                      ("06_refs/refs.bib", "@article{a, title={x}}\n"),
                      ("06_refs/library.json", '{"entries": []}'),
                      ("03_analysis/results/primary.json", '{"n": 412}')):
        (F / rel).parent.mkdir(parents=True, exist_ok=True)
        (F / rel).write_text(text, encoding="utf-8")

    def intact():
        fst = State(F, ".wf").load()
        return get("scientific_freeze_intact")(Ctx(pipeline=pipe, state=fst, project=F,
                                                   stage=pipe.stage("S20_journal"),
                                                   spec={"check": "scientific_freeze_intact"}))
    record("before S19 a missing freeze still passes (upstream paper)", intact().ok)
    fst = State(F, ".wf").load()
    fst.stage_info("S19_human_review")["status"] = "done"
    fst.save()
    r = intact()
    record("N: S19 done but no freeze fails (no silent pass)",
           not r.ok and "S19 is complete" in r.detail, r.detail[:100])
    pkg = F / "07_manuscript/review_packages"
    pkg.mkdir(parents=True)
    (pkg / "latest_review_package.json").write_text(
        json.dumps({"package_id": "abcdef1234567890"}), encoding="utf-8")
    fst = State(F, ".wf").load()
    fst.record_decision("manuscript_human_reviewed", "NO_FURTHER_REVIEW",
                        "user: no further review needed for v001")
    scifreeze.write_freeze(F)
    r = intact()
    record("N: a freeze whose package ID the approval does not name fails",
           not r.ok and "abcdef123456" in r.detail, r.detail[:100])
    fst = State(F, ".wf").load()
    fst.record_decision("manuscript_human_reviewed", "NO_FURTHER_REVIEW",
                        "user: no further review needed for v001 abcdef123456")
    scifreeze.write_freeze(F, force=True)
    record("a freeze bound to the named S19 package passes", intact().ok, intact().detail[:100])
    fst = State(F, ".wf").load()
    fst.data["decisions"].pop("manuscript_human_reviewed")
    fst.save()
    record("N: a freeze without a NO_FURTHER_REVIEW decision fails", not intact().ok)

    # ---- renderer rule ----------------------------------------------------------------------
    section("1.6.0 artifact plan: a non-R figure must say why")
    A = _new_paper(tmp / "plan")

    def plan_with(**fig):
        base = {"id": "Figure 1", "title": "t", "content": "c", "width": "single",
                "archetype": "box_jitter", "file": "05_figures/out/Figure1.png",
                "source_results": ["03_analysis/results/x.json"],
                "script": "05_figures/code/fig1.R"}
        base.update(fig)
        (A / "01_protocol").mkdir(exist_ok=True)
        (A / "01_protocol/artifact_plan.json").write_text(json.dumps(
            {"main_figures": [base], "main_tables": [], "supp_figures": [],
             "supp_tables": []}), encoding="utf-8")
        return _gate("artifact_plan_sane", A, stage="S07_artifacts")
    arch_ok = plan_with()
    record("an R figure under the R default needs no reason", arch_ok.ok, arch_ok.detail[:100])
    r = plan_with(script="05_figures/code/fig1.py")
    record("N: a Python figure without renderer_reason fails",
           not r.ok and "renderer_reason" in r.detail, r.detail[:100])
    r = plan_with(script="05_figures/code/fig1.py", renderer="Python", renderer_reason="short")
    record("N: a reason under 20 characters fails", not r.ok)
    r = plan_with(script="05_figures/code/fig1.py", renderer="Python",
                  renderer_reason="approved forest plot from the confirmed Python model; kept")
    record("an approved Python figure with a concrete reason passes", r.ok, r.detail[:100])
    r = plan_with(script="05_figures/code/fig1.R", renderer="Python",
                  renderer_reason="approved forest plot from the confirmed Python model; kept")
    record("N: a declared renderer that contradicts the script extension fails", not r.ok)
    record("the invariant keeps approved Python figures instead of refitting in R",
           any("never refit" in inv for inv in pipe.policy.get("invariants", [])))

    # ---- R provenance in qc.py (no R needed) ---------------------------------------------------
    section("1.6.0 qc.py: R render receipt and PNG-hash visual binding")
    from figures import qc as figqc
    import matplotlib.pyplot as plt
    Q = _new_paper(tmp / "qcprov")
    for sub in ("05_figures/out", "05_figures/qc", "05_figures/code", "03_analysis/results"):
        (Q / sub).mkdir(parents=True, exist_ok=True)
    fig = plt.figure(figsize=(3.54, 2.5), dpi=200)
    fig.add_subplot(111).plot([0, 1], [0, 1])
    fig.savefig(str(Q / "05_figures/out/Fig.png"))
    plt.close(fig)
    (Q / "05_figures/code/fig.R").write_text("# draws Fig\n", encoding="utf-8")
    (Q / "03_analysis/results/r.json").write_text('{"x": 1}', encoding="utf-8")
    from wfcore.packagefreeze import _sha256
    from figures import elements as el
    side = {"figure": "Fig", "archetype": None, "engine": "R", "n_axes": 1, "min_font_pt": 7,
            "max_font_pt": 8, "min_line_pt": 0.6, "text_clipped_at_edge": [],
            "axes_tightbbox_overlaps": [], "glyph_warnings": [], "tick_label_collisions": [],
            "interior_voids": [], "elements": {k: {"found": False, "evidence": ""}
                                               for k in el.DETECTORS},
            "figure_text": [], "script": "05_figures/code/fig.R",
            "script_sha256": _sha256(Q / "05_figures/code/fig.R"),
            "source_hashes": {"03_analysis/results/r.json": _sha256(Q / "03_analysis/results/r.json")},
            "render_hashes": {"05_figures/out/Fig.png": _sha256(Q / "05_figures/out/Fig.png")}}
    (Q / "05_figures/qc/Fig.artist.json").write_text(json.dumps(side), encoding="utf-8")
    qentry = {"id": "Fig", "file": "05_figures/out/Fig.png", "width": "single",
              "script": "05_figures/code/fig.R", "source_results": ["03_analysis/results/r.json"]}

    def provenance(entry_=qentry):
        with patch.dict(os.environ, {"MEDPAPER_PROJECT": str(Q)}):
            out = figqc.qc_figure(entry_, registry.effective_targets(Q), {})
        return {c["name"]: c for c in out["checks"]}.get("r_render_provenance", {})
    record("a matching R render receipt passes", provenance().get("ok") is True,
           provenance().get("detail", ""))
    (Q / "03_analysis/results/r.json").write_text('{"x": 2}', encoding="utf-8")
    record("N: a result changed after rendering fails r_render_provenance",
           provenance().get("ok") is False)
    (Q / "03_analysis/results/r.json").write_text('{"x": 1}', encoding="utf-8")
    record("N: plan source_results that differ from the receipt fail",
           provenance(dict(qentry, source_results=["03_analysis/results/other.json"]))
           .get("ok") is False)
    record("N: a different plotting script than the plan fails",
           provenance(dict(qentry, script="05_figures/code/other.R")).get("ok") is False)
    legacy = {k: v for k, v in side.items() if k not in figqc.PROVENANCE_KEYS}
    (Q / "05_figures/qc/Fig.artist.json").write_text(json.dumps(legacy), encoding="utf-8")
    c = provenance()
    record("a legacy R sidecar without a receipt only warns", c.get("ok") is False
           and c.get("severity") == "warn")
    with patch.dict(os.environ, {"MEDPAPER_PROJECT": str(Q)}):
        sha = figqc._png_sha256("05_figures/out/Fig.png")
        same = figqc._same_render({"png_sha256": sha}, sha, 1.0)
        differs = figqc._same_render({"png_sha256": sha}, "0" * 64, 1.0)
        legacy_ok = figqc._same_render({"png_mtime": 5.0}, sha, 5.0)
    record("visual review is bound to the PNG SHA-256 (legacy reports fall back to mtime)",
           same and not differs and legacy_ok)

    # ---- P thresholds and signs ---------------------------------------------------------------
    section("1.6.0 numbers: P thresholds and signs are checked, not scrubbed")
    conv = nums.CONVENTIONS
    record("P<0.001 with no result below 0.001 is an offender",
           nums._offenders("Mortality differed (P<0.001).", {0.03}, {"0.03"}, set(conv))
           == [(1, "P<0.001")])
    record("P<0.001 backed by p = 0.00021 passes",
           not nums._offenders("Mortality differed (P<0.001).", {0.00021}, {"0.00021"},
                               set(conv)))
    record("a formatted '<0.001' written by the analysis itself counts as provenance",
           not nums._offenders("P<0.001", {0.001}, {"0.001"}, set(conv),
                               stated={("<", "0.001")}))
    record("a table cell '<0.001' is checked like P<0.001",
           nums._offenders("<0.001", {0.2}, {"0.2"}, set(conv)) == [(1, "P<0.001")])
    record("U+2212 minus and hyphen-minus are the same number",
           not nums._offenders("change \u22120.42 units", {-0.42}, {"-0.42"}, set(conv)))
    record("N: a flipped sign is an offender",
           nums._offenders("change -0.42 units", {0.42}, {"0.42"}, set(conv)) == [(1, "-0.42")])
    record("display precision uses Decimal (0.80 matches 0.8, 0.781 not 0.79)",
           not nums._offenders("AUC 0.80", {0.8}, {"0.8"}, set())
           and nums._offenders("AUC 0.79", {0.781}, {"0.781"}, set()) == [(1, "0.79")])
    record("CONVENTIONS are kept (not emptied)", {"95", "0.05", "1"} <= conv)

    # ---- S18 reader-review coverage -------------------------------------------------------------
    section("1.6.0 S18: the independent review is bound to the rendered figures")
    Rv = _new_paper(tmp / "reader")
    for rel, data in (("07_manuscript/full_manuscript.md", "# Results\n\ntext\n"),
                      ("05_figures/legends.md", "# Figure legends\n"),
                      ("04_tables/table_captions.md", "# Table captions\n"),
                      ("05_figures/out/Figure1.png", "png-bytes"),
                      ("04_tables/main/Table1.xlsx", "xlsx-bytes")):
        (Rv / rel).parent.mkdir(parents=True, exist_ok=True)
        (Rv / rel).write_text(data, encoding="utf-8")
    (Rv / "01_protocol").mkdir(exist_ok=True)
    (Rv / "01_protocol/artifact_plan.json").write_text(json.dumps({
        "main_figures": [{"id": "Figure 1", "file": "05_figures/out/Figure1.png"}],
        "main_tables": [{"id": "Table 1", "file": "04_tables/main/Table1.xlsx"}]}),
        encoding="utf-8")
    body = ("A clinician can follow the cohort definition, the primary comparison and what "
            "Figure 1 encodes without the text; the y-axis units need stating.")
    med = ("Terminology and abbreviations are standard; the figure presents absolute risks "
           "with intervals and denominators, which is appropriate for this population.")

    def write_review(block: str, rc_text=body, mp_text=med):
        (Rv / readerreview.REVIEW_REL).write_text(
            f"# Verdict\n\nREVISE\n\n{block}\n\n## Reader comprehension\n\n{rc_text}\n\n"
            f"## Medical presentation\n\n{mp_text}\n", encoding="utf-8")

    def coverage():
        return _gate("reader_review_coverage", Rv, stage="S18_independent_review")
    write_review(readerreview.evidence_block(Rv))
    r = coverage()
    record("a review bound to the current manuscript, tables and figures passes", r.ok, r.detail[:100])
    record("the inventory includes the rendered figure",
           "05_figures/out/Figure1.png" in readerreview.reader_inputs(Rv))
    (Rv / "05_figures/out/Figure1.png").write_text("re-rendered", encoding="utf-8")
    r = coverage()
    record("N: a figure re-rendered after the review fails", not r.ok and "Figure1.png" in r.detail,
           r.detail[:100])
    write_review(readerreview.evidence_block(Rv), rc_text="PASS")
    record("N: a one-word Reader comprehension section fails", not coverage().ok)
    write_review("no evidence block")
    record("N: a review without the reviewed_artifacts block fails", not coverage().ok)
    toml_text = (ROOT / "pipeline/pipeline.toml").read_text(encoding="utf-8")
    s18 = next(s for s in __import__("tomllib").loads(toml_text)["stage"]
               if s["id"] == "S18_independent_review")
    record("reader_review_coverage is wired into the S18 gate and card",
           any(g["check"] == "reader_review_coverage" for g in s18["gate"])
           and "reader-inputs" in (ROOT / "pipeline/stages/S18_independent_review.md")
           .read_text(encoding="utf-8"))
    record("pipeline version is 1.8.0", pipe.meta.get("version") == "1.8.0")


def run_v170(tmp: Path) -> None:
    """1.7.0 scoped rework: collect -> seal -> fix in place -> check; no stage-tail rewind."""
    import json as _json
    from wfcore import registry, revision as rv, dependencies as deps
    from wfcore.checks import Ctx, get, load_all
    from wfcore.state import State
    section("1.7.0 scoped rework: one sealed batch, affected gates only, drift caught")
    pipe = registry.load()
    tmp.mkdir(parents=True, exist_ok=True)
    rework = ROOT / "tools/rework.py"
    acc = ["The requested change is visible in the source", "Nothing unrelated changed"]

    def paper(name: str, at: str) -> tuple[Path, State]:
        P = tmp / name
        P.mkdir(parents=True)
        st = State(P, ".wf").create(pipe.meta["name"], pipe.meta["version"], at)
        for s in pipe.stages:
            if s.index < pipe.stage(at).index:
                st.stage_info(s.id)["status"] = "done"
        st.stage_info(at)["status"] = "active"
        st.record_decision("manuscript_human_reviewed", "NO_FURTHER_REVIEW",
                           "The fixture user approved the scientific manuscript at S19.")
        st.save()
        files = {
            "07_manuscript/methods.md": "# Methods\n\nOriginal methods.\n",
            "07_manuscript/discussion.md": "# Discussion\n\nOriginal discussion.\n",
            "07_manuscript/introduction.md": "# Introduction\n\nOriginal introduction.\n",
            "06_refs/verified.json": '{"checked": 1}\n',
            "03_analysis/code/primary.py": "print('primary')\n",
            "03_analysis/code/secondary.py": "print('secondary')\n",
            "03_analysis/results/primary.json": _json.dumps(
                {"hr": 1.5, "environment": {"script": "03_analysis/code/primary.py"}}),
            "03_analysis/results/secondary.json": _json.dumps(
                {"hr": 0.9, "environment": {"script": "03_analysis/code/secondary.py"}}),
            "05_figures/code/fig1.R": "# fig1\n", "05_figures/code/fig2.R": "# fig2\n",
            "05_figures/out/Figure1.png": "old figure 1", "05_figures/out/Figure2.png": "old figure 2",
            "01_protocol/artifact_plan.json": _json.dumps({"main_figures": [
                {"id": "Figure 1", "file": "05_figures/out/Figure1.png",
                 "script": "05_figures/code/fig1.R",
                 "source_results": ["03_analysis/results/primary.json"]},
                {"id": "Figure 2", "file": "05_figures/out/Figure2.png",
                 "script": "05_figures/code/fig2.R",
                 "source_results": ["03_analysis/results/secondary.json"]}],
                "supp_figures": [], "main_tables": [], "supp_tables": []}),
        }
        for rel, text in files.items():
            (P / rel).parent.mkdir(parents=True, exist_ok=True)
            (P / rel).write_text(text, encoding="utf-8")
        return P, st

    def plan(name: str, feedback: str, items: list[dict]) -> Path:
        path = tmp / f"{name}.json"
        path.write_text(_json.dumps({
            "feedback_verbatim": feedback,
            "interpretation": "Apply the user's request to the named sources only and keep every "
                              "other approved artifact unchanged.",
            "ambiguous_or_requires_user_decision": [], "items": items}), encoding="utf-8")
        return path

    def rw(P: Path, *args):
        return _run([sys.executable, rework, *args, "--project", P],
                    env=_env(MEDPAPER_PROJECT=P, MEDPAPER_ROOT=ROOT))

    def load_round(P: Path) -> dict:
        return _json.loads((P / ".wf/revisions/R001.json").read_text(encoding="utf-8"))

    # ---- multi-message collection, one seal ---------------------------------------------
    P, _ = paper("scoped", "S19_human_review")
    (P / ".wf/check_receipts.json").write_text("{}", encoding="utf-8")
    a = rw(P, "batch", "--plan", plan("m1", "Please clarify the causal claim in the Discussion.", [
        {"kind": "discussion", "request": "Clarify the causal interpretation in the Discussion.",
         "affected_sources": ["07_manuscript/discussion.md"], "acceptance_criteria": acc}]))
    b = rw(P, "batch", "--plan", plan("m2", "Also shorten the Methods paragraph, please.", [
        {"kind": "methods", "request": "Shorten the Methods while keeping every detail.",
         "affected_sources": ["07_manuscript/methods.md"], "acceptance_criteria": acc}]))
    r = load_round(P)
    st = State(P, ".wf").load()
    try:
        deps.guard_build(P)
        blocked = False
    except ValueError:
        blocked = True
    record("two feedback messages collect into one round and nothing builds before seal",
           a.returncode == 0 and b.returncode == 0 and r.get("status") == "collecting"
           and r.get("schema_version") == 2 and len(r.get("feedback_updates", [])) == 2
           and len(r.get("items", [])) == 2 and blocked and st.current == "S19_human_review",
           _out(b)[-200:])
    s = rw(P, "seal", "--why", "The user said that is all, apply both changes now.")
    r = load_round(P)
    st = State(P, ".wf").load()
    try:
        deps.guard_build(P)
        open_build = True
    except ValueError:
        open_build = False
    record("seal plans once; no rewind: S08/S16 stay done, checkpoint stays S19",
           s.returncode == 0 and r.get("status") == "active" and open_build
           and st.current == "S19_human_review" and st.status_of("S08_methods") == "done"
           and st.status_of("S16_discussion") == "done" and st.status_of("S17_assemble") == "done"
           and st.decision("manuscript_human_reviewed") is None, _out(s)[-200:])
    record("gate receipts are invalidated across a rework",
           not (P / ".wf/check_receipts.json").exists())
    stages = set(r.get("validation_stages", []))
    check_stages = {c["stage"] for c in r.get("checks", [])}
    record("only the affected stages' non-lifecycle gates are validated",
           {"S08_methods", "S16_discussion"} <= stages
           and not stages & {"S05_analysis", "S10_tables", "S11_figures", "S14_introduction",
                             "S19_human_review", "S20_journal"}
           and check_stages <= stages | {"S19_human_review"}
           and not any(c["spec"].get("check") in rv.LIFECYCLE_CHECKS for c in r.get("checks", [])),
           f"stages={sorted(stages)}")

    # ---- scope drift, evidence refresh ------------------------------------------------
    (P / "07_manuscript/methods.md").write_text("# Methods\n\nShorter methods.\n", encoding="utf-8")
    in_scope = rv.scope_problems(P, r)
    sig0 = rv.input_signature(P, st, r)
    (P / "06_refs/verified.json").write_text('{"checked": 2}\n', encoding="utf-8")
    sig1 = rv.input_signature(P, st, r)
    record("a refreshed evidence receipt is not scope drift and keeps the input signature",
           not in_scope and not rv.scope_problems(P, r) and sig0 == sig1, "; ".join(in_scope))
    intro = P / "07_manuscript/introduction.md"
    intro.write_text("# Introduction\n\nSilently edited.\n", encoding="utf-8")
    results, _, _ = rv.validate(P, pipe, st, {**r, "checks": []})
    record("N: a file changed outside the sealed scope fails revision_scope_unchanged",
           results and results[0].check == "revision_scope_unchanged" and not results[0].ok
           and "introduction.md" in results[0].detail, results[0].detail[:160] if results else "")
    intro.write_text("# Introduction\n\nOriginal introduction.\n", encoding="utf-8")
    c = rw(P, "check")
    r = load_round(P)
    record("rework check runs the scoped gates in place and records the evidence",
           c.returncode in (0, 2) and "Scoped checks:" in _out(c) and "validation" in r
           and State(P, ".wf").load().current == "S19_human_review", _out(c)[-200:])
    lp = _wf("loop", "--to", "S16_discussion", "--why", "fixture tries to rewind mid-round",
             env=_env(MEDPAPER_PROJECT=P), cwd=P)
    record("N: wf loop is refused while a scoped round is open",
           lp.returncode != 0 and State(P, ".wf").load().current == "S19_human_review",
           f"rc={lp.returncode} " + (lp.stdout or "")[-200:])
    builds = [rw(P, "build", "--scope", "full", "--why", "fixture full build attempt")
              for _ in range(3)]
    record("rework build --scope full is capped at 2 per round",
           [p.returncode == 0 for p in builds] == [True, True, False]
           and load_round(P).get("full_builds") == 2, _out(builds[2])[-160:])

    # ---- planning rules ----------------------------------------------------------------
    st2 = State(P, ".wf").load()
    st2.stage_info("S16_discussion")["status"] = "skipped"
    skip_round = {"review_stage": "S19_human_review", "baseline": {}, "items": [
        {"kind": "discussion", "change_type": "scientific", "owning_stage": "S16_discussion",
         "affected_sources": ["07_manuscript/discussion.md"]}]}
    rv.plan_scope(P, pipe, st2, skip_round)
    record("a paper-local skipped stage never enters validation",
           "S16_discussion" not in skip_round["validation_stages"]
           and all(c["stage"] != "S16_discussion" for c in skip_round["checks"]),
           str(skip_round["validation_stages"]))
    ana = {"review_stage": "S19_human_review", "baseline": {}, "items": [
        {"kind": "analysis", "change_type": "scientific", "owning_stage": "S05_analysis",
         "affected_sources": ["03_analysis/code/primary.py"]}]}
    rv.plan_scope(P, pipe, st, ana)
    record("a 03_analysis change forces analysis_reproduces and reaches only its own result",
           any(c["spec"].get("check") == "analysis_reproduces" for c in ana["checks"])
           and {"S05_analysis", "S06_protocol_final"} <= set(ana["validation_stages"])
           and "03_analysis/results/primary.json" in ana["rebuild_files"]
           and "03_analysis/results/secondary.json" not in ana["rebuild_files"]
           and "05_figures/out/Figure1.png" in ana["rebuild_files"]
           and "05_figures/out/Figure2.png" not in ana["rebuild_files"],
           f"{len(ana['rebuild_files'])} file(s)")

    # ---- one figure changed: the other is protected ------------------------------------
    F, _ = paper("onefig", "S19_human_review")
    fs = rw(F, "batch", "--sealed", "--why", "The user asked to apply the figure fix now.",
            "--plan", plan("f1", "Figure 1 axis label is wrong, please fix it.", [
                {"kind": "figures", "request": "Fix the axis label of Figure 1 only.",
                 "affected_sources": ["05_figures/code/fig1.R"], "acceptance_criteria": acc}]))
    fr = load_round(F)
    try:
        rv.guard_outputs(F, [F / "05_figures/out/Figure2.png"])
        fig2_refused = False
    except ValueError:
        fig2_refused = True
    try:
        rv.guard_outputs(F, [F / "05_figures/out/Figure1.png"])
        fig1_ok = True
    except ValueError:
        fig1_ok = False
    record("one figure's closure includes that figure only; writers refuse the other",
           fs.returncode == 0 and fr.get("status") == "active" and fig1_ok and fig2_refused
           and "05_figures/out/Figure1.png" in fr.get("rebuild_files", [])
           and "05_figures/out/Figure2.png" not in fr.get("rebuild_files", []), _out(fs)[-200:])
    if shutil.which("Rscript"):
        before = _sha(F / "05_figures/out/Figure2.png")
        body = ('p <- ggplot(mtcars, aes(wt, mpg)) + geom_point() + labs(x = "Weight", y = "MPG") '
                '+ theme_medpaper()\nsave_medpaper(p, "05_figures/out/{n}", width = "single")\n')
        _r_script(F / "05_figures/code/fig1.R", body.replace("{n}", "Figure1"))
        _r_script(F / "05_figures/code/fig2.R", body.replace("{n}", "Figure2"))
        p1 = _wf("run-script", "05_figures/code/fig1.R", env=_env(MEDPAPER_PROJECT=F), cwd=tmp)
        p2 = _wf("run-script", "05_figures/code/fig2.R", env=_env(MEDPAPER_PROJECT=F), cwd=tmp)
        record("R: re-rendering Figure 1 works; Figure 2 render is refused and byte-identical",
               p1.returncode == 0 and (F / "05_figures/out/Figure1.tiff").is_file()
               and p2.returncode != 0 and "out-of-scope render" in _out(p2)
               and _sha(F / "05_figures/out/Figure2.png") == before,
               (_out(p1)[-120:] + " | " + _out(p2)[-160:]))
    else:
        record("R: one-figure re-render (skipped: Rscript not on PATH)", True)

    # ---- science changed after S19 returns to S19 -------------------------------------
    Q, qst = paper("post19", "S24_package_human_review")
    qst.record_decision("submission_package_user_confirmed", "OK",
                        "The fixture user approved the package before new feedback.")
    qst.save()
    (Q / "08_submission/manuscript").mkdir(parents=True)
    (Q / "08_submission/manuscript/title_page.md").write_text("# Title page\n", encoding="utf-8")
    qs = rw(Q, "batch", "--sealed", "--why", "The user wants both changes applied now.",
            "--plan", plan("q1", "Soften the causal claim and fix the title page affiliation.", [
                {"kind": "discussion", "request": "Soften the causal claim in the Discussion.",
                 "affected_sources": ["07_manuscript/discussion.md"], "acceptance_criteria": acc},
                {"kind": "title-page-or-statements", "request": "Fix the first author affiliation.",
                 "affected_sources": ["08_submission/manuscript/title_page.md"],
                 "acceptance_criteria": acc}]))
    qr = load_round(Q)
    qst = State(Q, ".wf").load()
    try:
        rv.resume_package(Q, pipe, qst)
        early = True
    except ValueError:
        early = False
    record("post-S19 science returns to S19 for re-approval; S20-S23 history kept",
           qs.returncode == 0 and qst.current == "S19_human_review"
           and qst.status_of("S24_package_human_review") == "pending"
           and all(qst.status_of(s) == "done" for s in
                   ("S20_journal", "S21_authors", "S22_polish", "S23_package"))
           and qst.data.get("resume_package_revision") == "R001"
           and qst.decision("manuscript_human_reviewed") is None
           and qst.decision("submission_package_user_confirmed") is None
           and len(qr.get("deferred_package_items", [])) == 1
           and not any(f.startswith("08_submission/") for f in qr.get("allowed_files", []))
           and not early, _out(qs)[-200:])
    s19 = pipe.stage("S19_human_review")
    record("the S19 re-review still requires explicit approval and a re-freeze",
           any(g.get("check") == "s19_review_release_explicit" for g in s19.gate)
           and any(g.get("check") == "scientific_freeze_captured" for g in s19.gate)
           and "rebind-variant" in (ROOT / "tools/manuscript/scientific_freeze.py")
           .read_text(encoding="utf-8"))

    # ---- legacy schema-1 rounds stay readable; migration notes them ----------------------
    L = tmp / "legacy"
    L.mkdir()
    lst = State(L, ".wf").create(pipe.meta["name"], "1.6.0", "S24_package_human_review")
    (L / "07_manuscript").mkdir()
    (L / "07_manuscript/methods.md").write_text("# Methods\n\nLegacy.\n", encoding="utf-8")
    (L / ".wf/revisions").mkdir(parents=True)
    (L / ".wf/revisions/R001.json").write_text(_json.dumps({
        "schema_version": 1, "round_id": "R001", "status": "complete",
        "review_stage": "S24_package_human_review", "items": [{
            "id": "R001-01", "kind": "methods", "status": "done",
            "validated_by": ["legacy fixture validation"],
            "changed_files": [{"path": "07_manuscript/methods.md",
                               "sha256": _sha(L / "07_manuscript/methods.md")}]}]}), encoding="utf-8")
    load_all()
    gate = get("revision_rounds_closed")(Ctx(pipe, lst, L, pipe.stage("S24_package_human_review"), {}))
    record("a completed schema-1 round is still read by revision_rounds_closed", gate.ok, gate.detail)
    (L / ".wf/revisions/R002.json").write_text(_json.dumps({
        "schema_version": 1, "round_id": "R002", "status": "active",
        "review_stage": "S24_package_human_review", "items": []}), encoding="utf-8")
    lst.data["active_revision_round"] = "R002"
    lst.save()
    lst.migrate_pipeline(pipe.meta["version"], [s.id for s in pipe.stages])
    record("migration keeps an open schema-1 round on its rewind flow and records it",
           lst.data.get("legacy_revision_round") == "R002"
           and any(e.get("kind") == "revision_legacy_round" for e in lst.data.get("events", [])))


def run_reporting_checklist(tmp: Path) -> None:
    from wfcore import scifreeze
    from wfcore.checks import reporting as rp
    section("reporting-guideline checklist")
    reg = rp.load_registry()
    counts = {g: len(reg[g]["items"]) for g in ("STROBE", "CONSORT", "CONSORT-2010", "STARD",
                                                  "TRIPOD", "PRISMA", "SPIRIT", "CARE", "CHEERS",
                                                  "RECORD", "STROBE-MR", "TRIPOD+AI")}
    record("registry structure is valid and item counts match the official lists",
           not rp.registry_problems(reg) and counts == {"STROBE": 34, "CONSORT": 42,
           "CONSORT-2010": 37, "STARD": 34, "TRIPOD": 37, "PRISMA": 42, "SPIRIT": 51, "CARE": 30,
           "CHEERS": 28, "RECORD": 13, "STROBE-MR": 42, "TRIPOD+AI": 52}, str(counts))
    record("1.7.2 lists are verified and keep the official main-item numbering",
           not any(reg[g]["verify"] for g in ("RECORD", "STROBE-MR", "TRIPOD+AI"))
           and len({i["id"].rstrip("abcdefg") for i in reg["STROBE-MR"]["items"]}) == 20
           and len({i["id"].rstrip("abcdefg") for i in reg["TRIPOD+AI"]["items"]}) == 27
           and {i["id"].split(".")[0] for i in reg["RECORD"]["items"]}
           == {"1", "6", "7", "12", "13", "19", "22"})
    split = {s: rp.split_guidelines(s, reg) for s in (
        "STROBE + RECORD", "STROBE+RECORD", "STROBE, RECORD", "TRIPOD+AI", "STROBE + PRISMA-ScR")}
    record("Guideline: values combine with + , ; & and; TRIPOD+AI is never split",
           split == {"STROBE + RECORD": (["STROBE", "RECORD"], []),
                     "STROBE+RECORD": (["STROBE", "RECORD"], []),
                     "STROBE, RECORD": (["STROBE", "RECORD"], []),
                     "TRIPOD+AI": (["TRIPOD+AI"], []),
                     "STROBE + PRISMA-ScR": (["STROBE"], ["PRISMA-ScR"])}, str(split))
    record("bare CONSORT means the current 2025 statement; 2010 must be named explicitly",
           reg["CONSORT"]["version"] == "2025"
           and rp.resolve_alias("CONSORT", reg) == "CONSORT"
           and rp.resolve_alias("CONSORT 2010", reg) == "CONSORT-2010"
           and len({i["id"].rstrip("abcd") for i in reg["CONSORT"]["items"]}) == 30)
    det = {s: rp.detect_guidelines(s, reg) for s in (
        "CONSORT 2025", "TRIPOD+AI", "STROBE-MR", "standard care", "CARE",
        "in the spirit of the original trial", "SPIRIT 2013", "three cheers", "a squire",
        "CHEERS 2022", "STROBE + RECORD", "the medical record")}
    record("alias detection: longest first, boundaries, case-sensitive English words",
           det == {"CONSORT 2025": ["CONSORT"], "TRIPOD+AI": ["TRIPOD+AI"],
                   "STROBE-MR": ["STROBE-MR"],
                   "standard care": [], "CARE": ["CARE"], "in the spirit of the original trial": [],
                   "SPIRIT 2013": ["SPIRIT"], "three cheers": [], "a squire": [],
                   "CHEERS 2022": ["CHEERS"], "STROBE + RECORD": ["STROBE", "RECORD"],
                   "the medical record": []}, str(det))
    P = _new_paper(tmp / "checkpaper")
    (P / "01_protocol").mkdir(exist_ok=True)
    (P / "08_submission/manuscript").mkdir(parents=True)

    def protocol(design: str = "Retrospective cohort study using NHANES."):
        (P / "01_protocol/protocol_final.md").write_text(
            f"# Protocol\n\n## Design\n{design}\n\n## Ethics\nx\n", encoding="utf-8")

    def require(value):
        """What S20 records when the journal's author guidelines demand a checklist."""
        data = {"journal": "Fixture Journal"}
        if value is not None:
            data["journal_requires_checklist"] = value
        (P / "08_submission/target_journal.json").write_text(json.dumps(data), encoding="utf-8")
    protocol()
    heads = ["Introduction", "2.1 Study design", "Methods", "Results", "Discussion"]
    items = [i["id"] for i in reg["STROBE"]["items"]]

    def ev(i):
        return f"Checklist item {i} is reported in this exact sentence."
    methods_body = " ".join(ev(i) for i in items)
    bodies = {"Methods": methods_body,
              "2.1 Study design": "This is a retrospective cohort design sentence."}
    (P / "08_submission/manuscript/full_manuscript.md").write_text(
        "# A retrospective cohort study title of moderate length\n\n" + "".join(
            f"## {h}\n{bodies.get(h, 'text')}\n\n" for h in heads), encoding="utf-8")

    def checklist(rows=None, guideline="STROBE", legacy=False):
        rows = rows if rows is not None else [(i, "Reported", "Methods", ev(i), "") for i in items]
        if legacy:
            body = "\n".join(f"| {a} | {b} | {c} | {e} |" for a, b, c, _, e in rows)
            head = "| Item | Status | Location | Reason |\n|---|---|---|---|"
        else:
            body = "\n".join(f"| {a} | {b} | {c} | {d} | {e} |" for a, b, c, d, e in rows)
            head = "| Item | Status | Location | Evidence | Reason |\n|---|---|---|---|---|"
        (P / "08_submission/reporting_checklist.md").write_text(
            f"# Reporting checklist\n\nGuideline: {guideline}\n\n{head}\n{body}\n",
            encoding="utf-8")

    def gate(**spec):
        return _gate("reporting_checklist_complete", P, stage="S23_package", **spec)
    g = gate()
    record("no journal requirement: the gate passes as not required, no checklist file needed",
           g.ok and "not required" in g.detail
           and not (P / "08_submission/reporting_checklist.md").exists(), g.detail[:120])
    require("none")
    record("journal_requires_checklist = none also counts as not required", gate().ok)
    require("STROBE")
    g = gate()
    record("N: journal requires STROBE and no checklist exists -> the gate enforces",
           not g.ok and "missing" in g.detail, g.detail[:120])
    checklist()
    g = gate()
    record("a complete checklist against the variant passes", g.ok, g.detail[:120])
    base = [(i, "Reported", "Methods", ev(i), "") for i in items]
    negs = {
        "missing item": base[1:],
        "duplicate": base + [base[0]],
        "unknown id": base + [("99z", "Reported", "Methods", ev("1a"), "")],
        "absent heading": [(items[0], "Reported", "Methods 2", ev(items[0]), "")] + base[1:],
        "short reason": [(items[0], "Not applicable", "", "", "too short")] + base[1:],
        "bad status": [(items[0], "Partly", "Methods", ev(items[0]), "")] + base[1:],
    }
    failed = {}
    for k, rows in negs.items():
        checklist(rows)
        failed[k] = not gate().ok
    record("N: missing, duplicate, unknown, unresolved, short-reason and bad-status rows fail",
           all(failed.values()), str(failed))
    checklist([(items[0], "Reported", "Methods", "", "")] + base[1:])
    g = gate()
    record("N: a Reported row with only a section and no evidence quote fails",
           not g.ok and "without a verbatim Evidence quote" in g.detail, g.detail[:160])
    checklist([(items[0], "Reported", "Methods", "We followed every guideline item carefully.",
                "")] + base[1:])
    g = gate()
    record("N: an evidence quote that is not in the manuscript fails",
           not g.ok and "not found in the stated location" in g.detail, g.detail[:160])
    checklist([(items[0], "Reported", "Introduction", ev(items[0]), "")] + base[1:])
    g = gate()
    record("N: a real quote attributed to the wrong section fails",
           not g.ok and "not found in the stated location" in g.detail, g.detail[:160])
    checklist([(i, "Reported", "Methods", ev(items[0]), "") for i in items[:5]] + base[5:])
    g = gate()
    record("N: one quote reused for many items fails",
           not g.ok and "reused for more than" in g.detail, g.detail[:160])
    checklist([(items[0], "Reported", "Methods", f"  checklist ITEM {items[0]} is reported\n in "
                "this *exact* sentence.  ", "")] + base[1:])
    record("evidence matching ignores whitespace, case and emphasis markup", gate().ok)
    checklist(legacy=True)
    g = gate()
    record("N: a pre-1.7.1 four-column checklist is refused with a migration hint",
           not g.ok and "added the Evidence column" in g.detail, g.detail[:160])
    checklist(guideline="CONSORT")
    record("N: a checklist for another guideline fails", not gate().ok)
    # STROBE + RECORD: union of both lists, as separate blocks or one prefixed combined block.
    ritems = [i["id"] for i in reg["RECORD"]["items"]]
    rev = {i: f"Record extension item {i} is stated in this sentence." for i in ritems}
    man = P / "08_submission/manuscript/full_manuscript.md"
    man_before = man.read_text(encoding="utf-8")
    man.write_text(man_before.replace("## Results", "## Data sources\n"
                   + " ".join(rev.values()) + "\n\n## Results"), encoding="utf-8")
    rrows = [(i, "Reported", "Data sources", rev[i], "") for i in ritems]
    require("STROBE + RECORD")
    checklist()
    g = gate()
    record("N: STROBE + RECORD with only the STROBE block fails",
           not g.ok and "do not match the requirement" in g.detail, g.detail[:160])
    cl = P / "08_submission/reporting_checklist.md"

    def rec_block(rows):
        return ("\nGuideline: RECORD\n\n| Item | Status | Location | Evidence | Reason |\n"
                "|---|---|---|---|---|\n"
                + "\n".join(f"| {a} | {b} | {c} | {d} | {e} |" for a, b, c, d, e in rows) + "\n")
    checklist()
    cl.write_text(cl.read_text(encoding="utf-8") + rec_block(rrows), encoding="utf-8")
    g = gate()
    record("STROBE + RECORD with a STROBE block and a RECORD block passes", g.ok, g.detail[:160])
    checklist()
    cl.write_text(cl.read_text(encoding="utf-8") + rec_block(rrows[1:]), encoding="utf-8")
    g = gate()
    record("N: STROBE + RECORD missing a RECORD item fails",
           not g.ok and "RECORD: missing item(s) 1.1" in g.detail, g.detail[:160])
    combined = ([(f"STROBE {a}", b, c, d, e) for a, b, c, d, e in base]
                + [(f"RECORD {a}", b, c, d, e) for a, b, c, d, e in rrows])
    checklist(combined, guideline="STROBE + RECORD")
    g = gate()
    record("one combined STROBE + RECORD block with prefixed items passes", g.ok, g.detail[:160])
    checklist(base + [(f"RECORD {a}", b, c, d, e) for a, b, c, d, e in rrows],
              guideline="STROBE + RECORD")
    g = gate()
    record("N: unprefixed items in a combined block fail",
           not g.ok and "needs a guideline prefix" in g.detail, g.detail[:160])
    man.write_text(man_before, encoding="utf-8")
    require("SQUIRE")
    g = gate()
    record("N: a journal-required but unverified guideline fails", not g.ok and "verify = true" in g.detail)
    require("PRISMA-ScR")
    record("N: an unregistered journal_requires_checklist name fails",
           "unregistered guideline in journal_requires_checklist" in gate().detail)
    # Meta-analysis keeps PRISMA in its normal flow even when the journal names none.
    require(None)
    protocol("Systematic review and meta-analysis of cohort studies.")
    checklist()
    g = gate()
    record("N: a meta-analysis is held to PRISMA without a journal requirement",
           not g.ok and "PRISMA" in g.detail and "meta-analysis design" in g.detail, g.detail[:160])
    pitems = [i["id"] for i in reg["PRISMA"]["items"]]
    man.write_text(man_before.replace("## Results", "## Review methods\n" + " ".join(
        f"PRISMA item {i} is reported in this sentence." for i in pitems) + "\n\n## Results"),
        encoding="utf-8")
    checklist([(i, "Reported", "Review methods", f"PRISMA item {i} is reported in this sentence.",
                "") for i in pitems], guideline="PRISMA")
    record("a meta-analysis with a complete PRISMA checklist passes", gate().ok, gate().detail[:160])
    man.write_text(man_before, encoding="utf-8")
    protocol()
    require("STROBE")
    rows = [(items[0], "Reported", "Title", "A retrospective cohort study title", ""),
            (items[1], "Reported", "Study design", "This is a retrospective cohort design", "")
            ] + base[2:]
    checklist(rows)
    g = gate()
    record("Title resolves to the H1 and numbered headings match without their numbers", g.ok,
           g.detail[:160])
    sup = P / "08_submission/manuscript/supplementary_methods.md"
    rows = [(items[0], "Reported", "Supplementary Methods > Sensitivity analyses",
             "Sensitivity analyses excluded early deaths.", ""),
            (items[1], "Reported", "Title page; Statements > Funding",
             "This study received no specific funding.", "")] + base[2:]
    checklist(rows)
    absent = not gate().ok
    sup.write_text("# Supplementary Methods\n## Sensitivity analyses\n"
                   "Sensitivity analyses excluded early deaths.\n", encoding="utf-8")
    (P / "08_submission/manuscript/title_page.md").write_text("# Title page\nx\n", encoding="utf-8")
    (P / "08_submission/manuscript/statements.md").write_text(
        "# Statements\n## Funding\nThis study received no specific funding.\n", encoding="utf-8")
    g = gate()
    present = g.ok
    checklist([(items[0], "Reported", "Nonexistent doc > X", ev(items[0]), "")] + base[1:])
    record("locations resolve across the variant's documents",
           absent and present and not gate().ok, g.detail[:160])
    record("the checklist is journal-downstream (cleared on a journal switch)",
           "08_submission/reporting_checklist.md" in scifreeze.JOURNAL_DOWNSTREAM)
    # 1.7.3: nothing pre-emptive in the default cards; registration only for meta-analysis.
    import re
    import tomllib
    from wfcore.state import State
    cards = {p.stem: p.read_text(encoding="utf-8") for p in (ROOT / "pipeline/stages").glob("S*.md")}
    named = sorted(k for k, t in cards.items()
                   if re.search(r"STROBE|TRIPOD|CONSORT|STARD|RECORD \d|Guideline:", t)
                   and k not in ("S20_journal", "S23_package"))
    record("no default stage card names a reporting checklist (only S20/S23 on demand)",
           not named, str(named))
    reg_words = sorted(k for k, t in cards.items()
                       if re.search(r"\bOSF\b|osf\.io|pre-?regist|trial registration|ClinicalTrials|ChiCTR", t, re.I))
    s03 = cards["S03_protocol"]
    record("non-meta studies carry no registration requirement; meta-analysis prompts PROSPERO",
           not reg_words and "need no registration" in s03 and "PROSPERO before screening" in s03,
           str(reg_words))
    pdoc = tomllib.loads((ROOT / "pipeline/pipeline.toml").read_text(encoding="utf-8"))
    heads = [g.get("headings", []) for s in pdoc["stage"] for g in s.get("gate", [])
             if str(g.get("path", "")).startswith("01_protocol/protocol")]
    record("protocols no longer require a Reporting guideline section",
           heads and not any("Reporting guideline" in h for h in heads))
    mig = State(tmp / "mig173", ".wf")
    mig.create("medpaper", "1.7.2", "S23_package")
    mig.migrate_pipeline("1.7.3", ["S23_package"])
    kinds = [e.get("kind") for e in mig.data.get("events", [])]
    record("migrating an in-flight 1.7.2 paper records the relaxed-requirements event",
           kinds.count("requirements_relaxed") == 1, str(kinds))


def run_new_wiring() -> None:
    import tomllib
    from wfcore import cli, overrides, registry
    from wfcore.checks import known
    section("1.5.0 gate wiring")
    names = {"results_have_environment", "analysis_reproduces", "reporting_checklist_complete"}
    pipe = tomllib.loads((ROOT / "pipeline/pipeline.toml").read_text(encoding="utf-8"))
    used = {g["check"] for s in pipe["stage"] for g in s.get("gate", [])}
    record("the three new gates are registered and used", names <= set(known()) and names <= used)
    record("they are non-overridable and protected; PROTECTED >= NON_OVERRIDABLE",
           names <= cli.NON_OVERRIDABLE_GATES and names <= overrides.PROTECTED_CHECKS
           and cli.NON_OVERRIDABLE_GATES <= overrides.PROTECTED_CHECKS)
    pairs = {(s["id"], g["check"]) for s in pipe["stage"] for g in s.get("gate", []) if g["check"] in names}
    expected = {("S04_data", "results_have_environment"), ("S05_analysis", "results_have_environment"),
                ("S06_protocol_final", "results_have_environment"), ("S06_protocol_final", "analysis_reproduces"),
                ("S17_assemble", "analysis_reproduces"), ("S23_package", "analysis_reproduces"),
                ("S25_submission_audit", "analysis_reproduces"),
                ("S23_package", "reporting_checklist_complete"),
                ("S24_package_human_review", "reporting_checklist_complete"),
                ("S25_submission_audit", "reporting_checklist_complete")}
    record("declarations match the specification", pairs == expected, str(sorted(pairs ^ expected)))
    stages = registry.load().stages
    reason = "This paper genuinely needs a different shape for this stage, explained here at length."
    relax_refused = all(overrides.validate({"schema": 1, "stage_override": [
        {"stage": sid, "reason": reason, "relax_gate": [chk]}]}, stages) for sid, chk in expected)
    skip_refused = all(overrides.validate({"schema": 1, "stage_override": [
        {"stage": sid, "reason": reason, "skip": True}]}, stages)
        for sid in ("S04_data", "S05_analysis", "S06_protocol_final", "S17_assemble", "S23_package",
                    "S24_package_human_review", "S25_submission_audit"))
    record("overrides cannot relax the new gates or skip their stages", relax_refused and skip_refused)
    s06 = next(s for s in pipe["stage"] if s["id"] == "S06_protocol_final")
    s23 = next(s for s in pipe["stage"] if s["id"] == "S23_package")
    record("S06 declares the reproducibility report, [freeform] the tolerance file; the "
           "on-demand checklist is not a required S23 output",
           "03_analysis/reproducibility_report.json" in s06["outputs"]
           and "08_submission/reporting_checklist.md" not in s23["outputs"]
           and "03_analysis/reproducibility.toml" in pipe["freeform"]["globs"])
    record("S06 no longer carries a checklist gate",
           not any(g["check"] == "reporting_checklist_complete" for g in s06["gate"]))



# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="self test for the medpaper toolchain")
    ap.add_argument("--keep", action="store_true", help="do not delete the temp project")
    ap.add_argument("--online", action="store_true", help="also exercise the live APIs")
    ap.add_argument("--workdir", type=Path,
                    help="use an existing empty directory instead of the system temp root")
    args = ap.parse_args()

    for mod, why in (("matplotlib", "figures"), ("numpy", "QC"), ("openpyxl", "tables"),
                     ("docx", "Word submission files")):
        try:
            __import__(mod)
        except ImportError:
            print(f"cannot run: {mod} is required for {why}.\n"
                  f"  uv pip install --python .venv/Scripts/python.exe {mod}")
            return 1

    from wfcore import paths as _paths
    if args.workdir:
        tmp = args.workdir.resolve()
        if _paths.in_engine(tmp):
            print(f"cannot run: --workdir is inside the engine: {tmp}")
            return 1
        tmp.mkdir(parents=True, exist_ok=True)
        if any(tmp.iterdir()):
            print(f"cannot run: --workdir must be empty: {tmp}")
            return 1
    else:
        if _paths.in_engine(Path(tempfile.gettempdir()).resolve()):
            print("cannot run: the system temp directory is inside the engine")
            return 1
        tmp = Path(tempfile.mkdtemp(prefix="medpaper_selftest_"))
    proj = tmp / "project"
    # Isolation: no test may touch the real papers root or the user's ~/.medpaper.
    real_root = ROOT.parent / "medpaper_papers"
    real_home = Path.home() / ".medpaper"

    def _listing(d: Path):
        if not d.exists():
            return None
        return sorted((x.relative_to(d).as_posix(), x.stat().st_mtime_ns)
                      for x in d.rglob("*"))
    real_before = (_listing(real_root), _listing(real_home))
    os.environ["MEDPAPER_HOME"] = str(tmp / "home")
    os.environ["MEDPAPER_PAPERS_ROOT"] = str(tmp / "papers")
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"  # child tools must not leave __pycache__ in the engine
    engine_top_before = sorted(x.name for x in ROOT.iterdir())
    os.environ["MEDPAPER_PROJECT"] = str(proj)
    os.environ["MEDPAPER_ROOT"] = str(ROOT)
    os.environ["MEDPAPER_SELFTEST_ROOT"] = str(tmp)
    if args.keep:
        os.environ["MEDPAPER_SELFTEST_KEEP_ARTIFACTS"] = "1"
    print(f"temp project: {proj}\n")

    try:
        section("building fixture")
        build_fixture(proj)
        record("fixture built", True)
        run_checks(proj)
        run_data_proof(proj)
        run_reference_proof(proj)
        run_reference_identity(proj)
        run_scientific_freeze(proj)
        run_paper_overrides(proj)
        run_qc(proj)
        run_visual_deferral(proj)
        run_archetypes(proj)
        run_codex_integration()
        run_fulltext_registration(proj)
        run_journal_eligibility(proj)
        run_manuscript_docx(proj)
        run_polish(proj)
        purity = tmp / "purity"
        purity.mkdir()
        run_engine_purity(purity)
        run_language_policy()
        run_paper_header(tmp / "header_root")
        run_no_plot_calls_r()
        run_results_environment(tmp / "receipts_root")
        run_reproduce(tmp / "repro_root")
        run_r_figures(tmp / "rfig_root")
        run_reporting_checklist(tmp / "checklist_root")
        run_v160(tmp / "v160_root")
        run_v170(tmp / "v170_root")
        import selftest_v180
        selftest_v180.run(tmp / "v180_root", record, section)
        run_new_wiring()
        section("isolation")
        record("selftest did not touch the real papers root or user home",
               (_listing(real_root), _listing(real_home)) == real_before)
        record("selftest left the engine's top level unchanged",
               sorted(x.name for x in ROOT.iterdir()) == engine_top_before
               and not any((ROOT / n).exists() for n in ("project", "papers", "temp", ".wf", "Rplots.pdf")),
               str(sorted(set(x.name for x in ROOT.iterdir()) ^ set(engine_top_before))))
        if args.online:
            run_online(proj)
    finally:
        if args.keep or args.workdir:
            print(f"\nkept: {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)

    failed = [r for r in results if r[1] == FAIL]
    print("\n" + "=" * 70)
    print(f"{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        for name, _, detail in failed:
            print(f"  FAIL  {name}  {detail}")
        return 2
    print("selftest: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

