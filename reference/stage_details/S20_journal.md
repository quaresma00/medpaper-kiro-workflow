# S20 - Select the most realistic current SCIE journal - details

> 1.15.0 supersedes older wording below where they differ: only an explicit numeric rule of
> the guide is a hard cap. Never derive a word cap from a page count; an estimate goes in
> `limits.estimated` (or a source saying 'estimated from N pages') and is a soft hint that
> never triggers cutting. New typed switches: `separate_display_files` (default on unless the
> journal forbids it: main figure TIFFs and table workbooks as separate uploads),
> `display_file_names`, `figure_dpi`, `supplementary_label` (default "Online Resource"),
> `abbreviation_list` (`none|after_keywords`, default after_keywords, never inside
> Declarations), `reference_rules.drop_discussion_pages`. A later change of the official
> guide: `wf guidelines refresh --from <new extract> --source <url>` (dated snapshot; audits
> read the latest).

> Long form of `pipeline/stages/S20_journal.md` (moved out of the card in 1.12.0 so the
> card stays short). Read only the section you need; the card has the commands.
>
> 1.12.0 supersedes older wording below where they differ: long runs use `--wait` (one
> blocking call, heartbeat <= 30 s) and logs live in `.wf/logs/` (or `temp/logs/`);
> `wf check` prints failures + one summary line by default; in `deferred` visual mode no
> DEFER decision is recorded (the look is owed at S23); the `medpaper-reviewer` agent
> writes only its own `report.md` in the review bundle; declaration and section heading
> names come from `target_journal.json` (defaults otherwise).

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
5. Get the chosen journal's current official author instructions lawfully (1.17.0):
   `wf journal lookup --issn <ISSN> [--title "<journal>"]` tries the dated local caches, the
   DOAJ record (`author_instructions`), OpenAlex and the NLM Catalog (homepage, current MEDLINE
   status) plus the vendored publisher URL table `reference/publisher_guideline_urls.json`
   (candidates, verified at runtime), then ONE polite GET. A real guide page is stored in
   `08_submission/cache/` (sha256, date, URL in `cache/index.json`) and converted to the
   line-numbered `08_submission/guidelines_source.txt`. On 403, a captcha or an empty page it
   stops and prints the exact URL: the user opens it in the browser and saves it ("web page,
   HTML only", or print to PDF, or the publisher's PDF guide / Word template), then
   `wf guidelines ingest --from <file> --url <official URL>`. Ingest every guide page the
   journal splits its rules over (figures, references, ethics). Never log in for the agent,
   never bypass bot protection, never use a third-party reader proxy; LetPub-style summaries
   are leads only. SCIE/JCR evidence: the user exports the Master Journal List page as PDF and
   ingests it with `--kind indexing`; NLM MEDLINE status is supplementary. Then write
   `target_journal.json` with the required SCIE, JCR, integrity and retrieval fields and
   `"csl": {"style_id", "issn"}` from the CSL index the lookup prints
   (`tools/refs/csl_index.py fetch --issn <ISSN>` installs the parent style).
6. Write `guidelines_extract.md` with sourced sections; since 1.17.0 every requirement cites
   the `guidelines_source.txt` line(s) it comes from (`L0012`, `L0040-L0046`); the gate checks
   that the cited lines exist. Sections for word limits, abstract, keywords,
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

## Switching journals (rejection, withdrawal) - 1.17.0
If the user later picks a different journal, do **not** overwrite S20 files in place and do
not merely call `open-variant --force`: that would leave the old journal's cache, bundle,
cover letter, audits and approvals nearby. One command does the whole switch from any stage at
or after S20 (also after S25 or a rejection):
```
.\.venv\Scripts\python.exe tools/wf.py journal switch --to "<new journal>" --confirm-old "<old journal>" --why "<rejection / reason>" --outcome rejected
```
It records `.wf/journal_history.json` (epoch, journal, outcome, dates), runs the equivalent of
`wf loop --to S20_journal` and `scientific_freeze.py reset-journal --confirm-journal "<old
journal>"`, and also archives `.wf/audits/`, the package review bundles/reports, the
package review rounds (grouped by epoch in `.wf/review_rounds.json`), the previous epoch's
helper scripts in `.wf/scripts/` and CSL files outside `08_submission/`, all into one archive
folder. Old S20+ handoff notes no longer count; the new S20 needs its own note. Journal-
independent facts are carried and never re-asked (study design, data source, ethics/consent/
data-availability assessment, the author's AI-use answer, author list); only journal wording
is regenerated. Display moves and presentation edits made for the old journal are listed once:
ask the user ONE question and record it with `wf journal restore --answer restore|keep --why
"<the user's words>"`. `wf journal shortlist` prints the archived fallback ladder as a
starting point only - re-verify every candidate with fresh evidence. S20-S25 adopt the current
engine's gate set (an event says so); completed science stages keep their pin. Gates then
require a fresh guideline snapshot (`journal_layer_clean`: nothing under `08_submission/`
older than the epoch, evidence dated in this epoch), the epoch in `target_journal.json` and
the variant (`journal_variant_ready`), a complete `presentation` block and re-rendered
displays (`presentation_params_confirmed`; `wf rebuild` re-renders). The first S25 audit of
the new journal is a full audit. After the switch tell the user: 请关闭本对话，新开一个对话，
输入“继续 medpaper”. Never list or search the journal archives; the engine reads them.
Then repeat S20 for the new journal and call `open-variant` for it. `07_manuscript/` and its freeze are never touched. `open-variant --force` is only
for rebuilding the current S20 variant; it clears S21+ downstream files as well as the variant.

## CSL check (1.9.0; an S23 gate since 1.17.0)
`csl_check` (S23) passes when the CSL in `08_submission/` names the journal ISSN, or is the
parent style the vendored ISSN index (`reference/csl_issn_index.json`, from the CSL styles
project, CC BY-SA 3.0) gives that ISSN, or `target_journal.json` `"csl": {"reason": ...}`
explains the choice (e.g. the guide's own example); the render checks below must be clean.
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

## Requirement list (1.18.0) - `08_submission/guideline_requirements.json`
Written after `guidelines_source.txt` exists, for the chosen article type; schema
`reference/guideline_requirements.schema.json`. One entry per rule:
`{id, category, quote, lines, rule, enforcement, article_type}`.
- `quote` is copied verbatim from the cited lines (whitespace and typographic quotes are
  normalised); `lines` is `L0012`, `L0040-L0046` or a list.
- `category` is one of the 26 fixed categories (word_limits, abstract_structure, keywords,
  title_page, running_title, highlights, section_headings, references, citations, figures,
  tables, supplementary, declarations, ethics_consent, data_availability, ai_disclosure,
  conflicts_of_interest, funding, author_contributions, cover_letter, required_uploads, layout,
  language, blinding, reporting_checklist, article_type_rules). A category the guide is
  silent on goes in `not_mentioned` with the terms you searched (>= 2; the gate fails when a
  searched term does occur in the guide).
- `enforcement`: `auto` = the engine measures `rule.field` / `rule.check` (fields:
  limits.main_text_words, limits.abstract_words, limits.reference_limit, limits.display_items,
  limits.main_figures, limits.main_tables, keywords.*, abstract.*, title_page.*,
  running_title_position, highlights.*/key_points.*, cover_letter.must_state,
  required_uploads, figure.*, figure_dpi, orcid_required, csl, declarations_order; checks:
  word_limits, reference_limit, display_items, keywords, abstract, title_page, running_title,
  highlights, cover_letter, required_uploads, figure_files, orcid, csl, declarations_order,
  page_numbers, ai_statement, reference_format); `builder` = a builder applies the typed
  field (main_text_headings, legend_style, reference_separator, line_numbers, docx_style.*,
  figure.formats, running_title_position, ...); `manual` = you record the evidence location at
  S23; `portal` = the user does it in the submission system; `n.a.` + `reason`.
- Lines of other article types or sections that do not apply: `not_applicable`
  `[{"lines": "L0040-L0052", "reason": "Case reports only"}]`.

`guideline_requirements_mapped` fails when a category is missing, a quote is not at its
lines, a number in an auto/builder quote differs from the typed field (`rule.value` too), an
auto rule names nothing the engine measures, or a guide sentence with must / required /
should / mandatory / please ensure / not exceed / maximum / no more than / at least /
limited to / are expected to / have to is covered by no requirement and no n.a. range (the
uncovered line numbers are listed). Typed fields with no requirement are a warning
(fallback). A journal switch archives the list; build the new one from the new guide only.

Typed fields added in 1.18.0 (`tools/wfcore/journalfields.py` has the formats):
`abstract {structured, headings[], per_section_words, total_words}`, `title_page {elements[],
title_max_chars, title_max_words, running_title_max_chars}`, `running_title_position`
(`manuscript` puts the title page's running title on the first manuscript page),
`highlights` or `key_points {required, n_min, n_max, max_chars, label, placement}`,
`cover_letter {must_state[]}`, `required_uploads[]` (strings or `{item, role}`; `{portal:
true}` for portal-only), `figure {formats[], min_dpi, max_mb, colour}` (separate figure
files are converted from the TIFF masters to the first format the engine can write: TIFF,
PNG, PDF, EPS, JPEG; CMYK/greyscale on request), `orcid_required` (true | "corresponding" |
"portal").
