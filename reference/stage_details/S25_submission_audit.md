# S25 - Independent reader, editor and compliance audit of the confirmed package - details

> 1.15.0 supersedes older wording below where they differ: `package_review.py audit-start`
> writes the audit bundle - the FIRST audit is full, later ones re-check the previous findings
> plus new BLOCKING issues only - and `package_review.py audit-save [--from <reply>]` copies
> the reviewer's report verbatim (refused if a paper file changed during the audit).
> Engine-owned formatting (keep markers, ESM header, PDF language, CSL rendering, document
> properties) is reported as 'Engine issues' and never causes REVISE by itself. At the first
> REVISE offer the user the author final copy at once (the open items are printed). The
> final-copy check also covers PDFs (`final_copy.py export-pdf --docx ...` records
> provenance) and TIFF/PNG figures (byte-identical to a certified master). The reviewer may
> write its report file (it is no longer read-only).

> Long form of `pipeline/stages/S25_submission_audit.md` (moved out of the card in 1.12.0 so the
> card stays short). Read only the section you need; the card has the commands.
>
> 1.12.0 supersedes older wording below where they differ: long runs use `--wait` (one
> blocking call, heartbeat <= 30 s) and logs live in `.wf/logs/` (or `temp/logs/`);
> `wf check` prints failures + one summary line by default; in `deferred` visual mode no
> DEFER decision is recorded (the look is owed at S23); the `medpaper-reviewer` agent
> writes only its own `report.md` in the review bundle; declaration and section heading
> names come from `target_journal.json` (defaults otherwise).

## Purpose
Give the exact package approved by the user one final fresh reading immediately before
submission. The same independent reviewer must judge it from three complementary positions:
an ordinary scientific reader trying to understand the paper without backstage context, a
journal editor screening for avoidable defects, and a submission-compliance reviewer applying
the chosen journal's current official instructions.

## Procedure
1. Before delegation, verify that the package still matches the user's freeze:
```
.\.venv\Scripts\python.exe tools/package_review.py verify
```
   Stop and return to S24 if any file was added, removed or changed.
2. Delegate to exactly one independent read-only subagent for this frozen package revision:
   **the `medpaper-reviewer` agent**, which is `tools: ["read"]` and therefore cannot edit
   anything. Do not give it the intended verdict, prior reviewers' conclusions, or ask it to
   edit files - withholding your expectation is what makes the audit worth running. Tell it to
   read the actual package in normal submission order before consulting backstage QA, and to
   judge from all three positions its prompt defines: publication readiness,
   journal-guideline compliance, and reader/editor comprehension.
   It reports; you save the file in step 4.
   Give it:
   - `08_submission/package_review_freeze.json` and every frozen file listed there;
   - the selected journal metadata, `guidelines_extract.md`, and the cached official author
     instructions;
   - `bundle/manifest.json`, `SUBMISSION_CHECKLIST.md`, and `submission_qc.md` (both measured
     by `submission_qc.py`; the same rows already passed at S23, so this audit confirms);
   - hash-bound text copies of every DOCX/XLSX upload for the read-only reviewer, regenerated
     now: `.\.venv\Scripts\python.exe tools/package_review.py reader-copies` (each copy names
     its source SHA-256; never hand over an older temp extract).
3. Require the reviewer to inspect the actual upload files rather than trusting the manifest
   or earlier QA. It must perform all three lenses and report exact locations for every
   actionable finding:
   - **Reader comprehension:** passages, terminology, abbreviations, referents, transitions,
     methods, tables, figures or legends that cannot be understood from the submitted files;
     contradictions, unexplained logic jumps and claims whose evidence is hard to locate;
   - **Editorial screening:** typographical, grammatical and punctuation errors; duplicated,
     missing or unfinished text; template residue and placeholders; inconsistent spelling,
     capitalization, tense, units, decimals, statistical notation, headings, numbering,
     citations, labels and terminology; title/abstract/keywords that misstate or obscure the
     paper; and any obvious issue likely to trigger an avoidable query or desk rejection;
   - **Journal compliance:** compare the frozen package with the official guide and report:
     - required, missing, extra or incorrectly formatted upload items and filenames;
     - article type, title page, abstract, keywords, word/reference limits and reference style;
     - any title-page reference count against the distinct citations actually used in the
       manuscript, never against the candidate-library or bibliography-file size;
     - author/affiliation/correspondence facts, declarations, ethics, funding, conflicts and
       data-availability consistency across all applicable files, without inventing facts;
     - figure/table callouts, numbering, legends/captions, abbreviations, file types, resolution
       and supplement correspondence;
     - mismatched titles, counts, versions, values, labels, citations or statements between
       manuscript, cover letter, title page, tables, figures, supplements and checklist;
     - portal-only tasks that cannot be verified from local files, clearly separated from
       defects in the package.
4. Save the review as `project/08_submission/independent_submission_audit.md` with headings
   `Verdict`, `Reader comprehension`, `Editorial screening and low-level errors`,
   `Guideline compliance`, `Required files and omissions`, `Cross-file consistency`,
   `Formatting and technical checks`, `Issues requiring correction`, `Final recommendation`.
   Under `Verdict`, write the exact `Freeze ID: <freeze_id>` from
   `package_review_freeze.json` so a stale review cannot be attached to a changed package.
   Every finding names the affected file and, where available, page plus heading, paragraph,
   table cell or figure panel; include only a short identifying fragment rather than rewriting
   the manuscript. Classify it as `BLOCKING`, `MINOR` or `PREFERENCE`, and cite the exact
   official rule or cross-file evidence when applicable. Use `PASS` only when there is no
   objective low-level error, reader-comprehension problem, material omission, noncompliance
   or unexplained mismatch. Use `REVISE` for any correctable `BLOCKING` or `MINOR` defect and
   `BLOCKED` when a required fact or file can only come from the user or journal portal.
   Pure preferences do not prevent `PASS` and must be clearly separated from defects.
5. Verify the freeze again after the reviewer returns. Then record the actual verdict:
```
.\.venv\Scripts\python.exe tools/wf.py decide submission_package_independent_audit "PASS|REVISE|BLOCKED" --why "<concise evidence-based basis>"
```
6. For `REVISE`, loop to S24 and run one review round there with these findings as its review:
   fix on your own judgement, report once, ask the single another-round question; audit the
   new freeze after the user's no-further-review answer:
```
.\.venv\Scripts\python.exe tools/wf.py loop --to S24_package_human_review --why "<material audit defects requiring correction and renewed user confirmation>"
```
   For `BLOCKED`, ask only for the missing user-owned fact/file. If the package changes, use
   the same S24 loop. Do not repeat an independent audit of an unchanged freeze.
   For any correction, use `tools/rework.py` to route content to its source; only a verified
   visible-text-preserving layout edit may remain solely in Word at S24.

## Author final copy (1.9.0)
```
.\.venv\Scripts\python.exe tools/final_copy.py record --edit "<one manual edit>" --edit "<another>" --words "<author's words>"
.\.venv\Scripts\python.exe tools/final_copy.py check
.\.venv\Scripts\python.exe tools/wf.py decide submission_package_independent_audit PASS_AUTHOR_FINAL_COPY --why "<audit verdict; final-copy check passed>"
```

## Outputs
- `08_submission/independent_submission_audit.md`

## Hard rules
- Legal end state (1.9.0): when the author chooses to finish journal requirements by hand in a copy of the uploads, put the edited files in `08_submission/final_copy/` (same names as in the bundle), record the edits and check them; numbers, citations and display references must be unchanged and blinding intact. Then record `submission_package_independent_audit PASS_AUTHOR_FINAL_COPY` and advance.
- The independent subagent is read-only and audits exactly the user-confirmed frozen files.
- Earlier S18 publishability review and S23 automated/visual QA do not substitute for this
  journal-specific final audit.
- A checklist assertion is not evidence; inspect the actual file and official rule.
- Read as a first-time reader and editor; do not treat prior automated QA or scientific review
  as proof that the prose is understandable or free of elementary errors.
- The subagent reports defects but never edits the frozen package. Corrections happen in an
  S24 review round, then the user's no-further-review answer and a new freeze.
- A reference-count field is optional when the journal is silent, but if present it must match
  the actual citation set in both the canonical title page and frozen Word file.
- `PASS` is required to complete the pipeline. Portal-only user tasks may be listed, but an
  unmet required local upload or unresolved cross-file mismatch is not a pass.
- `analysis_reproduces` and `reporting_checklist_complete` must pass here, so the audit may
  state that the submitted numbers re-execute and, when a checklist is required, every item
  is located.

## Close
```
.\.venv\Scripts\python.exe tools/wf.py check
.\.venv\Scripts\python.exe tools/wf.py advance --note "independent final submission audit=PASS; frozen package unchanged; remaining portal-only user tasks=<none or list>"
```
