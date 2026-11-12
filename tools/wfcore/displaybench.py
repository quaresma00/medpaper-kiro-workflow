"""1.23.0 (S2): display benchmark from comparable published papers (no network here).

01_protocol/display_benchmark.json holds 3-5 comparable papers (same design and data-source
family, similar question, preferably SCIE journals of the last 5 years, one from the target
journal or its tier when known): per paper the main figures, main tables, supplementary items
and display types. tools/pubmed/benchmark.py fills it - cheaply from the PMC / Europe PMC
full-text XML captions when open access, otherwise from a full text the cascade retrieved,
otherwise from the abstract (counts and types the agent read). Display types come from
reference/display_types.toml (per design plus common types).

The S07 gate display_plan_benchmarked: the artifact plan has at least the benchmark median of
main display items (capped by the provisional journal limits; extra items go to the
supplement) and covers every display type used by at least half of the benchmark papers - by an
item's "display_type", its archetype or its title/content - or gives a one-line reason in
artifact_plan.json "benchmark_omissions" {type: reason}.
"""
from __future__ import annotations

import json
import math
import re
import statistics
import tomllib
from datetime import datetime, timezone
from pathlib import Path

REL = "01_protocol/display_benchmark.json"
PLAN = "01_protocol/artifact_plan.json"
SOURCES = ("jats", "pdf", "abstract", "manual")
GROUPS = ("main_figures", "main_tables", "supp_figures", "supp_tables")
_SUPP_LABEL = re.compile(r"(?i)\b(?:S\d+|supplement\w*|additional\s+file|appendix|e(?:figure|table)"
                         r"\s*\d|online\s+resource)")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def taxonomy() -> dict:
    from . import paths
    with open(paths.repo_root() / "reference/display_types.toml", "rb") as fh:
        return tomllib.load(fh)


def designs() -> list[str]:
    return sorted(taxonomy().get("design", {}))


def types_for(design: str) -> dict[str, dict]:
    tax = taxonomy()
    out = dict(tax.get("common", {}))
    out.update(tax.get("design", {}).get(design, {}))
    return out


def classify(captions: list[dict], design: str) -> list[str]:
    """Display types whose patterns match a caption of a fitting kind."""
    found = set()
    for key, spec in types_for(design).items():
        kind = spec.get("kind", "any")
        for c in captions:
            if kind != "any" and c.get("kind") != kind:
                continue
            if any(re.search(p, str(c.get("text", "")), re.I) for p in spec.get("patterns", [])):
                found.add(key)
                break
    return sorted(found)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def jats_displays(blob: bytes) -> dict:
    """Main figures, main tables and supplementary items of a JATS article, from its captions."""
    import xml.etree.ElementTree as ET
    root = ET.fromstring(blob)
    parent = {c: p for p in root.iter() for c in p}

    def inside(el, names) -> bool:
        while el in parent:
            el = parent[el]
            if _local(el.tag) in names:
                return True
        return False

    def text_of(el, name) -> str:
        for c in el.iter():
            if _local(c.tag) == name:
                return " ".join("".join(c.itertext()).split())
        return ""
    figs = tabs = supp = 0
    captions = []
    for el in root.iter():
        tag = _local(el.tag)
        if tag == "supplementary-material" and not inside(el, {"supplementary-material"}):
            supp += 1
            continue
        if tag not in ("fig", "table-wrap") or inside(el, {"fig", "table-wrap"}):
            continue
        if inside(el, {"ref-list", "supplementary-material"}):
            continue
        label = text_of(el, "label")
        text = (label + " " + text_of(el, "caption")).strip()[:400]
        kind = "figure" if tag == "fig" else "table"
        if inside(el, {"app", "app-group"}) or _SUPP_LABEL.search(label):
            supp += 1
            captions.append({"kind": kind, "text": text, "supplementary": True})
            continue
        if kind == "figure":
            figs += 1
        else:
            tabs += 1
        captions.append({"kind": kind, "text": text})
    return {"main_figures": figs, "main_tables": tabs, "supplementary": supp, "captions": captions}


_TXT_CAP = re.compile(r"(?m)^\s*(Fig(?:ure)?\.?|Table)\s+(S?)(\d{1,2})[.:]?\s+(.{0,200})")


def text_displays(text: str) -> dict:
    """Counts and captions from a full text's plain text (PDF): highest Figure/Table number."""
    figs, tabs, supp, caps = set(), set(), set(), {}
    for m in _TXT_CAP.finditer(text or ""):
        kind = "table" if m.group(1).lower().startswith("table") else "figure"
        key = (kind, m.group(2), int(m.group(3)))
        if m.group(2):
            supp.add(key)
        elif kind == "figure":
            figs.add(key)
        else:
            tabs.add(key)
        caps.setdefault(key, {"kind": kind, "text": " ".join(m.group(0).split())[:400],
                              **({"supplementary": True} if m.group(2) else {})})
    return {"main_figures": len(figs), "main_tables": len(tabs), "supplementary": len(supp),
            "captions": list(caps.values())}


def load(project: Path) -> dict:
    try:
        data = json.loads((Path(project) / REL).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("schema", 1)
    data.setdefault("papers", [])
    return data


def save(project: Path, data: dict) -> Path:
    data["summary"] = summary(data)
    data["updated_at"] = _now()
    p = Path(project) / REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return p


def add_paper(project: Path, design: str, paper: dict) -> dict:
    if design not in designs():
        raise ValueError(f"unknown design '{design}' (known: {', '.join(designs())})")
    data = load(project)
    if data.get("design") and data["design"] != design:
        raise ValueError(f"the benchmark is for design '{data['design']}'")
    data["design"] = design
    for k in ("main_figures", "main_tables", "supplementary"):
        if not isinstance(paper.get(k), int) or paper[k] < 0:
            raise ValueError(f"{k}: a count >= 0 is required")
    if paper.get("source") not in SOURCES:
        raise ValueError(f"source must be one of {', '.join(SOURCES)}")
    if not paper.get("pmid") or not paper.get("title"):
        raise ValueError("pmid and title are required (from the retrieved record)")
    if not paper.get("display_types"):
        paper["display_types"] = classify(paper.get("captions", []), design)
    unknown = sorted(set(paper["display_types"]) - set(types_for(design)))
    if unknown:
        raise ValueError(f"unknown display type(s) {unknown}; known: {', '.join(sorted(types_for(design)))}")
    paper["added_at"] = _now()
    data["papers"] = [x for x in data["papers"] if str(x.get("pmid")) != str(paper["pmid"])] + [paper]
    save(project, data)
    return paper


def summary(data: dict) -> dict:
    papers = data.get("papers") or []
    if not papers:
        return {"n": 0}
    main = [int(p["main_figures"]) + int(p["main_tables"]) for p in papers]
    share: dict[str, int] = {}
    for p in papers:
        for t in set(p.get("display_types") or []):
            share[t] = share.get(t, 0) + 1
    n = len(papers)
    return {"n": n, "median_main_items": statistics.median(main),
            "median_main_figures": statistics.median(int(p["main_figures"]) for p in papers),
            "median_main_tables": statistics.median(int(p["main_tables"]) for p in papers),
            "median_supplementary": statistics.median(int(p["supplementary"]) for p in papers),
            "range_main_items": [min(main), max(main)], "type_counts": dict(sorted(share.items())),
            "majority_types": sorted(t for t, k in share.items() if 2 * k >= n)}


def _plan(project: Path) -> dict:
    try:
        data = json.loads((Path(project) / PLAN).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def plan_types(plan: dict, design: str) -> dict[str, list[str]]:
    """Display type -> plan item ids covering it (declared type, archetype or wording)."""
    specs = types_for(design)
    out: dict[str, list[str]] = {}
    for g in GROUPS:
        for it in plan.get(g) or []:
            if not isinstance(it, dict):
                continue
            kind = "figure" if "figures" in g else "table"
            iid = str(it.get("id", "?"))
            text = " ".join(str(it.get(k, "")) for k in ("title", "content", "slug"))
            for key, spec in specs.items():
                hit = it.get("display_type") == key or key in (it.get("display_types") or [])
                hit = hit or (it.get("archetype") and it.get("archetype") in spec.get("archetypes", []))
                if not hit and spec.get("kind", "any") in ("any", kind):
                    hit = any(re.search(p, text, re.I) for p in spec.get("patterns", []))
                if hit:
                    out.setdefault(key, []).append(iid)
    return out


def main_cap(project: Path) -> int:
    from . import registry
    try:
        t = registry.effective_targets(project)
    except Exception:  # noqa: BLE001
        t = {}
    cap = int(t.get("main_figures_max", 6)) + int(t.get("main_tables_max", 5))
    try:
        prof = json.loads((Path(project) / "01_protocol/journal_profile.json").read_text(encoding="utf-8"))
        lim = (prof.get("limits") or {}).get("display_items") or prof.get("display_items")
        if isinstance(lim, int) and lim > 0:
            cap = min(cap, lim)
    except (OSError, ValueError, AttributeError):
        pass
    return cap


def plan_problems(project: Path) -> list[str]:
    data = load(project)
    papers = data.get("papers") or []
    if len(papers) < 3:
        return [f"{REL}: {len(papers)} comparable paper(s); benchmark 3-5 (tools/pubmed/benchmark.py "
                "add --pmid ... --design ...)"]
    s = summary(data)
    plan = _plan(project)
    if not plan:
        return [f"{PLAN} missing or unreadable"]
    out = []
    n_main = len(plan.get("main_figures") or []) + len(plan.get("main_tables") or [])
    need = min(math.ceil(s["median_main_items"]), main_cap(project))
    if n_main < need:
        out.append(f"plan has {n_main} main display item(s); the benchmark median is "
                   f"{s['median_main_items']} (required {need} within the journal limits) - "
                   "add the missing displays, extra ones go to the supplement")
    covered = plan_types(plan, data["design"])
    omit = plan.get("benchmark_omissions") or {}
    for t in s["majority_types"]:
        if t in covered:
            continue
        if len(str(omit.get(t, "")).strip()) >= 10:
            continue
        out.append(f"display type '{t}' ({s['type_counts'][t]}/{s['n']} benchmark papers) is not in "
                   f"the plan: add it, or give a one-line reason in benchmark_omissions")
    return out


def message_zh(project: Path) -> list[str]:
    """The few Chinese lines for the S07 message to the user."""
    data = load(project)
    s = summary(data)
    if not s.get("n"):
        return ["尚无同类论文图表基准。"]
    labels = {k: v.get("label", k) for k, v in types_for(data.get("design", "")).items()}
    plan = _plan(project)
    covered = plan_types(plan, data.get("design", "")) if plan else {}
    out = [f"同类论文图表基准（{s['n']} 篇）：正文图表中位数 {s['median_main_items']}（图 "
           f"{s['median_main_figures']}、表 {s['median_main_tables']}，范围 {s['range_main_items'][0]}-"
           f"{s['range_main_items'][1]}），补充材料中位数 {s['median_supplementary']}。",
           "多数同类论文都有的图表类型：" + "；".join(
               f"{labels.get(t, t)}（{s['type_counts'][t]}/{s['n']}）" for t in s["majority_types"]) + "。"]
    if plan:
        out.append(f"本文计划：正文图 {len(plan.get('main_figures') or [])} 张、表 "
                   f"{len(plan.get('main_tables') or [])} 张，补充图 {len(plan.get('supp_figures') or [])}、"
                   f"补充表 {len(plan.get('supp_tables') or [])}；已覆盖类型 "
                   f"{sum(1 for t in s['majority_types'] if t in covered)}/{len(s['majority_types'])}。")
        omit = plan.get("benchmark_omissions") or {}
        for t in s["majority_types"]:
            if t not in covered and t in omit:
                out.append(f"未做“{labels.get(t, t)}”：{omit[t]}")
    return out
