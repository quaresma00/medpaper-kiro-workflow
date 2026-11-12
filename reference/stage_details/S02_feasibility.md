# S02 / S04 / S06 - publishability checkpoints (1.23.0) - details

> Long form for `pipeline/stages/S02_feasibility.md`, `S04_data.md` and
> `S06_protocol_final.md`. The gate `publishability_checkpoint` reads `.wf/publishability.json`.

## Why
A study that cannot become an original article should be recognised in hours, not after
weeks of analysis and writing. Each checkpoint records a verdict (GO | CONDITIONAL | NO-GO)
and the best achievable article type (original_article | brief_report | research_letter |
not_publishable), and the user hears it at once in a few Chinese lines. GO continues without a
question. CONDITIONAL or NO-GO stops and asks ONE question with your recommendation: continue as
is, change the angle or the article type, or stop.

## S02 evidence (`--evidence temp/pub_s02.json`; titles and abstracts only)
```json
{"novelty": {"query": "<same exposure + outcome + data-source family or design>",
             "count": 7, "years": 10,
             "closest": [{"pmid": "12345678", "title": "...", "year": 2022}]},
 "data_sufficiency": "<expected cases/events in the planned source>",
 "contribution": "<what this study adds that the closest papers do not>",
 "recommendation": "continue|change|stop"}
```
The count is the number of matching PubMed records of the last 10 years (`client.py search
--years 10`); list the 3-5 closest papers. Do not open full texts for this.

## S04 counts (`--design KEY --count METRIC=VALUE ...`)
Designs and floors live in `reference/publishability.toml` (disproportionality: cases per
drug-event pair and per subgroup; Mendelian randomisation: instrument F statistic and number of
instruments; cohort / case-control: events per variable; complex surveys: unweighted n per
stratum; prediction models: events per candidate predictor; meta-analysis: studies per pooled
outcome). A GO below a required floor is refused - record CONDITIONAL or NO-GO and ask. The
checkpoint is bound to `03_analysis/results/dataset_summary.json`; a change makes it stale.

## S06 evidence (`--evidence temp/pub_s06.json`)
```json
{"precision": "<width of the main interval; can it inform a decision?>",
 "duplication": "<does it only repeat existing findings?>",
 "robustness": "<do the sensitivity analyses agree?>",
 "recommendation": "continue|change|stop"}
```
Bound to every `03_analysis/results/*.json`; a changed result makes it stale.

## The user's answer
```
.\.venv\Scripts\python.exe tools/wf.py publishability answer --stage S04 --choice continue --words "<the user's words>"
```
`stop` ends the paper's work (the gate stays closed). `change` = loop back (`wf loop`) with the
new angle or article type.

## Additional analyses (any stage, incl. reviewer requests)
Before running one, print one line for the user - the conclusion it could change and its rough
cost - and recommend skipping a low-benefit one:
```
.\.venv\Scripts\python.exe tools/wf.py publishability value --analysis "E-value" --could-change "whether residual confounding explains the signal" --cost "1 script, 20 min" --benefit low
```
In `03_analysis/analysis_manifest.json` an `"additional"` entry carries `"decision"`, `"cost"`
and `"benefit"`; a low-benefit one needs `"requested_by"` (user or reviewer).
