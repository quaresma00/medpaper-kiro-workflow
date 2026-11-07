"""1.19.0 regression tests: the title page on the manuscript's first page (M1), figure and table
placement from typed fields only (M2), a Discussion that interprets instead of restating the
Results (M3), supplementary files named number + type (M4) and the layout lines of the S24
summary (M5). Counterexample first where the 1.18.0 engine passed the defect. Synthetic
fixtures only - no real paper, dataset or network is used.

Called from tools/selftest.py.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from selftest_v1140 import _gate, _paper, _w  # noqa: E402


def run(tmp: Path, record, section, only: str = "") -> None:
    tmp.mkdir(parents=True, exist_ok=True)
    for name, fn in GROUPS:
        if not only or name in only.split():
            fn(tmp / name, record, section)


def _pin(p: Path, version: str) -> None:
    st = json.loads((p / ".wf/state.json").read_text(encoding="utf-8"))
    st["engine_pin"] = version
    (p / ".wf/state.json").write_text(json.dumps(st), encoding="utf-8")


def _target(p: Path, **fields) -> dict:
    tj = {"journal": "Fixture Journal", **fields}
    _w(p, "08_submission/target_journal.json", tj)
    return tj


def _req(p: Path, *reqs) -> None:
    _w(p, "08_submission/guideline_requirements.json", {"schema": 1, "requirements": [
        {"id": f"R{i}", "category": cat, "lines": f"L{line:04d}", "quote": quote,
         "rule": {"field": field}, "enforcement": "builder", "article_type": "all"}
        for i, (cat, field, line, quote) in enumerate(reqs, 1)]})


TITLE_PAGE = ("# Exposure and Clinical Outcome in a Multicentre Cohort Study\n\n"
              "Running title: Exposure and outcome\n\nAuthors: Ana Author, Bo Author\n\n"
              "Affiliations: Department of Medicine, City Hospital\n\nCorresponding author: Ana "
              "Author, City Hospital, 1 Main Street; ana@example.org; +1 555 0100\n\n"
              "Keywords: cohort, exposure\n\nReferences: 3\n")


def _docx_text(path: Path) -> str:
    import re
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    return "\n".join(re.sub(r"<[^>]+>", "", m) for m in re.findall(r"<w:p[ >].*?</w:p>", xml, re.S))


# ------------------------------------------------------------------------------ M1
def run_title_page(tmp: Path, record, section) -> None:
    import selftest_v180 as v180
    from manuscript import build_docx as bd
    from wfcore import docxaudit, layout
    section("1.19.0 M1: the title page on the manuscript's first page")
    p, env = v180._paper(tmp / "tp", {"journal": "Fixture Journal"})
    _w(p, "07_manuscript/title_page.md", TITLE_PAGE)
    tj = json.loads((p / "08_submission/target_journal.json").read_text(encoding="utf-8"))
    _pin(p, "1.18.0")
    record("M1 counterexample: 1.18.0 kept author information only in the separate title page",
           layout.title_page_placement(tj, p) == "separate"
           and bd._title_page_front(v180._manuscript("x"), tj, p) == v180._manuscript("x"))
    record("M1 an explicit title_page.placement is honoured on a pinned paper's next build",
           layout.title_page_placement({**tj, "title_page": {"placement": "in_manuscript"}}, p)
           == "in_manuscript")
    _pin(p, "1.19.0")
    record("M1 not blinded, journal silent: default in_manuscript (no separate title-page file)",
           layout.title_page_placement(tj, p) == "in_manuscript")
    record("M1 required_uploads lists a title page: both (first page + separate file)",
           layout.title_page_placement({**tj, "required_uploads": ["manuscript", "title page"]}, p)
           == "both")
    blind = {**tj, "blinded_main_manuscript": True, "title_page": {"placement": "in_manuscript"}}
    record("M1 blinded journal: separate only, whatever the field says, and the field is flagged",
           layout.title_page_placement(blind, p) == "separate"
           and bd._title_page_front(v180._manuscript("x"), blind, p) == v180._manuscript("x"))
    front = bd._title_page_front(v180._manuscript("x"), tj, p)
    head = front.split("# Abstract")[0]
    record("M1 render copy: title page block (title, running title, authors, affiliations, "
           "corresponding author with address/email/phone, counts), a page break, then the "
           "abstract; one Keywords line (the abstract's)",
           head.startswith("# Exposure and Clinical") and "Ana Author" in head and "+1 555" in head
           and "References: 3" in head and bd.PAGE_BREAK_MD in head
           and front.count("Keywords:") == 1 and head.count("# Exposure") == 1, head[:200])
    src = p / "08_submission/full_manuscript.md"
    src.write_text(v180._manuscript(v180.__dict__.get("GOOD_DECL", "## Funding\nNone.\n\n## Competing "
                                    "interests\nNone.")), encoding="utf-8")
    proc = v180._build(p, env, "manuscript", src, "manuscript.docx", "--bibliography",
                       p / "06_refs/refs.bib", "--csl", p / "06_refs/numeric.csl")
    out = p / "08_submission/bundle/manuscript.docx"
    ok = proc.returncode == 0
    text = _docx_text(out) if ok else ""
    record("M1 the built manuscript carries the title page, then a page break, then the abstract",
           ok and text.index("Ana Author") < text.index("Abstract")
           and '<w:br w:type="page"/>' in zipfile.ZipFile(out).read("word/document.xml").decode(),
           (proc.stdout + proc.stderr)[-300:])
    from wfcore.packagecontent import build_receipt_path
    rp = build_receipt_path(p, out)
    rec = json.loads(rp.read_text(encoding="utf-8")) if ok and rp.is_file() else {}
    record("M1 one source: the manuscript receipt binds the title page and author_info.json",
           {"07_manuscript/title_page.md", "00_input/author_info.json"}
           <= {a["path"] for a in rec.get("auxiliaries", [])}, str(rec.get("auxiliaries"))[:200])
    _w(p, "08_submission/bundle/manifest.json", {"items": [
        {"file": "08_submission/bundle/manuscript.docx", "role": "manuscript", "required_by": "L1"}]})
    _w(p, "07_manuscript/full_manuscript.md", src.read_text(encoding="utf-8"))
    r = _gate(p, "title_page_reference_count", "S23_package")
    record("M1 title_page_reference_count reads the count on the manuscript's first page",
           r.ok and "matches 3" in r.detail, r.detail)
    _w(p, "08_submission/bundle/manifest.json", {"items": [
        {"file": "08_submission/bundle/manuscript.docx", "role": "manuscript", "required_by": "L1"},
        {"file": "08_submission/bundle/title_page.docx", "role": "title_page", "required_by": "L1"}]})
    record("M1 in_manuscript + a separate title-page upload is flagged (only for 'both')",
           any("remove it from the manifest" in x for x in layout.problems(p)), str(layout.problems(p)))
    _target(p, blinded_main_manuscript=True)
    proc = v180._build(p, env, "manuscript", src, "manuscript.docx", "--bibliography",
                       p / "06_refs/refs.bib", "--csl", p / "06_refs/numeric.csl")
    record("M1 blinded journal: the built manuscript stays anonymous (blinding audit clean)",
           proc.returncode == 0 and not docxaudit.blinding_problems(out, docxaudit.identity_strings(p))
           and "Ana Author" not in _docx_text(out), (proc.stdout + proc.stderr)[-200:])


# ------------------------------------------------------------------------------ M2
def run_placement(tmp: Path, record, section) -> None:
    import selftest_v180 as v180
    from manuscript import build_docx as bd
    from wfcore import displayfiles, docxaudit, layout
    section("1.19.0 M2: figure and table placement only from typed fields")
    p, _env = v180._paper(tmp / "fig", {"journal": "Fixture Journal", "embed_figures": True})
    record("M2 who decided (counterexample): the images at the end came from embed_figures=true "
           "in target_journal.json (S20 agent), which the 1.18.0 builder honoured without a "
           "guideline basis; 1.19.0 flags it",
           layout.legacy_embed(json.loads((p / "08_submission/target_journal.json").read_text()))
           and any("embed_figures = true" in x for x in layout.problems(p)), str(layout.problems(p)))
    tj = _target(p)
    spec = docxaudit.audit_spec(p)
    record("M2 defaults (guide silent): figures separate files (no images), tables after the "
           "references in the manuscript",
           layout.figure_placement(tj, p) == "separate_files" and not spec["embed_figures"]
           and layout.table_placement(tj, p) == "end_of_manuscript" and spec["word_tables"])
    _pin(p, "1.18.0")
    record("M2 a pinned paper without the fields keeps its legacy table layout (word_tables)",
           layout.table_placement(tj, p) == "none"
           and layout.table_placement({**tj, "word_tables": True}, p) == "end_of_manuscript")
    _pin(p, "1.19.0")
    ms = (v180._manuscript("x").replace("Results are shown in Figure 1 and Figure S1.",
                                        "Baseline data are in Table 1.\n\nThe association is shown "
                                        "in Figure 1."))
    src = _w(p, "temp/ms.md", ms)
    work = Path(tempfile.mkdtemp(dir=tmp))
    tj = _target(p, figures={"placement": "end_of_manuscript"})
    out = bd.prepare_source("manuscript", [src], p, work)[0].read_text(encoding="utf-8")
    legends_at = out.index("# Figure legends")
    record("M2 end_of_manuscript: the legend list, then each image on its own page with its legend",
           "# Figures" in out and out.index("# Figures") > legends_at
           and out.index("![](") > out.index("# Figures") and "**Figure 1" in out, out[legends_at:legends_at + 300])
    record("M2 a non-default placement without a guideline requirement is flagged",
           any("figures.placement = end_of_manuscript" in x for x in layout.problems(p)))
    _req(p, ("figures", "figures.placement", 12, "Figures should be placed at the end of the manuscript"))
    record("M2 ...and accepted with a requirement (rule.field figures.placement, quote + line)",
           not any("figures.placement" in x for x in layout.problems(p)), str(layout.problems(p)))
    (p / "05_figures/out/Figure1.tif").write_bytes((p / "05_figures/out/Figure1.png").read_bytes())
    files, _ = displayfiles.wanted(p)
    record("M2 figures are not both embedded and uploaded separately unless the guide asks",
           not [f for f in files if f[2] == "figures"]
           and layout.figures_separate({**tj, "figures": {"placement": "end_of_manuscript",
                                                         "also_separate": True}}, p))
    _target(p, figures={"placement": "in_text"}, tables={"placement": "in_text"})
    out = bd.prepare_source("manuscript", [src], p, work)[0].read_text(encoding="utf-8")
    cite_t, cite_f = out.index("Baseline data are in Table 1."), out.index("is shown in Figure 1.")
    record("M2 in_text: the table and the figure (with its legend) follow the paragraph that "
           "first cites them, before References",
           cite_t < out.index("<w:tbl>") < cite_f < out.index("![](") < out.index("# References")
           and "# Figure legends" not in out, out[cite_t:cite_t + 120])
    spec = docxaudit.audit_spec(p)
    record("M2 the audit follows the fields (in_text: no Figure legends section required)",
           spec["figure_placement"] == "in_text" and spec["embed_figures"])


# ------------------------------------------------------------------------------ M3
RESULTS = ("# Results\n\nAmong 412 patients, the exposed group had a higher risk of the outcome "
           "(HR 1.87, 95% CI 1.21 to 2.90; Table 2). Mortality at 30 days was 12.5% in the exposed "
           "group and 6.1% in the reference group. The association persisted in the restricted "
           "cohort (HR 1.74, 95% CI 1.10 to 2.75; Table S2). Bleeding occurred in 8.2% of exposed "
           "patients and 3.9% of reference patients (Figure 2).\n")
BAD = ("# Discussion\n\nAmong 412 patients, the exposed group had a higher risk of the outcome (HR "
       "1.87, 95% CI 1.21 to 2.90; Table 2). Mortality at 30 days was 12.5% in the exposed group "
       "and 6.1% in the reference group (Table 3). The association persisted in the restricted "
       "cohort (HR 1.74, 95% CI 1.10 to 2.75; Table S2). Bleeding occurred in 8.2% of exposed "
       "patients and 3.9% of reference patients (Figure 2). These findings agree with earlier "
       "work [@a1].\n")
GOOD = ("# Discussion\n\nIn this cohort, exposure was associated with a higher risk of the outcome "
        "(HR 1.87, 95% CI 1.21 to 2.90). This agrees with two registry studies [@a1; @a2] but "
        "contrasts with a trial population that excluded older patients [@a3]; the narrower "
        "definition of the outcome there probably lowered the event rate. Endothelial injury is a "
        "plausible pathway, consistent with experimental work [@a4]. Clinicians may consider closer "
        "monitoring of exposed patients, although a single observational study cannot change "
        "practice [@a5]. Residual confounding by frailty would most likely bias the estimate away "
        "from the null.\n")
OUTLINE = ("## Principal findings\nF1: exposure linked to higher risk of the outcome.\nF2: the "
           "association persisted after restriction.\n## Comparison with previous studies\nF1: "
           "agrees with [@a1; @a2]; differs from [@a3] (older patients excluded).\nF2: no prior "
           "study examined the restricted cohort.\n## Possible mechanisms\nEndothelial injury.\n"
           "## Clinical and research implications\nCloser monitoring; a trial is needed.\n"
           "## Strengths and limitations\nResidual confounding by frailty, bias away from the null.\n"
           "## Conclusion\nExposure was associated with higher risk.\n")


def run_discussion(tmp: Path, record, section) -> None:
    from wfcore import discussion
    sys.path.insert(0, str(ROOT / "tools/manuscript"))
    import writer_bundle as wb
    section("1.19.0 M3: the Discussion interprets, it does not restate the Results")
    p = _paper(tmp / "disc", "S16_discussion")
    _w(p, "06_refs/library.json", {"entries": [{"citekey": f"a{i}", "year": 2020, "title": f"T{i}"}
                                               for i in range(1, 7)]})
    probs, _w1 = discussion.analyse(p, BAD, RESULTS)
    record("M3 a Discussion restating the Results fails: own numbers, restated sentences, "
           "repeated table/figure citations",
           any("restate Results sentences" in x for x in probs)
           and any("repeat the study's own result numbers" in x for x in probs)
           and any("cites tables/figures" in x for x in probs), " | ".join(probs)[:300])
    record("M3 a supplementary citation (Table S2) in the Discussion fails, with a rewrite hint",
           any("supplementary material (Table S2)" in x and "remove" in x for x in probs))
    gp, gw = discussion.analyse(p, GOOD, RESULTS)
    record("M3 an interpretive Discussion (primary estimate once, comparison, mechanism, "
           "implication, bias direction, 5 prior studies) passes", not gp and not gw, str(gp + gw))
    _, few = discussion.analyse(p, GOOD.replace("[@a4]", "").replace("[@a5]", ""), RESULTS)
    record("M3 fewer than 5 distinct verified prior studies is a warning only",
           any("cites 3 distinct verified prior studies" in x for x in few), str(few))
    _w(p, ".wf/config.toml", "[targets]\ndiscussion_display_citations_max = 6\n")
    t, warn = discussion.thresholds(p)
    record("M3 a per-paper threshold without a reason is ignored (engine default kept)",
           t["discussion_display_citations_max"] == 2 and "ignored" in warn[0], str(warn))
    _w(p, ".wf/config.toml", "[targets]\ndiscussion_display_citations_max = 6\n"
       "discussion_thresholds_reason = \"journal style cites every table in the Discussion\"\n")
    t, warn = discussion.thresholds(p)
    probs2, _ = discussion.analyse(p, BAD, RESULTS)
    record("M3 ...and applied with a reason (paper config, never the engine)",
           t["discussion_display_citations_max"] == 6 and not any("cites tables/figures" in x for x in probs2))
    (p / ".wf/config.toml").unlink()
    r = _gate(p, "discussion_outline_ready", "S16_discussion")
    record("M3 outline gate fails without the outline", not r.ok and "missing" in r.detail, r.detail)
    _w(p, discussion.OUTLINE, OUTLINE.replace("## Possible mechanisms\nEndothelial injury.\n", "")
       .replace("F2: no prior study examined the restricted cohort.", "F2: see above."))
    r = _gate(p, "discussion_outline_ready", "S16_discussion")
    record("M3 outline gate fails: a missing label, a key finding without a verified comparison",
           not r.ok and "Possible mechanisms" in r.detail and "F2" in r.detail, r.detail)
    _w(p, discussion.OUTLINE, OUTLINE)
    r = _gate(p, "discussion_outline_ready", "S16_discussion")
    record("M3 outline gate passes: six labels, each finding compared or 'no prior study'", r.ok, r.detail)
    _w(p, "07_manuscript/discussion.md", BAD)
    _w(p, "07_manuscript/results.md", RESULTS)
    r = _gate(p, "section_language_clean", "S16_discussion", path="07_manuscript/discussion.md",
              discussion_checks=True)
    record("M3 the S16 section-language gate carries the Discussion checks (since 1.19.0)",
           not r.ok and "discussion:" in r.detail, r.detail[:200])
    _pin(p, "1.18.0")
    r = _gate(p, "section_language_clean", "S16_discussion", path="07_manuscript/discussion.md",
              discussion_checks=True)
    r2 = _gate(p, "discussion_outline_ready", "S16_discussion")
    record("M3 a paper pinned before 1.19.0 keeps its gate set", "discussion:" not in r.detail
           and r2.ok and "1.19.0" in r2.detail, r.detail[:120])
    _pin(p, "1.19.0")
    # (a) writer bundle for S16
    _w(p, "01_protocol/display_dictionary.json", {"terms": [
        {"internal": "comp_a", "label": "Portal vascular disease", "definition": "portal vein "
         "thrombosis or nodular hyperplasia"},
        {"internal": "exposed", "label": "Exposed group", "definition": "reports naming the drug"}]})
    _w(p, "03_analysis/results/primary.json", {"comp_a": {"exposed": {"hr": 1.87, "hr_low": 1.2,
                                                                      "hr_high": 2.9}},
                                               "environment": {"ci_level": 0.95}})
    _w(p, "06_refs/deepread/a1.md", "# a1 - Registry cohort\n\n## Design and population\nOlder "
       "registry cohort (Table 2).\n\n## How this supports or contradicts our finding\nAgrees.\n")
    _w(p, "03_analysis/notes.md", "# Notes\n\n## Limitations\nResidual confounding by frailty "
       "(Table S3).\n")
    out = wb.build(p, "S16_discussion")
    names = sorted(x.name for x in out.iterdir())
    allt = "\n".join((out / n).read_text(encoding="utf-8") for n in names if n != "MANIFEST.md")
    kf = (out / "key_findings.md").read_text(encoding="utf-8")
    record("M3 (a) the S16 bundle has key findings in words, the primary estimate once, the "
           "deep-read comparison points and the limitations - no result tables, legends or display ids",
           {"key_findings.md", "comparison_points.md", "limitations.md", "library.md"} <= set(names)
           and not {"tables.md", "legends.md", "results_in_words.md"} & set(names)
           and "[primary]" in kf and "moderately higher (hazard ratio)" in kf
           and "1.87 (95% CI 1.2 to 2.9)" in kf and "Table" not in allt.replace("tables or figures", ""),
           f"{names} | {kf[-200:]}")
    man = (out / "MANIFEST.md").read_text(encoding="utf-8")
    record("M3 (b) the manifest asks for the outline first (labels, F1..., never exported)",
           discussion.OUTLINE in man and all(lab in man for lab in discussion.LABELS))
    record("M3 the S16 bundle passes the writer-bundle lint", not wb.lint(p, "S16_discussion"),
           str(wb.lint(p, "S16_discussion"))[:200])
    card = (ROOT / "pipeline/stages/S16_discussion.md").read_text(encoding="utf-8")
    writer = (ROOT / ".kiro/agents/medpaper-clinical-writer.md").read_text(encoding="utf-8")
    reviewer = (ROOT / ".kiro/agents/medpaper-reviewer.md").read_text(encoding="utf-8")
    from wfcore import adapters
    record("M3 (d) S16 card and writer prompt: principal findings without numbers/tables, compare "
           "and explain, mechanisms, implications, bias direction, no new results, no subheadings; "
           "the writer may write only the outline besides prose",
           all(s in card for s in ("explain why results differ", "mechanisms", "direction and size",
                                   "no overclaiming", "without subheadings"))
           and all(s in writer for s in ("interpret, do not restate", "explain why results differ",
                                         "direction and size", "no overclaiming", "without subheadings"))
           and ".wf/writer/*.md" in writer and '".wf/**"' not in writer
           and not adapters.agent_scope_problems("medpaper-clinical-writer", writer))
    record("M3 (e) reviewer rubric: Discussion restates results / missing comparison or "
           "explanation / missing mechanisms or implications / generic limitations, closed as "
           "changed or kept with a reason",
           all(s in reviewer for s in ("restates the Results", "differences are not",
                                       "mechanisms/plausibility", "limitations are generic",
                                       "changed or kept with a reason")))


# ------------------------------------------------------------------------------ M4
def run_names(tmp: Path, record, section) -> None:
    import selftest_v180 as v180
    from wfcore import layout, supplementary
    from wfcore.packagecontent import build_receipt_path
    section("1.19.0 M4: supplementary files named number + type")
    record("M4 title slug: ASCII, words capitalised, underscores, <= 50 characters",
           layout.title_slug("Supplementary methods") == "Supplementary_Methods"
           and layout.title_slug("STROBE checklist") == "STROBE_Checklist"
           and len(layout.title_slug("word " * 40)) <= 50
           and layout.title_slug("Tableaux supplémentaires") == "Tableaux_Supplementaires")
    record("M4 default pattern Supplemental_File_{n}_{Title}",
           layout.supplementary_stem(layout.DEFAULT_SUPP_PATTERN, 1, "Supplementary Methods")
           == "Supplemental_File_1_Supplementary_Methods")
    p, _env = v180._paper(tmp / "esm", {"journal": "Fixture Journal",
                                        "supplementary_label": "Online Resource"})
    shutil.copyfile(p / "05_figures/out/Figure1.png", p / "05_figures/out/FigureS1.png")
    out, rec = supplementary.figures_pdf(p, p / "08_submission/bundle", 3)
    from pypdf import PdfReader
    txt = PdfReader(str(out)).pages[0].extract_text()
    record("M4 a bundle directory as output gets Supplemental_File_3_Supplementary_Figures.pdf; the "
           "info page reads 'Online Resource 3: Supplementary Figures'",
           out.name == "Supplemental_File_3_Supplementary_Figures.pdf"
           and "Online Resource 3: Supplementary Figures" in " ".join(txt.split()), out.name + " | " + txt[:80])
    old = _w(p, "08_submission/bundle/ESM_2.xlsx", "x")
    rp = build_receipt_path(p, old)
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(json.dumps({"kind": "esm_xlsx", "output": "08_submission/bundle/ESM_2.xlsx",
                              "output_sha256": "", "sources": [], "auxiliaries": [],
                              "args": {"number": 2, "input": "04_tables/supplementary/t.xlsx"}}),
                  encoding="utf-8")
    _w(p, "08_submission/bundle/manifest.json", {"items": [
        {"file": "08_submission/bundle/ESM_2.xlsx", "role": "supplementary", "required_by": "L9"}]})
    _w(p, "08_submission/cover_letter.md", "Dear Editor, ESM_2.xlsx holds the tables.\n")
    probs = layout.problems(p)
    record("M4 counterexample: an 'ESM_2' upload name is flagged with its new name",
           any("ESM_2.xlsx -> 08_submission/bundle/Supplemental_File_2_Supplementary_Tables.xlsx" in x
               for x in probs), str(probs)[:300])
    moved = layout.rename_supplementary(p)
    man = json.loads((p / "08_submission/bundle/manifest.json").read_text(encoding="utf-8"))
    new = p / "08_submission/bundle/Supplemental_File_2_Supplementary_Tables.xlsx"
    record("M4 wf rebuild renames the file, its receipt and the manifest entry (upload list, "
           "portal to-do and final copy read the manifest)",
           moved and new.is_file() and not old.exists() and build_receipt_path(p, new).is_file()
           and man["items"][0]["file"].endswith("Supplemental_File_2_Supplementary_Tables.xlsx"),
           str(moved))
    record("M4 a cover letter still naming the old file is flagged",
           any("cover letter names" in x and "ESM_2.xlsx" in x for x in layout.problems(p)))
    _w(p, "08_submission/cover_letter.md", "Dear Editor, Online Resource 2 holds the tables.\n")
    _target(p, supplementary_file_pattern="ESM_{n}")
    record("M4 an explicit pattern without a guideline mandate is flagged",
           any("supplementary_file_pattern" in x and "e.g." in x for x in layout.problems(p)))
    _req(p, ("supplementary", "supplementary_file_pattern", 30, "Files must be named ESM_1, ESM_2"))
    record("M4 ...a mandated pattern (quote + line) renames to it",
           not any("supplementary_file_pattern needs" in x for x in layout.problems(p))
           and layout.rename_supplementary(p) and (p / "08_submission/bundle/ESM_2.xlsx").is_file())
    q, _e = v180._paper(tmp / "pinned", {"journal": "Fixture Journal"})
    _pin(q, "1.18.0")
    record("M4 a pinned paper keeps the names it chose until wf migrate --yes or a journal switch",
           layout.supplementary_pattern({}, q) is None and not layout.rename_supplementary(q))
    st = json.loads((q / ".wf/state.json").read_text(encoding="utf-8"))
    st["journal_gate_pin"] = {"version": "1.19.0", "stages": ["S20_journal", "S21_authors",
                                                              "S22_polish", "S23_package",
                                                              "S24_package_human_review",
                                                              "S25_submission_audit"]}
    (q / ".wf/state.json").write_text(json.dumps(st), encoding="utf-8")
    record("M4/M1/M2 after a journal switch the new journal's package uses the 1.19.0 defaults",
           layout.supplementary_pattern({}, q) == layout.DEFAULT_SUPP_PATTERN
           and layout.title_page_placement({}, q) == "in_manuscript"
           and layout.table_placement({}, q) == "end_of_manuscript")


# ------------------------------------------------------------------------------ M5
def run_summary(tmp: Path, record, section) -> None:
    from wfcore import compliance, layout
    from wfcore.state import State
    section("1.19.0 M5: layout decisions with their basis in the S24 summary")
    p = _paper(tmp / "sum", "S24_package_human_review")
    _target(p, figures={"placement": "in_text"})
    _req(p, ("figures", "figures.placement", 41, "Figures should be embedded in the text near "
             "their first citation"))
    lines = layout.decisions_zh(p)
    record("M5 one line per decision (title page, figures, tables, supplementary names, "
           "abbreviation list), each with its basis: guideline L#### quote or engine default",
           len(lines) == 6 and "L0041" in lines[2] and "first citation" in lines[2]
           and "引擎默认" in lines[1] and all("依据" in x for x in lines[1:]), "\n".join(lines))
    record("M5 wf compliance summary prints them (also without a matrix)",
           compliance.summary_zh(p)[-6:] == lines)
    st = State(p, ".wf").load()
    n0 = len(st.data.get("events", []))
    st._note_v1190("1.18.0", "1.19.0")
    st._note_v1190("1.18.0", "1.19.0")
    ev = st.data.get("events", [])
    record("M5 migration: one event, no paper file touched",
           len(ev) == n0 + 1 and "Paper files were not modified" in str(ev[-1]))
    from wfcore import registry
    q = tmp / "old"
    q.mkdir(parents=True, exist_ok=True)
    st = State(q, ".wf").create("medpaper", "1.18.0", "S23_package")
    before = sorted(x.name for x in q.rglob("*") if x.is_file() and ".wf" not in x.parts)
    st.migrate_pipeline("1.19.0", ["S23_package"])
    st.migrate_pipeline("1.19.0", ["S23_package"])
    notes = [e for e in st.data["events"] if e["kind"] == "requirements_changed"
             and str(e.get("detail", "")).startswith("1.19.0")]
    pipe = registry.load()
    sizes = {s.id: len((ROOT / "pipeline" / s.card).read_text(encoding="utf-8")) for s in pipe.stages}
    gates = {(s.id, g.get("check")): g for s in pipe.stages for g in s.gate}
    record("R pipeline 1.19.0; a 1.18.0 paper gets exactly one 1.19.0 event, stays pinned, no "
           "paper file changes; cards <= limit; new gates carry since = 1.19.0",
           pipe.meta.get("version") in ("1.19.0", "1.20.0", "1.21.0") and len(notes) == 1 and st.engine_pin == "1.18.0"
           and before == sorted(x.name for x in q.rglob("*") if x.is_file() and ".wf" not in x.parts)
           and max(sizes.values()) <= registry.CARD_MAX_CHARS
           and gates[("S16_discussion", "discussion_outline_ready")].get("since") == "1.19.0"
           and gates[("S23_package", "layout_from_guideline")].get("since") == "1.19.0"
           and gates[("S16_discussion", "section_language_clean")].get("discussion_checks") is True,
           f"{len(notes)} {max(sizes.values())}")


GROUPS = [("title_page", run_title_page), ("placement", run_placement),
          ("discussion", run_discussion), ("names", run_names), ("summary", run_summary)]
