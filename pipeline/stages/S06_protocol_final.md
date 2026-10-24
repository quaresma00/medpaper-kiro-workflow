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
.\.venv\Scripts\python.exe tools/reproduce.py run --log <paper>/temp/repro.log
```
   Run it in the background (`<paper>` = the paper project folder). Check the log no more
   often than every 2-3 minutes and read only its last few progress lines (`[i/N] start|ok|FAIL
   <script>`); it is finished when a `REPRODUCE DONE rc=N ...` line appears. Never spin short
   polling loops. When the passing proof still matches every script, data file, manifest,
   tolerance, result and engine helper, it ends at once with `REUSED` (typical when only
   presentation changed); `--force` re-runs anyway. After a change it re-runs only the
   affected scripts by default; `--full` re-runs all.
   It copies `02_data/` (except `derived/`, which is rebuilt) and `03_analysis/code/` into a
   sandbox, re-runs every top-level analysis script in the order declared by
   `03_analysis/analysis_manifest.json` (`{"schema": 1, "scripts": [{"path", "inputs",
   "outputs", "after"}]}`, every top-level script listed once; without it, filename order with
   a warning) and compares every results JSON (timestamps ignored). After a passing proof the
   scoped run re-runs only the scripts the changed inputs reach through the dependency closure
   and carries the rest from that proof (a data or engine-helper change re-runs all). `00_input/` and `01_protocol/` are not available there,
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

## Outputs
- `01_protocol/protocol_final.md`
- `01_protocol/protocol_diff.md`
- `03_analysis/reproducibility_report.json`

## Hard rules
- 1.10.0: keep the `Statistical reporting plan` lines in protocol_final.md. `raw_spot_check`: a script in `03_analysis/spot_check/` (run with `wf run-script`) draws 10 reproducible subjects with `tools/analysis/spotcheck.py` `sample_ids(ids, seed)`, recomputes the key variables from the raw source (`02_data/raw/` files; for a public database the downloaded files) and calls `write_spot_check`; a mismatch is fixed at S04/S05 or carries an explanation.
- Carry the `Design precedent` lines into `protocol_final.md` and update them if the final
  comparator, denominator or primary outcome changed (`design_precedent_recorded`).
- Do not retro-fit the protocol to make the result look pre-specified. The diff file
  exists so that this is impossible to do accidentally.
- A `STOP` here is a real outcome. Report it to the user with the reasoning; do not
  soften a dead result into a "hypothesis-generating" paper without saying so.

## Close
```
.\.venv\Scripts\python.exe tools/wf.py check
.\.venv\Scripts\python.exe tools/wf.py advance --note "protocol final; K deviations; go_nogo_2=<...>; realistic tier=<...>"
```
