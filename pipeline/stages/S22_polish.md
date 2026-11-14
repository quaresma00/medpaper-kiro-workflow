# S22 - Journal-specific, fact-preserving polish

Goal: adapt the journal copy (`08_submission/manuscript/`, never `07_manuscript/`) without
changing a number, citekey, display reference or claim. No second full polish (1.25.0).
Details (variant comparison, trim authorisation, log headings): `reference/stage_details/S22_polish.md`.

## Do
1. Snapshot before editing (tools resolve the variant themselves):
```
.\.venv\Scripts\python.exe tools/text/polish.py snapshot
```
2. Each section was already polished at its own stage (`section_polished`: drafted by the
   clinical writer, polished at once by the medical editor, S07-S17); do not re-polish sections
   here. Here only: (a) cross-section consistency a single section cannot show, (b) the
   journal's style - abstract structure, limits, headings - and (c) the paragraphs you change.
   Continuous prose; Keywords right after the Abstract; References heading and Figure legends kept.
```
.\.venv\Scripts\python.exe tools/text/polish.py crosscheck
.\.venv\Scripts\python.exe tools/text/polish.py lint
.\.venv\Scripts\python.exe tools/text/polish.py diff
```
   Read the crosscheck report, the lint/diff output and the paragraphs you change - not the
   whole manuscript (unless the user asks). Restore and redo any edit that loses or adds a
   number, citation or display reference. A cut that drops facts needs the user's
   authorisation (`journal_trim_authorised YES`).
3. 1.25.0: every paragraph changed after assembly (trims, journal edits, review rounds) goes to
   the medical editor - only those paragraphs:
```
.\.venv\Scripts\python.exe tools/manuscript/writer_bundle.py edit --section manuscript
.\.venv\Scripts\python.exe tools/manuscript/writer_bundle.py polished --section manuscript
```
4. Measure the journal adaptation, then write `polish_log.md` with the headings
   `Cross-section consistency fixes`, `Journal adaptation`,
   `Re-polished paragraphs (editor receipts)`, `Cut to meet journal limits`,
   `Tier-B phrases kept`:
```
.\.venv\Scripts\python.exe tools/manuscript/scientific_freeze.py delta
```
5. Record `polish_reviewed YES` with a concrete reason (what the report, lint and diff showed).

## Outputs
- `08_submission/manuscript/polish_report.json`, `crosscheck_report.json`
- `08_submission/manuscript/polish_log.md`
- `08_submission/manuscript/prepolish/` (fact-preservation snapshot)

## Gate
polish_complete (snapshot, lint report, facts preserved, log headings), cross-section
consistency (abbreviation redefined / used before definition, abstract number not in the
Results or tables block on 1.25.0+), changed paragraphs polished, AI tells, style, journal
limits, structure, references live, abbreviations, numbers, display references, variant
preserves science. Never re-take the snapshot to hide a failed diff.

## Close
```
.\.venv\Scripts\python.exe tools/wf.py check
.\.venv\Scripts\python.exe tools/wf.py advance --note "journal adaptation complete; facts preserved; limits pass; cross-section report clean; changed paragraphs re-polished"
```
