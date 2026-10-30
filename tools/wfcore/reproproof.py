"""Reproducibility proof: what S06 re-executes and how the gate re-checks it. Stdlib only.

`tools/reproduce.py run` copies exactly `sandbox_inputs()` into a sandbox, re-runs every
top-level 03_analysis/code script in the order `ordered_scripts()` gives (the paper's
analysis_manifest.json, else filename order) - or, with `--affected-only`, only the scripts
`affected_scripts()` reaches, carrying the rest from the previous passing proof - keeps the
re-run results in `.wf/repro/rerun/` and writes
`03_analysis/reproducibility_report.json`. `validate()` (gate `analysis_reproduces`) recomputes
every verdict from those files; the report's statuses are informational.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

REPORT_REL = "03_analysis/reproducibility_report.json"
TOLERANCE_REL = "03_analysis/reproducibility.toml"
MANIFEST_REL = "03_analysis/analysis_manifest.json"
VOLATILE_KEYS = frozenset({"run_at", "built_at", "generated_at", "timestamp", "timestamps",
                           "written_at"})
ACQ_PREFIX = "02_data/acquisition/"
ACQ_RESULT = "03_analysis/results/dataset_summary.json"
TOL_ABS_MAX = 1e-6
TOL_REL_MAX = 1e-6
INPUT_TREES = ("02_data", "03_analysis/code")
RERUN_DIR = ".wf/repro/rerun"
# 1.13.0: the sandbox lives inside the paper, one at a time, and is deleted after the run;
# 1.14.0: inputs are copied (never hard-linked) and leftovers are removed only with an owner
# marker whose process is gone (cleanup_stale).
SANDBOX_DIR = ".wf/repro/sandboxes"
LOCK_REL = ".wf/repro/run.lock"
SNAPSHOT_EXCLUDE = (".wf", "temp", ".kiro", REPORT_REL)
# 1.13.0: documentation, acquisition code (never re-run), the extraction cache and the S04
# receipts are not analysis inputs; editing them never invalidates the proof.
INPUT_EXCLUDE_DIRS = ("02_data/derived", "02_data/acquisition", "02_data/cache")
INPUT_EXCLUDE_FILES = ("02_data/acquisition_manifest.json", "02_data/variable_crosswalk.json")
DOC_SUFFIXES = (".md",)
INPUT_EXCLUDE_NAMES = ("__pycache__", ".Rhistory", ".DS_Store")
RESULTS_DIR = "03_analysis/results"
DATASOURCE_PREFIX = "datasource:"
# 1.11.0 (#2f): reproduction depends only on data, analysis code, manifest, tolerances and the
# engine helpers. Edits in these trees during a run are manuscript/package work, not inputs.
NON_ANALYSIS_PREFIXES = ("00_input/", "01_protocol/", "04_tables/", "05_figures/", "06_refs/",
                         "07_manuscript/", "08_submission/")


def counts_as_input(rel: str) -> bool:
    """1.13.0: is this paper path (or datasource label) an analysis input?"""
    rel = rel.replace("\\", "/")
    if rel.startswith(DATASOURCE_PREFIX) or rel in (TOLERANCE_REL, MANIFEST_REL):
        return True
    if not rel.startswith(tuple(t + "/" for t in INPUT_TREES)):
        return False
    if any(rel == d or rel.startswith(d + "/") for d in INPUT_EXCLUDE_DIRS):
        return False
    if rel in INPUT_EXCLUDE_FILES or (rel.startswith("02_data/") and rel.endswith(DOC_SUFFIXES)):
        return False
    parts = rel.split("/")
    return not any(p in INPUT_EXCLUDE_NAMES for p in parts) and not rel.endswith((".pyc", ".pyo"))


def split_paper_changes(changes: list[str]) -> tuple[list[str], list[str]]:
    """(changes that invalidate the run, other edits recorded for information).

    1.13.0: only analysis inputs and results invalidate a run; notes, documentation and
    manuscript work in the meantime are recorded, never fatal."""
    keep = [c for c in changes if counts_as_input(c) or c.startswith(RESULTS_DIR + "/")
            or not c.startswith(("00_input/", "01_protocol/", "02_data/", "03_analysis/",
                                 "04_tables/", "05_figures/", "06_refs/", "07_manuscript/",
                                 "08_submission/"))]
    return keep, [c for c in changes if c not in keep]


_ISO = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")


@dataclass
class Tol:
    abs: float
    rel: float
    reason: str


@dataclass
class Outcome:
    ok: bool
    problems: list[str]
    detail: str


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# 1.13.0: sandbox housekeeping - never copy the user's data, never leave GBs behind
# ---------------------------------------------------------------------------
def _pid_alive(pid: int) -> bool:
    import os
    import sys
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFO
        if not handle:
            return False
        code = ctypes.c_ulong()
        ok = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return bool(ok) and code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def acquire_lock(project: Path) -> str | None:
    """Take the per-paper run lock -> None, or the reason another run holds it."""
    import os
    lock = Path(project) / LOCK_REL
    lock.parent.mkdir(parents=True, exist_ok=True)
    if lock.is_file():
        try:
            info = json.loads(lock.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            info = {}
        if _pid_alive(int(info.get("pid", 0) or 0)) and int(info.get("pid", 0)) != os.getpid():
            return (f"another reproduce.py run is active for this paper (pid {info.get('pid')}, "
                    f"since {info.get('started_at')}); wait for its REPRODUCE DONE line - never "
                    "start a second run or kill the first")
    from datetime import datetime, timezone
    lock.write_text(json.dumps({"pid": os.getpid(), "started_at": datetime.now(timezone.utc)
                                .strftime("%Y-%m-%dT%H:%M:%SZ")}), encoding="utf-8")
    return None


def release_lock(project: Path) -> None:
    (Path(project) / LOCK_REL).unlink(missing_ok=True)


def _rmtree(path: Path) -> None:
    import os
    import shutil
    import stat

    def onerror(func, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            pass
    shutil.rmtree(path, onerror=onerror)


class DataCopyRefused(Exception):
    """Providing an input would copy more data than data_copy_limit_mb allows."""


class Budget:
    """1.14.0 (D): inputs reach the sandbox as copies within data_copy_limit_mb, never as hard
    links (a hard link is the same file: a script writing the sandbox path would change the
    original). Raw data is read in place through analysis.datasources.source_path()."""

    def __init__(self, limit: int):
        self.limit, self.copied, self.linked = int(limit), 0, 0


def unlink_links(budget: Budget) -> None:
    """Kept for callers of 1.13: there are no links to remove any more."""
    return None


def provide(src: Path, dst: Path, budget: Budget, *, prefer_copy: bool = False) -> str:
    """Copy `src` to `dst` within the budget, else raise DataCopyRefused (never a link)."""
    import shutil
    dst.parent.mkdir(parents=True, exist_ok=True)
    size = src.stat().st_size
    if budget.copied + size > budget.limit:
        raise DataCopyRefused(
            f"{src.name}: providing it to the sandbox would copy "
            f"{(budget.copied + size) / 1e6:,.0f} MB of input data (limit "
            f"{budget.limit / 1e6:,.0f} MB, data_copy_limit_mb). Never copy the user's dataset "
            "and never link it: declare it in place (`wf data add <path>`) and read it with "
            "analysis.datasources.source_path() (R: medpaper_source_path()); derived products "
            "that large belong in a declared source too.")
    shutil.copyfile(src, dst)  # contents only: the original's attributes/ACLs are never touched
    budget.copied += size
    return "copy"


# ---------------------------------------------------------------------------
# 1.14.0 (D): data integrity around a run - every data source and every in-place input
# ---------------------------------------------------------------------------
def integrity_snapshot(project: Path, extra: list[Path] | None = None) -> dict[str, dict]:
    """{label: {path, size, mtime_ns, sha256}} of every declared data-source file plus the
    paper inputs given in `extra` (size + mtime + cached sha256)."""
    from . import datasources
    project = Path(project)
    out: dict[str, dict] = {}
    items = list(datasources.files(project))
    items += [(Path(p).relative_to(project).as_posix() if _inside(p, project) else str(p), Path(p))
              for p in (extra or [])]
    for label, path in items:
        try:
            st = path.stat()
            out[label] = {"path": str(path), "size": st.st_size, "mtime_ns": st.st_mtime_ns,
                          "sha256": datasources.cached_sha256(project, path)}
        except OSError:
            out[label] = {"path": str(path), "missing": True}
    return out


def _inside(p, root) -> bool:
    try:
        Path(p).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


def integrity_changes(before: dict[str, dict]) -> list[str]:
    """Labels whose content changed (or that vanished/appeared) since `before`; a full hash
    only when size or mtime differ."""
    from . import datasources
    changed = []
    for label, rec in sorted(before.items()):
        path = Path(rec["path"])
        try:
            st = path.stat()
        except OSError:
            if not rec.get("missing"):
                changed.append(f"{label} (deleted)")
            continue
        if rec.get("missing"):
            changed.append(f"{label} (created)")
            continue
        if st.st_size == rec["size"] and st.st_mtime_ns == rec["mtime_ns"]:
            continue
        if datasources._raw_sha(path) != rec["sha256"]:
            changed.append(label)
    return changed


# ---------------------------------------------------------------------------
# 1.14.0 (D): sandbox ownership and cleanup
# ---------------------------------------------------------------------------
MARKER = ".medpaper_sandbox.json"
LEGACY_AGE_HOURS = 12.0


def write_marker(sandbox: Path, project: Path) -> None:
    import os
    import socket
    from datetime import datetime, timezone
    (Path(sandbox) / MARKER).write_text(json.dumps({
        "paper": str(Path(project).resolve()), "pid": os.getpid(), "host": socket.gethostname(),
        "started_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}),
        encoding="utf-8")


def _process_texts() -> list[str] | None:
    """Command lines (and cwd where readable) of running processes; None when unknown."""
    import os
    import subprocess
    import sys
    if sys.platform == "win32":
        try:
            done = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 "Get-CimInstance Win32_Process | ForEach-Object { $_.CommandLine }"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        except (OSError, subprocess.SubprocessError):
            return None
        return [ln for ln in done.stdout.splitlines() if ln.strip()] if done.returncode == 0 else None
    out = []
    proc = Path("/proc")
    if not proc.is_dir():
        return None
    for d in proc.iterdir():
        if not d.name.isdigit():
            continue
        try:
            out.append((d / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace"))
            out.append(os.readlink(d / "cwd"))
        except OSError:
            continue
    return out


def _referenced(d: Path, texts: list[str] | None) -> bool:
    if texts is None:
        return True  # cannot tell: keep it
    key = str(d).casefold()
    return any(key in t.casefold() for t in texts)


def _fresh_lock(d: Path, hours: float) -> bool:
    import time
    for p in d.glob("*.lock"):
        try:
            if time.time() - p.stat().st_mtime < hours * 3600:
                return True
        except OSError:
            continue
    return False


def cleanup_stale(project: Path, legacy_age_hours: float = LEGACY_AGE_HOURS
                  ) -> tuple[list[tuple[str, int]], list[str]]:
    """Remove sandboxes of interrupted runs -> (removed [(path, bytes)], kept [reason]).

    A sandbox with an owner marker is removed only when it belongs to this paper, its process
    (same host) is no longer alive and this paper's run lock is not held by it. A folder
    without a marker (<= 1.13) is removed only when older than `legacy_age_hours`, no running
    process references it (command line / cwd) and it holds no fresh lock; otherwise it is
    listed for the user. Another paper's sandbox is never touched. This paper's own unmarked
    1.13 sandboxes (.wf/repro/sandboxes/run_*) are removed: the caller holds the paper's lock."""
    import socket
    import tempfile
    import time
    project = Path(project).resolve()
    removed: list[tuple[str, int]] = []
    kept: list[str] = []
    texts: list[str] | None = None
    texts_read = False

    def size(d: Path) -> int:
        total = 0
        for p in d.rglob("*"):
            try:
                if p.is_file() and not p.is_symlink():
                    total += p.stat().st_size
            except OSError:
                pass
        return total

    def consider(d: Path, local: bool) -> None:
        nonlocal texts, texts_read
        marker = d / MARKER
        if local and not marker.is_file():
            pass  # a 1.13 sandbox of this paper; this run holds the paper's lock
        elif marker.is_file():
            try:
                info = json.loads(marker.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                info = {}
            if str(info.get("paper", "")).casefold() != str(project).casefold():
                kept.append(f"{d} (another paper's sandbox; left alone)")
                return
            if info.get("host") != socket.gethostname() or _pid_alive(int(info.get("pid", 0) or 0)):
                kept.append(f"{d} (its run may still be active)")
                return
        else:
            try:
                old = time.time() - d.stat().st_mtime > legacy_age_hours * 3600
            except OSError:
                return
            if not texts_read:
                texts, texts_read = _process_texts(), True
            if not old or _fresh_lock(d, legacy_age_hours) or _referenced(d, texts):
                kept.append(f"{d} (no owner marker; younger than {legacy_age_hours:g} h, locked "
                            "or used by a running process - delete it yourself when sure)")
                return
        n = size(d)
        _rmtree(d)
        removed.append((str(d), n))

    root = project / SANDBOX_DIR
    for d in sorted(root.glob("run_*")) if root.is_dir() else []:
        if d.is_dir():
            consider(d, True)
    for d in sorted(Path(tempfile.gettempdir()).glob("medpaper_repro_*")):
        if d.is_dir():
            consider(d, False)
    return removed, kept


def analysis_scripts(project: Path) -> list[Path]:
    code = Path(project) / "03_analysis" / "code"
    if not code.is_dir():
        return []
    return sorted((p for p in code.iterdir()
                   if p.is_file() and p.suffix.casefold() in (".py", ".r")),
                  key=lambda p: p.name.casefold())


# ---------------------------------------------------------------------------
# Execution order (1.7.1). A file name is not a dependency declaration: "02_model" running
# after "01_clean" is a naming convention, and a renamed or inserted script silently reorders
# the analysis. The paper may declare the order in 03_analysis/analysis_manifest.json:
#
#   {"schema": 1, "scripts": [
#      {"path": "03_analysis/code/01_clean.py", "outputs": ["02_data/derived/clean.csv"]},
#      {"path": "03_analysis/code/02_model.py", "inputs": ["02_data/derived/clean.csv"],
#       "outputs": ["03_analysis/results/primary.json"], "after": []}]}
#
# Edges come from `after` and from one script's `outputs` appearing in another's `inputs`.
# Every top-level script must be listed exactly once. Without a manifest the old filename
# order is used and reported as such (papers started before 1.7.1 keep working).
def load_manifest(project: Path) -> tuple[list[dict] | None, list[str]]:
    project = Path(project)
    p = project / MANIFEST_REL
    if not p.is_file():
        return None, []
    data = _load_json(p)
    if not isinstance(data, dict) or data.get("schema") != 1 \
            or not isinstance(data.get("scripts"), list):
        return None, [f"{MANIFEST_REL}: must be {{\"schema\": 1, \"scripts\": [...]}}"]
    problems: list[str] = []
    entries: list[dict] = []
    top = {s.relative_to(project).as_posix() for s in analysis_scripts(project)}
    seen: set[str] = set()
    for i, e in enumerate(data["scripts"]):
        if not isinstance(e, dict) or not isinstance(e.get("path"), str):
            problems.append(f"{MANIFEST_REL} scripts[{i}]: needs a path")
            continue
        path = e["path"].replace("\\", "/")
        lists = {}
        for key in ("inputs", "outputs", "after"):
            v = e.get(key, [])
            if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
                problems.append(f"{MANIFEST_REL} {path}: {key} must be a list of paths")
                v = []
            lists[key] = [x.replace("\\", "/") for x in v]
        if path not in top:
            problems.append(f"{MANIFEST_REL}: {path} is not a top-level 03_analysis/code script")
        if path in seen:
            problems.append(f"{MANIFEST_REL}: {path} listed twice")
        seen.add(path)
        # 1.13.0: an entry that declares "inputs" (even []) is scoped precisely on a data change;
        # one without the key may read any data and is re-run whenever data change.
        entries.append({"path": path, **lists, "declares_inputs": "inputs" in e})
    for missing in sorted(top - seen):
        problems.append(f"{MANIFEST_REL}: {missing} is not listed (every top-level script must "
                        "be, so nothing runs in an undeclared order)")
    known = {e["path"] for e in entries}
    for e in entries:
        for a in e["after"]:
            if a not in known:
                problems.append(f"{MANIFEST_REL} {e['path']}: after names unlisted {a}")
    return (entries if not problems else None), problems


def ordered_scripts(project: Path) -> tuple[list[Path], str, list[str]]:
    """-> (scripts in execution order, "manifest" | "filename", problems)."""
    project = Path(project)
    entries, problems = load_manifest(project)
    if problems:
        return [], "manifest", problems
    if entries is None:
        return analysis_scripts(project), "filename", []
    producer = {o: e["path"] for e in entries for o in e["outputs"]}
    deps = {e["path"]: set(e["after"]) | {producer[i] for i in e["inputs"]
                                          if i in producer and producer[i] != e["path"]}
            for e in entries}
    order: list[str] = []
    done: set[str] = set()
    while len(order) < len(entries):
        ready = [e["path"] for e in entries if e["path"] not in done and deps[e["path"]] <= done]
        if not ready:
            stuck = sorted(p for p in deps if p not in done)
            return [], "manifest", [f"{MANIFEST_REL}: dependency cycle among {', '.join(stuck)}"]
        order.append(ready[0])
        done.add(ready[0])
    return [project / p for p in order], "manifest", []


def affected_scripts(project: Path, previous: dict) -> tuple[set[str] | None, list[str], str]:
    """Scripts a change since `previous` (the last passing report) can reach.

    -> (script paths to re-run, changed inputs, why) or (None, changed, why) for a full run.
    The closure comes from wfcore.dependencies (which widens on missing metadata), then flows
    downstream through the manifest's declared inputs. Anything that cannot be scoped safely
    falls back to a full run."""
    from . import dependencies
    project = Path(project)
    entries, problems = load_manifest(project)
    if entries is None or problems:
        return None, [], "no valid analysis_manifest.json; scoped re-run needs declared outputs"
    if not isinstance(previous, dict) or not previous.get("all_match"):
        return None, [], "no previous passing reproducibility report to carry results from"
    tp = project / TOLERANCE_REL
    if (sha256(tp) if tp.is_file() else None) != previous.get("tolerance_sha256"):
        return None, [], "the tolerance file changed"
    rec_engine = previous.get("engine_inputs")
    if isinstance(rec_engine, dict) and not helpers_match(rec_engine, engine_inputs(project)):
        return None, [], "an engine helper this paper's analysis uses changed"
    changed = changed_inputs(project, previous)
    prev_scripts = {s.get("path") for s in previous.get("scripts", []) if isinstance(s, dict)}
    cur_scripts = {e["path"] for e in entries}
    if not prev_scripts <= cur_scripts:
        return None, changed, "an analysis script was removed"
    added = cur_scripts - prev_scripts  # 1.13.0: a new script runs alone (plus its consumers)
    declared = {o for e in entries for o in e["outputs"]}
    results = {f"{RESULTS_DIR}/{p.name}" for p in (project / RESULTS_DIR).glob("*.json")} \
        if (project / RESULTS_DIR).is_dir() else set()
    undeclared = sorted(results - declared - {ACQ_RESULT})
    if undeclared:
        return None, changed, f"results not declared as any script's output: {undeclared[:3]}"
    if MANIFEST_REL in changed:
        old = previous.get("manifest_entries")
        if not isinstance(old, list):
            return set(cur_scripts), changed, "the manifest changed (older proof without entries)"
        old_by = {e.get("path"): e for e in old if isinstance(e, dict)}
        moved = {e["path"] for e in entries if e["path"] in old_by and
                 {k: e[k] for k in ("inputs", "outputs", "after")}
                 != {k: old_by[e["path"]].get(k, []) for k in ("inputs", "outputs", "after")}}
        added |= moved
    hit = set(added)
    data = [c for c in changed if c.startswith(("02_data/", DATASOURCE_PREFIX))]
    for c in data:
        for e in entries:
            if not e.get("declares_inputs", True) or any(
                    c == i or c.startswith(i.rstrip("/") + "/") for i in e["inputs"]):
                hit.add(e["path"])
    code = [c for c in changed if c.startswith("03_analysis/code/")]
    top = {e["path"] for e in entries}
    hit |= {c for c in code if c in top}
    for helper in (c for c in code if c not in top):
        users = helper_users(project, helper, sorted(top))
        if not users:
            reach = set(dependencies.closure(project, [helper]))
            users = {e["path"] for e in entries if e["path"] in reach or set(e["outputs"]) & reach}
        hit |= users
    grew = True
    while grew:
        produced = {o for e in entries if e["path"] in hit for o in e["outputs"]}
        more = {e["path"] for e in entries if e["path"] not in hit and set(e["inputs"]) & produced}
        grew = bool(more)
        hit |= more
    return hit, changed, ("scoped: new/changed scripts, the helpers' users, the scripts that "
                          "declare the changed data, and their consumers")


def helper_users(project: Path, helper: str, scripts: list[str]) -> set[str]:
    """1.13.0: top-level scripts that use a changed helper (by file name or module name),
    followed through helpers that use it in turn. Empty = unknown (caller widens)."""
    project = Path(project)
    code_dir = project / "03_analysis/code"
    helpers = [p.relative_to(project).as_posix() for p in code_dir.rglob("*")
               if p.is_file() and p.suffix.casefold() in (".py", ".r")
               and p.relative_to(project).as_posix() not in scripts] if code_dir.is_dir() else []

    def mentions(rel: str, target: str) -> bool:
        try:
            text = (project / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return False
        name, stem = Path(target).name, Path(target).stem
        return name in text or re.search(rf"(?<![\w-]){re.escape(stem)}(?![\w-])", text) is not None
    chain, frontier = {helper}, {helper}
    while frontier:
        nxt = {h for h in helpers if h not in chain and any(mentions(h, t) for t in frontier)}
        chain |= nxt
        frontier = nxt
    return {s for s in scripts if any(mentions(s, t) for t in chain)}


ENGINE_HELPERS_PY = "tools/analysis"
ENGINE_HELPERS_R = "tools/R"
_PY_HELPER_RE = re.compile(r"^\s*(?:from\s+analysis(?:\.(\w+))?\s+import\s+([\w\s,()*]+)|"
                           r"import\s+analysis\.(\w+))", re.M)
_R_HELPER_RE = re.compile(r"tools/R/([\w.-]+\.[Rr])\b")


def engine_inputs(project: Path | None = None) -> dict[str, str]:
    """SHA-256 of the engine helpers the paper's analysis scripts actually use (1.13.0).

    Python `from analysis.<m> import ...` / `import analysis.<m>` and R
    `source(.../tools/R/<f>.R)` in 03_analysis/code. Figure helpers (medfig.R, recipes.R) are
    never part of the analysis proof, and an engine release that leaves the used helpers
    byte-identical keeps the proof valid. Without a project: every analysis helper (legacy)."""
    from . import paths
    root = paths.repo_root()
    if project is None:
        files = sorted(list((root / ENGINE_HELPERS_R).glob("*.R"))
                       + [p for p in (root / ENGINE_HELPERS_PY).rglob("*.py")
                          if "__pycache__" not in p.parts])
    else:
        used: set[str] = set()
        code_dir = Path(project) / "03_analysis/code"
        for p in sorted(code_dir.rglob("*")) if code_dir.is_dir() else []:
            if not p.is_file() or p.suffix.casefold() not in (".py", ".r"):
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
            if p.suffix.casefold() == ".py":
                for mod, names, mod2 in _PY_HELPER_RE.findall(text):
                    cands = [mod or mod2] if (mod or mod2) else re.findall(r"\w+", names)
                    used |= {f"{ENGINE_HELPERS_PY}/{c}.py" for c in cands if c}
            else:
                used |= {f"{ENGINE_HELPERS_R}/{f}" for f in _R_HELPER_RE.findall(text)}
        files = [root / u for u in sorted(used) if (root / u).is_file()]
    return {p.relative_to(root).as_posix(): helper_sha256(p) for p in files if p.is_file()}


COMPAT_MARK = b"medpaper-compat"


def helper_sha256(path: Path) -> str:
    """1.14.0: the hash of a helper without its lines marked `medpaper-compat` - additions
    declared output-compatible (they only add environment.ci_level, which comparisons ignore),
    so a proof made with the previous helper stays valid and no paper re-runs for them."""
    data = Path(path).read_bytes()
    if COMPAT_MARK in data:
        data = b"".join(ln for ln in data.splitlines(keepends=True) if COMPAT_MARK not in ln)
    return hashlib.sha256(data).hexdigest()


def helpers_match(recorded: dict, current: dict) -> bool:
    """The helpers the paper uses now are byte-identical to the recorded ones (extra recorded
    helpers from an older, wider record are ignored)."""
    return all(recorded.get(k) == v for k, v in current.items())


def reuse_reason(project: Path, previous) -> tuple[bool, str]:
    """(True, why) when the previous passing proof still covers the paper exactly: the gate's
    own recomputation passes (scripts, manifest, data, tolerance, results and retained re-run
    hashes) and the engine helpers the paper uses are byte-identical to the recorded ones."""
    if not isinstance(previous, dict) or not previous.get("all_match"):
        return False, "no previous passing proof"
    rec = previous.get("engine_inputs")
    if not isinstance(rec, dict):
        return False, "the previous proof predates engine-helper hashes (1.9.1)"
    if not helpers_match(rec, engine_inputs(project)):
        return False, "an engine helper this paper's analysis uses changed since the proof"
    out = validate(project)
    if not out.ok:
        return False, out.problems[0] if out.problems else out.detail
    return True, ("scripts, manifest, data, tolerance, results and the engine helpers used are "
                  "identical to the passing proof of " + str(previous.get("generated_at", "?")))


def sandbox_inputs(project: Path) -> list[str]:
    """Analysis inputs: paper-relative paths plus `datasource:<name>/<file>` labels (1.13.0)."""
    from . import datasources
    project = Path(project)
    out: list[str] = []
    for tree in INPUT_TREES:
        base = project / tree
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            if p.is_file():
                rel = p.relative_to(project).as_posix()
                if counts_as_input(rel):
                    out.append(rel)
    if (project / TOLERANCE_REL).is_file():
        out.append(TOLERANCE_REL)
    if (project / MANIFEST_REL).is_file():
        out.append(MANIFEST_REL)
    out += [label for label, _p in datasources.files(project)]
    return sorted(set(out))


def input_path(project: Path, label: str) -> Path | None:
    from . import datasources
    if label.startswith(DATASOURCE_PREFIX):
        return datasources.resolve(project, label)
    return Path(project) / label


def input_sha(project: Path, label: str) -> str | None:
    """Hash of one input; data files use the size+mtime cache (never re-read GBs per gate)."""
    from . import datasources
    p = input_path(project, label)
    if p is None or not p.is_file():
        return None
    if label.startswith(("02_data/", DATASOURCE_PREFIX)):
        return datasources.cached_sha256(project, p)
    return sha256(p)


def input_hashes(project: Path) -> dict[str, str | None]:
    return {rel: input_sha(project, rel) for rel in sandbox_inputs(project)}


def changed_inputs(project: Path, report: dict) -> list[str]:
    """Inputs whose hash differs from the proof. Paths an older proof listed that are no
    longer inputs (documentation, acquisition code) are ignored."""
    rec = {i.get("path"): i.get("sha256") for i in report.get("inputs", []) if isinstance(i, dict)}
    cur = input_hashes(project)
    return sorted(r for r in set(rec) | set(cur) if r and r != TOLERANCE_REL
                  and (r in cur or counts_as_input(r)) and rec.get(r) != cur.get(r))


def next_step(project: Path) -> str:
    """1.13.0: the cheapest legal next command for the reproducibility proof (one line)."""
    project = Path(project)
    rp = project / REPORT_REL
    report = _load_json(rp) if rp.is_file() else None
    if not isinstance(report, dict) or not report.get("all_match"):
        return ("no passing proof yet: run `reproduce.py run --wait` once (full run); give the "
                "shell tool a long timeout, never kill it")
    ok, why = reuse_reason(project, report)
    if ok:
        return "the proof is valid by hash: nothing to run (never re-run reproduce.py to be safe)"
    scoped, changed, why2 = affected_scripts(project, report)
    entries = load_manifest(project)[0] or []
    if scoped is None:
        return f"re-run needed ({why2 or why}): `reproduce.py run --wait` (full)"
    if not scoped:
        return (f"{why}; no script is affected: `reproduce.py run --wait` only re-checks and "
                "records the proof")
    return (f"{len(changed)} analysis input(s) changed ({', '.join(changed[:3])}): "
            f"`reproduce.py run --wait` re-runs {len(scoped)} of {len(entries)} script(s) "
            "(affected only)")


def canonical(obj):
    """Parse-level copy without the volatile keys (top level, plus environment.written_at)."""
    if not isinstance(obj, dict):
        return obj
    out = {k: v for k, v in obj.items() if k not in VOLATILE_KEYS}
    env = out.get("environment")
    if isinstance(env, dict):
        # 1.14.0: environment.ci_level is a declaration the writer reads, not a result.
        out["environment"] = {k: v for k, v in env.items() if k not in ("written_at", "ci_level")}
    return out


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _integral(v) -> bool:
    return isinstance(v, int) or (isinstance(v, float) and math.isfinite(v) and v == int(v))


def first_difference(a, b, tol: Tol | None, path: str = "$", accepted: list | None = None):
    """First (path, a, b) where a and b differ, or None. Tolerance-only matches go to `accepted`."""
    if isinstance(a, dict) and isinstance(b, dict):
        ka, kb = set(a), set(b)
        if ka != kb:
            missing = sorted(ka - kb)
            extra = sorted(kb - ka)
            key = missing[0] if missing else extra[0]
            return (f"{path}.{key}", a.get(key, "<absent>"), b.get(key, "<absent>"))
        for k in sorted(a):
            d = first_difference(a[k], b[k], tol, f"{path}.{k}", accepted)
            if d:
                return d
        return None
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return (f"{path}.length", len(a), len(b))
        for i, (x, y) in enumerate(zip(a, b)):
            d = first_difference(x, y, tol, f"{path}[{i}]", accepted)
            if d:
                return d
        return None
    if _is_num(a) and _is_num(b):
        if a == b:
            return None
        if tol is not None and not (_integral(a) and _integral(b)):
            if abs(a - b) <= tol.abs + tol.rel * abs(b):
                if accepted is not None:
                    accepted.append((path, a, b))
                return None
        return (path, a, b)
    if a == b and type(a) is type(b):
        return None
    return (path, a, b)


def load_tolerances(project: Path) -> tuple[dict[str, Tol], list[str]]:
    p = Path(project) / TOLERANCE_REL
    if not p.is_file():
        return {}, []
    try:
        data = tomllib.loads(p.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        return {}, [f"{TOLERANCE_REL} is malformed: {exc}"]
    problems: list[str] = []
    unknown = sorted(set(data) - {"schema", "tolerance"})
    if unknown:
        problems.append(f"{TOLERANCE_REL}: unknown key(s) {unknown}")
    if data.get("schema") != 1:
        problems.append(f"{TOLERANCE_REL}: schema must be 1")
    out: dict[str, Tol] = {}
    for i, entry in enumerate(data.get("tolerance", [])):
        where = f"{TOLERANCE_REL} tolerance[{i}]"
        if not isinstance(entry, dict):
            problems.append(f"{where}: must be a table")
            continue
        extra = sorted(set(entry) - {"file", "abs", "rel", "reason"})
        if extra:
            problems.append(f"{where}: unknown key(s) {extra}")
        file = str(entry.get("file", ""))
        if not re.match(r"^03_analysis/results/[^/]+\.json$", file):
            problems.append(f"{where}: file must be a 03_analysis/results/*.json path")
        elif file == ACQ_RESULT:
            problems.append(f"{where}: dataset_summary.json can never carry a tolerance")
        elif not (Path(project) / file).is_file():
            problems.append(f"{where}: {file} does not exist")
        if file in out:
            problems.append(f"{where}: duplicate file {file}")
        reason = str(entry.get("reason", ""))
        if len(reason.strip()) < 40:
            problems.append(f"{where}: reason must explain the non-determinism (>= 40 chars)")
        try:
            a, r = float(entry.get("abs", 0.0)), float(entry.get("rel", 0.0))
        except (TypeError, ValueError):
            problems.append(f"{where}: abs/rel must be numbers")
            continue
        if not (math.isfinite(a) and math.isfinite(r)) or a < 0 or r < 0:
            problems.append(f"{where}: abs/rel must be finite and >= 0")
        elif a + r <= 0:
            problems.append(f"{where}: abs + rel must be > 0")
        elif a > TOL_ABS_MAX or r > TOL_REL_MAX:
            problems.append(f"{where}: tolerance above 1e-6 is refused; make the script "
                            "deterministic instead")
        out[file] = Tol(a, r, reason.strip())
    return (out if not problems else {}), problems


def _load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _env_script(obj) -> str:
    env = obj.get("environment") if isinstance(obj, dict) else None
    return str(env.get("script", "")) if isinstance(env, dict) else ""


def compare(project: Path, rerun_dir: Path, tols: dict[str, Tol]):
    """-> (entries, within_tolerance). Entries carry file, status, first_difference, values."""
    project = Path(project)
    cur = {p.name: p for p in sorted((project / RESULTS_DIR).glob("*.json"))} \
        if (project / RESULTS_DIR).is_dir() else {}
    ret = {p.name: p for p in sorted(Path(rerun_dir).glob("*.json"))} \
        if Path(rerun_dir).is_dir() else {}
    entries, within = [], []
    for name in sorted(set(cur) | set(ret)):
        rel = f"{RESULTS_DIR}/{name}"
        e = {"file": rel, "original_sha256": sha256(cur[name]) if name in cur else None,
             "rerun_sha256": sha256(ret[name]) if name in ret else None,
             "first_difference": None, "original_value": None, "rerun_value": None,
             "tolerance": None}
        orig = _load_json(cur[name]) if name in cur else None
        script = _env_script(orig)
        if name in cur and rel != ACQ_RESULT and script.startswith(ACQ_PREFIX):
            e["status"] = "acquisition_not_permitted"
        elif name in cur and rel == ACQ_RESULT and script.startswith(ACQ_PREFIX):
            again = _load_json(ret[name]) if name in ret else None
            if again is not None and canonical(again) == canonical(orig):
                e["status"] = "not_rerun_acquisition"
            else:
                e["status"] = "mismatch"
                e["first_difference"] = "$"
        elif name not in ret:
            e["status"] = "missing_in_rerun"
        elif name not in cur:
            e["status"] = "extra_in_rerun"
        else:
            again = _load_json(ret[name])
            tol = tols.get(rel)
            if tol:
                e["tolerance"] = {"abs": tol.abs, "rel": tol.rel}
            accepted: list = []
            d = first_difference(canonical(orig), canonical(again), tol, "$", accepted)
            if d is None:
                e["status"] = "match"
                within.extend({"file": rel, "path": p, "original_value": a, "rerun_value": b}
                              for p, a, b in accepted)
            else:
                e["status"] = "mismatch"
                e["first_difference"], e["original_value"], e["rerun_value"] = d
        entries.append(e)
    return entries, within


def validate(project: Path) -> Outcome:
    project = Path(project)
    problems: list[str] = []
    self_reported: list[str] = []
    rp = project / REPORT_REL
    if not rp.is_file():
        return Outcome(False, [f"{REPORT_REL} missing - run reproduce.py run"], "no proof")
    report = _load_json(rp)
    if not isinstance(report, dict) or report.get("schema") != 1:
        return Outcome(False, [f"{REPORT_REL} is not a schema-1 report"], "malformed report")
    started, generated = str(report.get("started_at", "")), str(report.get("generated_at", ""))
    if not (_ISO.match(started) and _ISO.match(generated)) or started > generated:
        problems.append("report timestamps are missing or out of order")

    tols, tol_problems = load_tolerances(project)
    problems.extend(tol_problems)
    tp = project / TOLERANCE_REL
    if (sha256(tp) if tp.is_file() else None) != report.get("tolerance_sha256"):
        problems.append(f"input changed since the proof: {TOLERANCE_REL}")

    for rel in changed_inputs(project, report):
        problems.append(f"input changed since the proof: {rel}")

    problems.extend(ordered_scripts(project)[2])
    reported_scripts = {s.get("path"): s for s in report.get("scripts", []) if isinstance(s, dict)}
    current_scripts = {s.relative_to(project).as_posix(): sha256(s)
                       for s in analysis_scripts(project)}
    if set(reported_scripts) != set(current_scripts):
        problems.append("analysis script set changed since the proof")
    for rel, sha in current_scripts.items():
        rec = reported_scripts.get(rel)
        if rec and rec.get("sha256") != sha:
            problems.append(f"input changed since the proof: {rel}")
    for rel, rec in reported_scripts.items():
        if rec.get("exit_code") not in (0, None) or rec.get("timed_out"):
            self_reported.append(f"{rel} exited {rec.get('exit_code')} "
                                 f"(timed_out={rec.get('timed_out')})")
    if report.get("failed_script"):
        self_reported.append(f"failed script: {report['failed_script']}")
    if report.get("paper_changes"):
        self_reported.append("the original paper changed during the run: "
                             + ", ".join(report["paper_changes"][:5]))

    rerun = project / RERUN_DIR
    carried = report.get("carried_results") if isinstance(report.get("carried_results"),
                                                          dict) else {}
    rep_results = {r.get("file"): r for r in report.get("results", []) if isinstance(r, dict)}
    cur_files = {f"{RESULTS_DIR}/{p.name}": sha256(p)
                 for p in sorted((project / RESULTS_DIR).glob("*.json"))} \
        if (project / RESULTS_DIR).is_dir() else {}
    rep_orig = {f: r.get("original_sha256") for f, r in rep_results.items()
                if r.get("original_sha256")}
    if set(rep_orig) != set(cur_files):
        problems.append("results set changed since the proof: "
                        + ", ".join(sorted(set(rep_orig) ^ set(cur_files))[:5]))
    for f, sha in cur_files.items():
        if f in rep_orig and rep_orig[f] != sha:
            problems.append(f"results file changed since the proof: {f}")
    ret_files = {f"{RESULTS_DIR}/{p.name}": sha256(p) for p in sorted(rerun.glob("*.json"))} \
        if rerun.is_dir() else {}
    rep_rerun = {f: r.get("rerun_sha256") for f, r in rep_results.items() if r.get("rerun_sha256")}
    for f in sorted(set(rep_rerun) | set(ret_files)):
        if rep_rerun.get(f) != ret_files.get(f):
            problems.append(f"retained re-run evidence missing or edited: {f}")
    for p in sorted(rerun.glob("*.json")) if rerun.is_dir() else []:
        f = f"{RESULTS_DIR}/{p.name}"
        if f == ACQ_RESULT:
            continue
        obj = _load_json(p)
        env = obj.get("environment") if isinstance(obj, dict) else None
        wa = str(env.get("written_at", "")) if isinstance(env, dict) else ""
        win = carried.get(f)
        lo, hi = (str(win.get("started_at", "")), str(win.get("generated_at", ""))) \
            if isinstance(win, dict) else (started, generated)
        if win is not None and not (_ISO.match(lo) and _ISO.match(hi) and hi <= started):
            problems.append(f"carried re-run of {f} has no valid earlier proof window")
        elif not (_ISO.match(wa) and lo <= wa <= hi):
            problems.append(f"retained re-run of {f} was not written by this run"
                            + (" or the earlier proof it was carried from" if win else ""))

    entries, _within = compare(project, rerun, tols)
    for e in entries:
        status = e["status"]
        if status != "match" and status != "not_rerun_acquisition":
            if status == "mismatch":
                problems.append(f"{e['file']} differs at {e['first_difference']}: "
                                f"{e['original_value']!r} vs {e['rerun_value']!r}")
            else:
                problems.append(f"{e['file']}: {status}")
        claimed = rep_results.get(e["file"], {}).get("status")
        if claimed is not None and claimed != status:
            how = (f"differs at {e['first_difference']}" if status == "mismatch" else status)
            problems.append(f"report claims {claimed} for {e['file']} but the retained re-run "
                            f"{how}")
    real = list(dict.fromkeys(problems))
    if bool(report.get("all_match")) != (not real and not self_reported):
        real.append("report all_match disagrees with the recomputed verdict")
    allp = real + [f"(self-reported) {s}" for s in self_reported]
    if allp:
        return Outcome(False, allp, "; ".join(allp[:8]))
    n = len([e for e in entries if e["status"] == "match"])
    return Outcome(True, [], f"{len(current_scripts)} script(s) re-executed; {n} results file(s) "
                             f"identical{', tolerances active' if tols else ''}")
