"""Gate runner: turns declarative gate specs into pass/fail results."""
from __future__ import annotations

from pathlib import Path

from . import checks, scifreeze
from .checks import Ctx, Result

# Gate specs are written against 07_manuscript/. Once the scientific record is frozen at S19 and
# a journal variant is opened, the files a journal legitimately alters live under
# 08_submission/manuscript/, and a gate asking "does the submitted manuscript meet the word cap"
# must read that copy. Rewriting the spec here keeps that in one place instead of duplicating
# every path in pipeline.toml, and it is the identity transform until a variant exists - so
# projects that predate the freeze are unaffected.
_PATH_KEYS = ("path", "paths")


def _resolve_manuscript_paths(spec: dict, project: Path) -> dict:
    if not scifreeze.variant_exists(project):
        return spec
    if not any(k in spec for k in _PATH_KEYS):
        return spec
    out = dict(spec)
    if isinstance(out.get("path"), str):
        out["path"] = scifreeze.resolve(project, out["path"])
    if isinstance(out.get("paths"), list):
        out["paths"] = [scifreeze.resolve(project, p) if isinstance(p, str) else p
                        for p in out["paths"]]
    return out


def run_stage(pipeline, state, project: Path, stage) -> list[Result]:
    checks.load_all()
    results: list[Result] = []
    if not stage.gate:
        results.append(Result(True, "-", "stage declares no gate"))
        return results
    for spec in stage.gate:
        spec = _resolve_manuscript_paths(spec, project)
        name = spec.get("check")
        fn = checks.get(name)
        if fn is None:
            results.append(
                Result(False, name or "<missing>", f"unknown check '{name}' - not in the registry",
                       [f"Known checks: {', '.join(checks.known())}"])
            )
            continue
        ctx = Ctx(pipeline=pipeline, state=state, project=project, stage=stage, spec=spec)
        try:
            res = fn(ctx)
        except Exception as exc:  # noqa: BLE001 - a broken check must not brick the pipeline
            res = Result(False, name, f"check raised {type(exc).__name__}: {exc}")
        if "severity" in spec and not res.ok:
            res.severity = spec["severity"]
        results.append(res)
    return results


def summarize(results: list[Result]) -> tuple[bool, int, int]:
    blocking = sum(1 for r in results if r.blocking)
    warned = sum(1 for r in results if (not r.ok) and r.severity == "warn")
    return blocking == 0, blocking, warned
