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
5. Check the result, fix, and re-run the engineering-language lint (part of `wf check`).

## Outputs
- `07_manuscript/methods.md`
- `07_manuscript/supplementary_methods.md` (optional; only when justified)

## Gate
numbers traceable to results JSON, citations live-verified, engineering language (warning
in Methods), clinical labels, continuous prose (`prose_not_lists`), no placeholders, only
this stage's file written. Past tense, declarative.

## Close
```
.\.venv\Scripts\python.exe tools\wf.py check
.\.venv\Scripts\python.exe tools\wf.py advance --note "methods drafted; heading map: <...>; supplementary Methods: <not needed/path and why>; citations used: <n>"
```
