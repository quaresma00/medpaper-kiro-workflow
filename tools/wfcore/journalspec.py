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
                "main_figures", "main_tables")
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
    unknown = sorted(set(block) - set(LIMIT_FIELDS) - {"source", "notes"})
    if unknown:
        problems.append("limits has unknown field(s): " + ", ".join(unknown))
    if not str(block.get("source", "")).strip():
        problems.append("limits.source must quote the official rule (or state the guide is silent)")
    return out, problems


def word_count_scope(target: dict) -> list[str]:
    scope = target.get("word_count_scope")
    if isinstance(scope, list) and scope and all(isinstance(x, str) for x in scope):
        return scope
    return list(DEFAULT_SCOPE)


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


def si_format(target: dict) -> str:
    value = str(target.get("si_format", "pdf")).strip().lower()
    return value if value in ("pdf", "docx") else "pdf"


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


def docx_counts(path: Path, scope: list[str]) -> dict[str, int]:
    """Count the final Word file's sections, split on SectionHeading paragraphs."""
    import zipfile
    from xml.etree import ElementTree as ET
    w = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    with zipfile.ZipFile(path) as zf:
        root = ET.fromstring(zf.read("word/document.xml"))
    names = {s.casefold() for s in scope}
    level1 = {"abstract", "references", "figure legends", "declarations and statements",
              "declarations", "tables", "supplementary figure legends", *names}
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
        if sid == "SectionHeading" and text.casefold() in level1 and not (
                section == "abstract" and text.casefold() != "introduction"):
            section = text.casefold()
            continue
        if section == "abstract":
            counts["abstract"] += word_count(text)
        elif section in names:
            counts["main"] += word_count(text)
        elif section == "references":
            refs += 1
    counts["references"] = refs
    return counts
