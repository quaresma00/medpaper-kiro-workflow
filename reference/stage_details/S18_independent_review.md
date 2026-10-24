# S18 - Independent publication-readiness review - details

> Long form of `pipeline/stages/S18_independent_review.md` (moved out of the card in 1.12.0 so the
> card stays short). Read only the section you need; the card has the commands.
>
> 1.12.0 supersedes older wording below where they differ: long runs use `--wait` (one
> blocking call, heartbeat <= 30 s) and logs live in `.wf/logs/` (or `temp/logs/`);
> `wf check` prints failures + one summary line by default; in `deferred` visual mode no
> DEFER decision is recorded (the look is owed at S23); the `medpaper-reviewer` agent
> writes only its own `report.md` in the review bundle; declaration and section heading
> names come from `target_journal.json` (defaults otherwise).

## Purpose
Test the frozen complete manuscript, supplementary Methods and every table before the user
edits them. This is an independent scientific/editorial audit, not another writing pass.

## Procedure
1. Freeze the inputs for this audit: `07_manuscript/full_manuscript.md`,
   `07_manuscript/supplementary_methods.md` when present, every workbook under
   `04_tables/main/` and `04_tables/supplementary/`, every rendered figure PNG in the plan,
   legends, captions and `01_protocol/artifact_plan.json`.
   Do not change them while the reviewer is working. Open review round 1 (it stays open; its
   fixes are applied at S19):
```
.\.venv\Scripts\python.exe tools/review_round.py start --scope manuscript
```
   It lists the exact current files, writes hash-bound text copies of the workbooks under
   `.wf/review_text/` (regenerated now; give the reviewer these, never an older extract) and
   prints a fenced `json` block (`reviewed_artifacts`: path -> SHA-256). Give the reviewer
   exactly those files, figures included; a review that never saw the figures cannot pass.
2. Delegate to exactly one independent subagent - **the `medpaper-reviewer` agent** - which
   must not edit files, run commands or advance a stage. It is declared `tools: ["read"]`, so
   that is structural rather than a request; do not grant it more. Give it the frozen paths
   and the review you want.
   Its context is isolated from this conversation, which is the point: a reviewer that watched
   you write the manuscript cannot judge it. Never substitute your own read-through for this
   step.
   The reviewer must judge whether the study could be published in a legitimate current SCIE
   journal, including a realistic low-impact/Q3/Q4 venue, rather than whether it belongs in a
   top journal.
   It reports; **you** write the file in step 4. That division is deliberate. Ask it
   explicitly for a reader-comprehension and a medical-presentation finding that covers the
   figures, not only the text.
3. Require the reviewer to check scientific validity, internal consistency, reporting
   completeness, whether the Methods support reproducibility without bloating the main
   text, whether tables/supplement agree with the manuscript, claim strength, fatal versus
   correctable problems, and the likely acceptance ceiling. It must distinguish data or
   design barriers from presentation defects.
   Check legend meaning in context: panel mapping and decoding information must suffice
   without repeating Results, including paraphrased findings that a phrase check cannot catch.
   Verify that each table footnote and figure legend defines the abbreviations that display
   uses (mixed-case terms included) and that the central list covers them too; do not treat
   every uppercase label as an acronym.
4. Preserve the review in `project/07_manuscript/independent_publishability_review.md`
   under these exact headings: `Verdict`, `Critical barriers`, `Scientific validity`,
   `Reporting completeness`, `Tables and supplementary material`, `Journal suitability`,
   `Required revisions`, `Post-revision outlook`, plus `Reader comprehension` (what a
   clinician reading the paper and its figures would and would not understand) and
   `Medical presentation` (how the figures, tables and terminology present the medicine),
   each at least 80 characters of the reviewer's actual findings. Paste the unchanged
   `reviewed_artifacts` block from step 1 into the report. The `reader_review_coverage` gate
   recomputes the hashes: if any input changed after the review, the review is stale.
5. Record one decision:
```
.\.venv\Scripts\python.exe tools/wf.py decide independent_publishability "READY|REVISE|NOT_READY" --why "<one-sentence basis from the independent review>"
```
   `READY` means ready for the user's review and realistic SCIE targeting; `REVISE` means
   potentially publishable after listed corrections; `NOT_READY` means a material validity
   barrier remains. The workflow may still advance so the user can inspect the evidence.
   Do not ask the user about individual findings here; S19 applies them and reports once.

## Outputs
- `07_manuscript/independent_publishability_review.md`

## Hard rules
- 1.11.0: pass the reviewer only the bundle path printed by `review_round.py start` (`.wf/review_bundle/<round>/MANIFEST.md`, self-contained: text copies, figure PNGs, rendered Word pages when available) and the neutral brief it prints. Never add known deviations, previous conclusions or what you expect to hear. From round 1 the reviewer reads as a first-time clinical reader and checks engineering language and self-contained tables/figures, numbering EVERY finding F1, F2 ... in every section (Reader comprehension and Medical presentation included). Save its full report to a file; `close --report <file>` fails until each numbered finding is changed, kept with `--kept ID "reason"`, or handed to the author.
- One independent reviewer only; no review committee and no repeated audit of unchanged
  material.
- The reviewer receives the full manuscript, optional supplementary Methods, tables and the
  rendered figure PNGs, not isolated excerpts.
- Do not let the reviewer silently edit the frozen source or manufacture missing evidence.
- A low impact factor is not a defect when the journal is current SCIE and a realistic fit.

## Close
```
.\.venv\Scripts\python.exe tools/wf.py check
.\.venv\Scripts\python.exe tools/wf.py advance --note "independent verdict=<READY|REVISE|NOT_READY>; critical barriers: <none or list>; frozen files unchanged"
```
