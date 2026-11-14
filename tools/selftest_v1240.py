"""1.24.0 regression tests: confident, non-defensive clinical writing.

A agent prompts and rubric, B spin and defensive-writing checks (polish.py, the section-language
gate, the editor bundle), C reference/writing_voice.md in the writer and editor bundles, D cards
and release policy. Synthetic fixtures only - no real paper, dataset, network or browser.
Called from tools/selftest.py.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from selftest_v1140 import _gate, _out, _paper, _run, _w  # noqa: E402

DISC = "07_manuscript/discussion.md"


def run(tmp: Path, record, section, only: str = "") -> None:
    tmp.mkdir(parents=True, exist_ok=True)
    for name, fn in GROUPS:
        if not only or name in only.split():
            fn(tmp / name, record, section)


def _pol():
    spec = importlib.util.spec_from_file_location("medpaper_polish_v1240",
                                                  ROOT / "tools" / "text" / "polish.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _pin(p: Path, version: str) -> None:
    st = json.loads((p / ".wf/state.json").read_text(encoding="utf-8"))
    st["engine_pin"] = version
    (p / ".wf/state.json").write_text(json.dumps(st), encoding="utf-8")


def _kinds(pol, text: str, rel: str = DISC, novelty: bool = False) -> list[str]:
    return [x["kind"] for x in pol.lint_voice(rel, text, novelty)]


def _labels(pol, text: str, tier: str | None = None, spin_block: bool = True) -> list[str]:
    return [x["label"] for x in pol.lint_ai(DISC, text, {}, spin_block)
            if tier is None or x["tier"] == tier]


# ------------------------------------------------------------------------------ A
def run_prompts(tmp: Path, record, section) -> None:
    from wfcore import adapters, sectionpolish as sp
    section("1.24.0 A: confident, not defensive - writer, editor, rubric and reviewer")
    agents = ROOT / ".kiro/agents"
    w = (agents / "medpaper-clinical-writer.md").read_text(encoding="utf-8")
    e = (agents / "medpaper-medical-editor.md").read_text(encoding="utf-8")
    r = re.sub(r"\s+", " ", (agents / "medpaper-reviewer.md").read_text(encoding="utf-8"))
    principle = "Organise the narrative, never select the evidence"
    record("A1 the clinical writer has 'Confident, not defensive (1.24.0)' with W1-W5, the "
           "principle, estimate + CI for negative results and no new limitation in the conclusion",
           "Confident, not defensive (1.24.0)" in w and principle in w
           and all(f"W{i} " in w for i in range(1, 6)) and "trend toward significance" in w
           and "S02 publishability" in w and "adds no new limitation" in w
           and "direction of bias" in w and not adapters.agent_scope_problems(
               "medpaper-clinical-writer", w))
    record("A2 the medical editor has 'Defensive writing (1.24.0)' E1-E4 with the keep-list test; "
           "the editor-bundle RUBRIC says the same; reports, cases and patients are never merged",
           "Defensive writing (1.24.0)" in e and all(f"E{i} " in e for i in range(1, 5))
           and "would removing it mislead a reader?" in e and "Defensive writing (1.24.0)" in sp.RUBRIC
           and "would removing it mislead a reader?" in sp.RUBRIC and "never merged" in sp.RUBRIC
           and "Prior studies have shown" in sp.RUBRIC and "serves as" in sp.RUBRIC
           and not adapters.agent_scope_problems("medpaper-medical-editor", e))
    record("A3 the reviewer checks spin (conclusion_strength) and defensive writing (other, "
           "presentation) after the 1.19 Discussion checks",
           "1.24.0 - spin and defensive writing" in r and "`conclusion_strength`" in r
           and "more than six limitation items" in r and r.index("1.19.0 - Discussion check")
           < r.index("1.24.0 - spin"))


# ------------------------------------------------------------------------------ B1
SPIN_POS = ["Mortality showed a trend toward significance (P = 0.07).",
            "The difference was marginally significant.",
            "The association approached statistical significance.",
            "There was borderline significance for stroke.",
            "The effect was nearly significant."]
SPIN_NEG = ("The P for trend was 0.40. The temporal trend in reporting was stable. A trend test "
            "across quartiles was performed. The association was significant (P = 0.01).")


def run_spin(tmp: Path, record, section) -> None:
    from wfcore import sectionpolish as sp
    pol = _pol()
    section("1.24.0 B1: spin on non-significant results blocks (since 1.24.0)")
    pos = [any(lab.startswith("spin_nonsignificant") for lab in _labels(pol, s, "A"))
           for s in SPIN_POS]
    neg = [lab for lab in _labels(pol, SPIN_NEG) if lab.startswith("spin")]
    old = [lab for lab in _labels(pol, SPIN_POS[0], "B", spin_block=False)
           if lab.startswith("spin")]
    record("B1 each spin phrase is tier A; 'P for trend', 'temporal trend', 'trend test' do not "
           "match; a paper pinned earlier sees it as tier B", all(pos) and not neg and bool(old),
           f"{pos} {neg} {old}")
    text = ("# Results\n\nAmong 412 patients, mortality was 12.0% and 14.1% (HR 0.88, 95% CI "
            "0.76-1.01); this showed a trend toward significance.\n")
    p = _paper(tmp / "new", "S09_results")
    _w(p, "07_manuscript/results.md", text)
    g_new = _gate(p, "section_language_clean", "S09_results", path="07_manuscript/results.md")
    q = _paper(tmp / "old", "S09_results")
    _pin(q, "1.23.0")
    _w(q, "07_manuscript/results.md", text)
    g_old = _gate(q, "section_language_clean", "S09_results", path="07_manuscript/results.md")
    lp_new = sp.language_problems(p, "results", text)
    lp_old = sp.language_problems(q, "results", text)
    record("B1 section_language_clean blocks spin on a 1.24.0 paper; a 1.23.0 pin only warns; the "
           "editor's polished text is refused for spin only on 1.24.0+",
           not g_new.ok and "trend toward significance" in g_new.detail
           and getattr(g_old, "severity", "") == "warn" and "blocking" not in g_old.detail
           and any("spin" in x for x in lp_new) and not any("spin" in x for x in lp_old),
           g_new.detail[:200] + " | " + g_old.detail[:200])


# ------------------------------------------------------------------------------ B2
def run_tierb(tmp: Path, record, section) -> None:
    pol = _pol()
    section("1.24.0 B2: tier-B de-AI and defensive-writing warnings")
    cases = {
        "ing_tail": ("Statin use was associated with fewer events, highlighting its value.",
                     "Statin use was associated with fewer events, reflecting lower LDL levels."),
        "copula_avoidance": ("Troponin serves as a marker of injury.",
                             "Patients served as their own controls."),
        "self_weakening": ("Unfortunately, the effect was merely modest.",
                           "Ten patients failed to attend follow-up."),
    }
    res = {}
    for k, (pos, neg) in cases.items():
        res[k] = (any(lab.startswith(k) for lab in _labels(pol, pos, "B")),
                  not any(lab.startswith(k) for lab in _labels(pol, neg)))
    record("B2 ing_tail, copula_avoidance and self_weakening warn (tier B); 'reflecting', "
           "'served as their own controls' and 'failed to attend' do not",
           all(a and b for a, b in res.values()), str(res))
    lim = ("This study has limitations. Reports are voluntary, which probably biases estimates "
           "away from the null; results should be interpreted with caution.")
    pre_out = "We emphasize that the cohort was large.\n\n" + lim
    pre_twice = ("This study has limitations. We do not claim causality. Reporting is voluntary "
                 "and we do not claim incidence.")
    record("B2 defensive_prebuttal warns once outside the limitations paragraph or twice anywhere; "
           "one caveat in the limitations paragraph does not",
           "defensive_prebuttal" in _kinds(pol, pre_out)
           and "defensive_prebuttal" in _kinds(pol, pre_twice)
           and "defensive_prebuttal" not in _kinds(pol, lim))
    vague = "Studies have shown that the drug lowers blood pressure. Experts recommend it."
    cited = ("Studies have shown that the drug lowers blood pressure [@smith2020]. Prior studies "
             "reported similar effects [@lee2019].")
    record("B2 vague_attribution warns without a citation in the same sentence, not with one",
           _kinds(pol, vague).count("vague_attribution") == 2
           and "vague_attribution" not in _kinds(pol, cited))


# ------------------------------------------------------------------------------ B3
def run_structure(tmp: Path, record, section) -> None:
    from wfcore import voice
    pol = _pol()
    section("1.24.0 B3: repeated caveats, synonym cycling, limitations volume, priority claims")
    rc = "Residual confounding may explain part of the association."
    rep = f"{rc} {rc}\n\n{rc}\n\nThis study has limitations. {rc}"
    once = f"{rc}\n\nThis study has limitations. {rc} {rc}"
    full = ("# Abstract\n\n" + f"{rc} {rc}\n\n# Discussion\n\n{rc} {rc}\n\nThis study has "
            "limitations. Exposure was self-reported.\n")
    record("B3 caveat_repeat warns at three repeats outside its place in the limitations "
           "paragraph; the first statement there and the abstract are counted separately",
           "caveat_repeat" in _kinds(pol, rep) and "caveat_repeat" not in _kinds(pol, once)
           and "caveat_repeat" not in _kinds(pol, full, "07_manuscript/full_manuscript.md"),
           str(_kinds(pol, rep)) + str(_kinds(pol, once)))
    syn = ("Patients were older. Participants had diabetes. Subjects were treated. Patients "
           "improved. Participants were followed. Subjects died.")
    units = ("Patients were older. Reports were voluntary. Cases had diabetes. Patients improved. "
             "Reports were coded. Cases died. Participants were followed.")
    intro = (syn + "\n\nWe therefore examined outcomes in patients treated with the drug.")
    record("B3 synonym_cycling warns when three population names are each used twice; reports and "
           "cases are not population synonyms; Introduction background sentences are exempt",
           "synonym_cycling" in _kinds(pol, syn) and "synonym_cycling" not in _kinds(pol, units)
           and "synonym_cycling" not in _kinds(pol, intro, "07_manuscript/introduction.md"))
    many = ("This study has limitations. First, a. Second, b. Third, c. Fourth, d. Fifth, e. "
            "Sixth, f. Seventh, g.")
    few = "This study has limitations. First, a. Second, b. Third, c. Fourth, d."
    hedge = ("This study has limitations. Exposure was self-reported; however, a strength is the "
             "size. Follow-up was short, although another strength is complete linkage.")
    record("B3 limitations_volume warns above six items or with two 'however ... strength' hedges; "
           "four items without hedges pass",
           "limitations_volume" in _kinds(pol, many) and "limitations_volume" in _kinds(pol, hedge)
           and "limitations_volume" not in _kinds(pol, few))
    claim = "This is the first study to examine this association in a national cohort."
    plain = ("We examined this association in a national cohort of 412 000 adults; 1204 unique "
             "patients were treated with novel oral anticoagulants.")
    p = _paper(tmp / "p", "S16_discussion")
    clear0 = voice.novelty_clear(p)
    _w(p, ".wf/publishability.json", {"schema": 1, "checkpoints": {"S02": {"evidence": {
        "novelty": {"query": "drug AND outcome", "count": 0}}}}, "additional": []})
    record("B3 priority_claim warns unless the S02 publishability record found no comparable "
           "study; 'unique patients' and 'novel oral anticoagulants' are not claims",
           "priority_claim" in _kinds(pol, claim) and "priority_claim" not in _kinds(pol, plain)
           and not clear0 and voice.novelty_clear(p)
           and "priority_claim" not in _kinds(pol, claim, novelty=voice.novelty_clear(p)))


# ------------------------------------------------------------------------------ B4 + C
METHODS = ("# Methods\n\nWe conducted a cohort study of adults treated in two hospitals in 2023. "
           "Troponin serves as a marker of myocardial injury. Studies have shown that the "
           "marker predicts death.\n")


def run_bundles(tmp: Path, record, section) -> None:
    from wfcore import clinical, sectionpolish as sp
    section("1.24.0 B4/C: writing_voice.md in the bundles; warnings listed for the editor")
    ref = ROOT / "reference/writing_voice.md"
    txt = ref.read_text(encoding="utf-8")
    ident = re.findall(r"(?<![@\w-])[a-z][a-z0-9]*(?:_[a-z0-9]+)+(?![\w-])", txt)
    record("C writing_voice.md (<= 80 lines): the principle, adapted rules with bad -> good "
           "examples, the rules not adopted and why, both MIT idea sources; clean for the bundle",
           len(txt.splitlines()) <= 80 and "Organise the narrative, never select the evidence" in txt
           and "Ideas not adopted" in txt and "outcome switching" in txt
           and "Adkid-Zephyr/anti-defensive-writing-Skill (MIT)" in txt
           and "Worigin0314/academic-defensive-writing-auditor (MIT)" in txt
           and txt.count("- Bad:") >= 5 and not clinical.engineering_hits(txt, {}) and not ident,
           str(ident)[:200])
    p = _paper(tmp / "p", "S14_introduction")
    b = _run(p, "tools/manuscript/writer_bundle.py", "build", "--stage", "S14_introduction",
             "--project", p)
    man = p / ".wf/writer_bundle/S14_introduction/MANIFEST.md"
    man_t = man.read_text(encoding="utf-8") if man.is_file() else ""
    src = (ROOT / "tools/manuscript/writer_bundle.py").read_text(encoding="utf-8")
    m = re.search(r"VOICE_STAGES = \(([^)]*)\)", src)
    stages = set(re.findall(r'"(S\d\d_\w+)"', m.group(1))) if m else set()
    record("C the S08/S09/S14/S16/S17 writer bundles carry writing_voice.md (listed in MANIFEST)",
           b.returncode == 0 and "- writing_voice.md" in man_t
           and (man.parent / "writing_voice.md").read_text(encoding="utf-8") == txt
           and stages == {"S08_methods", "S09_results", "S14_introduction", "S16_discussion",
                          "S17_assemble"}, _out(b)[-300:] + str(stages))
    q = _paper(tmp / "q", "S08_methods")
    _w(q, "07_manuscript/methods.md", METHODS)
    _w(q, ".wf/writer_bundle/S08_methods/MANIFEST.md", "# Writer bundle (S08_methods)\n\nWrite: "
                                                        "07_manuscript/methods.md\n")
    rc = _run(q, "tools/manuscript/writer_bundle.py", "receipt", "--stage", "S08_methods",
              "--project", q)
    ed = _run(q, "tools/manuscript/writer_bundle.py", "edit", "--section", "methods", "--project", q)
    em = (q / ".wf/editor_bundle/methods/MANIFEST.md").read_text(encoding="utf-8")
    record("B4 the editor bundle carries writing_voice.md and lists the draft's warning-level hits "
           "(copula_avoidance, vague_attribution)",
           rc.returncode == 0 and ed.returncode == 0
           and (q / ".wf/editor_bundle/methods/writing_voice.md").is_file()
           and "writing_voice.md" in em and "Warning-level findings" in em
           and "copula_avoidance" in em and "vague_attribution" in em, em[-500:])
    _w(q, ".wf/editor_bundle/methods/polished.md",
       METHODS.replace("2023.", "2023; the difference showed a trend toward significance."))
    r_spin = _run(q, "tools/manuscript/writer_bundle.py", "polished", "--section", "methods",
                  "--project", q)
    _w(q, ".wf/editor_bundle/methods/polished.md", METHODS)
    r_ok = _run(q, "tools/manuscript/writer_bundle.py", "polished", "--section", "methods",
                "--project", q)
    record("B4 `writer_bundle.py polished` refuses spin on a 1.24.0 paper and accepts a text with "
           "warnings, printing them in one line (not blocking)",
           r_spin.returncode == 2 and "spin_nonsignificant" in _out(r_spin) and r_ok.returncode == 0
           and "warnings (not blocking" in _out(r_ok)
           and bool(sp.receipt(q, "methods").get("polished_sha256")), _out(r_spin)[-200:] + _out(r_ok)[-300:])


# ------------------------------------------------------------------------------ D
def run_release(tmp: Path, record, section) -> None:
    from wfcore import registry
    from wfcore.state import State
    section("1.24.0 D: one migration event, cards and SKILL point to writing_voice.md")
    q = tmp / "mig"
    q.mkdir(parents=True, exist_ok=True)
    st = State(q, ".wf").create("medpaper", "1.23.0", "S16_discussion")
    before = sorted(x.name for x in q.rglob("*"))
    st.migrate_pipeline("1.24.0", [s.id for s in registry.load().stages])
    st.migrate_pipeline("1.24.0", [s.id for s in registry.load().stages])
    notes = [e for e in st.data["events"] if e["kind"] == "requirements_changed"
             and str(e.get("detail", "")).startswith("1.24.0")]
    after = sorted(x.name for x in q.rglob("*"))
    pipe = registry.load()
    record("D pipeline 1.24.0; a 1.23.0 paper gets exactly one 1.24.0 event (rules now, the spin "
           "block after wf migrate --yes) and stays pinned; no paper file touched",
           pipe.meta.get("version") in ("1.24.0", "1.25.0", "1.25.1") and len(notes) == 1
           and "wf migrate --yes" in notes[0]["detail"] and "spin" in notes[0]["detail"]
           and st.engine_pin == "1.23.0" and before == after, str(notes)[:300])
    cards = {s.id: (ROOT / "pipeline" / s.card).read_text(encoding="utf-8") for s in pipe.stages}
    skill = (ROOT / ".kiro/skills/medpaper-pipeline/SKILL.md").read_text(encoding="utf-8")
    record("D S08/S09/S14/S16 cards and SKILL name reference/writing_voice.md; cards within the "
           "limit", all("writing_voice.md" in cards[s] for s in ("S08_methods", "S09_results",
                                                                  "S14_introduction",
                                                                  "S16_discussion"))
           and "writing_voice.md" in skill
           and max(len(c) for c in cards.values()) <= registry.CARD_MAX_CHARS,
           str({k: len(v) for k, v in cards.items() if len(v) > 3900}))


GROUPS = [("prompts", run_prompts), ("spin", run_spin), ("tierb", run_tierb),
          ("structure", run_structure), ("bundles", run_bundles), ("release", run_release)]
