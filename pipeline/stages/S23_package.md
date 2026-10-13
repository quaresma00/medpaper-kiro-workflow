# S23 - Build and visually verify the submission package

## Purpose
Produce the exact files required by the chosen journal. All uploadable prose is delivered
as Word, with deterministic typography and no residual Pandoc/Word theme defects. This stage
builds the package; S24 is the user's final content/format review and S25 is the independent
journal-guideline audit.

This is also **the visual checkpoint for the whole run**. Under the default
`visual_review_mode = "deferred"`, the figure and table looks parked at S10/S11 are discharged
here in one pass (step 8) - on final renders, with the journal's column width, font floor and
palette already fixed by S20. `visual_debts_cleared` is non-overridable, so nothing ships
unlooked-at.

## Procedure
1. Freeze the journal-required item list from `guidelines_extract.md`; do not add generic
   extras. Write the journal-specific cover letter source outside the bundle at
   `project/08_submission/cover_letter.md`.
2. Before building the title page, synchronize any existing reference-count field with the
   distinct citekeys actually used in `full_manuscript.md`:
```
.\.venv\Scripts\python.exe tools/manuscript/reference_count.py sync
```
   Use `sync --add` only when the official title-page instructions require that field. Do not
   derive it from the candidate literature-library size.
3. Build every prose upload with `tools/manuscript/build_docx.py` **from the journal
   variant**, never from the frozen `07_manuscript/` source. At minimum:
```
.\.venv\Scripts\python.exe tools/manuscript/build_docx.py build --kind manuscript --input project/08_submission/manuscript/full_manuscript.md --output project/08_submission/bundle/manuscript.docx --style-config project/08_submission/docx_style.json --bibliography project/06_refs/refs.bib --csl <journal.csl>
.\.venv\Scripts\python.exe tools/manuscript/build_docx.py build --kind title_page --input project/08_submission/manuscript/title_page.md --output project/08_submission/bundle/title_page.docx --style-config project/08_submission/docx_style.json
.\.venv\Scripts\python.exe tools/manuscript/build_docx.py build --kind cover_letter --input project/08_submission/cover_letter.md --output project/08_submission/bundle/cover_letter.docx --style-config project/08_submission/docx_style.json
```
   These `project/...` arguments are logical paths and the builder maps them to the paper shown
   by `wf status`. A manifest item's `source` must likewise name the matching
   `08_submission/manuscript/...` file, so the visible-text baseline binds the DOCX to the
   journal copy that was actually submitted. Every successful build also writes a deterministic
   source/output receipt under `08_submission/build_receipts/`; S23 refuses to capture a
   baseline without it. The receipt is evidence, not an upload item, and is frozen with S24.
   The builder applies `target_journal.json` on a temporary render copy (sources are never
   rewritten): automatic page numbers in every footer, references as `1. Author...` (number,
   period, one space; no TAB, no hanging indent unless the journal requires
   `"reference_separator": "tab"`), numeric citations collapsed to ranges, `legend_style`, `embed_figures`,
   `word_tables`. Main-text Figure legends hold main figures only; the supplementary build
   appends the Figure S* legends from `legends.md`, an information page (title, journal,
   authors, corresponding author) and strips engine plumbing and local paths from code.
   If supplementary Methods exists, build it (or the journal-mandated combined supplement)
   as `.docx`; when `si_format` is `pdf` (the default) add `--pdf` and list the PDF in the
   manifest with role `supplementary_pdf`. Convert every other narrative upload to `.docx`; do not leave cover letters,
   methods supplements or declarations as Markdown in the bundle. A journal-supplied fixed
   form may remain in the exact PDF/XLSX/DOCX format the journal requires.
4. The builder applies journal-specified size and spacing, with the recorded fallback only
   where the guide is silent. It forces all text black, removes hyperlinks, uses one
   font family throughout, and maps Markdown section headings to the Normal-based
   `SectionHeading` paragraph style. Across every Word XML part it removes `outlineLvl`,
   `keepNext`, `keepLines` and `pageBreakBefore`; visible headings therefore have neither a
   collapsible hierarchy marker nor the left-side black-square control indicator.
   It also converts Shift+Enter/text-wrapping controls to ordinary paragraphs and rejects the
   literal down-arrow character. Use blank lines for paragraph boundaries in Markdown and
   natural wrapping within paragraphs; never pad layout with manual line breaks.
5. Confirm manuscript order: Abstract then Keywords; explicit References heading before
   the bibliography; concise Figure legends as the final section. There must be exactly one
   `Figure legends` section title, exactly one heading per figure, and the legend body must
   not repeat `Figure N` immediately after its heading. Build separate figure
   legend Word files only when the journal explicitly asks, but the legends always remain
   in the manuscript.
6. Add figures and tables in the exact editable/separate forms required by the journal.
   Never omit the supplementary file. Supplementary Methods must contain prose only and no
   Markdown horizontal rules. Put every supplementary table in the separate three-line
   workbook under `04_tables/supplementary/` and list that workbook as a table upload; the
   supplementary-Methods DOCX audit rejects embedded Word tables. Write `manifest.json`;
   every bundle file is listed with its role and the guideline rule that requires it. The
   checklist is **measured, never hand-written**: after every (re)build run
```
.\.venv\Scripts\python.exe tools/manuscript/submission_qc.py write
```
   which writes `SUBMISSION_CHECKLIST.md` and the measured block of `submission_qc.md` (page
   numbers, reference format, legends, declarations order, word/reference/display caps,
   abbreviations, backstage language, SI format). `submission_checklist_measured` regenerates
   it and fails on any FAIL row or stale/hand-edited file - the same list S25 confirms.
7. Run the structural Word audit:
```
.\.venv\Scripts\python.exe tools/manuscript/build_docx.py audit --manifest project/08_submission/bundle/manifest.json --style-config project/08_submission/docx_style.json
```
8. **The consolidated visual pass. This is where every deferred look comes due.**
   `wf status` lists what is parked; the `visual_debts_cleared` gate is non-overridable.

   a. Figures, in one image load rather than one per figure:
```
.\.venv\Scripts\python.exe tools/figures/qc.py --contact-sheet
```
   Then `read_file project/05_figures/qc/contact_sheet.png`. Judge what code cannot: colour
   semantics and colour-blind safety, greyscale legibility, legend placement over data,
   clutter and visual hierarchy, significance-bracket placement, leftover explanatory text,
   overall aliasing. Crop in at full resolution only where the sheet raises a doubt:
```
.\.venv\Scripts\python.exe tools/figures/qc.py --crop "Figure 1" --cols 2 --cell B
```
   Fix the plotting **script** - if it is frozen or certified by an earlier round, first open
   `tools/rework.py layout --source <script> --why "..."` (edits outside a round are refused) -
   re-render, re-run `qc.py --all`, look again. Record each
   figure you actually loaded, then lift the parked decision:
```
.\.venv\Scripts\python.exe tools/figures/qc.py --confirm "Figure 1" --note "<what you saw / changed>"
.\.venv\Scripts\python.exe tools/wf.py decide figures_visually_confirmed YES --why "<per figure: what you saw>"
```
   b. Tables: inspect the rendered worksheets and the built table upload files, then
   `.\.venv\Scripts\python.exe tools/wf.py decide tables_visually_confirmed YES --why "..."`.

   c. Render every final DOCX with Microsoft Word or the document workflow and inspect
   the title/abstract, heading transitions, first/last pages, references, figure legends,
   tables, symbols, page breaks and missing glyphs. Fix the source or builder and rebuild
   only affected files.

   A re-render invalidates its own confirmation: `--confirm` is bound to the PNG mtime and
   refuses a stale report. Never confirm a figure you did not load.
9. After visual corrections are complete and the manifest and all DOCX files are final, bind
   their visible text to this legitimate S23 build:
```
.\.venv\Scripts\python.exe tools/package_content.py capture
```
   When S23 is being rerun after a source-routed correction, use `--replace`. Capture is refused
   outside S23. This baseline permits later Word layout edits while detecting any direct text
   edit or an upstream source change that was not rebuilt.
10. Write `submission_qc.md` with `Rendered files inspected`, `Citation and cross-reference
   checks`, `Typography and hyperlinks`, `Tables and figures`, `Defects resolved` (your visual
   findings; the measured block is maintained by `submission_qc.py write`). Plans and working
   notes go in `08_submission/notes/`, never loose in `08_submission/`. Record
   `submission_files_visually_confirmed YES`, then clean temporary/orphaned files.
11. Only if `target_journal.json` sets `journal_requires_checklist` (or the study is a
   meta-analysis: PRISMA), write `project/08_submission/reporting_checklist.md` as a
   submission file; otherwise skip this step - the gate passes as not required. One
   block per required guideline, every item of
   `reference/reporting_guidelines.toml` exactly once (`STROBE + RECORD`: either a separate
   `Guideline: RECORD` block, or one `Guideline: STROBE + RECORD` block whose Item cells are
   prefixed, e.g. `STROBE 7`, `RECORD 7.1`):
```markdown
# Reporting checklist

Guideline: STROBE
Manuscript: 08_submission/manuscript/full_manuscript.md

| Item | Status | Location | Evidence | Reason |
|---|---|---|---|---|
| 1a | Reported | Title; Abstract | A retrospective cohort study of 1,204 adults | |
| 12e | Reported | Supplementary Methods > Sensitivity analyses | We repeated the primary model after excluding deaths within 30 days | |
| 14c | Not applicable | | | Cross-sectional design; there is no follow-up time to summarise. |
| 22 | Reported | Title page; Statements > Funding | This study received no specific funding | |
```
   Status is `Reported` or `Not applicable` (with a reason of >= 20 characters). A location is
   one or more `;`-separated tokens: a heading of the variant's `full_manuscript.md`, `Title`,
   `<document> > <heading>` (`Supplementary Methods`, `Title page`, `Statements`), or a bare
   document name. Evidence is the sentence that actually reports the item, copied verbatim
   (>= 25 characters) from inside that location; the gate finds it there after normalising
   whitespace, case and emphasis markup. A quote reused for more than 3 items is refused - it
   cannot be specific to each. A heading is not evidence: if no sentence reports the item, fix
   the manuscript or justify Not applicable. `reporting_checklist_complete` (non-overridable)
   resolves every token and quote; a "Reported" row pointing at text that does not exist is a
   fabricated compliance claim. The
   `check-reporting` skill may assist read-only. `analysis_reproduces` is re-checked here too,
   so the package is never built on numbers that no longer re-execute.

## Outputs
- `08_submission/cover_letter.md`
- `08_submission/bundle/SUBMISSION_CHECKLIST.md`
- `08_submission/bundle/manifest.json`
- `08_submission/package_content_baseline.json`
- `08_submission/submission_qc.md`
- `08_submission/reporting_checklist.md` (only when required, step 11)
- the journal-required Word, figure, table and supplementary upload files

## Hard rules
- Pipeline-authored bundle-facing narrative files are DOCX, never Markdown; journal-supplied
  fixed forms retain their mandated non-Markdown format.
- All text is black; no external hyperlinks; no Aptos/theme-font leakage when the selected
  font is Times New Roman; no outline numbering, `outlineLvl`, `keepNext`, `keepLines`,
  `pageBreakBefore`, paragraph-border residue or collapsible heading level in any Word XML.
- `References` and `Figure legends` must be visible in the manuscript.
- Any title-page reference count must equal the distinct citations actually used in the
  canonical manuscript; both the Markdown source and generated Word title page are checked.
- Figure legends only identify and decode the display; they do not restate result direction
  or numerical findings. Crowded abbreviation lists appear once under `Declarations and
  Statements > Abbreviations`, unless an explicitly sourced journal rule requires them local.
- Never invent reviewer contact information or an AI-use disclosure.
- Do not infer final user approval from this build/QA stage. Present the complete package at
  S24 and preserve any user edits made there.
- Never recapture the visible-text baseline merely to accept a content edit made directly in
  Word. Route content changes to their source; use the baseline only to permit format-only edits.

## Close
```
.\.venv\Scripts\python.exe tools/wf.py check
.\.venv\Scripts\python.exe tools/wf.py advance --note "submission package built and visually verified; Word typography/link/heading audit passed; ready for user package review"
```

