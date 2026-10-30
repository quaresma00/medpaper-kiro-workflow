# S13 - Build the verified reference library

Goal: about 50 real references with real abstracts, verified live against PubMed; all
literature claims in the Introduction and Discussion come from here.
Details (coverage plan, verification proof, export rules): `reference/stage_details/S13_reflib.md`.

## Do
1. Plan coverage by argument role: problem and burden, what is known, prior work extended,
   Methods citations, agreeing and disagreeing studies, guideline/definition sources.
2. Build (only these tools ever write the library files):
```
.\.venv\Scripts\python.exe tools/pubmed/build_library.py --topic "<core topic>" --target 50
.\.venv\Scripts\python.exe tools/pubmed/build_library.py --add-query "<gap area>" --target 50
.\.venv\Scripts\python.exe tools/pubmed/build_library.py --add-ids 12345678,23456789
```
3. Verify (fresh EFetch; failures are quarantined, never patched):
```
.\.venv\Scripts\python.exe tools/pubmed/verify.py
.\.venv\Scripts\python.exe tools/pubmed/verify.py --check
```
4. Export (brace-protects proper nouns/acronyms with the same rule the gate uses, ISO
   `shortjournal`, full page ranges, particle surnames):
```
.\.venv\Scripts\python.exe tools/pubmed/build_library.py --export
```
5. `06_refs/coverage.json` {"roles": {background, gap, methods, comparison, mechanism: [keys]},
   "not_applicable": {role: reason}}. No count target here (45-60 is an S17 health check).
6. Read the abstracts; add citekey-tagged points to `03_analysis/notes.md`.

## Outputs
- `06_refs/library.json`
- `06_refs/verified.json`
- `06_refs/refs.bib`
- `06_refs/refs.ris`

## Gate
reference provenance (live, non-overridable), library/bib/ris agree, bib format clean,
argument roles covered. No abstract, no entry (1.14.0: unless `--allow-fulltext` and an
identity-verified full text). `verified: true` by itself has no authority;
never invent or hand-edit a citekey, PMID, DOI or bibliographic field. Flag retracted records.

## Close
```
.\.venv\Scripts\python.exe tools/wf.py check
.\.venv\Scripts\python.exe tools/wf.py advance --note "library: <n> fresh-PubMed-proven entries with abstracts; independent live gate passed; coverage gaps: <...>"
```
