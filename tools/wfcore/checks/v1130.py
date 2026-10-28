"""1.13.0 checks.

engine_fork_recorded   G1: a paper that runs a project-local engine fork keeps its diff against
                       the base current (.wf/engine_fork.diff) so the maintainer can upstream
                       it; shown at S25 (warning, never blocking).
"""
from __future__ import annotations

from . import Ctx, Result, check


_POLISH = None
# Structural lint kinds that block a section (AI tells, pipeline/plan history, list density).
SECTION_BLOCKING = frozenset({"backstage_language", "bullets_in_prose", "em_dash_density",
                              "transition_density", "hedge_stacking"})


def _polish():
    global _POLISH
    if _POLISH is None:
        import importlib.util
        from .. import paths
        spec = importlib.util.spec_from_file_location(
            "medpaper_polish_lint", paths.tools_dir() / "text" / "polish.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _POLISH = mod
    return _POLISH


@check("section_language_clean")
def section_language_clean(ctx: Ctx) -> Result:
    """G4 (#5): each writing stage polishes its own section before it advances - medical
    register, de-AI, de-engineering, no pipeline/plan history, prose not lists. Blocking:
    engineering language (warning in Methods, as in 1.11), backstage/deviation narration,
    tier-A AI phrases, AI rhythm (em dashes, transitions, stacked hedges), list density.
    Style issues warn; S22 then only harmonises across sections and to the journal."""
    from .v1110 import _file_hits
    from .. import clinical
    rel = ctx.src(ctx.spec["path"])
    if not ctx.p(rel).is_file():
        if ctx.spec.get("optional"):
            return Result(True, "section_language_clean", f"{rel}: optional file absent")
        return Result(False, "section_language_clean", f"{rel} missing")
    text = ctx.read(rel)
    pol = _polish()
    try:
        allow = pol.allowlist()
    except (Exception, SystemExit):  # noqa: BLE001 - no allowlist outside a paper
        allow = {}
    ai = pol.lint_ai(rel, text, allow)
    struct = pol.lint_structure(rel, text)
    style = pol.lint_style(rel, text)
    eng_block, eng_warn = _file_hits(ctx, rel, text, clinical.allowlist(ctx.project))
    block = [f"engineering: {x}" for x in eng_block]
    block += [f"AI phrase '{x['match']}' (line {x['line']})" for x in ai if x["tier"] == "A"]
    block += [f"{x['kind']}: {x['detail'][:140]}" for x in struct if x["kind"] in SECTION_BLOCKING]
    warn = [f"engineering (advisory): {x}" for x in eng_warn]
    warn += [f"{x['kind']}: {x['detail'][:100]}" for x in struct + style
             if x["kind"] not in SECTION_BLOCKING and x["severity"] == "blocking"]
    tier_b = sum(1 for x in ai if x["tier"] == "B")
    hints = [f"Polish this section now: python tools/text/polish.py lint --file {rel} - rewrite "
             "every blocking item in clinical prose without changing a number, citation or "
             "table/figure reference; a genuine exception goes in "
             "07_manuscript/polish_allowlist.tsv with a reason.",
             "Never narrate the pipeline, an initial plan or protocol deviations; simply "
             "describe the analysis performed."]
    if block:
        return Result(False, "section_language_clean", f"{rel}: {len(block)} blocking language "
                      "item(s): " + "; ".join(block[:6]), hints)
    if warn or tier_b:
        return Result(False, "section_language_clean", f"{rel}: clean of engineering, AI and "
                      f"backstage language; {len(warn)} style item(s), {tier_b} tier-B phrase(s) "
                      "to consider: " + "; ".join(warn[:4]), hints, severity="warn")
    return Result(True, "section_language_clean", f"{rel}: polished (medical register, no AI, "
                                                  "engineering or backstage language)")


@check("data_not_copied")
def data_not_copied(ctx: Ctx) -> Result:
    """G2: the user's datasets are used in place. A copy (or hard link) of a declared data
    source inside the paper fails; a large raw folder with no declared source and an
    oversized extraction cache warn. Stat only - nothing is hashed."""
    from .. import datasources
    project = ctx.project
    index: dict[tuple[str, int], str] = {}
    for label, p in datasources.files(project):
        try:
            index[(p.name.casefold(), p.stat().st_size)] = label
        except OSError:
            continue
    dups, raw_bytes = [], 0
    base = project / "02_data"
    for p in sorted(base.rglob("*")) if base.is_dir() else []:
        if not p.is_file():
            continue
        rel = p.relative_to(project).as_posix()
        try:
            size = p.stat().st_size
        except OSError:
            continue
        if rel.startswith("02_data/raw/"):
            raw_bytes += size
        hit = index.get((p.name.casefold(), size))
        if hit and size > 0 and not rel.startswith("02_data/cache/"):
            dups.append(f"{rel} (= {hit}, {size / 1e6:,.1f} MB)")
    limit = datasources.copy_limit_bytes(project)
    cache = project / "02_data/cache"
    cache_bytes = sum(f.stat().st_size for f in cache.rglob("*") if f.is_file()) \
        if cache.is_dir() else 0
    hints = ["Delete the copy and read the dataset where it is: scripts use "
             "analysis.datasources.source_path('<name>') (R: medpaper_source_path()); "
             "evidence and raw_files use datasource:<name>/<file> labels "
             "(tools/data_manifest.py sync).",
             "Never copy, hard-link or fully extract the user's dataset into the paper; stream "
             "archive members (open_member / medpaper_unz)."]
    if dups:
        return Result(False, "data_not_copied", f"{len(dups)} copy/copies of declared datasets "
                      "inside the paper: " + "; ".join(dups[:5]), hints)
    if cache_bytes > limit:
        return Result(False, "data_not_copied", f"02_data/cache holds {cache_bytes / 1e6:,.0f} MB "
                      f"(limit {limit / 1e6:,.0f} MB); clear it (analysis.datasources.clear_cache)",
                      hints, severity="warn")
    if raw_bytes > limit and not datasources.load(project):
        return Result(False, "data_not_copied", f"02_data/raw holds {raw_bytes / 1e6:,.0f} MB and "
                      "no data source is declared: if these files came from a dataset the user "
                      "already has, register it in place (wf data add) and delete the copy",
                      hints, severity="warn")
    n = len(datasources.load(project))
    return Result(True, "data_not_copied", f"{n} declared data source(s) used in place; no "
                                           "copies in the paper")


@check("engine_fork_recorded")
def engine_fork_recorded(ctx: Ctx) -> Result:
    from .. import enginefork
    info = enginefork.info(ctx.project)
    if not info:
        return Result(True, "engine_fork_recorded", "no engine fork (the paper uses the global "
                                                    "engine read-only)")
    changes = enginefork.changed_files(ctx.project)
    diff = ctx.project / enginefork.DIFF_REL
    text = diff.read_text(encoding="utf-8", errors="replace") if diff.is_file() else ""
    stale = [rel for _s, rel in changes if f"b/{rel}" not in text and f"a/{rel}" not in text]
    if not diff.is_file() or stale:
        return Result(False, "engine_fork_recorded",
                      f"engine fork with {len(changes)} changed file(s); diff not recorded for: "
                      + ", ".join(stale[:5] or ["(no .wf/engine_fork.diff)"]),
                      ["Run `wf engine-fork diff` and give .wf/engine_fork.diff to the engine "
                       "maintainer (it is the only way the fix reaches other papers)."],
                      severity="warn")
    return Result(True, "engine_fork_recorded",
                  f"engine fork of {info.get('base_version')}: {len(changes)} changed file(s), "
                  "diff recorded in .wf/engine_fork.diff for the maintainer")
