"""Filesystem / structural checks: existence, placement, discipline."""
from __future__ import annotations

import ast
import fnmatch
import json
import re

from . import Ctx, Result, check


@check("outputs_exist")
def outputs_exist(ctx: Ctx) -> Result:
    optional = set(ctx.spec.get("optional", []))
    missing, empty, optional_present = [], [], 0
    for declared in ctx.stage.outputs:
        # A journal-variable output (title page, statements) is written into the journal variant
        # once one is open, so look for it where it actually belongs. Identity transform before
        # the scientific freeze exists.
        rel = ctx.src(declared)
        p = ctx.p(rel)
        if not p.exists():
            if declared not in optional:
                missing.append(rel if rel == declared else f"{rel} (declared {declared})")
        elif p.is_file() and p.stat().st_size == 0:
            empty.append(rel)
        elif declared in optional:
            optional_present += 1
    if missing or empty:
        bits = []
        if missing:
            bits.append("missing: " + ", ".join(missing))
        if empty:
            bits.append("empty: " + ", ".join(empty))
        return Result(
            False,
            "outputs_exist",
            "; ".join(bits),
            [f"Create each declared output under project/. Stage {ctx.stage.id} declares {len(ctx.stage.outputs)}."],
        )
    required = len(ctx.stage.outputs) - len(optional)
    detail = f"{required} required output(s) present"
    if optional:
        detail += f"; {optional_present}/{len(optional)} optional output(s) present"
    return Result(True, "outputs_exist", detail)


@check("no_future_artifacts")
def no_future_artifacts(ctx: Ctx) -> Result:
    """Enforce 'one thing at a time': later stages' outputs must not exist yet."""
    offenders = []
    for st in ctx.pipeline.stages_after(ctx.stage.id):
        if ctx.state.is_done(st.id):
            continue
        for rel in st.outputs:
            if ctx.p(rel).exists():
                offenders.append(f"{rel} (belongs to {st.id})")
    if offenders:
        return Result(
            False,
            "no_future_artifacts",
            "produced ahead of schedule: " + "; ".join(offenders[:8]),
            ["Delete these and produce them in their own stage. Running ahead is how the workflow drifts."],
        )
    return Result(True, "no_future_artifacts", "nothing produced ahead of schedule")


@check("single_section_written")
def single_section_written(ctx: Ctx) -> Result:
    """A manuscript stage may add only its own declared manuscript file(s)."""
    # 1.12.0 (A1): judged only for the stage being advanced. Re-checking a finished stage (or
    # any stage other than the active one) sees later stages' legitimate files and used to
    # fail for that reason alone.
    if ctx.stage.id != ctx.state.current or ctx.state.is_done(ctx.stage.id):
        return Result(True, "single_section_written",
                      f"{ctx.stage.id} is not the active stage; judged only when it is advanced")
    manuscript_stages = [
        s for s in ctx.pipeline.stages
        if any(o.startswith("07_manuscript/") and o.endswith(".md") for o in s.outputs)
    ]
    # An output declared by a stage that genuinely finished is owned by that stage, even when a
    # later stage declares the same path. `07_manuscript/statements.md` is the live case: S17
    # writes the optional abbreviation list and S21 fills in the administrative statements, so
    # after a rewind past S17 the file is finished work, not S21 running ahead.
    already_owned = {
        rel
        for st in ctx.pipeline.stages
        if ctx.state.was_completed(st.id) or ctx.state.is_done(st.id)
        for rel in st.outputs
    }
    unexpected = []
    for st in manuscript_stages:
        if st.index <= ctx.stage.index or ctx.state.is_done(st.id):
            continue
        # A stage that was completed and then rewound past by `wf loop` is not running ahead.
        # `loop` leaves downstream artifacts in place on purpose, so flagging them here would
        # make the gate satisfiable only by deleting finished work.
        if ctx.state.was_completed(st.id):
            continue
        for rel in st.outputs:
            if rel.startswith("07_manuscript/") and rel not in already_owned and ctx.p(rel).exists():
                unexpected.append(f"{rel} (stage {st.id})")
    if unexpected:
        return Result(
            False,
            "single_section_written",
            "manuscript file(s) from a future stage exist: " + "; ".join(unexpected),
            ["Write only the active stage's manuscript file(s). Remove the premature file(s)."],
        )
    return Result(True, "single_section_written", "only active-stage manuscript file(s) were written")


@check("file_count")
def file_count(ctx: Ctx) -> Result:
    pattern = ctx.spec["glob"]
    lo = ctx.spec.get("min")
    hi = ctx.spec.get("max")
    n = len(ctx.glob(pattern))
    if lo is not None and n < lo:
        return Result(False, "file_count", f"{pattern}: found {n}, need >= {lo}")
    if hi is not None and n > hi:
        return Result(False, "file_count", f"{pattern}: found {n}, allowed <= {hi}")
    return Result(True, "file_count", f"{pattern}: {n} file(s)")


@check("temp_clean")
def temp_clean(ctx: Ctx) -> Result:
    tmp = ctx.project / ctx.pipeline.layout.get("temp_dir", "temp")
    if not tmp.exists():
        return Result(True, "temp_clean", "no temp dir")
    # 1.12.0 (C4): temp/logs/ is a log directory (--log, reproduce --log, --wait), not scratch.
    logs = tmp / "logs"
    leftovers = [p for p in tmp.rglob("*") if p.is_file() and p.name != ".gitkeep"
                 and logs not in p.parents]
    if leftovers:
        names = ", ".join(p.name for p in leftovers[:8])
        return Result(
            False,
            "temp_clean",
            f"{len(leftovers)} leftover scratch file(s): {names}",
            ["Delete scratch files before advancing:  .venv/Scripts/python.exe tools/wf.py clean --apply"],
        )
    return Result(True, "temp_clean", "scratch dir empty")


@check("no_orphans")
def no_orphans(ctx: Ctx) -> Result:
    declared = ctx.pipeline.all_declared_outputs()
    free = ctx.pipeline.freeform
    always = ctx.pipeline.policy.get("always_allowed", [])
    from .. import paths as _paths
    users = _paths.user_files(ctx.project)  # 1.13.0: the user's own files from before `wf init`
    foreign = _paths.foreign_prefixes(ctx.project)  # 1.14.1: older attempts, restart archive
    orphans = []
    for p in ctx.project.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(ctx.project).as_posix()
        if rel.startswith(foreign):
            continue
        # Archived journal variants/packages are kept on purpose (a rejected journal's work).
        if rel.startswith("08_submission/journal_archives/"):
            continue
        if rel in declared or rel in users:
            continue
        if any(fnmatch.fnmatch(rel, g) for g in free + always):
            continue
        orphans.append(rel)
    if orphans:
        return Result(
            False,
            "no_orphans",
            f"{len(orphans)} undeclared file(s): " + ", ".join(orphans[:10]),
            [
                "Either delete them, or declare them in pipeline.toml (stage outputs / [freeform].globs).",
                "Run `.venv/Scripts/python.exe tools/wf.py clean` to review.",
            ],
            severity=ctx.spec.get("severity", "fail"),
        )
    return Result(True, "no_orphans", "every file is accounted for")


@check("json_keys")
def json_keys(ctx: Ctx) -> Result:
    rel = ctx.spec["path"]
    if not ctx.p(rel).exists():
        return Result(False, "json_keys", f"{rel} missing")
    try:
        data = ctx.read_json(rel)
    except json.JSONDecodeError as exc:
        return Result(False, "json_keys", f"{rel} is not valid JSON: {exc}")
    if not isinstance(data, dict):
        return Result(False, "json_keys", f"{rel} must be a JSON object")
    required = ctx.spec.get("keys", [])
    missing = [k for k in required if k not in data]
    blank = [k for k in required if k in data and data[k] in (None, "", [], {})]
    if missing or blank:
        bits = []
        if missing:
            bits.append("absent: " + ", ".join(missing))
        if blank:
            bits.append("empty: " + ", ".join(blank))
        return Result(False, "json_keys", f"{rel} -> " + "; ".join(bits))
    return Result(True, "json_keys", f"{rel}: {len(required)} required key(s) populated")


def _python_script_scope(text: str) -> tuple[bool, list[str]]:
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return False, [f"cannot parse Python: {exc}"]
    calls_project_dir = any(
        isinstance(node, ast.Call)
        and ((isinstance(node.func, ast.Name) and node.func.id == "project_dir")
             or (isinstance(node.func, ast.Attribute) and node.func.attr == "project_dir"))
        for node in ast.walk(tree))
    reads_env = any(
        isinstance(node, ast.Constant) and node.value == "MEDPAPER_PROJECT"
        for node in ast.walk(tree)) or any(
        isinstance(node, ast.ImportFrom) and node.module == "analysis.results"
        for node in ast.walk(tree))
    bad_literals = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        value = node.value.strip().replace("\\", "/")
        if value == "project" or value.startswith("project/"):
            bad_literals.append(node.value)
    return bool(calls_project_dir or reads_env), bad_literals


_R_HELPER_SOURCE = re.compile(
    r"source\s*\(\s*file\.path\s*\(\s*Sys\.getenv\s*\(\s*['\"]MEDPAPER_ROOT['\"]\s*\)\s*,\s*"
    r"['\"]tools/(?:figures/R/(?:medfig|recipes)|R/medresults|R/medsources)\.R['\"]")
_R_JSON_WRITE = re.compile(
    r"(?<![\w.])(?:jsonlite::|RJSONIO::|rjson::)?(?:toJSON|write_json)\s*\(")
_ABS_PATH = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\[^\\\s]|~[\\/]|/(?:[^/\s\"']+/)+)")
ENGINE_PACKAGES = ("analysis", "figures", "tables", "wfcore", "pubmed", "manuscript", "text",
                   "hooks")
SCRIPT_DIRS = ("02_data/acquisition", "03_analysis/code", "04_tables/code", "05_figures/code")
_RERUN_DIRS = ("03_analysis/code/", "04_tables/code/", "05_figures/code/")


def _r_script_scope(text: str) -> tuple[bool, list[str]]:
    code = re.sub(r"(?m)#.*$", "", text)
    scoped = bool(re.search(r"Sys\.getenv\s*\(\s*['\"]MEDPAPER_PROJECT['\"]", code)
                  or _R_HELPER_SOURCE.search(code))
    bad = re.findall(r"['\"]project(?:[/\\][^'\"]*)?['\"]", code, re.I)
    return scoped, bad


def _absolute_literals(strings: list[str]) -> list[str]:
    out = []
    for s in strings:
        v = s.strip()
        if re.match(r"^[a-z][a-z0-9+.-]*://", v, re.I):
            continue
        if _ABS_PATH.match(v):
            out.append(v)
    return out


@check("paper_scripts_scoped")
def paper_scripts_scoped(ctx: Ctx) -> Result:
    """Paper-authored code must resolve its own paper root and never write into the engine.

    `wf run-script` exports MEDPAPER_PROJECT and puts tools/ on PYTHONPATH. Requiring the script
    to consume that root makes direct invocation fail closed rather than quietly writing into
    whichever directory happens to be current.
    """
    patterns = ctx.spec.get("patterns") or [
        "02_data/acquisition/**/*.py", "02_data/acquisition/**/*.R", "02_data/acquisition/**/*.r",
        "03_analysis/code/**/*.py", "03_analysis/code/**/*.R", "03_analysis/code/**/*.r",
        "04_tables/code/**/*.py", "04_tables/code/**/*.R", "04_tables/code/**/*.r",
        "05_figures/code/**/*.py", "05_figures/code/**/*.R", "05_figures/code/**/*.r",
    ]
    from ..codescan import scan_py, scan_r
    files = sorted({p for pattern in patterns for p in ctx.project.glob(pattern) if p.is_file()})
    problems = []
    # A paper package or module named like an engine package sits on sys.path[0] and shadows it.
    for sdir in SCRIPT_DIRS:
        base = ctx.project / sdir
        if not base.is_dir():
            continue
        for child in sorted(base.iterdir()):
            stem = child.name if child.is_dir() else child.stem
            if (child.is_dir() or child.suffix.casefold() == ".py") and \
                    stem.casefold() in ENGINE_PACKAGES:
                problems.append(f"{child.relative_to(ctx.project).as_posix()}: shadows the engine "
                                f"package {stem.casefold()}; rename it")
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        rel = path.relative_to(ctx.project).as_posix()
        suffix = path.suffix.casefold()
        if suffix == ".py":
            consumes_root, bad_literals = _python_script_scope(text)
            _code, strings = scan_py(text)
        elif suffix == ".r":
            consumes_root, bad_literals = _r_script_scope(text)
            code, strings = scan_r(text)
            if _R_JSON_WRITE.search(code):
                problems.append(f"{rel}: writes JSON directly (toJSON/write_json); use "
                                "write_results() from tools/R/medresults.R")
        else:
            problems.append(f"{rel}: unsupported script type")
            continue
        if not consumes_root:
            problems.append(
                f"{rel}: never resolves the active paper (use MEDPAPER_PROJECT or "
                "wfcore.paths.project_dir())")
        if bad_literals:
            problems.append(
                f"{rel}: literal project/ path(s) are forbidden: "
                + ", ".join(repr(x) for x in bad_literals[:3]))
        if rel.startswith(_RERUN_DIRS):
            absolute = _absolute_literals(strings)
            if absolute:
                problems.append(f"{rel}: absolute path literal(s) are forbidden: "
                                + ", ".join(repr(x) for x in absolute[:3])
                                + "; build paths from MEDPAPER_PROJECT / project_dir(), and read "
                                "the user's dataset in place with source_path('<name>') "
                                "(`wf data add <path>`; never copy it into the paper)")
    if problems:
        hints = ["Run paper code with: .venv/Scripts/python.exe tools/wf.py run-script "
                 "<paper-relative-script.py|.R>",
                 "Python: `from wfcore.paths import project_dir; PROJECT = project_dir()`",
                 "R: `PROJECT <- Sys.getenv(\"MEDPAPER_PROJECT\")` and stop if it is empty, or "
                 "source tools/R/medresults.R / tools/figures/R/medfig.R via MEDPAPER_ROOT.",
                 "Never use a literal project/ path or assume the current working directory is the paper."]
        return Result(False, "paper_scripts_scoped", "; ".join(problems[:8]), hints,
                      severity="fail")
    return Result(True, "paper_scripts_scoped",
                  f"{len(files)} paper-owned script(s) resolve the active paper root")
