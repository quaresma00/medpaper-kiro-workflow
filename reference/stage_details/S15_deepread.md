# S15 - Deep-read the papers that carry the Discussion - details

> Long form of `pipeline/stages/S15_deepread.md` (moved out of the card in 1.12.0 so the
> card stays short). Read only the section you need; the card has the commands.
>
> 1.12.0 supersedes older wording below where they differ: long runs use `--wait` (one
> blocking call, heartbeat <= 30 s) and logs live in `.wf/logs/` (or `temp/logs/`);
> `wf check` prints failures + one summary line by default; in `deferred` visual mode no
> DEFER decision is recorded (the look is owed at S23); the `medpaper-reviewer` agent
> writes only its own `report.md` in the review bundle; declaration and section heading
> names come from `target_journal.json` (defaults otherwise).

## Purpose
Abstracts are enough to frame the Introduction. They are not enough to compare methods and
effect sizes with prior work. Fetch and read ~5 full texts properly.

## Procedure
1. Select the papers that the Discussion genuinely depends on. Typically:
   - the closest prior study on the same question (whatever the direction of its result),
   - the study that most disagrees with your finding,
   - the methodological reference your approach stands on,
   - the largest or most authoritative study in the area,
   - the paper a reviewer will ask "why does your result differ from this one".
   Selection is by argumentative need, not by impact factor.
2. Fetch open-access full text. Legal open-access routes only:
```
.\.venv\Scripts\python.exe tools/pubmed/fulltext.py fetch --citekey smith2023 --citekey lee2021
```
   It tries Europe PMC / PMC, Unpaywall and OpenAlex, saves the PDF or XML to
   `06_refs/fulltext/`, and records the route, access basis, file hash **and an identity
   verdict** in `06_refs/fulltext/retrieval_manifest.json`.

   **Read the identity line, not just the hash.** The hash proves the bytes have not changed
   since download; it cannot tell you the bytes are the paper you asked for. A wrong PMCID in
   `library.json` fetches a completely different article and its receipt still verifies clean -
   that has actually happened here, and it put four wrong papers into a deep read. So each
   payload is asked who it is:
   - `identity=match` - a structured identifier in the JATS/HTML metadata agrees, or the
     library DOI appears in the PDF. Good to read.
   - `identity=mismatch` - the payload's own metadata names a different article. The file is
     **refused and not saved**, and no other route is tried, because the locator is wrong
     rather than the download. Fix `library.json` by rebuilding it from a fresh EFetch
     (`tools/pubmed/build_library.py`). Never hand-edit a PMCID to make this go away.
   - `identity=indeterminate` - typically an opaque PDF. Note that a PDF's *cited* DOIs prove
     nothing either way, which is why they are ignored. Open the file, read the title on page
     one, and record it:
```
.\.venv\Scripts\python.exe tools/pubmed/fulltext.py verify --citekey smith2023 --confirm-identity "<title on page 1>"
```
   To re-check everything already on disk without refetching:
```
.\.venv\Scripts\python.exe tools/pubmed/fulltext.py verify --all-retrieved
```
3. If a scholarly retrieval skill supplies an open-access file, or the user legally
   obtains one through institutional access, register the local copy before reading it:
```
.\.venv\Scripts\python.exe tools/pubmed/fulltext.py register --citekey smith2023 --file "C:\path\paper.pdf" --access oa --source-url "https://publisher.example/article" --route scansci-pdf
```
   For institutional access, use `--access authorized --authorization-note "<basis>"`.
   Do not use Sci-Hub or another unauthorized source. Do not request browser login,
   cookies or credentials unless the user explicitly authorizes that route. If only a
   paywalled link or abstract is available, replace the paper or leave the stage blocked;
   it does not count as a deep read.
4. **Delegate each full text to the `medpaper-deepreader` agent, one invocation per paper.**
   Do not read the full texts in this context: a single paper is tens of thousands of tokens
   and five will not fit, which is exactly how a deep read silently degrades into an abstract
   skim. Each invocation gets an isolated context, reads one paper end to end, and hands back
   the notes. Tell it the path to the registered local file and the finding it should be
   compared against.
   Then **you** write each returned set of notes to `06_refs/deepread/<citekey>.md`:
```markdown
# <citekey> - <short title>
## Design and population
## What they did differently from us
## Their key numbers
## How this supports or contradicts our finding
## What a reviewer would take from this
```
   Notes must be substantive; the gate rejects notes under 400 characters as evidence that
   no real read happened. If the agent reports abstract-only access, keep that line in the
   notes - a Discussion built on an abstract must say so.
5. Index them in `project/06_refs/deepread/deepread_index.json`:
```json
{"selected": [{"citekey": "", "pmid": "", "reason": "why this paper carries part of the Discussion",
  "access": "oa|authorized", "fulltext": "06_refs/fulltext/<file>.pdf",
  "notes": "06_refs/deepread/<citekey>.md"}]}
```
6. Update `03_analysis/notes.md` -> `Discussion points` with what the deep reads changed.
   If a deep read overturned an assumption, that is the most valuable output of this stage.

## Outputs
- `06_refs/deepread/deepread_index.json`
- (plus per-paper notes and fetched full texts)

## Hard rules
- Every selected citekey must already be in `library.json`.
- Every selected file must have a matching retrieval-manifest record and unchanged hash.
- Every selected file must carry `identity=match`. `deepread_complete` is non-overridable, so
  `--force` will not move it: a deep read of the wrong paper is worse than a missing one,
  because it puts confident sourced claims about a study nobody read into the Discussion.
- Tell the deep-reader agent the citekey **and** the expected title, and treat a mismatch
  report from it as authoritative over any manifest field.
- Every selection needs a recorded reason. "Highly cited" is not a reason.
- If a paper turns out not to matter, remove it from the index and record why - the gate at
  S16 requires every indexed paper to be cited in the Discussion.

## Close
```
.\.venv\Scripts\python.exe tools/wf.py check
.\.venv\Scripts\python.exe tools/wf.py advance --note "<n> deep reads: <citekeys>; changed my view on: <...>"
```
