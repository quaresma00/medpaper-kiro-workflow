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
Give the journal's copy of the manuscript one language pass without changing a number, citekey,
figure/table reference or scientific claim.

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
5. Write `polish_log.md` with `AI patterns removed`, `Language changes by section`, `House
   style decisions`, `Cut to meet journal limits`, `Read by eye`, `Tier-B phrases kept`.
6. Check what the journal adaptation actually cost, and put the numbers in `polish_log.md`
   under `Cut to meet journal limits`:
```
.\.venv\Scripts\python.exe tools/manuscript/scientific_freeze.py delta
```
7. Reread the complete manuscript and optional supplementary Methods, then record
   `polish_reviewed YES` with a concrete reason.

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
