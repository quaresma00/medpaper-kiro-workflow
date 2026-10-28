# S05 - Method scan + exploratory analysis (NO FIGURES)

Goal: find what the data says with accepted methods and dump every number to disk.
Loopable: iterate here until the analysis converges.
Details (code templates, R/Python split, sandbox rules): `reference/stage_details/S05_analysis.md`.

## Do
1. Method scan: >= 5 formal queries through the client, then write `03_analysis/method_scan.md`
   (method, papers using it `[@key]`, fit to our data):
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
   update `03_analysis/notes.md`; delete abandoned scripts and result JSONs.

## Outputs
- `03_analysis/method_scan.md`
- `03_analysis/analysis_log.md`
- (scripts in `03_analysis/code/`, results in `03_analysis/results/`)

## Gate
>= 5 recorded queries, notes populated, environment receipts, scripts scoped, no plot calls
(Python or R; figures are S11), temp clean. The primary analysis does not change silently -
a change is logged in `.wf/protocol_changes.md` at S06 (internal, never in the paper).

## Close
```
.\.venv\Scripts\python.exe tools/wf.py check
.\.venv\Scripts\python.exe tools/wf.py advance --note "primary result: <effect, CI, p>; K result files; open: <...>"
```
Iterate later from downstream: `.\.venv\Scripts\python.exe tools/wf.py loop --to S05_analysis --why "..."`
