# S20 - Select the most realistic current SCIE journal

Goal: pick a legitimate current SCIE venue with realistic acceptance odds, freeze its
author instructions as typed fields, and open the journal variant.
Details (typed fields, docx style, evidence, browser, switching, 1.22.0 linked pages and
difference list): `reference/stage_details/S20_journal.md`.

## Do
1. Journal named by the user (`wf decisions show`)? Verify it only (SCIE, JCR, integrity):
   `journal_shortlist.md` needs only `Eligibility screen`; no shortlist, never re-ask.
2. Otherwise screen journals that recently published the same design/topic (current SCIE,
   JCR Q1-Q4, no integrity warning, evidence <= 90 days, official source first) and write
   `08_submission/journal_shortlist.md` (`Eligibility screen`, `Ranking basis`, `Shortlist`,
   `Reject-fallback cascade`): 5-8 candidates by acceptance probability and fit. Ask the
   user to choose (never default to the highest impact factor); `wf decisions set`.
3. Official guide: `wf journal lookup --issn <ISSN>`. Failed GET/JS page: the BROWSER is
   the default fallback (`playwright`: capture to `.playwright-mcp/`, `wf guidelines ingest
   --from <capture> --url <final URL>`, sub-pages `--append`; the user does verification/
   login in the window), else the manual save. MJL/JCR: `--kind indexing --screenshot
   <png>`. Never solve checks or type credentials.
4. Every guide sentence that sends you to another page for rules (artwork, editorial
   policies, article type, with or without URL): ingest it with `--append`, or record it in
   `linked_pages` with an n.a. reason (gate, 1.22.0).
5. `08_submission/target_journal.json` typed fields (list in the details): `limits`
   (+ `source`; only an explicit numeric rule is a cap - never derive word caps from a
   page count), `abbreviation_list` (`none|after_keywords|after_conclusions`), `page_breaks`
   (`allowed|none`), `csl` {style_id, issn}, `title_page.placement`, `figures.placement`,
   `tables.placement`, `supplementary_file_pattern` ONLY from a guide rule (quote + line).
   Absent = default.
6. `guidelines_extract.md` citing `guidelines_source.txt` lines (`L0012`), `docx_style.json`
   and `08_submission/guideline_requirements.json` (schema in `reference/`): every rule of
   this article type with verbatim `quote`, `lines`, `category`, `rule`, `enforcement`
   auto|builder|manual|portal|n.a.; silent categories in `not_mentioned`, other article
   types in `not_applicable`. Over the display limit? `display_reallocation.json`.
7. `wf journal diff`: differences vs the previous journal (or defaults; auto/self-verify/
   user decision) and rules the engine cannot lay out, with the manual handling. Show it
   ONCE in Chinese, in the same message as the other S20 questions.
8. Open the variant (all journal edits go to `08_submission/manuscript/`, never `07_manuscript/`):
```
.\.venv\Scripts\python.exe tools/manuscript/scientific_freeze.py open-variant --journal "<chosen journal>"
```
   Rejected later? `wf journal switch --to "<new>" --confirm-old "<old>" --why "..."`
   (`--repackage` when the science is frozen; then a new chat). Never edit S20 files in
   place for a new journal.

## Outputs
- `08_submission/journal_shortlist.md`, `target_journal.json`, `guidelines_extract.md`,
  `docx_style.json`, `guideline_requirements.json`, `manuscript/` (journal variant)

## Gate
guidelines sourced, indexing evidence, requirement list mapped (obligation and linked-page
lines), journal layer clean, no old-journal traces, difference list, docx style, display
plan, freeze and variant. Never state indexing, fees or rules from memory.

## Close
```
.\.venv\Scripts\python.exe tools/wf.py decide journal_chosen "<journal>" --why "<user choice and acceptance-fit rationale>"
.\.venv\Scripts\python.exe tools/wf.py check
.\.venv\Scripts\python.exe tools/wf.py advance --note "target=<journal>; current SCIE/JCR verified; Word rules frozen; journal deltas=<...>"
```
