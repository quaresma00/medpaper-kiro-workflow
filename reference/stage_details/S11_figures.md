# S11 - Render figures (R by default), QC them by code, then look (now or at S23) - details

> Long form of `pipeline/stages/S11_figures.md` (moved out of the card in 1.12.0 so the
> card stays short). Read only the section you need; the card has the commands.
>
> 1.12.0 supersedes older wording below where they differ: long runs use `--wait` (one
> blocking call, heartbeat <= 30 s) and logs live in `.wf/logs/` (or `temp/logs/`);
> `wf check` prints failures + one summary line by default; in `deferred` visual mode no
> DEFER decision is recorded (the look is owed at S23); the `medpaper-reviewer` agent
> writes only its own `report.md` in the review bundle; declaration and section heading
> names come from `target_journal.json` (defaults otherwise).

## Purpose
Produce journal-grade figures. Verification is two-phase: deterministic QC by code, then
visual inspection of the rendered PNG. Reading the plotting code is not verification.

**Renderer.** Figures are drawn in R by default (`reference/language_policy.toml`): ggplot2 +
patchwork, rendered by `save_medpaper()` from `tools/figures/R/medfig.R`. Check the paper's
setting before you start:
```
.\.venv\Scripts\python.exe tools/wf.py config get figure_engine
```
`R` (default) uses the R procedure below; `python` uses `tools/figures/style.py` (step 2b).
Mixing per figure is allowed and only warns (`engine_matches_policy`).

**Phase 2 timing is controlled by `visual_review_mode`.** Check it too:
```
.\.venv\Scripts\python.exe tools/wf.py config get visual_review_mode
```
- `deferred` (default) - get deterministic QC green here, record
  `figures_visually_confirmed DEFER`, and do not load a single PNG at this stage. The whole
  backlog is discharged in one contact-sheet pass at S23.
- `inline` - look at every figure here, in the loop, as step 5 below describes.

Why deferring is the default: the cost is not the look, it is the loop. Every re-render
re-loads the image, and the look is invalidated later anyway - S12 can force a figure change,
S18/S19 review can, and **S20 picks the journal, which fixes column width, font floor and
house palette**. Deterministic QC is code, so it runs every round for free and still blocks
here. The S23 gate `visual_debts_cleared` is **non-overridable** - `--force` will not move it.

Read `reference/figure-standards.md` before writing the first script, and read your
figure's entry with `wf archetype <name>` - it lists the elements the gate will look for.

**Also activate the `medical-sci-figure-skill` global skill** and read its atlas entry for the
chart type in hand (`references/figure_atlas.md`, `references/universal_laws.md`). It is the
authority on visual grammar: which elements an archetype must carry, what is forbidden (a
dynamite plot, a KM curve with no risk table, "400x" in a caption instead of a scale bar),
and which journal palette to use. Translate its matplotlib idioms into ggplot2.

It is reading and styling, never the renderer. Render with `save_medpaper()` (R) or
`tools/figures/style.py` `save()` (Python) and judge with `tools/figures/qc.py`, always.
Anything drawn through `medfigure/recipes/` or a bare `ggsave()` writes no sidecar, so
`figures_qc_pass` cannot go green. Where the skill and the pipeline disagree on a number -
column widths, the font floor, legend placement, panel titles, the rendering library, which QA
engine - `reference/skill_policy.toml` `[figure_authority]` records seven conflicts, and every
one resolves to this pipeline. Do not call `medfigure.qa.audit_medical_figure()` on a
pipeline figure.

## Procedure
1. **R (default): one script per planned figure**, `05_figures/code/<plan script>.R`, using a
   recipe when one exists (`recipe_km`, `recipe_cif`, `recipe_forest`, `recipe_roc`,
   `recipe_calibration`, `recipe_dca`, `recipe_volcano`):
```r
source(file.path(Sys.getenv("MEDPAPER_ROOT"), "tools/figures/R/medfig.R"))
source(file.path(Sys.getenv("MEDPAPER_ROOT"), "tools/figures/R/recipes.R"))
res <- jsonlite::fromJSON(medpaper_path("03_analysis/results/primary.json"), simplifyVector = FALSE)
dat <- read.csv(medpaper_path("02_data/derived/analysis.csv"))
p <- recipe_km(dat, "time", "status", "arm", times = c(0, 12, 24, 36),
               hr = res$estimates[[1]]$estimate,
               hr_ci = c(res$estimates[[1]]$ci_low, res$estimates[[1]]$ci_high))
save_medpaper(p, "05_figures/out/Figure1", width = "single", archetype = "km_survival")
```
   Run it with `.\.venv\Scripts\python.exe tools/wf.py run-script 05_figures/code/fig1_km.R`.
   Recipes take statistics as **numbers read from results JSON, never display strings**.
   Without a recipe: `ggplot(...) + theme_medpaper()`, palettes via
   `scale_colour_medpaper("okabe_ito")` (journal palettes `nejm`, `lancet`, `jama`, `jco`,
   `nature` warn about red/green pairs - dual-encode with shape or linetype).
   Multi-panel = patchwork with `plot_annotation(tag_levels = "A")`; never hand-place panels
   with `annotation_custom` or viewports. Do not set `plot.margin`: `save_medpaper()` sets the
   outer margin itself, equalising the ink margins with the same rule `qc.py` judges
   (`not_clipped`, `no_excess_whitespace`, `margins_symmetric`).
2b. **Python (`figure_engine = python`)**: the same plan through `tools/figures/style.py` and
   `tools/figures/recipes.py` (`km_survival`, `forest_plot`, `roc_curve`, `volcano_plot`):
```python
from wfcore.paths import project_dir
from figures.style import apply_style, figure, save

PROJECT = project_dir()
apply_style()
fig, panels = figure(width="double", height_mm=90, panels=(1, 2))   # SubFigure per panel
...
save(fig, PROJECT / "05_figures/out/Figure1", width="double", archetype="box_jitter")
```
   One SubFigure is one logical panel; never place panels with `add_axes`/`subplots_adjust`.
3. Both renderers write PNG (preview) + LZW TIFF (print master) at the exact column width from
   the paper's targets, and the artist sidecar `05_figures/qc/<stem>.artist.json`.
4. **Deterministic QC first.** Fix everything code can detect before spending a look:
```
.\.venv\Scripts\python.exe tools/figures/qc.py --all
```
   From the PNG: effective dpi, margins, margin asymmetry, edge clipping, grey text-like
   regions. From the sidecar (measured on the drawn figure): minimum font size and line width,
   panel overlap, clipped text, **missing glyphs**, **tick-label collisions**, **dead bands
   between panels**, **bar baselines at zero**, **the archetype's mandatory elements**, and the
   sidecar schema itself. Results land in `project/05_figures/qc/qc_report.json`.
   An `element:<name>` failure means the figure lacks something its archetype requires - add
   it, or change the archetype if you picked the wrong one.
5. **Then look - only if `visual_review_mode = inline`.** In `deferred` mode skip to step 7.
   Open the rendered PNG: `read_file project/05_figures/out/Figure1.png`; crop a suspect panel
   (`.\.venv\Scripts\python.exe tools/figures/qc.py --crop "Figure 1" --cols 2 --cell B`).
   Check fonts and glyphs, overlapping or clipped labels, legend placement, axis ranges and
   units, colour-blind safety and greyscale legibility, panel alignment, line widths,
   overplotting, significance markers, leftover explanatory text.
   ImageGen may act as a second visual critic; it must not redraw, regenerate, inpaint or
   otherwise edit a statistical figure. Apply accepted fixes in the script and re-render.
6. Fix the **script**, re-render, re-run QC, look again. Say which findings came from QC and
   which from looking.
7. **Strip explanatory text from the panels.** Move only what is needed to decode the figure
   to the legend; log every removal in `project/05_figures/moved_to_legend.md` as
   `Figure N | removed text | now in legend`. Never grey text down. Keep each legend within
   the 180-word ceiling, and never restate Results in it. Panel text that stays: axis titles
   and units, tick labels, panel letters, group labels, legend entries, significance markers,
   key data values (n, HR with CI, AUC), and required content (KM risk tables,
   flow-diagram box text, scale bars).
8. Write `project/05_figures/manifest.json`:
```json
{"built_at": "", "figures": [{"id": "Figure 1", "script": "", "png": "", "tiff": "",
  "width": "double", "size_mm": [180, 90], "dpi": 600, "engine": "R", "review_rounds": 2}]}
```
9. Close phase 2 according to the mode.
   `inline` - record the look, per figure, only after genuinely loading each image:
```
.\.venv\Scripts\python.exe tools/figures/qc.py --confirm "Figure 1" --note "<what you saw / changed>"
.\.venv\Scripts\python.exe tools/wf.py decide figures_visually_confirmed YES --why "<per figure: what you saw and what you changed>"
```
   `deferred` - park it, stating the QC evidence you rely on until S23:
```
# 1.12.0: deferred mode records nothing here (figures look owed at S23)
```
   Never `--confirm` a figure you did not load, and never record YES on the strength of QC.
10. Delete scratch renders from `project/temp/`.

## Outputs
- `05_figures/manifest.json`
- `05_figures/qc/qc_report.json`
- `05_figures/moved_to_legend.md`
- (plus scripts in `05_figures/code/` and PNG+TIFF in `05_figures/out/`)

## Hard rules
- 1.11.0: in-figure text comes from the display dictionary (R `clinical_label()`, `mf_label()`); the render sidecar's text is linted for internal names, letter codes, engineering words and raw statuses. Text is >= the journal minimum at final print size (`journal_profile.json` font_min_pt, default 8 pt; `theme_medpaper()`/`apply_style()` default to it); widths and panel-label case (`mf_tag_levels()`) come from the profile. A flow diagram is a schematic: boxes, counts and arrows, no axis titles; every count box names its analysis unit (reports, cases, patients, participants); lines/rows read, files, versions or quarters loaded belong in a supplementary data-scale table (`flow_diagram_units`). Each legend defines the abbreviations its figure uses.
- Never claim visual verification without having loaded the image.
- `DEFER` is a scheduling decision, never a verdict.
- Deferring never lowers a deterministic bar.
- Numbers drawn in a figure come from `03_analysis/results/*.json`, passed as numbers.
- Never fix a layout problem by shrinking fonts below the floor, nudging a single label or
  hand-tuning margins; fix the layout structure (patchwork/SubFigure composition, ratios).
- No 3-D decoration, no gratuitous gridlines, no chartjunk.
- Do not add a figure that is not in the artifact plan.

## Close
```
.\.venv\Scripts\python.exe tools/wf.py check
.\.venv\Scripts\python.exe tools/wf.py advance --note "K figures rendered (R|python); QC clean; visual: <reviewed (rounds: ...) | DEFERRED to S23>; moved to legend: <n> items"
```
