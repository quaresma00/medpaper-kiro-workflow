# S11 - Render figures, QC them by code, then look (now or at S23)

## Purpose
Produce journal-grade figures. Verification is two-phase: deterministic QC by code, then
visual inspection of the rendered PNG. Reading the plotting code is not verification.

**Phase 2 timing is controlled by `visual_review_mode`.** Check it before you start:
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
house palette**. Looking before the journal is known means looking twice. Deterministic QC has
no such problem: it is code, so it runs every round for free and still blocks here.

What deferring does not change: QC must be green at this stage, and the parked look is on two
ledgers (the DEFER decision and each figure's `visual_reviewed` flag). The S23 gate
`visual_debts_cleared` is **non-overridable** - `--force` will not move it.

Read `reference/figure-standards.md` before writing the first script, and read your
figure's entry in `reference/archetypes.toml` - that entry lists the elements the gate will
look for in the rendered figure.

**Also activate the `medical-sci-figure-skill` global skill** and read its atlas entry for the
chart type in hand (`references/figure_atlas.md`, `references/universal_laws.md`). It is the
authority on visual grammar: what the archetype is, which elements it must carry, what is
forbidden for it (a dynamite plot, a box plot at n<=5, a KM curve with no risk table, "400x"
written in a caption instead of an overlaid scale bar), and which journal palette to use. Its
wet-lab coverage is better than this pipeline's - dot-bar with SEM at n=3-8, paired dot-line,
violin/raincloud, Western blot panels, IHC/IF scale bars - and it carries a GraphPad-Prism
preset for those panels.

It is reading and styling, never the renderer. Build with `tools/figures/style.py` and judge
with `tools/figures/qc.py`, always. Anything drawn through `medfigure/recipes/` skips this
pipeline's `save()`, writes no sidecar, and leaves artist-level QC with nothing to read, so
`figures_qc_pass` cannot go green. Where the two disagree on a number - column widths, the font
floor, legend placement, panel titles, which QA engine - `reference/skill_policy.toml`
`[figure_authority]` records six, and every one resolves to this pipeline. In particular
do not call `medfigure.qa.audit_medical_figure()` on a pipeline figure: it reports the
pipeline's own SubFigure panel title as a critical failure.

## Procedure
1. **Check for a recipe first.** `tools/figures/recipes.py` covers the archetypes with the
   strictest requirements and satisfies them by construction:
```python
import sys; sys.path.insert(0, "tools")
from wfcore.paths import project_dir
from figures.style import apply_style, save
from figures.recipes import km_survival, forest_plot, roc_curve, volcano_plot

PROJECT = project_dir()
apply_style()                      # add palette="nejm" if the journal expects its house colours
fig, _ = km_survival(groups, time_points=[0, 12, 24, 36],
                     hr=1.87, hr_ci=[1.34, 2.61])   # values read from results JSON
save(fig, PROJECT / "05_figures/out/Figure1", width="single", archetype="km_survival")
```
   Recipes take statistics as **numbers, not display strings**, so read them out of
   `03_analysis/results/*.json`. Never pass a pre-formatted `"HR 1.87"` - that is how a
   hand-typed number reaches a figure.

2. For anything without a recipe, one script per figure under `project/05_figures/code/`,
   named after the plan's `script` field, starting from the shared style. Run every figure
   script with `python tools/wf.py run-script 05_figures/code/<script>.py`; never assume a
   physical `<engine>/project` directory exists:
```python
from wfcore.paths import project_dir
from figures.style import apply_style, figure, save

PROJECT = project_dir()
apply_style()                      # journal rcParams: fonts, line widths, no top/right spines
fig, panels = figure(width="double", height_mm=90, panels=(1, 2))   # SubFigure-based layout
...
save(fig, PROJECT / "05_figures/out/Figure1", width="double", archetype="box_jitter")
```
3. **Multi-panel figures are built panel-first.** Each panel is a `SubFigure` that owns its
   own axes, ticks, labels, legend and colorbar. Never place panels by hand with
   `add_axes`/`subplots_adjust`/pixel coordinates - one panel's tick labels will drift into
   its neighbour's space and every value change re-breaks the layout. Panel letters go at
   `(0, 1)` of the SubFigure, not inside the axes. `figure()` sets this up for you.
   One SubFigure is one *logical* panel: when two axes must stay column-aligned (a survival
   curve above its risk table, a plot above its marginal), put both inside the same
   SubFigure with `sharex=True`. Sibling SubFigures solve their layouts independently, so
   their axes are not guaranteed to line up.
4. **Deterministic QC first.** Fix everything code can detect before spending a look:
```
.\.venv\Scripts\python.exe tools/figures/qc.py --all
```
   From the rendered PNG: effective dpi against the target column width, content bounding
   box and the four margins, margin asymmetry, edge clipping, and mid-grey text-like
   regions (candidate leftover footnotes). From the live figure object via the sidecar
   `save()` writes: minimum font size and line width, panel tight-bbox overlap, clipped
   text, **missing font glyphs**, **tick-label collisions**, **dead bands between panels**,
   **bar baselines at zero**, and **the mandatory elements for the declared archetype**.
   Results land in `project/05_figures/qc/qc_report.json`.
   An `element:<name>` failure means the archetype's registry entry requires something the
   figure does not have - add it, or change the archetype if you picked the wrong one.
5. **Then look - only if `visual_review_mode = inline`.**
   In `deferred` mode skip to step 7 and do not open any PNG; step 9 records DEFER instead.

   Open the rendered PNG as an image and inspect it:
   `read_file project/05_figures/out/Figure1.png`. For a suspect panel, crop it first
   (`.\.venv\Scripts\python.exe tools/figures/qc.py --crop "Figure 1" --cols 2 --cell B`) and look at the
   crop rather than squinting at the whole plate. Check: fonts and missing glyphs; overlapping or
   clipped labels; legend placement and completeness; axis ranges, tick density, units,
   log labelling; colour consistency, colour-blind safety, greyscale legibility; margins
   and stray whitespace; panel alignment and panel-letter placement; line widths; point
   size, overplotting, transparency; significance markers and bracket heights; leftover
   explanatory text; overall resolution and aliasing.
   ImageGen may participate as a second visual critic when available, especially for clutter,
   hierarchy, contrast, clipping, text density and journal-native appearance. Treat its
   comments as review findings only. It must not redraw, regenerate, inpaint or otherwise
   edit a statistical figure, because that could change data geometry, labels or meaning.
   Apply accepted fixes in the plotting script and inspect the new deterministic render.
6. Fix the **script**, re-render, re-run QC, look again. Repeat until clean. Say in each
   round which findings came from QC and which came from looking.
   In `deferred` mode this loop runs on QC output alone; it is normally one or two rounds
   because QC failures name the defect precisely.
7. **Strip explanatory text from the panels.** Move only information needed to decode the
   figure to the legend: essential test/error-bar/threshold definitions, what a reference
   line means, and only a short abbreviation clause. Detailed adjustment sets, cohort provenance, software
   versions, interpretation and general caveats belong in Methods or supplementary Methods;
   do not dump them into the legend. Log every panel removal in
   `project/05_figures/moved_to_legend.md` as `Figure N | removed text | now in legend`,
   and record its correct prose destination in the same edit. Never fix this by greying the
   text down. Keep each legend within the configured 180-word ceiling. The legend identifies
   the display, maps panels and decodes symbols; it must not repeat which group was higher,
   restate an association, or reproduce effect estimates already reported in Results.
   Panel text that stays: axis titles and units, tick labels, panel letters, group labels,
   legend entries, significance markers, key data values (n, HR with CI, AUC, r), and
   guideline-mandated in-figure content (KM risk tables, CONSORT/PRISMA box text, scale
   bars). All of it black or near-black, at or above the size floor.
8. Write `project/05_figures/manifest.json`:
```json
{"built_at": "", "figures": [{"id": "Figure 1", "script": "", "png": "", "tiff": "",
  "width": "double", "size_mm": [180, 90], "dpi": 600, "review_rounds": 2}]}
```
9. Close phase 2 according to the mode.

   `inline` - record the look, per figure, only after genuinely loading each image:
```
.\.venv\Scripts\python.exe tools/figures/qc.py --confirm "Figure 1" --note "<what you saw / changed>"
.\.venv\Scripts\python.exe tools/wf.py decide figures_visually_confirmed YES --why "<per figure: what you saw and what you changed>"
```
   `deferred` - park it, stating the QC evidence you are relying on until S23:
```
.\.venv\Scripts\python.exe tools/wf.py decide figures_visually_confirmed DEFER --why "deterministic QC green for N figures: dpi/margins/fonts/overlap/glyphs/archetype elements all pass; colour semantics, legibility and clutter judgement deferred to the S23 contact-sheet pass once S20 fixes the journal's column width and palette"
```
   Never write `--confirm` for a figure you did not load, and never record YES on the strength
   of QC output. If an image cannot be loaded, say exactly that and report only the QC findings.

10. Delete scratch renders from `project/temp/`.

## Outputs
- `05_figures/manifest.json`
- `05_figures/qc/qc_report.json`
- `05_figures/moved_to_legend.md`
- (plus scripts in `05_figures/code/` and PNG+TIFF in `05_figures/out/`)

## Hard rules
- Never claim visual verification without having loaded the image. If the image cannot be
  loaded, say exactly that and report only the deterministic findings.
- `DEFER` is a scheduling decision, never a verdict. It says "not looked at yet", so it may
  never be reported as "figures verified". Deterministic QC must still be green to record it.
- Deferring never lowers a deterministic bar. Font floor, line-width floor, dpi, archetype
  elements and panel-overlap checks block here in both modes.
- ImageGen feedback never satisfies the visual-review decision by itself and never replaces
  source-code correction plus a fresh render.
- Never fix a layout problem by shrinking fonts below the floor or by nudging a single
  label's coordinates. Fix the layout structure (gridspec ratios, panel spans, SubFigure
  composition).
- No 3-D decoration, no gratuitous gridlines, no chartjunk.
- Do not add a figure that is not in the artifact plan.

## Close
```
.\.venv\Scripts\python.exe tools/wf.py check
.\.venv\Scripts\python.exe tools/wf.py advance --note "K figures rendered; QC clean; visual: <reviewed (rounds: ...) | DEFERRED to S23>; moved to legend: <n> items"
```
Say which it was in the note. `wf status` reprints every parked review until S23 clears it.
