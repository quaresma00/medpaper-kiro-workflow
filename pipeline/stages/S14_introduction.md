# S14 - Introduction

## Purpose
Write the Introduction from the verified library's abstracts plus `notes.md`. One file,
this stage only.

## Inputs
- `06_refs/library.json` (abstracts - read them, do not recall them)
- `03_analysis/notes.md` -> `Introduction points`
- `01_protocol/feasibility.md` -> the gap argument, already reasoned once
- `01_protocol/protocol_final.md` -> the objective, stated exactly

## Procedure
1. Four moves, in order, and nothing else:
   1. The clinical problem and why it matters (burden, consequence).
   2. What is established. Cite the strongest evidence, not the most convenient.
   3. What is not established - the specific gap, narrow enough to be closable by this
      study. This is the sentence the reviewer tests the whole paper against.
   4. The objective. One sentence, matching `protocol_final.md` word for word in substance.
2. Write `project/07_manuscript/introduction.md` through the `medpaper-clinical-writer` agent
   (1.12.0): build its bundle and pass the printed MANIFEST path. Cite with pandoc markers
   `[@key]`, keys from `refs.bib` only.
```
.\.venv\Scripts\python.exe tools/manuscript/writer_bundle.py build --stage S14_introduction
```
3. Check the soft upper budgets (no lower bound) and the engineering-language lint:
```
.\.venv\Scripts\python.exe tools/wf.py config list        # intro_words_max, intro_refs_min/max
.\.venv\Scripts\python.exe tools/wf.py check
```
   If the target journal turns out to want something different, change the target rather
   than padding: `.\.venv\Scripts\python.exe tools/wf.py config set intro_words_max 600`.

## Outputs
- `07_manuscript/introduction.md`

## Hard rules
- 1.10.0: word and reference targets are soft budgets (warnings) while writing; hard limits start after S20 with the chosen journal.
- Body text is continuous paragraphs (1.9.0). Lists only where a sentence truly cannot carry the content (rarely more than one short list per section); every result, count, criterion, covariate and sensitivity finding is written as a sentence. `prose_not_lists` fails above `body_list_items_max` items or `body_list_share_max` of the blocks.
- ONE section file this stage. No Discussion, no Abstract.
- Every citation verified. Every claim attributable to an abstract you read.
- No results in the Introduction. No hypothesis stated as if already confirmed.
- No stock openers: not "In recent years", not "has attracted increasing attention",
  not "plays a crucial role". The gate flags these.
- Do not restate the whole field. Three to five paragraphs, tightest possible path to the
  gap.

## Close
```
.\.venv\Scripts\python.exe tools/wf.py advance --note "introduction drafted; <n> words, <k> refs; gap sentence: <quote it>"
```
