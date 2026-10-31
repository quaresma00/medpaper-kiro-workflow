"""Structured journal rules read from 08_submission/target_journal.json (stdlib only).

Every presentation rule a check or the Word builder needs comes from typed fields here, never
from a regex over guideline prose (a prose parse once read "45 references, no more than 6
figures/tables" as a 6-reference cap). A field the journal is silent on falls back to a common
medical-journal default, so the same code serves every paper and journal.

    {
      "article_type": "Original Article",
      "limits": {"main_text_words": 4000, "abstract_words": 250, "reference_limit": 45,
                 "display_items": 6, "main_figures": null, "main_tables": null,
                 "source": "<guide URL + quoted rule>"},
      "word_count_scope": ["Introduction", "Methods", "Results", "Discussion", "Conclusions"],
      "declarations_order": ["Funding", "Competing interests", ...],
      "discussion_subheadings": false,
      "embed_figures": false, "word_tables": false,
      "legend_style": {"prefix": "Fig.", "bold": true, "panel_label_case": "lower",
                       "end_punctuation": "."},
      "supplementary_aliases": {"Online Resource 1": ["Supplementary Methods", "Table S1"]},
      "reference_separator": "space",
      "si_format": "pdf",
      "evidence_sources": {"official": [...], "third_party": [...]}
    }
"""
from __future__ import annotations

import json
import re
from pathlib import Path

TARGET = "08_submission/target_journal.json"

# Springer Nature order; used when the guide does not prescribe one.
DEFAULT_DECLARATIONS_ORDER = (
    "Funding", "Competing interests", "Ethics approval", "Consent to participate",
    "Consent for publication", "Data availability", "Code availability",
    "Author contributions", "Acknowledgements",
)
# Common heading variants mapped onto the canonical item they stand for.
DECLARATION_SYNONYMS = {
    "funding": "funding", "funding information": "funding", "financial support": "funding",
    "competing interests": "competing interests", "conflict of interest": "competing interests",
    "conflicts of interest": "competing interests", "declaration of interests": "competing interests",
    "ethics approval": "ethics approval", "ethical approval": "ethics approval",
    "ethics approval and consent to participate": "ethics approval",
    "ethics statement": "ethics approval",
    "consent to participate": "consent to participate", "informed consent": "consent to participate",
    "consent for publication": "consent for publication",
    "data availability": "data availability", "data availability statement": "data availability",
    "availability of data and materials": "data availability",
    "code availability": "code availability",
    "author contributions": "author contributions", "authors' contributions": "author contributions",
    "author contribution": "author contributions",
    "acknowledgements": "acknowledgements", "acknowledgments": "acknowledgements",
}
# Drafting defaults used S08-S17 before a journal is chosen (common medical caps); S20 replaces
# them with the chosen journal's structured limits.
DEFAULT_DRAFT_LIMITS = {"main_text_words": 4000, "abstract_words": 250}
DEFAULT_SCOPE = ("Introduction", "Methods", "Results", "Discussion", "Conclusion", "Conclusions")
LIMIT_FIELDS = ("main_text_words", "abstract_words", "reference_limit", "display_items",
                "main_figures", "main_tables", "figure_legend_words")
# 1.10.0 (#10): legend length blocks only when the journal states a cap; otherwise
# targets.figure_legend_words_max is advisory.
NO_CAP = 10 ** 6


def legend_cap(target: dict) -> int | None:
    """The journal's explicit figure-legend word cap, or None when the guide states none."""
    block = target.get("limits") if isinstance(target, dict) else None
    value = block.get("figure_legend_words") if isinstance(block, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None
DEFAULT_LEGEND_STYLE = {"prefix": "Figure", "bold": True, "panel_label_case": "any",
                        "end_punctuation": "any"}
PIPELINE_CODE_RE = re.compile(
    r"wfcore|MEDPAPER_[A-Z_]+|project_dir\s*\(|sys\.path\.(?:insert|append)|"
    r"tools[/\\](?:analysis|R|figures|wf\.py)|medresults\.R|write_results\s*\(|"
    r"(?<![\w])[A-Za-z]:[\\/][^\s'\"`)]*|(?<![\w./])/(?:Users|home)/[^\s'\"`)]+")


def load(project: Path) -> dict:
    path = Path(project) / TARGET
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def limits(target: dict) -> tuple[dict[str, int | None], list[str]]:
    """Return the typed caps and any schema problems. None means the journal states no cap."""
    block = target.get("limits")
    problems: list[str] = []
    out: dict[str, int | None] = {k: None for k in LIMIT_FIELDS}
    if not isinstance(block, dict):
        return out, ["target_journal.json has no structured 'limits' object"]
    for key in LIMIT_FIELDS:
        value = block.get(key)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            problems.append(f"limits.{key} must be a positive integer or null, got {value!r}")
            continue
        out[key] = value
    unknown = sorted(set(block) - set(LIMIT_FIELDS) - {"source", "notes", "estimated"})
    if unknown:
        problems.append("limits has unknown field(s): " + ", ".join(unknown))
    if not str(block.get("source", "")).strip():
        problems.append("limits.source must quote the official rule (or state the guide is silent)")
    return out, problems


ESTIMATE_RE = re.compile(r"(?i)\b(estimat\w*|approx\w*|derived|about|roughly|equivalent)\b|~|≈")
PAGE_RE = re.compile(r"(?i)\bpages?\b")


def soft_limits(target: dict) -> set[str]:
    """1.15.0 (E9): word caps that are NOT an explicit numeric rule of the guide - listed in
    limits.estimated, or a source that derives them from a page count ('8-10 printed pages,
    ~3500 words estimated'). They are hints only and never a reason to cut."""
    block = target.get("limits") if isinstance(target.get("limits"), dict) else {}
    out = {str(k) for k in (block.get("estimated") or []) if isinstance(k, str)}
    src = str(block.get("source", ""))
    if PAGE_RE.search(src) and ESTIMATE_RE.search(src):
        out |= {"main_text_words"} & {k for k in LIMIT_FIELDS if block.get(k)}
    return out


def word_count_scope(target: dict) -> list[str]:
    scope = target.get("word_count_scope")
    if isinstance(scope, list) and scope and all(isinstance(x, str) for x in scope):
        out = list(scope)
    else:
        out = list(DEFAULT_SCOPE)
    # A renamed body heading ("Materials and Methods") counts like its canonical section.
    heads = main_text_headings(target)
    for canon, shown in heads.items():
        if canon in out and shown not in out:
            out.append(shown)
    return out


def declarations_order(target: dict) -> list[str]:
    order = target.get("declarations_order")
    if isinstance(order, list) and order and all(isinstance(x, str) and x.strip() for x in order):
        return order
    return list(DEFAULT_DECLARATIONS_ORDER)


def canonical_declaration(heading: str) -> str:
    key = re.sub(r"\s+", " ", heading.strip().rstrip(":").casefold())
    return DECLARATION_SYNONYMS.get(key, key)


def declaration_order_problems(headings: list[str], order: list[str], where: str) -> list[str]:
    """Relative order of the declaration items that are present; unknown headings are ignored."""
    rank = {canonical_declaration(name): i for i, name in enumerate(order)}
    present = [(rank[canonical_declaration(h)], h) for h in headings
               if canonical_declaration(h) in rank]
    for (ra, a), (rb, b) in zip(present, present[1:]):
        if rb < ra:
            return [f"{where}: declaration '{b}' must come before '{a}' "
                    f"(order: {', '.join(order)})"]
    return []


def discussion_subheadings_allowed(target: dict) -> bool:
    return target.get("discussion_subheadings") is True


def legend_style(target: dict) -> dict:
    style = dict(DEFAULT_LEGEND_STYLE)
    raw = target.get("legend_style")
    if isinstance(raw, dict):
        for key in style:
            if key in raw:
                style[key] = raw[key]
    if style["prefix"] not in ("Figure", "Fig.", "Fig"):
        style["prefix"] = "Figure"
    return style


def reference_separator(target: dict) -> str:
    """'space' (default: "1. Author ...") or 'tab' (number + TAB + hanging indent) only when
    the journal explicitly requires it."""
    return "tab" if str(target.get("reference_separator", "")).strip().casefold() == "tab" else "space"


def supplementary_aliases(target: dict) -> dict[str, list[str]]:
    """alias -> canonical ids, e.g. {"Online Resource 2": ["Table S1", "Table S2"]}."""
    raw = target.get("supplementary_aliases")
    out: dict[str, list[str]] = {}
    if isinstance(raw, dict):
        for alias, canon in raw.items():
            items = [canon] if isinstance(canon, str) else canon
            if isinstance(alias, str) and alias.strip() and isinstance(items, list):
                out[alias.strip()] = [str(x).strip() for x in items if str(x).strip()]
    return out


def expand_aliases(text: str, aliases: dict[str, list[str]]) -> str:
    """Replace each journal alias by its canonical ids so fact checks compare like with like."""
    for alias in sorted(aliases, key=len, reverse=True):
        canon = ", ".join(aliases[alias])
        text = re.sub(rf"(?<![\w]){re.escape(alias)}(?![\w])", canon, text)
    return text


def project_aliases(project: Path) -> dict[str, list[str]]:
    return supplementary_aliases(load(project))


# ---------------------------------------------------------------------------
# 1.9.0: typed structure fields. The Markdown source keeps the workflow's canonical names
# (# Methods, comma-separated keywords); the DOCX build renames/re-joins them from these fields
# and the checks compare against them, with the workflow defaults only when a field is absent.
# ---------------------------------------------------------------------------
CANON_BODY = ("Introduction", "Methods", "Results", "Discussion")
HEADING_SYNONYMS = {
    "introduction": {"introduction", "background"},
    "methods": {"methods", "materials and methods", "material and methods", "patients and methods",
                "subjects and methods", "methods and materials", "study design and methods"},
    "results": {"results"},
    "discussion": {"discussion"},
}
DEFAULT_KEYWORDS = {"min": 3, "max": 6, "separator": ","}


# 1.11.0 (#3d): gates judge a heading by its semantic role, never by one literal string.
SECTION_SYNONYMS = {
    "abstract": {"abstract", "summary", "structured abstract"},
    "references": {"references", "reference list", "literature cited", "bibliography", "works cited"},
    "figure legends": {"figure legends", "figure captions", "legends to figures", "figure legend",
                       "legends"},
    "declarations": {"declarations and statements", "statements and declarations", "declarations",
                     "statements", "declaration", "declarations of interest and statements",
                     "ethics and declarations", "compliance with ethical standards",
                     "additional information", "article information", "back matter"},
}


def section_role(heading: str, target: dict | None = None) -> str:
    """Canonical role of a level-1 heading: abstract, introduction, methods, results,
    discussion, references, figure legends, declarations - else the casefolded heading.
    Journal names come from target_journal.json (main_text_headings, declarations_heading)."""
    key = re.sub(r"\s+", " ", str(heading).strip().rstrip(":")).casefold()
    target = target or {}
    for canon, shown in main_text_headings(target).items():
        if key == shown.casefold():
            return canon.casefold()
    for canon, names in HEADING_SYNONYMS.items():
        if key in names:
            return canon
    decl = str(target.get("declarations_heading", "")).strip().casefold()
    if decl and key == decl:
        return "declarations"
    for canon, names in SECTION_SYNONYMS.items():
        if key in names:
            return canon
    return key


def main_text_headings(target: dict) -> dict[str, str]:
    """canonical heading -> the journal's display name (identity when the guide is silent)."""
    out = {c: c for c in CANON_BODY}
    raw = target.get("main_text_headings")
    if isinstance(raw, list):
        for name in raw:
            if not isinstance(name, str) or not name.strip():
                continue
            key = re.sub(r"\s+", " ", name.strip()).casefold()
            for canon, names in HEADING_SYNONYMS.items():
                if key in names:
                    out[canon.capitalize() if canon != "methods" else "Methods"] = name.strip()
    return out


def keyword_rules(target: dict) -> dict:
    rules = dict(DEFAULT_KEYWORDS)
    raw = target.get("keywords")
    if isinstance(raw, dict):
        for key in ("min", "max"):
            if isinstance(raw.get(key), int) and not isinstance(raw.get(key), bool) and raw[key] > 0:
                rules[key] = raw[key]
        sep = str(raw.get("separator", "")).strip()
        if sep in (",", ";", "|", "/", "·", "\u00b7"):
            rules["separator"] = sep
    return rules


def keyword_terms(payload: str, rules: dict) -> list[str]:
    """Split a Keywords payload on the canonical comma or the journal's separator."""
    seps = {",", rules.get("separator", ",")}
    pattern = "|".join(re.escape(s) for s in sorted(seps))
    return [x.strip() for x in re.split(pattern, payload) if x.strip()]


def keyword_problems(payload: str, rules: dict) -> list[str]:
    problems = []
    forbidden = [ch for ch in "/;&|" if ch in payload and ch != rules.get("separator")]
    if forbidden:
        problems.append("Keywords use '" + "', '".join(forbidden) + "'; separate terms with commas "
                        f"(or the journal's '{rules['separator']}')")
    terms = keyword_terms(payload, rules)
    if not rules["min"] <= len(terms) <= rules["max"]:
        problems.append(f"Keywords must contain {rules['min']}-{rules['max']} terms "
                        f"(target_journal.json keywords or the workflow default), found {len(terms)}")
    if len({x.casefold() for x in terms}) != len(terms):
        problems.append("Keywords contain duplicates")
    return problems


def blinded(target: dict) -> bool:
    """Double-blind review: every review-facing file is anonymised (1.9.0, #13)."""
    return target.get("blinded_main_manuscript") is True or target.get("double_blind") is True


def running_title_position(target: dict) -> str:
    """'title_page' (default) or 'manuscript' (first page of the main document)."""
    value = str(target.get("running_title_position", "title_page")).strip().casefold()
    return "manuscript" if value in ("manuscript", "main", "first_page") else "title_page"


LINE_NUMBER_MODES = ("continuous", "per_page", "none")


def line_numbers(target: dict) -> str:
    """1.12.0 (C7): target_journal.json `line_numbers`: continuous | per_page | none."""
    value = target.get("line_numbers", "none")
    if value is True:
        return "continuous"
    value = str(value or "none").strip().casefold().replace("-", "_")
    return value if value in LINE_NUMBER_MODES else "none"


def si_format(target: dict) -> str:
    value = str(target.get("si_format", "pdf")).strip().lower()
    return value if value in ("pdf", "docx") else "pdf"


# ---------------------------------------------------------------------------
# 1.15.0 journal switches (E5/E6). Anything that changes package contents applies to a paper
# pinned before 1.15.0 only after `wf migrate --yes` (or when the switch is set explicitly).
# ---------------------------------------------------------------------------
def since_1150(project: Path | None) -> bool:
    from .state import version_tuple
    if project is None:
        return True
    try:
        st = json.loads((Path(project) / ".wf/state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return True
    pin = str(st.get("engine_pin") or st.get("pipeline_version") or "0")
    return version_tuple(pin) >= (1, 15, 0)


def esm_label(target: dict) -> str:
    """The journal's name for supplementary files ('Online Resource' by default)."""
    value = str(target.get("supplementary_label") or "").strip()
    return value or "Online Resource"


def separate_display_files(target: dict, project: Path | None = None) -> bool:
    """Main figures (TIFF) and main tables (xlsx) also as separate uploads: ON unless the
    journal forbids it (`separate_display_files`: false | "forbidden")."""
    raw = target.get("separate_display_files")
    if raw is None:
        return since_1150(project)
    if raw is True or str(raw).strip().casefold() in ("true", "yes", "required"):
        return True
    if raw is False or str(raw).strip().casefold() in ("false", "no", "forbidden", "none"):
        return False
    return since_1150(project)


def display_file_names(target: dict) -> dict[str, str]:
    raw = target.get("display_file_names") if isinstance(target.get("display_file_names"), dict) else {}
    return {"figure": str(raw.get("figure") or "Fig{n}.tif"),
            "table": str(raw.get("table") or "Table{n}.xlsx")}


def figure_dpi(target: dict) -> int | None:
    for key in ("figure_dpi", "halftone_dpi", "line_art_dpi"):
        v = target.get(key)
        if isinstance(v, int) and not isinstance(v, bool) and v > 0:
            return v
    return None


def abbreviation_list(target: dict, project: Path | None = None) -> str:
    """'none' | 'after_keywords' (default when the journal is silent) | 'keep' (a paper
    pinned before 1.15.0). Never inside Declarations."""
    raw = str(target.get("abbreviation_list") or "").strip().casefold()
    if raw in ("none", "after_keywords"):
        return raw
    return "after_keywords" if since_1150(project) else "keep"


def reference_rules(target: dict, project: Path | None = None) -> dict:
    """1.15.0 (E12): render-time reference fixes. `drop_discussion_pages` removes a
    '; discussion 741-2' tail from a page field (default on for 1.15.0 papers)."""
    raw = target.get("reference_rules") if isinstance(target.get("reference_rules"), dict) else {}
    drop = raw.get("drop_discussion_pages")
    return {"drop_discussion_pages": bool(drop) if isinstance(drop, bool) else since_1150(project)}


# ---------------------------------------------------------------------------
# Word-compatible counting
# ---------------------------------------------------------------------------
_CITE_GROUP = re.compile(r"\[[^\]\n]*@[^\]\n]*\]")


def word_count(text: str) -> int:
    """Count like Microsoft Word: whitespace-separated tokens holding a letter or digit.

    Numbers, '95%', 'HR' and '1.34-2.61' all count. A Pandoc citation group renders as one
    bracketed token ('[3-5]') and counts once. Markdown markup is removed first.
    """
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"(?m)^:::.*$", " ", text)
    text = _CITE_GROUP.sub(" [1] ", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", text)
    return sum(1 for tok in text.split() if re.search(r"[0-9A-Za-z\u00C0-\uFFFF]", tok))


def markdown_sections(text: str) -> dict[str, str]:
    """Level-1 sections of a full manuscript, keyed by casefolded heading."""
    matches = list(re.finditer(r"(?m)^#\s+([^#\n].*)$", text))
    out: dict[str, str] = {}
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        out[m.group(1).strip().casefold()] = text[m.end():end]
    return out


def markdown_counts(text: str, scope: list[str]) -> dict[str, int]:
    secs = markdown_sections(text)
    wanted = {s.casefold() for s in scope}
    body = sum(word_count(v) for k, v in secs.items() if k in wanted)
    abstract = secs.get("abstract", "")
    abstract = re.sub(r"(?mi)^Keywords\s*:.*$", "", abstract)
    return {"main": body, "abstract": word_count(abstract)}


def docx_counts(path: Path, scope: list[str], target: dict | None = None) -> dict[str, int]:
    """Count the final Word file's sections, split on SectionHeading paragraphs.

    1.14.1 (B11): headings are judged by their semantic role (section_role), so 'Statements and
    Declarations', 'Compliance with Ethical Standards' or the journal's declarations_heading end
    the counted body exactly like 'Declarations'."""
    import zipfile
    from xml.etree import ElementTree as ET
    w = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    with zipfile.ZipFile(path) as zf:
        root = ET.fromstring(zf.read("word/document.xml"))
    names = {section_role(s, target) for s in scope}
    level1 = {"abstract", "references", "figure legends", "declarations", "tables",
              "supplementary figure legends", *names}
    # A structured abstract's 'Background'/'Results' subheadings never end the abstract.
    intro_names = {"introduction", main_text_headings(target or {})["Introduction"].casefold()}
    section, counts, refs = "front", {"main": 0, "abstract": 0}, 0
    for p in root.iter(w + "p"):
        text = "".join(t.text or "" for t in p.iter(w + "t")).strip()
        if not text:
            continue
        pstyle = p.find(f"{w}pPr/{w}pStyle")
        sid = pstyle.get(w + "val", "") if pstyle is not None else ""
        if re.match(r"(?i)^keywords\s*:", text):
            section = "keywords"
            continue
        # Structured-abstract subheadings (Results, Conclusions) do not end the abstract.
        role = section_role(text, target) if sid == "SectionHeading" else ""
        if sid == "SectionHeading" and role in level1 and not (
                section == "abstract" and text.casefold() not in intro_names):
            section = role
            continue
        if section == "abstract":
            counts["abstract"] += word_count(text)
        elif section in names:
            counts["main"] += word_count(text)
        elif section == "references":
            refs += 1
    counts["references"] = refs
    return counts
