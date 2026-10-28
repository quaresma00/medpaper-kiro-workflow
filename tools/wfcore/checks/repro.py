"""Environment receipts and analysis re-execution gates."""
from __future__ import annotations

import hashlib
import json
import re

from . import Ctx, Result, check
from .. import reproproof

_ISO = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
_SHA = re.compile(r"^[0-9a-f]{64}$")


def _env_problems(ctx: Ctx, rel: str, data) -> list[str]:
    if not isinstance(data, dict):
        return [f"{rel}: not a JSON object"]
    env = data.get("environment")
    if not isinstance(env, dict):
        return [f"{rel}: no environment receipt (write it with write_results())"]
    out = []
    if env.get("schema") != 1:
        out.append(f"{rel}: environment.schema must be 1")
    if env.get("language") not in ("python", "R"):
        out.append(f"{rel}: environment.language must be python or R")
    if not isinstance(env.get("version"), str) or not env.get("version"):
        out.append(f"{rel}: environment.version missing")
    pk = env.get("packages")
    if not isinstance(pk, dict) or not all(isinstance(k, str) and isinstance(v, str)
                                           for k, v in pk.items()):
        out.append(f"{rel}: environment.packages must map names to version strings")
    seed = env.get("seed")
    if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int)):
        out.append(f"{rel}: environment.seed must be an integer or null")
    script = env.get("script")
    if not isinstance(script, str) or not script or script.startswith("/") or ".." in \
            script.split("/") or "\\" in script:
        out.append(f"{rel}: environment.script must be a paper-relative POSIX path")
        return out
    top = script.startswith("03_analysis/code/") and "/" not in script[len("03_analysis/code/"):]
    acq = script.startswith(reproproof.ACQ_PREFIX) and rel.endswith("/dataset_summary.json")
    if not (top or acq):
        out.append(f"{rel}: environment.script {script} is not a top-level 03_analysis/code "
                   "script" + ("" if not script.startswith(reproproof.ACQ_PREFIX) else
                               " (acquisition may write only dataset_summary.json)"))
    p = ctx.project / script
    if not p.is_file():
        out.append(f"{rel}: environment.script {script} does not exist")
    else:
        sha = hashlib.sha256(p.read_bytes()).hexdigest()
        if not isinstance(env.get("script_sha256"), str) or not _SHA.match(env["script_sha256"]):
            out.append(f"{rel}: environment.script_sha256 malformed")
        elif sha != env["script_sha256"]:
            out.append(f"{rel}: {script} changed after it wrote these results; re-run it")
    if not isinstance(env.get("written_at"), str) or not _ISO.match(env["written_at"]):
        out.append(f"{rel}: environment.written_at must be UTC ISO-8601 (YYYY-MM-DDTHH:MM:SSZ)")
    return out


@check("results_have_environment")
def results_have_environment(ctx: Ctx) -> Result:
    files = ctx.glob("03_analysis/results/*.json")
    problems: list[str] = []
    for p in files:
        rel = p.relative_to(ctx.project).as_posix()
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            problems.append(f"{rel}: not valid JSON ({exc})")
            continue
        problems.extend(_env_problems(ctx, rel, data))
    if problems:
        return Result(False, "results_have_environment", "; ".join(problems[:8]),
                      ["Write results only with write_results(): Python "
                       "`from analysis.results import write_results, set_seed`, R "
                       "`source(file.path(Sys.getenv(\"MEDPAPER_ROOT\"), \"tools/R/medresults.R\"))`.",
                       "Run the top-level script with: .venv/Scripts/python.exe tools/wf.py "
                       "run-script 03_analysis/code/<script>"])
    return Result(True, "results_have_environment",
                  f"{len(files)} results file(s) carry a valid environment receipt")


@check("analysis_reproduces")
def analysis_reproduces(ctx: Ctx) -> Result:
    outcome = reproproof.validate(ctx.project)
    if outcome.ok:
        # 1.13.0: checked by hash - the proof is reused, nothing is re-executed here.
        return Result(True, "analysis_reproduces",
                      outcome.detail + "; valid by hash - nothing to re-run")
    try:
        nxt = reproproof.next_step(ctx.project)
    except Exception as exc:  # noqa: BLE001 - the hint must never break the gate
        nxt = f"reproduce.py run --wait ({type(exc).__name__} while scoping)"
    return Result(False, "analysis_reproduces", outcome.detail,
                  [f"Cheapest next step: {nxt}",
                   "Make scripts deterministic (seed every RNG via set_seed()/medpaper_seed()), "
                   "or declare a justified tolerance (<= 1e-6) in 03_analysis/reproducibility.toml"])
