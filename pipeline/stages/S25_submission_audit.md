# S25 - Independent reader, editor and compliance audit of the confirmed package

Goal: one fresh reading of the exact package the user confirmed, by exactly one independent
read-only subagent, from three positions: first-time reader, editor, journal compliance.
Details (what the reviewer must inspect, finding format, verdict rules): `reference/stage_details/S25_submission_audit.md`.

## Do
1. Verify the freeze; return to S24 if anything changed:
```
.\.venv\Scripts\python.exe tools/package_review.py verify
.\.venv\Scripts\python.exe tools/package_review.py reader-copies
```
2. Write the audit bundle (the FIRST audit is full; after a REVISE it is a re-audit: previous
   findings RESOLVED/OPEN plus new BLOCKING only; engine-owned formatting is an "Engine
   issue", never REVISE by itself):
```
.\.venv\Scripts\python.exe tools/package_review.py audit-start
```
   Give the `medpaper-reviewer` agent the printed MANIFEST path only - no expected verdict,
   no earlier conclusions, never paraphrase.
3. It writes `report.md` in that bundle; copy it verbatim (refused if a paper file changed
   during the audit; `--from <saved reply>` when it could not write):
```
.\.venv\Scripts\python.exe tools/package_review.py audit-save
```
4. Verify the freeze again, then record the verdict:
```
.\.venv\Scripts\python.exe tools/wf.py decide submission_package_independent_audit "PASS|REVISE|BLOCKED" --why "<concise evidence-based basis>"
```
5. `REVISE`: `wf decide` prints the open items; offer the user BOTH routes at once: the
   author final copy (step 6) or one S24 round with these findings, then a new freeze:
```
.\.venv\Scripts\python.exe tools/wf.py loop --to S24_package_human_review --why "<material audit defects requiring correction and renewed user confirmation>"
```
   `BLOCKED`: ask only for the missing user-owned fact or file.
6. Author final copy (the author finishes hand edits in `08_submission/final_copy/`; numbers
   traceable to results, citations and display references unchanged):
```
.\.venv\Scripts\python.exe tools/final_copy.py record --edit "<one manual edit>" --words-file <utf8_file_with_author_words>
.\.venv\Scripts\python.exe tools/final_copy.py check
.\.venv\Scripts\python.exe tools/wf.py decide submission_package_independent_audit PASS_AUTHOR_FINAL_COPY --why "<audit verdict; final-copy check passed>"
```

## Outputs
- `08_submission/independent_submission_audit.md`

## Gate
audit matches the freeze, decision PASS or PASS_AUTHOR_FINAL_COPY, final copy verified,
analysis reproduces, reporting checklist, live references. Do not repeat an audit of an
unchanged freeze.

## Close
```
.\.venv\Scripts\python.exe tools/wf.py check
.\.venv\Scripts\python.exe tools/wf.py advance --note "independent final submission audit=PASS; frozen package unchanged; remaining portal-only user tasks=<none or list>"
```
