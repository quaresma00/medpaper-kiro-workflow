#!/usr/bin/env python3
"""Create and verify the local medpaper environment for Kiro.

    python bootstrap.py

Creates .venv, installs the pinned dependencies, wires the Kiro steering file, the two hooks
and the skill (workspace and user level), then runs doctor and the regression suite.
Safe to re-run.

It deliberately does not create a paper: `wf new <slug>` does that, so the engine directory
never accumulates an unnamed project/ alongside papers/.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def run(cmd: list[str], label: str, optional: bool = False) -> bool:
    print(f"\n>>> {label}\n    {' '.join(map(str, cmd))}")
    try:
        proc = subprocess.run(cmd, cwd=ROOT)
    except FileNotFoundError:
        print(f"    !! command not found: {cmd[0]}")
        return False
    if proc.returncode:
        print(f"    !! exited {proc.returncode}" + ("  (optional, continuing)" if optional else ""))
        return False
    return True


def create_venv(uv: str | None) -> bool:
    if venv_python().exists():
        print(f"\n>>> virtual environment already exists: {VENV.name}")
        return True
    if uv:
        return run([uv, "venv", "--python", "3.13", str(VENV)], "create Python 3.13 environment")
    return run([sys.executable, "-m", "venv", str(VENV)], "create virtual environment")


def install_dependencies(uv: str | None) -> bool:
    req = ROOT / "requirements.txt"
    if not req.exists():
        print("requirements.txt is missing")
        return False
    if uv:
        cmd = [uv, "pip", "install", "--python", str(venv_python()), "-r", str(req)]
    else:
        cmd = [str(venv_python()), "-m", "pip", "install", "-r", str(req)]
    return run(cmd, "install pinned science dependencies")


def main() -> int:
    ap = argparse.ArgumentParser(description="set up and verify medpaper for Kiro")
    ap.add_argument("--skip-selftest", action="store_true")
    ap.add_argument("--skip-venv", action="store_true", help="use the current interpreter")
    args = ap.parse_args()

    if sys.version_info < (3, 11):
        print(f"Python 3.11+ required (tomllib); found {sys.version.split()[0]}")
        return 1

    uv = shutil.which("uv")
    print("=" * 72)
    print("medpaper bootstrap (Kiro)")
    print(f"engine: {ROOT}")
    print(f"runner: {sys.executable} ({sys.version.split()[0]})")
    print(f"uv:     {uv or 'not found; using stdlib venv/pip'}")
    print("=" * 72)

    ok_env = True
    if not args.skip_venv:
        ok_env = create_venv(uv) and install_dependencies(uv)
        if not ok_env:
            print("\n!! dependency install failed. The workflow driver still works "
                  "(it is stdlib only); figures, tables and Word output will not.")

    # --global also installs the skill under ~/.kiro/skills so `/` finds it from any workspace.
    run([sys.executable, "tools/install_adapters.py", "--global"],
        "wire Kiro steering, hooks and the skill (workspace + user level)")
    run([sys.executable, "tools/wf.py", "doctor"], "validate workflow and environment",
        optional=True)

    if ok_env and not args.skip_selftest and venv_python().exists():
        run([str(venv_python()), "tools/selftest.py"], "run offline regression suite",
            optional=True)

    print("\n" + "=" * 72)
    print("Start a paper:")
    print("    python tools/wf.py new <slug>        e.g. new sarcopenia-mortality")
    print("\nThat creates papers/<slug>/ and selects it. Put your research idea file in")
    print("papers/<slug>/00_input/, then run:")
    print("    python tools/wf.py status")
    print("\nOne engine, many papers: `wf papers` lists them, `wf use <slug>` switches.")
    print("\nRestart Kiro (or reload the window) so it picks up .kiro/ - the steering file")
    print("and the two hooks take effect from the next session.")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
