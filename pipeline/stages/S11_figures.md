# S11 - Render figures (R by default), QC them by code, look at S23

Goal: journal-grade figures verified by deterministic QC now and by eye in one pass at S23.
Details (R/Python templates, skill arbitration, QC list, manifest JSON): `reference/stage_details/S11_figures.md`,
`reference/figure-standards.md`, `wf archetype <name>`.

## Do
1. Check the settings:
```
.\.venv\Scripts\python.exe tools/wf.py config get figure_engine
.\.venv\Scripts\python.exe tools/wf.py config get visual_review_mode
```
2. One script per planned figure, `05_figures/code/<plan script>.R`, using a recipe when one
   exists; render only through `save_medpaper()` (R, `tools/figures/R/medfig.R`) or
   `tools/figures/style.py` `save()` (python). Statistics are numbers read from results JSON.
   In-figure text from the display dictionary (`clinical_label()`); fonts >= the profile
   minimum at print size; widths and panel-label case from the profile; no in-figure title
   when the journal puts titles in the legend. Flow diagrams: boxes, counts, arrows, every
   count names its analysis unit. The `medical-sci-figure-skill` may guide styling, never render.
```
.\.venv\Scripts\python.exe tools/wf.py run-script 05_figures/code/fig1_km.R
.\.venv\Scripts\python.exe tools/figures/qc.py --all
```
   QC waits for a render in progress (marker `05_figures/qc/<stem>.rendering`) instead of
   failing; re-run it once the render is done. Stacked bars are valid baselines.
3. Fix the script, re-render, re-run QC until green. Strip explanatory text from panels; log
   moves in `05_figures/moved_to_legend.md`. Write `05_figures/manifest.json`.
4. Visual look: default `deferred` mode records nothing here (no DEFER decision needed); the
   look is owed at S23 (`visual_debts_cleared`, non-overridable). `inline` mode only: load
   each PNG, then
   `.\.venv\Scripts\python.exe tools/figures/qc.py --confirm "Figure 1" --note "<what you saw>"` and
   `.\.venv\Scripts\python.exe tools/wf.py decide figures_visually_confirmed YES --why "<per figure>"`.
   Never confirm a figure you did not load.

## Outputs
- `05_figures/manifest.json`
- `05_figures/qc/qc_report.json`
- `05_figures/moved_to_legend.md`
- (scripts in `05_figures/code/`, PNG + TIFF in `05_figures/out/`)

## Gate
figures match the plan, QC pass (render provenance, fonts, overlap, glyphs, archetype
elements), print font, flow units, abbreviations, clinical labels, engineering language,
first-reader check (warning). No figure outside the plan; never shrink fonts to fix layout.

## Close
```
.\.venv\Scripts\python.exe tools/wf.py check
.\.venv\Scripts\python.exe tools/wf.py advance --note "K figures rendered (R|python); QC clean; visual: <reviewed | deferred to S23>; moved to legend: <n> items"
```
