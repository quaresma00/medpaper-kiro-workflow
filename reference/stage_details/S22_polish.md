# S22 - Journal-specific, fact-preserving polish - details

> Long form of `pipeline/stages/S22_polish.md` (moved out of the card in 1.12.0 so the
> card stays short). Read only the section you need; the card has the commands.
>
> 1.12.0 supersedes older wording below where they differ: long runs use `--wait` (one
> blocking call, heartbeat <= 30 s) and logs live in `.wf/logs/` (or `temp/logs/`);
> `wf check` prints failures + one summary line by default; in `deferred` visual mode no
> DEFER decision is recorded (the look is owed at S23); the `medpaper-reviewer` agent
> writes only its own `report.md` in the review bundle; declaration and section heading
> names come from `target_journal.json` (defaults otherwise).

## Purpose
Adapt the journal's copy of the manuscript to the journal without changing a number, citekey,
figure/table reference or scientific claim. 1.25.0: no second full polish - only cross-section
consistency, journal adaptation and the paragraphs changed after assembly.

**You are editing `08_submission/manuscript/`, not `07_manuscript/`.** The science was frozen
when the user released S19; this stage is journal-specific work, so it happens on the variant
S20 opened. `polish.py` and every gate here resolve there automatically - you do not pass
different paths. The pre-polish snapshot and report also live under the variant, so S22 writes
nothing into `07_manuscript/`. The separate `variant_preserves_science` gate compares the final
variant to the frozen source directly.

`variant_preserves_science` compares the variant to the frozen source directly. Prose may be
tightened as much as the journal's cap requires. A number, citation or artifact reference that
disappears means content was dropped rather than tightened, which is a scientific decision:
restore it and tighten prose instead, or get the user's explicit authorisation and record
`journal_trim_authorised YES` with what was dropped and where it now lives.

## Procedure
1. Snapshot before editing:
```
.\.venv\Scripts\python.exe tools/text/polish.py snapshot
```
   When `full_manuscript.md` exists, the tool treats it as the canonical main source and
   snapshots it plus supplementary Methods and administrative files; it does not also
   polish stale component drafts.
2. Run `tools/text/polish.py lint`, fix blocking AI tells and house-style defects, and align
   abstract structure, spelling, word/reference limits and permitted headings with the
   chosen journal. Preserve medical-journal prose: continuous narrative, calibrated claims,
   concise Methods in the main paper, and detailed implementation only in the supplement.
3. Keep Keywords immediately after the Abstract, comma-delimited, 3-6 items. Preserve the
   explicit References heading and concise Figure legends at the end.
4. Run `tools/text/polish.py diff` and `tools/text/polish.py lint` again. Restore and redo
   any wording edit that loses or adds a number, citation or artifact reference.
5. Write `polish_log.md` with the headings `Cross-section consistency fixes`,
   `Journal adaptation`, `Re-polished paragraphs (editor receipts)`,
   `Cut to meet journal limits`, `Tier-B phrases kept` (1.25.0; `polish_complete` checks them on 1.25.0+ papers - a paper pinned earlier may
   keep the old headings). There is no second full polish: every section was polished by the
   medical editor at its own stage, so the log records only what this stage changed.
6. Check what the journal adaptation actually cost, and put the numbers in `polish_log.md`
   under `Cut to meet journal limits`:
```
.\.venv\Scripts\python.exe tools/manuscript/scientific_freeze.py delta
```
7. Read the cross-section report (`polish.py crosscheck`), the lint and diff output and the
   paragraphs you changed - not the whole manuscript, unless the user asks for it - then
   record `polish_reviewed YES` with a concrete reason.

## 1.25.0 - after assembly: cross-section consistency and changed paragraphs only
- `polish.py crosscheck` (also the gate `cross_section_consistent`: a warning at S17 right after
  assembly, so issues are fixed before the S18 review; at S22 the clear errors block on 1.25.0+
  papers) reports what one section cannot show: one population name across the manuscript
  (reports, cases and patients never interchanged; display-dictionary labels); abbreviations
  defined once at first use, separately in the abstract and the body (redefinition and use
  before the definition block; defined but used once warns); near-duplicate sentences
  Introduction vs Discussion and Methods vs Results (content-word Jaccard >= 0.7, warning;
  the 1.19 Discussion-vs-Results rule is unchanged); every number of the abstract's results and
  conclusion is a value in the Results text or the tables (blocks on a mismatch); the abstract
  and Discussion conclusions are listed for the reviewer (strength); spelling variant and P/p.
- Paragraphs changed after assembly - S22 trims and journal edits in
  `08_submission/manuscript/`, edits in review rounds (S18/S19/S24) and rework rounds - pass
  through `medpaper-medical-editor`, those paragraphs only: `writer_bundle.py edit --section
  manuscript` writes `.wf/editor_bundle/manuscript/changed.md` with the changed paragraphs
  (per-paragraph hashes against every section's polished text and earlier manuscript receipts);
  the editor writes `polished.md` with the same `<!-- paragraph N -->` markers; `polished
  --section manuscript` checks numbers, citations, display references and language and merges
  them. Gate `changed_paragraphs_polished` at S22 and S23 (since 1.25.0). Unchanged paragraphs
  are never sent again. The S25 final copy is the author's own Word edit, checked by
  `final_copy.py check`; wording the AI changes goes into the journal copy first (and through
  the editor) before the package is rebuilt.

## Outputs
- `08_submission/manuscript/polish_report.json`
- `08_submission/manuscript/polish_log.md`
- `08_submission/manuscript/prepolish/` (fact-preservation snapshot)

## Hard rules
- Body text is continuous paragraphs (1.9.0; also checked by polish.py lint as `bullets_in_prose`). Lists only where a sentence truly cannot carry the content (rarely more than one short list per section); every result, count, criterion, covariate and sensitivity finding is written as a sentence. `prose_not_lists` fails above `body_list_items_max` items or `body_list_share_max` of the blocks.
- Wording only. Never change a number, citekey, artifact reference or conclusion strength.
- Do not re-take the snapshot to hide a failed fact-preservation diff.
- Do not add content or an AI-use disclosure during polishing.

## Close
```
.\.venv\Scripts\python.exe tools/wf.py check
.\.venv\Scripts\python.exe tools/wf.py advance --note "journal polish complete; facts preserved; abstract/main/reference limits pass; read by eye"
```
