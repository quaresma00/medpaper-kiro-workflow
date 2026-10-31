# S23 - Build and visually verify the submission package

Goal: the journal-required files, as Word, from the journal variant; plus the one
consolidated visual pass (every look deferred at S10/S11 comes due here).
Details (builder, manifest roles, checklist format, portal to-do): `reference/stage_details/S23_package.md`.

## Do
1. `08_submission/cover_letter.md`; item list from `guidelines_extract.md` only. Sync any
   title-page reference count:
   `.\.venv\Scripts\python.exe tools/manuscript/reference_count.py sync`
2. Build every prose upload once from `08_submission/manuscript/` (never `07_manuscript/`):
```
.\.venv\Scripts\python.exe tools/manuscript/build_docx.py build --kind manuscript --input project/08_submission/manuscript/full_manuscript.md --output project/08_submission/bundle/manuscript.docx --style-config project/08_submission/docx_style.json --bibliography project/06_refs/refs.bib --csl <journal.csl> --wait
.\.venv\Scripts\python.exe tools/manuscript/build_docx.py build --kind title_page --input project/08_submission/manuscript/title_page.md --output project/08_submission/bundle/title_page.docx --style-config project/08_submission/docx_style.json
```
   Same for the cover letter. Supplementary Methods: `--kind supplementary --esm-number <n>
   --pdf` (header "Online Resource n"). Supplementary figures PDF and workbook info sheet:
   `tools/supplementary.py figures --number <n> --output ...` / `xlsx --input ... --number
   <n> --output ...`. No black squares (zero keep markers). Keep any helper script you need
   later in `.wf/scripts/` - never in `temp/` (`wf clean` empties it).
3. Write `08_submission/bundle/manifest.json` (every upload, role, rule). Main figure TIFFs
   and table workbooks are added automatically when the journal wants separate files.
   From now on ONE command rebuilds what an edit affects and re-measures (audit,
   `submission_qc.md` - fully generated -, capture, polish lint):
```
.\.venv\Scripts\python.exe tools/wf.py rebuild --wait
```
4. Consolidated visual pass (`wf status` lists what is owed):
```
.\.venv\Scripts\python.exe tools/figures/qc.py --contact-sheet
```
   Load `05_figures/qc/contact_sheet.png` (crop where in doubt: `qc.py --crop`); fix scripts
   inside a rework round, re-render, `qc.py --all`. Then record what you saw:
```
.\.venv\Scripts\python.exe tools/figures/qc.py --confirm "Figure 1" --note "<what you saw / changed>"
.\.venv\Scripts\python.exe tools/wf.py decide figures_visually_confirmed YES --why "<per figure: what you saw>"
.\.venv\Scripts\python.exe tools/wf.py decide tables_visually_confirmed YES --why "<sheets and upload tables inspected>"
```
   Render each DOCX (`tools/manuscript/preview.py 08_submission/bundle/manuscript.docx`) and
   inspect pages; then record `submission_files_visually_confirmed YES`.
5. `08_submission/reporting_checklist.md` only if `journal_requires_checklist` is set (or
   PRISMA for a meta-analysis); it is numbered after the content supplementary files.

## Outputs
- `08_submission/cover_letter.md`
- `08_submission/bundle/SUBMISSION_CHECKLIST.md`
- `08_submission/bundle/manifest.json`
- `08_submission/package_content_baseline.json`
- `08_submission/submission_qc.md`

## Gate
bundle complete, DOCX bundle ready, measured checklist (WARN never blocks), package
baseline, visual debts cleared, reporting checklist, analysis reproduces, no orphans. Never
recapture the baseline to accept a Word content edit.

## Close
```
.\.venv\Scripts\python.exe tools/wf.py check
.\.venv\Scripts\python.exe tools/wf.py advance --note "submission package built and visually verified; Word typography/link/heading audit passed; ready for user package review"
```
