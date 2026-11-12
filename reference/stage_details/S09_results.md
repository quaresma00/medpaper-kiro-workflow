# S09 - Results - details

> Long form of `pipeline/stages/S09_results.md` (1.23.0 moved the hard rules here so the card
> stays short and could take the science review step).

## Science review before writing (1.23.0, `science_review_before_writing`)
One round of the independent `medpaper-reviewer` in science mode, after S11 (tables and figures
final) and before the Results are written, in the same pass as the one contact-sheet look
(1.14 D2) and the display-text pass (1.20):
```
.\.venv\Scripts\python.exe tools/review_round.py start --scope science
```
The bundle holds the final protocol (question, design, data source, outcomes, statistical
plan), the S08 Methods draft, the results in words and `key_results.md`, the contact sheet and
display inventory, `display_benchmark.json`, the publishability evidence and the analyses done
by role. The reviewer judges suitability for an SCIE original article of the target tier,
design validity, key analyses comparable papers have and this paper lacks, robustness, bias
and confounding, display adequacy against the benchmark, overclaiming risk and the recommended
article type. MUST-FIX = likely rejection or a wrong conclusion.

You then revise - analyses (loop to S05 when needed, with `wf publishability value` first),
displays (S10/S11 scripts, re-render) and the Methods (re-polish the changed paragraphs) - which
is cheap before writing. Close the round (`close --report`, every finding changed, kept with a
reason, or handed to the author), send ONE Chinese summary (problems by severity, what changed,
what was not changed and why) and ask ONE question: another round, or proceed. Record it:
```
.\.venv\Scripts\python.exe tools/review_round.py decide no_further_review --scope science --words "<the user's words, e.g. 继续写作>"
```
'OK' or '可以' alone is not a decision. The 1.8.1 loop, the 1.22 convergence rules and round
caps apply (standard 3, fast 1). The decision is bound to the hashes of the results and
displays: a later change makes it stale -> a delta round (`start --scope science --delta`).
The S18 brief then focuses on writing quality, consistency and readability and does not reopen
closed science items unless results changed.

## Hard rules
- Effects as the protocol's Statistical reporting plan says (estimate + interval, then P);
  `effects_with_intervals` warns on P-value-only sentences.
- Body text is continuous paragraphs (1.9.0). Lists only where a sentence truly cannot carry
  the content (rarely more than one short list per section); every result, count, criterion,
  covariate and sensitivity finding is written as a sentence. `prose_not_lists` fails above
  `body_list_items_max` items or `body_list_share_max` of the blocks.
- ONE section file this stage.
- Every number traceable to results JSON, told in its own context (1.16.0): the measure, time
  window and dictionary labels of the result it comes from; a small integer next to n=, %, a CI
  or an effect measure is a finding. Sentences combining results go to the reviewer list.
- Every figure/table citation matches `artifact_plan.json` exactly, including supplementary
  numbering.
- No claim about a result you did not compute. If a reviewer would ask "where is the test for
  that", either run it (loop to S05) or do not claim it.
- Do not interpret (no "importantly", no mechanism) and do not restate tables row by row.
