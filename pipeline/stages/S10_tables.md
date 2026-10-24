# S10 - Build the tables

## Purpose
Render the planned tables as three-line xlsx files a reader and a reviewer can use.
Generated from result JSONs by code, never retyped.

## Procedure
1. Write `project/04_tables/code/build_tables.py` (Python writes the xlsx; run it with
   `wf run-script 04_tables/code/build_tables.py`, which puts `tools/` on `PYTHONPATH`). It
   reads `03_analysis/results/*.json` and `01_protocol/artifact_plan.json`, and writes every
   table with the shared helper so formatting cannot drift. Table 1 statistics are computed
   in `03_analysis/code/` at S05 (R per `reference/language_policy.toml`: tableone/gtsummary
   via `write_results()`). If one must be added now, run
   `.\.venv\Scripts\python.exe tools/reproduce.py run --log <paper>/temp/repro.log` in the
   background before leaving S10 (check the log every 2-3 minutes, last lines only; done at
   `REPRODUCE DONE`; no short polling loops); S17 re-checks the proof.

```python
from wfcore.paths import project_dir
from tables.threeline import write_table, write_workbook

PROJECT = project_dir()
write_table(
    path=PROJECT / "04_tables/main/Table1.xlsx",
    sheet="Table 1",
    title="Table 1. Baseline characteristics of the study population.",
    header=["Characteristic", "Group A (n=123)", "Group B (n=456)", "P value"],
    rows=[["Age, years, mean (SD)", "62.1 (11.4)", "61.7 (12.0)", "0.62"]],
    footnotes=[
        "Data are n (%) unless stated otherwise.",
        "Abbreviations: SD, standard deviation; BMI, body mass index.",
        "P values from the two-sided t test for continuous and chi-square for categorical variables.",
    ],
)
```
2. Layout rules (enforced by the `tables_threeline` gate):
   - Row 1 is the title. Unruled.
   - Exactly three horizontal rules: above the header, below the header, below the last
     data row. No vertical rules. No interior horizontal rules.
   - At least one footnote row beneath the bottom rule.
   - Main tables: one xlsx per table.
   - Supplementary tables: **one** xlsx (`04_tables/supplementary/supplementary_tables.xlsx`)
     with one sheet per table, named exactly as the plan's `sheet` value. Use
     `write_workbook()` for this.
3. Write `project/04_tables/manifest.json`:
```json
{"built_at": "", "built_by": "04_tables/code/build_tables.py",
 "tables": [{"id": "Table 1", "file": "04_tables/main/Table1.xlsx", "sheet": "Table 1",
             "n_rows": 0, "source_results": ["03_analysis/results/baseline.json"]}]}
```
4. Run it through the paper-aware wrapper, then verify the structure rather than assuming:
```
.\.venv\Scripts\python.exe tools/wf.py run-script 04_tables/code/build_tables.py
.\.venv\Scripts\python.exe tools/wf.py check
```
   Do not run `python project/04_tables/...` from the engine root: in a multi-paper workspace
   that path is the mother engine, not the selected paper.
5. **Visual inspection - timing depends on `visual_review_mode`** (see the S11 card for why).
   The structural checks above (`tables_threeline`, `tables_match_plan`,
   `numbers_have_provenance`) are code and block here in both modes.

   `inline` - render and visually inspect every worksheet in every generated workbook. Check
   clipping, wrapping, column widths, row heights, title and header hierarchy, footnotes,
   units, decimal precision, missing-value symbols and page usability. It is a QA helper
   only: fix the generating script, regenerate, and inspect the affected workbook again;
   never hand-edit a generated value.

   `deferred` (default) - do not render the workbooks for inspection yet. Table layout is
   re-decided at S23 anyway, where the chosen journal's format is applied and the workbooks
   are rebuilt into the upload files that actually get inspected.
6. Record the gate.

   `inline`, after all workbooks pass visual review:
```
.\.venv\Scripts\python.exe tools/wf.py decide tables_visually_confirmed YES --why "<workbooks/sheets inspected and defects corrected>"
```
   `deferred`:
```
.\.venv\Scripts\python.exe tools/wf.py decide tables_visually_confirmed DEFER --why "three-line structure, plan match and number provenance all pass by code; sheet-level layout inspection deferred to the S23 pass where the journal's table format is applied"
```
7. Delete scratch files from `project/temp/`.

## Outputs
- `04_tables/code/build_tables.py`
- `04_tables/manifest.json`
- (plus the xlsx files declared in the artifact plan)

## Hard rules
- A table is a reader-facing object, not an analysis dump. No model diagnostics, no
  console output, no paragraph-length cells. The gate rejects body cells over 300 characters
  and footnotes over `table_footnote_words_max` words (default 120) in total; write each
  footnote as whole sentences, never split one sentence over rows.
- Every numeric cell must trace to `03_analysis/results/*.json` (gate:
  `numbers_have_provenance source=tables`). Do not retype from the Results prose.
- Titles are self-contained and short. Footnotes carry abbreviations, units and the
  estimation method in one sentence; longer method explanations go to Methods.
- 1.11.0 presentation standard at build: row/column labels from the display dictionary
  (`clinical_labels_used`), `threeline.not_estimable(lower)` for zero-cell/unbounded estimates,
  one missing symbol (`threeline.MISSING`, defined in the footnote), digits via `fmt()/ci()`,
  separators via the journal profile. Never print Undefined, Not fitted, NA, NaN or Inf
  (`display_values_presented`). Model diagnostics, merge/collapse steps and convergence go to
  a supplementary table; content a review asks to add is placed main vs supplementary by you
  on what the reader needs (`table_footnotes_concise`).
- Each footnote defines every abbreviation its table uses; the manuscript keeps a central
  list too (`display_abbreviations_defined`). No engineering language in cells
  (`engineering_language_clean`).
- Do not add a table that is not in the plan. If one is needed, loop to S07.
- Structural checks alone are insufficient; the visual-review decision is mandatory.

## Close
```
.\.venv\Scripts\python.exe tools/wf.py advance --note "K main + M supp tables built; all values traced to results JSON"
```
