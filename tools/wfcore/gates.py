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


# A failure in one of these means the stage's inputs are not there yet. Running the dependent
# checks would only print a cascade of consequential failures (and cost a live PubMed round
# trip) for the agent to read; they are reported as pending instead, never as passed.
STOP_ON_FAIL = frozenset({"outputs_exist"})


def pinned_out(state, sid: str, spec: dict) -> bool:
    """1.9.0 (#8): a gate marked `since = "X"` newer than the paper's engine pin does not
    re-judge a stage the paper already completed; stages not yet completed get it."""
    fn = getattr(state, "pin_excludes", None)
    return bool(fn and fn(sid, spec.get("since")))


def run_stage(pipeline, state, project: Path, stage, *, reuse: bool = False,
              record: bool = False) -> list[Result]:
    """Run a stage gate.

    record=True (wf check) writes short-lived receipts for passing pure-local checks;
    reuse=True (wf advance) may reuse them. See gatecache for what is and is not reusable.
    """
    if getattr(stage, "skipped", False):
        return [Result(True, "paper_override_skip",
                       f"{stage.id} is inapplicable to this paper: {stage.skip_reason}")]
    checks.load_all()
    results: list[Result] = []
    if not stage.gate:
        results.append(Result(True, "-", "stage declares no gate"))
        return results
    receipts = None
    if reuse or record:
        from .gatecache import Receipts
        receipts = Receipts(project, pipeline, state)
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
        if pinned_out(state, stage.id, spec):
            results.append(Result(True, name, f"gate added in engine {spec.get('since')}; this "
                                  f"completed stage keeps the paper's pinned {state.engine_pin} "
                                  "gate set (wf migrate adopts it)"))
            continue
        ctx = Ctx(pipeline=pipeline, state=state, project=project, stage=stage, spec=spec)
        try:
            identity = receipts.identity(stage, spec) if receipts else None
            res = receipts.get(identity) if receipts and reuse else None
            if res is None:
                res = fn(ctx)
                # A pure check must not change the very inputs it certifies.
                if receipts and identity and identity == receipts.identity(stage, spec):
                    receipts.put(identity, res)
        except Exception as exc:  # noqa: BLE001 - a broken check must not brick the pipeline
            res = Result(False, name, f"check raised {type(exc).__name__}: {exc}")
        if "severity" in spec and not res.ok:
            res.severity = spec["severity"]
        results.append(res)
        if res.blocking and name in STOP_ON_FAIL:
            results.append(Result(
                False, "dependent_checks_pending",
                "required outputs are missing; the remaining checks of this gate were not run "
                "and cannot be forced",
                ["Create the missing outputs listed above, then run `wf check` again."]))
            break
    if receipts:
        receipts.save()
    return results


def summarize(results: list[Result]) -> tuple[bool, int, int]:
    blocking = sum(1 for r in results if r.blocking)
    warned = sum(1 for r in results if (not r.ok) and r.severity == "warn")
    return blocking == 0, blocking, warned
