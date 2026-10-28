# S22 - Journal-specific, fact-preserving polish

Goal: one language pass on the journal copy (`08_submission/manuscript/`, never
`07_manuscript/`) without changing a number, citekey, display reference or claim.
Details (variant comparison, trim authorisation, log headings): `reference/stage_details/S22_polish.md`.

## Do
1. Snapshot before editing (tools resolve the variant themselves):
```
.\.venv\Scripts\python.exe tools/text/polish.py snapshot
```
2. Each section was already polished at its own stage (`section_language_clean` at
   S08/S09/S14/S16/S17). Here only: cross-section consistency (abbreviations defined once,
   spelling variant, P/p style, terminology) and the journal's style - abstract structure,
   limits, headings. Continuous prose; Keywords right after the Abstract; References
   heading and Figure legends kept.
```
.\.venv\Scripts\python.exe tools/text/polish.py lint
.\.venv\Scripts\python.exe tools/text/polish.py diff
```
   Restore and redo any edit that loses or adds a number, citation or display reference.
   A cut that drops facts needs the user's authorisation (`journal_trim_authorised YES`).
3. Measure the journal adaptation, then write `polish_log.md` (`AI patterns removed`,
   `Language changes by section`, `House style decisions`, `Cut to meet journal limits`,
   `Read by eye`, `Tier-B phrases kept`):
```
.\.venv\Scripts\python.exe tools/manuscript/scientific_freeze.py delta
```
4. Reread everything, then record `polish_reviewed YES` with a concrete reason.

## Outputs
- `08_submission/manuscript/polish_report.json`
- `08_submission/manuscript/polish_log.md`
- `08_submission/manuscript/prepolish/` (fact-preservation snapshot)

## Gate
polish_complete (one gate: snapshot, lint report, facts preserved), AI tells, style,
journal limits, structure, references live, abbreviations, numbers, display references,
variant preserves science. Never re-take the snapshot to hide a failed diff.

## Close
```
.\.venv\Scripts\python.exe tools/wf.py check
.\.venv\Scripts\python.exe tools/wf.py advance --note "journal polish complete; facts preserved; abstract/main/reference limits pass; read by eye"
```
