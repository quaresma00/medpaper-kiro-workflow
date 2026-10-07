"""Run one paper-owned script with the paper exported, and trip on any engine change.

Stdlib only. Shared by `wf run-script` and `tools/reproduce.py`.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import paths

ENGINE_IGNORED_CACHES = frozenset({".pytest_cache", "__pycache__", ".ruff_cache", ".mypy_cache",
                                   ".vscode", ".idea"})
_SNAPSHOT_SKIP_DIRS = frozenset({".git", ".venv"}) | ENGINE_IGNORED_CACHES


@dataclass
class RunOutcome:
    returncode: int
    seconds: float
    engine_changes: list[str] = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False


class RunnerError(Exception):
    """Missing interpreter or a bad script; the message is for the user."""


def science_python() -> Path | None:
    root = paths.repo_root()
    for cand in (root / ".venv/Scripts/python.exe", root / ".venv/bin/python",
                 paths._physical_engine() / ".venv/Scripts/python.exe",
                 paths._physical_engine() / ".venv/bin/python"):
        if cand.exists():
            return cand
    return None


def interpreter_for(script: Path) -> list[str]:
    suffix = script.suffix.casefold()
    if suffix == ".py":
        exe = science_python()
        if exe is None:
            raise RunnerError("science venv is missing; run `uv venv .venv` in the engine first")
        return [str(exe)]
    if suffix == ".r":
        exe = shutil.which("Rscript")
        if exe is None:
            raise RunnerError("Rscript is missing; run `wf doctor` and install/configure R first")
        return [exe]
    raise RunnerError(f"paper script not found (or not .py/.R): {script}")


def tree_snapshot(root: Path, exclude_rel: tuple[str, ...] = (),
                  skip_dirs: frozenset[str] = frozenset()) -> dict[str, tuple[int, int]]:
    """(size, mtime_ns) of every file under root, keyed by root-relative POSIX path."""
    out: dict[str, tuple[int, int]] = {}
    root = Path(root)
    if not root.exists():
        return out
    excl = tuple(e.strip("/") for e in exclude_rel)
    for dirpath, dirnames, filenames in os.walk(root):
        d = Path(dirpath)
        rel_dir = d.relative_to(root).as_posix()
        rel_dir = "" if rel_dir == "." else rel_dir
        keep = []
        for name in dirnames:
            rel = f"{rel_dir}/{name}" if rel_dir else name
            if name in skip_dirs or rel in excl:
                continue
            keep.append(name)
        dirnames[:] = keep
        for name in filenames:
            rel = f"{rel_dir}/{name}" if rel_dir else name
            if rel in excl or name.endswith((".pyc", ".pyo")):
                continue
            try:
                st = (d / name).stat()
            except OSError:
                continue
            out[rel] = (st.st_size, st.st_mtime_ns)
    return out


def engine_snapshot() -> dict[str, tuple[int, int]]:
    out: dict[str, tuple[int, int]] = {}
    for root in paths.engine_roots():
        for rel, sig in tree_snapshot(root, skip_dirs=_SNAPSHOT_SKIP_DIRS).items():
            out[f"{root.as_posix()}/{rel}"] = sig
    return out


def diff_snapshots(before: dict, after: dict) -> list[str]:
    return sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p))


def run_paper_script(paper: Path, script: Path, args=(), *, timeout: float | None = None,
                     capture: bool = False) -> RunOutcome:
    paper = Path(paper).resolve()
    script = Path(script)
    script = (script if script.is_absolute() else paper / script).resolve()
    try:
        script.relative_to(paper)
    except ValueError as exc:
        raise RunnerError(f"refusing to run a script outside the paper: {script}") from exc
    if not script.is_file() or script.suffix.casefold() not in {".py", ".r"}:
        raise RunnerError(f"paper script not found (or not .py/.R): {script}")
    cmd = [*interpreter_for(script), str(script), *args]
    env = os.environ.copy()
    env["MEDPAPER_PROJECT"] = str(paper)
    env["MEDPAPER_ROOT"] = str(paths.repo_root())
    # Lets save_medpaper() bind a figure to the exact script that drew it.
    env["MEDPAPER_SCRIPT"] = script.relative_to(paper).as_posix()
    tools = str(paths.tools_dir())
    env["PYTHONPATH"] = tools + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["PYTHONIOENCODING"] = "utf-8"
    before = engine_snapshot()
    start = time.monotonic()
    timed_out = False
    stdout = stderr = ""
    try:
        if capture:
            done = subprocess.run(cmd, cwd=paper, env=env, capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=timeout)
            stdout, stderr = done.stdout or "", done.stderr or ""
        else:
            done = subprocess.run(cmd, cwd=paper, env=env, timeout=timeout)
        code = int(done.returncode)
    except subprocess.TimeoutExpired as exc:
        timed_out, code = True, 124
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
    seconds = time.monotonic() - start
    changes = diff_snapshots(before, engine_snapshot())
    return RunOutcome(code, seconds, changes, stdout, stderr, timed_out)
