# S06 - Final protocol + go/no-go #2

## Purpose
Reconcile what was planned with what was done, then re-judge publishability now that
the effect size and the data's limits are known. This is the last cheap exit.

## Procedure
1. Write `project/01_protocol/protocol_final.md` - same headings as v1 plus
   `Deviations from protocol v1`. The deviations section is the important one:
   for each change, state what changed, why, and whether the change was driven by the
   data (which weakens it) or by a method-scan finding (which strengthens it).
2. Write `project/01_protocol/protocol_diff.md` - a plain list of v1 -> final changes,
   one line each. This becomes the honest basis for any "pre-specified" claim in Methods.
3. Confirm the analysis is finished:
```
.\.venv\Scripts\python.exe tools/wf.py decide analysis_converged YES --why "<what was the last analysis, why nothing further would change the conclusion>"
```
   If it is not converged: `.\.venv\Scripts\python.exe tools/wf.py loop --to S05_analysis --why "..."`.
   Then prove the analysis re-executes. Do not run other work on the paper meanwhile (only
   `temp/` and `.kiro/` writes are tolerated):
```
.\.venv\Scripts\python.exe tools/reproduce.py run
```
   It copies `02_data/` (except `derived/`, which is rebuilt) and `03_analysis/code/` into a
   sandbox, re-runs every top-level analysis script in the order declared by
   `03_analysis/analysis_manifest.json` (`{"schema": 1, "scripts": [{"path", "inputs",
   "outputs", "after"}]}`, every top-level script listed once; without it, filename order with
   a warning) and compares every results JSON (timestamps ignored). After a passing proof,
   `reproduce.py run --affected-only` re-runs only the scripts the changed inputs reach through
   the dependency closure and carries the rest from that proof (a data change re-runs all). `00_input/` and `01_protocol/` are not available there,
   absolute paths are forbidden, and acquisition is never re-run (only an acquisition-written
   `dataset_summary.json` is carried over). A mismatch names the file and JSON path: make the
   script deterministic (seed it), or, for genuine floating-point reduction noise only, declare
   a justified tolerance (<= 1e-6, never for counts) in `03_analysis/reproducibility.toml`.
   The re-run outputs are kept in `.wf/repro/rerun/` as the gate's evidence - never edit them.
   Any later edit to `03_analysis/code/**`, `02_data/` (outside `derived/`), a results file or
   the tolerance file invalidates the proof; `analysis_reproduces` re-checks it at S17, S23 and
   S25.
4. Re-judge publishability against the real result, not the hoped-for one:
   - Is the primary result interpretable (direction, magnitude, precision)?
   - A null result is publishable if the question mattered and the study was adequately
     powered to answer it. Say which of those two conditions holds.
   - Does the finding survive the sensitivity analyses?
   - Has the gap from S02 changed now that you know the effect size?
```
.\.venv\Scripts\python.exe tools/wf.py decide go_nogo_2 GO --why "<the finding, its precision, why a journal takes it, which journal tier is realistic>"
```

The `Reporting guideline` section must hold one `Guideline: <name>` line per applicable
guideline (e.g. `Guideline: STROBE`, or `Guideline: STROBE + RECORD` for a database study;
mapping in S03); that line is what `reporting_checklist_complete` reads at S23. A warning here means the guideline is not registered in
`reference/reporting_guidelines.toml` or its item list is not shipped yet - fix that in the
engine workspace now, not at S23.

## Outputs
- `01_protocol/protocol_final.md`
- `01_protocol/protocol_diff.md`
- `03_analysis/reproducibility_report.json`

## Hard rules
- Do not retro-fit the protocol to make the result look pre-specified. The diff file
  exists so that this is impossible to do accidentally.
- A `STOP` here is a real outcome. Report it to the user with the reasoning; do not
  soften a dead result into a "hypothesis-generating" paper without saying so.

## Close
```
.\.venv\Scripts\python.exe tools/wf.py check
.\.venv\Scripts\python.exe tools/wf.py advance --note "protocol final; K deviations; go_nogo_2=<...>; realistic tier=<...>"
```
