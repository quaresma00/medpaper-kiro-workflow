# S07 - Artifact inventory (benchmarked) + legends written first - details

> Long form of `pipeline/stages/S07_artifacts.md` (moved out of the card in 1.12.0 so the
> card stays short). Read only the section you need; the card has the commands.
>
> 1.12.0 supersedes older wording below where they differ: long runs use `--wait` (one
> blocking call, heartbeat <= 30 s) and logs live in `.wf/logs/` (or `temp/logs/`);
> `wf check` prints failures + one summary line by default; in `deferred` visual mode no
> DEFER decision is recorded (the look is owed at S23); the `medpaper-reviewer` agent
> writes only its own `report.md` in the review bundle; declaration and section heading
> names come from `target_journal.json` (defaults otherwise).

## Purpose
Decide exactly what the paper displays, benchmarked against what comparable papers
actually display, and write every legend before anything is drawn. Legends written
first keep panels from filling up with explanatory text later.

## Procedure
1. **Benchmark.** Retrieve comparable papers - same design, same field, the kind of
   journal you are targeting - and count what they display. Since 1.25.0 the candidates come
   from `tools/pubmed/benchmark.py search` (the most recent first; see below), not from a
   relevance-sorted search.
   Write `project/01_protocol/artifact_benchmark.md` with headings
   `Comparable papers surveyed`, `Figure/table counts observed`, `Chosen inventory and why`.
   Record the observed range (e.g. "4-6 main figures, 2-3 main tables, n=8 papers"), and
   justify your inventory against it. Fewer, better displays beat padding.
   1.23.0 (`display_plan_benchmarked`): `tools/pubmed/benchmark.py add --pmid P --design KEY`
   per comparable paper (3-5) builds `01_protocol/display_benchmark.json` from open-access
   JATS captions (Europe PMC), else a full text the cascade retrieved, else the counts and
   types you read from the abstract. `benchmark.py types --design KEY` lists the display types
   of `reference/display_types.toml` (e.g. pharmacovigilance: case-selection flow diagram,
   forest plot of reporting odds ratios, time-to-onset distribution, outcome seriousness,
   trend by year, signal heatmap, sensitivity forest). The plan needs at least the benchmark
   median of main items (capped by `main_figures_max + main_tables_max` or the provisional
   journal profile's `display_items`; extra items go to the supplement) and every type used by
   at least half of the papers: give an item `"display_type": "<key>"` (its archetype and
   wording also count), or `"benchmark_omissions": {"<key>": "<one-line reason>"}` in the plan.
   The 1.12 non_redundancy rule still applies. `benchmark.py show` prints the Chinese lines
   (benchmark counts and types, the plan against them) for the S07 message to the user.

   **1.25.0 - the most recent comparable papers (supersedes "3-5, preferably last 5 years").**
   - `benchmark.py search [--design KEY] [--query "..."]` builds the PubMed query from
     `01_protocol/idea.json` (design; data-source family, e.g. FAERS/JADER/VigiBase
     disproportionality, NHANES-type survey, Mendelian randomization, a named registry) and the
     exposure/outcome labels of the display dictionary (entries with `"role": "exposure"` /
     `"outcome"` first); `--query` replaces that topical part. Filters are always added: no
     reviews, systematic reviews/meta-analyses (unless the paper is a meta-analysis), letters,
     comments, editorials, case reports or errata; English; the window. Sorted by publication
     date, most recent first (E-utilities via `tools/pubmed/eutils.py`, `NCBI_API_KEY` from the
     environment); metadata only (PMID, date - electronic first -, journal, title). The log is
     `01_protocol/benchmark_search.json` (query, search date, window, counts, candidates).
   - Comparability: required = same design AND same data-source family; preferred = same
     outcome family or exposure class; preferred = the target journal or its tier when known.
   - Selection: among candidates meeting the required level take the most recent 5-10 (target
     8), in the log's order. A more recent candidate is passed over only with `benchmark.py skip
     --pmid P --reason not_comparable|not_original_article|displays_not_obtainable --note "..."`.
   - Window: the last 3 years before the search date; the search extends to 5 years by itself
     when fewer than 5 candidates exist (recorded), or `search --extend --reason "..."` when
     fewer than 5 of them are comparable. An older paper only as `add --exception "<reason>"`
     (e.g. the only comparable paper in the target journal); it is listed but outside the median.
   - Display extraction as in 1.23 (open-access JATS captions; else the lawful full-text
     cascade or the browser with the user's institutional access; else `add --unknown-counts`
     = abstract only). Unknown counts stay outside the median; at least 5 papers with known
     counts unless the window has fewer (then all of them, each skipped one with its reason).
   - Gate (`display_plan_benchmarked`, since 1.25.0): the dated log; 5-10 included (fewer only
     when every candidate is included or skipped); all from the window except exceptions; no
     more recent candidate passed over without a reason; the plan's main items >= the median
     (journal limits; extras to the supplement) and every type of >= half of the papers
     present or explained (1.23 rule). Papers pinned earlier keep the 1.23 rule until
     `wf migrate --yes`.
   - The S07 message to the user: `benchmark.py show` - the included papers (year, journal,
     main figures/tables) and the planned displays, in a few Chinese lines.
2. **Plan.** Write `project/01_protocol/artifact_plan.json`. Every entry needs a
   `source_results` list pointing at the result JSONs it is built from - an artifact with
   no numeric source cannot be built:
```json
{
  "main_figures": [
    {"id": "Figure 1", "slug": "flow", "title": "",
     "content": "what the reader learns from it, in one sentence",
     "archetype": "flow_diagram",
     "panels": ["A", "B"], "width": "single|1.5|double",
     "script": "05_figures/code/fig1_flow.R",
     "file": "05_figures/out/Figure1.png",
     "tiff": "05_figures/out/Figure1.tiff",
     "source_results": ["03_analysis/results/dataset_summary.json"]}
  ],
  "main_tables": [
    {"id": "Table 1", "slug": "baseline", "title": "",
     "content": "", "file": "04_tables/main/Table1.xlsx", "sheet": "Table 1",
     "source_results": ["03_analysis/results/baseline.json"]}
  ],
  "supp_figures": [],
  "supp_tables": [
    {"id": "Table S1", "slug": "", "title": "", "content": "",
     "file": "04_tables/supplementary/supplementary_tables.xlsx", "sheet": "Table S1",
     "source_results": []}
  ],
  "supp_files": [{"id": "Supplementary File 1", "file": "", "what": ""}]
}
```
   Structural requirements the gate enforces: sequential numbering with no gaps; each
   main table in its own xlsx; **all supplementary tables in a single xlsx, one sheet
   each**; every figure has a `width`, a `script` and an `archetype`. Figures render in R
   by default (`figure_engine`); a figure whose script is the other engine (e.g. an approved
   Python figure that is kept as it is) needs `"renderer": "Python"` and a
   `"renderer_reason"` of at least 20 characters. Never refit a confirmed model just to draw
   it in R. `source_results` lists the result files the figure is drawn from; the R render
   receipt binds to exactly that list.
   A participant-selection flow diagram (PRISMA flow for a meta-analysis), if planned,
   is Figure 1.

3. **Declare each figure's archetype.** Pick it from `reference/archetypes.toml` and read
   that entry before planning the figure - it lists the elements that chart type must have,
   and S11 checks the rendered figure for them. Choosing `km_survival` commits you to a
   number-at-risk table and censoring marks; choosing `histopathology` commits you to a
   physical scale bar. Pick the archetype that matches what the data needs, then accept its
   requirements. `other` is available but demands an `archetype_rationale`, and it turns off
   the domain checks, so prefer a real archetype.
4. **Legends.** Write `project/05_figures/legends.md`, one compact block per figure, each
   headed `Figure N.` / `Figure S1.` Use medical-journal form: a brief descriptive title;
   one clause or sentence per panel; only essential visual encodings; sample size/error-bar
   definition/statistical test only when the figure cannot be interpreted without it; then
   a short abbreviations clause when needed. Target 40-140 words and never exceed the
   configured 180-word ceiling. Describe what is drawn and how to decode it; do not state
   which group was higher or lower, repeat effect estimates, or retell the Results.
   Do not repeat cohort acquisition, complete model specification, software versions,
   interpretation, numerical Results or generic caveats already stated elsewhere. The file
   contains exactly one `# Figure legends` section heading and exactly one heading for each
   planned figure. After a `Figure N.` heading, do not begin the body with `Figure N.` again.
5. **Table captions.** Write `project/04_tables/table_captions.md`, one block per table,
   headed `Table N.` Each needs a title line plus the footnote content: abbreviation
   expansions, units, the estimation method in one sentence, what a dagger/asterisk marks.
   Every table footnote and figure legend defines the abbreviations it uses, so each display
   reads on its own; the manuscript keeps a central list as well. Only a journal that
   explicitly requires a single central list changes this (`abbreviation_placement =
   "central_required"` at S20).
6. **Display dictionary (1.11.0).** Write `project/01_protocol/display_dictionary.json`
   (next to the artifact plan): one entry per internal group, outcome, contrast or model
   name used by the analysis code - `{"internal": "comp_a", "aliases": ["Composite A"],
   "label": "<clinical name>", "abbreviation": "<or empty>", "definition": "<one line>"}`.
   Table builders, figure scripts (R `clinical_label()`), legends and prose use only the
   label; letter codes ("Composite A", "Group B", "Model 3") stay out of displays unless the
   dictionary makes that exact string the clinical label.
7. **Provisional journal parameters (1.11.0).** Write `project/01_protocol/journal_profile.json`
   for the likely target journal or journal type (`font_min_pt`, `figure_width_mm`
   single/1.5/double, `panel_label_case`, `line_art_dpi`, `number_format`, `spelling`,
   `heading_names`, `source`). Tables and figures render with it from the first build; S20
   confirms or replaces it, which is a presentation re-render, never science.

## Outputs
- `01_protocol/artifact_benchmark.md`
- `01_protocol/artifact_plan.json`
- `05_figures/legends.md`
- `04_tables/table_captions.md`

## Hard rules
- 1.10.0 `figure_text_planned`: every figure entry carries `"text_plan": {"in_figure": "axis titles, units, group labels, n at risk (or none)", "legend": "what the legend explains"}` - plan both together. Legend length (`figure_legend_words_max`) is advisory; it blocks only when the journal states `limits.figure_legend_words`.
- The display inventory is re-checked against the chosen journal at S20 (`display_plan_fits_journal`).
- Do not draw anything yet. No xlsx, no png.
- Do not plan a display item you have no result JSON for.
- Detailed methods, cohort provenance and general caveats belong in Methods or
  supplementary Methods, not in panels and not automatically in every legend.
- Do not use the literal down-arrow character. Express direction in words outside legends;
  legends themselves describe the display without claiming the direction of a result.
- Do not duplicate the Figure legends section title, a figure identifier, or the descriptive
  legend title between the heading and the first body sentence.

## Close
```
.\.venv\Scripts\python.exe tools/wf.py check
.\.venv\Scripts\python.exe tools/wf.py advance --note "inventory: <F main / T main / F supp / T supp> vs benchmark <range>; legends written"
```

