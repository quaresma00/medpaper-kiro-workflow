#!/usr/bin/env python3
"""Wire the pipeline into Kiro, at engine level, paper level and optionally user level.

    python tools/install_adapters.py                  # engine .kiro files (maintenance workspace)
    python tools/install_adapters.py --global         # + user-level skill and the three agents
    python tools/install_adapters.py --paper <DIR>    # (re)render a paper's .kiro (e.g. engine moved)
    python tools/install_adapters.py --check [--global] [--paper DIR]   # drift only, exit 2 on drift

The skill source of truth is `.kiro/skills/medpaper-pipeline/SKILL.md`. Steering and hooks are
generated from `tools/wfcore/adapters.py`, so editing a stage card never requires touching an
adapter. Every paper is its own Kiro workspace whose adapters call this engine by absolute path;
`wf new` writes them. The user-level copies carry the engine's absolute path, which is the only
way an agent in a paper workspace can locate `tools/wf.py`. Re-run with `--global` if the engine
ever moves.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from wfcore import adapters, paths  # noqa: E402

SKILL_SRC = ROOT / ".kiro" / "skills" / "medpaper-pipeline"
GLOBAL_SKILL_ROOT = Path.home() / ".kiro" / "skills"

ENGINE_BLOCK = """
> **Engine location: `{engine}`**
>
> This skill is installed at the user level, so it is discoverable from every workspace.
> The engine lives at the path above, is shared by every paper and is maintenance-only: no
> paper lives in it or writes into it.
>
> Papers live under the papers root (`MEDPAPER_PAPERS_ROOT`, else `papers_root` in
> `~/.medpaper/config.toml`, else `<engine parent>/medpaper_papers`). Start one with
> `python "{engine}/tools/wf.py" new <slug>` and open the folder it prints as its own Kiro
> workspace; from there:
>
> ```
> python "{engine}/tools/wf.py" status
> ```
>
> The driver resolves the paper in this order: `MEDPAPER_PROJECT`, an initialised paper at or
> above the working directory, then the paper selected with `wf use` (`~/.medpaper/active`).
> From the engine folder itself, paper-driving commands are refused.
"""


def global_skill(check: bool) -> tuple[str, str]:
    """Install the skill at the user level, carrying the engine's absolute path."""
    body = (SKILL_SRC / "SKILL.md").read_text(encoding="utf-8")
    parts = body.split("---", 2)
    block = ENGINE_BLOCK.format(engine=ROOT.as_posix())
    body = f"---{parts[1]}---\n{block}{parts[2]}" if len(parts) >= 3 else block + body
    dest = GLOBAL_SKILL_ROOT / "medpaper-pipeline" / "SKILL.md"
    return _copy(dest, body, check)


def _copy(dest: Path, body: str, check: bool) -> tuple[str, str]:
    label = str(dest).replace(str(Path.home()), "~")
    if check:
        if not dest.exists():
            return label, "MISSING"
        return label, "ok" if dest.read_text(encoding="utf-8") == body else "STALE"
    dest.parent.mkdir(parents=True, exist_ok=True)
    existed = dest.exists()
    if existed and dest.read_text(encoding="utf-8") == body:
        return label, "ok"
    dest.write_text(body, encoding="utf-8", newline="\n")
    return label, "updated" if existed else "created"


def global_agents(check: bool) -> list[tuple[str, str]]:
    """Byte copies of the two read-only agents, so S15/S18/S25 can delegate from a paper."""
    rows = []
    for name in adapters.GLOBAL_AGENTS:
        src = ROOT / ".kiro" / "agents" / name
        rows.append(_copy(adapters.global_agents_dir() / name,
                          src.read_text(encoding="utf-8"), check))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description="wire the pipeline into Kiro")
    ap.add_argument("--check", action="store_true", help="report drift without writing")
    ap.add_argument("--global", dest="do_global", action="store_true",
                    help="also install the skill and the read-only agents at the user level")
    ap.add_argument("--paper", help="(re)render the .kiro adapters of an initialised paper")
    args = ap.parse_args()

    if not (SKILL_SRC / "SKILL.md").exists():
        print(f"error: skill source missing at {SKILL_SRC / 'SKILL.md'}", file=sys.stderr)
        return 1

    rows: list[tuple[str, str]] = []
    if args.paper:
        try:
            paper = paths.paper_from_cli(args.paper)
        except SystemExit as exc:
            print(f"install_adapters: {exc}", file=sys.stderr)
            return 2
        rows += [(f"{paper.as_posix()}/{rel}", status) for rel, status in
                 adapters.write_adapters(paper, adapters.paper_adapters(ROOT), check=args.check)]
    else:
        rows.append((".kiro/skills/medpaper-pipeline/SKILL.md", "source of truth"))
        rows += adapters.write_adapters(ROOT, adapters.engine_adapters(), check=args.check)
    if args.do_global:
        rows.append(global_skill(args.check))
        rows += global_agents(args.check)

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
    if not args.do_global and not args.paper:
        print("\nTo make `/` find the skill and the review agents from paper workspaces too:")
        print("    python tools/install_adapters.py --global")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
