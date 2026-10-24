# S06 - Final protocol + go/no-go #2

Goal: reconcile plan and practice, prove the analysis re-executes, re-judge publishability.
Details (sandbox, manifest, tolerances, spot-check script): `reference/stage_details/S06_protocol_final.md`.

## Do
1. `01_protocol/protocol_final.md`: v1 headings + `Deviations from protocol v1` (what, why,
   data-driven or method-driven); keep the `Statistical reporting plan` and `Design precedent`
   lines up to date. `01_protocol/protocol_diff.md`: one line per change.
2. Converged?
```
.\.venv\Scripts\python.exe tools/wf.py decide analysis_converged YES --why "<what was the last analysis, why nothing further would change the conclusion>"
```
   If not: `.\.venv\Scripts\python.exe tools/wf.py loop --to S05_analysis --why "..."`.
3. Reproduce (one blocking call with a heartbeat; details in `.wf/logs/`; `REUSED` when nothing
   changed; manuscript edits never invalidate it; affected scripts only by default):
```
.\.venv\Scripts\python.exe tools/reproduce.py run --wait
```
   A mismatch names the file and JSON path: seed the script, or declare a justified
   floating-point tolerance (<= 1e-6, never counts) in `03_analysis/reproducibility.toml`.
4. Raw spot check: a script in `03_analysis/spot_check/` draws 10 reproducible subjects
   (`tools/analysis/spotcheck.py` `sample_ids`), recomputes key variables from `02_data/raw/`
   and calls `write_spot_check`; fix mismatches at S04/S05 or explain them.
5. Decide the provisional target journal or journal type (S07 records its parameters).
6. Re-judge against the real result (interpretable? adequately powered if null? robust?):
```
.\.venv\Scripts\python.exe tools/wf.py decide go_nogo_2 GO --why "<the finding, its precision, why a journal takes it, which journal tier is realistic>"
```

## Ask the user
A `STOP` is a real outcome: report it with the reasoning; never soften a dead result.

## Outputs
- `01_protocol/protocol_final.md`
- `01_protocol/protocol_diff.md`
- `03_analysis/reproducibility_report.json`

## Gate
analysis_reproduces and results_have_environment (non-overridable), raw spot check, design
precedent, reporting plan, decisions recorded. No retro-fitting of the protocol.

## Close
```
.\.venv\Scripts\python.exe tools/wf.py check
.\.venv\Scripts\python.exe tools/wf.py advance --note "protocol final; K deviations; go_nogo_2=<...>; realistic tier=<...>"
```
