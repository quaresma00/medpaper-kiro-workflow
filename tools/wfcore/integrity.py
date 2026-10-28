"""1.13.0: the shared engine is read-only for paper sessions. Stdlib only.

Paper sessions used to edit the global engine to get past a false positive (a `str_replace` in
tools/wfcore/checks/numbers.py, another in bibrules.py); every other paper then ran on the edited
code. Invariant 8 was text only. Now every paper-acting command resolves its paper through
paths.project_dir()/paper_from_cli(), which calls require_clean(): when the engine checkout has
local modifications the command refuses and names the legal paths (paper overrides first, then a
project-local engine fork, `wf engine-fork`).

Exempt: MEDPAPER_ENGINE_DEV=1 (selftest, deliberate engine development), a linked git worktree
(maintenance happens there), and an engine fork (it exists to be edited; its diff is recorded in
the paper). A checkout without git is compared with ENGINE_MANIFEST.json when one exists
(`install_adapters.py --manifest`), otherwise it is "unverifiable" and allowed.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

DEV_ENV = "MEDPAPER_ENGINE_DEV"
FORK_MARKER = "ENGINE_FORK.json"
MANIFEST_NAME = "ENGINE_MANIFEST.json"
MANIFEST_TREES = ("pipeline", "tools", "reference", ".kiro")
_CACHE: dict[str, tuple[str, list[str]]] = {}


class EngineModified(SystemExit):
    """The shared engine has local edits; paper commands refuse to run on it."""


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def manifest_files(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for tree in MANIFEST_TREES:
        base = root / tree
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts and p.suffix not in (".pyc", ".pyo"):
                out[p.relative_to(root).as_posix()] = _sha(p)
    return out


def write_manifest(root: Path) -> Path:
    target = Path(root) / MANIFEST_NAME
    target.write_text(json.dumps({"schema": 1, "files": manifest_files(Path(root))}, indent=1)
                      + "\n", encoding="utf-8")
    return target


def _git_changes(root: Path) -> list[str] | None:
    try:
        done = subprocess.run(["git", "-C", str(root), "status", "--porcelain",
                               "--untracked-files=all"], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    return [ln[3:].strip().strip('"') for ln in done.stdout.splitlines() if ln.strip()]


def engine_state(root: Path | str | None = None, *, use_cache: bool = True) -> tuple[str, list[str]]:
    """-> (kind, changed paths). kind: dev | fork | worktree | clean | modified | unverifiable."""
    from . import paths
    root = Path(root or paths._physical_engine()).resolve()
    if os.environ.get(DEV_ENV) == "1":
        return "dev", []
    if (root / FORK_MARKER).is_file():
        return "fork", []
    key = str(root)
    if use_cache and key in _CACHE:
        return _CACHE[key]
    git = root / ".git"
    result: tuple[str, list[str]] | None = None
    if git.is_file():
        result = ("worktree", [])
    elif git.is_dir():
        changed = _git_changes(root)
        if changed is not None:
            result = ("modified" if changed else "clean", changed)
    if result is None:
        man = root / MANIFEST_NAME
        if man.is_file():
            try:
                rec = json.loads(man.read_text(encoding="utf-8")).get("files", {})
            except (OSError, ValueError, AttributeError):
                rec = {}
            cur = manifest_files(root)
            diff = sorted(k for k in set(rec) | set(cur) if rec.get(k) != cur.get(k))
            result = ("modified" if diff else "clean", diff)
        else:
            result = ("unverifiable", [])
    _CACHE[key] = result
    return result


def refusal(root: Path, changed: list[str]) -> str:
    shown = "\n".join(f"    {c}" for c in changed[:12])
    more = f"\n    ... and {len(changed) - 12} more" if len(changed) > 12 else ""
    eng = Path(root).as_posix()
    return (
        f"REFUSED: the shared medpaper engine at {eng} has local modifications:\n{shown}{more}\n"
        "Paper sessions must never edit the global engine - it drives every paper. Nothing was "
        "run.\nLegal paths, in this order:\n"
        "  1. paper overrides: `wf config set KEY VALUE` (.wf/config.toml), `wf override init` "
        "(.wf/overrides.toml), the journal's own names and rules in target_journal.json;\n"
        f'  2. a project-local engine fork for this paper only: python "{eng}/tools/wf.py" '
        "engine-fork (it copies the committed engine, not these edits; its diff is kept in the "
        "paper for the maintainer).\n"
        "Tell the user; the maintainer restores the engine (`git -C <engine> status`, `git "
        "checkout -- <file>`) or moves the change into a maintenance worktree.")


def require_clean(root: Path | str | None = None) -> None:
    from . import paths
    root = Path(root or paths._physical_engine()).resolve()
    kind, changed = engine_state(root)
    if kind == "modified":
        raise EngineModified(refusal(root, changed))
