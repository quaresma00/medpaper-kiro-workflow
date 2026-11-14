# S16 - Discussion

Goal: interpret the finding against the literature actually read. One file, this stage only.
Details (move-by-move structure, inputs): `reference/stage_details/S16_discussion.md`.

## Do
1. Build the writer bundle (1.19.0: key findings in words with the primary estimate once,
   deep-read comparison points, known limitations, library, journal profile - no result
   tables, no display ids) and delegate to the `medpaper-clinical-writer` agent with the
   printed MANIFEST path. Also for any later rewrite of the Discussion:
```
.\.venv\Scripts\python.exe tools/manuscript/writer_bundle.py build --stage S16_discussion
```
   The writer first writes the outline `.wf/writer/discussion_outline.md` (<= 200 words,
   never exported): Principal findings (F1, F2 ...); Comparison with previous studies
   (citekeys, why results differ); Possible mechanisms; Clinical and research implications;
   Strengths and limitations (likely direction of bias); Conclusion.
2. Structure - interpret, do not restate the Results:
   - principal findings in one short paragraph, the primary estimate once, no other numbers,
     no table/figure citations;
   - compare with previous studies (every deep-read paper) and explain why results differ
     (design, population, definitions, follow-up);
   - possible mechanisms or plausibility, labelled as inference;
   - clinical and research implications, proportionate to the evidence;
   - strengths and limitations with the likely direction and size of each bias (never an
     initial plan or protocol deviations);
   - no new results, no overclaiming; a two-to-three-sentence conclusion;
   - continuous prose without subheadings (unless the journal requires them); adjacent
     citations in one group `[@a; @b]`. Never cite supplementary items (Table S2).
   - 1.24.0: confident, not defensive - limitations in one paragraph (3-5 items, bias direction), each caveat once, no prebuttals (`reference/writing_voice.md`).
   - 1.25.1: the first paragraph leads with the primary outcome, whatever its direction; the limitations paragraph is always present with the design caveat (`limitations_present`).
3. 1.23.0: right after the draft the `medpaper-medical-editor` polishes it: `writer_bundle.py
   receipt --stage S16_discussion`, `edit --section discussion`, delegate, `polished --section
   discussion` (`section_polished`; medical register, de-AI, no engineering narration,
   abbreviations, facts unchanged); fix every blocking item, then `wf check`
   (`section_language_clean`, citations, deep reads cited, soft word/reference budget):
```
.\.venv\Scripts\python.exe tools/text/polish.py lint --file 07_manuscript/discussion.md
```

## Outputs
- `07_manuscript/discussion.md`

## Gate
outline ready (1.19.0: labels present, every key finding compared with a verified study or
'no prior study'); Discussion checks in the section-language gate (no supplementary display
citations, <= 2 table/figure citations, <= 3 sentences with own result numbers, <= 2
restated Results sentences, >= 5 prior studies as a warning; a paper changes a threshold
only in `.wf/config.toml` [targets] with `discussion_thresholds_reason`);
citekeys resolve and are live-verified, deep reads cited, numbers traceable (a prior
study's number only in the same sentence as its verified citation, and 1.14.0: only when
that number is in the cited source's abstract, `06_refs/deepread/<key>.md` or its
identity-verified full text - quote the passage in the notes or remove it), engineering language,
continuous prose; word/reference counts are soft upper budgets until S20. No causal
language for observational designs, no pipeline history, no stock closers, no unsupported
"first".

## Close
```
.\.venv\Scripts\python.exe tools/wf.py advance --note "discussion drafted; <n> words, <k> refs; disagreements addressed: <citekeys>"
```
