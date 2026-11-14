---
name: medpaper-pipeline
description: Drives a gated, resumable medical/clinical research paper pipeline from a research idea through feasibility, data acquisition, exploratory analysis, figure and table production, IMRAD writing, independent review, journal selection, de-AI polish and a Word submission package. Use whenever the task involves a medical research idea, a clinical manuscript, a research protocol, literature retrieval via PubMed, publication-grade figures or three-line tables, journal selection, a submission package, or a revision round on any of these. Do not follow the workflow from memory - run `python tools/wf.py status` and obey the stage card it prints.
compatibility: Requires Python 3.11+ for the driver. Tables and Word output additionally need numpy, pandas, openpyxl and python-docx (matplotlib for the Python figure path). R 4.3+ with the packages in reference/language_policy.toml (figures default to R). Network access is required for PubMed, Crossref and Unpaywall. Set NCBI_API_KEY to raise the E-utilities rate limit.
metadata:
  version: "2.9.0"
  stages: "25"
  entrypoint: "python tools/wf.py status"
---

# medpaper pipeline

A 25-stage research pipeline. The workflow is **not** in this file: it lives in
`pipeline/pipeline.toml` and `pipeline/stages/*.md`, and the CLI hands you one stage at a
time. Long-form background: `reference/skill_details.md` (read only if needed).

## The loop

```
python tools/wf.py status                       # stage, gate, last handoff, the stage card
<do the work on the card>
python tools/wf.py check                        # failures + one summary line (full list: .wf/logs/)
python tools/wf.py advance --note "..."         # refuses on a red gate
```

Run `status` once per session or stage change; never infer the stage from memory or files.
The paper is the folder the user opened as the Kiro workspace: `wf init` there, in place
(an existing paper is resumed). Never create a subfolder for the paper, never ask the user
to reopen another folder, never use the data folder; `wf init` names the rare refusal. `wf new --root/--central` only on the user's explicit request.
Commands act only on that paper; never read or list another paper. Datasets are declared in
place, read-only, never copied: `wf data add <absolute path>`.
1.23.0: report each publishability verdict at once (`wf publishability`); CONDITIONAL or
NO-GO = one question. 1.25.0: S07 benchmark = the 5-10 newest comparable papers
(`benchmark.py search`). 1.25.1: primary outcome first; null results, CIs, limitations kept.
Reports the user wants outside the paper: `wf config --user report_dirs add <dir>` (.md/.txt).

## Execution economy (1.12.0)

- **Context for a new session or delegated step: `wf handoff`** (<= 60 lines: stage, card,
  gates, open rounds, questions, next command). Pass its output instead of a hand-written brief.
- Long commands: `--wait` (one blocking call, heartbeat <= 30 s, failures + one summary line)
  for `wf check`, `rework.py check`, `reproduce.py run`, `build_docx.py`; `wf check --summary`
  for one line. Logs live in `.wf/logs/` (or `temp/logs/`), never in external temp folders.
- Reproduce once at S06; later stages accept the proof by hash. Batch a review round's
  analysis edits into one plan and reproduce once per round (affected scripts only; `REUSED`
  when nothing changed; notes, docs and manuscript edits never invalidate it). Never run it
  "to be safe" - `wf check` names the cheapest next command. Never copy the user's data.
- Cards are short; read `reference/stage_details/` only when needed; `wf archetype <name>`
  prints one archetype.
- Prefer a cheaper model for mechanical steps.
- Browser (1.21.0; only if a browser tool `playwright` is in your tool list): APIs first
  (PubMed/E-utilities, open-access APIs; DOAJ/OpenAlex/NLM via `wf journal lookup`). Full
  text, lawful routes only (1.23.0): `fulltext.py fetch` cascade -> publisher page in the
  visible browser with the user's own login (only the listed papers) -> for what is still
  missing, ask the user for the PDF once (`fulltext.py remaining`: drop folder, e-mail drafts). Never
  `browser_snapshot` without `filename` on long pages; prefer `browser_evaluate` on `main`;
  never read capture files into the chat - ingest them (`wf guidelines ingest`, `wf portal
  ingest`, `wf data capture`), then read only the needed line ranges of
  `guidelines_source.txt`. One browser session per task, then `browser_close`. Browsing is
  the paper's main agent's job (subagents get the ingested files); a verification page or
  login is completed by the user in the browser window.
- One look at the end: in `deferred` mode no PNG is loaded at S10/S11 and no decision is
  recorded; S23 discharges every look on one contact sheet (`qc.py --contact-sheet`).

Never a saving: skipping the visual check, truncating a data pull, or reviewing your own
manuscript instead of the subagent. If context runs out, say so.

## Delegate

| Stage | Agent | Notes |
|---|---|---|
| S08, S09, S14, S16, S19 rewrites | `medpaper-clinical-writer` | Pass the MANIFEST of `tools/manuscript/writer_bundle.py build --stage <S>`; it sees clinical text only - never code, JSON keys or logs. Then `wf check`. |
| after S11 (with the D2 look) | `medpaper-clinical-writer` | 1.20.0: table/figure wording - `wf displays text` writes `.wf/writer_bundle/displays/MANIFEST.md` (only strings that read like an analysis report); then `wf displays apply` and re-render. |
| each prose section, right after its draft (1.23.0) | `medpaper-medical-editor` | `writer_bundle.py receipt` -> `edit --section S` (pass its MANIFEST) -> `polished --section S`; numbers and citations unchanged (`section_polished`). 1.24.0 voice: `reference/writing_voice.md`. 1.25.0: after S17 only `polish.py crosscheck` + `edit --section manuscript` (changed paragraphs). |
| S09, before the Results (1.23.0) | `medpaper-reviewer` (science) | `review_round.py start --scope science`; revise analyses/displays/Methods, ONE summary, ONE question (another round or proceed). |
| S15 | `medpaper-deepreader` | One invocation per full text; save its notes yourself. |
| S18, S19/S24 rounds, S25 | `medpaper-reviewer` | Give it only the bundle path `review_round.py start` prints and the neutral brief. It writes only `.wf/review_bundle/<round>/report.md`; `close` reads that file - never paraphrase findings. Confirmation is the exact sentence `我确认这一版`. |

## Review loops and Kiro workflows (1.22.0)

- `review_round.py start` / `package_review.py audit-start` print the exact subagent call;
  run review rounds in the paper's main chat (a workflow step cannot start a subagent);
  `close` reads the report.md the reviewer wrote. Nothing is relayed by hand.
- Orchestrating with Kiro workflows: a user scope change -> `update_workflow`
  replace_remaining (or end the skipped steps), never leave them pending; on abort write one
  line: what was delivered, what was skipped. Before relaying a paused step's question,
  check `wf decisions show` and the conversation; answer it when derivable and state the basis.
- Before asking the user anything: `wf decisions show`; record answers with `wf decisions set`.

## Python and R

Python for data, tables, Word and gates; R for figures and R-strong statistics
(`reference/language_policy.toml`); paper code only via `wf run-script <relative.py|.R>`.

## One paper, never the engine

A gate that does not fit: `wf config set` -> `wf override init|show|validate` -> `wf
engine-fork create` -> never the global engine (commands refuse a modified engine). A paper
keeps its pinned gate set for completed stages until `wf migrate --yes`.

## The absolute rules

1. A `verified: true` boolean is not evidence; never fabricate or hand-set reference fields.
2. Acquire the complete protocol-defined data universe; no silent caps.
3. No number without provenance in `03_analysis/results/*.json`, written by executed code.
4. Draft sections only at their stages; S17 assembles.
5. Figures are verified by looking at the rendered PNG; `DEFER`/deferred means "not looked
   at yet"; `visual_debts_cleared` (S23) is non-overridable.
6. No explanatory prose in panels; legends never restate Results; clinical labels only.
7. Polishing changes wording only (snapshot + diff).
8. The science freezes at S19; journals adapt the copy in `08_submission/manuscript/`.
9. Every revision goes through `tools/rework.py` (`preview` first; an S19 return only on 我确认回退).
10. The package is final only after the user's 我确认这一版 at S24; S25 audits the freeze.
11. A red gate means fix it, not `--force`.

## Other skills

Never use a skill in place of a stage (`write-paper`, `orchestrate`, `make-figures` ...);
complementary ones (`check-reporting`, `deidentify` ...) may help inside a stage.
Classification: `reference/skill_policy.toml` (`python tools/hooks/skill_guard.py --audit`).

## Handoff

Before advancing, record what a stranger needs: produced, decided, still open.
