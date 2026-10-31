"""1.13.0: a project-local engine fork for one paper (`wf engine-fork`). Stdlib only.

When a paper genuinely needs an engine change (a false positive no override can express), the
global engine stays untouched: `wf engine-fork` copies the COMMITTED engine (tools/, pipeline/,
reference/ - no .git, no .venv; the global venv is reused) into <paper>/.wf/engine_fork/,
records the base version, commit and file hashes in ENGINE_FORK.json, keeps the pristine base
as .wf/engine_fork_base.zip and re-points the paper's Kiro adapters at the fork. The fork is
engine only inside its own folder (paths.in_engine), drives only its own paper, and keeps the
global engine protected. `wf engine-fork diff` writes .wf/engine_fork.diff for the maintainer;
`wf handoff`, `wf status` and S25 show it so the change can be upstreamed.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import shutil
import subprocess
import tomllib
import zipfile
from datetime import datetime, timezone
from pathlib import Path

FORK_REL = ".wf/engine_fork"
BASE_ZIP_REL = ".wf/engine_fork_base.zip"
DIFF_REL = ".wf/engine_fork.diff"
TREES = ("tools", "pipeline", "reference", ".kiro")  # .kiro: skill + agents for install_adapters
MARKER = "ENGINE_FORK.json"


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _skip(rel: str) -> bool:
    parts = rel.split("/")
    return "__pycache__" in parts or rel.endswith((".pyc", ".pyo")) or not parts[0] in TREES


def _base_zip(engine: Path, dest: Path) -> tuple[str, str]:
    """Write the committed engine trees to `dest` -> (source, commit)."""
    from . import integrity
    dest.parent.mkdir(parents=True, exist_ok=True)
    # MEDPAPER_ENGINE_DEV=1 (engine development, selftest): the working tree is the engine meant.
    if (engine / ".git").exists() and integrity.engine_state(engine)[0] != "dev":
        try:
            done = subprocess.run(["git", "-C", str(engine), "archive", "--format=zip", "-o",
                                   str(dest), "HEAD", *TREES], capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=120)
            head = subprocess.run(["git", "-C", str(engine), "rev-parse", "HEAD"],
                                  capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=30)
            if done.returncode == 0 and dest.is_file():
                return "git HEAD", head.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
    kind, changed = integrity.engine_state(engine, use_cache=False)
    if kind == "modified":
        raise ValueError("the global engine has local edits and its committed version cannot be "
                         "read (no git); the maintainer must restore it first: "
                         + ", ".join(changed[:5]))
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for tree in TREES:
            for p in sorted((engine / tree).rglob("*")):
                rel = p.relative_to(engine).as_posix()
                if p.is_file() and not _skip(rel):
                    zf.write(p, rel)
    return "working tree", ""


def _base_members(paper: Path) -> dict[str, bytes]:
    z = Path(paper) / BASE_ZIP_REL
    if not z.is_file():
        return {}
    with zipfile.ZipFile(z) as zf:
        return {n: zf.read(n) for n in zf.namelist() if not n.endswith("/") and not _skip(n)}


def fork_root(paper: Path) -> Path:
    return Path(paper) / FORK_REL


def info(paper: Path) -> dict | None:
    p = fork_root(paper) / MARKER
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None
    except (OSError, ValueError):
        return None


def create(paper: Path, engine: Path) -> dict:
    from . import adapters
    paper, engine = Path(paper).resolve(), Path(engine).resolve()
    fork = fork_root(paper)
    if fork.exists():
        raise ValueError(f"{fork} already exists (wf engine-fork status)")
    if (engine / MARKER).is_file():
        raise ValueError("this command already runs from an engine fork")
    zpath = paper / BASE_ZIP_REL
    source, commit = _base_zip(engine, zpath)
    members = _base_members(paper)
    for rel, data in members.items():
        target = fork / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    try:
        version = tomllib.loads(members.get("pipeline/pipeline.toml", b"").decode("utf-8")) \
            .get("meta", {}).get("version", "?")
    except (UnicodeDecodeError, tomllib.TOMLDecodeError):
        version = "?"
    rec = {"schema": 1, "base_engine": str(engine), "base_version": version,
           "base_commit": commit, "base_source": source, "paper": str(paper),
           "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "files": {rel: _sha(data) for rel, data in sorted(members.items())}}
    (fork / MARKER).write_text(json.dumps(rec, indent=1) + "\n", encoding="utf-8")
    adapters.write_adapters(paper, adapters.paper_adapters(fork, paper), check=False)
    return rec


def changed_files(paper: Path) -> list[tuple[str, str]]:
    """[(M|A|D, rel)] of the fork against its recorded base."""
    rec = info(paper) or {}
    base = rec.get("files", {}) if isinstance(rec.get("files"), dict) else {}
    fork = fork_root(paper)
    cur: dict[str, str] = {}
    for tree in TREES:
        for p in sorted((fork / tree).rglob("*")) if (fork / tree).is_dir() else []:
            rel = p.relative_to(fork).as_posix()
            if p.is_file() and not _skip(rel):
                cur[rel] = _sha(p.read_bytes())
    out = [("M" if r in base and r in cur else "A" if r in cur else "D", r)
           for r in sorted(set(base) | set(cur)) if base.get(r) != cur.get(r)]
    return out


def write_diff(paper: Path) -> tuple[Path, list[tuple[str, str]]]:
    """Unified diff of the fork against the pristine base -> (.wf/engine_fork.diff, changes)."""
    paper = Path(paper)
    changes = changed_files(paper)
    base = _base_members(paper)
    fork = fork_root(paper)
    chunks: list[str] = []
    rec = info(paper) or {}
    chunks.append(f"# engine fork of {rec.get('base_engine')} {rec.get('base_version')} "
                  f"({rec.get('base_source')} {rec.get('base_commit', '')[:12]})\n")
    for status, rel in changes:
        old = base.get(rel, b"").decode("utf-8", "replace").splitlines(keepends=True)
        new = (fork / rel).read_text(encoding="utf-8", errors="replace").splitlines(keepends=True) \
            if (fork / rel).is_file() else []
        chunks.extend(difflib.unified_diff(old, new, f"a/{rel}", f"b/{rel}"))
        if chunks and not chunks[-1].endswith("\n"):
            chunks.append("\n")
    out = paper / DIFF_REL
    out.write_text("".join(chunks), encoding="utf-8")
    return out, changes


def remove(paper: Path) -> Path:
    """Keep the final diff, delete the fork and point the adapters back at the global engine."""
    from . import adapters
    paper = Path(paper).resolve()
    rec = info(paper) or {}
    diff, _ = write_diff(paper)
    base = Path(rec.get("base_engine") or "")
    shutil.rmtree(fork_root(paper))
    (paper / BASE_ZIP_REL).unlink(missing_ok=True)
    if base.is_dir():
        adapters.write_adapters(paper, adapters.paper_adapters(base, paper), check=False)
    return diff
