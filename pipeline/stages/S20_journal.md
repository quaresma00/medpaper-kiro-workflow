# S20 - Select the most realistic current SCIE journal

Goal: pick a legitimate current SCIE venue with realistic acceptance odds, freeze its
author instructions as typed fields, and open the journal variant.
Details (typed-field JSON, docx_style.json template, evidence rules, switching journals):
`reference/stage_details/S20_journal.md`.

## Do
1. Screen candidates that recently published the same design/topic: currently SCIE, current
   JCR Q1-Q4, no integrity warning; evidence <= 90 days old (official source first).
2. `08_submission/journal_shortlist.md` (`Eligibility screen`, `Ranking basis`, `Shortlist`,
   `Reject-fallback cascade`): 5-8 candidates ranked by acceptance probability and fit.
3. Ask the user to choose (never default to the highest impact factor).
4. Official guide: `wf journal lookup --issn <ISSN>` (DOAJ/OpenAlex/NLM + publisher URL table,
   one polite GET). Blocked (403/captcha)? It prints the URL: the user saves the page in the
   browser (HTML only, or PDF), then `wf guidelines ingest --from <file> --url <URL>`. Never
   log in, bypass bot checks or use reader proxies. MJL page as PDF: `--kind indexing`.
5. `08_submission/target_journal.json` typed fields: `limits` (+ `source`; only an explicit
   numeric rule is a cap - never derive word caps from a page count; an estimate goes in
   `limits.estimated`), `separate_display_files`, `supplementary_label`, `abbreviation_list`,
   `figure_dpi`, `word_count_scope`, `declarations_order`, `main_text_headings`, `keywords`,
   `legend_style`, `supplementary_aliases`, `reference_separator`, `si_format`,
   `abbreviation_placement` (`self_contained` unless `central_required` + source),
   `line_numbers`, `journal_requires_checklist` only if required, `csl` {style_id, issn} from
   the lookup (`tools/refs/csl_index.py fetch --issn <ISSN>`), `presentation` {font_min_pt,
   figure_width_mm, panel_label_case, line_art_dpi, number_format, spelling, heading_names,
   in_figure_title} (complete after a journal switch; a change is a re-render via
   `wf rebuild`, never science).
6. `08_submission/guidelines_extract.md` citing `guidelines_source.txt` lines (`L0012`) and
   `08_submission/docx_style.json` (fallbacks listed under `fallbacks`). Over the display
   limit? `08_submission/display_reallocation.json` as a presentation rework round.
7. Open the variant (all journal edits go to `08_submission/manuscript/`, never `07_manuscript/`):
```
.\.venv\Scripts\python.exe tools/manuscript/scientific_freeze.py open-variant --journal "<chosen journal>"
```
   Rejected later? `wf journal switch --to "<new>" --confirm-old "<old>" --why "..."` (one
   command; then the user opens a new chat). Never edit S20 files in place for a new journal.

## Outputs
- `08_submission/journal_shortlist.md`
- `08_submission/target_journal.json`
- `08_submission/guidelines_extract.md`
- `08_submission/docx_style.json`
- `08_submission/manuscript/` (journal variant)

## Gate
guidelines sourced (cited lines), journal layer clean, docx style, display plan fits,
presentation params confirmed, freeze intact and variant ready (non-overridable). Never state
indexing, fees or rules from memory.

## Close
```
.\.venv\Scripts\python.exe tools/wf.py decide journal_chosen "<journal>" --why "<user choice and acceptance-fit rationale>"
.\.venv\Scripts\python.exe tools/wf.py check
.\.venv\Scripts\python.exe tools/wf.py advance --note "target=<journal>; current SCIE/JCR verified; Word rules frozen; journal deltas=<...>"
```
