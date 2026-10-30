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


def _decision_gate(p: Path, stage: str, decision: str, allowed: list[str]):
    from wfcore import registry
    from wfcore.checks import Ctx, get, load_all
    from wfcore.state import State
    load_all()
    pipe = registry.load()
    return get("decision_recorded")(Ctx(pipeline=pipe, state=State(p, ".wf").load(), project=p,
                                        stage=pipe.stage(stage),
                                        spec={"check": "decision_recorded", "name": decision,
                                              "allowed": allowed}))


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


# ------------------------------------------------------------------------------ B
def run_b(tmp: Path, record, section) -> None:
    sys.path.insert(0, str(ROOT / "tools/manuscript"))
    import writer_bundle as wb
    from wfcore import reproproof as rp
    section("1.14.0 B: the writer bundle keeps every result (lists, comparison, CI level)")
    dic = {"terms": [
        {"internal": "exposed", "label": "Exposed group", "definition": "reports naming the drug"},
        {"internal": "unexposed", "label": "Unexposed group", "definition": "all other reports"},
        {"internal": "death_30d", "label": "Death within 30 days", "definition": "any death"}]}

    def lines(name: str, payload) -> tuple[list[str], list[str]]:
        p = _paper(tmp / name, "S09_results")
        _w(p, "01_protocol/display_dictionary.json", dic)
        _w(p, "03_analysis/results/primary.json", payload)
        out, gaps = wb.results_in_words(p, wb.clinical.dictionary(p))
        return [x for x in out if x.startswith("- ")], gaps
    est = {"hr": 1.5, "hr_low": 1.1, "hr_high": 2.0, "p": 0.01, "n": 420}
    as_dict, g1 = lines("dict", {"ci_level": 0.95, "exposed": est})
    as_list, g2 = lines("list", {"ci_level": 0.95, "estimates": [{"term": "exposed", **est}]})
    record("B a list of estimates gives the same sentences as the dict form (nothing dropped)",
           as_dict == as_list and as_dict and not g1 and not g2
           and "95% CI 1.1 to 2.0" in as_dict[0] and "P = 0.01" in as_dict[0], f"{as_dict} | {as_list} | {g1 + g2}")
    comp, _ = lines("comp", {"environment": {"ci_level": 0.9}, "estimates": [
        {"exposure": "exposed", "reference": "unexposed", "outcome": "death_30d",
         "measure": "or", "estimate": 2.1, "lower": 1.4, "upper": 3.0}]})
    record("B comparison, outcome, measure type and the ACTUAL 90% level reach the writer",
           comp and "Odds ratio" in comp[0] and "Exposed group vs Unexposed group" in comp[0]
           and "Death within 30 days" in comp[0] and "90% CI 1.4 to 3.0" in comp[0]
           and "95%" not in comp[0], str(comp))
    nolevel, g3 = lines("nolevel", {"exposed": {"hr": 1.5, "ci_low": 1.1, "ci_high": 2.0}})
    record("B an interval without a recorded level says 'CI level not recorded' and is a gap "
           "(never assumed 95%)", nolevel and "CI level not recorded" in nolevel[0]
           and "95%" not in nolevel[0] and any("CI level not recorded" in g for g in g3), f"{nolevel} {g3}")
    p = _paper(tmp / "gap", "S09_results")
    _w(p, "01_protocol/display_dictionary.json", dic)
    _w(p, "03_analysis/results/primary.json", {"ci_level": 0.95, "exposed": est,
                                               "strict_contrast_x": {"hr": 3.1, "p": 0.2}})
    _w(p, "01_protocol/protocol_final.md", "# Protocol\n\nWe compared `exposed` with `weird_code` "
                                           "in each stratum.\n")
    r = _run(p, "tools/manuscript/writer_bundle.py", "build", "--stage", "S09_results",
             "--project", p)
    g = _gate(p, "writer_results_mapped", "S09_results")
    gaps_md = wb.gaps_path(p, "S09_results")
    proto = (p / ".wf/writer_bundle/S09_results/protocol_summary.md").read_text(encoding="utf-8")
    record("B an unmapped required result is a counted gap: build exits non-zero, the S09 gate "
           "fails, GAPS.md lists it outside the writer's folder",
           r.returncode == 2 and "INCOMPLETE" in r.stdout and not g.ok
           and "strict_contrast_x" in gaps_md.read_text(encoding="utf-8")
           and "strict_contrast_x" not in "".join(
               f.read_text(encoding="utf-8") for f in (p / ".wf/writer_bundle/S09_results").glob("*.md")),
           _out(r)[-300:] + " | " + g.detail[:160])
    record("B inline code is mapped through the dictionary, never silently deleted: a label "
           "replaces a known name, a visible placeholder and a listed gap mark an unknown one",
           "Exposed group" in proto and wb.UNMAPPED in proto and "weird_code" not in proto
           and "weird_code" in gaps_md.read_text(encoding="utf-8"), proto[:200])
    ok_gate = _gate(_paper(tmp / "fine", "S09_results"), "writer_results_mapped", "S09_results")
    record("B the gate passes when every result maps (or there are none yet)", ok_gate.ok, ok_gate.detail)
    old = {}
    for rel in ("tools/analysis/results.py", "tools/R/medresults.R"):
        try:
            old[rel] = subprocess.run(["git", "-C", str(ROOT), "show", f"6d4a0af:{rel}"],
                                      capture_output=True, timeout=30).stdout
        except (OSError, subprocess.SubprocessError):
            old[rel] = b""
    import hashlib
    same = all(not o or hashlib.sha256(o.replace(b"\r\n", b"\n")).hexdigest() == hashlib.sha256(
        b"".join(ln for ln in (ROOT / rel).read_bytes().replace(b"\r\n", b"\n").splitlines(True)
                 if rp.COMPAT_MARK not in ln)).hexdigest() for rel, o in old.items())
    src = (ROOT / "tools/analysis/results.py").read_text(encoding="utf-8")
    rsrc = (ROOT / "tools/R/medresults.R").read_text(encoding="utf-8")
    record("B the analysis helpers record ci_level by default (environment), as output-compatible "
           "lines: the 1.13 helper hash still holds, so no paper re-runs, and the comparison "
           "ignores it", same and 'env["ci_level"]' in src and "ci_level" in rsrc
           and rp.canonical({"environment": {"ci_level": 0.95, "x": 1}}) == {"environment": {"x": 1}},
           str({k: len(v) for k, v in old.items()}))


# ------------------------------------------------------------------------------ C
def run_c(tmp: Path, record, section) -> None:
    import hashlib
    from wfcore import refproof
    section("1.14.0 C: a cited number must be in the cited source; abstracts really compared")
    p = _paper(tmp / "disc", "S16_discussion")
    _w(p, "03_analysis/results/primary.json", {"hr": 1.87})
    _w(p, "06_refs/refs.bib", "@article{smith2020, title={A}}\n@article{lee2021, title={B}}\n"
                              "@article{kim2022, title={C}}\n")
    _w(p, "06_refs/verified.json", {"records": {k: {"verified": True}
                                                for k in ("smith2020", "lee2021", "kim2022")}})
    _w(p, "06_refs/library.json", {"entries": [
        {"citekey": "smith2020", "abstract": "Among 1,204 patients the adjusted HR was 2.31."},
        {"citekey": "lee2021", "abstract": "A registry study."},
        {"citekey": "kim2022", "abstract": "A trial."}]})
    _w(p, "06_refs/deepread/lee2021.md", "# lee2021\n\nTable 2 reports a 12.5% event rate "
                                        "(\u22120.4 change).\n")
    xml = _w(p, "06_refs/fulltext/kim2022.xml", "<article><body><p>Primary result.</p>"
                                                "<table-wrap><table><tr><td>0.77</td></tr></table>"
                                                "</table-wrap></body></article>")
    _w(p, "06_refs/fulltext/retrieval_manifest.json", {"schema": 1, "retrievals": [
        {"citekey": "kim2022", "fulltext": "06_refs/fulltext/kim2022.xml", "identity": "match",
         "sha256": hashlib.sha256(xml.read_bytes()).hexdigest()}]})
    rel = "07_manuscript/discussion.md"
    _w(p, rel, "Smith found an HR of 2.31 in 1204 patients [@smith2020]. Lee reported 12.5% "
               "and a change of -0.4 [@lee2021]. Kim reported 0.77 [@kim2022].\n")
    ok = _gate(p, "numbers_have_provenance", "S16_discussion", path=rel)
    rec = json.loads((p / ".wf/citation_numbers.json").read_text(encoding="utf-8")).get(rel, [])
    where = {r["number"]: r["source"] for r in rec}
    record("C a cited number found in the abstract, the deep-read notes or the verified full "
           "text passes (thousands separator, unicode minus, %), its location is recorded",
           ok.ok and "abstract" in where.get("2.31", "") and "notes" in where.get("12.5", "")
           and "full text table" in where.get("0.77", ""), ok.detail + " | " + str(where))
    _w(p, rel, "Smith found an HR of 2.45 [@smith2020].\n")
    bad = _gate(p, "numbers_have_provenance", "S16_discussion", path=rel)
    record("C a cited number absent from that source fails with 'quote the passage in the "
           "deep-read notes or remove the number'",
           not bad.ok and "2.45" in bad.detail
           and any("quote the passage in the deep-read notes or remove the number" in h
                   for h in bad.hints), bad.detail)
    (p / "06_refs/fulltext/kim2022.xml").write_text("<article>other</article>", encoding="utf-8")
    _w(p, rel, "Kim reported 0.77 [@kim2022].\n")
    tamper = _gate(p, "numbers_have_provenance", "S16_discussion", path=rel)
    record("C a full text whose bytes no longer match its identity receipt is no source",
           not tamper.ok and "0.77" in tamper.detail, tamper.detail)
    src = {"pmid": "1", "doi": "10.1/x", "title": "T", "journal": "J", "year": "2020",
           "first_author": "Smith", "abstract": "Background: statins. Results: HR 2.31."}
    entry = {"pmid": "1", "doi": "10.1/x", "title": "T", "journal": "J", "year": "2020",
             "authors": [{"last": "Smith"}], "abstract": "Background: statins.  Results: HR 2.31"}
    same = refproof.compare_entry_to_source(entry, src)
    diff = refproof.compare_entry_to_source(dict(entry, abstract="A completely different study of "
                                                 "knee surgery outcomes in athletes."), src)
    record("C the stored abstract is really compared with the source abstract (whitespace and "
           "punctuation tolerated; a different abstract fails)",
           not same and any("abstract differs" in x for x in diff), f"{same} | {diff}")
    nosrc = dict(src, abstract="")
    noabs = dict(entry, abstract="", source="fulltext")
    record("C a record without an abstract is citable only through an identity-verified full "
           "text (source 'fulltext'); otherwise it still fails",
           not refproof.compare_entry_to_source(noabs, nosrc, True)
           and refproof.compare_entry_to_source(noabs, nosrc, False)
           and refproof.compare_entry_to_source(dict(noabs, source="pubmed"), nosrc, True),
           str(refproof.compare_entry_to_source(noabs, nosrc, False)))
    q = _paper(tmp / "lib", "S13_reflib")
    x2 = _w(q, "06_refs/fulltext/a.xml", "<article>A</article>")
    _w(q, "06_refs/fulltext/retrieval_manifest.json", {"schema": 1, "retrievals": [
        {"citekey": "a2020", "fulltext": "06_refs/fulltext/a.xml", "identity": "match",
         "sha256": hashlib.sha256(x2.read_bytes()).hexdigest()},
        {"citekey": "b2020", "fulltext": "06_refs/fulltext/a.xml", "identity": "indeterminate",
         "sha256": hashlib.sha256(x2.read_bytes()).hexdigest()}]})
    sys.path.insert(0, str(ROOT / "tools"))
    from pubmed import build_library as bl
    lib = {"entries": []}
    rec_no = {"pmid": "9", "title": "Editorial on statins", "abstract": "", "year": "2020",
              "authors": [{"last": "Ng", "first": "A"}], "journal": "J", "doi": ""}
    kept = bl.add_records({"entries": []}, [rec_no], allow_fulltext=True)
    dropped = bl.add_records(lib, [rec_no])
    record("C build_library keeps a no-abstract record as source 'fulltext' only on request; "
           "only an identity-match full text counts as verified",
           kept[0] == 1 and dropped == (0, 1, 0) and set(refproof.fulltext_verified(q)) == {"a2020"},
           f"{kept} {dropped} {refproof.fulltext_verified(q)}")


# ------------------------------------------------------------------------------ D
def run_d(tmp: Path, record, section) -> None:
    import tempfile
    import time
    from unittest.mock import patch
    from wfcore import reproproof as rp
    section("1.14.0 D: reproduction never links or alters data; integrity; safe cleanup")
    src = _w(tmp, "u/a.csv", "x\n1\n")
    with patch("os.link", side_effect=AssertionError("hard link attempted")):
        how = rp.provide(src, tmp / "sb/a.csv", rp.Budget(10_000))
        try:
            rp.provide(src, tmp / "sb/b.csv", rp.Budget(2))
            refused = ""
        except rp.DataCopyRefused as exc:
            refused = str(exc)
    record("D provide copies within data_copy_limit_mb and never hard-links; beyond it refuses "
           "with the in-place path", how == "copy" and os.stat(tmp / "sb/a.csv").st_nlink == 1
           and "source_path" in refused and not (tmp / "sb/b.csv").exists(), refused[:120])
    P = _paper(tmp / "paper", "S06_protocol_final")
    D = tmp / "datasrc"
    _w(D, "big.csv", "x,y\n1,2\n2,3\n")
    _w(P, "02_data/raw/small.csv", "a\n1\n")
    env = _env(P)
    add = _run(None, "tools/wf.py", "data", "add", D, "--name", "src", env=env, cwd=P)
    C = "03_analysis/code/"
    _w(P, C + "01_load.py",
       "import os\nfrom wfcore.paths import project_dir\nfrom analysis.datasources import source_path\n"
       "from analysis.results import write_results\nP = project_dir()\n"
       "rows = source_path('src', 'big.csv').read_text().splitlines()\n"
       "small = (P / '02_data/raw/small.csv').read_text()\n"
       "if 'sandboxes' in str(P) and os.environ.get('MP_TAMPER') == 'copy':\n"
       "    (P / '02_data/raw/small.csv').write_text('tampered in sandbox\\n')\n"
       "if 'sandboxes' in str(P) and os.environ.get('MP_TAMPER') == 'source':\n"
       "    source_path('src', 'big.csv').write_text('x,y\\n9,9\\n')\n"
       "write_results('primary', {'n': len(rows)})\n")
    r0 = _run(None, "tools/wf.py", "run-script", C + "01_load.py", env=env, cwd=P)
    rep = P / "03_analysis/reproducibility_report.json"

    def run(**extra):
        r = _run(None, "tools/reproduce.py", "run", "--full", "--project", P, env=_env(P, **extra))
        return r, (json.loads(rep.read_text(encoding="utf-8")) if rep.is_file() else {})
    r1, j1 = run()
    sb = j1.get("sandbox", {})
    record("D a reproduction copies paper inputs (no hard links) and checks every data source "
           "before and after the run", add.returncode == 0 and r0.returncode == 0
           and r1.returncode == 0 and j1.get("all_match") and sb.get("data_files_linked") == 0
           and sb.get("data_bytes_copied", 0) > 0 and j1.get("data_integrity", {}).get("ok")
           and j1["data_integrity"]["checked"] >= 2, (_out(add) + _out(r0) + _out(r1))[-400:])
    r2, j2 = run(MP_TAMPER="copy")
    record("D a script writing to its sandbox copy of an input leaves the original unchanged",
           (P / "02_data/raw/small.csv").read_text(encoding="utf-8") == "a\n1\n"
           and j2.get("data_integrity", {}).get("ok") is True, _out(r2)[-300:])
    r3, j3 = run(MP_TAMPER="source")
    record("D a data source changed during the run is CRITICAL: the run is invalid and the file "
           "is named", "CRITICAL" in r3.stdout and "datasource:src/big.csv" in r3.stdout
           and j3.get("all_match") is False
           and "datasource:src/big.csv" in j3.get("data_integrity", {}).get("changed", []),
           _out(r3)[-300:])
    # cleanup: only this paper's dead sandboxes and old, unreferenced legacy folders
    tmpdir = Path(tempfile.gettempdir())
    dead = P / rp.SANDBOX_DIR / "run_dead"
    _w(dead, "x.bin", "x")
    _w(dead, rp.MARKER, {"paper": str(P.resolve()), "pid": 0, "host": __import__("socket").gethostname()})
    active = tmpdir / f"medpaper_repro_st1140_active_{os.getpid()}"
    _w(active, rp.MARKER, {"paper": str(P.resolve()), "pid": os.getpid(),
                           "host": __import__("socket").gethostname()})
    foreign = tmpdir / f"medpaper_repro_st1140_foreign_{os.getpid()}"
    _w(foreign, rp.MARKER, {"paper": str(tmp / "other_paper"), "pid": 0, "host": "x"})
    old_unused = tmpdir / f"medpaper_repro_st1140_old_{os.getpid()}"
    old_used = tmpdir / f"medpaper_repro_st1140_used_{os.getpid()}"
    young = tmpdir / f"medpaper_repro_st1140_young_{os.getpid()}"
    for d in (old_unused, old_used, young):
        _w(d, "y.bin", "y")
    t13 = time.time() - 13 * 3600
    for d in (old_unused, old_used):
        os.utime(d, (t13, t13))
    holder = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)", str(old_used)])
    try:
        time.sleep(1)
        removed, kept = rp.cleanup_stale(P)
    finally:
        holder.kill()
    # only this run's folders count (a concurrent selftest may clean the shared temp dir too)
    mine = {dead.name, active.name, foreign.name, old_unused.name, old_used.name, young.name}
    gone = {Path(x).name for x, _ in removed} & mine
    record("D cleanup removes only this paper's dead sandboxes and old unreferenced legacy "
           "folders; an active, a foreign, a young or a process-referenced folder is kept and listed",
           "run_dead" in gone and gone <= {"run_dead", old_unused.name}
           and not old_unused.exists() and active.exists() and foreign.exists()
           and old_used.exists() and young.exists() and len(kept) >= 4, f"{gone} | {kept}")
    for d in (active, foreign, old_used, young):
        shutil.rmtree(d, ignore_errors=True)


# ------------------------------------------------------------------------------ E + G
def run_e(tmp: Path, record, section) -> None:
    from wfcore.state import State
    section("1.14.0 E: analysis stop rule, retired results, diagnostics, stale decisions")
    p = _paper(tmp / "e", "S05_analysis")
    man = {"schema": 1, "scripts": [
        {"path": "03_analysis/code/01_primary.py", "inputs": [], "outputs": [], "role": "primary"},
        {"path": "03_analysis/code/02_extra.py", "inputs": [], "outputs": [], "role": "additional"}]}
    _w(p, "03_analysis/analysis_manifest.json", man)
    bad = _gate(p, "additional_analyses_justified", "S05_analysis")
    man["scripts"][1]["decision"] = "whether the primary estimate is robust to the exposure window"
    _w(p, "03_analysis/analysis_manifest.json", man)
    good = _gate(p, "additional_analyses_justified", "S05_analysis")
    record("E an additional analysis must state the scientific decision it could change",
           not bad.ok and "decision" in bad.detail and good.ok, bad.detail + " | " + good.detail)
    _w(p, "03_analysis/results/primary.json", {"hr": 1.87})
    _w(p, "03_analysis/results/old_model.json", {"hr": 2.95})
    _w(p, "07_manuscript/results.md", "The HR was 2.95.\n")
    before = _gate(p, "numbers_have_provenance", "S09_results", path="07_manuscript/results.md")
    r = _run(p, "tools/retire_result.py", "--file", "03_analysis/results/old_model.json", "--why",
             "superseded by the corrected exclusion criteria", "--project", p)
    after = _gate(p, "numbers_have_provenance", "S09_results", path="07_manuscript/results.md")
    log = p / "03_analysis/retired/RETIRED.md"
    record("E a superseded result is retired (moved with its reason), never deleted, and is no "
           "longer number provenance", r.returncode == 0 and before.ok and not after.ok
           and (p / "03_analysis/retired/results/old_model.json").is_file()
           and "corrected exclusion" in log.read_text(encoding="utf-8"), _out(r)[-200:] + after.detail)
    _w(p, "03_analysis/diagnostics/residuals.py", "import matplotlib.pyplot as plt\nplt.plot([1])\n")
    _w(p, "03_analysis/diagnostics/residuals.png", "png")
    plots = _gate(p, "no_plot_calls", "S05_analysis", glob="03_analysis/code/*.*")
    orphans = _gate(p, "no_orphans", "S05_analysis")
    record("E internal diagnostic plots under 03_analysis/diagnostics/ are allowed (no plot-call "
           "or orphan failure there)", plots.ok and not any(
               x in orphans.detail for x in ("diagnostics", "retired")), plots.detail + " | " + orphans.detail[:200])
    q = _paper(tmp / "go", "S06_protocol_final")
    _w(q, "03_analysis/results/primary.json", {"hr": 1.87, "environment": {"written_at": "a"}})
    _w(q, "01_protocol/protocol_final.md", "# Protocol\n")
    st = State(q, ".wf").load()
    st.record_decision("go_nogo_2", "GO", "The primary estimate is precise and clinically relevant.")
    fresh = _decision_gate(q, "S06_protocol_final", "go_nogo_2", ["GO"])
    _w(q, "03_analysis/results/primary.json", {"hr": 1.87, "environment": {"written_at": "b"}})
    rerun_only = _decision_gate(q, "S06_protocol_final", "go_nogo_2", ["GO"])
    _w(q, "03_analysis/results/primary.json", {"hr": 1.42})
    stale = _decision_gate(q, "S06_protocol_final", "go_nogo_2", ["GO"])
    st = State(q, ".wf").load()
    st.record_decision("go_nogo_2", "GO", "Re-judged on the corrected estimate: still precise and relevant.")
    again = _decision_gate(q, "S06_protocol_final", "go_nogo_2", ["GO"])
    st = State(q, ".wf").load()
    st.data["decisions"]["go_nogo_2"].pop("inputs_sha256")
    st.save()
    legacy = _decision_gate(q, "S06_protocol_final", "go_nogo_2", ["GO"])
    record("E GO stores a hash of its scientific inputs: a re-run with identical results keeps "
           "it, changed results make it stale until the agent re-records it with a reason; a "
           "pre-1.14 decision is accepted", fresh.ok and rerun_only.ok and not stale.ok
           and "stale" in stale.detail and "ask the user only if" in " ".join(stale.hints)
           and again.ok and legacy.ok, stale.detail)
    src = (ROOT / "pipeline/stages/S05_analysis.md").read_text(encoding="utf-8")
    record("E the S05 card states the stop rule, retirement and diagnostics; no deletion of "
           "result JSONs", "validity checks" in src and "retire_result.py" in src
           and "03_analysis/diagnostics/" in src and "delete abandoned" not in src)
    section("1.14.0 G: no query-count minimums at S02/S05/S07")
    from wfcore import registry
    pipe = registry.load()
    mins = [g.get("min_queries") for sid in ("S02_feasibility", "S05_analysis", "S07_artifacts")
            for g in pipe.stage(sid).gate if g.get("check") == "pubmed_cache_fresh"]
    g = _paper(tmp / "g", "S05_analysis")
    _w(g, "06_refs/cache/q.json", "{}")
    _w(g, "06_refs/cache/scan_manifest.json", {"queries": [
        {"query": "statin mortality cohort", "ids": [str(i) for i in range(40)],
         "cache_file": "06_refs/cache/q.json"}]})
    one = _gate(g, "pubmed_cache_fresh", "S05_analysis", manifest="06_refs/cache/scan_manifest.json",
                min_queries=1, min_hits=30)
    record("G one well-aimed search passes; S02/S05/S07 carry no query minimum and the cards no "
           "query counts", mins == [1, 1, 1] and one.ok and ">= 5" not in src, f"{mins} {one.detail}")


# ------------------------------------------------------------------------------ F
def run_f(tmp: Path, record, section) -> None:
    import builtins
    import fnmatch
    import io
    import time
    from unittest.mock import patch
    from wfcore import gatecache
    section("1.14.0 F: gate-cache dependencies complete, receipts merged, close re-checks drift")
    p = _paper(tmp / "f", "S16_discussion")
    _w(p, "03_analysis/results/primary.json", {"hr": 1.87})
    _w(p, "06_refs/refs.bib", "@article{smith2020, title={A}}\n")
    _w(p, "06_refs/verified.json", {"records": {"smith2020": {"verified": True}}})
    _w(p, "06_refs/library.json", {"entries": [{"citekey": "smith2020", "abstract": "HR 2.31."}]})
    _w(p, "06_refs/deepread/smith2020.md", "# smith2020\n\nHR 2.31.\n")
    _w(p, "01_protocol/display_dictionary.json", {"terms": []})
    _w(p, "07_manuscript/discussion.md", "# Discussion\n\nOur HR was 1.87; Smith found 2.31 "
                                         "[@smith2020].\n")
    specs = [("numbers_have_provenance", {"path": "07_manuscript/discussion.md"}),
             ("md_sections", {"path": "07_manuscript/discussion.md", "headings": ["Discussion"]}),
             ("no_ai_boilerplate", {"path": "07_manuscript/discussion.md"}),
             ("md_wordcount", {"path": "07_manuscript/discussion.md", "max": 2000}),
             ("manuscript_structure", {}),
             ("supplementary_methods_clean", {})]
    real_open = io.open
    root = str(p.resolve()).casefold()
    missing: dict[str, list[str]] = {}
    for name, spec in specs:
        reads: set[str] = set()

        def spy(file, *a, _reads=reads, **k):
            try:
                s = os.path.abspath(os.fspath(file))
                if s.casefold().startswith(root):
                    _reads.add(Path(s).relative_to(p.resolve()).as_posix())
            except (TypeError, ValueError):
                pass
            return real_open(file, *a, **k)
        with patch.object(io, "open", spy), patch.object(builtins, "open", spy):
            try:
                _gate(p, name, "S16_discussion", **spec)
            except Exception:  # noqa: BLE001 - a failing check still shows what it reads
                pass
        pats = gatecache.dependencies(p, {"check": name, **spec}) or []
        bad = sorted(r for r in reads if not r.startswith(".wf/")
                     and not any(fnmatch.fnmatch(r, pat) or r == pat for pat in pats))
        if bad:
            missing[name] = bad
    record("F every file a cached check actually reads is one of its declared dependencies "
           "(numbers_have_provenance now includes the reference files)", not missing
           and "06_refs/verified.json" in gatecache.INPUTS["numbers_have_provenance"], str(missing))
    from wfcore import registry
    from wfcore.state import State
    st = State(p, ".wf").load()
    path = st.dir / gatecache.REL
    now = time.time()
    _w(p, f".wf/{gatecache.REL}", {"keep": {"at": now, "result": {"ok": True, "check": "x",
                                                                  "detail": "", "hints": [],
                                                                  "severity": "fail"}},
                                    "old": {"at": now - 10 * gatecache.TTL_SECONDS, "result": {}}})
    rc = gatecache.Receipts(p, registry.load(), st)
    from wfcore.checks import Result
    rc.put("new", Result(True, "y", "fine"))
    rc.save()
    saved = json.loads(path.read_text(encoding="utf-8"))
    record("F saving receipts keeps still-valid receipts of checks not run this time and drops "
           "expired ones", set(saved) == {"keep", "new"}, str(sorted(saved)))
    record("F rework close re-runs a pure check whose inputs drifted (renewed reference "
           "evidence) and reuses the others",
           gatecache.depends_on(p, {"check": "numbers_have_provenance",
                                    "path": "07_manuscript/discussion.md"}, ["06_refs/verified.json"])
           and not gatecache.depends_on(p, {"check": "md_sections", "path": "07_manuscript/x.md"},
                                        ["06_refs/verified.json"])
           and "depends_on(project" in (ROOT / "tools/wfcore/revision.py").read_text(encoding="utf-8"))


# ------------------------------------------------------------------------------ H
def run_h(tmp: Path, record, section) -> None:
    from contextlib import redirect_stdout
    from io import StringIO
    from unittest.mock import patch
    from wfcore import cli, integrity
    sys.path.insert(0, str(ROOT / "tools/hooks"))
    import paper_guard
    section("1.14.0 H: only release-tagged engines serve papers; the guard blocks engine git writes")
    with _envset(MEDPAPER_ENGINE_DEV=None):
        g = tmp / "eng"
        (g / "tools").mkdir(parents=True)
        (g / "tools/a.py").write_text("x = 1\n", encoding="utf-8")
        git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid",
               "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false", "-C", str(g)]
        subprocess.run(["git", "init", "-q", str(g)], capture_output=True)
        subprocess.run([*git, "add", "-A"], capture_output=True)
        subprocess.run([*git, "commit", "-q", "-m", "x"], capture_output=True)
        untagged = integrity.engine_state(g, use_cache=False)
        info0 = integrity.release_info(g)
        subprocess.run([*git, "tag", "-a", "v9.9.9", "-m", "v9.9.9"], capture_output=True)
        tagged = integrity.engine_state(g, use_cache=False)
        info1 = integrity.release_info(g)
        (g / "tools/b.py").write_text("y = 1\n", encoding="utf-8")
        subprocess.run([*git, "add", "-A"], capture_output=True)
        subprocess.run([*git, "commit", "-q", "-m", "local"], capture_output=True)
        after_local = integrity.engine_state(g, use_cache=False)
    record("H a clean checkout serves papers only at a release tag: a local commit after the "
           "tag is 'untagged' (the 1.13 guard missed it)",
           untagged[0] == "untagged" and tagged == ("clean", []) and after_local[0] == "untagged"
           and info0["tag"] is None and info1["tag"] == "v9.9.9", str([untagged, tagged, after_local]))
    ws = _paper(tmp / "ws")
    buf = StringIO()
    with patch.object(integrity, "engine_state", return_value=("untagged", ["HEAD abc1234 is "
                                                                           "not a release tag (vX.Y.Z)"])), \
            _envset(MEDPAPER_PROJECT=ws):
        with redirect_stdout(buf):
            rc = cli.main(["check"])
    out = buf.getvalue()
    record("H paper commands refuse an untagged global engine (rc 3) and name the legal paths",
           rc == 3 and "REFUSED" in out and "release" in out and "engine-fork" in out
           and "MEDPAPER_ENGINE_DEV" in out, out[-300:])
    with _envset(MEDPAPER_ENGINE_DEV=None):
        doc = _run(None, "tools/wf.py", "doctor", env=_env(None, MEDPAPER_ENGINE_DEV=None), cwd=tmp)
    record("H wf doctor shows the engine release state (tag or untagged; commits ahead of origin)",
           "engine release" in _out(doc), _out(doc)[-400:])
    eng = str(ROOT)
    blocked_cmds = [f"git -C {eng} commit -m x", f"git -C \"{eng}\" merge v1140",
                    f"git -c user.name=t -C {eng} commit -am x", f"git -C {eng} switch main",
                    f"git -C {eng} reset --hard HEAD~1", f"git -C {eng} revert HEAD",
                    f"git -C {eng} am patch.mbox", f"git -C {eng} cherry-pick abc",
                    f"git -C {eng} rebase main", f"git -C {eng} tag -a v9.9.9 -m x",
                    f"git -C {eng} push origin main", f"git -C {eng} worktree add {ws / 'wt'}",
                    f"git -C {eng} worktree remove x", f"git -C {eng} branch -d x",
                    f"git -C {eng} branch -D x", f"git -C {eng} stash",
                    f"git -C {eng} checkout -- tools/wf.py"]
    allowed_cmds = [f"git -C {eng} status", f"git -C {eng} log --oneline -3",
                    f"git -C {eng} tag --points-at HEAD", f"git -C {eng} branch --show-current",
                    f"git -C {eng} worktree list", f"git -C {eng} stash list",
                    f"git -C {eng} diff", f"git -C {ws} commit -m paper"]
    guard = paper_guard.Guard(ws)

    def decide(cmd, cwd=None):
        payload = {"tool_name": "execute_pwsh", "tool_input": {"command": cmd}}
        if cwd:
            payload["tool_input"]["cwd"] = str(cwd)
        return guard.decide(payload)
    blocked = {c: decide(c) for c in blocked_cmds}
    cwd_blocked = decide("git commit -m x", ROOT) and decide("git tag -a v1.0.0 -m x", ROOT)
    allowed = {c: decide(c) for c in allowed_cmds}
    record("H the paper guard blocks git write commands aimed at the engine (via -C or cwd) and "
           "allows read-only git and the paper's own repository",
           all(blocked.values()) and cwd_blocked and not any(allowed.values()),
           str({k[-30:]: bool(v) for k, v in {**blocked, **allowed}.items()}))


# ------------------------------------------------------------------------------ I (D1-D3)
def run_i(tmp: Path, record, section) -> None:
    from xml.etree import ElementTree as ET
    from wfcore import decisionrecord, docxaudit, meaning, registry, reviewrounds
    section("1.14.0 D1-D3: decision record for reviewers, one look before Results, table "
            "footnote stays with its table")
    # D1 ----------------------------------------------------------------------------------
    p = _paper(tmp / "d1", "S18_independent_review")
    _w(p, "01_protocol/protocol_v1.md", "# Protocol\n\n## Variables\n\n- Primary outcome: 30-day "
       "mortality\n- Exposure: drug A\n- Comparator: drug B\n\n## Statistical analysis plan\n\n"
       "Main model: Cox regression adjusted for age\n\n## Design precedent\n\n- Primary outcome: "
       "precedent yes - PMID 12345678\n")
    _w(p, "01_protocol/protocol_final.md", "# Protocol\n\n- **Primary outcome:** 90-day "
       "mortality\n- Exposure: drug A\n- Comparator: drug B\n- Main model: Cox regression "
       "adjusted for age\n")
    _w(p, ".wf/protocol_changes.md", "# Plan changes\n\n- primary outcome 30-day -> 90-day "
       "mortality (data-driven: few early events)\n")
    _w(p, "03_analysis/analysis_manifest.json", {"schema": 1, "scripts": [
        {"path": "03_analysis/code/a.R", "role": "primary"},
        {"path": "03_analysis/code/b.R", "role": "additional",
         "decision": "whether the effect holds in women only"}]})
    _w(p, "01_protocol/artifact_plan.json", {"main_figures": [], "supp_figures": [],
                                             "main_tables": [], "supp_tables": []})
    text = decisionrecord.build(p)
    rows = {ln.split("|")[1].strip(): ln for ln in text.splitlines() if ln.startswith("| ")}
    record("D1 the decision record states, from the protocol records only, what was "
           "pre-specified and what was decided after the data were seen",
           "changed after the data were seen" in rows.get("Primary outcome", "")
           and "as pre-specified" in rows.get("Exposure", "")
           and "as pre-specified" in rows.get("Main model", "")
           and "few early events" in text and "b.R: whether the effect holds" in text
           and "never presented as confirmatory" in text
           and "precedent" not in rows.get("Primary outcome", ""), text[:600])
    rnd = {"id": "M001", "scope": "manuscript", "mode": "full", "reviewed": [], "stage": "S10"}
    bundle = reviewrounds.write_bundle(p, rnd)
    man = (bundle / "MANIFEST.md").read_text(encoding="utf-8")
    pairs = [{"file": "07_manuscript/results.md", "old": "An exploratory analysis showed x.",
              "new": "The analysis confirmed x.", "hash": "h1"}]
    mb = meaning.write_bundle(p, "test", pairs)
    mman = (mb / "MANIFEST.md").read_text(encoding="utf-8")
    exported = [rel for rel in ("tools/manuscript/writer_bundle.py", "tools/manuscript/build_docx.py",
                                "tools/final_copy.py", "tools/wfcore/packagecontent.py",
                                "tools/wfcore/finalcopy.py")
                if "decisionrecord" in (ROOT / rel).read_text(encoding="utf-8")
                or "decision_record" in (ROOT / rel).read_text(encoding="utf-8")]
    agent = (ROOT / ".kiro/agents/medpaper-reviewer.md").read_text(encoding="utf-8")
    writer = (ROOT / ".kiro/agents/medpaper-clinical-writer.md").read_text(encoding="utf-8")
    record("D1 review and meaning bundles carry the record (reviewer only); the brief and the "
           "reviewer agent ask that post hoc analyses are not presented as confirmatory; it is "
           "never exported and the writer keeps labelling post hoc analyses exploratory",
           (bundle / "decision_record.md").is_file() and "decision_record.md" in man
           and "confirmatory" in man and (mb / "decision_record.md").is_file()
           and "decision_record.md" in mman and not exported
           and "not presented as confirmatory" in agent and "exploratory" in writer
           and str(bundle).replace("\\", "/").count("/.wf/") == 1, str(exported))
    # D2 ----------------------------------------------------------------------------------
    pipe = registry.load()
    s09 = pipe.stage("S09_results")
    gate = [g for g in s09.gate if g.get("name") == "displays_seen_before_results"]
    card = (ROOT / "pipeline/stages/S09_results.md").read_text(encoding="utf-8")
    q = _paper(tmp / "d2", "S09_results")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    (q / "05_figures/out").mkdir(parents=True)
    fig = plt.figure(figsize=(3, 2))
    plt.plot([0, 1], [0, 1])
    fig.savefig(q / "05_figures/out/Figure1.png", dpi=60)
    plt.close(fig)
    _w(q, "01_protocol/artifact_plan.json", {
        "main_figures": [{"id": "Figure 1", "file": "05_figures/out/Figure1.png"}],
        "supp_figures": [], "main_tables": [{"id": "Table 1", "file": "04_tables/main/T1.xlsx"}],
        "supp_tables": []})
    sheet = _run(q, "tools/figures/qc.py", "--contact-sheet", "--with-tables")
    before = _decision_gate(q, "S09_results", "displays_seen_before_results", ["YES"])
    dec = _run(q, "tools/wf.py", "decide", "displays_seen_before_results", "YES", "--why",
               "one sheet of Figure 1 and Table 1; axis labels readable, fixed nothing")
    after = _decision_gate(q, "S09_results", "displays_seen_before_results", ["YES"])
    record("D2 one contact-sheet image of all final tables and figures before Results "
           "(a table that cannot be rendered is named), recorded once as a S09 gate; the "
           "card stays short and the other visual checks stay at S23",
           len(gate) == 1 and gate[0].get("since") == "1.14.0" and "--with-tables" in card
           and len(card) <= registry.CARD_MAX_CHARS and sheet.returncode == 0
           and (q / "05_figures/qc/displays_sheet.png").is_file() and "Table 1" in _out(sheet)
           and "deferred to S23" in _out(sheet) and not before.ok and dec.returncode == 0
           and after.ok, _out(sheet)[-300:] + _out(dec)[-200:])
    # D3 ----------------------------------------------------------------------------------
    from manuscript import build_docx as bd
    W = docxaudit.W

    def row(t):
        return (f'<w:tr><w:trPr><w:cantSplit/></w:trPr><w:tc><w:p><w:pPr><w:jc w:val="left"/>'
                f'</w:pPr><w:r><w:t>{t}</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>{t}2</w:t>'
                "</w:r></w:p></w:tc></w:tr>")
    xml = (f'<w:document xmlns:w="{W}"><w:body><w:p><w:pPr><w:pStyle w:val="SectionHeading"/>'
           "</w:pPr><w:r><w:t>Results</w:t></w:r></w:p><w:tbl>" + row("a") + row("b") + row("c")
           + "</w:tbl><w:p><w:r><w:t>Data are n (%).</w:t></w:r></w:p><w:tbl>" + row("x")
           + row("y") + '</w:tbl><w:p><w:pPr><w:sectPr><w:type w:val="nextPage"/></w:sectPr>'
           "</w:pPr></w:p><w:sectPr/></w:body></w:document>").encode()
    kept = bd.keep_table_footnotes(xml)
    root = ET.fromstring(kept)
    tbls = root.findall(f".//{{{W}}}tbl")
    per_row = [[len(r.findall(f".//{{{W}}}keepNext")) for r in t.findall(f"{{{W}}}tr")] for t in tbls]

    def flagged(mutate) -> bool:
        r2 = ET.fromstring(kept)
        mutate(r2)
        return any("black squares" in x for x in docxaudit.keep_problems(r2))

    def add(where, tag="keepNext"):
        def f(r2):
            p_ = where(r2)
            ppr = p_.find(f"{{{W}}}pPr")
            if ppr is None:
                ppr = ET.SubElement(p_, f"{{{W}}}pPr")
            ET.SubElement(ppr, f"{{{W}}}{tag}")
        return f
    first_row_p = lambda r2: r2.find(f".//{{{W}}}tbl/{{{W}}}tr/{{{W}}}tc/{{{W}}}p")  # noqa: E731
    heading_p = lambda r2: r2.find(f"{{{W}}}body/{{{W}}}p")  # noqa: E731
    last_row_p = lambda r2: r2.findall(f".//{{{W}}}tbl")[0].findall(  # noqa: E731
        f"{{{W}}}tr")[-1].find(f".//{{{W}}}p")
    record("D3 keepNext only on the last data row of a table followed by its footnote; the "
           "audit allows exactly that row and flags a keep marker anywhere else",
           per_row == [[0, 0, 2], [0, 0]] and b"<w:pPr><w:keepNext/><w:jc" in kept
           and not docxaudit.keep_problems(root) and docxaudit.stray_markers(root, "keepNext") == 0
           and flagged(add(first_row_p)) and flagged(add(heading_p))
           and flagged(add(last_row_p, "keepLines")), str(per_row))
    st = bd.modern_layout(b'<w:settings xmlns:w="x"><w:zoom/><w:rsids/></w:settings>')
    record("D3 Word layout mode 15 is set (legacy mode ignores keepNext on table rows; checked "
           "with a Word render of a long table), placed before rsids",
           st.find(b'w:val="15"') != -1 and st.find(b"<w:compat>") < st.find(b"<w:rsids")
           and bd.modern_layout(st) == st, st.decode())
    st_ = (f'<w:settings xmlns:w="{W}"><w:zoom w:percent="100"/><w:rsids/></w:settings>').encode()
    lay = bd.modern_layout(st_)
    record("D3 the builder sets Word layout mode 15 (the legacy mode Pandoc implies ignores "
           "keepNext on table rows; confirmed with Word: footnote no longer alone on a page)",
           b'w:val="15"' in lay and lay.index(b"<w:compat>") < lay.index(b"<w:rsids")
           and bd.modern_layout(lay) == lay, lay.decode()[:200])


def run_r(tmp: Path, record, section) -> None:
    from wfcore import registry
    from wfcore.state import State
    section("1.14.0 release: version, one migration event, card length")
    q = tmp / "old"
    q.mkdir(parents=True, exist_ok=True)
    st = State(q, ".wf").create("medpaper", "1.13.0", "S10_tables")
    before = sorted(x.name for x in q.rglob("*") if x.is_file() and ".wf" not in x.parts)
    st.migrate_pipeline("1.14.0", ["S10_tables"])
    st.migrate_pipeline("1.14.0", ["S10_tables"])
    notes = [e for e in st.data["events"] if e["kind"] == "requirements_changed"
             and str(e.get("detail", "")).startswith("1.14.0")]
    after = sorted(x.name for x in q.rglob("*") if x.is_file() and ".wf" not in x.parts)
    pipe = registry.load()
    sizes = {s.id: len((ROOT / "pipeline" / s.card).read_text(encoding="utf-8")) for s in pipe.stages}
    record("R pipeline 1.14.0; a 1.13 paper gets exactly one 1.14.0 migration event and no paper "
           "file changes; every card <= the card limit",
           pipe.meta.get("version") == "1.14.0" and len(notes) == 1 and before == after
           and max(sizes.values()) <= registry.CARD_MAX_CHARS, f"{len(notes)} {max(sizes.values())}")


GROUPS = [("A", run_a), ("B", run_b), ("C", run_c), ("D", run_d), ("E", run_e), ("F", run_f),
          ("H", run_h), ("I", run_i), ("R", run_r)]
