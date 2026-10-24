# S21 - Collect authors and administrative statements

## Purpose
Collect user-owned authorship and compliance facts only after the scientific manuscript has
been assembled, independently reviewed, user-reviewed and matched to a journal.

## This stage needs the user
Ask once for the exact author order and names, affiliations, ORCIDs, corresponding-author
details, funding/grants, conflicts, code availability, acknowledgements, CRediT roles,
preprint and prior presentation. Never infer a missing item. Ethics, consent and data
availability are judged by the workflow (1.10.0): run `tools/declarations.py assess`, write
its conclusions into statements.md, and add only its printed open questions to the same
message (record answers with `tools/declarations.py answer <id> "<value>"`).
Do not ask for or write a study-registration statement unless the journal requires one; a
meta-analysis states its PROSPERO ID (or that it was not registered).
If people coded or adjudicated data and `idea.json` lacks `human_coders`, ask in the same
message for each coder's and adjudicator's specialty and years of experience.

Write the response faithfully to `project/00_input/author_info.json`, then create:
- `project/07_manuscript/title_page.md` using the already selected title without offering
  new title options;
- `project/07_manuscript/statements.md` headed `Declarations and Statements`, containing
  user-supplied facts, the exact sections required by the selected journal, and the verified
  master abbreviation list when consolidation is triggered.

If the chosen journal requires administrative declarations in the manuscript file, merge them
into the existing Declarations and Statements section between Discussion and References;
otherwise package administrative facts separately. Keep the centralized Abbreviations subsection
in the manuscript, and respect author blinding for administrative content. Do not move Keywords,
References or Figure legends, or duplicate the Declarations and Statements heading.

Read the official title-page instructions or journal template to determine whether a reference
count must appear. Inspect and synchronize the count with the distinct Pandoc citekeys actually
used in the canonical manuscript:
```
.\.venv\Scripts\python.exe tools/manuscript/reference_count.py show
.\.venv\Scripts\python.exe tools/manuscript/reference_count.py sync
```
Normal `sync` updates an existing field but does not invent an optional field. Use `sync --add`
only when the official guide requires a title-page reference count. The 45--60-paper literature
library is a research resource, not the number to report on the title page.

Preserve the verified abbreviation list prepared at S17. Reconcile any later additions
across figure legends, table captions and finished workbooks. When there are more than eight
unique defined terms or a local list exceeds 50 words, keep `## Abbreviations` under
`# Declarations and Statements`, define every term once, remove all repeated
`Abbreviations:` blocks from legends/captions and the table-building script, regenerate and
visually check affected workbooks, and insert the Declarations and Statements section
between Discussion and References in `full_manuscript.md`. If the journal explicitly
requires local definitions, retain them only when `target_journal.json` records
`abbreviation_placement=local_required` and the official rule URL.

## Outputs
- `00_input/author_info.json`
- `07_manuscript/title_page.md` -> written to `08_submission/manuscript/title_page.md`
- `07_manuscript/statements.md` -> written to `08_submission/manuscript/statements.md`

`00_input/author_info.json` is administrative and is not an analysis input, so writing it does
not touch the S06 reproducibility proof.

Both are journal facts: a title page's layout and which statements are mandatory come from the
chosen journal's guide, not from the science. Write them into the variant that S20 opened. The
gates resolve there on their own, so the paths above are the logical names, not the disk paths.

## Hard rules
- Never invent an author, affiliation, ORCID, email, ethics number, funding source or
  contribution.
- Do not write into `07_manuscript/`. It was frozen when the user released S19.
- Do not alter the selected scientific title merely to accommodate the title page.
- Do not draft or insert an AI-use disclosure unless the user explicitly requested that
  exact content.
- If the title page reports a reference count, it must equal the number of distinct citekeys
  actually used in `full_manuscript.md`, never the size of `library.json` or `refs.bib`.
- Do not use the literal down-arrow character or manual line breaks as visible layout marks.

## Close
```
.\.venv\Scripts\python.exe tools/wf.py check
.\.venv\Scripts\python.exe tools/wf.py advance --note "author/admin facts supplied; title page and required statements assembled; missing user-owned fields=<none or list>"
```
