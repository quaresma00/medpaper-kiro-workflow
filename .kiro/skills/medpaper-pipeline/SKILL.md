---
name: medpaper-pipeline
description: Drives a gated, resumable medical/clinical research paper pipeline from a research idea through feasibility, data acquisition, exploratory analysis, figure and table production, IMRAD writing, independent review, journal selection, de-AI polish and a Word submission package. Use whenever the task involves a medical research idea, a clinical manuscript, a research protocol, literature retrieval via PubMed, publication-grade figures or three-line tables, journal selection, a submission package, or a revision round on any of these. Do not follow the workflow from memory - run `python tools/wf.py status` and obey the stage card it prints.
compatibility: Requires Python 3.11+ for the driver. Tables and Word output additionally need numpy, pandas, openpyxl and python-docx (matplotlib for the Python figure path). R 4.3+ with the packages in reference/language_policy.toml (figures default to R). Network access is required for PubMed, Crossref and Unpaywall. Set NCBI_API_KEY to raise the E-utilities rate limit.
metadata:
  version: "2.6.1"
  stages: "25"
  entrypoint: "python tools/wf.py status"
---

# medpaper pipeline

A 25-stage research pipeline. The workflow is **not** in this file: it lives in
`pipeline/pipeline.toml` and `pipeline/stages/*.md`, and the CLI hands you one stage at a
time. Long-form background: `reference/skill_details.md` (read only if needed).

## The loop

```
python tools/wf.py status                       # stage, gate, last handoff, the stage card
<do the work on the card>
python tools/wf.py check                        # failures + one summary line (full list: .wf/logs/)
python tools/wf.py advance --note "..."         # refuses on a red gate
```

Run `status` once per session or stage change; never infer the stage from memory or files.
The paper is the folder the user opened as the Kiro workspace: `wf init` there, in place
(an existing paper there is resumed). Never create a subfolder for the paper, never ask the
user to reopen another folder, never invent a location, never the data folder or its parent;
`wf init` names the rare refusal (drive root, home folder, inside another paper) and only then
ask once. An older attempt in a subfolder stays untouched. `wf new --root/--central` only on
the user's explicit request. Commands act only on that paper; never read or list another
paper. Datasets are declared in place, read-only, never copied: `wf data add <absolute path>`.
Reports the user wants outside the paper: `wf config --user report_dirs add <dir>` (.md/.txt).

## Execution economy (1.12.0)

- **Context for a new session or delegated step: `wf handoff`** (<= 60 lines: versions,
  stage + card, gate fail/warn names, open rework/review rounds, pending user questions,
  last events, next command). Pass its output instead of a hand-written brief.
- Long commands: `--wait` (one blocking call, heartbeat <= 30 s, failures + one summary line)
  for `wf check`, `rework.py check`, `reproduce.py run`, `build_docx.py`; `wf check --summary`
  for one line. Logs live in `.wf/logs/` (or `temp/logs/`), never in external temp folders.
- Reproduce once at S06; later stages accept the proof by hash. Batch a review round's
  analysis edits into one plan and reproduce once per round (affected scripts only; `REUSED`
  when nothing changed; notes, docs and manuscript edits never invalidate it). Never run it
  "to be safe" - `wf check` names the cheapest next command. Never copy the user's data.
- Stage cards are short; their `reference/stage_details/` files are read only when needed.
  `wf archetype <name>` prints one figure archetype.
- Prefer a cheaper model for mechanical steps (building tables/figures, checks, DOCX builds)
  when the host lets you choose.
- One look at the end: in `deferred` mode no PNG is loaded at S10/S11 and no decision is
  recorded; S23 discharges every look on one contact sheet (`qc.py --contact-sheet`).

Never a saving: skipping the visual check, truncating a data pull, or reviewing your own
manuscript instead of the subagent. If context runs out, say so.

## Delegate

| Stage | Agent | Notes |
|---|---|---|
| S08, S09, S14, S16, S19 rewrites | `medpaper-clinical-writer` | Pass the MANIFEST of `tools/manuscript/writer_bundle.py build --stage <S>`; it sees clinical labels, results in words, tables, legends, notes - never code, JSON keys or logs. Run `wf check` (engineering-language lint) afterwards. |
| S15 | `medpaper-deepreader` | One invocation per full text; save its notes yourself. |
| S18, S19/S24 rounds, S25 | `medpaper-reviewer` | Give it only the bundle path `review_round.py start` prints and the neutral brief. It writes only `.wf/review_bundle/<round>/report.md`; `close` reads that file - never paraphrase findings. Confirmation is the exact sentence `我确认这一版`. |

## Python and R

`reference/language_policy.toml`: Python for acquisition, cleaning, xlsx tables, Word and
gates; R for figures (`save_medpaper()`) and R-strong statistics. Paper code runs only via
`wf run-script <relative.py|.R>`.

## One paper, never the engine

Order of preference when a gate does not fit the paper: values `wf config set KEY VALUE`
(`.wf/config.toml`) -> shape `wf override init|show|validate` (`.wf/overrides.toml`) ->
a project-local fork `wf engine-fork create` (diff kept for the maintainer) -> never the
global engine (commands refuse to run on a modified engine; the guard hook blocks the write).
A paper keeps the gate set of its pinned engine for completed stages until `wf migrate --yes`.

## The absolute rules

1. A `verified: true` boolean is not evidence; never fabricate or hand-set reference fields.
2. Acquire the complete protocol-defined data universe; no silent caps.
3. No number without provenance in `03_analysis/results/*.json`, written by executed code.
4. Draft sections only at their stages; S17 assembles.
5. Figures are verified by looking at the rendered PNG; `DEFER`/deferred means "not looked
   at yet"; `visual_debts_cleared` (S23) is non-overridable.
6. No explanatory prose in panels; legends never restate Results; clinical labels only.
7. Polishing changes wording only (snapshot + diff).
8. The science freezes at S19; journals adapt the copy in `08_submission/manuscript/`.
9. Every revision goes through `tools/rework.py` (`preview` first; an S19 return only on 我确认回退).
10. The package is final only after the user's 我确认这一版 at S24; S25 audits the freeze.
11. A red gate means fix it, not `--force`.

## Other skills

Never use a skill in place of a stage (`write-paper`, `orchestrate`, `search-lit`,
`make-figures`, `manage-refs`, `polish-language`, `find-journal`, `write-protocol`,
`analyze-stats` ...); complementary ones (`check-reporting`, `deidentify`,
`calc-sample-size` ...) may help inside a stage. Classification: `reference/skill_policy.toml`
(`python tools/hooks/skill_guard.py --audit`).

## Handoff discipline

Before advancing, record what a stranger needs: produced, decided and why, still open.
