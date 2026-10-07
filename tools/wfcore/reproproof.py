"""Reproducibility proof: what S06 re-executes and how the gate re-checks it. Stdlib only.

`tools/reproduce.py run` copies exactly `sandbox_inputs()` into a sandbox, re-runs every
top-level 03_analysis/code script, keeps the re-run results in `.wf/repro/rerun/` and writes
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
VOLATILE_KEYS = frozenset({"run_at", "built_at", "generated_at", "timestamp", "timestamps",
                           "written_at"})
ACQ_PREFIX = "02_data/acquisition/"
ACQ_RESULT = "03_analysis/results/dataset_summary.json"
TOL_ABS_MAX = 1e-6
TOL_REL_MAX = 1e-6
INPUT_TREES = ("02_data", "03_analysis/code")
RERUN_DIR = ".wf/repro/rerun"
SNAPSHOT_EXCLUDE = (".wf", "temp", ".kiro", REPORT_REL)
INPUT_EXCLUDE_DIRS = ("02_data/derived",)
INPUT_EXCLUDE_NAMES = ("__pycache__", ".Rhistory", ".DS_Store")
RESULTS_DIR = "03_analysis/results"
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


def analysis_scripts(project: Path) -> list[Path]:
    code = Path(project) / "03_analysis" / "code"
    if not code.is_dir():
        return []
    return sorted((p for p in code.iterdir()
                   if p.is_file() and p.suffix.casefold() in (".py", ".r")),
                  key=lambda p: p.name.casefold())


def sandbox_inputs(project: Path) -> list[str]:
    project = Path(project)
    out: list[str] = []
    for tree in INPUT_TREES:
        base = project / tree
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            if not p.is_file():
                continue
            rel = p.relative_to(project).as_posix()
            if any(rel == d or rel.startswith(d + "/") for d in INPUT_EXCLUDE_DIRS):
                continue
            if any(part in INPUT_EXCLUDE_NAMES for part in p.relative_to(project).parts):
                continue
            if p.suffix in (".pyc", ".pyo"):
                continue
            out.append(rel)
    if (project / TOLERANCE_REL).is_file():
        out.append(TOLERANCE_REL)
    return sorted(set(out))


def canonical(obj):
    """Parse-level copy without the volatile keys (top level, plus environment.written_at)."""
    if not isinstance(obj, dict):
        return obj
    out = {k: v for k, v in obj.items() if k not in VOLATILE_KEYS}
    env = out.get("environment")
    if isinstance(env, dict):
        out["environment"] = {k: v for k, v in env.items() if k != "written_at"}
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

    reported_inputs = {i.get("path"): i.get("sha256") for i in report.get("inputs", [])
                       if isinstance(i, dict)}
    current_inputs = {rel: sha256(project / rel) for rel in sandbox_inputs(project)}
    for rel in sorted(set(reported_inputs) | set(current_inputs)):
        if rel == TOLERANCE_REL:
            continue
        if reported_inputs.get(rel) != current_inputs.get(rel):
            problems.append(f"input changed since the proof: {rel}")

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
        if not (_ISO.match(wa) and started <= wa <= generated):
            problems.append(f"retained re-run of {f} was not written by this run")

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
