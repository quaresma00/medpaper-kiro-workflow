# S15 - Deep-read the papers that carry the Discussion

Goal: read ~5 full texts properly (abstracts cannot compare methods and effect sizes).
Details (selection roles, identity verdicts, registration, notes template, index JSON):
`reference/stage_details/S15_deepread.md`.

## Do
1. Select by argumentative need: closest prior study, strongest disagreement, the method
   reference, the largest/most authoritative study, the one a reviewer will cite against you.
2. Full text through the lawful cascade (1.23.0: cache -> PMC/Europe PMC -> Unpaywall ->
   OpenAlex incl. repository manuscripts -> Semantic Scholar -> CORE if keyed -> preprints),
   then check the identity verdict, not just the hash:
```
.\.venv\Scripts\python.exe tools/pubmed/fulltext.py fetch --citekey smith2023 --citekey lee2021
.\.venv\Scripts\python.exe tools/pubmed/fulltext.py verify --all-retrieved
```
   `identity=mismatch` -> fix `library.json` by rebuilding from EFetch; `indeterminate` -> read
   page one and confirm:
   `.\.venv\Scripts\python.exe tools/pubmed/fulltext.py verify --citekey smith2023 --confirm-identity "<title on page 1>"`.
   Still missing: the publisher page in the visible browser with the user's own institutional
   login (they log in once; only these papers, one at a time; `register --route
   browser-institutional --access authorized`); then `fulltext.py remaining` -> ONE message
   (DOI + title list, drop folder, author-request drafts, library list) and `fulltext.py
   ingest-drop` for PDFs the user places there. Never store logins or cookies.
3. Delegate each full text to the `medpaper-deepreader` agent, one invocation per paper (path,
   citekey, expected title, our finding). Do not read full texts in this context.
4. Write each returned set of notes to `06_refs/deepread/<citekey>.md` (>= 400 characters,
   template in details) and index them in `06_refs/deepread/deepread_index.json`
   (citekey, pmid, reason, access, fulltext, notes).
5. Update `03_analysis/notes.md` -> `Discussion points` with what the reads changed.

## Outputs
- `06_refs/deepread/deepread_index.json`
- (per-paper notes and fetched full texts)

## Gate
deepread_complete (non-overridable): every selected paper in the library, retrieval
manifest hash unchanged, `identity=match`, substantive notes, a recorded reason. Every
indexed paper must be cited in the Discussion (S16).

## Close
```
.\.venv\Scripts\python.exe tools/wf.py check
.\.venv\Scripts\python.exe tools/wf.py advance --note "<n> deep reads: <citekeys>; changed my view on: <...>"
```
