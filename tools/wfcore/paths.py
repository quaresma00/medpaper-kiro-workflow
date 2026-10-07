"""Path resolution. Stdlib only.

The engine lives in one place; the papers live somewhere else. Since 1.5.0 the engine is a
pure, maintenance-only workflow: no paper may live in it, be resolved inside it, or write into
it. Papers live under a papers root outside the engine (MEDPAPER_PAPERS_ROOT, then
~/.medpaper/config.toml `papers_root`, then <engine parent>/medpaper_papers), each opened as its
own Kiro workspace, and "which paper" is a user-level marker (~/.medpaper/active).
"""
from __future__ import annotations

import os
import re
import tomllib
from pathlib import Path


class EngineWorkspace(SystemExit):
    """The working directory is the engine: maintenance only, no paper may be driven here."""


class PaperLocationError(SystemExit):
    """A resolved paper (or user-state) path is inside, equal to, or contains the engine."""


ENGINE_MESSAGE = (
    "this is the medpaper ENGINE workspace (maintenance only). No paper may live in or be "
    "driven from it.\n"
    "Open a paper folder as its own Kiro workspace, or start one with:  python tools/wf.py new "
    "<slug>")


def _physical_engine() -> Path:
    return Path(__file__).resolve().parents[2]


def repo_root() -> Path:
    """Engine root = parent of tools/. Overridable with MEDPAPER_ROOT."""
    env = os.environ.get("MEDPAPER_ROOT")
    if env:
        return Path(env).resolve()
    return _physical_engine()


def pipeline_dir() -> Path:
    return repo_root() / "pipeline"


def pipeline_file() -> Path:
    return pipeline_dir() / "pipeline.toml"


def reference_dir() -> Path:
    return repo_root() / "reference"


def tools_dir() -> Path:
    return repo_root() / "tools"


# ---------------------------------------------------------------------------
# engine identity
# ---------------------------------------------------------------------------
def _norm(p: Path | str) -> str:
    return os.path.normcase(str(Path(p).resolve()))


def within(child: Path | str, parent: Path | str) -> bool:
    """True when `child` is `parent` or lies below it (resolved, case-normalised)."""
    a, b = _norm(child), _norm(parent)
    try:
        return os.path.commonpath([a, b]) == b
    except ValueError:  # different drives
        return False


def engine_roots() -> tuple[Path, ...]:
    """The physical engine plus repo_root() when MEDPAPER_ROOT points elsewhere.

    Redirecting MEDPAPER_ROOT therefore never removes protection from the physical engine.
    """
    phys, cfg = _physical_engine(), repo_root()
    return (phys,) if _norm(phys) == _norm(cfg) else (phys, cfg)


def in_engine(p: Path | str) -> bool:
    """p is an engine root, lies inside one, or contains one."""
    return any(within(p, e) or within(e, p) for e in engine_roots())


def cwd_in_engine() -> bool:
    try:
        cwd = Path.cwd()
    except OSError:
        return False
    return any(within(cwd, e) for e in engine_roots())


def check_paper_location(p: Path | str, source: str) -> Path:
    resolved = Path(p).expanduser().resolve()
    if in_engine(resolved):
        raise PaperLocationError(
            f"refusing paper path from {source}: {resolved} is inside, equal to or contains the "
            f"medpaper engine ({engine_roots()[0]}). Papers live under the papers root "
            f"(wf papers), never in the engine.")
    return resolved


# ---------------------------------------------------------------------------
# user-level state and the papers root
# ---------------------------------------------------------------------------
def user_home() -> Path:
    env = os.environ.get("MEDPAPER_HOME")
    if env:
        home = Path(env).expanduser()
        if not home.is_absolute():
            raise SystemExit(f"MEDPAPER_HOME must be an absolute path, got {env!r}")
    else:
        home = Path.home() / ".medpaper"
    home = home.resolve()
    if in_engine(home):
        raise PaperLocationError(
            f"refusing user state location {home}: it is inside or contains the medpaper engine")
    return home


def user_config() -> dict:
    p = user_home() / "config.toml"
    if not p.is_file():
        return {}
    try:
        return tomllib.loads(p.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise SystemExit(f"malformed {p}: {exc}") from exc


def papers_root() -> tuple[Path, str]:
    """(papers root, source). Refused when it is in, equal to or contains an engine root."""
    env = os.environ.get("MEDPAPER_PAPERS_ROOT")
    if env is not None:
        raw, source = env, "MEDPAPER_PAPERS_ROOT"
    else:
        cfg = user_config()
        if "papers_root" in cfg:
            raw, source = cfg["papers_root"], "~/.medpaper/config.toml"
        else:
            raw, source = str(repo_root().parent / "medpaper_papers"), "default"
    if not isinstance(raw, str) or not raw.strip():
        raise SystemExit(f"papers root from {source} must be a non-empty path string")
    root = Path(raw.strip()).expanduser()
    if not root.is_absolute():
        raise SystemExit(f"papers root from {source} must be absolute, got {raw!r}")
    root = root.resolve()
    if in_engine(root):
        raise PaperLocationError(
            f"refusing papers root from {source}: {root} is inside, equal to or contains the "
            f"medpaper engine. Papers live outside the engine.")
    return root, source


def papers_dir() -> Path:
    return papers_root()[0]


def active_marker() -> Path:
    return user_home() / "active"


def active_paper() -> Path | None:
    p = active_marker()
    if not p.is_file():
        return None
    raw = p.read_text(encoding="utf-8").strip()
    return Path(raw) if raw else None


def set_active_paper(paper: Path) -> None:
    p = active_marker()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(str(Path(paper).resolve()) + "\n", encoding="utf-8")


def clear_active_paper() -> None:
    active_marker().unlink(missing_ok=True)


def list_papers() -> list[Path]:
    root = papers_dir()
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if p.is_dir() and (p / ".wf" / "state.json").is_file())


def check_not_nested(target: Path) -> None:
    """Refuse a paper inside a paper, the papers root itself, or a folder holding papers."""
    target = Path(target).resolve()
    for anc in target.parents:
        if (anc / ".wf" / "state.json").is_file():
            raise SystemExit(f"{target} is inside the paper {anc}; papers cannot be nested")
    try:
        root = papers_dir()
    except SystemExit:
        root = None
    if root is not None and _norm(root) == _norm(target):
        raise SystemExit(f"{target} is the papers root; it holds papers, it is not one")
    found: list[str] = []
    if target.is_dir():
        for pattern in ("*/.wf/state.json", "*/*/.wf/state.json"):
            found.extend(str(p.parents[1]) for p in target.glob(pattern))
    if found:
        raise SystemExit(f"{target} already contains the paper(s) {', '.join(sorted(found)[:3])}")


# ---------------------------------------------------------------------------
# which paper
# ---------------------------------------------------------------------------
def _find_upwards(start: Path, state_dir: str = ".wf") -> Path | None:
    """A paper directory at or above `start`, identified by its own run state."""
    for cand in [start.resolve(), *start.resolve().parents]:
        if (cand / state_dir / "state.json").exists():
            return cand
    return None


def project_dir(layout: dict | None = None) -> Path:
    """Resolve the paper directory, in priority order.

    1. MEDPAPER_PROJECT              explicit override, used by tests and CI
    2. cwd inside the engine         EngineWorkspace (maintenance only)
    3. an initialised paper at or above the working directory
    4. the paper selected with `wf use` (user-level marker)
    """
    env = os.environ.get("MEDPAPER_PROJECT")
    if env:
        return check_paper_location(env, "MEDPAPER_PROJECT")
    if cwd_in_engine():
        raise EngineWorkspace(ENGINE_MESSAGE)

    state_dir = (layout or {}).get("state_dir", ".wf")
    found = _find_upwards(Path.cwd(), state_dir)
    if found is not None:
        return check_paper_location(found, "working directory")

    marker = active_paper()
    if marker is not None:
        if not (marker / state_dir / "state.json").is_file():
            raise SystemExit(
                f"active paper marker names {marker}, but its state is missing. Refusing to "
                f"guess.\nSelect a real paper with `wf use <slug|path>` or start one with "
                f"`wf new <slug>`.")
        return check_paper_location(marker, "wf use")

    raise SystemExit(
        "no paper selected. Start one with `wf new <slug>`, select one with `wf use <slug|path>`, "
        "or open a paper folder as the workspace.")


def describe_project_source(layout: dict | None = None) -> str:
    """Human-readable reason the current paper directory was chosen."""
    if os.environ.get("MEDPAPER_PROJECT"):
        return "MEDPAPER_PROJECT"
    state_dir = (layout or {}).get("state_dir", ".wf")
    if _find_upwards(Path.cwd(), state_dir) is not None:
        return "found at or above the working directory"
    marker = active_paper()
    if marker is not None:
        return f"selected with wf use ({marker})"
    return "nothing selected"


def paper_from_cli(arg: Path | str | None) -> Path:
    """The paper an engine CLI acts on (`--project`)."""
    if arg is None or str(arg) == "":
        return project_dir()
    p = Path(arg)
    if not p.is_absolute() and p.parts and p.parts[0].casefold() == "project":
        return project_dir()
    if not p.is_absolute():
        p = Path.cwd() / p
    resolved = check_paper_location(p, "--project")
    if not (resolved / ".wf" / "state.json").is_file():
        raise SystemExit(f"--project {resolved} is not an initialised paper")
    return resolved


def rel(p: Path) -> str:
    """Engine-relative POSIX path for stable printing; absolute when outside the engine."""
    try:
        return p.resolve().relative_to(repo_root()).as_posix()
    except ValueError:
        return p.as_posix()


def resolve_paper_path(raw: str | Path, layout: dict | None = None) -> Path:
    """Resolve the documented `project/...` alias against the active paper.

    `project/05_figures/out/Figure1.png` -> <paper>/05_figures/out/Figure1.png. Absolute paths
    and other relative paths keep their ordinary meaning.
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
    """Resolve an output path and refuse writes in the engine or outside the selected paper."""
    resolved = resolve_paper_path(raw, layout)
    candidate = resolved.resolve() if resolved.is_absolute() else (Path.cwd() / resolved).resolve()
    if any(within(candidate, e) for e in engine_roots()):
        raise ValueError(f"output path is inside the engine and is refused: {raw}")
    paper = project_dir(layout).resolve()
    try:
        candidate.relative_to(paper)
    except ValueError as exc:
        raise ValueError(f"output path must stay inside the selected paper: {raw}") from exc
    return candidate


def output_within(paper: Path, raw: str | Path) -> Path:
    """An explicit output path for a CLI that already holds its paper."""
    p = Path(raw)
    if not p.is_absolute() and p.parts and p.parts[0].casefold() == "project":
        cand = (Path(paper) / Path(*p.parts[1:])).resolve() if len(p.parts) > 1 \
            else Path(paper).resolve()
    elif p.is_absolute():
        cand = p.resolve()
    else:
        cand = (Path.cwd() / p).resolve()
    if in_engine(cand):
        raise ValueError(f"output path is inside the engine and is refused: {raw}")
    if not within(cand, paper):
        raise ValueError(f"output path must stay inside the paper: {raw}")
    return cand


# ---------------------------------------------------------------------------
# render-time localisation of card text and hints
# ---------------------------------------------------------------------------
PROJECT_ALIAS_RE = re.compile(r"(?<![\w/\\.\-])project/")
_VENV_RE = re.compile(
    r"(?:\.\\\.venv\\Scripts\\python\.exe|\.venv[/\\]Scripts[/\\]python\.exe)\s+tools([/\\])")
_PY_RE = re.compile(r'(?<![\w/\\."])python\s+tools[/\\]([^\s`)\]]+)')
_BARE_TOOL_RE = re.compile(r'(?<![\w/\\.\-"<>])tools[/\\]([\w./\\-]+\.py)')
_BARE_REF_RE = re.compile(r'(?<![\w/\\.\-"<>$])reference[/\\]([\w./\\-]+)')


def localize_commands(text: str, paper: Path | None = None) -> str:
    """Make card text and hints valid from the workspace the agent is actually in."""
    engine_cwd = cwd_in_engine()
    if paper is None and engine_cwd:
        return text
    if paper is not None:
        try:
            at_root = _norm(Path.cwd()) == _norm(paper)
        except OSError:
            at_root = False
        repl = "" if at_root else Path(paper).resolve().as_posix() + "/"
        text = PROJECT_ALIAS_RE.sub(lambda _m: repl, text)
    if engine_cwd:
        return text
    engine = _physical_engine().as_posix() if _norm(repo_root()) == _norm(_physical_engine()) \
        else repo_root().as_posix()
    spaced = " " in engine
    venv = f"{engine}/.venv/Scripts/python.exe"

    def venv_sub(_m):
        return (f'& "{venv}" {engine}/tools/' if spaced else f"{venv} {engine}/tools/")

    text = _VENV_RE.sub(venv_sub, text)
    text = _PY_RE.sub(lambda m: f'python "{engine}/tools/{m[1].replace(chr(92), "/")}"', text)
    text = _BARE_TOOL_RE.sub(lambda m: f'python "{engine}/tools/{m[1].replace(chr(92), "/")}"',
                             text)
    text = _BARE_REF_RE.sub(lambda m: f"{engine}/reference/{m[1].replace(chr(92), '/')}", text)
    return text
