# S08 - Methods - details

> Long form of `pipeline/stages/S08_methods.md` (moved out of the card in 1.12.0 so the
> card stays short). Read only the section you need; the card has the commands.
>
> 1.12.0 supersedes older wording below where they differ: long runs use `--wait` (one
> blocking call, heartbeat <= 30 s) and logs live in `.wf/logs/` (or `temp/logs/`);
> `wf check` prints failures + one summary line by default; in `deferred` visual mode no
> DEFER decision is recorded (the look is owed at S23); the `medpaper-reviewer` agent
> writes only its own `report.md` in the review bundle; declaration and section heading
> names come from `target_journal.json` (defaults otherwise).

## Purpose
Write a concise, journal-native main Methods section. Create a supplementary Methods file
only when reproducibility requires detail that would obscure the main narrative.

## Inputs
- `01_protocol/protocol_final.md` and `01_protocol/protocol_diff.md`
- `02_data/codebook.md`, `02_data/provenance.md`
- `03_analysis/method_scan.md` (for the methods you cite)
- `03_analysis/results/*.json` (for every number)
- `reference/methods-structure.md` (structure and main-versus-supplement boundary)

## Procedure
1. Read `reference/methods-structure.md`, then re-read the protocol. The guide supplies a flexible architecture, not a mandatory heading template.
   The Methods describes what was actually done, in the order a medical reader needs it.
2. Before drafting, choose and record a compact heading map appropriate to this design. For
   an ordinary original clinical study, prefer about four to seven substantive subsections:
   design/setting; participants or data source; design-specific procedures or measurements;
   outcomes/variables; and statistical analysis. Merge short adjacent topics. Do not create
   a heading merely because a checklist contains an item.
3. Make `Statistical analysis` the final main-Methods subsection for quantitative studies
   (`Data analysis` for qualitative studies; `Evidence synthesis` or equivalent for reviews),
   unless the target journal's current examples clearly use another order. Put prespecified
   sensitivity, subgroup, missing-data and software details inside that subsection when they
   can be stated briefly. Do not append automatic standalone headings for them after it.
4. Write `project/07_manuscript/methods.md`. It must retain the primary design, setting,
   eligibility, exposures/interventions/tests, primary outcomes and primary analysis needed
   to understand validity and interpret the Results.
5. If—and only if—implementation detail is genuinely long, write
   `project/07_manuscript/supplementary_methods.md` and refer to it once from the main Methods.
   Suitable content includes complete search strings, code lists, assay protocols, model
   tuning grids, full imputation or sensitivity specifications, interview guides and a full
   statistical analysis plan. Do not move a core design decision or primary analysis there.
   Supplementary Methods is prose only: do not embed Markdown, HTML or grid tables. Any
   genuinely tabular material must already be planned as `Table S*`, built later under
   `04_tables/supplementary/` with the three-line table writer, and referenced from the prose.
   Do not use `---`, `***` or `___` as visual separators; use ordinary paragraph spacing.
6. Cite methodological choices with pandoc markers `[@key]`—the cutoff you adopted, the
   scoring system, the model. Keys must come from records already
   retrieved this session.
7. Numbers—study period, follow-up, n screened/excluded/analysed, software versions—must
   already exist in `03_analysis/results/*.json`. If a number you need is not there, go back
   and dump it from code rather than typing it.
8. Do not describe an analysis you did not run, and do not omit one you did.

## Outputs
- `07_manuscript/methods.md`
- `07_manuscript/supplementary_methods.md` (optional; only when justified)

## Hard rules
- 1.11.0 layering: body Methods state principles (what was standardised, how duplicates were identified, which definitions applied); implementation detail - parsing, matching rules, character handling, code-level steps, file formats, re-execution - goes to Supplementary Methods. `engineering_language_clean` warns on such terms here and blocks them in Results/Discussion/Abstract, legends, tables and in-figure text; a term the paper genuinely needs goes to `.wf/language_allowlist.json` with a reason. Use the display dictionary's clinical labels, never internal group names.
- 1.10.0: verify each methodological citation (statistics, software, definitions, guidelines) when you introduce it: `tools/pubmed/build_library.py --add-ids <PMID>` then `tools/pubmed/verify.py`. The S08 gate re-fetches every Methods citekey live from PubMed (`reference_provenance cited_in`); replace a failing one now, not at S13.
- Body text is continuous paragraphs (1.9.0). Lists only where a sentence truly cannot carry the content (rarely more than one short list per section); every result, count, criterion, covariate and sensitivity finding is written as a sentence. `prose_not_lists` fails above `body_list_items_max` items or `body_list_share_max` of the blocks.
- Write only Methods-stage files. Do not also write Results.
- No default boilerplate subsections after the analysis subsection.
- The optional supplement may extend reproducibility, never hide core validity information.
- Supplementary Methods contains no embedded table or Markdown horizontal-rule residue.
  Tabular content belongs in the supplementary-tables workbook and must pass the S10
  three-line-table gate.
- Every number traceable to results JSON (gate: `numbers_have_provenance`).
- No placeholders. `TODO`, `TBD`, `xx.x` and friends fail the gate.
- Past tense, declarative. No "we aimed to comprehensively investigate".

## Close
```
.\.venv\Scripts\python.exe tools\wf.py check
.\.venv\Scripts\python.exe tools\wf.py advance --note "methods drafted; heading map: <...>; supplementary Methods: <not needed/path and why>; citations used: <n>"
```

