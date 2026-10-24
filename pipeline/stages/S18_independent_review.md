# S18 - Independent publication-readiness review

Goal: exactly one independent subagent audits the complete manuscript, supplementary
Methods, every table and every rendered figure before the user edits them.
Details (what the reviewer must check, verdict meanings): `reference/stage_details/S18_independent_review.md`.

## Do
1. Do not change the inputs while the review runs. Open round 1 (its fixes are applied at S19):
```
.\.venv\Scripts\python.exe tools/review_round.py start --scope manuscript
```
   It writes `.wf/review_bundle/<round>/MANIFEST.md` (copies, hash-bound text copies, figure
   PNGs, a Word build of the draft with page previews when a converter exists) and prints the
   neutral brief and the `reviewed_artifacts` json block.
2. Delegate to the `medpaper-reviewer` agent with that ONE bundle path and the brief,
   unchanged. Add nothing about known deviations, earlier conclusions or what you expect. It
   reads as a first-time clinical reader, an editor checking engineering language and
   self-contained displays, and a methods/journal reviewer; it numbers every finding
   F1, F2 ... in every section and writes its full report to
   `.wf/review_bundle/<round>/report.md` - the only file it may write.
3. Copy that report unchanged (do not paraphrase findings) into
   `07_manuscript/independent_publishability_review.md` with headings `Verdict`,
   `Critical barriers`, `Scientific validity`, `Reporting completeness`,
   `Tables and supplementary material`, `Journal suitability`, `Required revisions`,
   `Post-revision outlook`, `Reader comprehension`, `Medical presentation` (each >= 80
   characters of findings), plus the unchanged `reviewed_artifacts` block.
4. Record the verdict (do not ask the user about findings here; S19 applies them):
```
.\.venv\Scripts\python.exe tools/wf.py decide independent_publishability "READY|REVISE|NOT_READY" --why "<one-sentence basis from the independent review>"
```

## Outputs
- `07_manuscript/independent_publishability_review.md`

## Gate
reader_review_coverage is incremental: a file is covered when any earlier review saw its
current bytes; after a change only the changed files need a `--delta` round, never a full
re-read. Live references, supplementary Methods clean, decision recorded. A low impact
factor is not a defect when the journal is current SCIE and a realistic fit.

## Close
```
.\.venv\Scripts\python.exe tools/wf.py check
.\.venv\Scripts\python.exe tools/wf.py advance --note "independent verdict=<READY|REVISE|NOT_READY>; critical barriers: <none or list>; frozen files unchanged"
```
