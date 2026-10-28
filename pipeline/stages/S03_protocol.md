# S03 - Protocol v1 + data acquisition plan

Goal: commit to the design before seeing the data.
Details (heading-by-heading content, sampling rule, pagination proof): `reference/stage_details/S03_protocol.md`.

## Do
1. No registration and no reporting checklist here: retrospective database, registry and
   own-centre studies need no registration; a checklist is written at S23 only if the
   journal requires one. Systematic review / meta-analysis: register on PROSPERO before
   screening (ID under `Ethics`).
2. Write `01_protocol/protocol_v1.md` with headings `Objective`, `Design`,
   `Population and eligibility`, `Variables`, `Statistical analysis plan`,
   `Sample size / power`, `Ethics`:
   - Variables: operational definition, source field, unit, missing-value handling, cited cutoffs;
     only if `data_source.manual_abstraction` is true: coders/adjudicators with specialty and
     experience (automated extraction needs no multi-person checks).
   - Statistical analysis plan: primary model and estimand, confounder choice, missing data,
     sensitivity analyses, primary result; plus `### Statistical reporting plan` with
     `Primary comparisons: <n>`, `Multiplicity: <...>`, `Effect measures: <...>`, `Intervals: <...>`.
   - `Design precedent`: one line each for Comparator, Denominator, Primary outcome
     (`precedent yes - <PMID/[@key]>` or `precedent no - justification: <reason>`).
3. Write `02_data/acquisition_plan.md` with `Source`, `Access route`, `Licence and ethics`,
   `Protocol-defined data universe`, `Exact retrieval steps`, `Pagination and completeness proof`,
   `Expected shape`, `Known limitations`. The universe is never narrowed for speed or size;
   no silent LIMIT/TOP/head()/sample()/first-N/date cap.
4. Scientific sampling of a larger accessible population needs the user's approval first:
```powershell
.\.venv\Scripts\python.exe tools\wf.py decide protocol_sampling_authorized YES --why "<the user-approved design and why a census is not the chosen scientific design>"
```

## Ask the user
Credentials, applications or IRB approvals the plan needs and they have not mentioned;
any sampling design (frame, method, size, bias tradeoff).

## Outputs
- `01_protocol/protocol_v1.md`
- `02_data/acquisition_plan.md`

## Gate
sections present, design precedent, statistical reporting plan, study basis. No figures,
tables or prose; data not inspected before the plan (if it was, record it at S06).

## Close
```
.\.venv\Scripts\python.exe tools/wf.py check
.\.venv\Scripts\python.exe tools/wf.py advance --note "protocol v1 fixed; primary model=<y>; data route=<z>"
```
