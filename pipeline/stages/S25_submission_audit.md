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
2. Delegate to the `medpaper-reviewer` agent (writes only its report file). Give it
   `package_review_freeze.json` and every frozen file, the journal metadata,
   `guidelines_extract.md` and cached guide, `bundle/manifest.json`, `SUBMISSION_CHECKLIST.md`,
   `submission_qc.md` and the fresh hash-bound text copies. Never give it the verdict you
   expect or earlier conclusions; context for yourself comes from `wf handoff`.
3. Save its report verbatim as `08_submission/independent_submission_audit.md` with headings
   `Verdict` (incl. `Freeze ID: <freeze_id>`), `Reader comprehension`,
   `Editorial screening and low-level errors`, `Guideline compliance`,
   `Required files and omissions`, `Cross-file consistency`, `Formatting and technical checks`,
   `Issues requiring correction`, `Final recommendation`. Findings: file + location,
   BLOCKING / MINOR / PREFERENCE. Do not paraphrase.
4. Verify the freeze again, then record the verdict:
```
.\.venv\Scripts\python.exe tools/wf.py decide submission_package_independent_audit "PASS|REVISE|BLOCKED" --why "<concise evidence-based basis>"
```
5. `REVISE`: one S24 review round with these findings, then a new freeze:
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
