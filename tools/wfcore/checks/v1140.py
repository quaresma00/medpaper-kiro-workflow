"""1.14.0 checks.

writer_results_mapped   B: every required result reaches the clinical writer - each numeric
                        result has a clinical label (display dictionary) and each interval its
                        recorded confidence level; tools/manuscript/writer_bundle.py lists the
                        gaps in .wf/writer_bundle/<stage>_GAPS.md.
additional_analyses_justified   E: the analysis is complete when the primary and secondary
                        outcomes and the validity checks of the statistical reporting plan are
                        done; each additional analysis (analysis_manifest.json entry with role
                        "additional") states which scientific decision it could change.
"""
from __future__ import annotations

from . import Ctx, Result, check


def _writer_bundle():
    import importlib.util
    from .. import paths
    spec = importlib.util.spec_from_file_location(
        "medpaper_writer_bundle", paths.tools_dir() / "manuscript" / "writer_bundle.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@check("writer_results_mapped")
def writer_results_mapped(ctx: Ctx) -> Result:
    gaps = _writer_bundle().result_gaps(ctx.project)
    if gaps:
        return Result(False, "writer_results_mapped",
                      f"{len(gaps)} result(s) the clinical writer cannot be given: "
                      + "; ".join(gaps[:4]),
                      ["Add each name to 01_protocol/display_dictionary.json (label + definition), "
                       "record ci_level in the results (write_results does by default), or list "
                       "a value that is never reported under 'not_reported' with a reason; then "
                       "writer_bundle.py build again."])
    return Result(True, "writer_results_mapped",
                  "every result has a clinical label and every interval its confidence level")


ROLES = ("primary", "secondary", "validity", "descriptive", "additional")


@check("additional_analyses_justified")
def additional_analyses_justified(ctx: Ctx) -> Result:
    import json
    rel = "03_analysis/analysis_manifest.json"
    try:
        entries = json.loads(ctx.p(rel).read_text(encoding="utf-8")).get("scripts", [])
    except (OSError, ValueError, AttributeError):
        return Result(True, "additional_analyses_justified", f"{rel} absent; nothing to check")
    problems, extra = [], 0
    for e in entries if isinstance(entries, list) else []:
        if not isinstance(e, dict) or "role" not in e:
            continue
        role = str(e.get("role", "")).strip().casefold()
        if role not in ROLES:
            problems.append(f"{e.get('path')}: role '{role}' (use {', '.join(ROLES)})")
        elif role == "additional":
            extra += 1
            if len(str(e.get("decision", "")).strip()) < 15:
                problems.append(f"{e.get('path')}: an additional analysis needs 'decision' - the "
                                "scientific decision it could change (one line)")
    if problems:
        return Result(False, "additional_analyses_justified", "; ".join(problems[:6]),
                      ["Stop when the primary and secondary outcomes and the validity checks of "
                       "the statistical reporting plan are done; keep an extra analysis only if "
                       "it could change a scientific decision, and say which."])
    return Result(True, "additional_analyses_justified",
                  f"{extra} additional analysis/analyses, each with the decision it could change")
