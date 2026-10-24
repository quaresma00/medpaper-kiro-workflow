# S20 - Select the most realistic current SCIE journal

## Purpose
Choose a legitimate current SCIE venue that maximises realistic acceptance probability,
then freeze its actual author instructions and Word-format rules.

## Procedure
1. Read the user-reviewed full manuscript and the independent review. Search for journals
   that recently published studies of the same design, scale and topic; this is stronger
   scope evidence than a generic aims-and-scope match.
2. Build a current eligibility screen. A candidate is eligible only if it is currently
   SCIE-indexed, has a current JCR quartile Q1-Q4, and has no active warning, delisting
   concern or material integrity signal. Verify title and ISSN from current sources. The
   chosen journal's SCIE, JCR, integrity and author-guide checks must be no more than 90
   days old when this gate closes; future-dated evidence also fails.
3. Write `project/08_submission/journal_shortlist.md` with `Eligibility screen`, `Ranking
   basis`, `Shortlist`, `Reject-fallback cascade`. Include 5-8 candidates with fit evidence,
   realistic acceptance reasoning, APC and turnaround when currently verifiable, and the
   main rejection risk. Rank by acceptance probability and study fit. Q3/Q4 and low-impact
   journals are fully acceptable and should outrank prestige targets with poor odds.
4. Present the shortlist and wait for the user's choice. Do not default to the highest
   impact factor.
5. Fetch the chosen journal's current official author instructions, snapshot the raw page
   under `project/08_submission/cache/`, and write `target_journal.json` with the required
   SCIE, JCR, integrity and retrieval fields.
6. Write `guidelines_extract.md` with sourced sections for word limits, abstract, keywords,
   references, figures and legends, tables, supplements, statements, cover letter, required
   upload items and formatting.
   Record the journal's abbreviation-placement rule. Set `abbreviation_placement` in
   `target_journal.json` to `self_contained` by default (each table/figure defines its own
   abbreviations, plus a central list). Use `central_required` only when the official guide
   explicitly requires one central list without local definitions, and put the exact guide
   URL and rule in `abbreviation_rule_source`.
   1.11.0: add `"presentation": {...}` confirming or replacing the provisional
   `01_protocol/journal_profile.json` values (font_min_pt, figure_width_mm, panel_label_case,
   line_art_dpi, number_format, spelling, heading_names). A replacement re-renders tables and
   figures as a presentation change (facts unchanged), never an S19 return.
   Record the journal's rules as **typed fields** in `target_journal.json`; checks and the Word
   builder read these, never the prose of `guidelines_extract.md` (null = the guide is silent):
```
"article_type": "Original Article",
"limits": {"main_text_words": 4000, "abstract_words": 250, "reference_limit": 45,
           "display_items": 6, "main_figures": null, "main_tables": null,
           "source": "<guide URL + quoted rule>"},
"word_count_scope": ["Introduction", "Methods", "Results", "Discussion", "Conclusions"],
"declarations_order": ["Funding", "Competing interests", "Ethics approval", "Consent to participate",
                       "Consent for publication", "Data availability", "Code availability",
                       "Author contributions", "Acknowledgements"],
"discussion_subheadings": false,
"embed_figures": false, "word_tables": false,
"legend_style": {"prefix": "Figure", "bold": true, "panel_label_case": "any", "end_punctuation": "any"},
"supplementary_aliases": {"Online Resource 1": ["Supplementary Methods", "Table S1"]},
"reference_separator": "space",
"si_format": "pdf",
"evidence_sources": {"official": ["<publisher/Clarivate URL>"], "third_party": ["<e.g. LetPub URL>"]}
```
   `declarations_order` defaults to the Springer Nature order above when the guide is silent;
   `discussion_subheadings` is true only if the guide requires them; `supplementary_aliases`
   lets the variant say "Online Resource n" without failing fact preservation. Evidence: SCIE
   and quartile come from an official source (publisher page, Clarivate MJL/JCR) when reachable;
   a third-party mirror alone is acceptable only when the official source needs a login, and
   must be listed under `third_party` with the official URL tried.
   Reporting checklist and registration are on demand: only if the official instructions
   require a checklist, set `"journal_requires_checklist": "<name, e.g. STROBE>"` in
   `target_journal.json` (S23 then fills it); otherwise leave it unset. Likewise a
   registration statement is written only if the journal demands one.
7. Write `project/08_submission/docx_style.json`. Use the journal's explicit requirements
   for font size, spacing, margins and paper size. All text is always black and external
   hyperlinks are always removed. If the journal is silent, use these medical-manuscript
   fallbacks and record them under `fallbacks`: Times New Roman, 12 pt body, 12 pt bold
   section headings, 12 pt bold subsection headings, double spacing, 0 pt paragraph-after,
   1-inch margins, A4 paper. If a journal explicitly mandates a different font, its
   instruction overrides the fallback and `source` must quote it.
```
{
  "font_family": "Times New Roman",
  "body_font_pt": 12,
  "title_font_pt": 14,
  "section_heading_font_pt": 12,
  "subsection_heading_font_pt": 12,
  "line_spacing": 2.0,
  "paragraph_spacing_after_pt": 0,
  "margins_in": 1.0,
  "paper_size": "A4",
  "all_text_black": true,
  "external_hyperlinks": false,
  "source": "<official guideline URL and quoted rule, or journal silent>",
  "fallbacks": ["font_family", "body_font_pt", "title_font_pt", "section_heading_font_pt", "subsection_heading_font_pt", "line_spacing", "paragraph_spacing_after_pt", "margins_in", "paper_size"]
}
```

Then **open the journal variant.** The science was frozen when the user released S19, so every
requirement you just extracted is applied to a copy, never to `07_manuscript/`:
```
.\.venv\Scripts\python.exe tools/manuscript/scientific_freeze.py open-variant --journal "<chosen journal>"
```
This copies the frozen manuscript, supplementary Methods and statements into
`08_submission/manuscript/`. From here on that copy is what S21 completes, S22 polishes and
S23 renders to DOCX; every gate that reads "the manuscript" resolves there automatically.

If the user later picks a different journal, do **not** overwrite S20 files in place and do
not merely call `open-variant --force`: that would leave the old journal's cache, bundle,
cover letter and approvals nearby. First route back to S20 and clear the whole submission area:
```
.\.venv\Scripts\python.exe tools/wf.py loop --to S20_journal --why "switching target journal"
.\.venv\Scripts\python.exe tools/manuscript/scientific_freeze.py reset-journal --confirm-journal "<old journal>"
```
Then repeat S20 from the shortlist with fresh official evidence and call `open-variant` for the
new journal. `07_manuscript/` and its freeze are never touched. `open-variant --force` is only
for rebuilding the current S20 variant; it clears S21+ downstream files as well as the variant.

## CSL check (1.9.0)
```
.\.venv\Scripts\python.exe tools/manuscript/csl_check.py --csl project/08_submission/journal.csl --example "<official example reference>"
```

## Outputs
- `08_submission/journal_shortlist.md`
- `08_submission/target_journal.json`
- `08_submission/guidelines_extract.md`
- `08_submission/docx_style.json`
- `08_submission/manuscript/` (the journal adaptation copy, opened from the frozen source)

## Hard rules
- 1.10.0 `display_plan_fits_journal`: compare the main figures/tables with `limits` (display_items, main_figures, main_tables). Over the limit -> write `08_submission/display_reallocation.json` `{"moves": [{"id", "to": "supplementary", "new_id", "why"}]}` before any further writing, and apply it as a rework round (kind figure-layout/table-layout; facts unchanged = presentation). Record `limits.figure_legend_words` only if the guide states a legend cap.
- Record typed structure fields in target_journal.json: `main_text_headings`, `keywords` {min, max, separator}, `running_title_position`, `blinded_main_manuscript`, `spelling`, `number_format` {p_space, minus (unicode|hyphen), thousands (","|"thin"|""), interval}. Builders and checks read them; a change to them later is a `journal-format` (presentation) revision.
- CSL (1.9.0): compare the journal's official example reference with the rendered list before S23 and fix differences with a paper-local `08_submission/csl_patch.json` (never by editing refs.bib or the final Word file). `initialize-with-hyphen` only works on the `<style>` root - use `{"initialize_with_hyphen": false}` in the patch.
- Never state indexing, quartile, fees, turnaround or format rules from memory.
- Never satisfy a journal requirement by editing `07_manuscript/`. That is what the variant is
  for, and `scientific_freeze_intact` is non-overridable.
- Current SCIE status and a current JCR quartile are eligibility requirements; impact
  factor is not the ranking objective.
- The user chooses the journal.
- Formatting defaults are used only where the chosen journal is silent and are documented.
- `fallbacks` lists only the canonical JSON keys whose rules are silent; every other style
  value must be supported by the official `guidelines_url`, which is included in `source`.

## Close
```
.\.venv\Scripts\python.exe tools/wf.py decide journal_chosen "<journal>" --why "<user choice and acceptance-fit rationale>"
.\.venv\Scripts\python.exe tools/wf.py check
.\.venv\Scripts\python.exe tools/wf.py advance --note "target=<journal>; current SCIE/JCR verified; Word rules frozen; journal deltas=<...>"
```
