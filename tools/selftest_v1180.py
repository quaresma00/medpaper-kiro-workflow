"""1.18.0 regression tests: the author guide as a checked requirement list (K1/K2), typed journal
fields wired into builders and checks (K3), the compliance matrix and the user summary (K4/K5),
the S25 audit judging every row against the original text (K6), the DOCX preflight (K7) and the
journal-switch integration (K8). Counterexample first: each gap below passed the 1.17.0 gates.
Synthetic fixtures only - no real paper, dataset or network is used.

Called from tools/selftest.py.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from selftest_v1140 import _gate, _out, _paper, _run, _w  # noqa: E402


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
    "Instructions for Authors - Original Articles",
    "The main text must not exceed 3000 words, excluding the abstract, references and legends.",
    "The abstract is limited to 250 words and must be structured with the headings Background, "
    "Methods, Results and Conclusions.",
    "Provide 3 to 6 keywords listed after the abstract.",
    "The title page should include the full title, a running title of no more than 50 characters, "
    "all author names and affiliations, and the corresponding author's e-mail address.",
    "Highlights are not required.",
    "Use section headings Introduction, Methods, Results and Discussion in this order.",
    "References must follow the Vancouver style and should not exceed 40 references.",
    "Cite references in the text with numbers in square brackets.",
    "Figures must be supplied as TIFF files at a minimum of 300 dpi and each file should be no "
    "larger than 10 MB.",
    "Tables must be editable and cited in numerical order.",
    "Supplementary material should be submitted as a single PDF file.",
    "Declarations must appear in this order: Ethics approval, Consent, Data availability, "
    "Competing interests, Funding, Authors' contributions.",
    "Ethics approval and informed consent must be reported in the Methods.",
    "A data availability statement is mandatory.",
    "Any use of generative AI tools must be disclosed in the Methods.",
    "Each author must complete the ICMJE disclosure form in the submission system.",
    "Funding sources must be listed in the Funding section.",
    "Authors' contributions must follow the CRediT taxonomy, and ORCID identifiers are required "
    "for all authors.",
    "The cover letter must state that the manuscript is not under consideration elsewhere.",
    "Required uploads: cover letter, title page, manuscript, figures and tables.",
    "Line numbers and page numbers are required.",
    "Manuscripts should be written in American English.",
    "Peer review is single-blind.",
    "A completed STROBE checklist must accompany observational studies.",
    "Case reports: the text must not exceed 1500 words and requires no abstract.",
    "Review articles should not exceed 5000 words.",
]
ORCIDS = ["0000-0002-1825-0097", "0000-0001-5109-3700"]


def _req(rid, cat, line, quote, enf, rule=None, **extra):
    return {"id": rid, "category": cat, "lines": f"L{line:04d}", "quote": quote, "rule": rule or {},
            "enforcement": enf, "article_type": "Original article", **extra}


def _requirements() -> list[dict]:
    return [
        _req("R01", "word_limits", 2, "The main text must not exceed 3000 words", "auto",
             {"field": "limits.main_text_words"}),
        _req("R02", "abstract_structure", 3, "must be structured with the headings Background, "
             "Methods, Results and Conclusions", "auto", {"field": "abstract.headings"}),
        _req("R02b", "word_limits", 3, "The abstract is limited to 250 words", "auto",
             {"field": "limits.abstract_words", "value": 250}),
        _req("R03", "keywords", 4, "Provide 3 to 6 keywords", "auto", {"field": "keywords.max"}),
        _req("R04", "title_page", 5, "all author names and affiliations", "manual"),
        _req("R05", "running_title", 5, "a running title of no more than 50 characters", "auto",
             {"field": "title_page.running_title_max_chars"}),
        _req("R06", "highlights", 6, "Highlights are not required.", "n.a.",
             reason="the journal does not ask for highlights"),
        _req("R07", "section_headings", 7, "Introduction, Methods, Results and Discussion in "
             "this order", "manual"),
        _req("R08", "references", 8, "should not exceed 40 references", "auto",
             {"field": "limits.reference_limit"}),
        _req("R09", "citations", 9, "numbers in square brackets", "manual"),
        _req("R10", "figures", 10, "TIFF files at a minimum of 300 dpi", "auto",
             {"field": "figure.min_dpi"}),
        _req("R11", "tables", 11, "Tables must be editable", "manual"),
        _req("R12", "supplementary", 12, "submitted as a single PDF file", "builder",
             {"field": "si_format"}),
        _req("R13", "declarations", 13, "Declarations must appear in this order", "manual"),
        _req("R14", "ethics_consent", 14, "Ethics approval and informed consent must be reported",
             "manual"),
        _req("R15", "data_availability", 15, "A data availability statement is mandatory.", "manual"),
        _req("R16", "ai_disclosure", 16, "generative AI tools must be disclosed", "manual"),
        _req("R17", "conflicts_of_interest", 17, "complete the ICMJE disclosure form in the "
             "submission system", "portal"),
        _req("R18", "funding", 18, "Funding sources must be listed", "manual"),
        _req("R19", "author_contributions", 19, "ORCID identifiers are required for all authors",
             "auto", {"field": "orcid_required"}),
        _req("R20", "cover_letter", 20, "not under consideration elsewhere", "auto",
             {"field": "cover_letter.must_state"}),
        _req("R21", "required_uploads", 21, "Required uploads: cover letter, title page", "auto",
             {"field": "required_uploads"}),
        _req("R22", "layout", 22, "Line numbers and page numbers are required.", "builder",
             {"field": "line_numbers"}),
        _req("R23", "language", 23, "written in American English", "manual"),
        _req("R24", "blinding", 24, "Peer review is single-blind.", "manual"),
        _req("R25", "reporting_checklist", 25, "A completed STROBE checklist must accompany",
             "manual"),
        _req("R26", "article_type_rules", 26, "Case reports: the text must not exceed 1500 words",
             "n.a.", reason="applies to case reports only"),
    ]


def _target(p: Path, **extra) -> dict:
    tj = {"journal": "Journal K", "issn": "1471-2482", "article_type": "Original article",
          "guidelines_url": "https://journal-k.example.org/guide",
          "limits": {"main_text_words": 3000, "abstract_words": 250, "reference_limit": 40,
                     "source": "https://journal-k.example.org/guide L0002 L0003 L0008"},
          "abstract": {"structured": True, "headings": ["Background", "Methods", "Results",
                                                        "Conclusions"]},
          "keywords": {"min": 3, "max": 6},
          "title_page": {"running_title_max_chars": 50,
                         "elements": ["title", "running title", "authors", "affiliations",
                                      "corresponding author", "orcid"]},
          "figure": {"formats": ["TIFF"], "min_dpi": 300, "max_mb": 10},
          "si_format": "pdf", "line_numbers": "continuous", "orcid_required": True,
          "cover_letter": {"must_state": ["not under consideration elsewhere"]},
          "required_uploads": ["cover letter", "title page", "manuscript", "figures", "tables"]}
    tj.update(extra)
    _w(p, "08_submission/target_journal.json", tj)
    return tj


def _reqfile(p: Path, reqs=None, **extra) -> None:
    data = {"schema": 1, "journal": "Journal K", "article_type": "Original article",
            "requirements": _requirements() if reqs is None else reqs,
            "not_mentioned": [],
            "not_applicable": [{"lines": "L0027", "reason": "Review articles only"}]}
    data.update(extra)
    _w(p, "08_submission/guideline_requirements.json", data)


def _guide_paper(path: Path, at: str = "S20_journal") -> Path:
    from wfcore import guideingest
    p = _paper(path, at)
    src = _w(p, "temp/guide.txt", "\n".join(GUIDE) + "\n")
    _target(p)
    guideingest.ingest(p, src, "https://journal-k.example.org/guide")
    src.unlink()
    _reqfile(p)
    return p


# ------------------------------------------------------------------------------ K1/K2
def run_mapped(tmp: Path, record, section) -> None:
    from wfcore import compliance, guideingest, requirements
    section("1.18.0 K1/K2: the guide becomes a requirement list checked line by line")
    p = _guide_paper(tmp / "map")
    lines = guideingest.source_lines(p)
    record("K1 fixture: guidelines_source.txt is line-numbered (27 lines)", len(lines) == 27,
           str(len(lines)))
    schema = json.loads((ROOT / "reference/guideline_requirements.schema.json").read_text(encoding="utf-8"))
    record("K1 the schema's category enum equals the engine's fixed list (26 categories) and the "
           "enforcement values",
           schema["$defs"]["category"]["enum"] == list(requirements.CATEGORIES)
           and len(requirements.CATEGORIES) == 26
           and schema["properties"]["requirements"]["items"]["properties"]["enforcement"]["enum"]
           == list(requirements.ENFORCEMENT))
    r = _gate(p, "guideline_requirements_mapped", "S20_journal")
    record("K2 a complete list (every category, verbatim quotes, numbers = typed fields, every "
           "obligation line covered) passes", r.ok, r.detail)
    (p / requirements.REQ_REL).unlink()
    r = _gate(p, "guideline_requirements_mapped", "S20_journal")
    record("K2 counterexample: 1.17.0 accepted an S20 with no requirement list; now it fails",
           not r.ok and r.blocking and "guideline_requirements.json missing" in r.detail, r.detail)
    reqs = _requirements()
    reqs[0]["quote"] = "The main text must not exceed 3500 words"
    _reqfile(p, reqs)
    r = _gate(p, "guideline_requirements_mapped", "S20_journal")
    record("K2 (b) a quote that is not verbatim at its cited line fails",
           not r.ok and "R01: quote does not occur verbatim at L0002" in r.detail, r.detail)
    _reqfile(p)
    _target(p, limits={"main_text_words": 3500, "abstract_words": 250, "reference_limit": 40,
                       "source": "x"})
    r = _gate(p, "guideline_requirements_mapped", "S20_journal")
    record("K2 (c) the extract says 3000 words but the typed field says 3500: caught",
           not r.ok and "R01: the guide says [3000]" in r.detail and "= 3500" in r.detail, r.detail)
    _target(p, limits={"main_text_words": 3000, "abstract_words": 300, "reference_limit": 40,
                       "source": "x"})
    r = _gate(p, "guideline_requirements_mapped", "S20_journal")
    record("K2 (c) rule.value differs from the typed field: caught",
           not r.ok and "R02b: rule value 250 differs" in r.detail, r.detail)
    _target(p)
    reqs = [x for x in _requirements() if x["id"] != "R14"]
    _reqfile(p, reqs)
    r = _gate(p, "guideline_requirements_mapped", "S20_journal")
    record("K2 (a)+(d) dropping the ethics requirement: the category is missing and its "
           "obligation line is listed as uncovered",
           not r.ok and "ethics_consent" in r.detail and "L0014" in r.detail, r.detail)
    _reqfile(p, [x for x in _requirements() if x["id"] != "R24"],
             not_mentioned=[{"category": "blinding", "searched": ["double-blind", "anonymised"]}])
    r = _gate(p, "guideline_requirements_mapped", "S20_journal")
    record("K2 (a) a silent category may be a 'not mentioned' entry with the terms searched",
           r.ok, r.detail)
    _reqfile(p, [x for x in _requirements() if x["id"] != "R24"],
             not_mentioned=[{"category": "blinding", "searched": ["single-blind", "anonymised"]}])
    r = _gate(p, "guideline_requirements_mapped", "S20_journal")
    record("K2 (a) a 'not mentioned' term that does occur in the guide fails with its line",
           not r.ok and "'single-blind' does occur at L0024" in r.detail, r.detail)
    _reqfile(p, not_applicable=[])
    r = _gate(p, "guideline_requirements_mapped", "S20_journal")
    record("K2 (d) an obligation sentence for another article type needs an n.a. range with a "
           "reason (L0027 uncovered)", not r.ok and "L0027" in r.detail and "uncovered" not in
           r.detail.split("L0027")[0][-5:], r.detail)
    reqs = _requirements()
    r07 = next(x for x in reqs if x["id"] == "R07")
    r07["enforcement"], r07["rule"] = "auto", {"field": "main_text_headings"}
    _reqfile(p, reqs)
    r = _gate(p, "guideline_requirements_mapped", "S20_journal")
    record("K2 an 'auto' rule the engine cannot measure is refused (use builder/manual)",
           not r.ok and "R07: enforcement auto, but the engine measures no field main_text_headings"
           in r.detail, r.detail)
    _reqfile(p)
    _target(p, double_blind=True)
    r = _gate(p, "guideline_requirements_mapped", "S20_journal")
    record("K2 a typed field with no requirement source is flagged as fallback (warning)",
           not r.ok and not r.blocking and "double_blind" in r.detail, r.detail)
    _target(p)
    _pin(p, "1.17.0")
    r = _gate(p, "guideline_requirements_mapped", "S20_journal")
    record("K2 a paper pinned to 1.17.0 is not judged until wf migrate", r.ok and "1.18.0" in r.detail,
           r.detail)
    record("K2 the obligation markers are matched case-insensitively per sentence",
           requirements.obligation_lines({1: "Authors MUST cite.", 2: "Figures look nice.",
                                          3: "A. No more than six. B."}) == [1, 3])
    record("K4 every auto field the gate accepts has an engine measurement",
           all(compliance.measurable(f, "") for f in ("limits.main_text_words", "abstract.headings",
                                                       "keywords.max", "figure.min_dpi", "csl",
                                                       "orcid_required", "required_uploads"))
           and not compliance.measurable("main_text_headings", ""))


# ------------------------------------------------------------------------------ K3
def _tiff(path: Path, dpi=300, mode="RGB", size=(60, 40)) -> Path:
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new(mode, size, "white").save(path, "TIFF", dpi=(dpi, dpi))
    return path


def _ms(abstract: str, extra_front: str = "") -> str:
    return (f"# Outcomes after X\n\n{extra_front}# Abstract\n\n{abstract}\n\nKeywords: cohort, "
            "outcome, surgery\n\n# Introduction\n\nText [@a].\n\n# Methods\n\nText.\n\n# Results\n"
            "\nText.\n\n# Discussion\n\nText.\n")


STRUCT = ("**Background:** Why it matters.\n\n**Methods:** What we did.\n\n**Results:** What we "
          "found.\n\n**Conclusions:** What it means.")


def run_fields(tmp: Path, record, section) -> None:
    from wfcore import displayfiles, journalfields as jf
    section("1.18.0 K3: typed journal fields reach the builders and the checks")
    p = _paper(tmp / "fields", "S23_package")
    tj = _target(p)
    _w(p, "07_manuscript/full_manuscript.md", _ms("A plain paragraph without headings."))
    s, d = jf.abstract_check(p, tj)
    record("K3 counterexample: an unstructured abstract passed 1.17.0; the journal wants headings",
           s == "FAIL" and "must be exactly" in d, d)
    _w(p, "07_manuscript/full_manuscript.md", _ms(STRUCT))
    s, d = jf.abstract_check(p, tj)
    record("K3 structured abstract with the journal's headings in order passes", s == "PASS", d)
    s, d = jf.abstract_check(p, {**tj, "abstract": {"structured": True, "per_section_words": 2}})
    record("K3 per-section word caps are measured", s == "FAIL" and "'Background' has 3 words > 2" in d, d)
    tp = ("# Outcomes after X\n\nRunning title: A much longer running title for the retrospective cohort study\n\n"
          f"Authors: Ann Lee (ORCID {ORCIDS[0]}), Bo Chen (ORCID {ORCIDS[1]})\n\n"
          "Affiliations: Department of Surgery, City Hospital\n\nCorresponding author: Ann Lee, "
          "ann@example.org\n")
    _w(p, "07_manuscript/title_page.md", tp)
    _w(p, "00_input/author_info.json", {"authors": [{"name": "Ann Lee", "orcid": ORCIDS[0]},
                                                    {"name": "Bo Chen", "orcid": ORCIDS[1]}],
                                        "corresponding": "Ann Lee"})
    s, d = jf.running_title_check(p, tj)
    record("K3 running title over the journal's 50 characters fails", s == "FAIL" and "> 50" in d, d)
    _w(p, "07_manuscript/title_page.md", tp.replace("A much longer running title for the retrospective cohort study",
                                                    "Outcomes after X"))
    s1, d1 = jf.running_title_check(p, tj)
    s2, d2 = jf.title_page_check(p, tj)
    record("K3 title page elements (title, running title, authors, affiliations, corresponding "
           "author, ORCID) and running-title length pass", s1 == "PASS" and s2 == "PASS", d1 + d2)
    s, d = jf.title_page_check(p, {**tj, "title_page": {"elements": ["word count"], "title_max_chars": 5}})
    record("K3 a missing title-page element and an over-long title fail",
           s == "FAIL" and "lacks 'word count'" in d and "title has 16 characters > 5" in d, d)
    tjm = {**tj, "running_title_position": "manuscript"}
    s, d = jf.running_title_check(p, tjm)
    record("K3 running_title_position 'manuscript' (defined but unused before 1.18.0) is checked",
           s == "FAIL" and "first page" in d, d)
    import importlib.util
    spec = importlib.util.spec_from_file_location("bd1180", ROOT / "tools/manuscript/build_docx.py")
    bd = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bd)
    out = bd._running_title(_ms(STRUCT), tjm, p)
    record("K3 the manuscript builder puts the title page's running title on the first page, "
           "after the title", out.startswith("# Outcomes after X\n\nRunning title: Outcomes after X\n\n# Abstract"),
           out[:80])
    record("K3 ...and leaves the manuscript alone when the journal wants it on the title page",
           bd._running_title(_ms(STRUCT), tj, p) == _ms(STRUCT))
    s, d = jf.orcid_check(p, tj)
    record("K3 orcid_required: every author's ORCID is valid and on the title page", s == "PASS", d)
    _w(p, "00_input/author_info.json", {"authors": [{"name": "Ann Lee", "orcid": "0000-0002-1825-0098"},
                                                    {"name": "Bo Chen"}]})
    s, d = jf.orcid_check(p, tj)
    record("K3 a wrong ORCID checksum and a missing ORCID fail",
           s == "FAIL" and "not valid" in d and "Bo Chen: no ORCID" in d, d)
    _w(p, "08_submission/cover_letter.md", "Dear Editor,\n\nPlease consider our cohort study.\n")
    s, d = jf.cover_letter_check(p, tj)
    record("K3 counterexample: a cover letter missing a must-state item passed 1.17.0; now FAIL",
           s == "FAIL" and "not under consideration elsewhere" in d, d)
    _w(p, "08_submission/cover_letter.md", "Dear Editor,\n\nThis work is not being considered for "
                                           "publication elsewhere and is not under consideration "
                                           "at another journal.\n")
    s, d = jf.cover_letter_check(p, {**tj, "cover_letter": {"must_state": [
        "not under consideration elsewhere", "all authors approved the final version"]}})
    record("K3 cover letter items: phrase/keyword presence, with the matching sentence listed "
           "for the reviewer", s == "FAIL" and "all authors approved" in d
           and jf.cover_letter_items(p, tj)[0][1].startswith("This work"), d)
    hl = {**tj, "highlights": {"required": True, "n_min": 3, "n_max": 5, "max_chars": 40}}
    s, d = jf.highlights_check(p, hl)
    record("K3 required highlights with no file fail", s == "FAIL" and "highlights.md" in d, d)
    _w(p, "08_submission/manuscript/highlights.md", "# Highlights\n\n- One short point\n- A second "
       "point that is clearly far too long for this journal\n")
    s, d = jf.highlights_check(p, hl)
    record("K3 highlights: count, characters per point and the upload are checked",
           s == "FAIL" and "2 point(s)" in d and "#2" in d and "role 'highlights'" in d, d)
    _w(p, "08_submission/manuscript/highlights.md", "# Highlights\n\n- Point one\n- Point two\n"
       "- Point three\n")
    hx = _w(p, "08_submission/bundle/highlights.docx", "x")
    src = p / "08_submission/manuscript/highlights.md"
    sha = lambda f: hashlib.sha256(f.read_bytes()).hexdigest().upper()  # noqa: E731
    _w(p, "08_submission/build_receipts/highlights.json", {
        "kind": "statements", "output": "08_submission/bundle/highlights.docx",
        "output_sha256": sha(hx), "sources": [{"path": "08_submission/manuscript/highlights.md",
                                                "sha256": sha(src)}], "auxiliaries": []})
    man = {"items": [{"file": "08_submission/bundle/highlights.docx", "role": "highlights",
                      "required_by": "L0006"}]}
    _w(p, "08_submission/bundle/manifest.json", man)
    s, d = jf.highlights_check(p, hl)
    record("K3 highlights generated from highlights.md (current build receipt) pass", s == "PASS", d)
    s, d = jf.uploads_check(p, tj)
    record("K3 required_uploads compared with the manifest roles",
           s == "FAIL" and "'cover letter' (role cover_letter)" in d, d)
    r = _gate(p, "bundle_complete", "S23_package")
    record("K3 bundle_complete reports the journal's missing required uploads",
           not r.ok and "required upload 'title page'" in r.detail, r.detail)
    # figure files: conversion from the TIFF master and format/dpi/size/colour checks
    _tiff(p / "05_figures/out/fig1.tif", dpi=300)
    _w(p, "01_protocol/artifact_plan.json", {"main_figures": [{"id": "Figure 1", "file": "05_figures/out/fig1.png"}],
                                             "main_tables": []})
    _w(p, "08_submission/bundle/manifest.json", {"items": []})
    _target(p, figure={"formats": ["EPS", "PDF"], "min_dpi": 300, "max_mb": 10})
    made = displayfiles.sync(p)
    item = json.loads((p / "08_submission/bundle/manifest.json").read_text(encoding="utf-8"))["items"][0]
    record("K3 figure.formats without TIFF: the separate figure file is converted from the master "
           "(EPS) and recorded with the master's hash",
           (p / "08_submission/bundle/Fig1.eps").is_file() and item["converted_to"] == "eps"
           and item["file"].endswith("Fig1.eps") and not displayfiles.problems(p), str(made))
    s, d = jf.figure_check(p, {"figure": {"formats": ["EPS"], "max_mb": 10}})
    record("K3 figure check: format accepted", s == "PASS", d)
    _tiff(p / "05_figures/out/fig1.tif", dpi=150)
    record("K3 a re-rendered master makes the converted file stale until wf rebuild",
           any("older master" in x or "150 dpi" in x for x in displayfiles.problems(p)),
           str(displayfiles.problems(p)))
    _target(p, figure={"formats": ["TIFF"], "colour": "CMYK"})
    displayfiles.sync(p)
    s, d = jf.figure_check(p, {"figure": {"formats": ["TIFF"], "min_dpi": 300, "max_mb": 0.000001,
                                          "colour": "RGB"}})
    record("K3 dpi below min_dpi, file over max_mb and the wrong colour mode are reported",
           s == "FAIL" and "150 dpi < 300" in d and "MB >" in d and "colour mode CMYK" in d, d)
    _pin(p, "1.17.0")
    _target(p, figure={"formats": ["EPS"]})
    files, _ = displayfiles.wanted(p)
    record("K3 a paper pinned to 1.17.0 keeps byte-identical TIFF copies (no conversion)",
           files and files[0][1].endswith("Fig1.tif"), str(files))
    r = _gate(p, "journal_fields_met", "S23_package")
    record("K3 journal_fields_met is not applied to a pinned paper", r.ok and "1.18.0" in r.detail, r.detail)


# ------------------------------------------------------------------------------ K4/K5
def _docx(path: Path, paras: list[tuple[str, str]], extra_xml: str = "", parts: dict | None = None) -> Path:
    ns = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"')
    body = "".join(f'<w:p><w:pPr><w:pStyle w:val="{s}"/></w:pPr><w:r><w:t>{t}</w:t></w:r></w:p>'
                   if s else f"<w:p><w:r><w:t>{t}</w:t></w:r></w:p>" for s, t in paras)
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", f"<w:document {ns}><w:body>{body}{extra_xml}</w:body></w:document>")
        for n, v in (parts or {}).items():
            z.writestr(n, v)
    return path


def _package(p: Path) -> None:
    """A synthetic S23 package that meets every auto rule of the fixture guide."""
    sh = "SectionHeading"
    tp = (f"# Outcomes after X\n\nRunning title: Outcomes after X\n\nAuthors: Ann Lee (ORCID "
          f"{ORCIDS[0]}), Bo Chen (ORCID {ORCIDS[1]})\n\nAffiliations: Department of Surgery\n\n"
          "Corresponding author: ann@example.org\n")
    for d in ("07_manuscript", "08_submission/manuscript"):  # frozen source and journal copy
        _w(p, f"{d}/full_manuscript.md", _ms(STRUCT))
        _w(p, f"{d}/title_page.md", tp)
    _w(p, "00_input/author_info.json", {"authors": [{"name": "Ann Lee", "orcid": ORCIDS[0]},
                                                    {"name": "Bo Chen", "orcid": ORCIDS[1]}]})
    _w(p, "08_submission/cover_letter.md", "Dear Editor, the manuscript is not under consideration "
       "elsewhere.\n")
    ms = _docx(p / "08_submission/bundle/manuscript.docx",
               [(sh, "Abstract"), ("", "Background: why. Methods: what. Results: found."),
                ("", "Keywords: cohort, outcome, surgery"), (sh, "Introduction"), ("", "Some words here."),
                (sh, "Methods"), ("", "More words."), (sh, "Results"), ("", "Found."),
                (sh, "Discussion"), ("", "Meaning."), (sh, "References"), ("", "1. Ref one."),
                ("", "2. Ref two.")])
    for name in ("title_page", "cover_letter"):
        _docx(p / f"08_submission/bundle/{name}.docx", [("", name)])
    _tiff(p / "08_submission/bundle/Fig1.tif")
    _w(p, "08_submission/bundle/Table1.xlsx", "x")
    _w(p, "08_submission/bundle/manifest.json", {"items": [
        {"file": f"08_submission/bundle/{f}", "role": r, "required_by": "L0021"} for f, r in
        (("manuscript.docx", "manuscript"), ("title_page.docx", "title_page"),
         ("cover_letter.docx", "cover_letter"), ("Fig1.tif", "figures"), ("Table1.xlsx", "tables"))]})
    sha = lambda f: hashlib.sha256(f.read_bytes()).hexdigest().upper()  # noqa: E731
    for kind, out in (("manuscript", ms), ("supplementary", _w(p, "08_submission/bundle/esm1.pdf", "%PDF"))):
        src = p / "08_submission/manuscript/full_manuscript.md" if kind == "manuscript" else \
            _w(p, "08_submission/manuscript/supplementary_methods.md", "# Supplementary\n")
        _w(p, f"08_submission/build_receipts/{kind}.json", {
            "kind": kind, "output": out.relative_to(p).as_posix(), "output_sha256": sha(out),
            "sources": [{"path": src.relative_to(p).as_posix(), "sha256": sha(src)}],
            "auxiliaries": [{"path": "08_submission/target_journal.json",
                             "sha256": sha(p / "08_submission/target_journal.json")}]})


MANUAL = ("R04", "R07", "R09", "R11", "R13", "R14", "R15", "R16", "R18", "R23", "R24", "R25")


def _evidence(p: Path, skip=()) -> None:
    _w(p, "08_submission/compliance_evidence.json", {
        rid: {"file": "07_manuscript/full_manuscript.md", "where": f"section for {rid}"}
        for rid in MANUAL if rid not in skip})


def _matrix_paper(path: Path, at: str) -> Path:
    p = _guide_paper(path, at)
    _package(p)
    return p


def run_matrix(tmp: Path, record, section) -> None:
    from wfcore import compliance
    section("1.18.0 K4/K5: one compliance-matrix row per requirement, summary for the user")
    p = _matrix_paper(tmp / "mx", "S23_package")
    r = _gate(p, "compliance_matrix_complete", "S23_package")
    record("K4 counterexample: 1.17.0 built the package without any per-requirement record; now "
           "the missing matrix fails", not r.ok and r.blocking and "stale" in r.detail, r.detail)
    from selftest_v180 import _gate as _g180  # noqa: F401 - same context builder
    from wfcore import registry
    from wfcore.checks import Ctx
    from wfcore.state import State
    pipe = registry.load()

    def ctx():
        return Ctx(pipe, State(p, ".wf").load(), p, pipe.stage("S23_package"), {})
    rows = compliance.write(ctx())
    by = {x["id"]: x for x in rows}
    auto_ok = all(by[i]["status"] == "PASS" for i in ("R01", "R02", "R02b", "R03", "R05", "R08",
                                                       "R10", "R19", "R20", "R21"))
    record("K4 auto rows are filled from measurements (words, abstract, keywords, running title, "
           "references, figure files, ORCID, cover letter, uploads)", auto_ok,
           json.dumps({k: (v["status"], v["evidence"][:60]) for k, v in by.items()
                       if v["enforcement"] == "auto" and v["status"] != "PASS"}))
    record("K4 builder rows come from current build receipts",
           by["R12"]["status"] == "PASS" and by["R22"]["status"] == "PASS"
           and "built by the engine" in by["R22"]["evidence"], by["R12"]["evidence"])
    record("K4 portal rows are CANNOT_ASSESS on the portal to-do list; n.a. rows keep their reason",
           by["R17"]["status"] == "CANNOT_ASSESS" and by["R17"]["portal"]
           and by["R26"]["status"] == "N.A." and "case reports" in by["R26"]["evidence"]
           and "R17" in (p / compliance.MATRIX_MD).read_text(encoding="utf-8").split("Portal to-do")[1])
    record("K4 manual rows without an evidence location are WARN",
           all(by[i]["status"] == "WARN" for i in MANUAL))
    r = _gate(p, "compliance_matrix_complete", "S23_package")
    record("K4 at S23 missing manual evidence is a warning only", not r.ok and not r.blocking
           and "manual evidence missing" in r.detail, r.detail)
    r = _gate(p, "compliance_matrix_complete", "S25_submission_audit", final=True)
    record("K4 at S25 (final) missing manual evidence fails", not r.ok and r.blocking, r.detail)
    _evidence(p)
    r = _gate(p, "compliance_matrix_complete", "S23_package")
    record("K4 an evidence edit makes the matrix stale until it is regenerated",
           not r.ok and "stale" in r.detail, r.detail)
    proc = _run(p, "tools/wf.py", "compliance", "write", cwd=p)
    r = _gate(p, "compliance_matrix_complete", "S23_package")
    record("K4 `wf compliance write` regenerates it; with evidence for every manual row the gate "
           "passes", proc.returncode == 0 and r.ok, _out(proc)[-300:] + r.detail)
    _w(p, "08_submission/compliance_evidence.json", {"R04": {"file": "nope.md", "where": "para 1"},
                                                     "R07": {"status": "cannot_assess",
                                                             "reason": "author decides headings"}})
    rows = {x["id"]: x for x in compliance.write(ctx())}
    record("K4 manual evidence must point to an existing file; 'cannot_assess' needs a reason",
           rows["R04"]["status"] == "FAIL" and rows["R07"]["status"] == "CANNOT_ASSESS")
    _evidence(p)
    _target(p, limits={"main_text_words": 5, "abstract_words": 250, "reference_limit": 1,
                       "source": "x"})
    compliance.write(ctx())
    r = _gate(p, "compliance_matrix_complete", "S23_package")
    record("K4 a measured violation (main text and reference count over the caps) is a FAIL row "
           "and blocks", not r.ok and r.blocking and "R01" in r.detail and "R08" in r.detail, r.detail)
    zh = compliance.summary_zh(p)
    record("K5 the Chinese summary gives counts per status and one line per FAIL / portal item",
           zh and zh[0].startswith("投稿指南合规矩阵（Journal K") and "未通过 4" in zh[0]
           and any(x.startswith("- R01［字数限制］") for x in zh)
           and any(x.startswith("- R22［行号/页码/版式］") and "stale" in x for x in zh)
           and "投稿系统中由您完成：" in zh and any(x.startswith("- R17") for x in zh), "\n".join(zh))
    proc = _run(p, "tools/wf.py", "compliance", "summary", cwd=p)
    record("K5 `wf compliance summary` prints it", proc.returncode == 0 and "未通过" in _out(proc),
           _out(proc)[-200:])
    rr = (ROOT / "tools/review_round.py").read_text(encoding="utf-8")
    record("K5 the package review round prints the summary before asking for 我确认这一版",
           "compliance.summary_zh(project)" in rr and rr.index("summary_zh") < rr.index(
               "Now give the user ONE summary"))
    _target(p)
    from wfcore import submissionqc
    (p / compliance.MATRIX_JSON).unlink()
    try:
        submissionqc.write(ctx())
        made = (p / compliance.MATRIX_JSON).is_file()
    except Exception as exc:  # noqa: BLE001
        made = f"{type(exc).__name__}: {exc}"
    record("K4 submission_qc.py write (run by wf rebuild) regenerates the matrix", made is True, str(made))


# ------------------------------------------------------------------------------ K6
def _report(verdicts: dict[str, str], extra: str = "", freeze: str = "ab" * 32) -> str:
    rows = "\n".join(f"- {k}: {v} - checked against guidelines_source.txt" for k, v in verdicts.items())
    return (f"## Verdict\nFreeze ID: {freeze}\nPASS\n\n## Guideline compliance\n{rows}\n\n"
            f"## Required files and omissions\n{extra or 'none'}\n")


def run_audit(tmp: Path, record, section) -> None:
    from wfcore import audit, compliance, registry
    from wfcore.checks import Ctx
    from wfcore.state import State
    section("1.18.0 K6: the S25 audit judges every requirement against the original text")
    p = _matrix_paper(tmp / "au", "S25_submission_audit")
    _evidence(p)
    pipe = registry.load()
    rows = compliance.write(Ctx(pipe, State(p, ".wf").load(), p, pipe.stage("S25_submission_audit"), {}))
    ids = [x["id"] for x in rows]
    _w(p, "08_submission/package_review_freeze.json", {"freeze_id": "ab" * 32})
    files = ["08_submission/guideline_requirements.json", "08_submission/compliance_matrix.md",
             "08_submission/compliance_matrix.json", *audit.guideline_files(p)]
    out, mode = audit.start(p, files)
    man = (out / "MANIFEST.md").read_text(encoding="utf-8")
    pr = (ROOT / "tools/package_review.py").read_text(encoding="utf-8")
    record("K6 the audit bundle lists the original guide, the cache original, the requirement "
           "list and the matrix, and the brief asks for a verdict per row and a scan for missing "
           "obligations", mode == "full" and "guideline_requirements.json" in man
           and "compliance_matrix.md" in man and "guidelines_source.txt" in man
           and "08_submission" in man and "cache" in man and "agree|disagree" in man
           and "MISSING L00nn" in man and "never a reason for\nREVISE" in man
           and "guideline_requirements.json" in pr and "compliance_matrix.json" in pr, man[:300])
    record("K6 a full audit must judge every row",
           json.loads((out / "rows_required.json").read_text(encoding="utf-8")) == ids)
    verdicts = {i: "agree" for i in ids}
    (out / "report.md").write_text(_report({k: v for k, v in verdicts.items() if k != "R09"}),
                                   encoding="utf-8")
    audit.save(p)
    r = _gate(p, "audit_rows_judged", "S25_submission_audit")
    record("K6 counterexample: an audit that skips a matrix row passed 1.17.0; now it fails",
           not r.ok and "R09" in r.detail, r.detail)
    verdicts["R09"] = "disagree"
    out, _m = audit.start(p, files)  # a fresh audit of the same freeze
    (out / "report.md").write_text(_report(verdicts, '- MISSING L0011: "cited in numerical order" '
                                                     "- BLOCKING"), encoding="utf-8")
    audit.save(p)
    st = State(p, ".wf").load()
    st.record_decision("submission_package_independent_audit", "PASS", "test")
    st.save()
    r = _gate(p, "audit_rows_judged", "S25_submission_audit")
    record("K6 a disagreement or a missing requirement is BLOCKING: PASS is refused",
           not r.ok and "disagrees with row(s) R09" in r.detail and "1 requirement(s) missing" in r.detail,
           r.detail)
    st = State(p, ".wf").load()
    st.record_decision("submission_package_independent_audit", "REVISE", "test")
    st.save()
    r = _gate(p, "audit_rows_judged", "S25_submission_audit")
    record("K6 with REVISE recorded the judged audit is consistent", r.ok, r.detail)
    # re-audit (same journal, new freeze): only the open rows plus new BLOCKING items
    _w(p, "08_submission/package_review_freeze.json", {"freeze_id": "cd" * 32})
    out2, mode2 = audit.start(p, files)
    need = json.loads((out2 / "rows_required.json").read_text(encoding="utf-8"))
    record("K6 a re-audit re-checks only the open rows (R09, previously disagreed)",
           mode2 == "recheck" and need == ["R09"] and (out2 / "open_rows.md").is_file()
           and "open_rows.md" in (out2 / "MANIFEST.md").read_text(encoding="utf-8"), str(need))
    (out2 / "report.md").write_text(_report({"R09": "agree"}, freeze="cd" * 32), encoding="utf-8")
    audit.save(p)
    st = State(p, ".wf").load()
    st.record_decision("submission_package_independent_audit", "PASS", "test")
    st.save()
    r = _gate(p, "audit_rows_judged", "S25_submission_audit")
    record("K6 the re-audit passes once the open row is agreed; CANNOT_ASSESS/portal rows do not "
           "block", r.ok, r.detail)


# ------------------------------------------------------------------------------ K7
def run_preflight(tmp: Path, record, section) -> None:
    from wfcore import docxaudit
    section("1.18.0 K7: DOCX preflight - tracked changes, comments, placeholders")
    clean = _docx(tmp / "clean.docx", [("", "Final text with 95% CI and a question?")])
    record("K7 a clean upload passes the preflight", docxaudit.preflight_problems(clean) == [],
           str(docxaudit.preflight_problems(clean)))
    bad = _docx(tmp / "bad.docx", [("", "Mortality was XXX% (TBD) [citation needed] ??")],
                extra_xml='<w:p><w:ins w:id="1"><w:r><w:t>added</w:t></w:r></w:ins>'
                          '<w:r><w:rPr><w:highlight w:val="yellow"/></w:rPr><w:t>insert value</w:t></w:r>'
                          '<w:r><w:commentReference w:id="0"/></w:r></w:p>',
                parts={"word/comments.xml": '<w:comments><w:comment w:id="0"/></w:comments>'})
    probs = " | ".join(docxaudit.preflight_problems(bad))
    record("K7 counterexample: tracked changes, comments, placeholders and highlighted text passed "
           "docx_bundle_ready in 1.17.0; the preflight reports each",
           "tracked change" in probs and "comment(s)" in probs and "XXX" in probs and "TBD" in probs
           and "[citation needed]" in probs and "??" in probs and "highlighted text" in probs, probs)
    lorem = _docx(tmp / "lorem.docx", [("", "Lorem ipsum dolor sit amet. TODO: add numbers.")])
    probs = " | ".join(docxaudit.preflight_problems(lorem))
    record("K7 lorem ipsum and TODO are placeholders", "lorem ipsum" in probs and "TODO" in probs, probs)
    src = (ROOT / "tools/wfcore/checks/manuscript.py").read_text(encoding="utf-8")
    record("K7 docx_bundle_ready runs the preflight on every DOCX upload (since 1.18.0)",
           "docxaudit.preflight_problems(path)" in src and "v1180 = " in src)


# ------------------------------------------------------------------------------ K8
def run_switch(tmp: Path, record, section) -> None:
    from selftest_v1170 import _frozen_paper
    from wfcore import compliance, journalepoch, registry, requirements
    from wfcore.state import State
    section("1.18.0 K8: requirement list and matrix are journal-layer files")
    p = _frozen_paper(tmp / "sw")
    for rel in (requirements.REQ_REL, compliance.MATRIX_JSON, compliance.MATRIX_MD, compliance.EVIDENCE):
        _w(p, rel, {"journal": "Journal A"} if rel.endswith(".json") else "Journal A matrix")
    _pin(p, "1.16.0")
    pipe = registry.load()
    st = State(p, ".wf").load()
    lines = journalepoch.switch(p, pipe, st, "Journal B", "Journal A", "rejected after review: scope")
    arch = journalepoch.archive_of(p)
    live = [rel for rel in (requirements.REQ_REL, compliance.MATRIX_JSON, compliance.MATRIX_MD,
                            compliance.EVIDENCE) if (p / rel).exists()]
    record("K8 the switch archives the old requirement list, matrix and evidence (none stay live)",
           not live and arch is not None and (arch / "guideline_requirements.json").is_file()
           and (arch / "compliance_matrix.md").is_file(), str(live))
    record("K8 the switch summary says the new list must be built from the new journal's own guide",
           any("guideline_requirements.json" in x and "新期刊自己的 guidelines_source.txt" in x
               for x in lines), "\n".join(lines))
    r = _gate(p, "guideline_requirements_mapped", "S20_journal")
    record("K8 the new epoch gets the full compliance flow even for a paper pinned to 1.16.0 "
           "(S20-S25 adopt the current gate set)", not r.ok and r.blocking
           and "guideline_requirements.json missing" in r.detail, r.detail)
    _w(p, requirements.REQ_REL, {"schema": 1, "journal": "Journal A", "journal_epoch": 1,
                                 "requirements": [{"id": "R1"}]})
    _w(p, "08_submission/guidelines_source.txt", "# guidelines_source.txt - journal epoch 2\nL0001  Text must be short.\n")
    r = _gate(p, "guideline_requirements_mapped", "S20_journal")
    record("K8 a copied old-journal list is refused (journal name and epoch)",
           not r.ok and "is for 'Journal A'" in r.detail and "journal_epoch must be 2" in r.detail,
           r.detail)


# ------------------------------------------------------------------------------ release
def run_release(tmp: Path, record, section) -> None:
    from wfcore import registry
    from wfcore.state import State
    section("1.18.0 release: version, one migration event, pinned paper policy, cards")
    q = tmp / "old"
    q.mkdir(parents=True, exist_ok=True)
    st = State(q, ".wf").create("medpaper", "1.17.0", "S23_package")
    before = sorted(x.name for x in q.rglob("*") if x.is_file() and ".wf" not in x.parts)
    st.migrate_pipeline("1.18.0", ["S23_package"])
    st.migrate_pipeline("1.18.0", ["S23_package"])
    notes = [e for e in st.data["events"] if e["kind"] == "requirements_changed"
             and str(e.get("detail", "")).startswith("1.18.0")]
    after = sorted(x.name for x in q.rglob("*") if x.is_file() and ".wf" not in x.parts)
    pipe = registry.load()
    sizes = {s.id: len((ROOT / "pipeline" / s.card).read_text(encoding="utf-8")) for s in pipe.stages}
    gates = {(s.id, g.get("check")): g.get("since") for s in pipe.stages for g in s.gate}
    record("R pipeline 1.18.0; a 1.17.0 paper gets exactly one 1.18.0 event, stays pinned, no paper "
           "file changes; cards <= limit",
           pipe.meta.get("version") in ("1.18.0", "1.19.0", "1.20.0", "1.21.0", "1.22.0", "1.23.0") and len(notes) == 1 and st.engine_pin == "1.17.0"
           and before == after and max(sizes.values()) <= registry.CARD_MAX_CHARS,
           f"{len(notes)} {max(sizes.values())}")
    record("R the new gates carry since = 1.18.0 at S20/S23/S25",
           all(gates.get(k) == "1.18.0" for k in (
               ("S20_journal", "guideline_requirements_mapped"), ("S23_package", "journal_fields_met"),
               ("S23_package", "compliance_matrix_complete"),
               ("S25_submission_audit", "compliance_matrix_complete"),
               ("S25_submission_audit", "audit_rows_judged"))), str(gates)[:200])
    cards = "".join((ROOT / "pipeline/stages" / n).read_text(encoding="utf-8") for n in (
        "S20_journal.md", "S23_package.md", "S24_package_human_review.md", "S25_submission_audit.md"))
    record("R the cards name the requirement list, the matrix evidence, the summary and the row "
           "verdicts", all(x in cards for x in ("guideline_requirements.json", "compliance_evidence.json",
                                                 "wf compliance summary", "agree/disagree")))


GROUPS = [("mapped", run_mapped), ("fields", run_fields), ("matrix", run_matrix),
          ("audit", run_audit), ("preflight", run_preflight), ("switch", run_switch),
          ("release", run_release)]


if __name__ == "__main__":  # quick subset run: python tools/selftest_v1180.py [groups]
    import tempfile
    os.environ.setdefault("MEDPAPER_STDOUT_ENCODING", "utf-8")
    fails = []

    def _record(name, ok, detail=""):
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail and not ok else ""))
        if not ok:
            fails.append(name)
        return ok
    with tempfile.TemporaryDirectory(prefix="mp_v1180_") as d:
        run(Path(d), _record, lambda t: print(f"\n{t}\n" + "-" * len(t)), " ".join(sys.argv[1:]))
    print(f"\n{len(fails)} failure(s)")
    sys.exit(1 if fails else 0)
