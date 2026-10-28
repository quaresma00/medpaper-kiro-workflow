# S06 - Final protocol + go/no-go #2

Goal: reconcile plan and practice, prove the analysis re-executes, re-judge publishability.
Details (sandbox, manifest, tolerances, spot-check script): `reference/stage_details/S06_protocol_final.md`.

## Do
1. `01_protocol/protocol_final.md`: the v1 headings, updated to the analysis actually
   performed; keep the `Statistical reporting plan` and `Design precedent` lines up to date.
   Changes of plan go to the internal log `.wf/protocol_changes.md` (one line each: what and
   why). It is never exported, never given to the writer or reviewer, and the manuscript
   never narrates an initial plan or protocol deviations (registered meta-analysis: PRISMA
   2020 item 24c only).
2. Converged?
```
.\.venv\Scripts\python.exe tools/wf.py decide analysis_converged YES --why "<what was the last analysis, why nothing further would change the conclusion>"
```
   If not: `.\.venv\Scripts\python.exe tools/wf.py loop --to S05_analysis --why "..."`.
3. Reproduce ONCE (one blocking call with a heartbeat; give the shell tool >= 1800 s and
   never kill it; sandbox inside the paper, data read in place, never copied):
```
.\.venv\Scripts\python.exe tools/reproduce.py run --wait
```
   Later stages accept this proof by hash. Never run it again "to be safe": `wf check` says
   whether the proof is valid and the cheapest next command (only analysis code, data,
   manifest or tolerance changes re-run the affected scripts). A mismatch names the file and
   JSON path: seed the script, or declare a justified floating-point tolerance (<= 1e-6,
   never counts) in `03_analysis/reproducibility.toml`.
4. Raw spot check: a script in `03_analysis/spot_check/` draws 10 reproducible subjects
   (`tools/analysis/spotcheck.py` `sample_ids`), recomputes key variables from the raw source
   (declared data source or `02_data/raw/`) and calls `write_spot_check`; fix mismatches at
   S04/S05 or explain them.
5. Decide the provisional target journal or journal type (S07 records its parameters).
6. Re-judge against the real result (interpretable? adequately powered if null? robust?):
```
.\.venv\Scripts\python.exe tools/wf.py decide go_nogo_2 GO --why "<the finding, its precision, why a journal takes it, which journal tier is realistic>"
```

## Ask the user
A `STOP` is a real outcome: report it with the reasoning; never soften a dead result.

## Outputs
- `01_protocol/protocol_final.md`
- `03_analysis/reproducibility_report.json`

## Gate
analysis_reproduces and results_have_environment (non-overridable), data not copied, raw
spot check, design precedent, reporting plan, decisions recorded. No retro-fitting.

## Close
```
.\.venv\Scripts\python.exe tools/wf.py check
.\.venv\Scripts\python.exe tools/wf.py advance --note "protocol final; go_nogo_2=<...>; realistic tier=<...>"
```
