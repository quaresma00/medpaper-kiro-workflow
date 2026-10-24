# S20 - Select the most realistic current SCIE journal

Goal: pick a legitimate current SCIE venue with realistic acceptance odds, freeze its
author instructions as typed fields, and open the journal variant.
Details (typed-field JSON, docx_style.json template, evidence rules, switching journals):
`reference/stage_details/S20_journal.md`.

## Do
1. Screen candidates that recently published the same design/topic: currently SCIE, current
   JCR Q1-Q4, no integrity warning; evidence <= 90 days old (official source first; a
   third-party mirror only when the official one needs a login).
2. `08_submission/journal_shortlist.md` (`Eligibility screen`, `Ranking basis`, `Shortlist`,
   `Reject-fallback cascade`): 5-8 candidates ranked by acceptance probability and fit.
3. Ask the user to choose (never default to the highest impact factor).
4. Snapshot the official author guide to `08_submission/cache/` and write
   `08_submission/target_journal.json` with typed fields: `limits` (+ `source`),
   `word_count_scope`, `declarations_order`, `main_text_headings`, `keywords`, `legend_style`,
   `supplementary_aliases`, `reference_separator`, `si_format`, `abbreviation_placement`
   (`self_contained` unless the guide requires `central_required` + `abbreviation_rule_source`),
   `line_numbers` (`continuous|per_page|none`), `journal_requires_checklist` only if required,
   `presentation` {font_min_pt, figure_width_mm, panel_label_case, line_art_dpi,
   number_format, spelling, heading_names, in_figure_title} confirming/replacing
   `01_protocol/journal_profile.json` (a change is a presentation re-render, never science).
5. `08_submission/guidelines_extract.md` (sourced sections) and `08_submission/docx_style.json`
   (journal values; fallbacks listed under `fallbacks`).
6. Over the display limit? Write `08_submission/display_reallocation.json` and apply it as a
   presentation rework round. Check the CSL against the guide's example reference:
```
.\.venv\Scripts\python.exe tools/manuscript/csl_check.py --csl project/08_submission/journal.csl --example "<official example reference>"
```
7. Open the variant (all journal edits go to `08_submission/manuscript/`, never `07_manuscript/`):
```
.\.venv\Scripts\python.exe tools/manuscript/scientific_freeze.py open-variant --journal "<chosen journal>"
```
   Switching journal later: `wf loop --to S20_journal`, then `scientific_freeze.py reset-journal` (details).

## Outputs
- `08_submission/journal_shortlist.md`
- `08_submission/target_journal.json`
- `08_submission/guidelines_extract.md`
- `08_submission/docx_style.json`
- `08_submission/manuscript/` (journal variant)

## Gate
guidelines sourced, docx style, display plan fits the journal, presentation params
confirmed, freeze intact and variant ready (non-overridable). Never state indexing, fees
or rules from memory.

## Close
```
.\.venv\Scripts\python.exe tools/wf.py decide journal_chosen "<journal>" --why "<user choice and acceptance-fit rationale>"
.\.venv\Scripts\python.exe tools/wf.py check
.\.venv\Scripts\python.exe tools/wf.py advance --note "target=<journal>; current SCIE/JCR verified; Word rules frozen; journal deltas=<...>"
```
