# medpaper on Kiro

A 20-stage medical research paper pipeline with enforced gates. The workflow is not a
prompt: it lives in `pipeline/` and a CLI hands the agent one stage at a time, so it does
not decay as the context window compacts.

## Install

```powershell
Expand-Archive medpaper-kiro.zip
cd medpaper-kiro
python bootstrap.py
python tools/install_adapters.py --global    # so `/` finds the skill from any workspace
```

Open the folder as the workspace in Kiro. `bootstrap.py` creates `.venv`, installs the
pinned dependencies, wires the adapters, then runs `doctor` and the self test. Python 3.11+
is required for the driver (`tomllib`); the driver itself has no third-party dependencies.

`--global` matters if you work in more than one folder. A workspace-level skill is only
discoverable in that workspace, so typing `/` elsewhere will not find it. The global copy
carries the engine's absolute path, so the agent can locate `tools/wf.py` from anywhere.
It also installs the three delegated agents (`medpaper-reviewer`, which may write only its
own `report.md` in a review bundle; `medpaper-deepreader`, read-only; and, from 1.12.0,
`medpaper-clinical-writer`, which writes manuscript prose from a writer bundle and never
reads analysis code). Re-run it if you ever move the engine.

Set these before running searches:

```powershell
$env:NCBI_API_KEY = "..."                  # raises PubMed from 3 to 10 requests/second
$env:NCBI_API_EMAIL = "you@example.org"    # required by Unpaywall for full-text retrieval
```

To persist them, use `[Environment]::SetEnvironmentVariable("NCBI_API_KEY", "...", "User")`
and restart Kiro.

## What Kiro reads

| File | Role |
|---|---|
| `.kiro/steering/medpaper-pipeline.md` | Steering with `inclusion: always` - present in every session |
| `.kiro/skills/medpaper-pipeline/SKILL.md` | Skill, activated on demand when the task matches |
| `.kiro/hooks/medpaper-status.json` | `SessionStart` hook running `wf status --brief`, so a new session opens already knowing the stage |

The steering file also pulls in reference material with `#[[file:...]]` links, so the figure
and table standards load when they become relevant instead of sitting in context all session.

After install, restart Kiro or reload the window so it picks up `.kiro/`. Confirm the
steering file is active in the Kiro panel under Steering.

Both files are short and say the same thing: run `python tools/wf.py status` and obey the
stage card. Neither contains the workflow, so editing a stage never means editing an adapter.

## Use

One engine drives many papers. The engine folder is maintenance-only and read-only for paper
sessions. A paper is the folder you open as the Kiro workspace; initialise it there, in place:

```powershell
python <engine>/tools/wf.py init                  # this folder becomes the paper
python <engine>/tools/wf.py data add G:/data/x    # datasets stay where they are (read-only, never copied)
python <engine>/tools/wf.py new <slug> --central  # only if you want it under the central papers root
```

`wf init` also writes the paper's own `.kiro/` steering and hooks (status, skill guard, frozen
guard, paper isolation guard), which call the engine by absolute path. Put your research idea
file in `00_input/`, then in Kiro chat:

```
Start the medpaper pipeline. My research idea is in #00_input/idea.md
```

Use `#File` to attach the idea document, or drag it in. From then on the loop is always the
same:

```powershell
python tools/wf.py status                     # where am I, what is blocking, full stage card
#   ... do the work the card describes ...
python tools/wf.py check                      # run the stage's gate
python tools/wf.py advance --note "..."       # close the stage
```

`status` prints the invariants, the progress map, the gate state, the last handoff note, the
outputs this stage may create, and the whole stage card. After a context compaction that one
command restores everything. The agent should never infer the current stage from the
conversation.

## Autonomy mode

**Autopilot** suits stages that are mostly mechanical: S04 data acquisition, S05 analysis,
S10 tables, S11 figures, S13 reference library. The gates are the safety net.

**Supervised** suits the stages where judgement matters and you will want to intervene per
hunk: S06 go/no-go, S08 Methods, S09 Results, S14 Introduction, S16 Discussion, S19 polish.

Four stages need your input and will stop to ask regardless: S01 intake, S17 front matter
(authors, affiliations, ethics), S18 journal choice, and both go/no-go decisions.

## Commands

| Command | Purpose |
|---|---|
| `wf init` / `wf data add <path>` / `wf engine-fork` | Paper in place, datasets in place, project-local engine fork |
| `wf tree -v` | Whole pipeline with outputs and gates |
| `wf card S11` | Read any stage card |
| `wf check S09` | Run any gate without advancing |
| `wf decide NAME VALUE --why "..."` | Record a gated decision (rationale >= 40 chars) |
| `wf loop --to S05_analysis --why "..."` | Reopen an earlier stage |
| `wf clean [--apply]` | Report scratch and undeclared files |
| `wf config set intro_words_max 600` | Override a target for this paper |
| `wf doctor` | Environment and wiring check |

Prefix each with `python tools/wf.py`.

`wf status` prints the engine path and the paper path it resolved, with the reason. If it ever
acts on the wrong paper, that header tells you why in one line.

## What the gates stop

- **Fabricated references.** Every search caches its raw API payload; a citekey absent from
  `project/06_refs/verified.json` with `verified: true` fails the gate.
- **Fabricated statistics.** Every number in the manuscript must already exist in
  `project/03_analysis/results/*.json`, written by code that ran.
- **Running ahead.** Later stages' outputs cannot exist yet; one manuscript section per stage.
- **Unverified figures.** Deterministic QC plus a recorded decision that the PNG was opened
  and looked at. Reading the plotting code does not count.
- **Corrupted polishing.** S19 snapshots the manuscript, then requires the multiset of
  numbers, the set of citekeys and the set of figure/table references to be unchanged.

## Notes for Kiro specifically

- **Looking at figures works natively.** Kiro reads PNG as image input, so S11's visual check
  needs no workaround. For a suspect panel of a multi-panel plate, crop it first:
  `python tools/figures/qc.py --crop "Figure 1" --cols 2 --cell B`, then read the crop.
- **Trust store.** The agent runs `python tools/wf.py ...` constantly. Trusting
  `python tools/wf.py` and `python tools/figures/qc.py` removes most prompts without granting
  anything broad.
- **Specs are the wrong tool here.** The pipeline is already a spec-driven workflow with its
  own state machine. Use a Vibe session and let `wf status` drive; do not wrap it in a Kiro
  spec, which would add a second, competing task list.
- **The SessionStart hook is already installed.** `.kiro/hooks/medpaper-status.json` runs
  `wf status --brief` when a session opens, so the stage, the gate state and the last handoff
  note are in context before you type anything. It takes effect from the next session.
- **Network access is required** for PubMed, Crossref, Unpaywall and the S18 guideline fetch.
  Without it, stages S02, S05, S07, S13, S15 and S18 fail at the gate rather than inventing
  data, which is the intended behaviour.

## Verify the install

```powershell
python tools/wf.py doctor                        # expect: 20/20 stage cards, 36/36 gate checks
.venv\Scripts\python.exe tools\selftest.py       # expect: 78/78
.venv\Scripts\python.exe tools\selftest.py --online   # 81/81, exercises the live APIs
```
