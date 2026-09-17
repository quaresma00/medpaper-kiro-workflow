---
inclusion: always
---

# medpaper pipeline

> **If you are a delegated subagent, stop here.** Steering is shared with subagents and is not
> isolated, so this file reaches you even when it should not. Everything below addresses the
> agent that *builds* the manuscript. If you were invoked to review, audit, read a full text or
> gather context, none of it applies to you: do not run `wf` commands, do not advance a stage,
> do not write pipeline artifacts. Do the job you were given and report back. Your own agent
> prompt governs; this file does not.

This workspace is driven by a gated pipeline, not by prompt instructions.

**Before doing anything in this repo, run `python tools/wf.py status`.** It returns the
current stage, the invariants, the gate state, the last handoff and the full stage card.
Do not infer the stage from the conversation or from which files exist.

Loop: `wf status` -> do the work -> `wf check` -> `wf advance --note "..."`.

25 stages. One engine, many papers: `wf new <slug>` starts one under `papers/`, `wf papers`
lists them, `wf use <slug>` switches. `wf status` prints which paper it resolved and why.

Never edit `pipeline/`, `tools/`, `reference/` or `.kiro/` for one study - they are the shared
mother workflow. Values go in this paper's `.wf/config.toml` via `wf config set`; a genuine
shape difference goes in `.wf/overrides.toml` via `wf override init`. `wf override validate`
refuses protected integrity gates, review/audit-stage skips, path escapes and retrospective
changes to an override that already governed a finished stage. Status reprints every effective
override on every call. Run paper Python/R code only through `wf run-script <relative.py|.R>`;
it uses the paper as cwd and trips if shared-engine files change.

Hard rules, several mechanically enforced by the gates:

- **A `verified: true` boolean is not evidence.** Reference gates re-parse the cached PubMed
  EFetch XML and recompute every bibliographic comparison against `library.json`; the cache
  path, its SHA-256 and the library hash must all match. Never write a script that sets
  `verified` or invents a DOI to turn `citekeys_resolve` green - that is fabrication. If a
  citation cannot be verified, delete it or replace it with a real record from `tools/pubmed/`.
- **Acquire the complete data universe.** No silent `LIMIT`/`TOP`/`head()`/`sample()`/first-N
  slice when the source can return everything. Any reduction is protocol-defined and recorded
  in the data manifest.
- Every manuscript number must already exist in `03_analysis/results/*.json`, written by
  executed code.
- Draft scientific sections only at their active stages; S17 assembles the canonical full text.
- Only create the outputs the stage declares; scratch lives in `temp/`.
- Figures: `python tools/figures/qc.py --all` every round - that half is code and never waits.
  *When* you look is set by `visual_review_mode`. The default `deferred` records `DEFER` at
  S10/S11 and discharges every look in one `qc.py --contact-sheet` pass at S23, once S20 has
  fixed the journal's column width and palette. `DEFER` means "not looked at yet" and must
  never be reported as verified; `visual_debts_cleared` at S23 is non-overridable. Reading the
  plotting code is not verification. Figure legends must not restate the Results.
- Figure standards, archetypes and palettes: activate the `medical-sci-figure-skill` global
  skill and read its atlas entry for the chart type in hand. Reading and styling only -
  `tools/figures/style.py` renders, `tools/figures/qc.py` judges, and its own
  `audit_medical_figure()` must not be run on a pipeline figure. Width, font-floor, legend and
  QA-engine conflicts are settled in `reference/skill_policy.toml` `[figure_authority]`.
- No explanatory prose inside figure panels.
- Language polishing changes wording only, never a number, a citation or a figure/table
  reference. Snapshot before the pass: `python tools/text/polish.py snapshot`.
- Route every user revision through `tools/rework.py` to the earliest owning stage, then
  rebuild downstream. Never patch a rendered artifact directly.
- The science freezes when the user releases S19 (`scientific_freeze.py capture`). From S20 on
  `07_manuscript/` is read-only: journal requirements are applied to the copy S20 opens at
  `08_submission/manuscript/`. To switch journals, first loop to S20 and run
  `scientific_freeze.py reset-journal --confirm-journal "<old>"`; it clears the whole old
  submission tree before S20 opens a fresh copy. `scientific_freeze_intact` is non-overridable.
  Gates resolve to the variant on their own - do not pass different paths. Prose may be tightened for a word cap; a number or citation
  that disappears is dropped content and needs `journal_trim_authorised YES`.
- The submission package is not final until S24 records explicit user confirmation and freezes
  the files; S25 then audits the frozen set.
- A red gate means fix it, not `--force`.

## Skill arbitration in this workspace

A general medical-research skill suite may also be installed at the user level. Several of
its skills do the same job as a pipeline stage, but write their outputs elsewhere and carry
no gate, so using one instead of the stage leaves the gate red with no way to satisfy it.

**Never use these in place of a stage. In this workspace the pipeline wins:**

| Skill | Superseded by | Why |
|---|---|---|
| `write-paper` | S08, S09, S14, S16, S17 | A competing 8-phase manuscript workflow with no gates |
| `orchestrate` | `wf status` | Routes the task away from the pipeline; the stage card is the router |
| `manage-project`, `intake-project` | `wf new`, `wf status`, S01 | Competing project scaffold and state |
| `search-lit`, `medsci-lit-api` | `tools/pubmed/client.py` | Payload never reaches `06_refs/cache/`, so the retrieval and verification receipts cannot pass |
| `make-figures` | S11 + `tools/figures/` | No `qc_report.json`, no archetype element checks, wrong output paths |
| `manage-refs`, `verify-refs` | S13 + `tools/pubmed/verify.py` | Does not produce the tamper-evident verification receipt the gate re-checks |
| `polish-language`, `humanize` | S22 + `tools/text/polish.py` | No pre-polish snapshot, so fact preservation cannot be proven |
| `find-journal`, `sync-submission` | S20, S23 | Bypasses the fetched-and-snapshotted guideline requirement |
| `write-protocol` | S03, S06 | Competing protocol format; the gate checks specific headings |
| `analyze-stats` | S05 | No results-JSON provenance contract, so downstream numbers fail their gate |

**These are complementary. Use them inside the relevant stage:**

- `check-reporting` - run it at S12, S18 or S22 against the declared reporting guideline. The
  pipeline records which guideline applies but does not check it item by item; this closes
  that gap.
- `self-review`, `peer-review`, `revise` - post-submission work, which the pipeline does not
  cover at all.
- `deidentify`, `generate-codebook`, `clean-data`, `version-dataset` - useful at S04, as long
  as the codebook and `dataset_summary.json` still land where S04 declares.
- `calc-sample-size`, `design-study`, `define-variables` - useful at S03, feeding into
  `protocol_v1.md`.
- Imaging and ML skills (`model-scaffold`, `radiomics-ml`, `explainability`,
  `preprocess-imaging`, `model-validation`, and similar) - a different domain, no conflict.

Rule of thumb: a skill that produces an **artifact a stage declares** must not be used unless
its output lands at the declared path and satisfies that stage's gate. A skill that produces
**analysis or a review** is fine anywhere.

The full classification is data, not prose: `reference/skill_policy.toml`. A `PreToolUse`
hook (`.kiro/hooks/medpaper-skill-guard.json`) enforces it, so this is not merely advice -
a blocked skill cannot be activated. Inspect or change it with:

```
python tools/hooks/skill_guard.py --audit            # every installed skill by verdict
python tools/hooks/skill_guard.py --explain write-paper
```

Detail: #[[file:.kiro/skills/medpaper-pipeline/SKILL.md]]

Reference material, loaded when relevant:
#[[file:reference/figure-standards.md]]
#[[file:reference/table-standards.md]]
