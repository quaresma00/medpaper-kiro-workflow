#!/usr/bin/env python3
"""Wire the pipeline into Kiro, at workspace level and optionally user level.

    python tools/install_adapters.py            # this workspace
    python tools/install_adapters.py --global   # also user level, so `/` finds it anywhere
    python tools/install_adapters.py --check    # report drift, change nothing

The skill source of truth is `.kiro/skills/medpaper-pipeline/SKILL.md`. The steering file and
the two hooks are generated from the templates below, so editing a stage card never requires
touching an adapter.

Why a user-level copy matters: a workspace-level skill is only discoverable inside that
workspace, so typing `/` in any other folder will not find it. The user-level copy carries the
engine's absolute path, which is the only way an agent activating the skill elsewhere can
locate `tools/wf.py`. Re-run with `--global` if the engine ever moves.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL_SRC = ROOT / ".kiro" / "skills" / "medpaper-pipeline"
GLOBAL_SKILL_ROOT = Path.home() / ".kiro" / "skills"

STEERING = """\
---
inclusion: always
---

# medpaper pipeline

> **If you are a delegated subagent, stop here.** Steering is shared with subagents and is not
> isolated, so this file reaches you even when it should not. Everything below addresses the
> agent that *builds* the manuscript. If you were invoked to review, audit, read a full text or
> gather context, none of it applies to you: do not run `wf` commands, do not advance a stage,
> do not write pipeline artifacts. Do the job you were given and report back. Your own agent
> prompt governs; this file does not.

This workspace is driven by a gated pipeline, not by prompt instructions.

**Before doing anything in this repo, run `python tools/wf.py status`.** It returns the
current stage, the invariants, the gate state, the last handoff and the full stage card.
Do not infer the stage from the conversation or from which files exist.

Loop: `wf status` -> do the work -> `wf check` -> `wf advance --note "..."`.

25 stages. One engine, many papers: `wf new <slug>` starts one under `papers/`, `wf papers`
lists them, `wf use <slug>` switches. `wf status` prints which paper it resolved and why.

Never edit `pipeline/`, `tools/`, `reference/` or `.kiro/` for one study - they are the shared
mother workflow. Values go in this paper's `.wf/config.toml` via `wf config set`; a genuine
shape difference goes in `.wf/overrides.toml` via `wf override init`. `wf override validate`
refuses protected integrity gates, review/audit-stage skips, path escapes and retrospective
changes to an override that already governed a finished stage. Status reprints every effective
override on every call. Run paper Python/R code only through `wf run-script <relative.py|.R>`;
it uses the paper as cwd and trips if shared-engine files change.

Hard rules, several mechanically enforced by the gates:

- **A `verified: true` boolean is not evidence.** Reference gates re-parse the cached PubMed
  EFetch XML and recompute every bibliographic comparison against `library.json`; the cache
  path, its SHA-256 and the library hash must all match. Never write a script that sets
  `verified` or invents a DOI to turn `citekeys_resolve` green - that is fabrication. If a
  citation cannot be verified, delete it or replace it with a real record from `tools/pubmed/`.
- **Acquire the complete data universe.** No silent `LIMIT`/`TOP`/`head()`/`sample()`/first-N
  slice when the source can return everything. Any reduction is protocol-defined and recorded
  in the data manifest.
- Every manuscript number must already exist in `03_analysis/results/*.json`, written by
  executed code.
- Draft scientific sections only at their active stages; S17 assembles the canonical full text.
- Only create the outputs the stage declares; scratch lives in `temp/`.
- Figures: `python tools/figures/qc.py --all` every round - that half is code and never waits.
  *When* you look is set by `visual_review_mode`. The default `deferred` records `DEFER` at
  S10/S11 and discharges every look in one `qc.py --contact-sheet` pass at S23, once S20 has
  fixed the journal's column width and palette. `DEFER` means "not looked at yet" and must
  never be reported as verified; `visual_debts_cleared` at S23 is non-overridable. Reading the
  plotting code is not verification. Figure legends must not restate the Results.
- Figure standards, archetypes and palettes: activate the `medical-sci-figure-skill` global
  skill and read its atlas entry for the chart type in hand. Reading and styling only -
  `tools/figures/style.py` renders, `tools/figures/qc.py` judges, and its own
  `audit_medical_figure()` must not be run on a pipeline figure. Width, font-floor, legend and
  QA-engine conflicts are settled in `reference/skill_policy.toml` `[figure_authority]`.
- No explanatory prose inside figure panels.
- Language polishing changes wording only, never a number, a citation or a figure/table
  reference. Snapshot before the pass: `python tools/text/polish.py snapshot`.
- Route every user revision through `tools/rework.py` to the earliest owning stage, then
  rebuild downstream. Never patch a rendered artifact directly.
- The science freezes when the user releases S19 (`scientific_freeze.py capture`). From S20 on
  `07_manuscript/` is read-only: journal requirements are applied to the copy S20 opens at
  `08_submission/manuscript/`. To switch journals, first loop to S20 and run
  `scientific_freeze.py reset-journal --confirm-journal "<old>"`; it clears the whole old
  submission tree before S20 opens a fresh copy. `scientific_freeze_intact` is non-overridable.
  Gates resolve to the variant on their own - do not pass different paths. Prose may be tightened for a word cap; a number or citation
  that disappears is dropped content and needs `journal_trim_authorised YES`.
- The submission package is not final until S24 records explicit user confirmation and freezes
  the files; S25 then audits the frozen set.
- A red gate means fix it, not `--force`.

## Skill arbitration in this workspace

A general medical-research skill suite may also be installed at the user level. Several of
its skills do the same job as a pipeline stage, but write their outputs elsewhere and carry
no gate, so using one instead of the stage leaves the gate red with no way to satisfy it.

**Never use these in place of a stage. In this workspace the pipeline wins:**

| Skill | Superseded by | Why |
|---|---|---|
| `write-paper` | S08, S09, S14, S16, S17 | A competing 8-phase manuscript workflow with no gates |
| `orchestrate` | `wf status` | Routes the task away from the pipeline; the stage card is the router |
| `manage-project`, `intake-project` | `wf new`, `wf status`, S01 | Competing project scaffold and state |
| `search-lit`, `medsci-lit-api` | `tools/pubmed/client.py` | Payload never reaches `06_refs/cache/`, so the retrieval and verification receipts cannot pass |
| `make-figures` | S11 + `tools/figures/` | No `qc_report.json`, no archetype element checks, wrong output paths |
| `manage-refs`, `verify-refs` | S13 + `tools/pubmed/verify.py` | Does not produce the tamper-evident verification receipt the gate re-checks |
| `polish-language`, `humanize` | S22 + `tools/text/polish.py` | No pre-polish snapshot, so fact preservation cannot be proven |
| `find-journal`, `sync-submission` | S20, S23 | Bypasses the fetched-and-snapshotted guideline requirement |
| `write-protocol` | S03, S06 | Competing protocol format; the gate checks specific headings |
| `analyze-stats` | S05 | No results-JSON provenance contract, so downstream numbers fail their gate |

**These are complementary. Use them inside the relevant stage:**

- `check-reporting` - run it at S12, S18 or S22 against the declared reporting guideline. The
  pipeline records which guideline applies but does not check it item by item; this closes
  that gap.
- `self-review`, `peer-review`, `revise` - post-submission work, which the pipeline does not
  cover at all.
- `deidentify`, `generate-codebook`, `clean-data`, `version-dataset` - useful at S04, as long
  as the codebook and `dataset_summary.json` still land where S04 declares.
- `calc-sample-size`, `design-study`, `define-variables` - useful at S03, feeding into
  `protocol_v1.md`.
- Imaging and ML skills (`model-scaffold`, `radiomics-ml`, `explainability`,
  `preprocess-imaging`, `model-validation`, and similar) - a different domain, no conflict.

Rule of thumb: a skill that produces an **artifact a stage declares** must not be used unless
its output lands at the declared path and satisfies that stage's gate. A skill that produces
**analysis or a review** is fine anywhere.

The full classification is data, not prose: `reference/skill_policy.toml`. A `PreToolUse`
hook (`.kiro/hooks/medpaper-skill-guard.json`) enforces it, so this is not merely advice -
a blocked skill cannot be activated. Inspect or change it with:

```
python tools/hooks/skill_guard.py --audit            # every installed skill by verdict
python tools/hooks/skill_guard.py --explain write-paper
```

Detail: #[[file:.kiro/skills/medpaper-pipeline/SKILL.md]]

Reference material, loaded when relevant:
#[[file:reference/figure-standards.md]]
#[[file:reference/table-standards.md]]
"""

STATUS_HOOK = """\
{
  "version": "v1",
  "hooks": [
    {
      "name": "medpaper: show pipeline state on session start",
      "trigger": "SessionStart",
      "description": "Prints the current pipeline stage, gate state and last handoff note at the start of every session, so the agent never has to guess where the work stopped.",
      "action": {
        "type": "command",
        "command": "python tools/wf.py status --brief",
        "timeout": 60
      }
    }
  ]
}
"""

SKILL_GUARD_HOOK = """\
{
  "version": "v1",
  "hooks": [
    {
      "name": "medpaper: block skills that replace a pipeline stage",
      "trigger": "PreToolUse",
      "matcher": "disclose_context",
      "description": "Refuses activation of skills that would substitute for a pipeline stage and leave its gate unsatisfiable (write-paper, orchestrate, make-figures, search-lit and others), and asks for confirmation on skills that merely overlap a stage. Decisions come from reference/skill_policy.toml.",
      "action": {
        "type": "command",
        "command": "python tools/hooks/skill_guard.py",
        "timeout": 30
      }
    }
  ]
}
"""

FILES = [
    (".kiro/steering/medpaper-pipeline.md", STEERING),
    (".kiro/hooks/medpaper-status.json", STATUS_HOOK),
    (".kiro/hooks/medpaper-skill-guard.json", SKILL_GUARD_HOOK),
]

ENGINE_BLOCK = """
> **Engine location: `{engine}`**
>
> This skill is installed at the user level, so it is discoverable from every workspace.
> The pipeline engine itself lives at the path above and is not copied per project.
>
> From inside the engine directory, commands are as written below. From anywhere else, use
> the absolute path and let the driver find the paper you are standing in:
>
> ```
> python "{engine}/tools/wf.py" status
> ```
>
> The driver resolves which paper it is acting on in this order: the `MEDPAPER_PROJECT`
> environment variable, an initialised paper at or above the working directory, the paper
> selected with `wf use`, then the engine's own `project/` directory. So you can either keep
> papers under `{engine}/papers/<slug>` and switch with `wf use`, or keep a paper anywhere on
> disk and run the driver from inside it.
"""


def write_file(rel: str, content: str, check: bool) -> tuple[str, str]:
    p = ROOT / rel
    if check:
        if not p.exists():
            return rel, "MISSING"
        return rel, "ok" if p.read_text(encoding="utf-8") == content else "STALE"
    p.parent.mkdir(parents=True, exist_ok=True)
    existed = p.exists()
    p.write_text(content, encoding="utf-8")
    return rel, "updated" if existed else "created"


def global_skill(check: bool) -> tuple[str, str]:
    """Install the skill at the user level, carrying the engine's absolute path."""
    body = (SKILL_SRC / "SKILL.md").read_text(encoding="utf-8")
    parts = body.split("---", 2)
    block = ENGINE_BLOCK.format(engine=ROOT.as_posix())
    body = f"---{parts[1]}---\n{block}{parts[2]}" if len(parts) >= 3 else block + body

    dest = GLOBAL_SKILL_ROOT / "medpaper-pipeline" / "SKILL.md"
    label = str(dest).replace(str(Path.home()), "~")
    if check:
        if not dest.exists():
            return label, "MISSING"
        return label, "ok" if dest.read_text(encoding="utf-8") == body else "STALE"
    dest.parent.mkdir(parents=True, exist_ok=True)
    existed = dest.exists()
    dest.write_text(body, encoding="utf-8")
    return label, "updated" if existed else "created"


def main() -> int:
    ap = argparse.ArgumentParser(description="wire the pipeline into Kiro")
    ap.add_argument("--check", action="store_true", help="report drift without writing")
    ap.add_argument("--global", dest="do_global", action="store_true",
                    help="also install the skill at the user level, so `/` finds it "
                         "from every workspace")
    args = ap.parse_args()

    if not (SKILL_SRC / "SKILL.md").exists():
        print(f"error: skill source missing at {SKILL_SRC / 'SKILL.md'}", file=sys.stderr)
        return 1

    rows = [(".kiro/skills/medpaper-pipeline/SKILL.md", "source of truth")]
    for rel, content in FILES:
        rows.append(write_file(rel, content, args.check))
    if args.do_global:
        rows.append(global_skill(args.check))

    width = max(len(r[0]) for r in rows)
    bad = sum(1 for _, s in rows if s in ("MISSING", "STALE"))
    for target, status in rows:
        print(f"{target:<{width}}  {status}")

    if args.check:
        print("\n" + ("adapters are in sync" if bad == 0
                      else f"{bad} adapter(s) out of sync - run without --check"))
        return 0 if bad == 0 else 2

    print("\nThe workflow itself lives in pipeline/; these files only point at it,")
    print("so editing a stage card never requires touching an adapter.")
    if not args.do_global:
        print("\nTo make `/` find the skill from other workspaces too:")
        print("    python tools/install_adapters.py --global")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
