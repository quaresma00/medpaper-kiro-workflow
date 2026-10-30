# S05 - Method scan + exploratory analysis (NO FIGURES)

Goal: find what the data says with accepted methods and dump every number to disk.
Loopable: iterate here until the analysis converges.
Details (code templates, R/Python split, sandbox rules): `reference/stage_details/S05_analysis.md`.

## Do
1. Method scan: the formal queries the design needs (no minimum count; judged by the
   methods it covers), then write `03_analysis/method_scan.md` (method, papers using it
   `[@key]`, fit to our data):
```
.\.venv\Scripts\python.exe tools/pubmed/client.py search --query "<design> <outcome> statistical analysis" --retmax 100
.\.venv\Scripts\python.exe tools/pubmed/client.py fetch --ids <...> --with-abstract
```
2. Analyse in top-level scripts `03_analysis/code/01_*.py|R`, `02_*` ... (helpers in
   `code/lib/`), language per `reference/language_policy.toml`. They run from raw data without
   arguments, rebuild `02_data/derived/`, seed every random step (`set_seed`/`medpaper_seed`),
   never read `00_input/` or `01_protocol/`, no absolute paths. Run each with
   `.\.venv\Scripts\python.exe tools/wf.py run-script 03_analysis/code/<script>`.
3. Every number the paper will ever show goes through `write_results()` into
   `03_analysis/results/<name>.json` (environment receipt added). Baseline tables: count every
   level of each categorical variable overall and per group (`baseline_counts()`).
4. Plan all analysis edits of a round together, then run the chain once (not per edit).
5. Keep `03_analysis/analysis_log.md` (what ran, what came out, next decision, dead ends) and
   update `03_analysis/notes.md`. Stop when the primary and secondary outcomes and the
   validity checks of the protocol's statistical reporting plan are done; an extra analysis
   gets `"role": "additional"` and one line `"decision"` (which scientific decision it could
   change) in `03_analysis/analysis_manifest.json`. Valid negative or contradictory results
   stay. Superseded or erroneous files are retired, not deleted:
   `.\.venv\Scripts\python.exe tools/retire_result.py --file <path> --why "<reason>"`.
   Internal diagnostic plots may go to `03_analysis/diagnostics/` (never submission figures).

## Outputs
- `03_analysis/method_scan.md`
- `03_analysis/analysis_log.md`
- (scripts in `03_analysis/code/`, results in `03_analysis/results/`)

## Gate
A recorded search, notes populated, environment receipts, scripts scoped, no plot calls in
`03_analysis/code/` (figures are S11), additional analyses justified, temp clean. The primary analysis does not change silently -
a change is logged in `.wf/protocol_changes.md` at S06 (internal, never in the paper).

## Close
```
.\.venv\Scripts\python.exe tools/wf.py check
.\.venv\Scripts\python.exe tools/wf.py advance --note "primary result: <effect, CI, p>; K result files; open: <...>"
```
Iterate later from downstream: `.\.venv\Scripts\python.exe tools/wf.py loop --to S05_analysis --why "..."`
