"""Path resolution. Stdlib only.

The engine lives in one place; the papers live somewhere else. Since 1.5.0 the engine is a
pure, maintenance-only workflow: no paper may live in it, be resolved inside it, or write into
it. 1.13.0: the paper is the Kiro workspace folder the user opened (`wf init` there, in place);
the central papers root (MEDPAPER_PAPERS_ROOT, ~/.medpaper/config.toml `papers_root`,
<engine parent>/medpaper_papers) is used only on explicit request (`wf new <slug> --central`).
"Which paper" comes only from the working directory (or MEDPAPER_PROJECT); the old user-level
`wf use` marker is no longer read. An engine fork (<paper>/.wf/engine_fork/ENGINE_FORK.json)
is engine only inside its own folder, belongs to exactly one paper and keeps the global engine
it was copied from protected.
"""
from __future__ import annotations

import json
import os
import re
import tomllib
from pathlib import Path

FORK_MARKER = "ENGINE_FORK.json"
FORK_REL = ".wf/engine_fork"


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


def fork_info(root: Path | str | None = None) -> dict | None:
    """The ENGINE_FORK.json of an engine fork root (None for a normal engine)."""
    p = Path(root or _physical_engine()) / FORK_MARKER
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"broken": True}
    return data if isinstance(data, dict) else {"broken": True}


def is_fork_root(root: Path | str) -> bool:
    return (Path(root) / FORK_MARKER).is_file()


def fork_owner(root: Path | str | None = None) -> Path | None:
    """<paper> for an engine fork at <paper>/.wf/engine_fork, else None."""
    root = Path(root or _physical_engine()).resolve()
    return root.parents[1] if is_fork_root(root) and len(root.parents) >= 2 else None


def base_engine() -> Path | None:
    """The global engine a running fork was copied from (still protected, read-only)."""
    info = fork_info()
    raw = (info or {}).get("base_engine")
    return Path(raw).resolve() if isinstance(raw, str) and raw else None


def engine_roots() -> tuple[Path, ...]:
    """The physical engine plus repo_root() when MEDPAPER_ROOT points elsewhere, plus the
    global engine a fork was copied from.

    Redirecting MEDPAPER_ROOT therefore never removes protection from the physical engine.
    """
    phys, cfg = _physical_engine(), repo_root()
    roots = [phys] if _norm(phys) == _norm(cfg) else [phys, cfg]
    base = base_engine()
    if base is not None:
        roots.append(base)
    out: list[Path] = []
    for r in roots:
        if all(_norm(r) != _norm(o) for o in out):
            out.append(r)
    return tuple(out)


def in_engine(p: Path | str) -> bool:
    """p is an engine root, lies inside one, or contains one.

    A fork lives inside its paper, so for a fork root only "inside" counts: the paper that
    holds .wf/engine_fork is not "over the engine"."""
    return any(within(p, e) or (within(e, p) and not is_fork_root(e)) for e in engine_roots())


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
            f"medpaper engine ({engine_roots()[0]}). A paper is the folder the user opened as "
            f"its Kiro workspace, never the engine.")
    owner = fork_owner()
    if owner is not None and _norm(owner) != _norm(resolved):
        raise PaperLocationError(
            f"refusing paper path from {source}: this engine fork belongs to {owner} and drives "
            f"no other paper")
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
            found.extend(str(p.parents[1]) for p in target.glob(pattern)
                         if not _norm(p.parents[1]).startswith(_norm(target / ".wf")))
    if found:
        raise SystemExit(f"{target} already contains {len(found)} other paper(s); a paper folder "
                         "never holds other papers")


ASK_ONCE = ("Ask the user once which folder this paper should live in, open that folder as the "
            "Kiro workspace and run `wf init` there. Never invent a location (such as a "
            "'studies' folder next to the data) and never use the data folder or its parent.")


def user_files(project: Path | str) -> set[str]:
    """Files the user already had in the folder when `wf init` made it a paper (1.13.0)."""
    p = Path(project) / ".wf" / "user_files.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    except (OSError, ValueError):
        return set()
    return {f for f in data.get("files", []) if isinstance(f, str)} if isinstance(data, dict) \
        else set()


def unsuitable_paper_dir(target: Path | str) -> str | None:
    """Why `target` cannot be a paper folder (1.13.0), or None.

    Refused: a drive root, the user's home folder, the engine (or a folder inside or around
    it), a folder inside another paper, the central papers root itself, a folder that already
    holds other papers."""
    t = Path(target).expanduser().resolve()
    if t.parent == t:
        return f"{t} is a drive root"
    try:
        if _norm(t) == _norm(Path.home()):
            return f"{t} is your home folder"
    except RuntimeError:
        pass
    if in_engine(t):
        return f"{t} is inside, equal to or contains the medpaper engine"
    try:
        check_not_nested(t)
    except SystemExit as exc:
        return str(exc)
    return None


# ---------------------------------------------------------------------------
# which paper
# ---------------------------------------------------------------------------
def _find_upwards(start: Path, state_dir: str = ".wf") -> Path | None:
    """A paper directory at or above `start`, identified by its own run state."""
    for cand in [start.resolve(), *start.resolve().parents]:
        if (cand / state_dir / "state.json").exists():
            return cand
    return None


def cwd_paper(state_dir: str = ".wf") -> Path | None:
    """The paper the working directory belongs to (None in the engine or outside any paper)."""
    try:
        if cwd_in_engine():
            return None
        return _find_upwards(Path.cwd(), state_dir)
    except OSError:
        return None


def _same_paper_as_cwd(resolved: Path, source: str, state_dir: str = ".wf") -> None:
    """1.13.0: engine commands act only on the paper of the workspace they run in."""
    here = cwd_paper(state_dir)
    if here is not None and _norm(here) != _norm(resolved):
        raise PaperLocationError(
            f"refusing {source} {resolved}: the working directory belongs to the paper {here}. "
            "Commands act only on the paper of the workspace you are in; never on another paper.")


def project_dir(layout: dict | None = None, *, check_engine: bool = True) -> Path:
    """Resolve the paper directory.

    1. MEDPAPER_PROJECT        set by the paper's own adapters, tests and CI; refused when the
                               working directory belongs to a different paper
    2. cwd inside the engine   EngineWorkspace (maintenance only)
    3. an initialised paper at or above the working directory
    The user-level `wf use` marker is no longer read (1.13.0): a paper is the workspace you
    are in. Then the shared engine must be unmodified (integrity.require_clean).
    """
    state_dir = (layout or {}).get("state_dir", ".wf")
    env = os.environ.get("MEDPAPER_PROJECT")
    if env:
        found = check_paper_location(env, "MEDPAPER_PROJECT")
        _same_paper_as_cwd(found, "MEDPAPER_PROJECT", state_dir)
    elif cwd_in_engine():
        raise EngineWorkspace(ENGINE_MESSAGE)
    else:
        here = _find_upwards(Path.cwd(), state_dir)
        if here is None:
            raise SystemExit(
                "no paper here: the working directory is not inside an initialised paper.\n"
                "The paper is the folder the user opened as the Kiro workspace: run `wf init` "
                "there (in place). " + ASK_ONCE.split(". ", 1)[1])
        found = check_paper_location(here, "working directory")
    if check_engine:
        from . import integrity
        integrity.require_clean()
    return found


def describe_project_source(layout: dict | None = None) -> str:
    """Human-readable reason the current paper directory was chosen."""
    if os.environ.get("MEDPAPER_PROJECT"):
        return "MEDPAPER_PROJECT"
    state_dir = (layout or {}).get("state_dir", ".wf")
    if _find_upwards(Path.cwd(), state_dir) is not None:
        return "the working directory"
    return "nothing selected"


def paper_from_cli(arg: Path | str | None, *, check_engine: bool = True) -> Path:
    """The paper an engine CLI acts on (`--project`): only the paper of the working directory
    (or of MEDPAPER_PROJECT when the cwd is outside every paper)."""
    if arg is None or str(arg) == "":
        return project_dir(check_engine=check_engine)
    p = Path(arg)
    if not p.is_absolute() and p.parts and p.parts[0].casefold() == "project":
        return project_dir(check_engine=check_engine)
    if not p.is_absolute():
        p = Path.cwd() / p
    resolved = check_paper_location(p, "--project")
    if not (resolved / ".wf" / "state.json").is_file():
        raise SystemExit(f"--project {resolved} is not an initialised paper")
    _same_paper_as_cwd(resolved, "--project")
    if check_engine:
        from . import integrity
        integrity.require_clean()
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
