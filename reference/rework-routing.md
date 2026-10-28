# User-requested revision routing

All revisions remain inside the medpaper state machine. Reading or editing files directly is
an implementation step, not permission to bypass the owning stage, source of truth or gates.

## Where repeated feedback belongs

- **S19 is the repeated scientific-review loop.** Use it for the assembled manuscript,
  supplementary Methods, results, references, tables, figures, legends and scientific
  interpretation. The user may request as many rounds as needed. Do not advance to journal
  selection until the user approves the scientific version.
- **S24 is the repeated journal-package loop.** Use it after journal selection for DOCX/PDF
  appearance, title page, declarations, cover letter, filenames, upload composition and any
  late content correction. Content still routes back to its scientific source; format-only
  changes may remain at S24. Do not freeze or start S25 until the user approves the actual
  package.

Feedback can also arrive at any other stage. Record it immediately and route it to the
earliest owner; the review loop to return to is the active S19 or S24 round.

## Multi-item revision rounds

For actual user feedback, prefer one batch round over repeatedly invoking the single-kind
command. Interpret the feedback once and write `project/temp/revision_plan.json`:

```json
{
  "feedback_verbatim": "The user's complete feedback, preserved without paraphrased loss.",
  "interpretation": "A concise explanation of the intended outcome, constraints, and what must remain unchanged.",
  "ambiguous_or_requires_user_decision": [],
  "items": [
    {
      "kind": "methods",
      "request": "Shorten the main Methods while retaining the reproducible detail in supplementary Methods.",
      "affected_sources": ["07_manuscript/methods.md", "07_manuscript/supplementary_methods.md"],
      "acceptance_criteria": ["Main Methods retains every design-critical fact", "Supplement contains no tables"]
    },
    {
      "kind": "figures",
      "request": "Increase label legibility in Figure 2 without changing data geometry.",
      "affected_sources": ["05_figures/code/fig2.py", "05_figures/out/Figure2.png"],
      "acceptance_criteria": ["Deterministic figure QC passes", "Fresh render is visually inspected"]
    }
  ]
}
```

If `ambiguous_or_requires_user_decision` is non-empty, ask one concise question and do not
guess. Otherwise collect it into the round (scoped, schema 2, since 1.7.0):

```powershell
.\.venv\Scripts\python.exe tools\rework.py batch --plan project\temp\revision_plan.json   # one per message; builds nothing
.\.venv\Scripts\python.exe tools\rework.py seal --why "<user: that is all, apply it>"     # once
.\.venv\Scripts\python.exe tools\rework.py status                                        # closure + stages to re-check
.\.venv\Scripts\python.exe tools\rework.py check                                         # after editing; also `wf check`
```

`batch` stores the verbatim feedback, its SHA-256, the interpretation and atomic items under
`.wf/revisions/RNNN.json` and snapshots the paper. Further messages before `seal` append to the
same round; identical feedback is ignored. While collecting, `wf run-script`, `save_medpaper`,
`assemble.py` and `build_docx.py` refuse to build. `seal` plans the dependency closure
(`wfcore/dependencies.py`: artifact plan, result receipts, bundle manifest; unknown edges widen),
the stages whose non-lifecycle gates must re-check it (skipped stages never; any 03_analysis
change always adds `analysis_reproduces`) and invalidates only decisions whose evidence can
change. The state machine does not move: completed stages stay completed, and `wf advance`
and `wf loop` are refused until the round closes. The three writers refuse files outside the
closure, so changing one figure re-renders only that figure. `check` fails any file changed
outside the closure. `rework.py build --scope full` (rebuild everything in the closure) is
allowed at most twice per round; otherwise `build --why "<files>"` records targeted rebuilds.

At S24 a scientific source (anything outside `00_input/` and `08_submission/`) moves the round
back to S19: re-review, new approval, `scientific_freeze.py capture --force`, then `wf advance`
resumes a package round at S24 whose only work is to merge the change into the journal copy
and rebind it (`scientific_freeze.py rebind-variant`); S20-S23 are not replayed.

Full rewind is the explicit fallback only, when the scope cannot be determined (for example a
journal switch) or the user asks for it: `batch --rewind` (converts a still-collecting round)
or the single-kind `start` below. Legacy schema-1 rounds keep that flow until closed.

Then record the final files and completed checks for each item:

```powershell
.\.venv\Scripts\python.exe tools\rework.py mark --item R001-01 `
  --changed-file 07_manuscript/methods.md `
  --changed-file 07_manuscript/supplementary_methods.md `
  --validated-by "S08 gates" --validated-by "assembly and citation checks" `
  --summary "Implemented the requested Methods restructuring and preserved all design-critical facts."

.\.venv\Scripts\python.exe tools\rework.py close `
  --summary "All requested items were rebuilt from their owning sources and passed the applicable gates."
```

`revision_rounds_closed` blocks S19/S24 approval and S25 audit when an item is pending, a
changed source is missing, or its final hash drifted after the round was closed.

Single-kind route lookup and the legacy full-rewind `start`:

```powershell
.\.venv\Scripts\python.exe tools/rework.py plan --kind <kind> --why "<requested change>"
.\.venv\Scripts\python.exe tools/rework.py start --kind <kind> --why "<requested change>"
```

Use the earliest stage that owns the changed fact or artifact:

| Revision kind | Owning stage |
|---|---|
| study question, population or design | `study-design` -> S03 |
| raw/derived data | `data` -> S04 |
| model, estimate, numerical result or analysis meaning | `analysis` -> S05 |
| final protocol decision | `final-protocol` -> S06 |
| display inventory or substantive legend plan | `artifact-plan-or-legend` -> S07 |
| Methods or supplementary Methods content | `methods` -> S08 |
| Results wording with unchanged analysis | `results-wording` -> S09 |
| table content | `tables` -> S10 |
| figure content or rendering | `figures` -> S11 |
| figure/table appearance only, same data (no `.md`) | `figure-layout` -> S11, `table-layout` -> S10 |
| reference selection, citation or verified metadata | `references` -> S13 |
| Introduction | `introduction` -> S14 |
| Discussion | `discussion` -> S16 |
| title, abstract, keywords or initial assembly | `title-abstract-keywords` -> S17 |
| meaning-preserving copyedit | `manuscript-copyedit` -> S19 before journal polish, otherwise S22 |
| switch to another target journal | `journal-switch` (was `journal`; full rewind) -> S20 |
| journal formatting: CSL, target_journal.json formatting fields, docx_style.json | `journal-format` -> S20 (presentation) |
| title page or declarations | `title-page-or-statements` -> S21 |
| cover letter, filename, upload list or package composition | `cover-letter-or-package-structure` -> S23 |
| Word layout with absolutely no visible-text change | `word-format-only` -> S23/S24 |

For S19 copyedits, update the owning component Markdown and rerun
`tools/manuscript/assemble.py`; `full_manuscript.md` must still match its components. A change
to a claim, interpretation, method, number, table or figure is not a copyedit and must use its
earlier route.

At S23, capture `package_content_baseline.json` after all DOCX files and `manifest.json` are
final. S24 may preserve manual Word formatting only while the visible-text hash is unchanged.
If Word text changes, reconcile the requested wording to its Markdown/data/table/figure source,
run the owning route, rebuild the true dependants and capture a new baseline at S23. Never
recapture a baseline at S24 merely to bless an edited DOCX.

The legacy single-kind `start` command rewinds and conservatively invalidates every downstream
decision; the scoped round invalidates only decisions whose evidence may have changed.
After corrections, progress through the gates, present the revised artifact again, obtain the
required user confirmation, freeze the new package and run one new independent audit.
Unchanged artifacts may be reused; rebuild only the changed artifact and its actual dependants.

## Context and token discipline without quality loss

Token use is reduced by avoiding repeated interpretation and irrelevant rereading, not by
reducing the requested work:

1. Preserve the user's exact feedback once, then resume from `tools/rework.py status` after
   context compaction instead of reconstructing it from conversation memory.
2. Read the active item, its declared source files, shared result/reference evidence and the
   specific downstream consumers only. Do not reload every manuscript file for a local edit.
3. Change the earliest source of truth. Reuse immutable raw data, verified literature,
   analysis results, journal snapshots and unchanged artifacts when their hashes/dependencies
   did not change.
4. Rebuild only the dependency closure. A Methods wording change rebuilds manuscript/package
   outputs but does not rerun data acquisition; a changed estimate reruns its analysis and all
   dependent prose/tables/figures.
5. Run cheap structural checks first, targeted scientific/functional checks second, and the
   required final visual or independent review once on the resulting revision.
6. Never cite token limits, context compaction, runtime or convenience as a reason to omit an
   item, shrink the analysis, skip a gate, reduce literature verification or accept a partial
   artifact. If the context compacts, continue from the persisted round until every item is
   complete.

## Open rounds, interruptions and S23 layout edits (1.8.0)

- New feedback while a round is sealed: `batch --plan p.json --merge` folds it into the open
  round (scope re-planned); `batch --plan p.json --priority` parks the open round
  (`suspend`) and opens the new one first - e.g. science over an unfinished layout round.
  `resume --round R00n` reactivates a parked round; files other rounds changed meanwhile are
  rebased, not reported as its unplanned changes. A suspended round blocks
  `revision_rounds_closed` until closed.
- Interrupted runs: record partial work with `progress --item <id> --summary "..."
  [--changed-file f]`; `resume` (no `--round`) lists every item with its status, notes and the
  files changed so far, plus changed files not yet attributed to an item.
- At S23/S24 an edit to a frozen or round-certified figure/table script is refused at once
  (frozen-guard hook on file writes, and `wf run-script` before rendering). Open the controlled
  layout round it names: `layout --source 05_figures/code/fig1.R --why "..."`, then edit,
  re-render, `check`, `mark`, `close`.
- Agent plans and check records go in `08_submission/notes/` (or `.wf/`, `temp/`); they are
  never unplanned changes or orphans.
- Revised prose never mentions the pipeline's history (independent review, earlier draft,
  previous version, reviewer request) or the plan's history (initial plan, protocol
  deviations): it simply describes the analysis performed; `no_ai_boilerplate`,
  `section_language_clean` and the S22 lint block such phrases (registered meta-analysis:
  PRISMA 2020 item 24c is the only exception).

## Post-freeze classification (1.13.0)

SCIENCE - back to S19, only after the user's words '我确认回退' - is exactly one of:
(a) analysis code, data, the analysis manifest/tolerances or the results JSON changed;
(b) a reported number changed value (a positional diff of the reviewed text, tables and
figure text); (c) a new number that cannot be traced to the frozen results JSON with the
same meaning. Everything else is PRESENTATION-TRACEABLE: new numbers that trace to the
results (each listed to the user with its file and JSON path), deletions (including a
repeated value), wording and structure edits made for reviewers, label numbers (Online
Resource 2). Only the deterministic checks re-run (provenance, denominators, citations); no
new review round, no re-confirmation - the S24 '我确认这一版' covers them.
`rework.py preview` shows the verdict and the added numbers before anything is recorded.

