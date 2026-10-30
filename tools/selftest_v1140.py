"""1.14.0 regression tests from an external review of engine 1.13.0: post-freeze meaning
changes (A), complete writer bundle (B), citation claims (C), reproduction data protection (D),
analysis stop rule and results retention (E), gate-cache dependencies (F), no query-count
minimums (G), release-tag integrity and the paper guard (H), and D1-D3. Synthetic fixtures
only - no real paper or dataset is read.

Called from tools/selftest.py.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))


def _env(p: Path | None = None, **extra) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in ("MEDPAPER_PROJECT", "MEDPAPER_ROOT")}
    env.update(PYTHONIOENCODING="utf-8", MEDPAPER_ROOT=str(ROOT))
    if p is not None:
        env["MEDPAPER_PROJECT"] = str(p)
    for k, v in extra.items():
        if v is None:
            env.pop(k, None)
        else:
            env[k] = str(v)
    return env


def _run(p: Path | None, tool: str, *args, env=None, cwd=None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-B", str(ROOT / tool), *map(str, args)],
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          env=env or _env(p), cwd=str(cwd) if cwd else None, timeout=900)


def _out(p) -> str:
    return (p.stdout or "") + (p.stderr or "")


def _w(p: Path, rel: str, text) -> Path:
    t = p / rel
    t.parent.mkdir(parents=True, exist_ok=True)
    t.write_text(text if isinstance(text, str) else json.dumps(text), encoding="utf-8")
    return t


def _paper(path: Path, at: str | None = None) -> Path:
    from wfcore import registry
    from wfcore.state import State
    pipe = registry.load()
    path.mkdir(parents=True, exist_ok=True)
    st = State(path, ".wf").create(pipe.meta["name"], pipe.meta["version"], at or pipe.first().id)
    if at:
        for s in pipe.stages:
            if s.index < pipe.stage(at).index:
                st.stage_info(s.id)["status"] = "done"
        st.stage_info(at)["status"] = "active"
        st.save()
    return path


def _gate(p: Path, name: str, stage: str, **spec):
    import selftest_v180 as v180
    return v180._gate(p, name, stage, **spec)


@contextmanager
def _envset(**kv):
    old = {k: os.environ.get(k) for k in kv}
    for k, v in kv.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = str(v)
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def run(tmp: Path, record, section, only: str = "") -> None:
    tmp.mkdir(parents=True, exist_ok=True)
    for name, fn in GROUPS:
        if not only or name in only:
            fn(tmp / name, record, section)


# ------------------------------------------------------------------------------ A
MS_OLD = ("# T\n\n# Results\n\nThere was no association between statin use and stroke "
          "(hazard ratio 1.02) [@a].\n\nStatin use was associated with lower mortality "
          "(hazard ratio 0.80; Figure 1).\n\nCausal inference is not possible from these data.\n")


def _frozen(base: Path, manuscript: str) -> Path:
    import selftest_v180 as v180
    from wfcore import scifreeze
    p = v180._rw_paper(base, "S24_package_human_review")
    for rel, text in {"07_manuscript/full_manuscript.md": manuscript,
                      "05_figures/legends.md": "# Figure legends\n\n## Figure 1.\nMortality by "
                                               "group.\n",
                      "06_refs/refs.bib": "@article{a, title={A}, year={2020}}\n",
                      "06_refs/library.json": "{\"a\": {}}",
                      "03_analysis/results/primary.json": json.dumps(
                          {"hr_stroke": 1.02, "hr_death": 0.80})}.items():
        _w(p, rel, text)
    scifreeze.write_freeze(p)
    return p


def _plan(tmp: Path, name: str, src: str, request: str) -> Path:
    return _w(tmp, f"{name}.json", {
        "feedback_verbatim": request,
        "interpretation": "Apply the user's request to the named source only and keep every "
                          "other approved artifact unchanged.",
        "ambiguous_or_requires_user_decision": [],
        "items": [{"kind": "results-wording", "request": request, "affected_sources": [src],
                   "acceptance_criteria": ["The requested change is visible in the source",
                                           "Nothing unrelated changed"]}]})


def run_a(tmp: Path, record, section) -> None:
    from wfcore import meaning, presentation
    section("1.14.0 A: post-freeze meaning changes - SAFE / MEANING_CHECK / SCIENCE")
    p = _frozen(tmp / "cls", MS_OLD)
    ms = p / "07_manuscript/full_manuscript.md"
    base = presentation.snapshot_facts(p, with_text=True)
    rel = "07_manuscript/full_manuscript.md"

    def cls(new: str) -> dict:
        ms.write_text(new, encoding="utf-8")
        v = presentation.classify(p, base, [rel])
        ms.write_text(MS_OLD, encoding="utf-8")
        return v
    examples = {
        "no association -> association": MS_OLD.replace("There was no association", "There was an association"),
        "associated with lower -> reduced": MS_OLD.replace("was associated with lower mortality", "reduced mortality"),
        "causal caveat deleted": MS_OLD.replace("\n\nCausal inference is not possible from these data.", ""),
    }
    got = {k: cls(v) for k, v in examples.items()}
    record("A the three review examples are MEANING_CHECK (no number changed, no rewind)",
           all(v["class"] == "meaning_check" and v["label"] == "MEANING_CHECK" and not v["reasons"]
               and v["meaning_pairs"] for v in got.values()),
           str({k: (v["class"], [x["cues"][:2] for x in v["meaning_pairs"]]) for k, v in got.items()})[:300])
    safe = {
        "synonym": MS_OLD.replace("Statin use was", "Use of statins was"),
        "typo": MS_OLD.replace("associated with lower", "assocaited with lower"),
        "punctuation": MS_OLD.replace("from these data.", "from these data;"),
        "reorder": MS_OLD.replace(
            "Statin use was associated with lower mortality (hazard ratio 0.80; Figure 1).\n\n"
            "Causal inference is not possible from these data.",
            "Causal inference is not possible from these data.\n\nStatin use was associated "
            "with lower mortality (hazard ratio 0.80; Figure 1)."),
    }
    gs = {k: cls(v) for k, v in safe.items()}
    record("A synonyms, a typo, punctuation and reordered paragraphs stay SAFE",
           all(v["class"] == "presentation" and v["label"] == "SAFE" for v in gs.values()),
           str({k: [x["cues"] for x in v["meaning_pairs"]] for k, v in gs.items()})[:300])
    sci = cls(MS_OLD.replace("0.80", "0.70"))
    record("A a changed number is SCIENCE (the existing rule)",
           sci["class"] == "scientific" and sci["label"] == "SCIENCE", str(sci["reasons"])[:160])
    terms = {"label": "Direct oral anticoagulant", "abbreviation": "DOAC", "internal": "doac_any",
             "definition": "apixaban, rivaroxaban, edoxaban or dabigatran"}
    _w(p, "01_protocol/display_dictionary.json", {"terms": [terms, {
        "label": "Warfarin", "internal": "vka", "definition": "vitamin K antagonist therapy"}]})
    tm = meaning.dictionary_terms(p)
    swap = meaning.pairs_for("Bleeding was rarer with DOAC use.", "Bleeding was rarer with "
                             "warfarin use.", "x.md", tm)
    same = meaning.pairs_for("Bleeding was rarer with DOAC use.", "Bleeding was rarer with "
                             "direct oral anticoagulant use.", "x.md", tm)
    window = meaning.pairs_for("Events within 30 days.", "Events within 30 months.", "x.md", tm)
    record("A exposure/comparator terms from the display dictionary and time windows are "
           "meaning-bearing; an abbreviation and its label are the same term",
           bool(swap) and not same and bool(window), str([swap, same, window])[:200])
    (p / "01_protocol/display_dictionary.json").unlink()

    # end to end: rework check writes a bundle, close is blocked, verdicts route the round
    def round_with(name: str, verdict_line: str | None):
        q = _frozen(tmp / name, MS_OLD)
        b = _run(q, "tools/rework.py", "batch", "--sealed", "--why",
                 "The user asked to shorten the Results wording now.", "--plan",
                 _plan(tmp, name, rel, "Shorten the mortality sentence in the Results."),
                 "--project", q)
        f = q / rel
        f.write_text(MS_OLD.replace("was associated with lower mortality", "reduced mortality"),
                     encoding="utf-8")
        c1 = _run(q, "tools/rework.py", "check", "--project", q)
        bundles = sorted((q / ".wf/review_bundle").glob("meaning_*"))
        _run(q, "tools/rework.py", "mark", "--item", "R001-01", "--summary",
             "Shortened the mortality sentence of the Results as requested.", "--changed-file",
             rel, "--validated-by", "rework.py check", "--project", q)
        close = _run(q, "tools/rework.py", "close", "--summary",
                     "Shortened the Results wording as the user asked in this round.",
                     "--project", q)
        pv = _run(q, "tools/rework.py", "preview", "--project", q)
        c2 = None
        if verdict_line and bundles:
            (bundles[0] / "report.md").write_text(verdict_line + "\n", encoding="utf-8")
            c2 = _run(q, "tools/rework.py", "check", "--project", q)
        st = json.loads((q / ".wf/state.json").read_text(encoding="utf-8"))
        return b, c1, bundles, close, pv, c2, st
    b, c1, bundles, close, pv, c2, st = round_with("e2e_ok", "P01: meaning unchanged")
    pairs_md = (bundles[0] / "pairs.md").read_text(encoding="utf-8") if bundles else ""
    record("A rework check on a meaning change: MEANING_CHECK, small reviewer bundle (pairs, "
           "results in words, neutral brief), nothing rewound; preview shows the class",
           b.returncode == 0 and c1.returncode == 2 and "MEANING_CHECK" in c1.stdout
           and bundles and (bundles[0] / "MANIFEST.md").is_file()
           and (bundles[0] / "results_in_words.md").is_file() and "reduced mortality" in pairs_md
           and "lower mortality" in pairs_md and st["current"] == "S24_package_human_review"
           and "MEANING_CHECK" in pv.stdout, (_out(b) + _out(c1) + _out(pv))[-500:])
    record("A the round cannot close before every pair has a verdict",
           close.returncode != 0 and "meaning-check pair" in _out(close), _out(close)[-200:])
    record("A verdict 'meaning unchanged' -> SAFE path (presentation delta, no S19 return)",
           c2 is not None and "PRESENTATION" in c2.stdout and "meaning check" in c2.stdout
           and st["current"] == "S24_package_human_review", _out(c2)[-300:] if c2 else "no c2")
    b, c1, bundles, close, pv, c2, st = round_with("e2e_changed",
                                                    "P01: meaning changed - causal claim")
    record("A verdict 'meaning changed' -> SCIENCE path, which still STOPS for '我确认回退'",
           c2 is not None and c2.returncode == 2 and "SCIENTIFIC" in c2.stdout
           and "meaning changed" in c2.stdout and "STOPPED" in c2.stdout
           and st["current"] == "S24_package_human_review", _out(c2)[-300:] if c2 else "no c2")
    # journal copy and final copy use the same three classes
    from wfcore import scifreeze
    v = _frozen(tmp / "variant", MS_OLD)
    scifreeze.open_variant(v, "Journal X", force=True)
    var = v / "08_submission/manuscript/full_manuscript.md"
    var.write_text(var.read_text(encoding="utf-8").replace("There was no association",
                                                           "There was an association"),
                   encoding="utf-8")
    from wfcore.state import State
    st = State(v, ".wf").load()
    st.record_decision("journal_trim_authorised", "YES",
                       "The user authorised trimming the journal copy to the word cap.")
    ok, probs, summ = scifreeze.variant_delta(v)
    g = _gate(v, "variant_preserves_science", "S22_polish")
    dec = _run(v, "tools/rework.py", "meaning-decide", "--context", "variant", "--pair", "P01",
               "--verdict", "unchanged", "--words", "The author checked it: same meaning here.",
               "--project", v)
    ok2, _p2, _ = scifreeze.variant_delta(v)
    record("A journal copy: a meaning change fails variant_preserves_science even with a trim "
           "authorisation, until a per-pair verdict (here the author's) is recorded",
           not ok and any("medpaper-reviewer" in x for x in probs) and not g.ok and "medpaper-reviewer" in g.detail
           and dec.returncode == 0 and ok2, (str(probs) + g.detail + _out(dec))[:400])


GROUPS = [("A", run_a)]
