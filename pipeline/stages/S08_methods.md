# S08 - Methods

Goal: a concise, journal-native Methods; Supplementary Methods only when reproducibility needs it.
Details (heading map, main-vs-supplement boundary, citation rules): `reference/stage_details/S08_methods.md`
and `reference/methods-structure.md`.

## Do
1. Decide the heading map (about 4-7 subsections; `Statistical analysis` last) and record it.
2. Verify each methodological citation as you introduce it:
   `.\.venv\Scripts\python.exe tools/pubmed/build_library.py --add-ids <PMID>` then
   `.\.venv\Scripts\python.exe tools/pubmed/verify.py`.
3. Build the writer bundle and delegate the prose to the `medpaper-clinical-writer` agent
   (pass it the printed MANIFEST path only; it never sees code, JSON keys or logs); it writes
   `project/07_manuscript/methods.md`:
```
.\.venv\Scripts\python.exe tools/manuscript/writer_bundle.py build --stage S08_methods
```
4. Layering rule: body Methods state principles (design, population, definitions, outcomes,
   statistics); implementation detail - parsing, matching rules, character handling, file
   formats, re-execution - goes to `07_manuscript/supplementary_methods.md` (prose only, no
   tables or rules) or nowhere. Clinical labels from the display dictionary only.
   1.24.0: one purpose clause per sensitivity/subgroup analysis, no prebuttals (`reference/writing_voice.md`).
5. 1.23.0: polish this section right after the draft, by an independent medical editor
   (medical register, de-AI, no engineering or data-processing narration - "duplicate reports
   were removed following the FDA-recommended approach" - prose not lists, abbreviations;
   numbers and citations unchanged). `required_statements.md` in the bundle (pooling,
   single-imputation reason, derived-variable units) must be stated. Describe the analysis
   performed; never an initial plan or protocol deviations:
```
.\.venv\Scripts\python.exe tools/manuscript/writer_bundle.py receipt --stage S08_methods --section methods
.\.venv\Scripts\python.exe tools/manuscript/writer_bundle.py edit --section methods
.\.venv\Scripts\python.exe tools/manuscript/writer_bundle.py polished --section methods
```
   Delegate `edit`'s MANIFEST to `medpaper-medical-editor` between the last two commands;
   the same for `supplementary_methods` when written (`section_polished`). Then lint:
```
.\.venv\Scripts\python.exe tools/text/polish.py lint --file 07_manuscript/methods.md
```

## Outputs
- `07_manuscript/methods.md`
- `07_manuscript/supplementary_methods.md` (optional; only when justified)

## Gate
numbers traceable to results JSON, citations live-verified, engineering language (warning
in Methods; 1.23.0 `section_polished` blocks it in the polished text), clinical labels, continuous prose (`prose_not_lists`), no placeholders, only
this stage's file written. Past tense, declarative.

## Close
```
.\.venv\Scripts\python.exe tools\wf.py check
.\.venv\Scripts\python.exe tools\wf.py advance --note "methods drafted; heading map: <...>; supplementary Methods: <not needed/path and why>; citations used: <n>"
```
