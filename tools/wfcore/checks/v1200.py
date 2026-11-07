"""1.20.0 checks (a paper pinned earlier gets them after `wf migrate --yes`; `wf journal switch`
adopts the current gate set for S20-S25).

display_text_resolved   V3/V5 (S09 next to displays_seen_before_results, S12, S23): every
                        visible string of every table and figure (the inventory of `wf displays
                        text`, recomputed here) reads in clinical language - code-like names,
                        placeholder labels, software-output columns, scientific notation,
                        missing units, undefined 'Model 2' labels are mapped through the display
                        dictionary, reworded, or allowlisted with a reason. Technical terms not
                        spelled out and main tables wider than 8 data columns are advisory.
At S10/S11 the same findings are part of first_reader_displays (warning).
"""
from __future__ import annotations

from . import Ctx, Result, check

HINTS = ["`wf displays text` lists each string with its display and role and writes the writer "
         "bundle .wf/writer_bundle/displays/; the medpaper-clinical-writer answers in "
         ".wf/writer/display_wording.md, `wf displays apply` puts labels/units/definitions into "
         "01_protocol/display_dictionary.json (the builders relabel at the next render), other "
         "wording goes into the table/figure scripts, legends and captions; then re-render "
         "(`wf rebuild --wait` after S19).",
         "A string that is right as it is (e.g. a methods paper's model columns): "
         ".wf/language_allowlist.json {\"terms\": [{\"term\": \"<exact string>\", \"reason\": "
         "\">= 15 chars\", \"scope\": \"all\"}]}."]


@check("display_text_resolved")
def display_text_resolved(ctx: Ctx) -> Result:
    from .. import displaytext
    name = "display_text_resolved"
    if not displaytext.since_1200(ctx):
        return Result(True, name, "applies from engine 1.20.0 (`wf migrate --yes` or `wf journal "
                                  "switch`); paper pinned earlier - `wf displays text` works now")
    inv = displaytext.inventory(ctx.project)
    finds = displaytext.findings(ctx.project, inv)
    block = [f for f in finds if f["severity"] == "fail"]
    warn = [f for f in finds if f["severity"] != "fail"]
    n = sum(len(d["strings"]) for d in inv["displays"].values())
    tag = f"inventory {inv['hash'][:12]}"
    if block:
        return Result(False, name, f"{len(block)} visible string(s) not in clinical language "
                      f"({tag}): " + "; ".join(displaytext.line(f) for f in block[:8]), HINTS)
    if warn:
        return Result(False, name, f"{len(warn)} advisory ({tag}): "
                      + "; ".join(displaytext.line(f) for f in warn[:6]), HINTS, severity="warn")
    return Result(True, name, f"{len(inv['displays'])} display(s), {n} visible string(s) in "
                              f"clinical language ({tag})")
