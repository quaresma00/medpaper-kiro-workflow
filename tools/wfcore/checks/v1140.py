"""1.14.0 checks.

writer_results_mapped   B: every required result reaches the clinical writer - each numeric
                        result has a clinical label (display dictionary) and each interval its
                        recorded confidence level; tools/manuscript/writer_bundle.py lists the
                        gaps in .wf/writer_bundle/<stage>_GAPS.md.
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
