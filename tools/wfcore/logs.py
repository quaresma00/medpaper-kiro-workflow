"""1.13.0: one log file per command in <paper>/.wf/logs/, overwritten per run, size-capped.

Paper sessions used to scatter logs (s19_reproduce_m002d.log, $env:TEMP\\repro12.txt, a
console file per retry). Every engine log now lives in .wf/logs/: the default name is the
command (reproduce.log, wf_check.log), a requested --log inside .wf/logs keeps its name, and a
requested path anywhere else (system temp, temp/, another folder) is redirected into .wf/logs
under the same file name. The directory is pruned oldest-first to `log_cap_mb` (default 50 MB).
"""
from __future__ import annotations

import os
import re
from pathlib import Path

LOG_REL = ".wf/logs"
CAP_MB_DEFAULT = 50


def log_dir(paper: Path) -> Path:
    return Path(paper) / LOG_REL


def _within(child: Path, parent: Path) -> bool:
    a, b = os.path.normcase(str(child.resolve())), os.path.normcase(str(parent.resolve()))
    try:
        return os.path.commonpath([a, b]) == b
    except ValueError:
        return False


def _cap_bytes(paper: Path) -> int:
    mb = CAP_MB_DEFAULT
    try:
        import tomllib
        cfg = Path(paper) / ".wf" / "config.toml"
        if cfg.is_file():
            raw = tomllib.loads(cfg.read_text(encoding="utf-8")).get("targets", {}).get("log_cap_mb")
            if raw is not None:
                mb = float(raw)
    except (OSError, ValueError, TypeError):
        pass
    return int(mb * 1024 * 1024)


def prune(paper: Path, keep: Path | None = None) -> list[str]:
    """Delete the oldest logs until the directory fits the cap -> deleted names."""
    d = log_dir(paper)
    if not d.is_dir():
        return []
    files = sorted((p for p in d.rglob("*") if p.is_file()), key=lambda p: p.stat().st_mtime)
    total = sum(p.stat().st_size for p in files)
    cap, gone = _cap_bytes(paper), []
    for p in files:
        if total <= cap:
            break
        if keep is not None and p.resolve() == keep.resolve():
            continue
        try:
            size = p.stat().st_size
            p.unlink()
            total -= size
            gone.append(p.name)
        except OSError:
            continue
    return gone


def log_path(paper: Path, command: str, requested: Path | str | None = None) -> Path:
    """Where `command` logs for this paper (created, pruned)."""
    d = log_dir(paper)
    d.mkdir(parents=True, exist_ok=True)
    if requested:
        req = Path(requested)
        req = (req if req.is_absolute() else Path.cwd() / req)
        target = req if _within(req, d) else d / (req.name or f"{command}.log")
    else:
        target = d / (re.sub(r"[^\w.-]+", "_", command).strip("_") + ".log")
    target.parent.mkdir(parents=True, exist_ok=True)
    prune(paper, keep=target)
    return target
