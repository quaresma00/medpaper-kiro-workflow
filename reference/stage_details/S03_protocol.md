# S03 - Protocol v1 + data acquisition plan - details

> Long form of `pipeline/stages/S03_protocol.md` (moved out of the card in 1.12.0 so the
> card stays short). Read only the section you need; the card has the commands.
>
> 1.12.0 supersedes older wording below where they differ: long runs use `--wait` (one
> blocking call, heartbeat <= 30 s) and logs live in `.wf/logs/` (or `temp/logs/`);
> `wf check` prints failures + one summary line by default; in `deferred` visual mode no
> DEFER decision is recorded (the look is owed at S23); the `medpaper-reviewer` agent
> writes only its own `report.md` in the review bundle; declaration and section heading
> names come from `target_journal.json` (defaults otherwise).

## Purpose
Commit to a design before seeing the data, so that later choices are visibly
pre-specified rather than fitted to whatever happened to be significant.

## Procedure
1. No study registration and no reporting checklist are chosen or filled here. Retrospective
   database / registry / own-centre retrospective studies need no registration; a checklist is
   written only at S23 if the chosen journal requires one. Exception - systematic review /
   meta-analysis: register the protocol on PROSPERO before screening, record the registration
   ID in `Ethics`; if not registered, say so in Methods. Its PRISMA flow diagram and checklist
   are part of the normal flow.
2. Write `project/01_protocol/protocol_v1.md` with exactly these headings:
   `Objective`, `Design`, `Population and eligibility`, `Variables`,
   `Statistical analysis plan`, `Sample size / power`, `Ethics`.
   - `Variables`: for every exposure, outcome and covariate give the operational
     definition, the source field, the unit, and the handling of missing values.
     If a cutoff is used, say where the cutoff comes from (cite it).
   - `Statistical analysis plan`: name the primary model, the primary estimand, how
     confounders were chosen, how missing data is handled, what sensitivity analyses
     will run, and what constitutes the primary result. Pre-specify it now.
   - `Sample size / power`: if the dataset is fixed, state the precision it affords
     rather than pretending to a prospective calculation.
   - `Design precedent` (one PubMed search, not a review): for the **comparator**, the
     **denominator** and the **primary outcome definition** write one line each,
     `- Comparator: precedent yes - <PMID/DOI/[@key]>` or
     `- Comparator: precedent no - justification: <methodological reason>`. A choice with no
     precedent is allowed; an undefended one is what reviewers attack at submission.
     `design_precedent_recorded` checks the three lines here and again at S06.
   - Only if `data_source.manual_abstraction` is true (people code or adjudicate variables by
     hand), name each coder/adjudicator role with specialty and years of experience under
     `Variables` now. Automated extraction (public databases, coded fields, registry files)
     needs no coders, double entry, adjudication or agreement statistics (1.13.0).
3. Write `project/02_data/acquisition_plan.md` with exactly these headings:
   `Source`, `Access route`, `Licence and ethics`, `Protocol-defined data universe`,
   `Exact retrieval steps`, `Pagination and completeness proof`, `Expected shape`,
   `Known limitations`.
   - `Protocol-defined data universe` defines the complete set that should be acquired
     before post-acquisition eligibility exclusions. It may be a scientifically pre-specified
     sample design, but it must not be narrowed later for speed, token use, download size,
     memory or convenience.
     If the research design itself would sample from a larger accessible eligible population,
     show the sampling frame, method, target size, precision/power rationale and bias tradeoff
     to the user. Do not choose sampling autonomously. Continue only after their explicit
     approval is recorded:
```powershell
.\.venv\Scripts\python.exe tools\wf.py decide protocol_sampling_authorized YES --why "<the user-approved design and why a census is not the chosen scientific design>"
```
   `Exact retrieval steps` must be reproducible commands or a numbered manual procedure
   with URLs, query/filter text and version/release identifiers, not "download the dataset".
   State every server-side eligibility filter. Do not silently add a date restriction,
   field subset, first-N cap, `LIMIT`, `TOP`, `head()`, `sample()`, or maximum page count.
   - `Pagination and completeness proof` names the source's total-count field or count query,
     the raw receipt that will preserve it, the page/cursor termination rule, and how received
     records will be counted from raw payloads. A page-size parameter is allowed only when the
     plan follows every page/cursor until the terminal response.
4. If the data requires credentials, an application, or an IRB approval the user has not
   mentioned, raise it now.

## Outputs
- `01_protocol/protocol_v1.md`
- `02_data/acquisition_plan.md`

## Hard rules
- 1.10.0: under `Statistical analysis plan` add `### Statistical reporting plan` with the lines `Primary comparisons: <n>`, `Multiplicity: <method, or none and why>`, `Effect measures: <OR/HR/RR/MD ...>`, `Intervals: <95% CI ...>` (`statistical_reporting_plan`). Re-check `study_design`/`data_source` in idea.json against the acquisition plan (`study_basis_recorded`).
- Confirm the spelling system decided at S01 (`wf config get spelling`); table/figure label text is generated with it.
- Do not look at the data before the analysis plan is written down. If data was already
  inspected, say so in the protocol under `Deviations` at S06 rather than hiding it.
- The acquisition target is the entire protocol-defined universe. A small schema/connectivity
  pilot may be planned, but it is never an analysis dataset and must be followed by full
  acquisition before S04 can close.
- If an external source truly prevents full access, do not choose a subset yourself. Record
  the exact restriction and its receipt, ask the user whether a source-limited analysis is
  acceptable, and continue only after the explicit decision required at S04.
- No figures, no tables, no manuscript prose.

## Close
```
.\.venv\Scripts\python.exe tools/wf.py check
.\.venv\Scripts\python.exe tools/wf.py advance --note "protocol v1 fixed; primary model=<y>; data route=<z>"
```
