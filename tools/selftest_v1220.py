"""1.22.0 regression tests: fewer pauses and faster convergence.

C1 certificates per journal epoch, C2 bookkeeping round, C3 derived files by build receipt and
deletion credentials, C4 figure QC at once, C5 no stale renders in bundles, C6 engine counts;
R1-R3 review convergence; U1-U5 user decisions, pauses, confirmation, cost, language;
J1-J7 layout, guideline completeness, portal reconciliation, dated package folders, repackage,
old-journal traces, difference list; O1 orchestration; release policy.
Synthetic fixtures only - no real paper, dataset, network or browser is used.
Called from tools/selftest.py.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from selftest_v1140 import _env, _gate, _out, _paper, _run, _w  # noqa: E402,F401


def run(tmp: Path, record, section, only: str = "") -> None:
    tmp.mkdir(parents=True, exist_ok=True)
    for name, fn in GROUPS:
        if not only or name in only.split():
            fn(tmp / name, record, section)


def _pin(p: Path, version: str) -> None:
    st = json.loads((p / ".wf/state.json").read_text(encoding="utf-8"))
    st["engine_pin"] = version
    (p / ".wf/state.json").write_text(json.dumps(st), encoding="utf-8")


def _closed_round(p: Path, rid: str, files: list[str], when: str | None = None) -> dict:
    """A closed schema-2 round certifying `files` (receipts of their current bytes)."""
    from wfcore import revision
    data = {"schema_version": 2, "round_id": rid, "status": "complete",
            "review_stage": "S24_package_human_review", "created_at": when or revision._now(),
            "completed_at": when or revision._now(),
            "items": [{"id": f"{rid}-01", "status": "done", "validated_by": ["x"],
                       "changed_files": [revision.receipt(p, f) for f in files]}],
            "validation": {"ok": True, "input_signature": "s", "results": [{"check": "x", "ok": True}]}}
    _w(p, f".wf/revisions/{rid}.json", data)
    return data


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


# ------------------------------------------------------------------------------ C1-C3
def run_certs(tmp: Path, record, section) -> None:
    from selftest_v1170 import FIG_SCRIPT, _frozen_paper
    from wfcore import revision
    from wfcore.state import State
    section("1.22.0 C1-C3: certificates per journal epoch, bookkeeping round, derived files")
    p = _frozen_paper(tmp / "sw")
    _w(p, "08_submission/manuscript/cover_note.md", "Journal A copy: mortality was 23.4%.\n")
    _closed_round(p, "R001", ["08_submission/manuscript/cover_note.md", "07_manuscript/full_manuscript.md"],
                  when="2026-01-01T12:00:00Z")
    sw = _run(p, "tools/wf.py", "journal", "switch", "--to", "Journal B", "--confirm-old", "Journal A",
              "--why", "rejected after peer review: scope", "--outcome", "rejected")
    drift = revision.certified_drift(p)
    rd = json.loads((p / ".wf/revisions/R001.json").read_text(encoding="utf-8"))
    record("C1 reproduced: before 1.22.0 an S24 round's journal-layer receipt (archived by the switch) "
           "was drift for every new-epoch render; now the switch marks it superseded and it is "
           "not drift", sw.returncode == 0 and rd.get("journal_layer_superseded") == 1
           and "08_submission/manuscript/cover_note.md" not in drift, f"{drift} {_out(sw)[-200:]}")
    st = State(p, ".wf").load()
    st.data["current"] = "S23_package"
    st.save()
    _w(p, "05_figures/code/fig1.py", FIG_SCRIPT)
    r = _run(p, "tools/wf.py", "run-script", "05_figures/code/fig1.py", cwd=p)
    rb = _run(p, "tools/wf.py", "rebuild", cwd=p)
    record("C1 S25 PASS -> rejected -> switch -> S20-S23: wf run-script and wf rebuild succeed in "
           "the new epoch", r.returncode == 0 and rb.returncode == 0, _out(r)[-300:] + _out(rb)[-300:])
    (p / "07_manuscript/full_manuscript.md").write_text("# Results\n\nMortality was 99%.\n", encoding="utf-8")
    record("C1 science-layer receipts are untouched: an edited certified manuscript is still drift",
           "07_manuscript/full_manuscript.md" in revision.certified_drift(p))
    q = _paper(tmp / "legacy", "S23_package")
    _w(q, "08_submission/cover_letter.md", "Dear Editor of Journal A\n")
    _closed_round(q, "R001", ["08_submission/cover_letter.md"], when="2026-01-01T00:00:00Z")
    _w(q, ".wf/journal_history.json", {"schema": 1, "epochs": [
        {"epoch": 1, "journal": "A", "started_at": "2025-12-01T00:00:00Z"},
        {"epoch": 2, "journal": "B", "started_at": "2026-02-01T00:00:00Z"}]})
    _w(q, "08_submission/cover_letter.md", "Dear Editor of Journal B\n")
    record("C1 a paper that switched before 1.22.0 (no mark) is judged by the epoch start: the old "
           "round's journal-layer receipt is not drift", revision.certified_drift(q) == [],
           str(revision.certified_drift(q)))

    # C2 bookkeeping round
    b = _paper(tmp / "bk", "S22_polish")
    _w(b, "08_submission/notes_text.md", "Mortality was 23.4% in 2020.\n")
    _w(b, "08_submission/old_table.md", "Table 9 draft\n")
    _w(b, "03_analysis/results/x.json", {"a": 1})
    _closed_round(b, "R001", ["08_submission/notes_text.md", "08_submission/old_table.md",
                              "03_analysis/results/x.json"])
    _w(b, "08_submission/notes_text.md", "In 2020, mortality was 23.4%.\n")
    (b / "08_submission/old_table.md").unlink()
    ok = _run(b, "tools/rework.py", "bookkeep", "--why", "wording reordered, stale draft table removed",
              "--replaced", "08_submission/notes_text.md", "--deleted", "08_submission/old_table.md")
    bk = json.loads((b / ".wf/revisions/R002.json").read_text(encoding="utf-8")) \
        if (b / ".wf/revisions/R002.json").is_file() else {}
    g = _gate(b, "revision_rounds_closed", "S24_package_human_review")
    record("C2 rework.py bookkeep at any stage (here S22) registers a fact-identical replacement "
           "and a deletion of certified files as a closed, audited round; drift is gone and "
           "revision_rounds_closed passes", ok.returncode == 0 and bk.get("kind") == "bookkeeping"
           and revision.certified_drift(b) == [] and g.ok and "已登记 R002" in _out(ok),
           _out(ok)[-400:] + g.detail)
    _w(b, "08_submission/notes_text.md", "In 2020, mortality was 25.0%.\n")
    bad = _run(b, "tools/rework.py", "bookkeep", "--why", "a number changed here by mistake",
               "--replaced", "08_submission/notes_text.md")
    (b / "03_analysis/results/x.json").unlink()
    sci = _run(b, "tools/rework.py", "bookkeep", "--why", "results file deleted by mistake",
               "--deleted", "03_analysis/results/x.json")
    unk = _run(b, "tools/rework.py", "bookkeep", "--why", "an uncertified file was replaced",
               "--replaced", "08_submission/never.md")
    record("C2 refusals: a changed number (classifier), a deleted results file (science) and an "
           "uncertified file - each with a Chinese reason pointing to a normal round",
           bad.returncode == 2 and "拒绝登记" in _out(bad) and "numbers" in _out(bad)
           and sci.returncode == 2 and "science" in _out(sci) and unk.returncode == 2
           and "不是受认证文件" in _out(unk), _out(bad)[-300:] + _out(sci)[-200:])

    # C3 derived files certified by their build receipt; deletion credentials in mark
    d = _paper(tmp / "der", "S24_package_human_review")
    src = _w(d, "08_submission/manuscript/full_manuscript.md", "# Results\n\nText.\n")
    out = _w(d, "08_submission/bundle/manuscript.docx", "v1")
    _closed_round(d, "R001", ["08_submission/bundle/manuscript.docx"])
    out.write_text("v2 rebuilt with new container timestamps", encoding="utf-8")
    _w(d, "08_submission/build_receipts/manuscript.json", {
        "kind": "manuscript", "output": "08_submission/bundle/manuscript.docx",
        "output_sha256": _sha(out), "sources": [{"path": src.relative_to(d).as_posix(),
                                                 "sha256": _sha(src)}], "auxiliaries": [],
        "engine": "1.22.0"})
    held = revision.certified_drift(d)
    out.write_text("hand edit", encoding="utf-8")
    edited = revision.certified_drift(d)
    record("C3 a rebuilt derived file whose build receipt inputs match is not drift (its bytes "
           "changed); a hand edit of it still is", held == [] and edited == ["08_submission/bundle/manuscript.docx"],
           f"{held} {edited}")
    m = _paper(tmp / "mark", "S24_package_human_review")
    gone = _w(m, "08_submission/manuscript/old_note.md", "x\n")
    from wfcore import revision as rv
    base = rv.snapshot(m)
    _w(m, ".wf/revisions/R001.json", {
        "schema_version": 2, "round_id": "R001", "status": "active",
        "review_stage": "S24_package_human_review", "baseline": base, "items": [
            {"id": "R001-01", "status": "pending", "affected_sources": ["08_submission/manuscript/old_note.md"],
             "kind": "x", "request": "remove the note"}], "allowed_files": []})
    st = State(m, ".wf").load()
    st.data["active_revision_round"] = "R001"
    st.save()
    gone.unlink()
    mk = _run(m, "tools/rework.py", "mark", "--item", "R001-01", "--summary",
              "removed the obsolete note file from the journal copy", "--changed-file",
              "08_submission/manuscript/old_note.md", "--validated-by", "inspection")
    rec = json.loads((m / ".wf/revisions/R001.json").read_text(encoding="utf-8"))["items"][0]
    record("C3 reproduced: `mark --changed-file` on a deleted certified file failed ('changed file "
           "does not exist'); now it records a deletion credential", mk.returncode == 0
           and rec.get("changed_files", [{}])[0].get("deleted") is True, _out(mk)[-300:])
    rcp = (ROOT / "tools/manuscript/build_docx.py").read_text(encoding="utf-8")
    record("C3 build receipts record the engine version with inputs and command",
           'payload["engine"] = engine_version()' in rcp
           and "engine_version()" in (ROOT / "tools/wfcore/supplementary.py").read_text(encoding="utf-8"))


# ------------------------------------------------------------------------------ C4
BAD_FIG = """import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from wfcore import paths
P = paths.project_dir(check_engine=False)
img = np.zeros((400, 600, 3))
(P / "05_figures/out").mkdir(parents=True, exist_ok=True)
plt.imsave(P / "05_figures/out/Figure1.png", img)
"""


def run_qc(tmp: Path, record, section) -> None:
    section("1.22.0 C4: figure QC runs at once at the new size after a re-render")
    p = _paper(tmp / "q", "S23_package")
    _w(p, "01_protocol/artifact_plan.json", {"main_figures": [
        {"id": "Figure 1", "file": "05_figures/out/Figure1.png", "width": "double"}],
        "main_tables": [], "supp_figures": [], "supp_tables": [], "supp_files": []})
    _w(p, "05_figures/code/bad.py", BAD_FIG)
    r0 = _run(p, "tools/wf.py", "run-script", "05_figures/code/bad.py", cwd=p)
    _w(p, "08_submission/target_journal.json", {"journal": "Journal B"})
    r = _run(p, "tools/wf.py", "run-script", "05_figures/code/bad.py", cwd=p)
    record("C4 counterexample: before a journal is in play the render passes as in 1.21; with a "
           "journal, a figure that fails QC at its final size fails on the spot with the figure "
           "and the problem", r0.returncode == 0 and r.returncode == 2 and "Figure 1" in _out(r)
           and "图表质控" in _out(r), _out(r0)[-200:] + _out(r)[-500:])
    from wfcore import rebuild
    src = (ROOT / "tools/wfcore/rebuild.py").read_text(encoding="utf-8")
    record("C4 wf rebuild runs the same QC after re-rendering figures (failures are rebuild "
           "failures)", "figure_qc(project, pngs)" in src and callable(rebuild.figure_qc))


# ------------------------------------------------------------------------------ C5/C6/R1-R3
def _report(path: Path, lines: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("## Verdict\n\n" + "\n".join(lines) + "\n", encoding="utf-8")
    return path


def run_review(tmp: Path, record, section) -> None:
    from wfcore import convergence as cv, reviewrounds as rr
    section("1.22.0 C5/C6/R1-R3: review bundles converge (no stale renders, engine counts, "
            "previous round, fixed must-fix rule, caps, key results)")
    p = _paper(tmp / "r", "S19_human_review")
    _w(p, "01_protocol/artifact_plan.json", {"main_figures": [], "main_tables": [], "supp_figures": [],
                                             "supp_tables": [], "supp_files": []})
    _w(p, "05_figures/legends.md", "# Legends\n")
    _w(p, "04_tables/table_captions.md", "# Captions\n")
    _w(p, "07_manuscript/full_manuscript.md", "# Abstract\n\nBackground: one two three.\n\nKeywords: a\n\n"
                                              "# Introduction\n\nWords here [@a].\n\n# Results\n\nHR 1.87.\n")
    _w(p, "08_submission/target_journal.json", {"journal": "J", "limits": {
        "abstract_words": 250, "main_text_words": 3000, "source": "guide L0002"}})
    _w(p, "03_analysis/results/primary.json", {"hr": 1.87, "ci": [1.2, 2.9], "units": "per 10 mg/kg",
                                               "population": "all_cases", "covariates": "age, sex",
                                               "environment": {"python": "3.13"}})
    src = _w(p, "08_submission/manuscript/full_manuscript.md",
             (p / "07_manuscript/full_manuscript.md").read_text(encoding="utf-8"))
    stale = _w(p, "08_submission/bundle/manuscript.docx", "old journal build")
    _w(p, "08_submission/build_receipts/manuscript.json", {
        "kind": "manuscript", "output": "08_submission/bundle/manuscript.docx",
        "output_sha256": _sha(stale), "sources": [{"path": src.relative_to(p).as_posix(),
                                                   "sha256": "0" * 64}], "auxiliaries": []})
    rnd = rr.start(p, "manuscript", "S19_human_review")
    out = rr.write_bundle(p, rnd)
    man = (out / "MANIFEST.md").read_text(encoding="utf-8")
    brief = rr.brief(p, rnd, out)
    record("C5 a stale Word build (inputs changed since it was built) is omitted from the bundle "
           "and marked STALE - never rendered for the reviewer", "STALE" in man
           and "08_submission/bundle/manuscript.docx" in man.split("Omitted stale")[1]
           and not (out / "files/manuscript.docx.txt").exists(), man[-600:])
    record("C6 the brief carries the engine counts with the rule ('abstract 4/250 words', do not "
           "recount)", "do NOT recount" in brief and "abstract 4/250 words" in brief
           and "engine count" in brief, brief[-500:])
    kr = (out / "files/key_results.md").read_text(encoding="utf-8")
    record("R3 key_results.md lists estimates with CI, units, population and covariates from the "
           "results JSON (not the environment); the brief requires checking against it",
           "hr = 1.87" in kr and "ci = [1.2, 2.9]" in kr and "units = per 10 mg/kg" in kr
           and "covariates = age, sex" in kr and "python" not in kr and "cannot verify" in brief, kr[:400])
    record("R2 the fixed must-fix definition is in every brief and in the reviewer prompt",
           "MUST-FIX only when it changes a number, a conclusion, or a reader's correct" in brief
           and "Must-fix, fixed definition" in (ROOT / ".kiro/agents/medpaper-reviewer.md").read_text(encoding="utf-8"))
    rep = _report(out / "report.md", ["F1 [numbers] MUST-FIX: the HR in the abstract differs",
                                      "F2 [other] OPTIONAL: shorter title", "F3 [other] OPTIONAL: comma"])
    c1 = rr.close(p, "manuscript", {"major": 1}, [{"file": "07_manuscript/full_manuscript.md",
                                                    "summary": "HR corrected"}], [],
                  [{"id": "F1", "category": "numbers", "status": "changed", "summary": "HR fixed"}],
                  report=rep, preference_reason="optional wording, deferred to typesetting")
    rr.decide(p, "manuscript", rr.ANOTHER, "再审一轮")
    record("R2 optional findings close as one group with one reason; a must-fix round is not READY",
           c1["preference_group"]["ids"] == ["F2", "F3"] and c1["ready"] is False
           and c1["must_fix"] == ["F1"], json.dumps(c1.get("preference_group")))
    _w(p, "07_manuscript/full_manuscript.md", "# Abstract\n\nBackground: one two four.\n\n# Results\n\nHR 1.87.\n")
    r2 = rr.start(p, "manuscript", "S19_human_review", delta=True)
    out2 = rr.write_bundle(p, r2)
    man2 = (out2 / "MANIFEST.md").read_text(encoding="utf-8")
    closed = (out2 / "files/closed_findings.md").read_text(encoding="utf-8")
    record("R1 a delta bundle has the previous report and the closed/kept findings with decision "
           "and reason; the brief says judge only this round's changes, regressions, new must-fix",
           (out2 / "files/previous_report.md").is_file() and "previous_report.md" in man2
           and "M001 F1 [numbers] fixed" in closed and "optional wording" in closed
           and "judge ONLY this round's changes" in rr.brief(p, r2, out2), closed)
    rep2 = _report(out2 / "report.md", ["F1 [other] OPTIONAL: could trim the intro"])
    c2 = rr.close(p, "manuscript", {}, [], [], [], report=rep2,
                  preference_reason="optional only, kept as written")
    rr.decide(p, "manuscript", rr.ANOTHER, "再看一轮")
    record("R2 a round with no new must-fix is READY", c2["ready"] is True)
    r3 = rr.start(p, "manuscript", "S19_human_review", delta=True)
    rr.write_bundle(p, r3)
    _report(p / rr.BUNDLE_DIR / r3["id"] / "report.md", ["F1 [other] OPTIONAL: x"])
    rr.close(p, "manuscript", {}, [], [], [], report=p / rr.BUNDLE_DIR / r3["id"] / "report.md",
             preference_reason="optional only, kept as written")
    rr.decide(p, "manuscript", rr.ANOTHER, "再看一轮")
    r4 = rr.start(p, "manuscript", "S19_human_review", delta=True)
    zh = cv.cap_summary_zh(p, "manuscript")
    record("R2 after the cap (manuscript 3 rounds) the next round is regression-only, with one "
           "Chinese summary of the remaining items and a recommendation",
           r4["mode"] == "regression" and "check ONLY for regressions" in rr.brief(p, r4, Path("x"))
           and zh[0].startswith("稿件审阅已达到轮次上限（3 轮") and "建议" in zh[-1], "\n".join(zh))
    q = _paper(tmp / "fast", "S24_package_human_review")
    cfg = _run(q, "tools/wf.py", "config", "set", "review_mode", "fast")
    record("U4 fast mode lowers the caps (manuscript 2, package 0 LLM rounds, S25 1); the config "
           "command explains it in Chinese", cfg.returncode == 0 and "快速模式" in _out(cfg)
           and cv.cap(q, "manuscript") == 2 and cv.cap(q, "package") == 0 and cv.cap(q, "audit") == 1
           and cv.cap(p, "audit") == 2, _out(cfg)[-300:])


# ------------------------------------------------------------------------------ U1-U5
def run_user(tmp: Path, record, section) -> None:
    import subprocess
    import selftest_v181 as v181
    from selftest_v1170 import _frozen_paper
    from wfcore import reviewrounds as rr, userdecisions
    import rework
    section("1.22.0 U1-U5: user decisions recorded once, fewer pauses, equivalent confirmation, "
            "stage time, Chinese messages")
    p = _paper(tmp / "u1", "S20_journal")
    _w(p, "08_submission/target_journal.json", {"journal": "Journal X", "chosen_by_user": True})
    _w(p, "00_input/author_info.json", {"authors": [{"name": "A"}, {"name": "B"}]})
    s1 = _run(p, "tools/wf.py", "status", "--brief", cwd=p)
    s2 = _run(p, "tools/wf.py", "status", "--brief", cwd=p)
    dec = userdecisions.load(p)["decisions"]
    events = [e for e in json.loads((p / ".wf/state.json").read_text(encoding="utf-8"))["events"]
              if e.get("kind") == "user_decisions_seeded"]
    record("U1 the first wf command seeds .wf/user_decisions.json from the paper's state (one "
           "event; the second command adds none)", dec.get("target_journal", {}).get("value") == "Journal X"
           and "authors" in dec and len(events) == 1 and "已记录用户既定决定" in _out(s1)
           and "已记录用户既定决定" not in _out(s2), _out(s1)[-400:])
    st = _run(p, "tools/wf.py", "decisions", "set", "apc_policy", "APC <= 2000 USD", "--words",
              "版面费不超过2000美元", cwd=p)
    bad = _run(p, "tools/wf.py", "decisions", "set", "nonsense", "x", "--words", "随便", cwd=p)
    show = _run(p, "tools/wf.py", "decisions", "show", cwd=p)
    ho = _run(p, "tools/wf.py", "handoff", cwd=p)
    card = _run(p, "tools/wf.py", "card", cwd=p)
    record("U1 `wf decisions set/show` records the user's words with date and source; handoff "
           "lists the decisions; every card says to read them before asking",
           st.returncode == 0 and "已记录：apc_policy" in _out(st) and bad.returncode == 2
           and "版面费不超过2000美元" in _out(show) and "apc_policy=APC <= 2000 USD" in _out(ho)
           and "`wf decisions show`" in _out(card) and "ONE Chinese line" in _out(card),
           _out(st)[-200:] + _out(ho)[-300:])
    _w(p, "08_submission/journal_shortlist.md", "# Journal\n\n## Eligibility screen\n\nJournal X: "
                                                "SCIE, Q2, no integrity warning.\n")
    named = _gate(p, "md_sections", "S20_journal", path="08_submission/journal_shortlist.md",
                  headings=["Eligibility screen", "Ranking basis", "Shortlist", "Reject-fallback cascade"])
    q = _paper(tmp / "u1b", "S20_journal")
    _w(q, "08_submission/journal_shortlist.md", "# Journal\n\n## Eligibility screen\n\nx\n")
    unnamed = _gate(q, "md_sections", "S20_journal", path="08_submission/journal_shortlist.md",
                    headings=["Eligibility screen", "Ranking basis", "Shortlist", "Reject-fallback cascade"])
    record("U1 S20 with a user-named journal verifies it only (no shortlist); without a named "
           "journal the shortlist is still required", named.ok and not unnamed.ok,
           named.detail + " | " + unnamed.detail)
    f = _frozen_paper(tmp / "sw")
    userdecisions.put(f, "spelling", "US", "用美式拼写")
    userdecisions.put(f, "portal_check", "yes", "你帮我看投稿系统")
    sw = _run(f, "tools/wf.py", "journal", "switch", "--to", "Journal B", "--confirm-old", "Journal A",
              "--why", "rejected after peer review: scope", "--outcome", "rejected")
    d2 = userdecisions.load(f)
    record("U1 a journal switch keeps journal-independent decisions, archives journal-dependent "
           "ones and records the new journal as the user's decision",
           sw.returncode == 0 and d2["decisions"]["spelling"]["value"] == "US"
           and "portal_check" not in d2["decisions"]
           and d2["decisions"]["target_journal"]["value"] == "Journal B"
           and any(h.get("key") == "portal_check" for h in d2.get("history", []))
           and "用户既定决定" in _out(sw), _out(sw)[-300:])

    # U2/U3 through the CLI
    r, env = v181._review_paper(tmp / "rev")

    def cli(*args):
        args = v181.with_report(list(args), r)
        return subprocess.run([sys.executable, "-B", str(ROOT / "tools/review_round.py"), *args,
                               "--project", str(r)], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", env=env)
    cli("start")
    other = cli("close", "--findings", "major=1", "--finding", "F1", "other", "author", "label wording")
    closed = cli("close", "--findings", "major=2", "--finding", "F1", "numbers", "author", "HR rounding",
                 "--finding", "F2", "grouping", "author", "merge age bands", "--recommend", "F2", "change")
    record("U2 presentation/label findings are never handed to the author; protected findings "
           "proposed for keeping are asked in ONE message with a recommendation each",
           other.returncode != 0 and "不要交给作者" in other.stderr and closed.returncode == 0
           and "待您决定的条目 2 项" in closed.stdout and "F1［numbers］HR rounding -> 建议：保留" in closed.stdout
           and "F2［grouping］merge age bands -> 建议：修改" in closed.stdout,
           other.stderr[-200:] + closed.stdout[-600:])
    vague = cli("author", "all", "--words", "好的")
    allr = cli("author", "all", "--words", "按你的建议")
    last = rr.latest(r, "manuscript")
    choices = {x["id"]: (x.get("author_decision") or {}).get("choice") for x in last["finding_list"]}
    record("U2 '按你的建议' accepts every recommendation in one reply; a vague reply does not",
           vague.returncode != 0 and allr.returncode == 0 and "已按建议记录 2 项" in allr.stdout
           and choices == {"F1": "keep", "F2": "change"}, allr.stdout[-200:] + str(choices))
    record("U3 the first confirmation request states the sentence, the preconditions and every "
           "pending item at once", "回复“我确认这一版”" in closed.stdout and "确认前提" in closed.stdout
           and "“OK / 可以 / 好的 / 没问题 / 无需审阅”不算确认" in closed.stdout)
    yes = ["我确认这一版", "我确认此版", "确认这个版本，可以投了", "好的，我确认本版。", "I confirm this version."]
    no = ["OK", "可以", "好的", "没问题", "无需审阅", "不确认这一版", "这一版还要改", "我确认"]
    ry = ["我确认回退", "好的，我确认回退。", "I confirm the rewind, go ahead"]
    rn = ["可以回退", "OK", "我不确认回退", "不要回退"]
    ok = cli("decide", "no_further_review", "--words", "确认这一版，没有其他修改")
    record("U3 equivalent explicit sentences confirm (确认 + 这一版/此版/本版/这个版本; 我确认回退 "
           "inside a sentence); OK/可以/好的/没问题/无需审阅 and negations never do",
           all(rr.is_confirmation(w) for w in yes) and not any(rr.is_confirmation(w) for w in no)
           and all(rework._is_rewind_confirmation(w) for w in ry)
           and not any(rework._is_rewind_confirmation(w) for w in rn) and ok.returncode == 0,
           str([w for w in yes if not rr.is_confirmation(w)]) + str([w for w in no if rr.is_confirmation(w)])
           + ok.stderr[-200:])
    tm = _run(p, "tools/wf.py", "status", "--brief", cwd=p)
    record("U4/U5 wf status shows the stage's expected duration/credit class and the time spent, "
           "in Chinese", "预计耗时/额度：中（medium，约 15-40 分钟）" in _out(tm) and "本阶段已用" in _out(tm),
           _out(tm)[:600])


GROUPS = [("certs", run_certs), ("qc", run_qc), ("review", run_review), ("user", run_user)]
