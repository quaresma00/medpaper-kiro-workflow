# S10 - Build the tables

Goal: three-line xlsx tables generated from results JSON by code, never retyped.
Details (write_table example, layout rules, manifest JSON): `reference/stage_details/S10_tables.md`
and `reference/table-standards.md`.

## Do
1. `04_tables/code/build_tables.py` reads `03_analysis/results/*.json` and the plan and writes
   every table with `tables.threeline.write_table()` / `write_workbook()` (supplementary tables:
   one workbook, one sheet per table). Table 1 statistics come from S05
   (`reference/language_policy.toml`); if one must be added now, reproduce before leaving S10:
   `.\.venv\Scripts\python.exe tools/reproduce.py run --wait`.
2. Presentation at build: labels from the display dictionary; `threeline.not_estimable()` for
   unbounded estimates; one `threeline.MISSING` symbol defined in the footnote; digits via
   `fmt()/ci()`; separators from the journal profile; units in row labels ("Age, years");
   population/denominator in title or footnote; whole-sentence footnotes ending with a full
   stop; each footnote defines its abbreviations. Diagnostics and merge steps go to a
   supplementary table. Never print Undefined, Not fitted, NA, NaN or Inf.
3. Write `04_tables/manifest.json`, then run and check:
```
.\.venv\Scripts\python.exe tools/wf.py run-script 04_tables/code/build_tables.py
.\.venv\Scripts\python.exe tools/wf.py check
```
4. Visual look: in the default `deferred` mode nothing is recorded here - the look is owed at
   S23 (`wf status` lists it). Only in `inline` mode inspect every sheet now and record
   `.\.venv\Scripts\python.exe tools/wf.py decide tables_visually_confirmed YES --why "<what you saw>"`.
5. Delete scratch from `temp/` (logs belong in `.wf/logs/`).

## Outputs
- `04_tables/code/build_tables.py`
- `04_tables/manifest.json`
- (the xlsx files declared in the plan)

## Gate
three-line structure, plan match, number provenance (Office `~$` lock files ignored; a
locked workbook is reported as an IO problem), clinical labels, presented values, concise
footnotes, engineering language, first-reader check (warning here, blocking at S12).
No table outside the plan (loop to S07).

## Close
```
.\.venv\Scripts\python.exe tools/wf.py advance --note "K main + M supp tables built; all values traced to results JSON"
```
