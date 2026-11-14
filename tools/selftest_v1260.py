"""1.26.0 regression tests: the package is audited before the user's one confirmation; questions
travel with the S19 message; no Kiro workflows for papers; the run record.

audit    S24 round 1 is the full independent audit; a round that changed an upload must be
         re-audited before the confirmation; a re-audit that changes nothing allows it; BLOCKED
         waits for the missing fact.
s25      the freeze binds the audited round; record-audit makes it the S25 audit file (bound by
         content, not by a Freeze ID line); audit-start refuses such a freeze; PASS needs the
         last audit verdict PASS (REVISE can be confirmed, but only the author final copy then
         passes); a freeze from the earlier order keeps the S25 audit.
pinned   a paper pinned before 1.26.0 keeps the old S24/S25 order.
ask      the S19 confirmation block lists the basic facts still missing, and nothing once
         recorded; the S01/S19/S21/S24 cards say so.
runlog   engine commands write the run record; `wf report` summarises it and never fails.
release  version, one migration event, the new gate lines, cards/SKILL/steering/README.
Synthetic fixtures only - no real paper, dataset, network or browser. Called from
tools/selftest.py (or `selftest.py --only v1260`).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from selftest_v1140 import _gate, _out, _paper, _run, _w  # noqa: E402
from selftest_v1250 import _pin  # noqa: E402

S24 = "S24_package_human_review"
S25 = "S25_submission_audit"
AUDIT = "08_submission/independent_submission_audit.md"
SECTIONS = ("Reader comprehension", "Editorial screening and low-level errors",
            "Guideline compliance", "Required files and omissions", "Cross-file consistency",
            "Formatting and technical checks", "Issues requiring correction",
            "Final recommendation")


def run(tmp: Path, record, section, only: str = "") -> None:
    tmp.mkdir(parents=True, exist_ok=True)
    for name, fn in GROUPS:
        if not only or name in only.split():
            fn(tmp / name, record, section)


# ------------------------------------------------------------------------------ fixtures
def _docx(path: Path, text: str) -> Path:
    import docx
    path.parent.mkdir(parents=True, exist_ok=True)
    d = docx.Document()
    d.add_paragraph(text)
    d.save(str(path))
    return path


def _pkg(path: Path, at: str = S24) -> Path:
    """A minimal submission package the audit and the freeze can read."""
    p = _paper(path, at)
    _docx(p / "08_submission/bundle/manuscript.docx", "Methods. AKI was defined by KDIGO.")
    _w(p, "08_submission/bundle/manifest.json", {"items": [
        {"file": "08_submission/bundle/manuscript.docx", "role": "manuscript"}]})
    _w(p, "08_submission/target_journal.json", {"journal": "Journal of Tests"})
    _w(p, "08_submission/guidelines_extract.md", "# Extract\n\n- L0001 abstract <= 250 words\n")
    _w(p, "08_submission/docx_style.json", {})
    _w(p, "08_submission/submission_qc.md", "# Submission QC\n")
    _w(p, "08_submission/package_content_baseline.json", {})
    _w(p, "08_submission/cache/guide.html", "<html><body>Abstract: 250 words.</body></html>")
    _w(p, "08_submission/guidelines_source.txt", "L0001 Abstract: at most 250 words.\n")
    _w(p, "08_submission/compliance_matrix.json", {"rows": [
        {"id": "R01", "status": "PASS", "lines": "L0001", "quote": "Abstract: at most 250 words."}]})
    return p


def _report(rid: str, verdict: str, body: dict[str, str]) -> str:
    out = [f"## Verdict\n\nPackage round: {rid}\n\n{verdict}\n"]
    for s in SECTIONS:
        out.append(f"## {s}\n\n{body.get(s, 'none')}\n")
    return "\n".join(out)


FULL_REVISE = _report("P001", "REVISE", {
    "Reader comprehension": "- F1 MINOR manuscript.docx Methods: AKI is not defined",
    "Guideline compliance": "- R01: agree - the abstract has 212 words",
    "Issues requiring correction": "- F2 PREFERENCE manuscript.docx: a shorter title"})
RECHECK_PASS = _report("P002", "PASS", {
    "Reader comprehension": "- F1 MINOR: RESOLVED - manuscript.docx Methods: AKI now defined"})
RECHECK_REVISE = _report("P002", "REVISE", {
    "Reader comprehension": "- F1 MINOR: OPEN - manuscript.docx Methods: AKI still undefined"})


def _close(p: Path, rnd: dict, text: str, findings: list[dict], counts: dict,
           changes: list | None = None, kept: list | None = None, pref: str = "") -> dict:
    from wfcore import reviewrounds as rr
    rep = p / ".wf/review_bundle" / rnd["id"] / "report.md"
    rep.write_text(text, encoding="utf-8")
    return rr.close(p, "package", counts, changes or [], kept or [], findings, report=rep,
                    preference_reason=pref)


def _audited(path: Path, second: str = RECHECK_PASS) -> tuple[Path, dict, dict, str]:
    """Round 1 (full audit, a fix), round 2 (re-audit, no change), the user's confirmation."""
    from wfcore import packageaudit as pa, reviewrounds as rr
    p = _pkg(path)
    r1 = rr.start(p, "package", S24)
    b1 = rr.write_bundle(p, r1)
    _docx(p / "08_submission/bundle/manuscript.docx",
          "Methods. Acute kidney injury (AKI) was defined by KDIGO.")
    r1 = _close(p, r1, FULL_REVISE, [{"id": "F1", "category": "other", "status": "changed",
                                       "summary": "AKI defined at first use"}], {"minor": 1},
                changes=[{"file": "08_submission/bundle/manuscript.docx",
                          "summary": "AKI defined at first use"}],
                pref="a stylistic preference; the journal has no title rule")
    refused = ""
    try:
        rr.decide(p, "package", rr.DONE, "我确认这一版")
    except ValueError as exc:
        refused = str(exc)
    r2 = rr.start(p, "package", S24, delta=True)
    b2 = rr.write_bundle(p, r2)
    status = "open" if second is RECHECK_PASS else "kept"
    fl = [{"id": "F1", "category": "other", "status": "changed" if status == "open" else "kept",
           "summary": "resolved; verified by the re-audit" if status == "open" else "still open"}]
    r2 = _close(p, r2, second, fl, {"minor": 1},
                kept=[] if status == "open" else [{"item": "F1", "reason": "the author keeps the "
                                                   "abbreviation; defined in the abstract"}])
    probs = pa.problems(p)
    rr.decide(p, "package", rr.DONE, "我确认这一版")
    r2 = rr.load(p)["package"][-1]  # as stored, with the confirmed version
    info = {"b1": b1, "b2": b2, "refused": refused, "probs": probs,
            "man1": (b1 / "MANIFEST.md").read_text(encoding="utf-8"),
            "man2": (b2 / "MANIFEST.md").read_text(encoding="utf-8")}
    return p, r1, r2, info


# ------------------------------------------------------------------------------ audit
def run_audit(tmp: Path, record, section) -> None:
    from wfcore import packageaudit as pa, reviewrounds as rr
    section("1.26.0 audit: S24 round 1 is the full audit; every change is re-audited first")
    p, r1, r2, info = _audited(tmp / "flow")
    man1, man2 = (" ".join(info[k].split()) for k in ("man1", "man2"))
    record("round 1 is the full independent audit (the former S25 brief: three positions, every "
           "matrix row agree/disagree, MISSING obligations, engine issues, Package round line)",
           r1["mode"] == "audit" and "S24 independent package audit (P001, FULL" in man1
           and "first-time reader, an editor and a journal-compliance reviewer" in man1
           and "agree|disagree" in man1 and "MISSING L00nn" in man1 and "Engine issues" in man1
           and "Package round: P001" in man1 and "manuscript.docx" in man1
           and json.loads((info["b1"] / "rows_required.json").read_text(encoding="utf-8")) == ["R01"],
           man1[:300])
    record("the fixed round cannot be confirmed: the auditor has not read the change",
           "cannot be confirmed yet" in info["refused"] and "re-audit at once" in info["refused"]
           and "manuscript.docx" in info["refused"] and r1["audit_verdict"] == "REVISE",
           info["refused"][:300])
    prev = (info["b2"] / "previous_findings.md").read_text(encoding="utf-8")
    record("round 2 re-audits: previous BLOCKING/MINOR findings RESOLVED/OPEN plus new BLOCKING "
           "only (preferences are not re-checked); open matrix rows only",
           r2["mode"] == "recheck" and "RE-AUDIT of the changes made after P001" in man2
           and "F1 MINOR" in prev and "F2" not in prev
           and json.loads((info["b2"] / "rows_required.json").read_text(encoding="utf-8")) == []
           and r2.get("linked_to") == "P001", man2[:300] + prev)
    last = rr.load(p)["package"][-1]
    record("a re-audit that changed nothing and says PASS allows the one confirmation",
           info["probs"] == [] and last.get("user_decision") == rr.DONE
           and last.get("audit_verdict") == "PASS" and last.get("confirmed_version"),
           str(info["probs"]))
    g = _gate(p, "package_audit_ready", S24)
    record("S24 gate package_audit_ready passes on the confirmed, fully read package",
           g.ok and "P002" in g.detail, g.detail)
    # BLOCKED and no-audit counterexamples
    q = _pkg(tmp / "blocked")
    r = rr.start(q, "package", S24)
    rr.write_bundle(q, r)
    _close(q, r, _report("P001", "BLOCKED", {"Issues requiring correction":
                                              "- F1 BLOCKING title page: the ORCID is missing"}),
           [{"id": "F1", "category": "other", "status": "kept", "summary": "ORCID awaited"}],
           {"critical": 1}, kept=[{"item": "F1", "reason": "the author must supply the ORCID"}])
    blocked = pa.problems(q)
    record("a BLOCKED audit waits for the missing user-owned fact (no confirmation)",
           any("BLOCKED" in x for x in blocked), str(blocked))
    s = _pkg(tmp / "none")
    record("no full audit in this journal epoch: the S24 gate fails and says how to start it",
           not _gate(s, "package_audit_ready", S24).ok
           and "round 1 is the audit" in _gate(s, "package_audit_ready", S24).detail)


# ------------------------------------------------------------------------------ s25
def run_s25(tmp: Path, record, section) -> None:
    from wfcore import packageaudit as pa
    from wfcore.packagefreeze import verify_freeze, write_freeze
    from wfcore.state import State
    section("1.26.0 S25: the freeze binds the audited round; S25 verifies and records it")
    p, _r1, r2, _info = _audited(tmp / "ok")
    write_freeze(p)
    fz = json.loads((p / "08_submission/package_review_freeze.json").read_text(encoding="utf-8"))
    record("the freeze records the confirmed audit round, its version and verdict (freeze_id "
           "still covers the file records only)",
           fz.get("package_round") == "P002" and fz.get("confirmed_version") == r2["confirmed_version"]
           and fz.get("audit_verdict") == "PASS" and verify_freeze(p)[0], str({k: fz.get(k) for k in (
               "package_round", "audit_verdict")}))
    st = State(p, ".wf").load()
    st.stage_info(S24)["status"] = "done"
    st.data["current"] = S25
    st.stage_info(S25)["status"] = "active"
    st.save()
    start = _run(p, "tools/package_review.py", "audit-start")
    rec = _run(p, "tools/package_review.py", "record-audit")
    audit_text = (p / AUDIT).read_text(encoding="utf-8") if (p / AUDIT).is_file() else ""
    g = _gate(p, "submission_audit_matches_freeze", S25)
    record("S25 starts no second reading: audit-start refuses a 1.26.0 freeze; record-audit "
           "copies the bound S24 report verbatim; the audit file is bound by content",
           start.returncode == 2 and "already ran at S24" in _out(start) and rec.returncode == 0
           and audit_text == (p / ".wf/review_reports/P002.md").read_text(encoding="utf-8")
           and g.ok and "round P002" in g.detail, _out(start)[-200:] + _out(rec)[-200:] + g.detail)
    (p / AUDIT).write_text(audit_text + "\nEdited later.\n", encoding="utf-8")
    g2 = _gate(p, "submission_audit_matches_freeze", S25)
    record("an audit file that is not the bound round's report fails", not g2.ok
           and "not the saved report" in g2.detail, g2.detail)
    (p / AUDIT).write_text(audit_text, encoding="utf-8")
    st = State(p, ".wf").load()
    st.record_decision("submission_package_independent_audit", "PASS", "test")
    st.save()
    g3 = _gate(p, "package_audit_ready", S25, final=True)
    record("S25 final readiness: PASS with the last audit verdict PASS and the frozen uploads "
           "equal to what it read", g3.ok, g3.detail)
    # REVISE confirmed: PASS refused, the author final copy passes
    q, _a, _b, _i = _audited(tmp / "revise", second=RECHECK_REVISE)
    write_freeze(q)
    st = State(q, ".wf").load()
    st.record_decision("submission_package_independent_audit", "PASS", "test")
    st.save()
    g4 = _gate(q, "package_audit_ready", S25, final=True)
    st = State(q, ".wf").load()
    st.record_decision("submission_package_independent_audit", "PASS_AUTHOR_FINAL_COPY", "test")
    st.save()
    g5 = _gate(q, "package_audit_ready", S25, final=True)
    record("a REVISE audit may be confirmed, but S25 PASS is refused; the author final copy "
           "remains the route", not g4.ok and "says REVISE" in g4.detail and g5.ok,
           g4.detail + " | " + g5.detail)
    # a change after the freeze
    _docx(q / "08_submission/bundle/manuscript.docx", "Methods. Changed after the freeze.")
    record("a package changed after the confirmation is not recorded as the S25 audit",
           "changed after user confirmation" in str(_raises(lambda: pa.record_audit(q))))
    # a freeze from the earlier order (no audited round)
    lg = _pkg(tmp / "legacy", S25)
    write_freeze(lg)
    g6 = _gate(lg, "package_audit_ready", S25, final=True)
    record("a freeze without an audited round keeps the S25 audit (the line passes and says so; "
           "record-audit refuses)", g6.ok and "predates the 1.26.0 order" in g6.detail
           and "audit-start" in str(_raises(lambda: pa.record_audit(lg))), g6.detail)


def _raises(fn) -> str:
    try:
        fn()
    except (ValueError, OSError) as exc:
        return str(exc)
    return ""


# ------------------------------------------------------------------------------ pinned
def run_pinned(tmp: Path, record, section) -> None:
    from wfcore import packageaudit as pa, reviewrounds as rr
    section("1.26.0 pinned papers keep the earlier S24/S25 order")
    p = _pkg(tmp / "old")
    _pin(p, "1.25.1")
    rnd = rr.start(p, "package", S24)
    g = _gate(p, "package_audit_ready", S24)
    record("a 1.25.1 paper: the S24 round is the earlier package review (mode full), the new "
           "line passes as pinned, the freeze binds no round",
           rnd["mode"] == "full" and g.ok and "pinned earlier" in g.detail
           and pa.freeze_binding(p) == {} and not pa.audit_flow(p), rnd["mode"] + " " + g.detail)


# ------------------------------------------------------------------------------ ask
def run_ask(tmp: Path, record, section) -> None:
    from wfcore import convergence as cv, userdecisions as ud
    section("1.26.0 ask: basic author facts travel with the S19 confirmation message")
    p = _paper(tmp / "s19", "S19_human_review")
    before = "\n".join(cv.confirmation_zh(p, "manuscript"))
    for key, val in (("authors", "A. Author, B. Author; Hospital X; corresponding A, a@x.org"),
                     ("funding", "无"), ("conflicts", "无"), ("ai_use", "未使用"),
                     ("portal_check", "是")):
        ud.put(p, key, val, f"用户原话：{val}")
    after = "\n".join(cv.confirmation_zh(p, "manuscript"))
    record("the S19 confirmation block asks for the missing basic facts (authors, funding, "
           "conflicts, AI use, portal) and nothing once they are recorded",
           all(x in before for x in ("作者姓名与顺序", "基金资助", "利益冲突", "AI 工具", "投稿系统"))
           and "作者姓名与顺序" not in after and "我确认这一版" in after, before[-400:])
    q = _paper(tmp / "seed", "S21_authors")
    _w(q, "00_input/author_info.json", {"authors": [{"name": "A"}], "funding": "Grant 1",
                                        "conflicts": "none"})
    seeded = ud.seed(q)
    record("funding and conflicts are decision keys and are seeded from author_info.json",
           {"funding", "conflicts"} <= set(ud.KEYS) and {"funding", "conflicts"} <= set(seeded),
           str(seeded))
    card = {s: (ROOT / "pipeline/stages" / f"{s}.md").read_text(encoding="utf-8")
            for s in ("S01_intake", "S19_human_review", "S21_authors", S24)}
    record("cards: S01 asks for an already chosen journal; S19 puts the author facts in the one "
           "message; S21 asks only what is missing; S24 reuses the portal answer",
           "wf decisions set target_journal" in card["S01_intake"]
           and "Author facts only" in card["S19_human_review"]
           and "wf decisions set authors|funding|conflicts|ai_use|portal_check" in card["S19_human_review"]
           and "only what `wf decisions show` lacks" in card["S21_authors"]
           and "usually answered in the S19 message" in card[S24])


# ------------------------------------------------------------------------------ runlog
def run_runlog(tmp: Path, record, section) -> None:
    from wfcore import runlog
    section("1.26.0 run record: every engine command is logged; wf report summarises it")
    p = _paper(tmp / "rl", "S02_feasibility")
    chk = _run(p, "tools/wf.py", "check")
    kinds = [e.get("kind") for e in runlog.entries(p)]
    record("wf check writes a check line (blocking count, failing checks) and a command line",
           "check" in kinds and "cmd" in kinds and chk.returncode in (0, 2), str(kinds))
    with (p / runlog.REL).open("a", encoding="utf-8") as fh:
        for rec in ({"at": "2026-01-01T08:00:00Z", "stage": "S02_feasibility", "kind": "cmd",
                     "name": "wf check", "rc": 2, "seconds": 30},
                    {"at": "2026-01-01T10:00:00Z", "stage": "S02_feasibility", "kind": "subagent",
                     "agent": "medpaper-reviewer"},
                    {"at": "2026-01-01T10:05:00Z", "stage": "S02_feasibility", "kind": "reproduce",
                     "rc": 0, "seconds": 600},
                    {"at": "2026-01-01T10:06:00Z", "stage": "S02_feasibility", "kind": "cmd",
                     "name": "wf rebuild", "rc": 0}):
            fh.write(json.dumps(rec) + "\n")
    s = runlog.summary(p)["per"]["S02_feasibility"]
    rep = _run(p, "tools/wf.py", "report")
    record("wf report: idle gaps over 15 minutes, subagent calls, reproductions and rebuilds per "
           "stage; written to .wf/run_report.md",
           s["idle"] >= 7000 and s["subagents"]["medpaper-reviewer"] == 1 and s["repro"] == 1
           and s["rebuilds"] == 1 and rep.returncode == 0 and "运行记录" in _out(rep)
           and "S02_feasibility" in _out(rep) and (p / runlog.REPORT_REL).is_file(),
           _out(rep)[-400:])
    q = _paper(tmp / "fresh")
    outside = tmp / "not_a_paper"
    outside.mkdir(parents=True, exist_ok=True)
    runlog.log(outside, "cmd", name="x")
    record("the record never fails: a paper without a ledger reports; outside a paper nothing is "
           "written", bool(runlog.report(q, write=False)) and not (outside / runlog.REL).exists())


# ------------------------------------------------------------------------------ release
def run_release(tmp: Path, record, section) -> None:
    import tomllib
    from wfcore import adapters, registry
    from wfcore.state import State
    section("1.26.0 release: one migration event, gate lines, cards, SKILL, steering, README")
    q = tmp / "mig"
    q.mkdir(parents=True, exist_ok=True)
    st = State(q, ".wf").create("medpaper", "1.25.1", "S24_package_human_review")
    before = sorted(x.name for x in q.rglob("*"))
    st.migrate_pipeline("1.26.0", [s.id for s in registry.load().stages])
    st.migrate_pipeline("1.26.0", [s.id for s in registry.load().stages])
    notes = [e for e in st.data["events"] if e["kind"] == "requirements_changed"
             and str(e.get("detail", "")).startswith("1.26.0")]
    pipe = registry.load()
    gates = {(s.id, g["check"], bool(g.get("final"))) for s in pipe.stages for g in s.gate
             if g.get("since") == "1.26.0"}
    record("pipeline 1.26.0; a 1.25.1 paper gets one 1.26.0 event (questions, no workflows and "
           "the run record now; the S24/S25 order after wf migrate --yes) and stays pinned",
           pipe.meta.get("version") == "1.26.0" and len(notes) == 1
           and "wf migrate --yes" in notes[0]["detail"] and "package_audit_ready" in notes[0]["detail"]
           and st.engine_pin == "1.25.1" and before == sorted(x.name for x in q.rglob("*"))
           and gates == {(S24, "package_audit_ready", False), (S25, "package_audit_ready", True)},
           str(sorted(gates)))
    inv = "\n".join(tomllib.loads((ROOT / "pipeline/pipeline.toml").read_text(encoding="utf-8"))
                    ["policy"]["invariants"])
    cards = {s.id: (ROOT / "pipeline" / s.card).read_text(encoding="utf-8") for s in pipe.stages}
    skill = (ROOT / ".kiro/skills/medpaper-pipeline/SKILL.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    steer = dict(adapters.paper_adapters(ROOT, tmp))[".kiro/steering/medpaper-pipeline.md"]
    selftest = (ROOT / "tools/selftest.py").read_text(encoding="utf-8")
    record("docs: invariant, S24/S25 cards, SKILL (no Kiro workflows for papers), paper and "
           "engine steering, README; every card and SKILL within the limit; the 1.25.1 tests run "
           "once; selftest --only exists",
           "S25 then verifies the freeze" in inv and "review_round.py start --scope package" in cards[S24]
           and "record-audit" in cards[S25] and "never start a Kiro workflow" in skill
           and "1.26.0" in skill and len(skill) <= 9000 and "never start a Kiro workflow" in steer
           and "--only v1251,v1260" in adapters.STEERING_ENGINE and "## 1.26.0" in readme
           and "`1.26.0`" in readme and max(len(c) for c in cards.values()) <= registry.CARD_MAX_CHARS
           and selftest.count("selftest_v1251.run(") == 1 and selftest.count("selftest_v1260.run(") == 1
           and '"--only"' in selftest,
           str({k: len(v) for k, v in cards.items() if len(v) > 3900}) + f" skill={len(skill)}")


GROUPS = [("audit", run_audit), ("s25", run_s25), ("pinned", run_pinned), ("ask", run_ask),
          ("runlog", run_runlog), ("release", run_release)]
