# S20 - Select the most realistic current SCIE journal

Goal: pick a legitimate current SCIE venue with realistic acceptance odds, freeze its
author instructions as typed fields, and open the journal variant.
Details (typed fields, docx style, evidence, browser, switching):
`reference/stage_details/S20_journal.md`.

## Do
1. Screen journals that recently published the same design/topic: current SCIE, JCR Q1-Q4,
   no integrity warning; evidence <= 90 days old (official source first).
2. `08_submission/journal_shortlist.md` (`Eligibility screen`, `Ranking basis`, `Shortlist`,
   `Reject-fallback cascade`): 5-8 candidates ranked by acceptance probability and fit.
3. Ask the user to choose (never default to the highest impact factor).
4. Official guide: `wf journal lookup --issn <ISSN>`. Blocked/JS page: its BROWSER steps
   (`playwright` tool: capture to `.playwright-mcp/`, `wf guidelines ingest --from <capture>
   --url <final URL>`, sub-pages `--append`; the user does verification/login in the browser
   window) or the manual save path. MJL/JCR: `--kind indexing --screenshot <png>`. Never
   solve checks or type credentials.
5. `08_submission/target_journal.json` typed fields: `limits` (+ `source`; only an explicit
   numeric rule is a cap - never derive word caps from a page count; an estimate goes in
   `limits.estimated`), `separate_display_files`, `supplementary_label`, `abbreviation_list`,
   `figure_dpi`, `word_count_scope`, `declarations_order`, `main_text_headings`, `keywords`,
   `legend_style`, `supplementary_aliases`, `reference_separator`, `si_format`,
   `abbreviation_placement` (`self_contained` unless `central_required` + source),
   `line_numbers`, `journal_requires_checklist` only if required, `csl` {style_id, issn}
   (`tools/refs/csl_index.py fetch --issn`), `presentation`, 1.18.0 `abstract`,
   `title_page`, `highlights`/`key_points`, `cover_letter`, `required_uploads`, `figure`,
   `orcid_required`; 1.19.0 `title_page.placement`, `figures.placement`, `tables.placement`,
   `supplementary_file_pattern` ONLY from a guide rule (requirement, quote + line; 'e.g.'
   is no mandate). Absent = default.
6. `08_submission/guidelines_extract.md` citing `guidelines_source.txt` lines (`L0012`),
   `08_submission/docx_style.json` (fallbacks under `fallbacks`) and
   `08_submission/guideline_requirements.json` (`reference/guideline_requirements.schema.json`):
   every rule for this article type with verbatim `quote`, `lines`, `category`, `rule`,
   `enforcement` auto|builder|manual|portal|n.a.; silent categories in `not_mentioned` (terms
   searched), other article types' lines in `not_applicable`. Over the display limit?
   `08_submission/display_reallocation.json` as a presentation rework round.
7. Open the variant (all journal edits go to `08_submission/manuscript/`, never `07_manuscript/`):
```
.\.venv\Scripts\python.exe tools/manuscript/scientific_freeze.py open-variant --journal "<chosen journal>"
```
   Rejected later? `wf journal switch --to "<new>" --confirm-old "<old>" --why "..."` (one
   command; then a new chat). Never edit S20 files in place for a new journal.

## Outputs
- `08_submission/journal_shortlist.md`, `target_journal.json`, `guidelines_extract.md`,
  `docx_style.json`, `guideline_requirements.json`, `manuscript/` (journal variant)

## Gate
guidelines sourced (cited lines), indexing evidence, requirement list mapped (every obligation line covered,
quotes verbatim, numbers = typed fields), journal layer clean, docx style, display plan fits,
presentation params confirmed, freeze intact and variant ready (non-overridable). Never state
indexing, fees or rules from memory.

## Close
```
.\.venv\Scripts\python.exe tools/wf.py decide journal_chosen "<journal>" --why "<user choice and acceptance-fit rationale>"
.\.venv\Scripts\python.exe tools/wf.py check
.\.venv\Scripts\python.exe tools/wf.py advance --note "target=<journal>; current SCIE/JCR verified; Word rules frozen; journal deltas=<...>"
```
