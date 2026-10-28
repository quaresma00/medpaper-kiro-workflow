# S17 - Select the title and assemble the complete manuscript

Goal: the first complete, readable manuscript - the canonical source for review, editing,
polishing and packaging. No author details yet.
Details (title scoring, assembly order, statements file): `reference/stage_details/S17_assemble.md`.

## Do
1. Choose the single best title yourself (design accuracy, PICO specificity, searchability,
   brevity, no overclaim) -> `07_manuscript/title.md` (one level-1 heading).
2. `07_manuscript/abstract.md` (structure suited to the design; numbers from results JSON;
   conclusion consistent with the Discussion), polished before assembly
   (`tools/text/polish.py lint --file 07_manuscript/abstract.md`; `section_language_clean`),
   and `07_manuscript/keywords.md` (`Keywords: a, b, c`, 3-6 terms or the journal's min/max).
3. Central abbreviation list in `07_manuscript/statements.md` under the declarations heading
   (`## Abbreviations`); it is in addition to each display's own definitions. Then assemble:
```
.\.venv\Scripts\python.exe tools/manuscript/assemble.py
```
   Order: title, Abstract, Keywords, Introduction, Methods, Results, Discussion, optional
   declarations, References, Figure legends. Journal heading names are applied at the DOCX
   build, not in Markdown.
4. Read it end to end; fix the source section (never the assembled file) and re-assemble.
5. Only if `wf check` says the proof is stale (analysis code, data or results changed since
   S06) reproduce; never "to be safe" - an unchanged proof is accepted by hash:
```
.\.venv\Scripts\python.exe tools/reproduce.py run --wait
```

## Outputs
- `07_manuscript/title.md`
- `07_manuscript/abstract.md`
- `07_manuscript/keywords.md`
- `07_manuscript/full_manuscript.md`
- `07_manuscript/statements.md` (optional abbreviation list only)

## Gate
assembly matches sources, structure, citations live-verified, numbers traceable,
proportion denominators, engineering language, clinical labels, analysis reproduces,
every library entry cited or given a reason in `06_refs/uncited_reasons.json`. Length and
the 45-60 reference band only warn here (report them in the note).

## Close
```
.\.venv\Scripts\python.exe tools/wf.py check
.\.venv\Scripts\python.exe tools/wf.py advance --note "full manuscript assembled; selected title: <title>; keywords=<n>; figure legends=<n>"
```
