# S21 - Collect authors and administrative statements

Goal: user-owned authorship and compliance facts, collected once, after the science is
reviewed and the journal chosen.
Details (statements placement, blinding, abbreviation placement, reference count): `reference/stage_details/S21_authors.md`.

## Ask the user (one message)
Exact author order and names, affiliations, ORCIDs, corresponding-author details,
funding/grants, conflicts, code availability, acknowledgements, CRediT roles, preprint and
prior presentation; coders'/adjudicators' specialty and experience only if the study basis
declares manual abstraction (`data_source.manual_abstraction`) and `human_coders` is
missing. Ethics, consent and data availability are judged by the workflow - add only the
open questions this prints:
```
.\.venv\Scripts\python.exe tools/declarations.py assess
```
Record answers with `tools/declarations.py answer <id> "<value>"`. No registration statement
unless the journal requires one (a meta-analysis states its PROSPERO ID). Never infer a
missing item; never draft an AI-use disclosure unless the user asks for that exact content.

## Do
1. Write the answers faithfully to `00_input/author_info.json` (administrative; does not touch
   the reproduction proof).
2. In the journal variant (`08_submission/manuscript/`, never `07_manuscript/`): `title_page.md`
   with the selected title unchanged, and `statements.md` with the user's facts, the
   declarations the journal requires (its heading names and order from `target_journal.json`)
   and the central abbreviation list. Each display keeps its own abbreviation definitions
   unless the journal records `abbreviation_placement=central_required`.
3. Reference count only if the title-page guide requires it (never the library size):
```
.\.venv\Scripts\python.exe tools/manuscript/reference_count.py show
.\.venv\Scripts\python.exe tools/manuscript/reference_count.py sync
```
   `sync --add` only when the guide requires the field.

## Outputs
- `00_input/author_info.json`
- `07_manuscript/title_page.md` (written to `08_submission/manuscript/title_page.md`)
- `07_manuscript/statements.md` (written to `08_submission/manuscript/statements.md`)

## Gate
declarations assessed, structure and declarations order, title-page reference count,
abbreviations, freeze intact and variant ready. No down-arrow characters or manual line breaks.

## Close
```
.\.venv\Scripts\python.exe tools/wf.py check
.\.venv\Scripts\python.exe tools/wf.py advance --note "author/admin facts supplied; title page and required statements assembled; missing user-owned fields=<none or list>"
```
