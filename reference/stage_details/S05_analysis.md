# S05 - Method scan + exploratory analysis (NO FIGURES) - details

> Long form of `pipeline/stages/S05_analysis.md` (moved out of the card in 1.12.0 so the
> card stays short). Read only the section you need; the card has the commands.
>
> 1.12.0 supersedes older wording below where they differ: long runs use `--wait` (one
> blocking call, heartbeat <= 30 s) and logs live in `.wf/logs/` (or `temp/logs/`);
> `wf check` prints failures + one summary line by default; in `deferred` visual mode no
> DEFER decision is recorded (the look is owed at S23); the `medpaper-reviewer` agent
> writes only its own `report.md` in the review bundle; declaration and section heading
> names come from `target_journal.json` (defaults otherwise).

## Purpose
Find out what the data actually says, using methods the literature accepts for this
design, and dump every number to disk so writing can never invent one.

This stage is deliberately loopable. Iterate here as long as needed; do not
half-finish it and move on.

## Procedure
1. **Method scan.** Search for how comparable papers analysed this design - the model
   family, the confounder strategy, the sensitivity analyses, the standard reported
   metrics. Discovery tools may suggest candidates, but method claims and citations must
   resolve to records retrieved by the bundled client. Run the formal queries the design
   needs through the client (1.14.0: no minimum count - the scan is judged by the methods and
   argument it covers; the gate only needs proof that a search ran):
```
.\.venv\Scripts\python.exe tools/pubmed/client.py search --query "<design> <outcome> statistical analysis" --retmax 100
.\.venv\Scripts\python.exe tools/pubmed/client.py fetch --ids <...> --with-abstract
```
   Write `project/03_analysis/method_scan.md`: for each candidate method, what it is,
   which retrieved papers use it, and whether it fits our data. Cite with `[@key]`.
2. **Analyse.** Choose the language per `reference/language_policy.toml`: Python for cleaning,
   merging and ordinary statistics; R for survival, competing risks, nomogram/calibration/DCA,
   multiple imputation, propensity weighting, complex surveys, mixed models, meta-analysis and
   Table 1 statistics. Every analysis lives in a **top-level** script under
   `project/03_analysis/code/`, named `01_*`, `02_*` ... because S06 re-runs them in filename
   order, from raw data, without arguments, and they must rebuild `02_data/derived/`. Helpers
   go in subdirectories (`03_analysis/code/lib/`) and are imported or sourced. Analysis code
   must not read `00_input/` or `01_protocol/` (neither exists in the S06 sandbox), must not
   contain absolute paths, and must seed every random step:
```python
from analysis.results import set_seed, write_results
set_seed(20240917)
# ... analysis reading project_dir() / "02_data/..." ...
write_results("primary", {"analysis": "primary_model", "n_analysed": 1284, "ci_level": 0.95,
                          "estimates": [{"term": "exposure", "reference": "unexposed",
                                         "outcome": "death", "estimate": 1.87, "ci_low": 1.34,
                                         "ci_high": 2.61, "p": 0.00021, "scale": "HR"}]})
# 1.14.0: the writer bundle reads lists and the recorded ci_level (environment default 0.95);
# name terms/outcomes in the display dictionary so every estimate reaches the writer.
```
```r
source(file.path(Sys.getenv("MEDPAPER_ROOT"), "tools/R/medresults.R"))
medpaper_seed(20240917)
fit <- survival::coxph(survival::Surv(time, status) ~ exposure, data = dat)
write_results(list(analysis = "primary_model", hr = unname(exp(coef(fit))[1]),
                   covariates = I("age")), "primary")   # I() keeps a length-1 vector an array
```
   Run each with `python tools/wf.py run-script 03_analysis/code/<script>`. The wrapper
   exports the selected paper and adds `tools/` to `PYTHONPATH`; direct execution without a
   paper root fails closed. R scripts never call `toJSON()`/`write_json()` themselves.
3. **Results JSON.** `write_results()` writes `project/03_analysis/results/<name>.json`, one
   file per analysis block, plus an `environment` receipt (language and version, packages,
   seed, script and its sha256, written_at). `results_have_environment` checks every receipt;
   the receipt's own numbers never count as provenance for manuscript numbers.
   **Every number that will ever appear in the manuscript, a table, or an abstract must
   be in one of these files.** The gates at S08-S16 reject numbers that are not.
4. **Keep the log.** Append to `project/03_analysis/analysis_log.md` as you go: what you
   ran, what came out, what you decided next and why. Include dead ends - they become the
   sensitivity analyses a reviewer asks for.
5. **Keep the notes.** Update `03_analysis/notes.md` under all four headings. This is the
   only sanctioned input to Introduction and Discussion framing, so it must be substantive.
6. Delete scratch scripts and abandoned outputs from `project/temp/`. 1.14.0: a superseded
   or erroneous result JSON (and the script that wrote it) is RETIRED, not deleted -
   `tools/retire_result.py --file <path> --why "<reason>"` moves it to
   `03_analysis/retired/` with the reason in `RETIRED.md`, so it is never number provenance
   and never re-run. A valid negative or contradictory result is not retired: it stays and
   is reported.
7. When to stop (1.14.0): the analysis is complete when the primary and secondary outcomes
   and the validity checks declared in the protocol's statistical reporting plan are done.
   Each further analysis is marked `"role": "additional"` in
   `03_analysis/analysis_manifest.json` with one line `"decision"`: which scientific decision
   it could change (`additional_analyses_justified`). If it could change none, do not run it.

## Outputs
- `03_analysis/method_scan.md`
- `03_analysis/analysis_log.md`
- (plus scripts in `03_analysis/code/` and result JSONs in `03_analysis/results/`)

## Hard rules
- Baseline tables (1.9.0): count every level of a categorical variable - both categories of a binary one (women AND men) - overall and per group, with `baseline_counts()` (tools/R/medresults.R or tools/analysis/results.py) inside the results JSON, so any journal layout (M/F) has provenance.
- 1.14.0: internal diagnostic plots (residuals, proportional hazards, distributions) are
  allowed in scripts and images under `03_analysis/diagnostics/` (run with `wf run-script`);
  they are never submission figures, never re-run by reproduce.py, ignored by the figure
  gates and never cited in the manuscript. The rule below applies to `03_analysis/code/`.
- **No plotting.** Python: no matplotlib/seaborn/plotly imports, `plt.`, `.plot()`, `.hist()`,
  `.savefig()`. R: no `plot()`, `hist()`, `ggplot()`, `ggsave()`, `png()`/`pdf()`, `dev.off()`,
  `ggsurvplot()`, `forest()`, `love.plot()`, `densityplot()` and friends. The gate scans the code
  (comments and strings excluded). Figures are S11, built from an approved plan.
- No p-value computed in prose. If it is not in a JSON file, it does not exist.
- Do not silently switch the primary analysis. If it changes, record it at S06 (internal
  log; 1.14.0 D1: the reviewer gets a factual pre-specified vs final record).
- Analytical skills may help implement the approved analysis, but cannot change the
  protocol, create manuscript prose, bypass results JSON, or advance the stage.

## Close
When the primary and secondary outcomes and the declared validity checks are done (1.14.0;
additional analyses only with the decision they could change):
```
.\.venv\Scripts\python.exe tools/wf.py check
.\.venv\Scripts\python.exe tools/wf.py advance --note "primary result: <effect, CI, p>; K result files; open: <...>"
```
To iterate again later from a downstream stage: `.\.venv\Scripts\python.exe tools/wf.py loop --to S05_analysis --why "..."`
