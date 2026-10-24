"""1.9.0 regression tests: the 25 items of a full S01-S25 run report (content-classified
post-freeze changes, journal-driven Word structure, deterministic derived files, false-positive
fixes, builder fixes, S12 consistency checks, quiet checks, preview, final-copy end state).

Called from tools/selftest.py.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def _card(name) -> str:
    """1.12.0 (D1): a stage card plus its reference/stage_details/ long form."""
    from wfcore.registry import card_full_text
    return card_full_text(name)

sys.path.insert(0, str(ROOT / "tools"))


def _env(p: Path) -> dict:
    return {**os.environ, "MEDPAPER_PROJECT": str(p), "MEDPAPER_ROOT": str(ROOT),
            "PYTHONIOENCODING": "utf-8"}


def _run(p: Path, tool: str, *args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-B", str(ROOT / tool), *map(str, args)],
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          env=_env(p))


def _docx(path: Path, paragraphs: list[str], author: str = "") -> Path:
    from docx import Document
    doc = Document()
    for text in paragraphs:
        doc.add_paragraph(text)
    doc.core_properties.author = author
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)
    return path


def _frozen_s24(base: Path) -> Path:
    """A paper at S24 with a frozen scientific record and a journal variant."""
    import selftest_v180 as v180
    from wfcore import scifreeze
    p = v180._rw_paper(base, "S24_package_human_review")
    files = {
        "07_manuscript/full_manuscript.md": "# T\n\n# Results\n\nThe hazard ratio was 1.87 "
                                            "(Figure 1) [@a].\n",
        "05_figures/legends.md": "# Figure legends\n\n## Figure 1.\nHaemoglobin by group. (A) "
                                 "Women. (B) Men.\n",
        "06_refs/refs.bib": "@article{a, title={A}, year={2020}}\n",
        "06_refs/library.json": "{\"a\": {}}",
        "03_analysis/results/primary.json": "{\"hr\": 1.87}",
    }
    for rel, text in files.items():
        (p / rel).parent.mkdir(parents=True, exist_ok=True)
        (p / rel).write_text(text, encoding="utf-8")
    scifreeze.write_freeze(p)
    return p


def _plan(tmp: Path, name: str, kind: str, src: str, request: str) -> Path:
    path = tmp / f"{name}.json"
    path.write_text(json.dumps({
        "feedback_verbatim": request,
        "interpretation": "Apply the user's request to the named source only and keep every other "
                          "approved artifact unchanged.",
        "ambiguous_or_requires_user_decision": [],
        "items": [{"kind": kind, "request": request, "affected_sources": [src],
                   "acceptance_criteria": ["The requested change is visible in the source",
                                           "Nothing unrelated changed"]}]}), encoding="utf-8")
    return path


def run_rounds(tmp: Path, record, section) -> None:
    from wfcore import presentation, revision as rv, scifreeze
    section("1.9.0 post-freeze changes classified by content; rework kinds and credentials")
    # 1. presentation vs scientific, classified by facts not directory
    p = _frozen_s24(tmp / "pres")
    base = presentation.snapshot_facts(p)
    leg = p / "05_figures/legends.md"
    leg.write_text(leg.read_text(encoding="utf-8").replace("Haemoglobin", "Hemoglobin"), encoding="utf-8")
    pres = presentation.classify(p, base, ["05_figures/legends.md"])
    ms = p / "07_manuscript/full_manuscript.md"
    old_ms = ms.read_text(encoding="utf-8")
    ms.write_text(old_ms.replace("1.87", "1.91"), encoding="utf-8")
    sci = presentation.classify(p, base, ["07_manuscript/full_manuscript.md"])
    ms.write_text(old_ms.replace("(Figure 1)", "(Figure 1)").replace("was", "was  "), encoding="utf-8")
    spacing = presentation.classify(p, base, ["07_manuscript/full_manuscript.md"])
    ms.write_text(old_ms, encoding="utf-8")
    leg.write_text(leg.read_text(encoding="utf-8").replace("Hemoglobin", "Haemoglobin"), encoding="utf-8")
    record("facts unchanged (spelling, spacing) -> presentation; a changed number -> scientific",
           pres["class"] == "presentation" and spacing["class"] == "presentation"
           and sci["class"] == "scientific" and "1.87" in " ".join(sci["reasons"]),
           str(pres["reasons"] + sci["reasons"]))
    # end to end: an S24 legend spelling round stays at S24 and updates the freeze
    b = _run(p, "tools/rework.py", "batch", "--sealed", "--why", "The user asked for American spelling now.",
             "--plan", _plan(tmp, "pres", "artifact-plan-or-legend", "05_figures/legends.md",
                             "Use American spelling in the Figure 1 legend."), "--project", p)
    leg.write_text(leg.read_text(encoding="utf-8").replace("Haemoglobin", "Hemoglobin"), encoding="utf-8")
    c = _run(p, "tools/rework.py", "check", "--project", p)
    st = json.loads((p / ".wf/state.json").read_text(encoding="utf-8"))
    ok, problems, _ = scifreeze.verify_freeze(p)
    fz = scifreeze.load_freeze(p)
    record("an S24 presentation round: no return to S19, freeze updated with a presentation delta",
           b.returncode == 0 and "PRESENTATION" in c.stdout and st["current"] == "S24_package_human_review"
           and "manuscript_human_reviewed" in st.get("decisions", {}) and ok
           and fz.get("presentation_deltas") and "05_figures/legends.md" in fz["presentation_deltas"][-1]["files"],
           (b.stdout + b.stderr + c.stdout + c.stderr)[-400:] + str(problems))
    q = _frozen_s24(tmp / "sci")
    ms = q / "07_manuscript/full_manuscript.md"
    _run(q, "tools/rework.py", "batch", "--sealed", "--why", "The user corrected the reported ratio.",
         "--plan", _plan(tmp, "sci", "results-wording", "07_manuscript/full_manuscript.md",
                         "Correct the hazard ratio in the Results."), "--project", q)
    ms.write_text(ms.read_text(encoding="utf-8").replace("1.87", "1.91"), encoding="utf-8")
    c1 = _run(q, "tools/rework.py", "check", "--project", q)
    st1 = json.loads((q / ".wf/state.json").read_text(encoding="utf-8"))
    # 1.11.0 (#2e): never automatically - the check stops until the user's words are recorded.
    refused = _run(q, "tools/rework.py", "confirm-rewind", "--words", "OK", "--project", q)
    _run(q, "tools/rework.py", "confirm-rewind", "--words", "我确认回退", "--project", q)
    c2 = _run(q, "tools/rework.py", "check", "--project", q)
    st2 = json.loads((q / ".wf/state.json").read_text(encoding="utf-8"))
    record("an S24 round whose facts changed STOPS for the user's words, then escalates to S19",
           "SCIENTIFIC" in c1.stdout and "STOPPED" in c1.stdout and c1.returncode == 2
           and st1["current"] == "S24_package_human_review"
           and "manuscript_human_reviewed" in st1.get("decisions", {}) and refused.returncode != 0
           and "SCIENTIFIC" in c2.stdout and st2["current"] == "S19_human_review"
           and "manuscript_human_reviewed" not in st2.get("decisions", {}), (c1.stdout + c2.stdout)[-400:])
    # 6. kinds
    import rework
    from wfcore import registry
    pipe = registry.load()
    kinds = sorted([*rework.ROUTES, "manuscript-copyedit", "word-format-only"])
    try:
        rework._read_batch_plan(_plan(tmp, "js", "journal", "08_submission/target_journal.json",
                                      "Switch to another journal now."), kinds,
                                "S24_package_human_review", pipe)
        err = ""
    except ValueError as exc:
        err = str(exc)
    fmt = rework._read_batch_plan(_plan(tmp, "jf", "journal-format", "08_submission/journal.csl",
                                        "Fix the reference style of the journal."), kinds,
                                  "S24_package_human_review", pipe)
    record("'journal' is an alias of journal-switch, rejected at batch time; journal-format is layout",
           "journal-switch" in err and "--rewind" in err and fmt["items"][0]["change_type"] == "layout", err)
    # 5. deletion credential + 4. all drift listed + derived renewable
    r = tmp / "cred"
    (r / ".wf/revisions").mkdir(parents=True)
    for i in range(7):
        (r / f"04_tables/t{i}.md").parent.mkdir(parents=True, exist_ok=True)
        (r / f"04_tables/t{i}.md").write_text(f"v{i}", encoding="utf-8")
    items = [{"id": "R001-01", "status": "done", "validated_by": ["x"], "changed_files":
              [rv.receipt(r, f"04_tables/t{i}.md") for i in range(7)]
              + [{"path": "04_tables/gone.xlsx", "sha256": rv.DELETED, "deleted": True}]}]
    (r / ".wf/revisions/R001.json").write_text(json.dumps(
        {"schema_version": 1, "round_id": "R001", "status": "complete", "items": items}), encoding="utf-8")
    for i in range(7):
        (r / f"04_tables/t{i}.md").write_text(f"changed {i}", encoding="utf-8")
    from wfcore.checks.revisions import revision_rounds_closed

    class _S:
        data = {}
        dir = r / ".wf"
    res = revision_rounds_closed(type("C", (), {"state": _S, "project": r, "stage": None, "spec": {}})())
    (r / "04_tables/gone.xlsx").write_text("back", encoding="utf-8")
    back = revision_rounds_closed(type("C", (), {"state": _S, "project": r, "stage": None, "spec": {}})())
    record("revision_rounds_closed lists every drifted file at once and accepts a deletion credential",
           "7 changed source(s) drifted" in res.detail and "gone.xlsx" not in res.detail
           and "reappeared" in back.detail, res.detail[:200] + " | " + back.detail[-120:])
    record("tool-rewritten indexes are renewable; mark --deleted-file is a CLI option",
           rv.renewable("04_tables/manifest.json") and rv.renewable("05_figures/qc/qc_report.json")
           and "--deleted-file" in (ROOT / "tools/rework.py").read_text(encoding="utf-8"))


def run_determinism(tmp: Path, record, section) -> None:
    from wfcore import determinism, packagefreeze
    section("1.9.0 deterministic derived files; confirmation binds uploads by visible content")
    os.environ["MEDPAPER_PROJECT"] = str(tmp / "det")
    (tmp / "det/04_tables/main").mkdir(parents=True, exist_ok=True)
    from tables import threeline
    spec = ("T1", "Table 1. X", ["A", "B"], [["a", "1.0"]], ["Note."])
    a = threeline.write_table(tmp / "det/04_tables/main/T.xlsx", *spec).read_bytes()
    import time
    time.sleep(1.1)
    b = threeline.write_table(tmp / "det/04_tables/main/T.xlsx", *spec).read_bytes()
    record("the same table builds to the same xlsx bytes", a == b)
    d1 = _docx(tmp / "det/a.docx", ["Hello 1.87"])
    raw1, c1 = determinism.raw_sha256(d1), determinism.content_sha256(d1)
    time.sleep(1.1)
    with zipfile.ZipFile(d1) as zf:
        parts = [(i.filename, zf.read(i.filename)) for i in zf.infolist()]
    with zipfile.ZipFile(d1, "w") as zf:
        for name, blob in parts:
            zf.writestr(name, blob)  # new timestamps, same content
    tail = tmp / "det/tail.docx"
    tail.write_bytes(d1.read_bytes() + b"junk")
    record("visible-content hash ignores zip timestamps but not appended bytes",
           determinism.raw_sha256(d1) != raw1 and determinism.content_sha256(d1) == c1
           and determinism.content_sha256(tail) != c1)
    pdf = tmp / "det/x.pdf"
    pdf.write_bytes(b"%PDF-1.4\n1 0 obj << /CreationDate (D:20260101120000+08'00') >> endobj\n"
                    b"trailer << /ID [<ABCDEF><ABCDEF>] >>\n%%EOF")
    size = pdf.stat().st_size
    determinism.normalize(pdf)
    record("PDF dates and ID are fixed in place (same length)",
           pdf.stat().st_size == size and b"20260101" not in pdf.read_bytes()
           and b"ABCDEF" not in pdf.read_bytes())
    # 7. package freeze: uploads by content; evidence does not invalidate
    p = tmp / "pkg"
    sub = p / "08_submission"
    (sub / "cache").mkdir(parents=True)
    (sub / "cache/g.html").write_text("x", encoding="utf-8")
    for name in ("target_journal.json", "docx_style.json", "package_content_baseline.json"):
        (sub / name).write_text("{}", encoding="utf-8")
    for name in ("guidelines_extract.md", "submission_qc.md"):
        (sub / name).write_text("# x\n", encoding="utf-8")
    _docx(sub / "bundle/manuscript.docx", ["Results 1.87"])
    (sub / "bundle/manifest.json").write_text(json.dumps(
        {"items": [{"file": "08_submission/bundle/manuscript.docx", "role": "manuscript"}]}), encoding="utf-8")
    packagefreeze.write_freeze(p)
    (sub / "submission_qc.md").write_text("# x\n\nanother internal note\n", encoding="utf-8")
    ok1, pr1, _ = packagefreeze.verify_freeze(p)
    m = sub / "bundle/manuscript.docx"
    with zipfile.ZipFile(m) as zf:
        parts = [(i.filename, zf.read(i.filename)) for i in zf.infolist()]
    time.sleep(1.1)
    with zipfile.ZipFile(m, "w") as zf:
        for name, blob in parts:
            zf.writestr(name, blob)
    ok2, pr2, _ = packagefreeze.verify_freeze(p)
    _docx(m, ["Results 1.91"])
    ok3, pr3, _ = packagefreeze.verify_freeze(p)
    record("internal QC edits and a re-zipped identical upload keep the OK; a changed upload does not",
           ok1 and ok2 and not ok3 and any("manuscript.docx" in x for x in pr3), str(pr1 + pr2 + pr3))


def run_journal(tmp: Path, record, section) -> None:
    from manuscript import build_docx as bd
    from wfcore import journalspec, numfmt
    from wfcore.checks.text import backstage_hits, prose_list_problem
    section("1.9.0 journal-typed structure, prose, false positives, builders")
    tj = {"main_text_headings": ["Introduction", "Materials and Methods", "Results", "Discussion"],
          "keywords": {"min": 6, "max": 10, "separator": ";"}}
    md = "# Methods\n\nText.\n\nKeywords: a, b, c, d, e, f\n"
    out = bd.journal_structure(md, tj)
    rules = journalspec.keyword_rules(tj)
    record("DOCX build renames headings and re-joins keywords from target_journal.json",
           "# Materials and Methods" in out and "Keywords: a; b; c; d; e; f" in out
           and not journalspec.keyword_problems("a, b, c, d, e, f", rules)
           and journalspec.keyword_problems("a, b, c", rules)
           and not journalspec.keyword_problems("a, b, c", journalspec.keyword_rules({}))
           and "Materials and Methods" in journalspec.word_count_scope(tj))
    listy = "# Methods\n\n" + "\n".join(f"- criterion {i} applied to adults" for i in range(6)) + "\n"
    prose = "# Methods\n\nWe included adults. " * 3 + "\n\n- one exception\n"
    record("prose_not_lists fails a list-heavy body and passes prose with one item",
           prose_list_problem(listy, 3, 0.10) and not prose_list_problem(prose, 3, 0.5))
    record("CRediT role names are not backstage language; 'the original draft' still is",
           not backstage_hits("Writing \u2013 original draft; Writing \u2013 review & editing.")
           and backstage_hits("Unlike the original draft, we now adjust for age."))
    from wfcore import presentation
    record("in-word numbers (ICD-10, 5-minute, 2-second) and (1)-(4) markers are not facts",
           presentation.numbers(presentation.strip_non_facts(
               "ICD-10 codes, a 5-minute and 2-second window: (1) age, (2) sex.")) == [])
    p = tmp / "admin"
    (p / "00_input").mkdir(parents=True)
    (p / "00_input/author_info.json").write_text(json.dumps(
        {"authors": [{"name": "Ana Author", "email": "ana@example.org"}],
         "ethics": {"approval_number": "IRB-2024-0137"}}), encoding="utf-8")
    stripped = presentation.strip_admin("Approved (IRB-2024-0137).", presentation.admin_strings(p),
                                        "08_submission/manuscript/title_page.md")
    record("registered administrative facts are allowed on the title page",
           "0137" not in stripped and "IRB-2024-0137" in presentation.admin_strings(p))
    # 13. blinding
    (p / "08_submission").mkdir()
    (p / "08_submission/target_journal.json").write_text(json.dumps({"blinded_main_manuscript": True,
                                                                     "journal": "J"}), encoding="utf-8")
    page = bd._info_page(p)
    from wfcore import determinism, docxaudit
    leaky = _docx(p / "s.docx", ["Supplementary methods."], author="Ana Author")
    ids = docxaudit.identity_strings(p)
    found = docxaudit.blinding_problems(leaky, ids)
    determinism.normalize(leaky, blind=True)
    record("blinded journal: SI first page has no authors; metadata leak found and cleared",
           "Ana" not in page and any("metadata" in x for x in found)
           and not docxaudit.blinding_problems(leaky, ids), str(found))
    # 14. CSL patch + title protection
    from pubmed import build_library as bl
    csl = '<style class="in-text"><citation><layout delimiter=","/></citation></style>'
    patched = bd.patch_csl(csl.replace("/></citation>", '></layout></citation>'),
                           {"initialize_with_hyphen": False, "citation_brackets": True})
    record("paper-local CSL patch sets initialize-with-hyphen on <style> and brackets citations",
           '<style initialize-with-hyphen="false"' in patched and 'prefix="["' in patched
           and bl.protect_title("Mortality: A cohort of Poisson models") ==
           "Mortality: A cohort of {Poisson} models", patched)
    # 15. no-break spaces and column minimum
    nb = bd.nobreak("< 0.001 (n = 162) 95% CI")
    widths = bd._fit_widths([100, 100], [3000, 100], 2000)
    record("table cells keep '< 0.001', 'n = 162', '95% CI' together; columns fit their longest token",
           "<\u00a00.001" in nb and "n\u00a0=\u00a0162" in nb and "95%\u00a0CI" in nb
           and widths[0] >= 1900, nb + str(widths))
    # 16/17. number style and spelling from the journal
    st = {"p_space": True, "minus": "unicode", "thousands": ",", "interval": " to ",
          "spelling": "american"}
    txt = numfmt.apply_text("P <0.001; -0.42 (1.10-1.52); 12345 haemoglobin", st)
    record("number style and spelling come from the journal/paper config at build time",
           "P < 0.001" in txt and "\u22120.42" in txt and "(1.10 to 1.52)" in txt
           and "12,345" in txt and "hemoglobin" in txt
           and numfmt.apply_text("P <0.001", numfmt.DEFAULT) == "P <0.001", txt)


def run_checks(tmp: Path, record, section) -> None:
    import selftest_v180 as v180
    from wfcore.checks import display
    section("1.9.0 S12 numbering/panels, baseline counts, limits, quiet output, end state")
    cites = display.citations("See Table 2 and Table 1; Figure S2 then Figure S1; Figure 2C.")
    order = display.order_problems(cites)
    panels = display.panel_problems(cites, {("main figure", 2): {"A", "B", "C"}})
    whole = display.panel_problems(display.citations("Figure 2 shows it."),
                                   {("main figure", 2): {"A", "B"}})
    record("S12: first-citation order per series and per-panel citation are checked",
           any("main table" in x for x in order) and any("supp figure" in x for x in order)
           and panels and "A, B" in panels[0] and not whole, str(order + panels))
    from analysis.results import baseline_counts
    bc = baseline_counts([{"sex": "F", "arm": "a"}, {"sex": "M", "arm": "b"}, {"sex": None, "arm": "a"}],
                         ["sex"], "arm")
    record("baseline counts give both categories of a binary variable, overall and per group",
           set(bc["sex"]["overall"]["levels"]) == {"F", "M"} and bc["sex"]["a"]["missing"] == 1
           and bc["sex"]["b"]["levels"]["M"]["n"] == 1)
    p, _ = v180._paper(tmp / "lim", {"journal": "J", "limits": {"abstract_words": 4, "source": "guide"}})
    (p / "07_manuscript/full_manuscript.md").write_text("# T\n\n# Abstract\n\none two three four\n",
                                                        encoding="utf-8")
    at = v180._gate(p, "journal_limits_met", "S22_polish")
    (p / "07_manuscript/full_manuscript.md").write_text("# T\n\n# Abstract\n\none two three four five\n",
                                                        encoding="utf-8")
    over = v180._gate(p, "journal_limits_met", "S22_polish")
    record("a count at the cap passes (warning only); one word over fails",
           not at.blocking and at.severity == "warn" and over.blocking, at.detail + " | " + over.detail)
    q = v180._rw_paper(tmp / "quiet", "S03_protocol")
    s = _run(q, "tools/wf.py", "check", "--summary")
    lines = [ln for ln in s.stdout.splitlines() if ln.startswith("S03_protocol")]
    record("wf check --summary prints one result line", len(lines) == 1 and "passing" in lines[0]
           and "outputs_pending" in lines[0] and "->" not in s.stdout,
           s.stdout[-200:])
    # 8. engine pin
    from wfcore.state import State
    m = tmp / "pin"
    m.mkdir()
    st = State(m, ".wf").create("medpaper", "1.8.1", "S01_intake")
    st.stage_info("S01_intake")["status"] = "done"
    st.migrate_pipeline("1.9.0", ["S01_intake"])
    pinned = st.pin_excludes("S01_intake", "1.9.0") and not st.pin_excludes("S02_feasibility", "1.9.0")
    st.migrate_pin("1.9.0")
    record("a paper keeps its engine pin for completed stages until wf migrate",
           pinned and not st.pin_excludes("S01_intake", "1.9.0")
           and any("1.9.0" in e.get("detail", "") for e in st.data["events"]
                   if e["kind"] == "requirements_changed"))
    # 23. checklist DOCX
    from manuscript import checklist_docx
    src = tmp / "chk.md"
    src.write_text("# Reporting checklist\n\nGuideline: STROBE\nManuscript: 08_submission/manuscript/"
                   "full_manuscript.md\n\n| Item | Status | Location | Evidence | Reason |\n|---|---|---|---|---|\n"
                   "| 1a | Reported | Title; Abstract | quote | |\n", encoding="utf-8")
    out = checklist_docx.build(src, tmp / "chk.docx")
    with zipfile.ZipFile(out) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
    record("checklist DOCX: fixed column widths, Item not wrapped, no internal path",
           "w:noWrap" in xml and 'w:type="fixed"' in xml and "08_submission" not in xml
           and "Title/abstract" in xml)
    # 24. final copy
    from wfcore import finalcopy
    f = tmp / "final"
    _docx(f / "08_submission/bundle/manuscript.docx", ["Methods", "HR 1.87 [3]", "Table 1"])
    _docx(f / "08_submission/final_copy/manuscript.docx", ["Materials and Methods", "HR 1.87 [3]", "Table 1"])
    finalcopy.record(f, ["Renamed Methods heading per the guide"], "我确认这一版")
    ok, problems = finalcopy.check(f)
    _docx(f / "08_submission/final_copy/manuscript.docx", ["Materials and Methods", "HR 1.88 [3]", "Table 1"])
    changed = finalcopy.verified(f)
    bad, bad_p = finalcopy.check(f)
    record("author final copy: a heading edit passes; a changed number fails and stale checks are caught",
           ok and changed and not bad and any("numbers" in x for x in bad_p), str(problems + bad_p))
    cards = {n: _card(n)
             for n in ("S08_methods", "S09_results", "S14_introduction", "S16_discussion",
                       "S22_polish", "S23_package", "S25_submission_audit")}
    record("cards: prose rule in S08/S09/S14/S16/S22, portal to-do and preview in S23, final copy in S25",
           all("continuous paragraphs" in cards[n] for n in list(cards)[:5])
           and "Portal to-do" in cards["S23_package"] and "preview.py" in cards["S23_package"]
           and "final_copy.py" in cards["S25_submission_audit"])


def run(tmp: Path, record, section) -> None:
    tmp.mkdir(parents=True, exist_ok=True)
    old = os.environ.get("MEDPAPER_PROJECT")
    try:
        for fn, sub in ((run_rounds, "rounds"), (run_determinism, "det"), (run_journal, "journal"),
                        (run_checks, "checks")):
            try:
                fn(tmp / sub, record, section)
            except Exception as exc:  # noqa: BLE001
                import traceback
                record(f"1.9.0 {sub} tests ran to completion", False,
                       f"{type(exc).__name__}: {exc} " + traceback.format_exc()[-400:])
    finally:
        if old is None:
            os.environ.pop("MEDPAPER_PROJECT", None)
        else:
            os.environ["MEDPAPER_PROJECT"] = old
