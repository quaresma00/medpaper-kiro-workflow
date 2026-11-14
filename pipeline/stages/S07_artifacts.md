# S07 - Artifact inventory (benchmarked) + legends written first

Goal: decide exactly what the paper displays, benchmarked against comparable papers, and
write every legend before anything is drawn.
Details (plan JSON template, legend form, archetypes, dictionary/profile fields): `reference/stage_details/S07_artifacts.md`.

## Do
1. 1.25.0: benchmark the 5-10 (target 8) MOST RECENT comparable papers (same design and
   data-source family; then same outcome/exposure, target journal or tier). `search` = PubMed
   by publication date, original articles, last 3 years (5 when < 5 exist); take candidates in
   order, `skip` a newer one only with a reason; older = `--exception` (outside the median).
   Counts/types from open-access XML captions, else a retrieved full text, else
   `--unknown-counts` (outside the median); never read whole papers:
```
.\.venv\Scripts\python.exe tools/pubmed/benchmark.py search
.\.venv\Scripts\python.exe tools/pubmed/benchmark.py add --pmid <pmid> --design <key>
.\.venv\Scripts\python.exe tools/pubmed/benchmark.py skip --pmid <pmid> --reason not_comparable --note "..."
```
   Then `01_protocol/artifact_benchmark.md` (`Comparable papers surveyed`, `Figure/table counts
   observed`, `Chosen inventory and why`). Plan >= the median of main items (journal limits;
   extra to the supplement), every type of >= half of the papers (`display_type`, or
   `benchmark_omissions` {type: reason}); send the `benchmark.py show` Chinese lines (papers +
   plan) to the user.
2. `01_protocol/artifact_plan.json`: per item `id`, `content`, `source_results`, `file`; figures
   also `archetype` (`wf archetype <name>`), `width`, `script`, `text_plan` {in_figure, legend}.
   Main tables one xlsx each; all supplementary tables one workbook, one sheet each; numbering
   1..N; a selection flow diagram is Figure 1.
   1.12.0: every item after the first in its group carries `"non_redundancy": "<what it shows
   that the others do not>"` - an item that repeats another is merged or moved to the supplement.
3. `05_figures/legends.md` (one `# Figure legends`, one `## Figure N.` block each; 40-140
   words; decode the display, never restate results) and `04_tables/table_captions.md`
   (title + footnote: abbreviations, units, method in one sentence, symbols). Each legend and
   footnote defines its own abbreviations; the manuscript keeps a central list too.
4. `01_protocol/display_dictionary.json`: every internal group/outcome/contrast/model name ->
   clinical `label`, `abbreviation`, one-line `definition`. Displays and prose use labels only.
   Explanatory constants in table footnotes (e.g. "per 1000 reports") go in
   `footnote_constants` [{value, reason}].
5. `01_protocol/journal_profile.json`: provisional journal parameters (font_min_pt,
   figure_width_mm, panel_label_case, line_art_dpi, number_format, spelling, heading_names,
   in_figure_title, source). Tables and figures are built to it from the first render.

6. 1.23.0: legends and captions drafted by the `medpaper-clinical-writer` (`writer_bundle.py
   build --stage S07_artifacts --target 05_figures/legends.md`, `receipt --section legends`;
   the same for `table_captions`) and polished at once by the `medpaper-medical-editor`
   (`edit`/`polished --section ...`; `section_polished`).

## Outputs
- `01_protocol/artifact_benchmark.md`, `01_protocol/display_benchmark.json`
- `01_protocol/artifact_plan.json`
- `05_figures/legends.md`
- `04_tables/table_captions.md`

## Gate
plan benchmarked (1.25.0: recent 5-10), plan sane, per-item non-redundancy, legends/captions for every planned item, figure text
planned, display dictionary, provisional journal parameters, clinical labels, engineering
language, no results restated in legends, no forbidden symbols. Nothing is drawn yet.

## Close
```
.\.venv\Scripts\python.exe tools/wf.py check
.\.venv\Scripts\python.exe tools/wf.py advance --note "inventory: <F main / T main / F supp / T supp> vs benchmark <range>; legends written"
```
