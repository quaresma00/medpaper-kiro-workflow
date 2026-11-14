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

1.25.0 (A): the benchmark is the 5-10 (target 8) MOST RECENT comparable papers. benchmark.py
search writes 01_protocol/benchmark_search.json (query from the study basis and the display
dictionary, PubMed sorted by publication date, original articles in English, the last 3 years,
5 when fewer than 5 candidates exist; metadata only). A more recent candidate is passed over only
with a recorded reason (benchmark.py skip); an older paper only as a recorded exception, outside
the median; abstract-only papers (counts unknown) stay outside the median too. These selection
rules (selection_problems) apply to papers on 1.25.0+ (`wf migrate --yes`).
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
        if paper.get("counts_known") is False and paper.get(k) is None:
            continue  # 1.25.0 (A3): abstract only, counts unknown - never in the median
        if not isinstance(paper.get(k), int) or paper[k] < 0:
            raise ValueError(f"{k}: a count >= 0 is required")
    if paper.get("exception") is not None and len(str(paper["exception"]).strip()) < 10:
        raise ValueError("--exception needs a one-line reason (>= 10 characters)")
    if paper.get("source") not in SOURCES:
        raise ValueError(f"source must be one of {', '.join(SOURCES)}")
    if not paper.get("pmid") or not paper.get("title"):
        raise ValueError("pmid and title are required (from the retrieved record)")
    if not paper.get("display_types") and paper.get("counts_known") is not False:
        paper["display_types"] = classify(paper.get("captions", []), design)
    paper.setdefault("display_types", [])
    unknown = sorted(set(paper["display_types"]) - set(types_for(design)))
    if unknown:
        raise ValueError(f"unknown display type(s) {unknown}; known: {', '.join(sorted(types_for(design)))}")
    paper["added_at"] = _now()
    data["papers"] = [x for x in data["papers"] if str(x.get("pmid")) != str(paper["pmid"])] + [paper]
    save(project, data)
    return paper


def counted(papers: list[dict]) -> list[dict]:
    """1.25.0 (A2/A3): papers entering the median - known counts, not a recorded exception."""
    return [p for p in papers if p.get("counts_known") is not False and not p.get("exception")]


def summary(data: dict) -> dict:
    papers = counted(data.get("papers") or [])
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


def plan_problems(project: Path, v1250: bool = False) -> list[str]:
    """The 1.23 rule (3-5 papers); with v1250 (since 1.25.0) the search log, recency, window
    and 5-10 paper rules of selection_problems() come first."""
    data = load(project)
    papers = data.get("papers") or []
    out: list[str] = []
    if v1250:
        out = selection_problems(project)
        if not counted(papers):
            return out or [f"{REL}: no included paper with known display counts"]
    elif len(papers) < 3:
        return [f"{REL}: {len(papers)} comparable paper(s); benchmark 3-5 (tools/pubmed/benchmark.py "
                "add --pmid ... --design ...)"]
    s = summary(data)
    plan = _plan(project)
    if not plan:
        return out + [f"{PLAN} missing or unreadable"]
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
        return ["尚无同类论文图表基准。"] + paper_lines_zh(project, data)
    labels = {k: v.get("label", k) for k, v in types_for(data.get("design", "")).items()}
    plan = _plan(project)
    covered = plan_types(plan, data.get("design", "")) if plan else {}
    out = [f"同类论文图表基准（{s['n']} 篇）：正文图表中位数 {s['median_main_items']}（图 "
           f"{s['median_main_figures']}、表 {s['median_main_tables']}，范围 {s['range_main_items'][0]}-"
           f"{s['range_main_items'][1]}），补充材料中位数 {s['median_supplementary']}。",
           "多数同类论文都有的图表类型：" + "；".join(
               f"{labels.get(t, t)}（{s['type_counts'][t]}/{s['n']}）" for t in s["majority_types"]) + "。"]
    out += paper_lines_zh(project, data)
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


# ============================================================ 1.25.0 (A): the most recent papers
SEARCH_REL = "01_protocol/benchmark_search.json"
MIN_N, TARGET_N, MAX_N = 5, 8, 10
WINDOW_YEARS, WINDOW_EXTENDED = 3, 5
SKIP_REASONS = ("not_comparable", "not_original_article", "displays_not_obtainable")
# Data-source families (required comparability level with the design): name pattern -> PubMed term.
SOURCE_FAMILIES = {
    "pharmacovigilance": (r"faers|\baers\b|jader|vigibase|vigiaccess|eudravigilance|vaers|"
                          r"pharmacovigilance|spontaneous report",
                          '("FAERS"[tiab] OR "Adverse Event Reporting System"[tiab] OR "JADER"[tiab] '
                          'OR "VigiBase"[tiab] OR "EudraVigilance"[tiab] OR "pharmacovigilance"[tiab])'),
    "national_survey": (r"nhanes|knhanes|charls|\bchns\b|brfss|nhis\b",
                        '("NHANES"[tiab] OR "National Health and Nutrition Examination Survey"[tiab] '
                        'OR "KNHANES"[tiab] OR "CHARLS"[tiab] OR "CHNS"[tiab])'),
    "gwas_summary": (r"gwas|mendelian|finngen|\bieu\b", '"Mendelian randomization"[tiab]'),
    "uk_biobank": (r"uk\s*biobank", '"UK Biobank"[tiab]'),
    "icu_database": (r"mimic|eicu", '("MIMIC"[tiab] OR "eICU"[tiab])'),
    "seer": (r"\bseer\b", '"SEER"[tiab]'),
    "gbd": (r"global burden|\bgbd\b", '"Global Burden of Disease"[tiab]'),
}
DESIGN_TERMS = {
    "disproportionality": '(disproportionality[tiab] OR "reporting odds ratio"[tiab] OR "signal '
                          'detection"[tiab])',
    "mendelian_randomization": '("Mendelian randomization"[tiab] OR "Mendelian randomisation"[tiab])',
    "cohort": "cohort[tiab]",
    "case_control": '"case-control"[tiab]',
    "cross_sectional_survey": '"cross-sectional"[tiab]',
    "prediction_model": '(nomogram[tiab] OR "prediction model"[tiab] OR "risk score"[tiab])',
    "meta_analysis": '("meta-analysis"[pt] OR "meta-analysis"[tiab])',
}
EXCLUDED_PT = ("review", "systematic review", "meta-analysis", "letter", "comment", "editorial",
               "case reports", "published erratum", "retraction notice", "retracted publication")
_MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep",
                                       "oct", "nov", "dec"), 1)}


def _idea(project: Path) -> dict:
    try:
        d = json.loads((Path(project) / "01_protocol/idea.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def source_family(project: Path) -> str:
    src = _idea(project).get("data_source") or {}
    name = str(src.get("name", "")) if isinstance(src, dict) else ""
    for fam, (rx, _term) in SOURCE_FAMILIES.items():
        if re.search(rx, name, re.I):
            return fam
    return ""


def design_key(project: Path, given: str = "") -> str:
    """The display design key (reference/display_types.toml) from the structured study basis."""
    if given:
        return given
    if load(project).get("design"):
        return load(project)["design"]
    d = str(_idea(project).get("study_design", ""))
    fam = source_family(project)
    if fam == "pharmacovigilance":
        return "disproportionality"
    return {"cohort_retrospective": "cohort", "cohort_prospective": "cohort",
            "case_control": "case_control", "cross_sectional": "cross_sectional_survey",
            "mendelian_randomization": "mendelian_randomization", "meta_analysis": "meta_analysis",
            "systematic_review": "meta_analysis", "prognostic_model": "prediction_model"}.get(d, "")


def topic_terms(project: Path) -> list[str]:
    """Exposure / outcome clinical labels of the display dictionary (role-tagged first)."""
    try:
        data = json.loads((Path(project) / "01_protocol/display_dictionary.json").read_text(
            encoding="utf-8"))
    except (OSError, ValueError):
        return []
    entries = data.get("entries", data) if isinstance(data, dict) else data
    entries = [e for e in (entries if isinstance(entries, list) else []) if isinstance(e, dict)]
    tagged = [e for e in entries if str(e.get("role", "")).lower() in ("exposure", "outcome")]
    out = []
    for e in tagged or entries[:4]:
        lab = str(e.get("label", "")).strip()
        if 2 < len(lab) <= 60 and lab not in out:
            out.append(lab)
    return out[:6]


def _window(searched: datetime, years: int) -> tuple[str, str]:
    try:
        start = searched.replace(year=searched.year - years)
    except ValueError:  # 29 February
        start = searched.replace(year=searched.year - years, day=28)
    return start.strftime("%Y-%m-%d"), searched.strftime("%Y-%m-%d")


def build_query(project: Path, design: str, topical: str = "", years: int = WINDOW_YEARS,
                searched: datetime | None = None) -> tuple[str, str, str]:
    """(query, window start, window end): topical part (design + data-source family + exposure /
    outcome terms, or the agent's --query) AND original-article, English and date filters."""
    searched = searched or datetime.now(timezone.utc)
    start, end = _window(searched, years)
    if not topical:
        parts = []
        if DESIGN_TERMS.get(design):
            parts.append(DESIGN_TERMS[design])
        fam = source_family(project)
        if fam and SOURCE_FAMILIES[fam][1] not in parts:
            parts.append(SOURCE_FAMILIES[fam][1])
        terms = topic_terms(project)
        if terms:
            parts.append("(" + " OR ".join(f'"{t}"[tiab]' for t in terms) + ")")
        if not parts:
            raise ValueError("no study basis to build the query from (01_protocol/idea.json "
                             "study_design / data_source, display dictionary labels): pass --query")
        topical = " AND ".join(parts)
    excl = [t for t in EXCLUDED_PT if design != "meta_analysis" or t not in ("systematic review",
                                                                             "meta-analysis")]
    query = (f"({topical}) NOT (" + " OR ".join(f'"{t}"[pt]' for t in excl) + ") AND english[la] "
             f'AND ("{start.replace("-", "/")}"[dp] : "{end.replace("-", "/")}"[dp])')
    return query, start, end


def pub_date(rec: dict) -> str:
    """ISO date of an esummary record, preferring the electronic date."""
    for key in ("epubdate", "pubdate", "sortpubdate"):
        raw = str(rec.get(key, "")).strip()
        m = re.match(r"(\d{4})(?:[/ -]([A-Za-z]{3}|\d{1,2}))?(?:[/ -](\d{1,2}))?", raw)
        if not m:
            continue
        mon = m.group(2) or "1"
        mon = _MONTHS.get(mon[:3].lower(), 1) if not mon.isdigit() else int(mon)
        return f"{int(m.group(1)):04d}-{mon:02d}-{int(m.group(3) or 1):02d}"
    return ""


def eligible_record(rec: dict, design: str) -> bool:
    pts = {str(x).lower() for x in rec.get("pubtype") or []}
    excl = set(EXCLUDED_PT) - ({"systematic review", "meta-analysis"} if design == "meta_analysis"
                               else set())
    langs = {str(x).lower() for x in rec.get("lang") or ["eng"]}
    return not (pts & excl) and "eng" in langs


def load_search(project: Path) -> dict:
    try:
        d = json.loads((Path(project) / SEARCH_REL).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def save_search(project: Path, data: dict) -> Path:
    p = Path(project) / SEARCH_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return p


def record_search(project: Path, *, query: str, design: str, years: int, start: str, end: str,
                  count: int, records: list[dict], extended_reason: str = "") -> dict:
    """Write the search log: candidates most recent first; earlier skip records are kept."""
    old = load_search(project)
    cands = []
    for r in records:
        if not eligible_record(r, design):
            continue
        cands.append({"pmid": str(r.get("uid") or r.get("pmid")), "date": pub_date(r),
                      "journal": r.get("source") or r.get("fulljournalname") or "",
                      "title": str(r.get("title", ""))[:300]})
    cands.sort(key=lambda c: c["date"], reverse=True)
    data = {"schema": 1, "query": query, "design": design, "searched_at": _now(),
            "window_years": years, "window_start": start, "window_end": end,
            "sort": "pub_date (most recent first)", "esearch_count": count,
            "n_metadata": len(records), "n_candidates": len(cands), "candidates": cands,
            "skipped": {k: v for k, v in (old.get("skipped") or {}).items()
                        if k in {c["pmid"] for c in cands}}}
    if extended_reason:
        data["extended_reason"] = extended_reason
    save_search(project, data)
    return data


def skip(project: Path, pmid: str, reason: str, note: str = "") -> dict:
    data = load_search(project)
    if not data:
        raise ValueError(f"{SEARCH_REL} missing: run benchmark.py search first")
    if reason not in SKIP_REASONS:
        raise ValueError(f"reason must be one of {', '.join(SKIP_REASONS)}")
    if str(pmid) not in {c["pmid"] for c in data.get("candidates", [])}:
        raise ValueError(f"PMID {pmid} is not a candidate of the search log")
    if len(note.strip()) < 10:
        raise ValueError("--note: one line saying why (>= 10 characters)")
    data.setdefault("skipped", {})[str(pmid)] = {"reason": reason, "note": note.strip()}
    save_search(project, data)
    return data


def candidate_date(project: Path, pmid: str) -> str:
    for c in load_search(project).get("candidates", []):
        if c["pmid"] == str(pmid):
            return c["date"]
    return ""


def selection_problems(project: Path) -> list[str]:
    """A4 (since 1.25.0): search log dated; 5-10 included papers (fewer only when the window is
    exhausted); all from the window except recorded exceptions; no more recent candidate passed
    over without a reason; >= 5 with known counts unless the window has fewer."""
    s = load_search(project)
    if not s:
        return [f"{SEARCH_REL} missing: tools/pubmed/benchmark.py search (the most recent "
                "comparable papers, sorted by publication date)"]
    out = []
    if not s.get("searched_at") or not s.get("query") or not s.get("window_start"):
        out.append(f"{SEARCH_REL}: the search log has no query, date or window")
    if int(s.get("window_years") or 0) > WINDOW_YEARS and not s.get("extended_reason"):
        out.append(f"window of {s.get('window_years')} years without a recorded reason (the "
                   "3-year default extends to 5 only when fewer than 5 eligible papers exist)")
    cands = s.get("candidates") or []
    rank = {c["pmid"]: i for i, c in enumerate(cands)}
    skipped = s.get("skipped") or {}
    papers = load(project).get("papers") or []
    regular = [p for p in papers if not p.get("exception")]
    inc = {str(p.get("pmid")) for p in regular}
    for p in regular:
        if str(p.get("pmid")) not in rank:
            out.append(f"PMID {p.get('pmid')} is not a candidate of the search window: take "
                       "papers from the search log, or record it as an exception (--exception)")
    exhausted = all(c["pmid"] in inc or c["pmid"] in skipped for c in cands)
    n, known = len(regular), len(counted(regular))
    if n > MAX_N:
        out.append(f"{n} papers included; take the most recent {MAX_N} at most")
    if n < MIN_N and not exhausted:
        out.append(f"{n} paper(s) included; include the next most recent eligible candidates "
                   f"(target {TARGET_N}, at least {MIN_N}) or skip each with a reason")
    elif known < MIN_N and not exhausted:
        out.append(f"only {known} included paper(s) with known display counts (at least {MIN_N}; "
                   "abstract-only papers do not enter the median) - add the next candidates")
    if inc & set(rank):
        last = max(rank[x] for x in inc if x in rank)
        passed = [c["pmid"] for c in cands[:last] if c["pmid"] not in inc and c["pmid"] not in skipped]
        if passed:
            out.append("more recent candidate(s) passed over without a reason: PMID "
                       + ", ".join(passed[:6]) + " (include them, or benchmark.py skip --pmid P "
                       "--reason not_comparable|not_original_article|displays_not_obtainable "
                       "--note \"...\")")
    return out


def paper_lines_zh(project: Path, data: dict | None = None) -> list[str]:
    """1.25.0: one Chinese line per included paper (year, journal, main figures/tables)."""
    data = data or load(project)
    s = load_search(project)
    if not s:
        return []
    lines = [f"检索：{s.get('searched_at', '')[:10]}，近 {s.get('window_years')} 年"
             f"（{s.get('window_start')} 至 {s.get('window_end')}），按发表时间从新到旧，候选 "
             f"{s.get('n_candidates', 0)} 篇；纳入 {len([p for p in data.get('papers') or [] if not p.get('exception')])} 篇："]
    for p in data.get("papers") or []:
        year = (candidate_date(project, p.get("pmid", "")) or str(p.get("year") or ""))[:4]
        counts = (f"正文图 {p['main_figures']}、表 {p['main_tables']}"
                  if p.get("counts_known") is not False else "仅摘要，图表数未知（不计入中位数）")
        tag = f"（例外：{p['exception']}，不计入中位数）" if p.get("exception") else ""
        lines.append(f"- {year} {p.get('journal', '')}：{counts}{tag}")
    return lines
