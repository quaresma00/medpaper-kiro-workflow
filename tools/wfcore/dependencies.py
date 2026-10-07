"""File-level dependency closure for targeted rebuilds (ported from the Codex engine, 1.7.0).

`closure(project, changed)` answers "which files can a change to these sources affect?" from
what the paper itself declares: the artifact plan (figure/table `script`, `source_results`,
`file`/`tiff`/`pdf`), the results JSON environment receipt (`environment.script`, written by
write_results()), the table manifest and the bundle manifest. A's layout is used throughout:
the journal copy lives in 08_submission/manuscript/ (not B's integration/).

Where A does not record a precise edge the closure widens, never narrows: a data/protocol
change reaches every analysis script and result, an unmapped helper reaches every result, and
a bundle item with no known source is connected to every display and journal text. Missing
metadata can cost a rebuild; it can never certify that a consumer is unaffected.
"""
from __future__ import annotations

import json
from pathlib import Path

CHANGE_TYPES = {"scientific", "layout", "wording", "administrative"}
PLAN_REL = "01_protocol/artifact_plan.json"
FIG_GROUPS = ("main_figures", "supp_figures")
TAB_GROUPS = ("main_tables", "supp_tables")
GROUPS = FIG_GROUPS + TAB_GROUPS
VARIANT = "08_submission/manuscript"
SECTIONS = ("title", "abstract", "keywords", "introduction", "methods", "results",
            "discussion", "statements")
# Journal-copy text and where its frozen source lives (scifreeze.ADAPTED_TEXT_FILES).
ADAPTED = ("full_manuscript.md", "supplementary_methods.md", "title_page.md", "statements.md")
ROLE_SOURCES = {
    "manuscript": [f"{VARIANT}/full_manuscript.md", "06_refs/refs.bib"],
    "title_page": [f"{VARIANT}/title_page.md"],
    "cover_letter": ["08_submission/cover_letter.md"],
    "supplementary": [f"{VARIANT}/supplementary_methods.md", "06_refs/refs.bib"],
    "supplementary_methods": [f"{VARIANT}/supplementary_methods.md", "06_refs/refs.bib"],
    "statements": [f"{VARIANT}/statements.md"],
    "figure_legends": ["05_figures/legends.md"],
}


def _norm(value) -> str | None:
    return value.replace("\\", "/") if isinstance(value, str) and value.strip() else None


def _read(project: Path, rel: str):
    path = project / rel
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, ValueError):
        return {}


def figure_outputs(entry: dict) -> list[str]:
    """Every file one figure entry renders: PNG/TIFF/PDF masters and its artist sidecar."""
    outputs = [v for v in (_norm(entry.get(k)) for k in ("file", "tiff", "pdf")) if v]
    for output in list(outputs):
        stem = Path(output).with_suffix("")
        outputs += [stem.as_posix() + ext for ext in (".png", ".tiff", ".pdf")]
        outputs.append((stem.parent.parent / "qc" / (stem.name + ".artist.json")).as_posix())
    return sorted(set(outputs))


def receipt_rel(docx_rel: str) -> str:
    """packagecontent.build_receipt_path, as a project-relative path."""
    return "08_submission/build_receipts/" + docx_rel.replace("/", "__") + ".json"


def closure(project: Path, changed: list[str], *, change_type: str = "scientific",
            baseline_documents: dict | None = None) -> list[str]:
    if change_type not in CHANGE_TYPES:
        raise ValueError("unknown change type")
    edges: dict[str, set[str]] = {}

    def link(source, output):
        source, output = _norm(source), _norm(output)
        if source and output and source != output:
            edges.setdefault(source, set()).add(output)

    changed = [c for c in (_norm(x) for x in changed) if c]
    code_dir = project / "03_analysis/code"
    analysis_code = sorted(p.relative_to(project).as_posix() for p in code_dir.rglob("*")
                           if p.is_file() and "__pycache__" not in p.parts
                           and p.suffix != ".pyc") if code_dir.is_dir() else []
    results = sorted(p.relative_to(project).as_posix()
                     for p in (project / "03_analysis/results").glob("*.json"))

    # Data and protocol: A records no per-result data inputs, so they reach everything.
    for source in changed:
        if source.startswith("02_data/") or source in {
                "01_protocol/protocol_v1.md", "01_protocol/protocol_final.md"}:
            for output in (*analysis_code, *results):
                link(source, output)

    # Results receipts name their producing script (write_results() environment block).
    producers: set[str] = set()
    for rel in results:
        info = _read(project, rel)
        env = info.get("environment") if isinstance(info, dict) else None
        script = _norm(env.get("script")) if isinstance(env, dict) else None
        if script:
            link(script, rel)
            producers.add(script)
        for src in (info.get("source_files", []) if isinstance(info, dict) else []):
            link(src, rel)
        for dest in ("07_manuscript/methods.md", "07_manuscript/results.md",
                     "07_manuscript/abstract.md", "07_manuscript/discussion.md",
                     "03_analysis/reproducibility_report.json"):
            link(rel, dest)
    for source in analysis_code:
        link(source, "03_analysis/reproducibility_report.json")
        if source not in producers:  # helper/library: any result may depend on it
            for rel in results:
                link(source, rel)

    plan = _read(project, PLAN_REL)
    plan = plan if isinstance(plan, dict) else {}
    before = (baseline_documents or {}).get(PLAN_REL)
    touched = None
    if isinstance(before, dict) and before != plan:
        # Prune only a real entry-only edit with the same inventory; shared settings or a
        # reordered list widen to every display.
        rest_b = {k: v for k, v in before.items() if k not in GROUPS}
        rest_a = {k: v for k, v in plan.items() if k not in GROUPS}
        if rest_b == rest_a and all(
                [e.get("id") for e in before.get(g, [])] == [e.get("id") for e in plan.get(g, [])]
                for g in GROUPS):
            touched = {(g, i) for g in GROUPS for i, e in enumerate(plan.get(g, []))
                       if e != before[g][i]}
    table_files: list[str] = []
    display_outputs: list[str] = []
    for group in GROUPS:
        entries = [e for e in plan.get(group, []) if isinstance(e, dict)]
        for index, entry in enumerate(entries):
            if group in FIG_GROUPS:
                outputs = figure_outputs(entry)
            else:
                outputs = [v for v in (_norm(entry.get("file")),) if v]
                table_files += outputs
            display_outputs += outputs
            plan_src = [PLAN_REL] if touched is None or (group, index) in touched else []
            sources = [*entry.get("source_results", []), entry.get("script"), *plan_src]
            for source in sources:
                for output in outputs:
                    link(source, output)
    # One table builder renders every workbook unless an entry names its own script.
    for builder in ("04_tables/code/build_tables.py",):
        for output in table_files:
            link(builder, output)
    manifest = _read(project, "04_tables/manifest.json")
    for entry in (manifest.get("tables", []) if isinstance(manifest, dict) else []):
        if isinstance(entry, dict):
            for source in [*entry.get("source_results", []), entry.get("script")]:
                link(source, entry.get("file"))
    for dest in ("05_figures/legends.md", "04_tables/table_captions.md",
                 "01_protocol/artifact_benchmark.md"):
        link(PLAN_REL, dest)

    # Manuscript assembly (tools/manuscript/assemble.py) and its journal copy.
    for name in SECTIONS:
        link(f"07_manuscript/{name}.md", "07_manuscript/full_manuscript.md")
    link("05_figures/legends.md", "07_manuscript/full_manuscript.md")
    variant = (project / VARIANT / "full_manuscript.md").is_file()
    if variant:
        for name in ADAPTED:
            link(f"07_manuscript/{name}", f"{VARIANT}/{name}")
        for name in ("title_page.md", "statements.md"):
            link("00_input/author_info.json", f"{VARIANT}/{name}")
    link("00_input/author_info.json", "08_submission/cover_letter.md")
    for out in ("06_refs/refs.bib", "06_refs/refs.ris", "06_refs/verified.json"):
        link("06_refs/library.json", out)

    # Bundle uploads. Unknown items are connected to every display and journal text.
    bundle = _read(project, "08_submission/bundle/manifest.json")
    fallback = [*display_outputs, *(f"{VARIANT}/{n}" for n in ADAPTED), "05_figures/legends.md",
                "04_tables/table_captions.md"]
    for item in (bundle.get("items", []) if isinstance(bundle, dict) else []):
        if not isinstance(item, dict):
            continue
        file = _norm(item.get("file"))
        if not file:
            continue
        sources = item.get("source_files") or ([item["source"]] if item.get("source") else None)
        if not sources:
            sources = ROLE_SOURCES.get(str(item.get("role", "")).casefold())
        if not sources:
            stem = Path(file).stem.casefold()
            sources = [o for o in display_outputs if Path(o).stem.casefold() == stem] or fallback
        for source in sources:
            link(source, file)
        if file.endswith(".docx"):
            link("08_submission/docx_style.json", file)
            link(file, receipt_rel(file))

    for entry in plan.get("dependencies", []):
        if isinstance(entry, dict):
            for source in entry.get("source_files", []):
                link(source, entry.get("file"))

    seen = set(changed)
    pending = list(seen)
    while pending:
        for dependent in edges.get(pending.pop(), ()):
            if dependent not in seen:
                seen.add(dependent)
                pending.append(dependent)
    return sorted(seen)


def guard_build(project: Path) -> None:
    """Expensive builders refuse to run while user feedback is still being collected."""
    state = project / ".wf/state.json"
    if not state.is_file():
        return
    try:
        active = json.loads(state.read_text(encoding="utf-8")).get("active_revision_round")
        if not active:
            return
        payload = json.loads((state.parent / "revisions" / f"{active}.json")
                             .read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if payload.get("status") == "collecting":
        raise ValueError("feedback is still being collected; seal the batch "
                         "(tools/rework.py seal) before building")
