"""1.10.0 regression tests: the 13 workflow-order and rule changes (tables -> figures -> Results,
Methods citations verified on entry, display plan re-checked for the journal, variable crosswalk
and raw spot check, workflow-judged declarations, statistical reporting plan, cited external
numbers in the Discussion, role coverage instead of a reference count, three-phase length
budgets, advisory legend caps, optional review export, protected review findings, explicit
confirmation sentence).

Called from tools/selftest.py.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))


def _w(p: Path, rel: str, text) -> None:
    (p / rel).parent.mkdir(parents=True, exist_ok=True)
    (p / rel).write_text(text if isinstance(text, str) else json.dumps(text), encoding="utf-8")


def _paper(base: Path, at: str) -> Path:
    import selftest_v180 as v180
    p = v180._rw_paper(base, at)
    _w(p, "03_analysis/results/primary.json", {"hr": 1.87, "lo": 1.21, "hi": 2.9, "p": 0.004})
    return p


def _gate(p: Path, name: str, stage: str, **spec):
    import selftest_v180 as v180
    return v180._gate(p, name, stage, **spec)


def run_order(tmp: Path, record, section) -> None:
    from wfcore import registry
    from wfcore.state import State
    section("1.10.0 #1 tables -> figures -> Results -> cross-check; #9 soft budgets before S20")
    pipe = registry.load()
    ids = [s.id for s in pipe.stages]
    s09 = pipe.stage("S09_results")
    record("S09 Results now runs after S10 tables and S11 figures, before the S12 cross-check",
           ids.index("S10_tables") < ids.index("S11_figures") < ids.index("S09_results")
           < ids.index("S12_reconcile")
           and any(g["check"] == "displays_final_for_results" and g.get("since") == "1.10.0"
                   for g in s09.gate), str(ids[7:12]))
    p = _paper(tmp / "order", "S09_results")
    st = State(p, ".wf").load()
    st.stage_info("S11_figures")["status"] = "pending"
    st.save()
    _w(p, "04_tables/manifest.json", {"tables": []})
    _w(p, "05_figures/manifest.json", {"figures": []})
    early = _gate(p, "displays_final_for_results", "S09_results")
    st = State(p, ".wf").load()
    st.stage_info("S11_figures").update(status="done", completed_at="2999-01-01T00:00:00Z")
    st.save()
    ready = _gate(p, "displays_final_for_results", "S09_results")
    record("Results cannot be written before the figures are final; afterwards the gate passes",
           not early.ok and "S11_figures" in early.detail and ready.ok, early.detail + " | " + ready.detail)
    # migration of a paper whose active stage is S09 with tables/figures still pending
    q = tmp / "migrate"
    q.mkdir(parents=True)
    old = State(q, ".wf").create("medpaper", "1.9.1", "S09_results")
    for sid in ids[:ids.index("S08_methods") + 1]:
        old.stage_info(sid)["status"] = "done"
    old.save()
    st = State(q, ".wf").load()
    st.migrate_pipeline("1.10.0", ids)
    st = State(q, ".wf").load()
    ev = [e for e in st.data["events"] if e["kind"] == "requirements_changed"]
    record("migration: an active S09 with pending displays moves to S10; event only, pin kept",
           st.current == "S10_tables" and st.status_of("S09_results") == "pending"
           and st.engine_pin == "1.9.1" and ev and "1.10.0" in ev[-1]["detail"],
           st.current + str(ev[-1:]))
    pinned = st.pin_excludes("S04_data", "1.10.0")
    record("new 1.10.0 gates do not re-judge stages the pinned paper completed",
           pinned and not st.pin_excludes("S10_tables", "1.10.0"))
    raw = tomllib.loads((ROOT / "pipeline/pipeline.toml").read_text(encoding="utf-8"))
    soft = {"md_wordcount", "citation_count", "draft_length_targets"}
    hard_before_s20 = []
    for s in raw["stage"]:
        if s["id"] >= "S20":
            continue
        for g in s.get("gate", []):
            if g["check"] in soft and g.get("severity") != "warn":
                hard_before_s20.append(f"{s['id']}:{g['check']}")
            if g["check"] == "refs_library" and g.get("count_check") is not False:
                hard_before_s20.append(f"{s['id']}:refs_library count")
    record("no hard word or reference-count block before journal selection (S20)",
           not hard_before_s20, str(hard_before_s20))
    new = {(s["id"][:3], g["check"]) for s in raw["stage"] for g in s["gate"] if g.get("since") == "1.10.0"}
    want = {("S01", "study_basis_recorded"), ("S03", "study_basis_recorded"),
            ("S03", "statistical_reporting_plan"), ("S04", "variable_crosswalk_confirmed"),
            ("S06", "statistical_reporting_plan"), ("S06", "raw_spot_check"),
            ("S07", "figure_text_planned"), ("S08", "reference_provenance"),
            ("S09", "displays_final_for_results"), ("S09", "effects_with_intervals"),
            ("S13", "argument_roles_covered"), ("S17", "reference_library_health"),
            ("S19", "explicit_confirmation"), ("S20", "display_plan_fits_journal"),
            ("S21", "declarations_assessed"), ("S21", "display_plan_fits_journal"),
            ("S24", "explicit_confirmation")}
    free = set(raw["freeform"]["globs"])
    record("every 1.10.0 gate is wired with since = 1.10.0; its files are declared freeform",
           new == want and {"02_data/variable_crosswalk.json", "03_analysis/spot_check.json",
                            "06_refs/coverage.json", "06_refs/uncited_reasons.json",
                            "08_submission/display_reallocation.json",
                            "08_submission/declarations_assessment.json"} <= free,
           str(sorted(want ^ new)))
    later = {s["id"]: {g["check"] for g in s["gate"]} for s in raw["stage"]}
    record("after S20 the journal's typed limits are hard (journal_limits_met at S22/S23/S25)",
           all("journal_limits_met" in later[s] for s in
               ("S22_polish", "S23_package", "S25_submission_audit")))
    r = tmp / "len"
    p = _paper(r, "S17_assemble")
    _w(p, "07_manuscript/full_manuscript.md",
       "# T\n\n# Abstract\n\nShort.\n\n# Introduction\n\n" + " ".join(["word"] * 4100) + "\n\n# References\n")
    from wfcore import gates
    pipe = registry.load()
    spec = next(g for g in pipe.stage("S17_assemble").gate if g["check"] == "draft_length_targets")
    res = gates.run_stage(pipe, State(p, ".wf").load(), p,
                          type("S", (), {"id": "S17_assemble", "gate": [spec], "skipped": False})())
    record("an over-long draft at S17 is a warning health check, not a block",
           res and not res[0].ok and not res[0].blocking and res[0].severity == "warn", res[0].detail)


def run_methods_refs(tmp: Path, record, section) -> None:
    from wfcore import registry
    from wfcore.checks import Ctx
    from wfcore.checks.refs import cited_entries
    from wfcore.state import State
    section("1.10.0 #2 Methods citations verified live at S08; #8 roles not counts")
    pipe = registry.load()
    s08 = pipe.stage("S08_methods")
    record("S08 re-fetches every Methods citekey live (reference_provenance cited_in, since 1.10.0)",
           any(g["check"] == "reference_provenance" and g.get("live") is True and g.get("cited_in")
               and g.get("since") == "1.10.0" for g in s08.gate))
    p = _paper(tmp / "mrefs", "S08_methods")
    _w(p, "07_manuscript/methods.md", "We used Cox models [@cox1972; @ghost2020].\n")
    ctx = Ctx(pipeline=pipe, state=State(p, ".wf").load(), project=p, stage=s08, spec={})
    entries, missing, present = cited_entries(ctx, [{"citekey": "cox1972", "pmid": "1"},
                                                    {"citekey": "other", "pmid": "2"}],
                                              ["07_manuscript/methods.md"])
    record("only the cited entries are live-checked; a cited key absent from the library fails",
           [e["citekey"] for e in entries] == ["cox1972"] and missing == ["ghost2020"]
           and present == ["07_manuscript/methods.md"])
    _w(p, "06_refs/library.json", {"entries": [{"citekey": k} for k in ("a", "b", "c", "d", "e", "f")]})
    _w(p, "06_refs/coverage.json", {"roles": {"background": ["a"], "gap": ["b"], "methods": ["c"],
                                              "comparison": ["d"]}})
    miss = _gate(p, "argument_roles_covered", "S13_reflib")
    _w(p, "06_refs/coverage.json", {"roles": {"background": ["a"], "gap": ["b"], "methods": ["c"],
                                              "comparison": ["d"]},
                                    "not_applicable": {"mechanism": "descriptive prevalence study, no mechanism claimed"}})
    ok = _gate(p, "argument_roles_covered", "S13_reflib")
    record("S13 judges argumentative-role coverage (a missing role fails, a reasoned n/a passes)",
           not miss.ok and "mechanism" in miss.detail and ok.ok, miss.detail + " | " + ok.detail)
    _w(p, "07_manuscript/full_manuscript.md", "# Introduction\n\nText [@a; @b; @c; @d; @e].\n")
    orphan = _gate(p, "reference_library_health", "S17_assemble")
    _w(p, "06_refs/uncited_reasons.json", {"f": "background reading superseded by @e"})
    band = _gate(p, "reference_library_health", "S17_assemble")
    record("S17: an uncited library entry needs a reason (block); the 45-60 band only warns",
           not orphan.ok and orphan.blocking and "f" in orphan.detail
           and not band.ok and band.severity == "warn", orphan.detail + " | " + band.detail)


def run_display(tmp: Path, record, section) -> None:
    section("1.10.0 #3 display plan re-checked for the journal; #10 legend caps advisory")
    p = _paper(tmp / "disp", "S20_journal")
    figs = [{"id": f"Figure {i}", "file": f"05_figures/out/F{i}.png"} for i in range(1, 5)]
    tabs = [{"id": f"Table {i}", "file": f"04_tables/main/T{i}.xlsx"} for i in range(1, 4)]
    _w(p, "01_protocol/artifact_plan.json", {"main_figures": figs, "main_tables": tabs,
                                             "supp_figures": [], "supp_tables": []})
    _w(p, "08_submission/target_journal.json", {"journal": "J", "limits": {
        "display_items": 6, "source": "guide: max 6 figures/tables"}})
    over = _gate(p, "display_plan_fits_journal", "S20_journal")
    _w(p, "08_submission/display_reallocation.json", {"moves": [
        {"id": "Table 3", "to": "supplementary", "new_id": "Table S1", "why": "sensitivity detail"}]})
    planned = _gate(p, "display_plan_fits_journal", "S20_journal")
    record("7 main displays against a 6-item journal fail without a reallocation plan, pass with one",
           not over.ok and "display_items 7/6" in over.detail and planned.ok, over.detail + " | " + planned.detail)
    for e in figs:
        e.update(text_plan={"in_figure": "axis titles and units", "legend": "groups and error bars"})
    figs[0].pop("text_plan")
    _w(p, "01_protocol/artifact_plan.json", {"main_figures": figs, "main_tables": tabs,
                                             "supp_figures": [], "supp_tables": []})
    tp = _gate(p, "figure_text_planned", "S07_artifacts")
    record("each figure plans in-figure text and legend together (text_plan)",
           not tp.ok and "Figure 1" in tp.detail, tp.detail)
    from wfcore import journalspec
    record("legend cap is hard only when the journal states one",
           journalspec.legend_cap({"limits": {}}) is None
           and journalspec.legend_cap({"limits": {"figure_legend_words": 150}}) == 150)
    q = _paper(tmp / "leg", "S07_artifacts")
    _w(q, "01_protocol/artifact_plan.json", {"main_figures": [{"id": "Figure 1"}], "main_tables": [
        {"id": "Table 1"}], "supp_figures": [], "supp_tables": []})
    _w(q, "05_figures/legends.md", "# Figure legends\n\n## Figure 1.\n" + "word " * 200 + "\n")
    _w(q, "04_tables/table_captions.md", "## Table 1.\nBaseline characteristics of the cohort by group. "
       "Abbreviations: none.\n")
    soft = _gate(q, "legends_cover_plan", "S07_artifacts")
    _w(q, "08_submission/target_journal.json", {"limits": {"figure_legend_words": 150, "source": "g"}})
    hard = _gate(q, "legends_cover_plan", "S07_artifacts")
    record("a 200-word legend warns by default and fails only under a journal cap",
           not soft.ok and soft.severity == "warn" and not hard.ok and hard.blocking,
           soft.detail + " | " + hard.detail)


def run_data(tmp: Path, record, section) -> None:
    section("1.10.0 #4 variable crosswalk + 10-case raw spot check; #6 reporting plan")
    p = _paper(tmp / "data", "S04_data")
    row = {"variable": "age", "source_field": "RIDAGEYR", "definition": "age at screening",
           "unit": "years", "coding": "continuous", "time_window": "at exam",
           "missing_rule": "complete case", "basis": "codebook DEMO_J p.3", "confirmed": True}
    _w(p, "02_data/variable_crosswalk.json", {"analysis_variables": ["age", "sex"], "rows": [row]})
    bad = _gate(p, "variable_crosswalk_confirmed", "S04_data")
    _w(p, "02_data/variable_crosswalk.json", {"analysis_variables": ["age", "sex"], "rows": [
        row, {**row, "variable": "sex", "source_field": "RIAGENDR", "unit": "none",
              "coding": "1=male 2=female", "confirmed": True}]})
    good = _gate(p, "variable_crosswalk_confirmed", "S04_data")
    record("every analysis variable needs a confirmed crosswalk row (source field, definition, unit, ...)",
           not bad.ok and "sex: no crosswalk row" in bad.detail and good.ok, bad.detail)
    from analysis.spotcheck import sample_ids, write_spot_check
    ids = [f"P{i:03d}" for i in range(25)]
    s1, s2 = sample_ids(ids, 7), sample_ids(list(reversed(ids)), 7)
    _w(p, "02_data/raw/demo.csv", "id,age\n")
    cases = [{"id": i, "raw_source": ["02_data/raw/demo.csv"],
              "checks": [{"variable": "age", "raw": 50, "derived": 50 if i != s1[0] else 51}]}
             for i in s1]
    write_spot_check(cases, seed=7, population=ids, project=p)
    mism = _gate(p, "raw_spot_check", "S06_protocol_final")
    cases[0]["checks"][0].update(match=False, explanation="raw age is top-coded at 80 in this release")
    write_spot_check(cases, seed=7, population=ids, project=p)
    expl = _gate(p, "raw_spot_check", "S06_protocol_final")
    record("10 reproducible cases (same sample from the same seed); a mismatch fails unless explained",
           s1 == s2 and len(s1) == 10 and not mism.ok and "without explanation" in mism.detail and expl.ok,
           mism.detail + " | " + expl.detail)
    plan_bad = "# Protocol\n\n## Statistical analysis plan\n\nCox models.\n"
    _w(p, "01_protocol/protocol_v1.md", plan_bad)
    nb = _gate(p, "statistical_reporting_plan", "S03_protocol", path="01_protocol/protocol_v1.md")
    _w(p, "01_protocol/protocol_v1.md", plan_bad + "\n### Statistical reporting plan\n\nPrimary comparisons: 1\n"
       "Multiplicity: none (single primary comparison)\nEffect measures: HR\nIntervals: 95% CI\n")
    ok = _gate(p, "statistical_reporting_plan", "S03_protocol", path="01_protocol/protocol_v1.md")
    _w(p, "07_manuscript/results.md", "Mortality differed between groups (P=0.004).\n")
    warn = _gate(p, "effects_with_intervals", "S09_results", path="07_manuscript/results.md")
    record("the protocol states comparisons, multiplicity, effect measures and intervals; "
           "P-value-only Results warn", not nb.ok and ok.ok and not warn.ok and warn.severity == "warn",
           nb.detail + " | " + warn.detail)


def run_declarations(tmp: Path, record, section) -> None:
    from wfcore import declarations as dc
    section("1.10.0 #5 declarations judged from study design + data source; ask only what is unknown")
    p = _paper(tmp / "decl", "S01_intake")
    _w(p, "01_protocol/idea.json", {"design": "cross-sectional"})
    missing = _gate(p, "study_basis_recorded", "S01_intake")
    public = {"study_design": "cross_sectional", "data_source": {
        "type": "public_database", "name": "NHANES 2017-2018", "third_party": True,
        "redistributable": True, "deidentified": True, "vulnerable_populations": []}}
    _w(p, "01_protocol/idea.json", public)
    ok = _gate(p, "study_basis_recorded", "S01_intake")
    record("S01 requires structured study_design and data_source", not missing.ok and ok.ok, missing.detail)
    a = dc.assess(public)
    record("public de-identified database: exempt + the database's own approval, no author question",
           not a["questions"] and "NCHS" in a["ethics"]["conclusion"]
           and "publicly available" in a["data_availability"]["text"], json.dumps(a)[:300])
    own = {"study_design": "cohort_retrospective", "data_source": {
        "type": "own_centre_retrospective", "name": "our hospital EMR", "third_party": False,
        "redistributable": False, "deidentified": True, "vulnerable_populations": []}}
    b = dc.assess(own)
    record("own-centre retrospective: only the approval number and the consent waiver are asked",
           [q["id"] for q in b["questions"]] == ["ethics_committee_and_number", "consent_waiver"]
           and "not publicly available" in b["data_availability"]["text"])
    _w(p, "01_protocol/idea.json", own)
    dc.write(p)
    _w(p, "07_manuscript/statements.md", "# Declarations\n\n## Ethics approval\nApproved.\n\n"
       "## Data availability\nOn request.\n")
    pend = _gate(p, "declarations_assessed", "S21_authors")
    dc.answer(p, "ethics_committee_and_number", "XH-2024-017")
    dc.answer(p, "consent_waiver", "yes")
    absent = _gate(p, "declarations_assessed", "S21_authors")
    _w(p, "07_manuscript/statements.md", "# Declarations\n\n## Ethics approval\nApproved by the "
       "hospital ethics committee (XH-2024-017); consent waived.\n\n## Data availability\nOn request.\n")
    done = _gate(p, "declarations_assessed", "S21_authors")
    record("S21 gate: open questions block; the author's approval number must reach the statement",
           not pend.ok and "open author question" in pend.detail and not absent.ok and done.ok,
           pend.detail + " | " + absent.detail + " | " + done.detail)


def run_discussion_numbers(tmp: Path, record, section) -> None:
    section("1.10.0 #7 prior-study numbers only with their citation; allowlist closed in Discussion")
    p = _paper(tmp / "disc", "S16_discussion")
    _w(p, "06_refs/refs.bib", "@article{smith2020, title={A}}\n@article{fake2021, title={B}}\n")
    _w(p, "06_refs/verified.json", {"records": {"smith2020": {"verified": True}}})
    _w(p, "03_analysis/results/number_allowlist.tsv", "3.4\tprior study value\n")
    rel = "07_manuscript/discussion.md"
    _w(p, rel, "Our HR was 1.87. A cohort reported an HR of 2.31 [@smith2020].\n")
    cited = _gate(p, "numbers_have_provenance", "S16_discussion", path=rel)
    _w(p, rel, "Our HR was 1.87. A cohort reported an HR of 2.31.\n")
    uncited = _gate(p, "numbers_have_provenance", "S16_discussion", path=rel)
    _w(p, rel, "Another study found 2.31 [@fake2021].\n")
    unverified = _gate(p, "numbers_have_provenance", "S16_discussion", path=rel)
    _w(p, rel, "Earlier work found 3.4.\n")
    allow = _gate(p, "numbers_have_provenance", "S16_discussion", path=rel)
    _w(p, "07_manuscript/methods.md", "The threshold was 3.4.\n")
    meth = _gate(p, "numbers_have_provenance", "S08_methods", path="07_manuscript/methods.md")
    _w(p, "07_manuscript/full_manuscript.md", "# Methods\n\nThreshold 3.4.\n\n# Discussion\n\n"
       "A trial reported 2.31 [@smith2020]. Others found 3.4.\n")
    full = _gate(p, "numbers_have_provenance", "S19_human_review", path="07_manuscript/full_manuscript.md")
    record("a cited prior number passes; uncited, unverified-citation and allowlisted Discussion numbers fail",
           cited.ok and not uncited.ok and "2.31" in uncited.detail and not unverified.ok
           and not allow.ok and meth.ok and not full.ok and "3.4" in full.detail and "2.31" not in full.detail,
           " | ".join(r.detail for r in (cited, uncited, unverified, allow, meth, full)))


def run_review(tmp: Path, record, section) -> None:
    import selftest_v181 as v181
    from wfcore import reviewrounds as rr
    from wfcore.state import State
    section("1.10.0 #11 optional export; #12 protected findings; #13 explicit confirmation sentence")
    p, env = v181._review_paper(tmp / "rev")

    def cli(*args, tool="tools/review_round.py"):
        args = v181.with_report(list(args), p)
        return subprocess.run([sys.executable, "-B", str(ROOT / tool), *args, "--project", str(p)],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    cli("start")
    kept = cli("close", "--findings", "major=1", "--finding", "F1", "numbers", "kept", "HR rounding")
    uncounted = cli("close", "--findings", "major=2", "--finding", "F1", "other", "changed", "x")
    closed = cli("close", "--findings", "major=2", "--finding", "F1", "grouping", "author", "Merge age bands",
                 "--finding", "F2", "other", "kept", "Style preference")
    record("a numbers/grouping/conclusion finding cannot be closed as kept; every finding is listed",
           kept.returncode != 0 and "cannot be kept" in kept.stderr and uncounted.returncode != 0
           and closed.returncode == 0 and "PENDING AUTHOR" in closed.stdout,
           kept.stderr[-200:] + uncounted.stderr[-200:] + closed.stdout[-200:])
    hr = (p / "07_manuscript/human_review.md").read_text(encoding="utf-8")
    words = [cli("decide", "no_further_review", "--words", w) for w in ("无需审阅", "OK", "可以")]
    blocked = cli("decide", "no_further_review", "--words", "我确认这一版")
    cli("author", "F1", "keep", "--words", "保持原分组")
    ok = cli("decide", "no_further_review", "--words", "我确认这一版。")
    rnd = rr.latest(p, "manuscript")
    record("summary lists pending author decisions; decide waits for them",
           "PENDING AUTHOR DECISION" in hr and blocked.returncode != 0 and "pending" in blocked.stderr,
           blocked.stderr[-200:])
    record("'无需审阅', 'OK', '可以' are not confirmation; '我确认这一版' is, with the version hash",
           all(w.returncode != 0 and "not a confirmation" in w.stderr for w in words)
           and ok.returncode == 0 and rnd.get("confirmed_version")
           and rnd["confirmed_version"] == rr.version_id(rr.inputs(p, "manuscript")),
           ok.stderr[-200:])
    g = _gate(p, "explicit_confirmation", "S19_human_review", scope="manuscript")
    record("explicit_confirmation gate passes on the confirmed version",
           g.ok and "我确认这一版" in g.detail, g.detail)
    st = State(p, ".wf").load()
    st.data["current"] = "S19_human_review"
    st.save()
    wf = subprocess.run([sys.executable, "-B", str(ROOT / "tools/wf.py"), "decide",
                         "manuscript_human_reviewed", "NO_FURTHER_REVIEW", "--why", "x" * 50],
                        capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    record("`wf decide` cannot record the user's approval from words",
           wf.returncode != 0 and "review_round.py" in wf.stdout, wf.stdout[-200:])
    record("no review export exists unless asked",
           not list((p / "07_manuscript").glob("review_packages/export-*.zip")))
    ex = cli("export")
    zips = list((p / "07_manuscript").glob("review_packages/export-*.zip"))
    names, mode = [], 0
    if zips:
        with zipfile.ZipFile(zips[0]) as zf:
            names = zf.namelist()
            mode = zf.getinfo("CHANGES.md").external_attr >> 16
    record("export on request: read-only files + a one-page change summary",
           ex.returncode == 0 and "CHANGES.md" in names and "07_manuscript/full_manuscript.md" in names
           and mode == 0o444, ex.stdout + ex.stderr)
    cards = "".join((ROOT / f"pipeline/stages/{n}.md").read_text(encoding="utf-8")
                    for n in ("S19_human_review", "S24_package_human_review"))
    record("cards ask for the exact sentence and mention export only as optional on request",
           cards.count("我确认这一版") >= 4 and "review_round.py export" in cards
           and "无需继续审阅”" not in cards)


def run(tmp: Path, record, section) -> None:
    tmp.mkdir(parents=True, exist_ok=True)
    old = os.environ.get("MEDPAPER_PROJECT")
    try:
        run_order(tmp, record, section)
        run_methods_refs(tmp, record, section)
        run_display(tmp, record, section)
        run_data(tmp, record, section)
        run_declarations(tmp, record, section)
        run_discussion_numbers(tmp, record, section)
        run_review(tmp, record, section)
    finally:
        if old is None:
            os.environ.pop("MEDPAPER_PROJECT", None)
        else:
            os.environ["MEDPAPER_PROJECT"] = old
