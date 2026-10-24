# S01 - Intake: normalize the research idea

Goal: turn the user's idea into a machine-readable spec every later stage argues against.
Details (JSON template, notes headings): `reference/stage_details/S01_intake.md` - read only if needed.

## Do
1. Save the idea under `00_input/` (pasted text -> `00_input/idea_source.md`) and read it in full.
2. Write `01_protocol/idea.json` (template in the details file): title, design, population,
   exposure, comparator, outcomes, covariates, novelty, data-source candidates, the structured
   `study_design` and `data_source` {type, name, third_party, redistributable, deidentified,
   vulnerable_populations}, and `open_questions`. Unknown = `null` + an open question; never guess.
3. Create `03_analysis/notes.md` with `## Introduction points`, `## Discussion points`,
   `## Limitations`, `## Surprises / must-not-forget` and a first pass at each.

## Ask the user (one message)
- Anything in `open_questions` that would change the design (population, exposure
  definition, outcome timing).
- `study_design` / `data_source` if the idea does not state them (ethics, consent and data
  availability are later judged from them).
- Who codes or adjudicates variables, if anyone: role, specialty, years of experience
  (`human_coders`).
- British spelling only if wanted (`wf config set spelling british`; default american).

## Outputs
- `01_protocol/idea.json`
- `03_analysis/notes.md`

## Gate
outputs, idea.json keys, study basis recorded, nothing produced ahead of schedule.
No literature search (S02) and no manuscript prose here.

## Close
```
.\.venv\Scripts\python.exe tools/wf.py check
.\.venv\Scripts\python.exe tools/wf.py advance --note "idea normalized; design=<x>; unresolved: <...>"
```
