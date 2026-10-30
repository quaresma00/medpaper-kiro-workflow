"""Write 03_analysis/results/<name>.json with an environment receipt.

    from analysis.results import set_seed, write_results
    set_seed(20240917)
    write_results("primary", {"hr": 1.87432198765, "n": 1284})

Run the script with `wf run-script 03_analysis/code/01_primary.py`. The receipt records the
interpreter, the imported packages, the seed, the script and its sha256, so
`results_have_environment` can prove which code produced the numbers and S06 can re-execute
it. The receipt's own numbers never count as provenance for manuscript numbers.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import random
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from wfcore import paths

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,80}$")
ENGINE_PACKAGES = {"wfcore", "analysis", "figures", "tables", "pubmed", "manuscript", "text",
                   "hooks"}
WRITER = "tools/analysis/results.py"
CI_LEVEL_DEFAULT = 0.95  # medpaper-compat 1.14.0: the declared CI level (set payload 'ci_level' for another)
_SEED: int | None = None


def proportion(numerator: int, denominator: int, population: str, decimals: int = 1) -> dict:
    """1.11.0 (#3c): a percentage with its numerator, denominator and population key.

    Store it inside write_results(); the proportion_denominators gate traces every body
    percentage to such a record and flags two proportions compared in one sentence whose
    population keys differ ("women 64% of cases" vs "36% of all reports").
    """
    if not isinstance(population, str) or not population.strip():
        raise ValueError("population must name the denominator definition, e.g. 'all_cases'")
    if int(denominator) <= 0 or not 0 <= int(numerator) <= int(denominator):
        raise ValueError("need 0 <= numerator <= denominator, denominator > 0")
    return {"numerator": int(numerator), "denominator": int(denominator),
            "percent": round(100.0 * int(numerator) / int(denominator), decimals),
            "population": population.strip()}


def set_seed(seed: int) -> int:
    """Seed `random` and numpy's legacy global RNG; remembered for the receipt."""
    global _SEED
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an int")
    random.seed(seed)
    try:
        import numpy
        numpy.random.seed(seed % (2 ** 32))
    except ImportError:
        pass
    _SEED = seed
    return seed


def _jsonable(obj):
    if hasattr(obj, "item") and callable(obj.item):
        try:
            return obj.item()
        except (TypeError, ValueError):
            pass
    if hasattr(obj, "tolist") and callable(obj.tolist):
        return obj.tolist()
    raise TypeError(f"cannot serialise {type(obj).__name__}; convert it to a number, string, "
                    f"list or dict")


def _check_finite(obj, where: str = "$") -> None:
    if isinstance(obj, float) and not math.isfinite(obj):
        raise ValueError(f"{where} is {obj}; replace with None")
    if isinstance(obj, dict):
        for k, v in obj.items():
            _check_finite(v, f"{where}.{k}")
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            _check_finite(v, f"{where}[{i}]")


def _packages() -> dict[str, str]:
    import importlib.metadata as md
    try:
        mapping = md.packages_distributions()
    except Exception:  # noqa: BLE001
        mapping = {}
    out: dict[str, str] = {}
    stdlib = set(getattr(sys, "stdlib_module_names", ()))
    for name in list(sys.modules):
        top = name.split(".")[0]
        if not top or top.startswith("_") or top in stdlib or top in ENGINE_PACKAGES:
            continue
        for dist in mapping.get(top, []):
            try:
                out[dist] = md.version(dist)
            except md.PackageNotFoundError:
                continue
    return dict(sorted(out.items()))


def _calling_script() -> Path:
    main = sys.modules.get("__main__")
    f = getattr(main, "__file__", None)
    if not f:
        raise RuntimeError("write_results must run from a paper script via wf run-script")
    return Path(f).resolve()


def write_results(name: str, payload: dict, seed: int | None = None) -> Path:
    if not isinstance(name, str):
        raise ValueError("name must be a string")
    name = name[:-5] if name.endswith(".json") else name
    if not NAME_RE.match(name):
        raise ValueError(f"invalid results name {name!r}")
    if not isinstance(payload, dict) or not all(isinstance(k, str) for k in payload):
        raise ValueError("payload must be a dict with string keys")
    if "environment" in payload:
        raise ValueError("payload must not carry a top-level 'environment'; the writer adds it")
    if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int)):
        raise ValueError("seed must be an int or None")
    seed = _SEED if seed is None else seed
    script = _calling_script()
    paper = paths.project_dir().resolve()
    try:
        rel = script.relative_to(paper).as_posix()
    except ValueError as exc:
        raise ValueError(f"the calling script {script} is not inside the paper {paper}") from exc
    if rel.startswith("03_analysis/code/"):
        if script.parent != paper / "03_analysis" / "code":
            raise ValueError("only top-level 03_analysis/code scripts may write results; "
                             "helpers go in subdirectories")
        if len(sys.argv) > 1:
            raise ValueError("S06 re-runs scripts without arguments; put parameters in the script")
    elif rel.startswith("02_data/acquisition/"):
        if name != "dataset_summary":
            raise ValueError("acquisition writes raw files verbatim; analysis results come from "
                             "03_analysis/code")
    else:
        raise ValueError("write_results may be called only from 03_analysis/code/ or "
                         "02_data/acquisition/ scripts")
    _check_finite(payload)
    env = {
        "schema": 1,
        "language": "python",
        "version": platform.python_version(),
        "packages": _packages(),
        "seed": seed,
        "script": rel,
        "script_sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
        "written_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "writer": WRITER,
    }
    env["ci_level"] = payload.get("ci_level", CI_LEVEL_DEFAULT)  # medpaper-compat 1.14.0: writer bundle reads it
    text = json.dumps({**payload, "environment": env}, indent=2, ensure_ascii=False,
                      allow_nan=False, default=_jsonable)
    out = paths.paper_output_path(f"project/03_analysis/results/{name}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    try:
        tmp.write_text(text + "\n", encoding="utf-8")
        os.replace(tmp, out)
    finally:
        tmp.unlink(missing_ok=True)
    return out


def baseline_counts(rows, variables: list[str], group: str | None = None) -> dict:
    """Counts for EVERY level of each categorical variable (1.9.0) - both categories of a
    binary one - overall and per group, missing counted separately. `rows` is a pandas
    DataFrame or a list of dicts. Put the result into write_results() so a journal's "M/F"
    or "yes/no" layout has both numbers with provenance."""
    records = rows.to_dict("records") if hasattr(rows, "to_dict") else list(rows)

    def missing(v) -> bool:
        return v is None or (isinstance(v, float) and v != v)
    groups = {"overall": records}
    if group:
        for key in sorted({str(r.get(group)) for r in records if not missing(r.get(group))}):
            groups[key] = [r for r in records if not missing(r.get(group)) and str(r.get(group)) == key]
    out: dict = {}
    for var in variables:
        values = [r.get(var) for r in records]
        levels = sorted({str(v) for v in values if not missing(v)})
        if set(levels) <= {"True", "False"}:
            levels = ["False", "True"]
        elif set(levels) <= {"0", "1"}:
            levels = ["0", "1"]
        out[var] = {}
        for name, rs in groups.items():
            n = len(rs)
            out[var][name] = {
                "denominator": n,
                "missing": sum(1 for r in rs if missing(r.get(var))),
                "levels": {lv: {"n": (k := sum(1 for r in rs if not missing(r.get(var))
                                               and str(r.get(var)) == lv)),
                                "pct": (100.0 * k / n) if n else None} for lv in levels},
            }
    return out
