"""1.25.1 regression tests: confident writing never hides an unfavourable or null result, a
limitation or the uncertainty of an estimate.

R1 the primary-first wording and the three keep rules (writing_voice.md, writer, editor,
RUBRIC), R2 the deterministic checks (pre-specified outcomes reported, primary first, estimates
with intervals, limitations present; pinned papers warn), R3 the editor's polished step refuses
an edit that breaks them, R4 the reviewer's selective-reporting check, and the release policy.
Synthetic fixtures only - no real paper, dataset, network or browser. Called from
tools/selftest.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from selftest_v1140 import _gate, _paper, _w  # noqa: E402
from selftest_v1250 import _pin  # noqa: E402

IDEA = {"study_design": "cohort_retrospective", "design": "retrospective cohort",
        "outcomes": {"primary": [{"name": "All-cause mortality", "definition": "death",
                                  "timing": "1 year"}],
                     "secondary": [{"name": "Hospitalisation for heart failure"}, "aki"]},
        "data_source": {"type": "own_centre_retrospective", "name": "Hospital registry"}}
DICT = {"terms": [{"internal": "aki", "label": "Acute kidney injury", "abbreviation": "AKI",
                   "definition": "KDIGO stage 1 or higher", "role": "outcome"}]}
RESULTS = """# Results

Of 4210 patients, 610 died during the first year. All-cause mortality did not differ between
the groups (HR 0.97, 95% CI 0.85-1.11). Hospitalisation for heart failure was less frequent
with the new treatment (HR 0.81, 95% CI 0.70-0.94). Each 1-unit higher baseline creatinine was
associated with acute kidney injury (OR per 1-unit increase, 1.08; 95% CI 1.02-1.15), and the
incidence of AKI by group is shown in Table S3.
"""
DISC = """# Discussion

In this cohort, all-cause mortality did not differ with the new treatment, while
hospitalisation for heart failure was less frequent [@a2020].

These findings agree with an earlier trial [@b2021].

This study has limitations. Treatment was not randomised, so residual confounding by
indication may remain and the associations cannot establish causation. Creatinine was
measured at the discretion of clinicians, which probably led to under-ascertainment of acute
kidney injury and biased its estimate towards the null.
"""


def run(tmp: Path, record, section, only: str = "") -> None:
    tmp.mkdir(parents=True, exist_ok=True)
    for name, fn in GROUPS:
        if not only or name in only.split():
            fn(tmp / name, record, section)


def _proj(path: Path, stage: str, results: str = RESULTS, idea: dict | None = None) -> Path:
    p = _paper(path, stage)
    _w(p, "01_protocol/idea.json", idea or IDEA)
    _w(p, "01_protocol/display_dictionary.json", DICT)
    _w(p, "07_manuscript/results.md", results)
    return p


# ------------------------------------------------------------------------------ R1
def run_wording(tmp: Path, record, section) -> None:
    from wfcore import sectionpolish as sp
    section("1.25.1 R1: primary outcome first; null results, intervals and limitations kept")
    voice = (ROOT / "reference/writing_voice.md").read_text(encoding="utf-8")
    writer = (ROOT / ".kiro/agents/medpaper-clinical-writer.md").read_text(encoding="utf-8")
    editor = (ROOT / ".kiro/agents/medpaper-medical-editor.md").read_text(encoding="utf-8")
    voice, writer, editor, rubric = (" ".join(t.split()) for t in (voice, writer, editor, sp.RUBRIC))
    old = "strongest pre-specified"
    record("R1 'Lead with the strongest pre-specified finding' is gone from the voice file, the "
           "writer, the editor and the RUBRIC; the primary-first rule replaces it",
           all(old not in t for t in (voice, writer, editor, rubric))
           and "Lead with the main question and its answer" in voice
           and "lead with the main question and its answer" in writer
           and "never displaces or outranks a null primary result" in voice
           and "never displaces or outranks a null primary result" in writer
           and "primary outcome comes first" in rubric and "primary outcome comes first" in editor)
    record("R1 three keep rules (same prominence for null results, intervals not hedging words, "
           "limitations always present) and the absorbed / kept / not adopted lists",
           "K1 Null and unfavourable results" in voice and "K2 Uncertainty is expressed by "
           "intervals" in voice and "K3 Limitations are stated plainly" in voice
           and "Absorbed from the source idea" in voice and "no work-report narration" in voice
           and "Kept, because a medical paper must report them" in voice
           and "let the strongest result lead in place of the primary outcome" in voice
           and "Keep (1.25.1)" in writer and "Never remove, soften" in editor)


# ------------------------------------------------------------------------------ R2 a / c
def run_outcomes(tmp: Path, record, section) -> None:
    from wfcore import outcomereport as orep
    section("1.25.1 R2a/c: every pre-specified outcome reported; every estimate with its CI")
    p = _proj(tmp / "good", "S09_results")
    oc = orep.declared_outcomes(p)
    g = _gate(p, "prespecified_outcomes_reported", "S09_results")
    record("R2a idea.json outcomes (protocol terms and the display-dictionary label 'Acute kidney "
           "injury' for 'aki'); a supplementary table citation counts; a null primary passes",
           g.ok and [o["name"] for o in oc["primary"]] == ["All-cause mortality"]
           and "Acute kidney injury" in oc["secondary"][1]["terms"], g.detail)
    miss = RESULTS.replace("Hospitalisation for heart failure was less frequent\nwith the new "
                           "treatment (HR 0.81, 95% CI 0.70-0.94). ", "")
    q = _proj(tmp / "miss", "S09_results", miss)
    gq = _gate(q, "prespecified_outcomes_reported", "S09_results")
    r = _proj(tmp / "pinned", "S09_results", miss)
    _pin(r, "1.25.0")
    gr = _gate(r, "prespecified_outcomes_reported", "S09_results")
    n = _proj(tmp / "noidea", "S09_results", idea={"study_design": "cohort_retrospective"})
    gn = _gate(n, "prespecified_outcomes_reported", "S09_results")
    record("R2a a secondary outcome dropped from the Results blocks on 1.25.1; a 1.25.0 paper "
           "warns; no structured outcomes -> warning, never a pass",
           gq.blocking and "Hospitalisation for heart failure" in gq.detail
           and not gr.ok and gr.severity == "warn" and "wf migrate --yes" in gr.detail
           and not gn.ok and gn.severity == "warn", gq.detail + " | " + gr.detail)
    _w(p, "07_manuscript/abstract.md", "**Results:** Hospitalisation for heart failure was less "
       "frequent (HR 0.81, 95% CI 0.70-0.94).\n\n**Conclusions:** Fewer admissions.\n")
    ga = _gate(p, "prespecified_outcomes_reported", "S17_assemble", abstract=True)
    _w(p, "07_manuscript/abstract.md", "**Methods:** We estimated hazard ratios for patients aged "
       "65 years and older.\n\n**Results:** All-cause mortality did not differ (HR 0.97, 95% CI "
       "0.85-1.11); hospitalisation for heart failure was less frequent (HR 0.81, 95% CI "
       "0.70-0.94).\n\n**Conclusions:** No mortality difference.\n")
    gb = _gate(p, "prespecified_outcomes_reported", "S17_assemble", abstract=True)
    ge = _gate(p, "effects_with_intervals", "S17_assemble", path="07_manuscript/abstract.md")
    record("R2a the primary outcome must be in the Abstract results whatever its direction "
           "(missing -> block; present -> pass); a Methods sentence naming hazard ratios is no "
           "estimate", ga.blocking and "Abstract results" in ga.detail and gb.ok and ge.ok,
           ga.detail + " | " + ge.detail)
    fp = ("Of 1204 patients, 312 (25.9%) died (P = 0.03). HR-positive tumours were present in "
          "120 patients (35%). The signal persisted (IC 1.2, IC025 0.8). Each 1-unit increase in "
          "BMI raised the odds (OR per 1-unit increase, 1.08; 95% CI 1.02-1.15). The mean "
          "difference was 2.1 points (95% credible interval 0.4 to 3.8).")
    bad = "The odds ratio for death was 1.40 (P = 0.02). Mortality was higher (aHR 1.3)."
    record("R2c no false positives (counts, percentages, P values, 'HR-positive', IC with IC025, "
           "'per 1-unit', a credible interval); an odds ratio with only a P value and an aHR "
           "without CI are caught",
           orep.estimates_without_interval(fp) == [] and len(orep.estimates_without_interval(bad)) == 2,
           str(orep.estimates_without_interval(fp)) + str(orep.estimates_without_interval(bad)))
    b = _proj(tmp / "est", "S09_results", RESULTS + "\nThe odds ratio for readmission was 1.40 "
              "(P = 0.02).\n")
    gb1 = _gate(b, "effects_with_intervals", "S09_results", path="07_manuscript/results.md")
    _pin(b, "1.25.0")
    gb2 = _gate(b, "effects_with_intervals", "S09_results", path="07_manuscript/results.md")
    gok = _gate(p, "effects_with_intervals", "S09_results", path="07_manuscript/results.md")
    record("R2c estimates_have_intervals (inside effects_with_intervals): blocks in the Results on "
           "1.25.1, warns on a pinned paper, passes when every estimate has its CI",
           gb1.blocking and "estimates_have_intervals" in gb1.detail and not gb2.ok
           and gb2.severity == "warn" and gok.ok, gb1.detail + " | " + gok.detail)


# ------------------------------------------------------------------------------ R2 b
MS = """# Title

# Abstract

**Results:** Hospitalisation for heart failure was less frequent (HR 0.81, 95% CI 0.70-0.94).
All-cause mortality did not differ (HR 0.97, 95% CI 0.85-1.11).

**Conclusions:** Admissions were fewer.

# Results

{results}

# Discussion

{disc}
"""


def run_primary(tmp: Path, record, section) -> None:
    from wfcore import outcomereport as orep
    section("1.25.1 R2b: the primary outcome leads, a null primary is never displaced")
    p = _proj(tmp / "p", "S22_polish")
    bad_disc = DISC.replace("In this cohort, all-cause mortality did not differ with the new "
                            "treatment, while\nhospitalisation", "In this cohort, "
                            "hospitalisation")
    _w(p, "07_manuscript/full_manuscript.md", MS.format(results=RESULTS.split("\n", 2)[2],
                                                         disc=bad_disc.split("\n", 2)[2]))
    g22 = _gate(p, "primary_first", "S22_polish", block=True, manuscript=True)
    _w(p, "07_manuscript/abstract.md", MS.split("# Results")[0].split("# Abstract")[1])
    _w(p, "07_manuscript/discussion.md", bad_disc)
    g17 = _gate(p, "primary_first", "S17_assemble")
    q = _proj(tmp / "pin", "S22_polish")
    _w(q, "07_manuscript/full_manuscript.md", (p / "07_manuscript/full_manuscript.md").read_text(
        encoding="utf-8"))
    _pin(q, "1.25.0")
    gq = _gate(q, "primary_first", "S22_polish", block=True, manuscript=True)
    good = MS.replace("**Results:** Hospitalisation for heart failure was less frequent (HR 0.81, "
                      "95% CI 0.70-0.94).\nAll-cause mortality did not differ (HR 0.97, 95% CI "
                      "0.85-1.11).", "**Results:** All-cause mortality did not differ (HR 0.97, "
                      "95% CI 0.85-1.11). Hospitalisation for heart failure was less frequent "
                      "(HR 0.81, 95% CI 0.70-0.94).")
    r = _proj(tmp / "good", "S22_polish")
    _w(r, "07_manuscript/full_manuscript.md", good.format(results=RESULTS.split("\n", 2)[2],
                                                           disc=DISC.split("\n", 2)[2]))
    gr = _gate(r, "primary_first", "S22_polish", block=True, manuscript=True)
    record("R2b null primary (CI spans 1) displaced by a secondary result: blocks at S22 on "
           "1.25.1, warns at S17 and on a pinned paper; primary first passes",
           orep.primary_is_null(p, RESULTS) and g22.blocking and "secondary result leads" in g22.detail
           and not g17.ok and g17.severity == "warn" and not gq.ok and gq.severity == "warn"
           and gr.ok, g22.detail + " | " + gr.detail)


# ------------------------------------------------------------------------------ R2 d
FAERS = {"study_design": "secondary_analysis", "design": "disproportionality analysis",
         "outcomes": {"primary": ["Acute pancreatitis"], "secondary": []},
         "data_source": {"type": "public_database", "name": "FAERS"}}
FDISC = """# Discussion

Semaglutide was associated with reports of acute pancreatitis (ROR 2.1, 95% CI 1.8-2.5).

Our study has limitations. Disproportionality signals do not measure incidence or risk, and
spontaneous reports are affected by under-reporting and stimulated reporting after safety
warnings. Indication and concomitant drugs were often missing from the reports, which may
have confounded the association in either direction.
"""


def run_limits(tmp: Path, record, section) -> None:
    from wfcore import outcomereport as orep
    section("1.25.1 R2d: a limitations paragraph with the design's essential caveat")
    p = _proj(tmp / "faers", "S16_discussion", idea=FAERS)
    _w(p, "07_manuscript/discussion.md", FDISC)
    ok = _gate(p, "limitations_present", "S16_discussion", path="07_manuscript/discussion.md")
    _w(p, "07_manuscript/discussion.md", FDISC.replace(
        "Disproportionality signals do not measure incidence or risk, and\nspontaneous reports "
        "are affected by under-reporting and stimulated reporting after safety\nwarnings. ", ""))
    nocav = _gate(p, "limitations_present", "S16_discussion", path="07_manuscript/discussion.md")
    _w(p, "07_manuscript/discussion.md", FDISC.split("Our study has")[0])
    nolim = _gate(p, "limitations_present", "S16_discussion", path="07_manuscript/discussion.md")
    _w(p, "07_manuscript/discussion.md", FDISC.split("Our study has")[0]
       + "This study has several limitations. The results should be interpreted with caution.\n")
    generic = _gate(p, "limitations_present", "S16_discussion", path="07_manuscript/discussion.md")
    c = _proj(tmp / "cohort", "S16_discussion")
    _w(c, "07_manuscript/discussion.md", DISC)
    gc = _gate(c, "limitations_present", "S16_discussion", path="07_manuscript/discussion.md")
    _pin(c, "1.25.0")
    _w(c, "07_manuscript/discussion.md", DISC.replace("residual confounding by\nindication may "
                                                      "remain and the associations cannot "
                                                      "establish causation", "groups differed"))
    gpin = _gate(c, "limitations_present", "S16_discussion", path="07_manuscript/discussion.md")
    record("R2d disproportionality (FAERS): passes with 'not incidence or risk' + reporting bias; "
           "blocks without the caveat, without a limitations paragraph and with a generic one; a "
           "cohort needs residual confounding and no causal inference (pinned paper: warning)",
           orep.design_key(p) == "disproportionality" and ok.ok and nocav.blocking
           and "disproportionality" in nocav.detail and nolim.blocking
           and "no limitations paragraph" in nolim.detail and generic.blocking
           and "0 specific" in generic.detail and orep.design_key(c) == "observational" and gc.ok
           and not gpin.ok and gpin.severity == "warn",
           " | ".join(x.detail[:160] for x in (ok, nocav, nolim, generic, gc, gpin)))


# ------------------------------------------------------------------------------ R3
def run_editor(tmp: Path, record, section) -> None:
    from wfcore import sectionpolish as sp
    section("1.25.1 R3: the polished step refuses an edit that hides a result, an interval or a "
            "limitation")
    p = _proj(tmp / "p", "S16_discussion")
    _w(p, "07_manuscript/discussion.md", DISC)
    for stage, sec in (("S09_results", "results"), ("S16_discussion", "discussion")):
        _w(p, f".wf/writer_bundle/{stage}/MANIFEST.md", "# bundle\n")
        sp.record_draft(p, stage, sec)

    def attempt(sec: str, text: str) -> str:
        _w(p, f".wf/editor_bundle/{sec}/polished.md", text)
        try:
            sp.accept_polished(p, sec)
            return "accepted"
        except ValueError as exc:
            return str(exc)
    split = attempt("results", RESULTS.replace("(HR 0.97, 95% CI 0.85-1.11).",
                                               "(HR 0.97). The 95% CI was 0.85-1.11."))
    dropped = attempt("discussion", DISC.replace(
        "Treatment was not randomised, so residual confounding by\nindication may remain and the "
        "associations cannot establish causation. ", ""))
    fine = attempt("discussion", DISC.replace("These findings agree with an earlier trial",
                                              "This agrees with an earlier trial"))
    record("R3 an estimate separated from its CI and a dropped design caveat are refused "
           "(numbers unchanged, so only the 1.25.1 re-check catches them); a plain edit is "
           "accepted", "separated 1 effect estimate" in split and "caveat:observational" in dropped
           and fine == "accepted", split[:200] + " | " + dropped[:200] + " | " + fine[:200])


# ------------------------------------------------------------------------------ R4 + release
def run_release(tmp: Path, record, section) -> None:
    from wfcore import registry, reviewrounds
    from wfcore.state import State
    section("1.25.1 R4 + release: selective-reporting review, one migration event, docs")
    p = _proj(tmp / "rv", "S18_independent_review")
    man = reviewrounds.brief(p, {"id": "r1", "scope": "manuscript", "mode": "full"}, "B")
    sci = reviewrounds.brief(p, {"id": "s1", "scope": "science", "mode": "full"}, "B")
    rev = (ROOT / ".kiro/agents/medpaper-reviewer.md").read_text(encoding="utf-8")
    record("R4 S18 and science briefs ask for selective reporting and list the pre-specified "
           "outcomes; the reviewer prompt names the findings and categories",
           "selective reporting" in man and "selective reporting" in sci
           and "Pre-specified outcomes (protocol): primary All-cause mortality" in man
           and "1.25.1 - selective reporting" in rev and "null primary outcome buried" in rev,
           man[-400:])
    q = tmp / "mig"
    q.mkdir(parents=True, exist_ok=True)
    st = State(q, ".wf").create("medpaper", "1.25.0", "S09_results")
    before = sorted(x.name for x in q.rglob("*"))
    st.migrate_pipeline("1.25.1", [s.id for s in registry.load().stages])
    st.migrate_pipeline("1.25.1", [s.id for s in registry.load().stages])
    notes = [e for e in st.data["events"] if e["kind"] == "requirements_changed"
             and str(e.get("detail", "")).startswith("1.25.1")]
    pipe = registry.load()
    gates = {(s.id, g["check"]) for s in pipe.stages for g in s.gate if g.get("since") == "1.25.1"}
    record("release: pipeline 1.25.1; one 1.25.1 event for a 1.25.0 paper (pinned, files "
           "untouched); new gates carry since 1.25.1 at S09/S16/S17/S22",
           pipe.meta.get("version") == "1.25.1" and len(notes) == 1
           and "wf migrate --yes" in notes[0]["detail"] and st.engine_pin == "1.25.0"
           and before == sorted(x.name for x in q.rglob("*"))
           and {("S09_results", "prespecified_outcomes_reported"),
                ("S16_discussion", "limitations_present"), ("S17_assemble", "primary_first"),
                ("S17_assemble", "effects_with_intervals"),
                ("S22_polish", "primary_first")} <= gates, str(sorted(gates)))
    cards = {s.id: (ROOT / "pipeline" / s.card).read_text(encoding="utf-8") for s in pipe.stages}
    skill = (ROOT / ".kiro/skills/medpaper-pipeline/SKILL.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    record("docs: S09/S16/S17/S22 cards name the 1.25.1 rules; SKILL one line; README 1.25.1; "
           "every card within the limit",
           "1.25.1" in cards["S09_results"] and "limitations_present" in cards["S16_discussion"]
           and "primary_first" in cards["S17_assemble"] and "1.25.1" in cards["S22_polish"]
           and "1.25.1" in skill and len(skill) <= 9000 and "## 1.25.1" in readme
           and "`1.25.1`" in readme
           and max(len(c) for c in cards.values()) <= registry.CARD_MAX_CHARS,
           str({k: len(v) for k, v in cards.items() if len(v) > 3900}) + f" skill={len(skill)}")


GROUPS = [("wording", run_wording), ("outcomes", run_outcomes), ("primary", run_primary),
          ("limits", run_limits), ("editor", run_editor), ("release", run_release)]
