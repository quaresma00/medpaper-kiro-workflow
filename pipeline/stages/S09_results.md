# S09 - Results

## Purpose
Write the Results from the final tables and figures (1.10.0: S09 runs after S10/S11;
`displays_final_for_results`). S12 then only cross-checks.
Details (science review, hard rules): `reference/stage_details/S09_results.md`.

## Inputs
- the rendered tables (`04_tables/`) and figures (`05_figures/out/`) - write from these
- `01_protocol/artifact_plan.json` - the display items and what each one shows
- `03_analysis/results/*.json` - every number
- `05_figures/legends.md`, `04_tables/table_captions.md` - so the prose does not repeat them

## Procedure
0. 1.14.0: ONE look at all final tables and figures (one image); fix what you see first,
   record it once (all other visual checks stay at S23):
```
.\.venv\Scripts\python.exe tools/figures/qc.py --contact-sheet --with-tables
.\.venv\Scripts\python.exe tools/wf.py decide displays_seen_before_results YES --why "<what you saw; what you fixed>"
```
   1.20.0, in the same pass: `wf displays text` lists table/figure strings that read like an
   analysis report; delegate `.wf/writer_bundle/displays/MANIFEST.md` to the
   `medpaper-clinical-writer` (answer in `.wf/writer/display_wording.md`), `wf displays apply`,
   apply the listed wording, re-render, repeat until clean (`display_text_resolved`).
   1.23.0, still before writing: the independent science review (`medpaper-reviewer`, science
   mode); revise analyses, displays and Methods; ONE Chinese summary and ONE question (another
   round, or proceed); record the answer (details):
```
.\.venv\Scripts\python.exe tools/review_round.py start --scope science
```
1. Order the Results the way the artifact plan is ordered: cohort/flow, baseline
   characteristics, primary analysis, secondary analyses, sensitivity analyses.
   1.12.0: build the writer bundle (results rendered as sentences with clinical labels, table
   text, legends - no code, JSON keys or logs) and delegate the prose to the
   `medpaper-clinical-writer` agent with the printed MANIFEST path:
```
.\.venv\Scripts\python.exe tools/manuscript/writer_bundle.py build --stage S09_results
```
   Build exits 2 while a result lacks a clinical label or CI level (`S09_results_GAPS.md`);
   fix the dictionary or results first, never let the writer guess.
2. `project/07_manuscript/results.md`: every display item in the plan cited at least once, in
   order, as `(Figure 1)`, `(Table 2)`, `(Figure S1)`, `(Table S1)` (the gate rejects
   citations to items not in the plan, and items never cited). Effects: estimate, CI
   (recorded level), then P - never a bare P; values exactly as in the result JSONs. No
   interpretation, no row-by-row restating.
3. 1.23.0: right after the draft, `writer_bundle.py receipt --stage S09_results`, then the
   `medpaper-medical-editor` polishes it (`writer_bundle.py edit --section results`, then
   `polished --section results`; `section_polished`). Lint:
```
.\.venv\Scripts\python.exe tools/text/polish.py lint --file 07_manuscript/results.md
```

## Outputs
- `07_manuscript/results.md`

## Hard rules (full list in details)
ONE section file; continuous paragraphs; every number traceable to results JSON in its own
context; citations match `artifact_plan.json`; no claim about a result you did not compute.
1.24.0: a non-significant result is estimate + CI + plain words, never 'trend toward significance' (`reference/writing_voice.md`).

## Close
```
.\.venv\Scripts\python.exe tools/wf.py check
.\.venv\Scripts\python.exe tools/wf.py advance --note "results drafted; primary: <estimate, CI, p>; all <n> display items cited"
```
