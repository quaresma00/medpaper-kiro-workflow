# S24 - Review rounds on the submission package, then the user's confirmation - details

> 1.15.0 supersedes older wording below where they differ: after any edit run `wf rebuild
> --wait`. Meaning checks compare the last confirmed copy with the current one, per sentence
> pair, in ONE bundle per round; the author may override any pair (also a reviewer's
> 'changed') with `rework.py meaning-decide --pair <id|hash> --verdict unchanged --words
> "<author's words>"` (shown in the round summary). The reviewer writes its report itself;
> when the host refuses, save its reply and use `review_round.py ingest --from <file>` /
> `rework.py meaning-ingest --from <file>` (verbatim). PREFERENCE findings may close as one
> group: `review_round.py close ... --preference-group "<reason>"`.

> Long form of `pipeline/stages/S24_package_human_review.md` (moved out of the card in 1.12.0 so the
> card stays short). Read only the section you need; the card has the commands.
>
> 1.12.0 supersedes older wording below where they differ: long runs use `--wait` (one
> blocking call, heartbeat <= 30 s) and logs live in `.wf/logs/` (or `temp/logs/`);
> `wf check` prints failures + one summary line by default; in `deferred` visual mode no
> DEFER decision is recorded (the look is owed at S23); the `medpaper-reviewer` agent
> writes only its own `report.md` in the review bundle; declaration and section heading
> names come from `target_journal.json` (defaults otherwise).

## Purpose
Improve the assembled journal package in subagent review rounds, report each round once, and
freeze the exact files when the user confirms with the exact sentence 我确认这一版.

## This stage needs the user
Only for one answer per round (and for user-owned facts such as authorship or funding). Do not
ask permission per finding or per small change. Present clickable paths to
`08_submission/bundle/`, `SUBMISSION_CHECKLIST.md` and the rendered previews in each report.

## One round
1. **Review.**
```
.\.venv\Scripts\python.exe tools/review_round.py start --scope package
```
   Invoke the read-only `medpaper-reviewer` agent as a subagent with the printed bundle files,
   their fresh `.wf/review_text/` copies (DOCX/XLSX), the journal metadata,
   `guidelines_extract.md` and the cached official instructions. Ask for reader, editor and
   journal-compliance findings with exact locations. After an S25 `REVISE`, the S25 audit is
   this round's review: start the round (`--delta`) and use its findings instead of a new read.
   If the user edited files themselves, run `tools/package_content.py verify` first.
2. **Fix on your own judgement.** Apply every fix that improves the package. Journal copy,
   title page, cover letter and statements live in `08_submission/manuscript/` and
   `08_submission/`; rebuild the affected DOCX in place and re-run `bundle_complete`,
   `docx_bundle_ready`, `submission_checklist_measured` and visual QA for changed files.
   A scientific change (07_manuscript, results, tables, figures, references) goes through
   `tools/rework.py batch --sealed --plan ...` (then `tools/rework.py status` lists the only
   files you may change; `check`, `mark`, `close`) and back to S19 for a review round and
   re-freeze. A DOCX wording edit must come from its source; a visible-text-preserving layout
   edit may stay in Word (`package_content.py verify` proves it). Order: edit the source,
   `rework.py check` (classification), then rebuild DOCX/PDF. `package_content.py capture
   --replace` is legal only inside a revision round that reopened S23 for a non-layout item
   (the tool refuses otherwise); never recapture to bless drift. Never invent user-owned facts; list them as kept.
3. **Close and report once.**
```
.\.venv\Scripts\python.exe tools/review_round.py close --scope package --findings critical=<n>,major=<n>,minor=<n> --finding <id> <category> <status> "<one line>" --change <file> "<one line>" --kept "<id>" "<why>"
```
   List every finding once: `--finding <id> <numbers|grouping|conclusion_strength|other> <changed|kept|author> "<one line>"`.
   numbers/grouping/conclusion_strength findings are never `kept` on your preference: change
   them, or mark `author` and list them as pending author decisions (record each answer with
   `review_round.py author <id> change|keep --words "<user's words>"`).
   One concise message: issues by severity, changes (file + one line), what was kept and why,
   the bundle paths, pending author decisions. One question:
   > 本轮审阅与修改已完成。需要再审一轮请直接说明；确认当前版本请回复：我确认这一版
   Only that exact sentence (or "I confirm this version") confirms; "无需继续审阅", "OK",
   "可以" do not - ask again for the sentence.
4. **Record the answer.**
```
.\.venv\Scripts\python.exe tools/review_round.py decide another_round --scope package --words "<user's words>"
.\.venv\Scripts\python.exe tools/review_round.py decide no_further_review --scope package --words "我确认这一版"
```
   `no_further_review` records `submission_package_user_confirmed=OK` bound to the round and
   version hash (optional on explicit user request only: `review_round.py export --scope package`), and
   writes `08_submission/package_human_review.md`.

## Freeze the package
```
.\.venv\Scripts\python.exe tools/package_review.py freeze
```
S25 audits exactly these frozen files.

## Quiet checks (1.9.0)
```
.\.venv\Scripts\python.exe tools/rework.py check --quiet
.\.venv\Scripts\python.exe tools/wf.py check --summary
```

## Outputs
- `08_submission/package_human_review.md` (generated by `review_round.py`)
- `08_submission/package_review_freeze.json`

## Hard rules
- 1.11.0: give the reviewer the one bundle path `review_round.py start` prints and its
  neutral brief (never known deviations or earlier conclusions). Save the full report and
  `close --report <file>`: every F-numbered finding of every section is listed
  (`--finding`), kept ones with `--kept ID "reason"` (`review_findings_closed`).
- 1.11.0: before `rework.py check`, `rework.py preview` shows presentation vs science
  without recording anything. A number inside a label (Online Resource 2, Table S3, panel or
  item numbers) is not a fact. Writes outside the sealed round's files are refused at write
  time. An S19 return never happens automatically: check/seal STOP and you ask the user;
  only the words '我确认回退' (`rework.py confirm-rewind --words ...` or `seal
  --rewind-words ...`) authorise it.
- After the S19 freeze a revision item is classified by content at `rework.py check` (1.9.0): if numbers, citations, table/figure references, table cells and figure data are unchanged it is a PRESENTATION change - only the deterministic checks rerun, the freezes record a presentation delta, there is no return to S19, no new review round and no re-confirmation; just report the change summary to the user. Changed facts go back to S19 as before. Kinds: `journal-switch` (was `journal`; full rewind) and `journal-format` (CSL, target_journal.json formatting fields; presentation).
- A deleted source is credited with `rework.py mark --deleted-file <path>`.
- Confirmation binds the uploaded files by visible content; internal QC, notes and receipts never invalidate the user's OK.
- Any change after the freeze invalidates it; run another round and freeze again.
- Never infer or rewrite user-owned authorship, affiliation, funding, ethics or conflict data.
- Save tokens with delta rounds and scoped rebuilds, never by skipping a fix, validation or
  visual QA.

## Close
```
.\.venv\Scripts\python.exe tools/wf.py check
.\.venv\Scripts\python.exe tools/wf.py advance --note "package review rounds=<n>; last=<round id>; user: no further review; freeze=<freeze_id>"
```
