---
name: medpaper-pipeline
description: Drives a gated, resumable medical/clinical research paper pipeline from a research idea through feasibility, data acquisition, exploratory analysis, figure and table production, IMRAD writing, independent review, journal selection, de-AI polish and a Word submission package. Use whenever the task involves a medical research idea, a clinical manuscript, a research protocol, literature retrieval via PubMed, publication-grade figures or three-line tables, journal selection, a submission package, or a revision round on any of these. Do not follow the workflow from memory - run `python tools/wf.py status` and obey the stage card it prints.
compatibility: Requires Python 3.11+ for the driver. Tables and Word output additionally need numpy, pandas, openpyxl and python-docx (matplotlib for the Python figure path). R 4.3+ with the packages in reference/language_policy.toml (figures default to R). Network access is required for PubMed, Crossref and Unpaywall. Set NCBI_API_KEY to raise the E-utilities rate limit.
metadata:
  version: "2.1.0"
  stages: "25"
  entrypoint: "python tools/wf.py status"
---

# medpaper pipeline

This repository holds a 25-stage research pipeline. The workflow is **not** in this file and
must not be reconstructed from memory. It lives in `pipeline/pipeline.toml` and
`pipeline/stages/*.md`, and a CLI hands you exactly one stage at a time.

That indirection is the point. A long prompt degrades as context is compacted; a state file on
disk does not. Anything you need to know is one command away, always current.

## The only loop you need

```
python tools/wf.py status                       # where am I, what is blocking, full stage card
<do the work described on the card>
python tools/wf.py check                        # run the stage's gate
<fix what it reports>
python tools/wf.py advance --note "..."         # closes the stage; refuses on a red gate
```

**Run `status` first, every session, before anything else.** It prints the invariants, the
engine and paper paths, the progress map, the gate state, the last handoff note, the declared
outputs, and the whole stage card. After a context reset that single command restores
everything that matters.

Never infer the current stage from the conversation, from which files exist, or from what you
remember doing. Ask the CLI.

## One engine, many papers

```
python tools/wf.py new sarcopenia-mortality   # creates <papers root>/<slug>/ and selects it
python tools/wf.py papers                     # list them and the stage each is at
python tools/wf.py use other-paper            # switch (user-level marker ~/.medpaper/active)
```

The engine is the mother workflow and maintenance-only: no paper lives in it, is resolved in
it or writes into it. Papers live under the papers root (`MEDPAPER_PAPERS_ROOT`, else
`papers_root` in `~/.medpaper/config.toml`, else `<engine parent>/medpaper_papers`), and each
paper is opened as its own Kiro workspace; `wf new` writes its `.kiro/` adapters, which call
the engine by absolute path. `status` prints which paper it resolved and why. Resolution order:
`MEDPAPER_PROJECT`, then an initialised paper at or above the working directory, then the
paper selected with `wf use`. From the engine folder itself, paper-driving commands are
refused and `wf status` prints a maintenance banner. A stale selection fails closed.

## Python and R

`reference/language_policy.toml` is the division of labour: Python for acquisition, cleaning,
xlsx tables, Word and the gates; R for figures (default, `tools/figures/R/medfig.R`
`save_medpaper()`, recipes in `tools/figures/R/recipes.R`) and for survival, competing risks,
nomograms/calibration/DCA, imputation, propensity weighting, surveys, mixed models,
meta-analysis and Table 1 statistics. `targets.figure_engine = "python"` switches a paper's
figures back to `tools/figures/style.py`. `qc.py` judges both renderers identically.

## Reproducibility and environment receipts

Results JSON are written only through `write_results()` (Python `tools/analysis/results.py`,
R `tools/R/medresults.R`), which appends an `environment` receipt: language and version,
packages, seed, script and its sha256. Those receipt numbers never count as provenance. At S06
`python tools/reproduce.py run` re-executes every top-level `03_analysis/code` script in a
sandbox and requires identical results; `analysis_reproduces` re-checks that proof at S17,
S23 and S25. At S23 `08_submission/reporting_checklist.md` maps every item of the protocol's
reporting guideline (`reference/reporting_guidelines.toml`) to a location that exists.

## Customise one paper without changing the engine

The folders `pipeline/`, `tools/`, `reference/` and `.kiro/` are the shared mother workflow.
Never edit them to accommodate one study: that changes every other current and future paper.
There are two paper-local mechanisms instead:

```
python tools/wf.py config set intro_words_max 600  # values -> <paper>/.wf/config.toml
python tools/wf.py override init                    # shape  -> <paper>/.wf/overrides.toml
python tools/wf.py override validate
python tools/wf.py override show
```

`overrides.toml` can declare extra outputs, add gates, relax a non-protected gate, skip a truly
inapplicable non-protected stage, or permit a documented paper-specific file glob. Weakening
needs a substantive reason. Integrity gates (data completeness, reference/number provenance,
full-text identity, visual debt, scientific freeze) and S18/S19/S24/S25 review/audit stages
cannot be removed. `wf status` reprints every effective override; the exact entry is
fingerprinted when its stage finishes, so it cannot be edited or removed retrospectively.
Loop back to that stage first if the scientific design genuinely changes. Run paper-owned
Python or R code through `wf run-script <paper-relative.py|.R>`; it exports the selected root,
runs with the paper as cwd, and fails if shared-engine files change.

## Delegate the expensive reading

Two purpose-built read-only subagents exist. Using them is not optional politeness - it is how
this pipeline stays affordable and how its reviews stay honest. A subagent gets a **fresh,
isolated context**, so a full text or a review never enters this conversation.

| Stage | Delegate to | Why |
|---|---|---|
| S15 deep-read | `medpaper-deepreader`, **one invocation per paper** | A full text is tens of thousands of tokens. Five of them will not fit here. You get back a page of structured notes; save those to `06_refs/deepread/<citekey>.md` yourself. |
| S18 independent review | `medpaper-reviewer` | Its judgement must not be contaminated by having watched you write the manuscript. That is the entire point of the stage. |
| S25 submission audit | `medpaper-reviewer` | Same reviewer, three positions: publication readiness, guideline compliance, reader/editor. |
| S02 / S05 / S07 literature reconnaissance | `context-gatherer` for repo questions; the PubMed client for literature | Keep raw payloads out of this context; you only need the conclusion. |

Both reviewer agents are `tools: ["read"]`, so they cannot edit files, run commands or advance
anything. **You** save their output to the path the stage declares. That division is
deliberate: the reviewer owns the judgement, you own the artifact.

Invoke by naming the agent, e.g. "Use the medpaper-reviewer agent to audit the frozen package
at 08_submission/bundle/ against 08_submission/guidelines_extract.md".

Never review your own work in place of S18 or S25. You are the least reliable judge of whether
the manuscript you just wrote is ready, and the gate exists because of that.

## Token discipline

Quality first - but most token spend here is waste, not quality.

- **`status` once per session or per stage change**, not before every command. Within a stage
  use `wf check` (gate output only) or `status --brief` (no stage card). The full card is ~2000
  tokens; you do not need it twice for the same stage.
- **`wf archetype <name>`** prints one figure archetype. Never read
  `reference/archetypes.toml` whole - it is 11 KB and a figure needs one entry.
- **Read result JSONs, not raw data.** `03_analysis/results/*.json` exists so numbers are
  cheap to look up. Do not re-read `02_data/` to answer a question a results file answers.
- **Look once, at the end, on one sheet.** With the default `visual_review_mode = "deferred"`
  no PNG is loaded at S10/S11 at all; at S23 `python tools/figures/qc.py --contact-sheet`
  tiles every figure into a single image, so the whole run costs one load instead of one per
  figure per re-render. This is the largest single context saving in the pipeline, and it
  removes no check: the obligation is tracked and the S23 gate is non-overridable.
- **Crop before you look.** For a suspect panel of a multi-panel plate,
  `python tools/figures/qc.py --crop "Figure 1" --cols 2 --cell B`, then read the crop.
- **Let the gate find the problem.** `wf check` names the failing file and reason. Reading
  everything first to guess what might be wrong costs more than asking.
- **Do not re-read a stage card you are already working from**, and do not read other stages'
  cards speculatively. `wf card SNN` exists for when you genuinely need one.

What is never a saving: skipping the visual figure check (deferring it to S23 is scheduling,
dropping it is not), truncating a data pull, sampling
instead of full retrieval, or reviewing your own manuscript to avoid a subagent call. If
context is genuinely running out, say so and let the user decide - do not quietly downgrade
the work.

## Other commands

| Command | Use |
|---|---|
| `wf doctor` | Environment and wiring check; run when something behaves oddly |
| `wf card S11` | Print any stage card |
| `wf archetype km_survival` | One figure archetype's mandatory elements |
| `wf check S09` | Run a gate without advancing |
| `wf tree -v` | Whole pipeline with per-stage outputs and gates |
| `wf decide NAME VALUE --why "..."` | Record a gated decision plus its rationale |
| `wf note "..."` | Append to the handoff log |
| `wf loop --to S05_analysis --why "..."` | Deliberately reopen an earlier stage |
| `wf clean [--apply]` | Report scratch and undeclared files; delete scratch |
| `wf config set KEY VALUE` | Override a target for this paper (`.wf/config.toml`) |
| `wf override init/show/validate` | Change this paper's workflow shape without editing the mother workflow |
| `wf run-script 03_analysis/code/01_primary.py` | Run a paper script with its root exported; fails if it touches the engine |
| `wf invariants` | Reprint the non-negotiable rules |

## The absolute rules

`wf status` prints the full list. These are the ones that get violated under pressure.

1. **A `verified: true` boolean is not evidence.** Reference gates re-parse the cached PubMed
   EFetch XML and recompute every bibliographic comparison against `library.json`. The cache
   path must be a bundled verifier output, its SHA-256 must match, and the library hash must
   match. Never hand-write a script that sets `verified` or fabricates a DOI to make
   `citekeys_resolve` go green - that is fabrication, and the gate is built to catch it. If a
   citation cannot be verified, remove it from the text or replace it with a real record found
   through `tools/pubmed/`.
2. **Acquire the complete data universe.** Never silently use `LIMIT`/`TOP`, `head()`,
   `sample()`, or a first-N slice when the source can return everything. Any reduction must be
   protocol-defined and recorded in the data manifest.
3. **No number without provenance.** Every figure in the manuscript, tables and abstract must
   already exist in `03_analysis/results/*.json`, written there by code that ran.
4. **Draft scientific sections only at their active stages.** S17 assembles the canonical full
   manuscript; do not pre-assemble it.
5. **Figures are verified by looking at them.** Deterministic QC first
   (`tools/figures/qc.py`, every round, both modes), then load the rendered PNG as an image.
   Reading the plotting code is not verification, and claiming a visual check you did not
   perform is a fabrication. *When* you look is set by `visual_review_mode`: the default
   `deferred` records `DEFER` at S10/S11 and discharges every look in one contact-sheet pass at
   S23, once S20 has fixed the journal's column width and palette. `DEFER` means "not looked at
   yet" and must never be reported as verified; `visual_debts_cleared` at S23 is
   non-overridable, so nothing ships unlooked-at.
6. **No explanatory prose inside figure panels**, and a figure legend must not restate the
   Results.
7. **Language polishing changes wording only** - never a number, a citation or a figure/table
   reference. A snapshot is taken first and the gate diffs against it.
8. **The scientific record freezes at S19; journals adapt a copy.** When the user says the
   science needs no further change, `tools/manuscript/scientific_freeze.py capture` hashes it.
   `07_manuscript/` is read-only from then on. Word caps, abstract shape, reference style, title
   page and required statements are presentation, and are applied to the variant S20 opens at
   `08_submission/manuscript/`. Choosing a different journal first loops to S20 and runs
   `scientific_freeze.py reset-journal --confirm-journal "<old>"`; this clears the entire old
   submission tree, after which S20 takes a fresh copy from the same frozen text. A second
   journal never inherits the first journal's title page, cache, cover letter, trims, bundle or
   approvals. Gates resolve to the variant automatically. The freeze/variant gates are
   non-overridable.
9. **Route every revision through `tools/rework.py`.** A user's change request goes to the
   earliest owning stage, updates the source of truth, and rebuilds downstream. Never patch a
   rendered artifact directly.
10. **The package is not final until the user says so.** S24 records explicit confirmation and
    freezes the exact files; S25 then audits the frozen set.
11. **A red gate means stop and fix, not `--force`.**

## Do not let another skill replace a stage

A general medical-research skill suite may also be installed. Skills that produce an artifact a
stage declares write to different paths and carry no gate, so substituting one leaves the gate
red with nothing that can satisfy it:

| Do not use | Use instead |
|---|---|
| `write-paper` | S08, S09, S14, S16, S17 |
| `orchestrate`, `manage-project`, `intake-project` | `wf status`, `wf new`, S01 |
| `search-lit`, `medsci-lit-api` | `tools/pubmed/client.py` |
| `make-figures` | S11 + `tools/figures/` |
| `manage-refs`, `verify-refs` | S13 + `tools/pubmed/verify.py` |
| `polish-language`, `humanize` | S22 + `tools/text/polish.py` |
| `find-journal`, `sync-submission` | S20, S23 |
| `write-protocol`, `analyze-stats` | S03/S06, S05 |

Complementary and worth using inside a stage: `check-reporting` (read-only help filling the
S23 reporting checklist that `reporting_checklist_complete` verifies), `self-review` / `peer-review` / `revise` (post
submission), `deidentify` / `generate-codebook` / `clean-data` at S04, `calc-sample-size` /
`design-study` / `define-variables` at S03, and the imaging/ML skills, which are a different
domain entirely.

The full classification is in `reference/skill_policy.toml`, enforced by a `PreToolUse` hook so
a blocked skill cannot be activated at all:

```
python tools/hooks/skill_guard.py --audit              # every installed skill by verdict
python tools/hooks/skill_guard.py --explain write-paper
```

## Where things are

```
pipeline/pipeline.toml       the workflow definition (single source of truth)
pipeline/stages/*.md         one instruction card per stage, S01..S25
tools/wf.py                  the driver
tools/pubmed/                PubMed / Crossref / Unpaywall clients, library builder, verifier
tools/data_manifest.py       records the acquired data universe; blocks silent truncation
tools/tables/threeline.py    three-line xlsx writer
tools/figures/               journal style, archetype recipes, element detection, QC
tools/figures/R/             medfig.R (save_medpaper, theme, palettes) and recipes.R (R default)
tools/R/medresults.R         R results writer with environment receipt
tools/analysis/results.py    Python results writer with environment receipt
tools/reproduce.py           S06 sandbox re-execution and its proof
tools/manuscript/            assemble, build_docx, reference_count, review_package
tools/text/polish.py         de-AI + academic-English linter, fact-preservation diff
tools/rework.py              routes a revision to the earliest owning stage
tools/package_*.py           submission package build, content check, review freeze
tools/hooks/skill_guard.py   refuses skills that would replace a stage
reference/                   figure, table and Methods standards; archetypes; skill policy
reference/language_policy.toml      Python/R division of labour and required R packages
reference/reporting_guidelines.toml reporting-guideline item lists for the S23 checklist
<papers root>/<slug>/        the paper being written (its own Kiro workspace); state in .wf/
```

## Handoff discipline

Before advancing, record what a stranger would need to pick this up: what was produced, what
was decided and why, and what is still open. `wf advance` refuses without it. This is what
makes the pipeline survive a context reset or a new session.
