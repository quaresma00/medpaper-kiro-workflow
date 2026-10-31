# S21 - Collect authors and administrative statements - details

> 1.15.0 supersedes older wording below where they differ: AI/LLM use is asked once, with the
> journal's rule shown verbatim (`tools/declarations.py ai-rule`); the author's factual answer
> is recorded (`tools/declarations.py ai --used yes|no --tool --purpose --words`) and the
> printed statement goes into `statements.md`; audits read the fact instead of listing it as
> pending. An abbreviation list is written as `## Abbreviations`; the builder moves it after
> the keywords (or drops it for `abbreviation_list: none`), never inside Declarations.

> Long form of `pipeline/stages/S21_authors.md` (moved out of the card in 1.12.0 so the
> card stays short). Read only the section you need; the card has the commands.
>
> 1.12.0 supersedes older wording below where they differ: long runs use `--wait` (one
> blocking call, heartbeat <= 30 s) and logs live in `.wf/logs/` (or `temp/logs/`);
> `wf check` prints failures + one summary line by default; in `deferred` visual mode no
> DEFER decision is recorded (the look is owed at S23); the `medpaper-reviewer` agent
> writes only its own `report.md` in the review bundle; declaration and section heading
> names come from `target_journal.json` (defaults otherwise).

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
Only if the study basis declares manual abstraction (`data_source.manual_abstraction` true)
and `idea.json` lacks `human_coders`, ask in the same message for each coder's and
adjudicator's specialty and years of experience; automated extraction never triggers it.

Write the response faithfully to `project/00_input/author_info.json` (the corresponding author
as `"corresponding": {"name": ..., "email": ..., "affiliation": ...}`; the supplementary
information page reads `affiliation`, or `address` in older files), then create:
- `project/07_manuscript/title_page.md` using the already selected title without offering
  new title options;
- `project/07_manuscript/statements.md` headed `Declarations and Statements`, containing
  user-supplied facts, the exact sections required by the selected journal, and the central
  abbreviation list.

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

Preserve the central abbreviation list prepared at S17 and reconcile later additions across
legends, captions and workbooks. 1.11.0: each table footnote and figure legend keeps its own
definitions (self-contained displays) and the manuscript keeps the central list; remove local
blocks only when `target_journal.json` records `abbreviation_placement=central_required` with
the official rule in `abbreviation_rule_source`. A paper pinned before 1.11.0 keeps its
recorded legacy placement until `wf migrate`.

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
