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


GROUPS = [("A", run_a), ("B", run_b), ("C", run_c)]
