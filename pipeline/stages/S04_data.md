# S04 - Acquire data, codebook, provenance

Goal: the complete protocol-defined data, with an auditable trail, described before analysis.
Details (pilot/sampling markers, manifest fields, source-limited path): `reference/stage_details/S04_data.md`.

## Do
1. Run the full retrieval from `02_data/acquisition_plan.md`: scripts in
   `02_data/acquisition/`, raw payloads and count/page receipts in `02_data/raw/` (read-only
   afterwards). Python for acquisition (`reference/language_policy.toml`); save raw bodies
   verbatim; resolve the paper root with `wfcore.paths.project_dir()` and run through
   `.\.venv\Scripts\python.exe tools/wf.py run-script 02_data/acquisition/<script>.py`.
   Request the source total first, exhaust every page/cursor, no convenience cap.
2. Cleaning, recoding, exclusions and merges: scripts in `03_analysis/code/` writing
   `02_data/derived/`; no manual spreadsheet edits.
3. `02_data/provenance.md` (source, query, timestamp, release, hash, licence, who may see it)
   and `02_data/codebook.md` (role, type, units, levels, range, missingness; unknown codes
   `[NEEDS DICTIONARY]`).
4. Acquisition proof:
```powershell
.\.venv\Scripts\python.exe tools\data_manifest.py init
.\.venv\Scripts\python.exe tools\data_manifest.py sync
```
   Fill `02_data/acquisition_manifest.json` (`requested_scope` = `full_protocol_defined_universe`).
   A source that blocks part of the universe: ask the user, then
   `.\.venv\Scripts\python.exe tools\wf.py decide partial_data_authorized YES --why "<...>"`.
5. `03_analysis/code/00_dataset_summary.py` calls `write_results("dataset_summary", {...})`
   (rows, columns, variables, missingness, study period, source hash, scope, status); run it
   with `wf run-script` and reconcile `n_rows` with the manifest.
6. `02_data/variable_crosswalk.json`: one row per analysis variable (source field,
   definition, unit, coding, time window, missing rule, basis) with `confirmed: true` only
   after checking the source documentation.
```powershell
.\.venv\Scripts\python.exe tools\data_manifest.py verify
```

## Outputs
- `02_data/acquisition_manifest.json`
- `02_data/codebook.md`
- `02_data/provenance.md`
- `03_analysis/results/dataset_summary.json`

## Gate
data_acquisition_complete (non-overridable: raw recount, hashes, pagination, cap scan),
variable crosswalk, environment receipts, paper-scoped scripts, temp clean. De-identify
before any data reaches a prompt. No plotting.

## Close
```
.\.venv\Scripts\python.exe tools/wf.py check
.\.venv\Scripts\python.exe tools/wf.py advance --note "n=<rows>x<cols>; source=<x>; blockers=<missingness/dictionary gaps>"
```
