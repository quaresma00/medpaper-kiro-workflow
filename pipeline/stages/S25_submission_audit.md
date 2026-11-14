# S25 - Final verification of the confirmed package (audit only for older freezes)

Goal (1.26.0): the independent audit ran at S24 before the user's confirmation and the freeze
binds that audit round. S25 proves the frozen package is exactly what the auditor read and the
user confirmed, records that audit as the S25 audit file and runs the final deterministic
checks - no reviewer. Details and the S25 audit for freezes taken before 1.26.0:
`reference/stage_details/S25_submission_audit.md`.

## Do
1. Verify the freeze (return to S24 if anything changed) and record the bound S24 audit:
```
.\.venv\Scripts\python.exe tools/package_review.py verify
.\.venv\Scripts\python.exe tools/package_review.py record-audit
```
   `record-audit` copies that round's report verbatim to
   `08_submission/independent_submission_audit.md`. It refuses a freeze from before 1.26.0
   (no audited round in it): then run the audit here - `package_review.py audit-start`, give
   the `medpaper-reviewer` agent the printed MANIFEST path only (no expected verdict, no
   earlier conclusions), then `package_review.py audit-save` (details: "Before 1.26.0").
2. Final checks - reproduction proof, live references, bundle, DOCX preflight, compliance
   matrix (every row judged agree/disagree), checklist, freezes:
```
.\.venv\Scripts\python.exe tools/wf.py check
```
3. Record the verdict (PASS needs the last audit verdict PASS; it refreshes the dated package
   folder `submission_packages/<journal>_<date>/` - give the user its path):
```
.\.venv\Scripts\python.exe tools/wf.py decide submission_package_independent_audit "PASS|REVISE|BLOCKED" --why "<audit round + verdict; freeze unchanged; final checks green>"
```
4. `REVISE` (the last audit said REVISE, or a final check needs a package change): offer the
   user BOTH routes at once - the author final copy (step 5) or one S24 re-audit round, then a
   new confirmation and freeze:
```
.\.venv\Scripts\python.exe tools/wf.py loop --to S24_package_human_review --why "<material defects requiring correction and renewed user confirmation>"
```
   `BLOCKED`: ask only for the missing user-owned fact or file.
5. Author final copy (the author finishes hand edits in `08_submission/final_copy/`; numbers
   traceable to results, citations and display references unchanged):
```
.\.venv\Scripts\python.exe tools/final_copy.py record --edit "<one manual edit>" --words-file <utf8_file_with_author_words>
.\.venv\Scripts\python.exe tools/final_copy.py check
.\.venv\Scripts\python.exe tools/wf.py decide submission_package_independent_audit PASS_AUTHOR_FINAL_COPY --why "<audit verdict; final-copy check passed>"
```

## Outputs
- `08_submission/independent_submission_audit.md`

## Gate
audit bound to the freeze (1.26.0: the S24 round the freeze names), audit ready, every matrix
row judged (a disagreement or missing requirement blocks PASS), manual rows have evidence,
decision PASS or PASS_AUTHOR_FINAL_COPY, final copy verified, analysis reproduces, reporting
checklist, live references. Never repeat an audit of an unchanged freeze.

## Close
```
.\.venv\Scripts\python.exe tools/wf.py check
.\.venv\Scripts\python.exe tools/wf.py advance --note "final verification=PASS; audit round=<id>; frozen package unchanged; remaining portal-only user tasks=<none or list>"
```
