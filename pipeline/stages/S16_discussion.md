# S16 - Discussion

Goal: interpret the finding against the literature actually read. One file, this stage only.
Details (move-by-move structure, inputs): `reference/stage_details/S16_discussion.md`.

## Do
1. Build the writer bundle (deep-read notes, library, results in words, display dictionary,
   journal profile, exemplars) and delegate the prose to the `medpaper-clinical-writer`
   agent with the printed MANIFEST path:
```
.\.venv\Scripts\python.exe tools/manuscript/writer_bundle.py build --stage S16_discussion
```
2. Structure, as continuous prose without subheadings (only if the journal requires them):
   principal finding (no new numbers) -> comparison with prior work (every deep-read paper,
   with a methodological reason for disagreement) -> interpretation, labelled as inference ->
   proportionate implications -> specific strengths and limitations (every protocol deviation,
   direction of each bias) -> a two-to-three-sentence conclusion. Adjacent citations in one
   group `[@a; @b]`.
3. Review the written `07_manuscript/discussion.md`, then `wf check` (engineering language,
   prose, citations, deep reads cited, soft word/reference budget).

## Outputs
- `07_manuscript/discussion.md`

## Gate
citekeys resolve and are live-verified, deep reads cited, numbers traceable (a prior
study's number only in the same sentence as its verified citation), engineering language,
continuous prose; word/reference counts are soft upper budgets until S20. No causal
language for observational designs, no pipeline history, no stock closers, no unsupported
"first".

## Close
```
.\.venv\Scripts\python.exe tools/wf.py advance --note "discussion drafted; <n> words, <k> refs; disagreements addressed: <citekeys>"
```
