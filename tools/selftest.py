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
           legacy.data["pipeline_version"] == "1.4.0",
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
    pdf_self = b"%PDF-1.7 ... doi:10.1055/a-2669-5801 ... body"
    pdf_cites_others = (b"%PDF-1.7 ... References: 10.1055/s-0034-1393583, "
                        b"10.3748/wjg.v27.i38.6357 ... body")
    record("a PDF containing our DOI counts as a match",
           ft.check_identity(base, pdf_self, "pdf")["identity"] == "match")
    v = ft.check_identity(base, pdf_cites_others, "pdf")
    record("a PDF citing OTHER DOIs is indeterminate, never a mismatch",
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

    def gate(identity: str):
        """Set the first paper's identity verdict; the other two always verify."""
        recs = []
        for n, ck in enumerate(keys):
            f = scoped / f"06_refs/fulltext/{ck}.pdf"
            rec = {"citekey": ck, "access": "oa", "fulltext": f"06_refs/fulltext/{ck}.pdf",
                   "sha256": hashlib.sha256(f.read_bytes()).hexdigest()}
            verdict = identity if n == 0 else "match"
            if verdict:
                rec["identity"] = verdict
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
    record("the freeze hashes the manuscript, refs and library",
           all(k in freeze["files"] for k in scifreeze.REQUIRED_SCIENTIFIC),
           f"{len(freeze['files'])} file(s)")
    record("re-freezing without --force is refused",
           _raises(lambda: scifreeze.write_freeze(scoped)),
           "it would discard the record of what review closed on")

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
    record("same-journal rebuild preserves the current S20 metadata",
           (submission / "target_journal.json").is_file())

    removed = scifreeze.reset_journal(scoped)
    record("a full journal switch clears S20 metadata/cache and every downstream file",
           "08_submission/target_journal.json" in removed
           and not any(submission.iterdir()), f"removed {len(removed)} file(s)")
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
           and not any((scoped / "08_submission").iterdir()),
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
    record("legacy in-flight scripts get an explicit non-blocking migration warning",
           not legacy_result.ok and legacy_result.severity == "warn"
           and any("Legacy paper migration" in hint for hint in legacy_result.hints),
           legacy_result.detail)

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

    # Standalone engine tools (not launched through wf.py) follow the active pointer too. This
    # is the second leak route: an active paper selected by `wf use` must be enough.
    fake_root = scoped / "standalone_engine"
    fake_paper = fake_root / "papers/selected"
    (fake_paper / ".wf").mkdir(parents=True)
    State(fake_paper, ".wf").create(master.meta["name"], master.meta["version"], master.first().id)
    (fake_root / ".wf").mkdir(parents=True)
    (fake_root / ".wf/active").write_text("selected\n", encoding="utf-8")
    standalone_env = {k: v for k, v in env.items() if k != "MEDPAPER_PROJECT"}
    standalone_env["MEDPAPER_ROOT"] = str(fake_root)
    standalone_env["PYTHONPATH"] = str(ROOT / "tools")
    p = subprocess.run([sys.executable, "-c",
                        "from pubmed import eutils; print(eutils.project_root()); "
                        "print(eutils.cache_dir())"], capture_output=True, text=True,
                       env=standalone_env, encoding="utf-8", errors="replace")
    record("standalone PubMed tools follow the paper selected with wf use",
           p.returncode == 0 and str(fake_paper) in (p.stdout or "")
           and (fake_paper / "06_refs/cache").is_dir(),
           ((p.stdout or "") + (p.stderr or "")).strip()[-140:])
    p = subprocess.run([sys.executable, str(ROOT / "tools/data_manifest.py"), "init"],
                       capture_output=True, text=True, env=standalone_env,
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
                       env=standalone_env, encoding="utf-8", errors="replace")
    record("the documented project/... alias maps table output into the selected paper",
           p.returncode == 0 and (fake_paper / "04_tables/main/Table1.xlsx").is_file(),
           ((p.stdout or "") + (p.stderr or "")).strip()[-120:])
    record("standalone tools did not create the mother engine's project/ fallback",
           not (fake_root / "project").exists(), str(fake_root / "project"))
    (fake_root / ".wf/active").write_text("missing-paper\n", encoding="utf-8")
    p = subprocess.run([sys.executable, "-c",
                        "from pubmed import eutils; print(eutils.project_root())"],
                       capture_output=True, text=True, env=standalone_env,
                       encoding="utf-8", errors="replace")
    record("a stale active marker fails closed instead of falling back to engine/project",
           p.returncode != 0 and "Refusing to fall back" in
           ((p.stdout or "") + (p.stderr or "")) and not (fake_root / "project").exists(),
           ((p.stdout or "") + (p.stderr or "")).strip()[-150:])

    # Doctor makes any future regression visible instead of letting a 1 MB/run drip accumulate.
    fake_engine = scoped / "fake_engine"
    (fake_engine / "papers/p").mkdir(parents=True)
    (fake_engine / "project/06_refs/cache").mkdir(parents=True)
    (fake_engine / "project/06_refs/cache/leak.xml").write_bytes(b"wrong root")
    with patch.object(cli.paths, "repo_root", return_value=fake_engine):
        rows = cli._engine_hygiene_rows()
    record("doctor reports paper artifacts leaked into the engine project/",
           any(name == "engine project/" and status == "BROKEN" for name, status, _ in rows),
           str(rows))
    (fake_engine / "project/06_refs/cache/leak.xml").unlink()
    with patch.object(cli.paths, "repo_root", return_value=fake_engine):
        rows = cli._engine_hygiene_rows()
    record("doctor clears once the engine contains no paper artifacts",
           any(name == "engine project/" and status == "ok" for name, status, _ in rows),
           str(rows))

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
        os.utime(png, (png.stat().st_atime, png.stat().st_mtime + 60))
        p = subprocess.run([sys.executable, qc, "--confirm", "Figure 1", "--note",
                            "trying to confirm against a stale QC report on purpose"],
                           capture_output=True, text=True, env=env, encoding="utf-8",
                           errors="replace")
        record("--confirm refuses a report made stale by a re-render", p.returncode != 0,
               ((p.stdout or "") + (p.stderr or "")).strip()[-100:])

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
           pipe["meta"]["version"] == "1.4.0" and 'version: "2.0.0"' in skill,
           f'pipeline={pipe["meta"]["version"]}, skill=2.0.0 (Kiro adapter revision)')
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
           "loop S24_package_human_review" in final_audit_card,
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
        [sys.executable, str(ROOT / "tools/rework.py"), "batch", "--plan", str(plan_path),
         "--project", str(batch_project)], capture_output=True, text=True, env=batch_env,
        encoding="utf-8", errors="replace")
    batch_state = State(batch_project, ".wf").load()
    round_path = batch_project / ".wf/revisions/R001.json"
    round_payload = json.loads(round_path.read_text(encoding="utf-8")) if round_path.exists() else {}
    record("multi-item revision persists interpretation and rewinds once to earliest owner",
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
            body = f"doi:{entry['doi']}\n".encode() + body
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
    gx = proj / "08_submission/guidelines_extract.md"
    gx.write_text("# Guidelines\n\n## Word limits\nAbstract: 250 words. Main text: 3500 words "
                  "excluding references. References: maximum 50.\n", encoding="utf-8")
    polish("lint")
    r = gate("journal_limits_met")
    record("journal_limits_met parses the quoted caps and passes", r.ok, r.detail[:110])
    gx.write_text("# Guidelines\n\n## Word limits\nAbstract: 250 words. Main text: 100 words "
                  "excluding references. References: maximum 50.\n", encoding="utf-8")
    r = gate("journal_limits_met")
    record("journal_limits_met rejects an over-limit manuscript", not r.ok, r.detail[:110])
    gx.write_text("# Guidelines\n\n## Word limits\nSee the website.\n", encoding="utf-8")
    r = gate("journal_limits_met")
    record("journal_limits_met rejects unquoted limits", not r.ok, r.detail[:110])

    section("polish: allowlist escape hatch")
    disc.write_text(CLEAN + "\nThe guideline states that screening plays a crucial role.\n",
                    encoding="utf-8")
    polish("lint")
    record("allowlist absent -> phrase blocks", not gate("ai_tells_clean").ok)
    (proj / "07_manuscript/polish_allowlist.tsv").write_text(
        "plays a crucial role\tquoted verbatim from the 2023 guideline\n", encoding="utf-8")
    polish("lint")
    record("allowlisted phrase stops blocking", gate("ai_tells_clean").ok)

    for f in (disc, abstract, gx, proj / "07_manuscript/polish_allowlist.tsv"):
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

    if args.workdir:
        tmp = args.workdir.resolve()
        tmp.mkdir(parents=True, exist_ok=True)
        if any(tmp.iterdir()):
            print(f"cannot run: --workdir must be empty: {tmp}")
            return 1
    else:
        tmp = Path(tempfile.mkdtemp(prefix="medpaper_selftest_"))
    proj = tmp / "project"
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

