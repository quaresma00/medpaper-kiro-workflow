# S04 - Acquire data, codebook, provenance - details

> Long form of `pipeline/stages/S04_data.md` (moved out of the card in 1.12.0 so the
> card stays short). Read only the section you need; the card has the commands.
>
> 1.12.0 supersedes older wording below where they differ: long runs use `--wait` (one
> blocking call, heartbeat <= 30 s) and logs live in `.wf/logs/` (or `temp/logs/`);
> `wf check` prints failures + one summary line by default; in `deferred` visual mode no
> DEFER decision is recorded (the look is owed at S23); the `medpaper-reviewer` agent
> writes only its own `report.md` in the review bundle; declaration and section heading
> names come from `target_journal.json` (defaults otherwise).

> 1.13.0: a dataset the user already has is never copied into the paper. Register it in
> place (`wf data add <absolute path> --name <name>`; `.wf/data_sources.json`, hashes cached
> by size + mtime), read it with `analysis.datasources.source_path()` / `open_member()` (R:
> `tools/R/medsources.R`), and point evidence at `datasource:<name>/<file>` (archives:
> `zip_member_rows` / `zip_member_lines` stream one member). Only downloaded payloads live in
> `02_data/raw/`. `data_not_copied` fails on a copy or hard link of a declared dataset;
> copying more than `data_copy_limit_mb` (200 MB) of input data is refused by the engine.

## Purpose
Get the real data in place with an auditable trail, and describe it before analysing it.

## Procedure
1. Execute the full retrieval from `02_data/acquisition_plan.md`. Retrieval scripts and exact
   queries live under `project/02_data/acquisition/`; raw payloads and source count/page
   receipts land in `project/02_data/raw/` and are then treated as read-only. Never edit a
   raw file. Here and throughout the cards, `project/` is a logical name for the paper folder
   printed by `wf status`; the engine never holds paper files.
   - Language: acquisition, API clients and cleaning are Python
     (`reference/language_policy.toml`). Save raw API bodies verbatim (never via `toJSON()`/
     `write_json()` or a re-serialising writer).
   - Every acquisition script must resolve that root explicitly:
```python
from wfcore.paths import project_dir
PROJECT = project_dir()
# write only below PROJECT / "02_data" / ...
```
     Run it through `python tools/wf.py run-script 02_data/acquisition/<script>.py`. The wrapper
     exports `MEDPAPER_PROJECT` and fails rather than letting a relative `Path("project")` pollute
     the shared engine.
   - Request the source-reported total first, then acquire every record in the
     protocol-defined universe. Exhaust all pages/cursors and retain the terminal response.
   - Never introduce a convenience cap such as SQL `LIMIT`/`TOP`, `head()`, `sample()`,
     a literal first-N slice, `nrows`, a fixed maximum page count, or a narrower date range.
     A page size is not a cap only when the code continues to the terminal page.
   - A pilot is allowed only to test connectivity/schema. Mark the relevant code line
     `MEDPAPER_PILOT_ONLY`, exclude pilot output from analysis, and complete the full fetch.
     Protocol-defined scientific sampling must already exist in S03 and is marked
     `MEDPAPER_PROTOCOL_SAMPLING`; it also requires the user's recorded
     `protocol_sampling_authorized=YES` decision. Neither marker can excuse incomplete
     acquisition of the approved universe.
2. Any cleaning, recoding, post-acquisition eligibility exclusion or merging happens in a
   script under `03_analysis/code/`
   that writes to `02_data/derived/`. No manual spreadsheet edits.
3. Write `project/02_data/provenance.md`: where each raw file came from, the URL or
   query, the retrieval timestamp, the release/version, the file hash, the licence, and
   who is allowed to see it.
4. Generate the codebook. For every variable: role, type, units, level meanings,
   range or quantiles, and missingness. If a coded variable's level meanings are unknown,
   mark it `[NEEDS DICTIONARY]` - do not infer what `2` means.
   Write it to `project/02_data/codebook.md`.
5. Create the machine-verifiable acquisition proof:
```powershell
.\.venv\Scripts\python.exe tools\data_manifest.py init
# Fill the protocol population, source entries, count evidence, pagination and reconciliation.
.\.venv\Scripts\python.exe tools\data_manifest.py sync
```
   Write `project/02_data/acquisition_manifest.json` using the generated template. For every
   source it must bind these facts to raw, hashed receipts:
   - exact locator/query/release and timezone-aware retrieval time;
   - `source_total_expected`, `records_requested`, and `records_received`;
   - machine-countable total evidence and received-payload evidence;
   - pagination applicability, pages received, terminal-page status, and empty final cursor;
   - `complete: true` and `truncation_applied: false`.

   `requested_scope` is always `full_protocol_defined_universe`: this means the whole set
   defined at S03, including the whole pre-specified sample when sampling is the actual study
   design. It does not mean "all records on earth" and does not permit a convenience subset.

   If the source itself blocks part of that universe, preserve machine-readable evidence of
   the external restriction and first ask the user. Only an explicit user response may be
   recorded as:
```powershell
.\.venv\Scripts\python.exe tools\wf.py decide partial_data_authorized YES --why "<what the source blocks, what remains available, and the scientific consequence>"
```
   Then use status `source_limited_user_authorized` and still acquire the entire accessible
   subset. Time, tokens, context, download size, compute or convenience are not source limits.
6. Dump the machine-readable summary from executed code: `03_analysis/code/00_dataset_summary.py`
   (or `.R`) calls `write_results("dataset_summary", {...})` and is run with
   `python tools/wf.py run-script 03_analysis/code/00_dataset_summary.py`. It is re-run in the
   S06 sandbox from `02_data/raw/`, so its counts are re-proved like any other result. The
   writer adds the `environment` receipt (script, sha256, packages, written_at):
```python
from analysis.results import write_results
write_results("dataset_summary", {
  "n_rows": 0, "n_cols": 0,
  "variables": [{"name": "", "role": "", "type": "", "missing_pct": 0.0}],
  "missingness": {"any_missing_rows_pct": 0.0},
  "study_period": {"start": None, "end": None},
  "source_hash": "exact raw_bundle_sha256 printed by tools/data_manifest.py sync",
  "acquisition_scope": "full_protocol_defined_universe",
  "acquisition_status": "complete",
})
```
   Only a summary that truly needs the network may be written from `02_data/acquisition/`
   (the one carve-out: `write_results` there accepts only `dataset_summary`).
   Include the study period here even if it is just calendar years: every number that
   later appears in the manuscript must exist in a results JSON, dates included.
   Reconcile its `n_rows` against records received and explicit post-acquisition exclusions
   in `acquisition_manifest.json`. Complex joins require a substantive reconciliation note.
7. Run the standalone verifier, then delete scratch files from `project/temp/`:
```powershell
.\.venv\Scripts\python.exe tools\data_manifest.py verify
```

## Outputs
- `02_data/acquisition_manifest.json`
- `02_data/codebook.md`
- `02_data/provenance.md`
- `03_analysis/results/dataset_summary.json`

## Hard rules
- 1.10.0 `variable_crosswalk_confirmed`: before analysis write `02_data/variable_crosswalk.json` - `analysis_variables` plus one row per variable (`variable`, `source_field`, `definition`, `unit`, `coding`, `time_window`, `missing_rule`, `basis` = codebook/doc location) and `confirmed: true` only after checking that row against the source documentation. Full extraction guards quantity; this guards definitions.
- If the data contains identifiers, de-identify before any of it reaches a prompt, and
  record what was removed in `provenance.md`.
- Do not analyze a pilot, partial page set, convenience sample, preview export or silently
  narrowed query as if it were the complete dataset.
- The data-completeness gate re-counts raw evidence, verifies file hashes and pagination,
  scans acquisition code for common caps, and is not waivable with `--force`.
- No plotting in this stage.
- Never hand-type a count into the codebook; read it from the summary JSON.

## Close
```
.\.venv\Scripts\python.exe tools/wf.py check
.\.venv\Scripts\python.exe tools/wf.py advance --note "n=<rows>x<cols>; source=<x>; blockers=<missingness/dictionary gaps>"
```
