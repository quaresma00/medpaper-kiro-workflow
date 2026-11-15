"""1.27.0 checks (a paper pinned earlier sees them as warnings until `wf migrate --yes`).

display_wording_clean   S10 (tables) and S11 (figures): the words inside tables and figures.
                        Figures: no figure title, subtitle or caption line in the image (the
                        legend carries them), panel headings of at most 6 words, no explanatory
                        sentence, free text only as data labels or short labels (rules i, j of
                        wfcore/figuretext.py). Tables and figures: no tier-A AI phrasing or spin
                        in any title, header, row label, footnote, legend or in-figure string
                        (rule k); long labels, tier-B phrasing and data-processing words warn.
                        S09/S12/S23 judge the same rules through display_text_resolved.
"""
from __future__ import annotations

from . import Ctx, Result, check

HINTS = ["Figures: delete labs(title/subtitle/caption) and fig.suptitle; keep a panel heading of at "
         "most 6 words only in a multi-panel figure; move every explanation (what a line, colour or "
         "symbol means, the adjustment set, the population) into one sentence of "
         "05_figures/legends.md, then send the changed legend to the medical editor (writer_bundle.py "
         "edit --section legends). Re-render and re-run QC.",
         "Tables: write titles, headers, row labels and footnotes as the prose would say them; "
         "footnote sentences come from 04_tables/table_captions.md (writer_bundle.py edit --section "
         "table_captions after a change). `wf displays text` lists every string with a suggestion; "
         "a genuinely needed phrase goes into .wf/language_allowlist.json with a reason."]


@check("display_wording_clean")
def display_wording_clean(ctx: Ctx) -> Result:
    name = "display_wording_clean"
    from .. import displaytext, figuretext
    kinds = set(ctx.spec.get("kinds", ["table", "figure"]))
    strict = figuretext.since_1270(ctx)
    inv = displaytext.inventory(ctx.project)
    finds = []
    for d in inv["displays"].values():
        if d.get("kind") in kinds:
            finds += figuretext.findings(ctx.project, d, strict)
    allowed = displaytext.clinical.allowlist(ctx.project)
    finds = [f for f in finds if not any(allowed.get(k) in ("all", "display") for k in (
        f["text"].strip().casefold(), str(f.get("hit", "")).strip().casefold()) if k)]
    block = [f for f in finds if f["severity"] == "fail"]
    warn = [f for f in finds if f["severity"] != "fail"]
    what = " and ".join(sorted(kinds))
    if block:
        return Result(False, name, f"{len(block)} string(s) inside {what}: "
                      + "; ".join(displaytext.line(f) for f in block[:8]), HINTS)
    if warn:
        pinned = "" if strict else (f" (applies from engine {figuretext.SINCE} after `wf "
                                    "migrate --yes`; paper pinned earlier)")
        return Result(False, name, f"{len(warn)} advisory{pinned}: "
                      + "; ".join(displaytext.line(f) for f in warn[:6]), HINTS, severity="warn")
    n = sum(1 for d in inv["displays"].values() if d.get("kind") in kinds)
    return Result(True, name, f"{n} {what}: no title, subtitle or explanatory text inside figures; "
                              "display wording in the register of the prose")
