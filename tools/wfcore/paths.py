"""Path resolution. Stdlib only.

The engine lives in one place; the papers live somewhere else. This module is what lets a
single installed engine drive many papers, and lets the Kiro skill be installed at the user
level so `/` finds it from any workspace.
"""
from __future__ import annotations

import os
from pathlib import Path


def repo_root() -> Path:
    """Engine root = parent of tools/. Overridable with MEDPAPER_ROOT."""
    env = os.environ.get("MEDPAPER_ROOT")
    if env:
        return Path(env).resolve()
    return Path(__file__).resolve().parents[2]


def pipeline_dir() -> Path:
    return repo_root() / "pipeline"


def pipeline_file() -> Path:
    return pipeline_dir() / "pipeline.toml"


def reference_dir() -> Path:
    return repo_root() / "reference"


def tools_dir() -> Path:
    return repo_root() / "tools"


def papers_dir() -> Path:
    """Where multiple papers live under one engine install."""
    return repo_root() / "papers"


def active_marker() -> Path:
    """Records which paper under papers/ is currently selected."""
    return repo_root() / ".wf" / "active"


def active_paper() -> str | None:
    p = active_marker()
    if not p.exists():
        return None
    return p.read_text(encoding="utf-8").strip() or None


def set_active_paper(slug: str) -> None:
    p = active_marker()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(slug + "\n", encoding="utf-8")


def clear_active_paper() -> None:
    active_marker().unlink(missing_ok=True)


def list_papers() -> list[Path]:
    d = papers_dir()
    if not d.is_dir():
        return []
    return sorted(p for p in d.iterdir() if p.is_dir() and (p / ".wf").is_dir())


def _find_upwards(start: Path, state_dir: str = ".wf") -> Path | None:
    """A paper directory at or above `start`, identified by its own run state.

    Only the directory itself counts, never a `project/` child. Standing in the engine root
    does not mean "I am working on the paper that happens to sit in engine/project" - that
    case is the single-paper default and is resolved last.
    """
    engine = repo_root()
    for cand in [start.resolve(), *start.resolve().parents]:
        if cand == engine:
            break
        if (cand / state_dir / "state.json").exists():
            return cand
    return None


def project_dir(layout: dict | None = None) -> Path:
    """Resolve the paper directory, in priority order.

    1. MEDPAPER_PROJECT              explicit override, used by tests and CI
    2. an initialised paper at or above the working directory
    3. the paper selected with `wf use`, under papers/
    4. <engine>/project              the single-paper default

    Order 2 before 3 is deliberate: if you are standing inside a paper, that is the paper you
    mean, whatever was selected last.
    """
    env = os.environ.get("MEDPAPER_PROJECT")
    if env:
        return Path(env).resolve()

    state_dir = (layout or {}).get("state_dir", ".wf")
    found = _find_upwards(Path.cwd(), state_dir)
    if found is not None:
        return found

    slug = active_paper()
    if slug:
        cand = papers_dir() / slug
        if (cand / state_dir / "state.json").is_file():
            return cand
        available = [p.name for p in list_papers()]
        raise SystemExit(
            f"active paper marker names '{slug}', but its state is missing. Refusing to fall "
            f"back to <engine>/project.\nSelect a real paper with `wf use <slug>`. Available: "
            + (", ".join(available) if available else "(none)"))

    available = list_papers()
    if available:
        raise SystemExit(
            "papers exist but none is selected. Refusing to fall back to <engine>/project, "
            "which would pollute the mother workflow.\nSelect one with:  wf use "
            + available[0].name)

    name = (layout or {}).get("project_dir", "project")
    return repo_root() / name


def describe_project_source(layout: dict | None = None) -> str:
    """Human-readable reason the current paper directory was chosen."""
    if os.environ.get("MEDPAPER_PROJECT"):
        return "MEDPAPER_PROJECT"
    state_dir = (layout or {}).get("state_dir", ".wf")
    if _find_upwards(Path.cwd(), state_dir) is not None:
        return "found at or above the working directory"
    if active_paper():
        return f"selected with `wf use {active_paper()}`"
    return "engine default"


def rel(p: Path) -> str:
    """Engine-relative POSIX path for stable printing; absolute when outside the engine."""
    try:
        return p.resolve().relative_to(repo_root()).as_posix()
    except ValueError:
        return p.as_posix()


def resolve_paper_path(raw: str | Path, layout: dict | None = None) -> Path:
    """Resolve the documented `project/...` alias against the active paper.

    Stage cards historically use `project/05_figures/...` and similar paths because the
    workflow began as a single-paper engine. In one-engine/many-papers mode, treating that as a
    normal relative path writes into <engine>/project whenever a standalone script runs from
    the engine root. `project/` is therefore a logical alias, not a physical directory:

        project/05_figures/out/Figure1.png
            -> papers/<selected>/05_figures/out/Figure1.png

    Absolute paths and other relative paths retain their ordinary meaning. This lets a user
    still pass an explicit file outside the paper where a command supports it.
    """
    p = Path(raw)
    if p.is_absolute():
        return p.resolve()
    parts = p.parts
    if parts and parts[0].casefold() == "project":
        base = project_dir(layout).resolve()
        candidate = (base / Path(*parts[1:])).resolve()
        try:
            candidate.relative_to(base)
        except ValueError as exc:
            raise ValueError(f"logical project path escapes the selected paper: {raw}") from exc
        return candidate
    return p


def paper_output_path(raw: str | Path, layout: dict | None = None) -> Path:
    """Resolve an output path and refuse writes outside the selected paper."""
    paper = project_dir(layout).resolve()
    resolved = resolve_paper_path(raw, layout)
    candidate = resolved.resolve() if resolved.is_absolute() else (Path.cwd() / resolved).resolve()
    try:
        candidate.relative_to(paper)
    except ValueError as exc:
        raise ValueError(f"output path must stay inside the selected paper: {raw}") from exc
    return candidate
