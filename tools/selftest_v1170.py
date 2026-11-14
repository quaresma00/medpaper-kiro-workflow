"""1.17.0 regression tests: journal switching without leftovers (J1-J3), guideline ingestion
(J4), journal lookup by ISSN (J5), CSL by ISSN (J6) and render parameters (J7). Counterexample
first: each leak below passed the 1.16.0 gates. Synthetic fixtures only - no real paper, dataset
or network is used (lookup and CSL fetches read recorded responses).

Called from tools/selftest.py.
"""
from __future__ import annotations

import io
import json
import os
import sys
import zipfile
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from selftest_v1140 import _env, _gate, _out, _paper, _run, _w  # noqa: E402


def run(tmp: Path, record, section, only: str = "") -> None:
    tmp.mkdir(parents=True, exist_ok=True)
    for name, fn in GROUPS:
        if not only or name in only.split():
            fn(tmp / name, record, section)


def _pin(p: Path, version: str) -> None:
    st = json.loads((p / ".wf/state.json").read_text(encoding="utf-8"))
    st["engine_pin"] = version
    (p / ".wf/state.json").write_text(json.dumps(st), encoding="utf-8")


GUIDE = [
    "Instructions for Authors",
    "Article types and word limits",
    "Original articles: the main text must not exceed 3000 words and the abstract 250 words.",
    "The abstract is structured with Background, Methods, Results and Conclusions headings.",
    "Reference style: references are numbered consecutively in the order of first citation "
    "and formatted in Vancouver style; list up to six authors before et al.",
    "Figures must be submitted as TIFF or EPS files with a minimum resolution of 300 dpi.",
    "Tables must be editable Word tables, each on a separate page with a short title.",
    "Required statements: ethics approval and consent to participate, consent for publication, "
    "availability of data and materials, competing interests, funding and authors' "
    "contributions must appear under Declarations.",
    "Submission items: cover letter, title page with all author affiliations and ORCID, "
    "blinded manuscript, figures, tables and the completed reporting checklist.",
    "Use of large language models must be declared in the Methods and the Acknowledgements.",
    "Abbreviations are defined at first use in the abstract and again in the main text.",
    "Highlights are not required for this journal.",
]


def _guide_html(extra: str = "") -> str:
    items = "".join(f"<li>{x}</li>" for x in GUIDE[3:])
    return ("<!DOCTYPE html><html><head><title>Submission guidelines</title><script>var x=1;"
            "</script><style>p{}</style></head><body><nav>Home | Journals</nav>"
            f"<h1>{GUIDE[0]}</h1><h2>{GUIDE[1]}</h2><p>{GUIDE[2]}</p><ul>{items}</ul>{extra}"
            "</body></html>")


def _pdf(path: Path, lines: list[str]) -> Path:
    content = "BT /F1 9 Tf 40 800 Td 12 TL " + " ".join(
        "(" + ln.replace("(", "").replace(")", "").replace("'", "") + ") '" for ln in lines) + " ET"
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] /Resources << /Font << /F1 4 0 R"
            " >> >> /Contents 5 0 R >>",
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            f"<< /Length {len(content)} >>\nstream\n{content}\nendstream"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += (f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
            + b"".join(f"{o:010d} 00000 n \n".encode() for o in offs)
            + f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(out)
    return path


def _docx(path: Path, lines: list[str]) -> Path:
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    paras = "".join(
        (f'<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>{ln}</w:t></w:r></w:p>'
         if i == 0 else f"<w:p><w:r><w:t>{ln}</w:t></w:r></w:p>") for i, ln in enumerate(lines))
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", f"<w:document {ns}><w:body>{paras}</w:body></w:document>")
    return path


def _extract(url: str, cites: str = "L0001 L0003 L0005 L0006 L0007 L0008 L0009") -> str:
    return (f"# Guidelines extract\n\nSource: {url} ({cites})\n\n## Word limits\n3000 words "
            "(L0003).\n\n## Reference style\nVancouver (L0005).\n\n## Figure\nTIFF 300 dpi (L0006)."
            "\n\n## Table\nWord tables (L0007).\n\n## Required statements\nDeclarations (L0008).\n\n"
            "## Submission items\nCover letter, title page (L0009).\n")


def _target(p: Path, journal: str, epoch: int | None = None, url: str = "https://journal-b.example.org/guide",
            **extra) -> dict:
    from datetime import date
    today = date.today().isoformat()
    tj = {"journal": journal, "issn": "1471-2482", "publisher": "BMC", "scie_indexed": True,
          "scie_source_url": "https://mjl.clarivate.com/x", "scie_verified_at": today,
          "jcr_quartile": "Q2", "jcr_source": "JCR 2025", "jcr_verified_at": today,
          "integrity_status": "clear", "integrity_checked_at": today,
          "integrity_sources": ["https://a.example.org", "https://b.example.org"],
          "guidelines_url": url, "guidelines_fetched_at": today,
          "abbreviation_placement": "self_contained", "abbreviation_rule_source": url,
          "chosen_by_user": True, **extra}
    if epoch is not None:
        tj["journal_epoch"] = epoch
    _w(p, "08_submission/target_journal.json", tj)
    return tj


def _frozen_paper(path: Path) -> Path:
    """A paper that finished S25 for Journal A, with every journal-layer artefact 1.16 kept."""
    from wfcore import reviewrounds, scifreeze
    from wfcore.state import State
    p = _paper(path, "S25_submission_audit")
    _w(p, "07_manuscript/full_manuscript.md", "# Introduction\n\nText [@a].\n\n# Results\n\n"
                                              "Mortality was 23.4% (Figure 1).\n")
    _w(p, "06_refs/refs.bib", "@article{a, title={x}}\n")
    _w(p, "06_refs/library.json", {"entries": []})
    _w(p, "03_analysis/results/primary.json", {"mortality_pct": 23.4})
    _w(p, "05_figures/legends.md", "## Figure 1\n\nMortality (A) and survival (B).\n")
    _w(p, "01_protocol/idea.json", {"study_design": "retrospective cohort", "data_source": "registry"})
    _w(p, "00_input/author_info.json", {"authors": [{"name": "A B"}]})
    scifreeze.write_freeze(p)
    _target(p, "Journal A", url="https://journal-a.example.org/guide")
    scifreeze.open_variant(p, "Journal A")
    # journal-A residue in every place 1.16 kept it
    _w(p, "05_figures/legends.md", "## Fig. 1\n\nMortality (a) and survival (b).\n")
    _w(p, "08_submission/cache/journal-a.html", _guide_html())
    _w(p, "08_submission/guidelines_extract.md", "Journal A rules")
    _w(p, "08_submission/cover_letter.md", "Dear Editor of Journal A")
    _w(p, "08_submission/journal_shortlist.md", "# Shortlist\n\n## Shortlist\n1. Journal A\n2. Journal B"
                                               "\n\n## Reject-fallback cascade\nJournal B, then Journal C\n")
    _w(p, "08_submission/display_reallocation.json",
       {"moves": [{"id": "Figure 4", "to": "supplementary", "new_id": "Figure S1", "why": "limit 3"}]})
    _w(p, "08_submission/declarations_assessment.json",
       {"answers": {"consent": {"value": "waived by the ethics committee"}},
        "ai_use": {"used": False, "tool": "", "purpose": "", "author_words": "没有使用",
                   "statement": "No generative AI was used.", "journal_rule": "Journal A AI rule"}})
    _w(p, ".wf/audits/A001_deadbeef0000.md", "## Verdict\n- F1 BLOCKING Journal A title page\n")
    _w(p, ".wf/review_bundle/A001/MANIFEST.md", "old audit bundle")
    _w(p, ".wf/review_bundle/P001/MANIFEST.md", "old package round")
    _w(p, ".wf/review_bundle/M001/MANIFEST.md", "manuscript round (journal-independent)")
    _w(p, ".wf/review_reports/P001.md", "old package report")
    _w(p, ".wf/scripts/s23_fix_journal_a.py", "print('journal A helper')\n")
    _w(p, "06_refs/journal-a.csl", "<style/>")
    data = reviewrounds.load(p)
    data["package"] = [{"id": "P001", "scope": "package", "closed_at": "2026-01-01T00:00:00Z",
                        "user_decision": None, "finding_list": [
                            {"id": "F1", "status": "author", "summary": "Journal A word cap"}]}]
    reviewrounds._save(p, data)
    st = State(p, ".wf").load()
    st.add_note("target=Journal A; journal deltas=Fig. prefix", "S20_journal")
    st.stage_info("S25_submission_audit").update(status="done", completed_at="2026-01-02T00:00:00Z")
    st.save()
    return p


# ------------------------------------------------------------------------------ J1-J3
def run_switch(tmp: Path, record, section) -> None:
    from hooks.paper_guard import Guard
    from wfcore import adapters, audit, declarations, guideingest, journalepoch, reviewrounds
    from wfcore.state import State
    section("1.17.0 J1-J3: journal switch after a rejection leaves nothing of the old journal")
    p = _frozen_paper(tmp / "life")
    r = _gate(p, "journal_variant_ready", "S25_submission_audit")
    record("J2 baseline: the Journal A variant is ready", r.ok, r.detail)
    _target(p, "Journal B", url="https://journal-b.example.org/guide")
    r = _gate(p, "journal_variant_ready", "S20_journal")
    record("J2 counterexample: editing target_journal.json in place to Journal B passed 1.16.0; "
           "now journal_variant_ready fails (variant is for Journal A)",
           not r.ok and r.blocking and "switched in place" in r.detail, r.detail)
    _pin(p, "1.16.0")
    r = _gate(p, "journal_variant_ready", "S20_journal")
    record("J2 a paper pinned to 1.16.0 gets the in-place switch as a warning until wf migrate",
           not r.ok and not r.blocking and r.severity == "warn", r.detail)
    _target(p, "Journal A", url="https://journal-a.example.org/guide")
    bad = _run(p, "tools/wf.py", "journal", "switch", "--to", "Journal B", "--confirm-old",
               "Journal X", "--why", "rejected after peer review: scope")
    record("J3 --confirm-old must name the current journal", bad.returncode == 2
           and "Journal A" in _out(bad), _out(bad)[-200:])
    sw = _run(p, "tools/wf.py", "journal", "switch", "--to", "Journal B", "--confirm-old",
              "Journal A", "--why", "rejected after peer review: scope", "--outcome", "rejected")
    out = _out(sw)
    record("J3 wf journal switch runs after S25 completion and a rejection and ends with the "
           "new-chat instruction and the archive location",
           sw.returncode == 0 and journalepoch.RESTART in out and "journal_archives/" in out
           and "S20-S25 采用当前引擎" in out, out[-600:])
    st = State(p, ".wf").load()
    hist = journalepoch.load(p)["epochs"]
    record("J3 .wf/journal_history.json records both epochs, the outcome and the dates",
           len(hist) == 2 and hist[0]["journal"] == "Journal A" and hist[0]["outcome"] == "rejected"
           and hist[0].get("ended_at") and hist[1]["journal"] == "Journal B"
           and hist[1]["epoch"] == 2 and hist[1]["started_at"], json.dumps(hist)[:300])
    record("J3 the switch loops to S20, keeps the science pin and adopts the current gate set "
           "for S20-S25 (recorded as an event)",
           st.current == "S20_journal" and st.engine_pin == "1.16.0"
           and st.gate_pin("S22_polish") in ("1.17.0", "1.18.0", "1.19.0", "1.20.0", "1.21.0", "1.22.0", "1.23.0", "1.24.0", "1.25.0")
           and st.gate_pin("S09_results") == "1.16.0"
           and any(e["kind"] == "journal_gate_set_adopted" for e in st.data["events"]),
           f"{st.current} {st.engine_pin} {st.data.get('journal_gate_pin')}")
    live = sorted(x.relative_to(p).as_posix() for x in (p / "08_submission").rglob("*")
                  if x.is_file() and "journal_archives" not in x.parts)
    record("J3 the submission tree holds only the new stub target_journal.json (epoch 2) and the "
           "carried declarations assessment",
           live == ["08_submission/declarations_assessment.json", "08_submission/target_journal.json"]
           and json.loads((p / live[1]).read_text(encoding="utf-8")) == {"journal": "Journal B",
                                                                       "journal_epoch": 2}, str(live))
    record("J3 .wf audits, package bundles/reports, previous-epoch helper scripts and CSL files "
           "outside 08_submission are archived; the manuscript round stays",
           not (p / ".wf/audits").exists() and not (p / ".wf/review_bundle/A001").exists()
           and not (p / ".wf/review_bundle/P001").exists() and (p / ".wf/review_bundle/M001").is_dir()
           and not (p / ".wf/review_reports/P001.md").exists()
           and not (p / ".wf/scripts/s23_fix_journal_a.py").exists()
           and not (p / "06_refs/journal-a.csl").exists())
    rr = reviewrounds.load(p)
    record("J3 package review rounds are grouped by epoch, not deleted; no old author question "
           "is pending", rr["package"] == [] and rr["package_epochs"][0]["epoch"] == 1
           and rr["package_epochs"][0]["rounds"][0]["id"] == "P001"
           and reviewrounds.latest(p, "package") is None)
    fact = declarations.ai_fact(p)
    record("J3 journal-independent facts are carried and not re-asked (AI-use answer, ethics "
           "answers, authors, study design); the old journal's AI rule wording is dropped",
           fact is not None and fact["used"] is False and "journal_rule" not in fact
           and declarations.load(p)["answers"]["consent"]["value"].startswith("waived")
           and "作者的 AI 使用答复" in out and "作者名单" in out and "研究设计" in out, out[-500:])
    record("J3 old S20+ handoff notes do not satisfy the new S20 note requirement",
           st.notes_for("S20_journal") == [] and any(h.get("journal_epoch_superseded") == 1
                                                      for h in st.data["handoff"]))
    hand = _run(p, "tools/wf.py", "handoff")
    stat = _run(p, "tools/wf.py", "status", "--brief")
    banner = "journal epoch 2: Journal B - do not reuse rules of earlier journals"
    record("J3 wf status and wf handoff show the journal epoch as the first line and never print "
           "the archive path", _out(hand).splitlines()[0] == banner
           and _out(stat).splitlines()[0] == banner and "journal_archives" not in _out(hand)
           and "journal_archives" not in _out(stat),
           " || ".join(x[max(0, x.find("journal_archives") - 300):x.find("journal_archives") + 100]
                       for x in (_out(hand), _out(stat))))
    r = _gate(p, "journal_layer_clean", "S20_journal")
    record("J2 journal_layer_clean: the new epoch needs a fresh guideline snapshot and the one "
           "restore question", not r.ok and "no guideline snapshot" in r.detail
           and "ask the user ONCE" in r.detail, r.detail)
    old_aud = p / ".wf/audits/A001_cafe00000000.md"
    _w(p, ".wf/audits/A001_cafe00000000.md", "- F1 BLOCKING Journal A word count\n")
    os.utime(old_aud, (1_600_000_000, 1_600_000_000))
    record("J1 an audit from an earlier journal epoch (legacy, by date) never makes the first "
           "audit of the new journal a re-check", audit.epoch_history(p) == [])
    _w(p, ".wf/audits/epochs.json", {"A001_cafe00000000.md": {"journal": "Journal A", "epoch": 1}})
    os.utime(old_aud, None)
    bundle, mode = audit.start(p, ["08_submission/target_journal.json"])
    man = (bundle / "MANIFEST.md").read_text(encoding="utf-8")
    record("J1 the first S25 audit of the new epoch is FULL (indexed old audit ignored)",
           mode == "full" and "FULL - first audit for this journal" in man
           and not (bundle / "previous_findings.md").exists(), man[:200])
    _w(p, ".wf/audits/A002_beef00000000.md", "- F1 MINOR Journal B legend\n")
    _w(p, ".wf/audits/epochs.json", {"A001_cafe00000000.md": {"journal": "Journal A", "epoch": 1},
                                     "A002_beef00000000.md": {"journal": "Journal B", "epoch": 2}})
    _bundle, mode2 = audit.start(p, [])
    record("J1 a re-audit within the same epoch is still a re-check", mode2 == "recheck")
    # fresh guideline snapshot for Journal B
    saved = _w(tmp, "saved/Journal B - Submission guidelines.html", _guide_html())
    ing = _run(p, "tools/wf.py", "guidelines", "ingest", "--from", saved, "--url",
               "https://journal-b.example.org/guide", "--title", "Submission guidelines")
    record("J4 wf guidelines ingest stores the saved page and a line-numbered source",
           ing.returncode == 0 and (p / guideingest.SOURCE).is_file()
           and guideingest.source_lines(p).get(1, "").startswith("# Instructions for Authors")
           and guideingest.source_epoch(p) == 2, _out(ing)[-300:])
    files = audit.guideline_files(p)
    record("J1 the audit bundle lists the original guide (cache file) and guidelines_source.txt",
           files[0] == "08_submission/guidelines_source.txt" and len(files) == 2
           and files[1].startswith("08_submission/cache/") and files[1].endswith(".html"), str(files))
    _target(p, "Journal B", 2)
    r = _gate(p, "journal_layer_clean", "S20_journal")
    record("J3 the restore question is still owed", not r.ok and "ask the user ONCE" in r.detail
           and "Figure 4" not in r.detail, r.detail)
    res = _run(p, "tools/wf.py", "journal", "restore", "--answer", "keep", "--why",
               "用户：保持补充材料的安排")
    again = _run(p, "tools/wf.py", "journal", "restore", "--answer", "restore", "--why", "再问一次")
    rec = journalepoch.current(p)["restore"]
    record("J3 display moves and presentation edits are listed, the user is asked once and the "
           "answer is recorded", res.returncode == 0 and again.returncode == 2
           and rec["answer"] == "keep" and {i["kind"] for i in rec["items"]}
           == {"display_move", "presentation_edit"} and "Figure 4" in out, json.dumps(rec)[:300])
    r = _gate(p, "journal_layer_clean", "S20_journal")
    record("J2 journal_layer_clean passes once the epoch has its own snapshot, evidence and answer",
           r.ok, r.detail)
    old = _w(p, "08_submission/cover_letter.md", "Dear Editor of Journal A")
    os.utime(old, (1_600_000_000, 1_600_000_000))
    r = _gate(p, "journal_layer_clean", "S20_journal")
    record("J2 a file older than the epoch start under 08_submission blocks", not r.ok
           and "cover_letter.md" in r.detail, r.detail)
    old.unlink()
    _target(p, "Journal B", 2, scie_verified_at="2020-01-01")
    r = _gate(p, "journal_layer_clean", "S20_journal")
    record("J2 SCIE evidence from before the epoch start must be verified again", not r.ok
           and "scie_verified_at" in r.detail, r.detail)
    _target(p, "Journal B", 2)
    sl = _run(p, "tools/wf.py", "journal", "shortlist")
    record("J3 the archived fallback ladder is offered (read by the engine) and must be re-verified",
           sl.returncode == 0 and "Journal C" in _out(sl) and "重新核实" in _out(sl)
           and "journal_archives" not in _out(sl), _out(sl)[-300:])
    from wfcore import scifreeze
    scifreeze.open_variant(p, "Journal B")
    r = _gate(p, "journal_variant_ready", "S20_journal")
    record("J2 the new variant carries the epoch and passes", r.ok
           and scifreeze.variant_meta(p).get("journal_epoch") == 2, r.detail)
    _target(p, "Journal B", 1)
    r = _gate(p, "journal_variant_ready", "S20_journal")
    record("J2 an epoch mismatch between target_journal.json and the epoch blocks",
           not r.ok and r.blocking and "journal_epoch" in r.detail, r.detail)
    _target(p, "Journal B", 2)
    g = Guard(p)
    arch = str(next((p / "08_submission/journal_archives").iterdir()))
    lst = g.decide({"tool_name": "list_directory", "tool_input": {"path": arch}})
    grep = g.decide({"tool_name": "grep_search", "tool_input": {"query": "word limit",
                                                                "includePattern": "**/*.md"}})
    ok_grep = g.decide({"tool_name": "grep_search", "tool_input": {
        "query": "x", "includePattern": "**/*.md",
        "excludePattern": "08_submission/journal_archives/**"}})
    record("J3 discovery tools are blocked on journal archives (listing and whole-workspace "
           "search); excluding the archive is allowed; read_file/execute_pwsh stay unhooked",
           bool(lst) and "previous target journal" in lst and bool(grep) and ok_grep is None
           and not any(t in adapters.GUARD_MATCHER.split("|") for t in
                       ("read_file", "readFile", "execute_pwsh", "executePwsh")), f"{lst} | {grep}")
    # rework.py kind journal-switch calls the same command
    plan = _w(tmp, "plan.json", {"feedback_verbatim": "rejected again", "items": [
        {"kind": "journal-switch", "request": "Journal B desk-rejected the paper; go to C",
         "to_journal": "Journal C", "confirm_old": "Journal B", "outcome": "rejected",
         "affected_sources": ["08_submission/target_journal.json"],
         "acceptance_criteria": ["new journal"]}]})
    rw = _run(p, "tools/rework.py", "batch", "--plan", plan)
    record("J3 rework.py kind journal-switch runs wf journal switch (epoch 3)",
           rw.returncode == 0 and journalepoch.number(p) == 3
           and journalepoch.current(p)["journal"] == "Journal C" and journalepoch.RESTART in _out(rw),
           _out(rw)[-300:])
    q = _paper(tmp / "early", "S10_tables")
    early = _run(q, "tools/wf.py", "journal", "switch", "--to", "B", "--confirm-old", "A",
                 "--why", "no journal chosen yet at all")
    record("J3 the switch is refused before S20", early.returncode == 2
           and "S20" in _out(early), _out(early)[-200:])


# ------------------------------------------------------------------------------ J4
def run_ingest(tmp: Path, record, section) -> None:
    from wfcore import guideingest
    section("1.17.0 J4: guidelines the user saved become a line-numbered source")
    p = _paper(tmp / "ing", "S20_journal")
    url = "https://journal-b.example.org/guide"
    cases = {
        "html": _w(tmp, "in/guide.htm", _guide_html()),
        "mhtml": _w(tmp, "in/guide.mhtml", "MIME-Version: 1.0\nContent-Type: multipart/related; "
                    "boundary=\"b\"\n\n--b\nContent-Type: text/html; charset=utf-8\n\n"
                    + _guide_html() + "\n--b--\n"),
        "pdf": _pdf(tmp / "in/guide.pdf", GUIDE + GUIDE[2:6]),
        "docx": _docx(tmp / "in/guide.docx", GUIDE),
        "text": _w(tmp, "in/guide.txt", "\n".join(GUIDE)),
    }
    got = {}
    for kind, f in cases.items():
        try:
            e = guideingest.ingest(p, f, url + "/" + kind, kind)
            got[kind] = (e["format"], e["lines"], (p / guideingest.CACHE / e["file"]).is_file())
        except Exception as exc:  # noqa: BLE001
            got[kind] = str(exc)
    record("J4 HTML, single-file web archive, PDF (pypdf), DOCX and TXT are converted and the "
           "originals kept with sha256 and date",
           all(isinstance(v, tuple) and v[0] == k and v[1] >= 8 and v[2] for k, v in got.items()),
           str(got))
    lines = guideingest.source_lines(p)
    text = (p / guideingest.SOURCE).read_text(encoding="utf-8")
    record("J4 guidelines_source.txt numbers every line L0001... across sources, keeps headings "
           "and list items, drops scripts and navigation",
           lines.get(1) == "# Instructions for Authors" and "- Figures must be submitted" in text
           and "var x" not in text and "Home | Journals" not in text
           and text.count("== source S") == 5 and max(lines) == len(lines), text[:400])
    idx = guideingest.load_index(p)
    record("J4 cache/index.json records url, sha256, date, kind and epoch per original",
           len(idx) == 5 and all(e["sha256"] and e["ingested_at"] and e["epoch"] == 1
                                 and e["url"].startswith(url) for e in idx), json.dumps(idx[0]))
    cap = _w(tmp, "in/blocked.html", "<html><body><h1>Just a moment...</h1><p>Please verify you "
                                     "are human (captcha)</p></body></html>")
    for label, args in (("a captcha page", (cap, url)), ("a missing URL", (cases["html"], ""))):
        try:
            guideingest.ingest(p, *args)
            refused = False
        except guideingest.IngestError:
            refused = True
        record(f"J4 {label} is refused", refused)
    mjl = _pdf(tmp / "in/mjl.pdf", ["Master Journal List", "Journal B", "Science Citation Index "
                                    "Expanded"] * 3)
    e = guideingest.ingest(p, mjl, "https://mjl.clarivate.com/search-results?issn=1471-2482",
                           kind="indexing")
    record("J4 --kind indexing stores SCIE/JCR evidence without adding it to the guide",
           e["kind"] == "indexing" and "Master Journal List" not in
           (p / guideingest.SOURCE).read_text(encoding="utf-8"))
    _target(p, "Journal B", url=url + "/html")
    _w(p, "08_submission/cache/legacy.html", _guide_html())
    _w(p, "08_submission/guidelines_extract.md", _extract(url + "/html", "").replace("(L0", "(p. "))
    r = _gate(p, "guidelines_sourced", "S20_journal")
    record("J4 since 1.17.0 an extract that cites no guideline lines fails",
           not r.ok and "cites 0 guideline line" in r.detail, r.detail)
    _w(p, "08_submission/guidelines_extract.md", _extract(url + "/html") + "\nAlso L9999.\n")
    r = _gate(p, "guidelines_sourced", "S20_journal")
    record("J4 a cited line that does not exist fails", not r.ok and "L9999" in r.detail, r.detail)
    _w(p, "08_submission/guidelines_extract.md", _extract(url + "/html"))
    r = _gate(p, "guidelines_sourced", "S20_journal")
    record("J4 an extract citing existing source lines passes", r.ok, r.detail)
    _pin(p, "1.16.0")
    _w(p, "08_submission/guidelines_extract.md", _extract(url + "/html", "").replace("(L0", "(p. "))
    r = _gate(p, "guidelines_sourced", "S20_journal")
    record("J4 a paper pinned to 1.16.0 keeps the 1.16 extract rule", r.ok, r.detail)
    q = _paper(tmp / "alias", "S20_journal")
    al = _run(q, "tools/wf.py", "guidelines", "refresh", "--from", cases["html"], "--url", url)
    ex = _w(q, "new_extract.md", _extract(url) + "x" * 200)
    old = _run(q, "tools/wf.py", "guidelines", "refresh", "--from", ex, "--source", url)
    record("J4 wf guidelines refresh --from <saved page> --url is the same import; refresh --from "
           "<extract.md> keeps its 1.15 meaning",
           al.returncode == 0 and (q / guideingest.SOURCE).is_file() and old.returncode == 0
           and "guideline snapshot refreshed" in _out(old), _out(al)[-200:] + _out(old)[-200:])




# ------------------------------------------------------------------------------ J5
def _fixtures(d: Path, table: dict) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    out = {}
    for i, (url, (status, body, ctype)) in enumerate(table.items()):
        name = f"r{i}.bin"
        (d / name).write_bytes(body if isinstance(body, bytes) else
                               (body if isinstance(body, str) else json.dumps(body)).encode("utf-8"))
        out[url] = {"status": status, "file": name, "content_type": ctype}
    (d / "fixtures.json").write_text(json.dumps(out), encoding="utf-8")
    return d


def _nlm_urls(issn: str, uid: str | None) -> dict:
    import urllib.parse
    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    q1 = urllib.parse.urlencode({"db": "nlmcatalog", "term": f"{issn}[issn]", "retmode": "json"})
    out = {f"{base}/esearch.fcgi?{q1}": (200, {"esearchresult": {"idlist": [uid] if uid else []}},
                                          "application/json")}
    if uid:
        q2 = urllib.parse.urlencode({"db": "nlmcatalog", "id": uid, "retmode": "json"})
        out[f"{base}/esummary.fcgi?{q2}"] = (200, {"result": {uid: {
            "titlemainlist": [{"title": "BMC surgery."}], "currentindexingstatus": "Y",
            "elocationlist": [{"elocationvalue": "https://bmcsurg.biomedcentral.com/"}]}}},
            "application/json")
    return out


def run_lookup(tmp: Path, record, section) -> None:
    from wfcore import guideingest, journallookup
    section("1.17.0 J5: wf journal lookup finds the official guide lawfully (recorded responses)")
    p = _paper(tmp / "ok", "S20_journal")
    guide = "https://bmcsurg.biomedcentral.com/submission-guidelines"
    fx = _fixtures(tmp / "fx_ok", {
        "https://doaj.org/api/search/journals/issn%3A1471-2482": (200, {"results": [{"bibjson": {
            "title": "BMC Surgery", "publisher": {"name": "BMC"},
            "ref": {"author_instructions": guide, "journal": "https://bmcsurg.biomedcentral.com/"},
            "apc": {"has_apc": True}}}]}, "application/json"),
        "https://api.openalex.org/sources/issn:1471-2482": (200, {
            "id": "https://openalex.org/S1", "display_name": "BMC Surgery",
            "homepage_url": "https://bmcsurg.biomedcentral.com/",
            "host_organization_name": "BioMed Central", "apc_usd": 2990, "is_in_doaj": True},
            "application/json"),
        **_nlm_urls("1471-2482", "100968567"),
        guide: (200, _guide_html(), "text/html; charset=utf-8")})
    r = _run(p, "tools/wf.py", "journal", "lookup", "--issn", "14712482",
             env=_env(p, MEDPAPER_HTTP_FIXTURES=fx, LOCALAPPDATA=tmp / "lad"))
    out = _out(r)
    idx = guideingest.load_index(p)
    cache = p / journallookup.LOOKUP_DIR / "1471-2482.json"
    record("J5 DOAJ author_instructions -> one polite GET -> the official page is stored and "
           "ingested as guidelines_source.txt; NLM MEDLINE status shown as supplementary",
           r.returncode == 0 and "L3 已取得官方页面并导入" in out and (p / guideingest.SOURCE).is_file()
           and idx and idx[-1]["origin"] == "fetched" and idx[-1]["url"] == guide
           and "目前被 MEDLINE 收录" in out and "BMC Surgery" in out, out[-700:])
    rec = json.loads(cache.read_text(encoding="utf-8"))
    record("J5 network answers are cached with their date", rec["looked_up_at"][:4].isdigit()
           and rec["sources"]["openalex"]["homepage"] and rec["candidates"][0]["url"] == guide)
    r2 = _run(p, "tools/wf.py", "journal", "lookup", "--issn", "1471-2482", "--no-fetch",
              env=_env(p, MEDPAPER_OFFLINE=1, LOCALAPPDATA=tmp / "lad"))
    record("J5 offline, the dated local cache (L0) answers", r2.returncode == 0
           and "L0 使用本地缓存" in _out(r2) and guide in _out(r2), _out(r2)[-300:])
    q = _paper(tmp / "blocked", "S20_journal")
    home = "https://www.sciencedirect.com/journal/journal-of-tests"
    tpl = home + "/publish/guide-for-authors"
    blocked_table = {
        "https://doaj.org/api/search/journals/issn%3A1234-5679": (200, {"results": []},
                                                                 "application/json"),
        "https://api.openalex.org/sources/issn:1234-5679": (200, {
            "id": "https://openalex.org/S2", "display_name": "Journal of Tests",
            "homepage_url": home, "host_organization_name": "Elsevier BV", "is_in_doaj": False},
            "application/json"),
        **_nlm_urls("1234-5679", None),
        tpl: (403, b"", "text/html")}
    fx2 = _fixtures(tmp / "fx_403", blocked_table)
    r3 = _run(q, "tools/wf.py", "journal", "lookup", "--issn", "1234-5679",
              env=_env(q, MEDPAPER_HTTP_FIXTURES=fx2, LOCALAPPDATA=tmp / "lad"))
    o3 = _out(r3)
    record("J5 publisher URL template (Elsevier) -> 403 -> STOP with Chinese instructions naming "
           "the exact URL and the ingest command; no retry, nothing ingested",
           r3.returncode == 0 and "403" in o3 and "L4" in o3 and tpl in o3
           and f"wf guidelines ingest --from <保存的文件> --url {tpl}" in o3
           and "第三方" in o3 and "Master Journal List" in o3
           and not (q / guideingest.SOURCE).exists(), o3[-900:])
    fx3 = _fixtures(tmp / "fx_cap", {**blocked_table, tpl: (
        200, "<html><body><h1>Just a moment...</h1>Verify you are human (captcha)"
        "</body></html>", "text/html")})
    r4 = _run(q, "tools/wf.py", "journal", "lookup", "--issn", "1234-5679", "--refresh",
              env=_env(q, MEDPAPER_HTTP_FIXTURES=fx3, LOCALAPPDATA=tmp / "lad"))
    record("J5 a captcha page is recognised as blocked, not ingested", "验证码" in _out(r4)
           and not (q / guideingest.SOURCE).exists(), _out(r4)[-300:])
    lad = tmp / "lad2"
    _w(lad, "medpaper/journal_cache/2222-3333.json",
       {"issn": "2222-3333", "title": "Cached Journal", "looked_up_at": journallookup._now(),
        "candidates": [{"url": "https://cached.example.org/authors", "basis": "user cache"}]})
    r5 = _run(q, "tools/wf.py", "journal", "lookup", "--issn", "2222-3333", "--no-fetch",
              env=_env(q, MEDPAPER_OFFLINE=1, LOCALAPPDATA=lad))
    record("J5 the user-level read-only cache under LOCALAPPDATA is read (dated entry)",
           "user cache" in _out(r5) and "https://cached.example.org/authors" in _out(r5), _out(r5)[-300:])
    cands = journallookup.template_candidates(ROOT, {
        "publisher": "MDPI", "homepages": ["https://www.mdpi.com/journal/jcm"], "issn": "2077-0383"})
    tpl_n = len(journallookup.templates(ROOT))
    record("J5 the vendored publisher table covers 14+ publishers, each marked verify at runtime",
           tpl_n >= 14 and all(t.get("verify") == "runtime" for t in journallookup.templates(ROOT))
           and cands and cands[0]["url"] == "https://www.mdpi.com/journal/jcm/instructions", str(cands))
    card = (ROOT / "pipeline/stages/S20_journal.md").read_text(encoding="utf-8")
    record("J5 the S20 card uses lookup -> ingest and stays <= 4000 characters",
           "wf journal lookup" in card and "guidelines ingest" in card and len(card) <= 4000,
           str(len(card)))


# ------------------------------------------------------------------------------ J6
DEP = """<?xml version="1.0" encoding="utf-8"?>
<style xmlns="http://purl.org/net/xbiblio/csl" version="1.0" default-locale="en-US">
  <info><title>Journal of Tests</title><id>http://www.zotero.org/styles/journal-of-tests</id>
    <link href="http://www.zotero.org/styles/journal-of-tests" rel="self"/>
    <link href="http://www.zotero.org/styles/vancouver" rel="independent-parent"/>
    <issn>1234-5679</issn><eissn>9876-543X</eissn></info></style>
"""
PARENT = """<?xml version="1.0" encoding="utf-8"?>
<style xmlns="http://purl.org/net/xbiblio/csl" class="in-text" version="1.0">
  <info><title>Vancouver</title><id>http://www.zotero.org/styles/vancouver</id></info>
  <citation><layout><text variable="citation-number"/></layout></citation>
  <bibliography><layout><text variable="title"/></layout></bibliography></style>
"""
OTHER = PARENT.replace("vancouver", "apa").replace("Vancouver", "APA")


def run_csl(tmp: Path, record, section) -> None:
    sys.path.insert(0, str(ROOT / "tools/refs"))
    import csl_index
    from wfcore import cslindex
    section("1.17.0 J6: the reference style comes from the journal's ISSN (CSL styles index)")
    zpath = tmp / "styles.zip"
    zpath.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zpath, "w") as z:
        z.writestr("styles-1.0.2/dependent/journal-of-tests.csl", DEP)
        z.writestr("styles-1.0.2/vancouver.csl", PARENT)
        z.writestr("styles-1.0.2/apa.csl", OTHER)
    idx = csl_index.build_index(zpath.read_bytes(), "synthetic")
    record("J6 the generator maps print and electronic ISSN of a dependent style to its parent",
           idx["issn"].get("1234-5679") == ["journal-of-tests", "vancouver"]
           and idx["issn"].get("9876-543X") == ["journal-of-tests", "vancouver"], str(idx["issn"]))
    ipath = _w(tmp, "index.json", idx)
    os.environ["MEDPAPER_CSL_INDEX"] = str(ipath)
    cslindex._CACHE.clear()
    try:
        p = _paper(tmp / "csl", "S23_package")
        _target(p, "Journal of Tests", issn="1234-5679")
        _w(p, "08_submission/vancouver.csl", PARENT)
        r = _gate(p, "csl_check", "S23_package", render=False)
        record("J6 csl_check passes the parent style the index gives the journal ISSN", r.ok
               and "1234-5679" in r.detail, r.detail)
        (p / "08_submission/vancouver.csl").unlink()
        _w(p, "08_submission/apa.csl", OTHER)
        r = _gate(p, "csl_check", "S23_package", render=False)
        record("J6 counterexample: another journal's style passed 1.16.0 (csl_check was a manual "
               "tool); now it fails at S23", not r.ok and "vancouver" in r.detail, r.detail)
        _target(p, "Journal of Tests", issn="1234-5679",
                csl={"reason": "the guide's own example reference matches APA 7 exactly"})
        r = _gate(p, "csl_check", "S23_package", render=False)
        record("J6 a style with a recorded reason passes and says so", r.ok and "reason" in r.detail,
               r.detail)
        _target(p, "Journal of Tests", issn="1234-5679")
        _w(p, "08_submission/apa.csl", DEP)
        r = _gate(p, "csl_check", "S23_package", render=False)
        record("J6 a CSL naming the journal ISSN itself passes", r.ok, r.detail)
        _pin(p, "1.16.0")
        _w(p, "08_submission/apa.csl", OTHER)
        r = _gate(p, "csl_check", "S23_package", render=False)
        record("J6 a paper pinned to 1.16.0 gets csl_check only after wf migrate", r.ok, r.detail)
        q = _paper(tmp / "fetch", "S20_journal")
        _target(q, "Journal of Tests", issn="1234-5679")
        raw = "https://raw.githubusercontent.com/citation-style-language/styles/v1.0.2/"
        fx = _fixtures(tmp / "fx_csl", {raw + "dependent/journal-of-tests.csl": (200, DEP, "text/xml"),
                                        raw + "vancouver.csl": (200, PARENT, "text/xml")})
        f = _run(q, "tools/refs/csl_index.py", "fetch", "--issn", "1234-5679",
                 env=_env(q, MEDPAPER_HTTP_FIXTURES=fx, MEDPAPER_CSL_INDEX=ipath))
        tj = json.loads((q / "08_submission/target_journal.json").read_text(encoding="utf-8"))
        record("J6 fetch downloads the parent from the v1.0.2 branch (cached), installs it and "
               "records csl.style_id / csl.issn in target_journal.json",
               f.returncode == 0 and (q / "08_submission/vancouver.csl").is_file()
               and (q / "08_submission/cache/csl/journal-of-tests.csl").is_file()
               and tj["csl"]["style_id"] == "journal-of-tests" and tj["csl"]["issn"] == "1234-5679"
               and "citationstyles.org" in _out(f), _out(f)[-300:])
    finally:
        os.environ.pop("MEDPAPER_CSL_INDEX", None)
        cslindex._CACHE.clear()
    real = cslindex.load(ROOT)
    att = (ROOT / "reference/CSL_STYLES_ATTRIBUTION.md").read_text(encoding="utf-8")
    record("J6 the vendored index and its CC BY-SA 3.0 attribution ship with the engine; S23 gates "
           "csl_check since 1.17.0",
           len(real.get("issn", {})) >= 20 and "CC BY-SA 3.0" in att and "citationstyles.org" in att
           and any(g.get("check") == "csl_check" and g.get("since") == "1.17.0"
                   for g in _stage_gates("S23_package")), str(len(real.get("issn", {}))))


def _stage_gates(sid: str) -> list[dict]:
    from wfcore import registry
    return registry.load().stage(sid).gate


# ------------------------------------------------------------------------------ J7
FIG_SCRIPT = """import matplotlib
matplotlib.use("Agg")
from wfcore import paths
from figures.style import apply_style, figure, save
P = paths.project_dir(check_engine=False)
apply_style()
fig, panels = figure(width="single", height_mm=60, panels=(1, 1), letters=False)
_, ax = panels[0]
ax.plot([0, 1, 2, 3], [1.0, 0.9, 0.8, 0.7])
ax.set_xlabel("Year of follow-up")
ax.set_ylabel("Survival")
save(fig, P / "05_figures/out/Figure1", width="single", tiff=False)
"""
R_FIG = """source(file.path(Sys.getenv("MEDPAPER_ROOT"), "tools/figures/R/medfig.R"))
d <- data.frame(x = c(1, 2, 3), y = c(2, 1, 3))
p <- ggplot2::ggplot(d, ggplot2::aes(x, y)) + ggplot2::geom_point() +
  ggplot2::labs(x = "Dose", y = "Response") + theme_medpaper()
save_medpaper(p, "05_figures/out/Figure3", width = "single")
"""


def run_render(tmp: Path, record, section) -> None:
    from wfcore import journalepoch, renderparams
    section("1.17.0 J7: figures and tables carry the presentation parameters they were rendered with")
    p = _paper(tmp / "fig", "S20_journal")
    _w(p, "01_protocol/journal_profile.json", {
        "status": "provisional", "journal_or_type": "Journal A type", "font_min_pt": 7,
        "figure_width_mm": {"single": 84, "1.5": 129, "double": 174}, "panel_label_case": "lower",
        "line_art_dpi": 300, "number_format": {"thousands": ","}, "spelling": "british",
        "heading_names": {}, "source": "journal type default"})
    _w(p, "05_figures/code/fig1.py", FIG_SCRIPT)
    r = _run(p, "tools/wf.py", "run-script", "05_figures/code/fig1.py", cwd=p)
    side = p / "05_figures/qc/Figure1.artist.json"
    art = json.loads(side.read_text(encoding="utf-8")) if side.is_file() else {}
    record("J7 a Python figure sidecar records the presentation parameters it used",
           r.returncode == 0 and (art.get("presentation") or {}).get("line_art_dpi") == 300
           and art["presentation"]["panel_label_case"] == "lower", _out(r)[-400:])
    import shutil
    if shutil.which("Rscript"):
        _w(p, "05_figures/code/fig3.R", R_FIG)
        rr = _run(p, "tools/wf.py", "run-script", "05_figures/code/fig3.R", cwd=p)
        rside = p / "05_figures/qc/Figure3.artist.json"
        rart = json.loads(rside.read_text(encoding="utf-8")) if rside.is_file() else {}
        record("J7 an R figure sidecar (save_medpaper) records the presentation parameters it used",
               (rart.get("presentation") or {}).get("panel_label_case") == "lower"
               and (rart.get("presentation") or {}).get("line_art_dpi") == 300,
               _out(rr)[-400:])
        (p / "05_figures/qc/Figure3.artist.json").unlink(missing_ok=True)
    else:
        record("J7 R figure sidecar: Rscript available", False, "Rscript missing")
    from figures import qc
    record("J7 the sidecar schema accepts the presentation block", not any(
        "unknown key" in x for x in qc._schema_problems(art, "Figure1")) if art else False)
    sys.path.insert(0, str(ROOT / "tools"))
    from tables import threeline
    old = {k: os.environ.get(k) for k in ("MEDPAPER_PROJECT", "MEDPAPER_SCRIPT")}
    os.environ.update(MEDPAPER_PROJECT=str(p), MEDPAPER_SCRIPT="04_tables/code/t1.py")
    try:
        with redirect_stdout(io.StringIO()):
            threeline.write_table(p / "04_tables/main/Table1.xlsx", "Table 1", "Table 1. Cohort",
                                  ["Characteristic", "Value"], [["Age", "60"]], ["Values are years."])
    finally:
        for k, v in old.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
    tabs = json.loads((p / renderparams.TABLES).read_text(encoding="utf-8"))["tables"]
    record("J7 the table builder records number format and spelling per workbook",
           tabs.get("04_tables/main/Table1.xlsx", {}).get("params", {}).get("spelling") == "british"
           and tabs["04_tables/main/Table1.xlsx"]["script"] == "04_tables/code/t1.py", str(tabs))
    pres = {"font_min_pt": 7, "figure_width_mm": {"single": 84, "1.5": 129, "double": 174},
            "panel_label_case": "lower", "line_art_dpi": 300, "number_format": {"thousands": ","},
            "spelling": "british", "heading_names": {}, "in_figure_title": None}
    _target(p, "Journal A", presentation=pres)
    r = _gate(p, "presentation_params_confirmed", "S20_journal")
    record("J7 parameters equal to the render pass", r.ok, r.detail)
    _target(p, "Journal A", presentation={**pres, "line_art_dpi": 600, "panel_label_case": "upper"})
    r = _gate(p, "presentation_params_confirmed", "S20_journal")
    record("J7 counterexample: figures rendered at 300 dpi / lower-case panels passed 1.16.0 with a "
           "600 dpi / upper-case journal ('journal replaces provisional'); now one instruction to "
           "re-render with wf rebuild", not r.ok and "Figure1" in r.detail and "wf rebuild" in
           " ".join(r.hints) and "line_art_dpi 300 -> 600" in r.detail, r.detail)
    dry = _run(p, "tools/wf.py", "rebuild", "--dry-run", cwd=p)
    record("J7 wf rebuild --dry-run lists the presentation re-render (no science rewind)",
           "re-render 05_figures/code/fig1.py" in _out(dry), _out(dry)[-300:])
    rb = _run(p, "tools/wf.py", "rebuild", cwd=p)
    art2 = json.loads(side.read_text(encoding="utf-8"))
    r = _gate(p, "presentation_params_confirmed", "S20_journal")
    record("J7 wf rebuild re-runs the figure script with the journal's parameters; the gate then "
           "passes for the figure", art2["presentation"]["line_art_dpi"] == 600
           and "Figure1" not in r.detail and "04_tables/main/Table1.xlsx" not in r.detail,
           _out(rb)[-300:] + " | " + r.detail)
    _pin(p, "1.16.0")
    _target(p, "Journal A", presentation={**pres, "line_art_dpi": 1200})
    r = _gate(p, "presentation_params_confirmed", "S20_journal")
    record("J7 a paper pinned to 1.16.0 keeps the 1.16 behaviour until wf migrate", r.ok, r.detail)
    q = _paper(tmp / "epoch2", "S20_journal")
    _w(q, "01_protocol/journal_profile.json", {"journal_or_type": "x", "font_min_pt": 7,
                                               "spelling": "british"})
    _w(q, journalepoch.HISTORY, {"schema": 1, "epochs": [
        {"epoch": 1, "journal": "Journal A", "started_at": "2026-01-01T00:00:00Z"},
        {"epoch": 2, "journal": "Journal B", "started_at": journalepoch._now()}]})
    part = {k: v for k, v in pres.items() if k != "spelling"}
    _target(q, "Journal B", 2, presentation=part)
    r = _gate(q, "presentation_params_confirmed", "S20_journal")
    from wfcore import presentparams
    record("J7 after a switch the presentation block must be complete: nothing is inherited from "
           "the provisional journal_profile.json", not r.ok and "spelling" in r.detail
           and presentparams.params(q)["spelling"] is None, r.detail)
    _target(q, "Journal B", 2, presentation=pres)
    _w(q, "05_figures/qc/Figure2.artist.json", {"figure": "Figure2", "script": "05_figures/code/f2.R"})
    r = _gate(q, "presentation_params_confirmed", "S20_journal")
    record("J7 after a switch a figure rendered without recorded parameters must be re-rendered",
           not r.ok and "Figure2" in r.detail and "rendered before 1.17.0" in r.detail, r.detail)


def run_release(tmp: Path, record, section) -> None:
    from wfcore import registry
    from wfcore.state import State
    section("1.17.0 release: version, one migration event, pinned paper policy")
    q = tmp / "old"
    q.mkdir(parents=True, exist_ok=True)
    st = State(q, ".wf").create("medpaper", "1.16.0", "S23_package")
    before = sorted(x.name for x in q.rglob("*") if x.is_file() and ".wf" not in x.parts)
    st.migrate_pipeline("1.17.0", ["S23_package"])
    st.migrate_pipeline("1.17.0", ["S23_package"])
    notes = [e for e in st.data["events"] if e["kind"] == "requirements_changed"
             and str(e.get("detail", "")).startswith("1.17.0")]
    after = sorted(x.name for x in q.rglob("*") if x.is_file() and ".wf" not in x.parts)
    pipe = registry.load()
    sizes = {s.id: len((ROOT / "pipeline" / s.card).read_text(encoding="utf-8")) for s in pipe.stages}
    record("R pipeline 1.17.0; a 1.16.0 paper gets exactly one 1.17.0 event, stays pinned (gate pin "
           "unchanged without a journal switch) and no paper file changes; cards <= limit",
           pipe.meta.get("version") in ("1.17.0", "1.18.0", "1.19.0", "1.20.0", "1.21.0", "1.22.0", "1.23.0", "1.24.0", "1.25.0") and len(notes) == 1 and st.engine_pin == "1.16.0"
           and st.gate_pin("S23_package") == "1.16.0" and before == after
           and max(sizes.values()) <= registry.CARD_MAX_CHARS, f"{len(notes)} {max(sizes.values())}")


GROUPS = [("switch", run_switch), ("ingest", run_ingest), ("lookup", run_lookup), ("csl", run_csl),
          ("render", run_render), ("release", run_release)]


if __name__ == "__main__":  # quick subset run: python tools/selftest_v1170.py [groups]
    import tempfile
    os.environ.setdefault("MEDPAPER_STDOUT_ENCODING", "utf-8")
    fails = []

    def _record(name, ok, detail=""):
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail and not ok else ""))
        if not ok:
            fails.append(name)
        return ok
    with tempfile.TemporaryDirectory(prefix="mp_v1170_") as d:
        run(Path(d), _record, lambda t: print(f"\n{t}\n" + "-" * len(t)), " ".join(sys.argv[1:]))
    print(f"\n{len(fails)} failure(s)")
    sys.exit(1 if fails else 0)
