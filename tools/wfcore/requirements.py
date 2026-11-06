"""1.18.0 (K1/K2): the journal's author guidelines as a checked list of requirements.

At S20 the agent turns 08_submission/guidelines_source.txt (line-numbered, wf guidelines
ingest) into 08_submission/guideline_requirements.json for the chosen article type. Every
entry quotes the guide verbatim with its line numbers and says how it is enforced:

    {"schema": 1, "journal": "...", "journal_epoch": 1, "article_type": "Original article",
     "requirements": [
       {"id": "R01", "category": "word_limits", "article_type": "Original article",
        "quote": "the main text must not exceed 3000 words", "lines": "L0003",
        "rule": {"field": "limits.main_text_words", "value": 3000}, "enforcement": "auto"},
       {"id": "R02", "category": "ethics_consent", "quote": "...", "lines": "L0010-L0011",
        "rule": {}, "enforcement": "manual", "article_type": "all"},
       {"id": "R03", ..., "enforcement": "n.a.", "reason": "applies to Review articles only"}],
     "not_mentioned": [{"category": "highlights", "searched": ["highlights", "key points"]}],
     "not_applicable": [{"lines": "L0040-L0052", "reason": "Case reports only"}]}

enforcement: auto (the engine measures it), builder (a builder applies a typed field),
manual (the agent records where the package meets it), portal (the user does it in the
submission system), n.a. (with a reason). Schema: reference/guideline_requirements.schema.json.
The gate guideline_requirements_mapped (checks/v1180.py) runs `problems()` below.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REQ_REL = "08_submission/guideline_requirements.json"
TARGET = "08_submission/target_journal.json"
STYLE = "08_submission/docx_style.json"

CATEGORIES = {
    "word_limits": "字数限制", "abstract_structure": "摘要结构", "keywords": "关键词",
    "title_page": "题名页", "running_title": "短标题", "highlights": "要点/Highlights",
    "section_headings": "章节标题与顺序", "references": "参考文献格式与数量",
    "citations": "正文引用", "figures": "图片", "tables": "表格",
    "supplementary": "补充材料", "declarations": "声明内容与顺序", "ethics_consent": "伦理与知情同意",
    "data_availability": "数据可用性", "ai_disclosure": "AI 使用声明",
    "conflicts_of_interest": "利益冲突/ICMJE 表", "funding": "基金",
    "author_contributions": "作者贡献/ORCID", "cover_letter": "投稿信",
    "required_uploads": "必需上传文件与格式", "layout": "行号/页码/版式",
    "language": "语言与拼写", "blinding": "盲审", "reporting_checklist": "报告规范清单",
    "article_type_rules": "文章类型特定要求",
}
ENFORCEMENT = ("auto", "builder", "manual", "portal", "n.a.")
OBLIGATION_RE = re.compile(
    r"(?i)\b(must|required|requires?|should|mandatory|please ensure|not exceed|maximum|"
    r"no more than|at least|limited to|are expected to|have to)\b")
ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,23}$")
NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
             "eight": 8, "nine": 9, "ten": 10, "twelve": 12, "fifteen": 15, "twenty": 20}
# Typed fields of target_journal.json that a requirement should source (fallback warning).
TYPED_FIELDS = ("limits.main_text_words", "limits.abstract_words", "limits.reference_limit",
                "limits.display_items", "limits.main_figures", "limits.main_tables",
                "limits.figure_legend_words", "abstract", "keywords", "title_page",
                "highlights", "key_points", "cover_letter", "required_uploads", "figure",
                "orcid_required", "running_title_position", "line_numbers", "figure_dpi",
                "declarations_order", "main_text_headings", "blinded_main_manuscript",
                "double_blind", "journal_requires_checklist", "si_format", "reference_separator")
# Typed fields a builder applies (enforcement "builder").
BUILDER_FIELDS = ("main_text_headings", "keywords.separator", "legend_style", "reference_separator",
                  "line_numbers", "abbreviation_list", "si_format", "supplementary_label",
                  "supplementary_aliases", "display_file_names", "separate_display_files",
                  "embed_figures", "word_tables", "keep_table_footnotes", "blinded_main_manuscript",
                  "double_blind", "running_title_position", "docx_style", "csl", "reference_rules",
                  "figure.formats", "figure.colour", "declarations_heading", "declarations_order",
                  "abstract.headings", "presentation", "figures_at_end", "language", "spelling",
                  "number_format")


def _json(path: Path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def load(project: Path) -> dict:
    data = _json(Path(project) / REQ_REL)
    return data if isinstance(data, dict) else {}


def norm(text: str) -> str:
    """Whitespace-normalised text with typographic quotes/dashes folded (quote matching)."""
    s = str(text or "")
    for a, b in (("\u2018", "'"), ("\u2019", "'"), ("\u201c", '"'), ("\u201d", '"'),
                 ("\u2013", "-"), ("\u2014", "-"), ("\u00a0", " "), ("\u2009", " ")):
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s).strip()


def line_numbers(spec) -> list[int]:
    """'L0003', 'L0040-L0046', ['L0003', 'L0007-L0009'] -> sorted line numbers."""
    from .guideingest import cited_lines
    parts = spec if isinstance(spec, list) else [spec]
    return sorted(set(cited_lines(" ".join(str(x) for x in parts if x is not None))))


def field_value(project: Path, target: dict, dotted: str):
    """target_journal.json value at a dotted path ('limits.main_text_words'); 'docx_style.x'
    reads 08_submission/docx_style.json."""
    parts = [p for p in str(dotted or "").split(".") if p]
    if not parts:
        return None
    node = target
    if parts[0] == "docx_style":
        node, parts = (_json(Path(project) / STYLE) or {}), parts[1:]
    for p in parts:
        if not isinstance(node, dict) or p not in node:
            return None
        node = node[p]
    return node


def _numbers(text: str) -> set[float]:
    out = {float(x.replace(",", "")) for x in re.findall(r"\d[\d,]*(?:\.\d+)?", text)
           if x.replace(",", "").replace(".", "", 1).isdigit()}
    out |= {float(v) for w, v in NUM_WORDS.items() if re.search(rf"(?i)\b{w}\b", text)}
    return out


def _prefix_match(field: str, names) -> bool:
    return any(field == n or field.startswith(n + ".") or n.startswith(field + ".") for n in names)


def obligation_lines(lines: dict[int, str]) -> list[int]:
    """Lines holding at least one sentence with an obligation marker."""
    out = []
    for n, text in sorted(lines.items()):
        for sent in re.split(r"(?<=[.;!?])\s+", text):
            if OBLIGATION_RE.search(sent):
                out.append(n)
                break
    return out


def _ranges(nums: list[int]) -> str:
    out, start, prev = [], None, None
    for n in nums:
        if start is None:
            start = prev = n
        elif n == prev + 1:
            prev = n
        else:
            out.append(f"L{start:04d}" + (f"-L{prev:04d}" if prev != start else ""))
            start = prev = n
    if start is not None:
        out.append(f"L{start:04d}" + (f"-L{prev:04d}" if prev != start else ""))
    return ", ".join(out)


def problems(project: Path) -> tuple[list[str], list[str]]:
    """(blocking problems, fallback warnings) of the requirement list (gate K2)."""
    from . import guideingest, journalepoch, journalspec
    from .compliance import measurable
    project = Path(project)
    data = load(project)
    if not data:
        return ([f"{REQ_REL} missing or not a JSON object: turn guidelines_source.txt into the "
                 "requirement list (reference/stage_details/S20_journal.md, 'Requirement list')"], [])
    lines = guideingest.source_lines(project)
    if not lines:
        return (["no 08_submission/guidelines_source.txt (wf journal lookup, or wf guidelines "
                 "ingest --from <saved guide> --url <official URL>)"], [])
    target = journalspec.load(project)
    out: list[str] = []
    name = journalepoch.target_name(project)
    if name and journalepoch.norm(data.get("journal", "")) != journalepoch.norm(name):
        out.append(f"requirement list is for '{data.get('journal')}', target journal is '{name}' "
                   "- build the list from this journal's own guide")
    if journalepoch.current(project) and data.get("journal_epoch") != journalepoch.number(project):
        out.append(f"guideline_requirements.json journal_epoch must be {journalepoch.number(project)}")
    reqs = data.get("requirements")
    if not isinstance(reqs, list) or not reqs:
        return out + ["requirements must be a non-empty list"], []
    covered: set[int] = set()
    seen_ids: set[str] = set()
    cats: set[str] = set()
    sourced_fields: list[str] = []
    for i, r in enumerate(reqs, 1):
        if not isinstance(r, dict):
            out.append(f"requirement #{i} is not an object")
            continue
        rid = str(r.get("id", ""))
        tag = rid or f"#{i}"
        if not ID_RE.match(rid):
            out.append(f"{tag}: id must be short (R01, FIG-2)")
        elif rid in seen_ids:
            out.append(f"{tag}: duplicate id")
        seen_ids.add(rid)
        cat, enf = r.get("category"), r.get("enforcement")
        if cat not in CATEGORIES:
            out.append(f"{tag}: category '{cat}' is not one of {', '.join(CATEGORIES)}")
        else:
            cats.add(cat)
        if enf not in ENFORCEMENT:
            out.append(f"{tag}: enforcement must be one of {', '.join(ENFORCEMENT)}")
        if not str(r.get("article_type", "")).strip():
            out.append(f"{tag}: article_type missing (the article type it applies to, or 'all')")
        nums = line_numbers(r.get("lines"))
        if not nums:
            out.append(f"{tag}: lines must cite guidelines_source.txt (L0012 or L0040-L0046)")
        missing = [n for n in nums if n not in lines]
        if missing:
            out.append(f"{tag}: cites line(s) not in guidelines_source.txt: {_ranges(missing[:6])}")
        covered |= set(nums)
        quote = norm(r.get("quote", ""))
        if len(quote) < 8:
            out.append(f"{tag}: quote the guide verbatim (>= 8 characters)")
        elif nums and not missing and quote not in norm(" ".join(lines[n] for n in nums)):
            out.append(f"{tag}: quote does not occur verbatim at {_ranges(nums)}")
        rule = r.get("rule") if isinstance(r.get("rule"), dict) else {}
        fld, chk = str(rule.get("field", "")).strip(), str(rule.get("check", "")).strip()
        if fld:
            sourced_fields.append(fld)
        if enf == "n.a." and len(str(r.get("reason", "")).strip()) < 8:
            out.append(f"{tag}: an n.a. requirement needs a reason (e.g. 'applies to Review "
                       "articles only')")
        if enf == "auto" and not measurable(fld, chk):
            out.append(f"{tag}: enforcement auto, but the engine measures no "
                       f"{'field ' + fld if fld else 'check ' + (chk or '(none)')}; use builder "
                       "or manual (reference/stage_details/S20_journal.md lists the measured "
                       "fields)")
        if enf == "builder" and not (fld and _prefix_match(fld, BUILDER_FIELDS)):
            out.append(f"{tag}: enforcement builder needs rule.field of a typed field a builder "
                       f"applies ({', '.join(BUILDER_FIELDS[:8])}, ...)")
        if enf in ("auto", "builder") and fld:
            typed = field_value(project, target, fld)
            if typed is None:
                out.append(f"{tag}: rule.field {fld} is not set in target_journal.json")
                continue
            if "value" in rule and rule["value"] != typed:
                out.append(f"{tag}: rule value {rule['value']!r} differs from target_journal.json "
                           f"{fld} = {typed!r}")
            if isinstance(typed, (int, float)) and not isinstance(typed, bool):
                found = _numbers(quote)
                if found and float(typed) not in found:
                    out.append(f"{tag}: the guide says {sorted(int(x) if x.is_integer() else x for x in found)} "
                               f"but target_journal.json {fld} = {typed} (extract and typed field "
                               "disagree)")
    nm = data.get("not_mentioned") if isinstance(data.get("not_mentioned"), list) else []
    for e in nm:
        if not isinstance(e, dict) or e.get("category") not in CATEGORIES:
            out.append(f"not_mentioned entry {e!r}: needs a known category")
            continue
        terms = [str(t).strip() for t in e.get("searched") or [] if str(t).strip()]
        if len(terms) < 2:
            out.append(f"not_mentioned {e['category']}: list the terms searched (>= 2)")
        for t in terms:
            hit = next((n for n, s in sorted(lines.items())
                        if re.search(rf"(?i)(?<!\w){re.escape(t)}(?!\w)", s)), None)
            if hit is not None:
                out.append(f"not_mentioned {e['category']}: '{t}' does occur at L{hit:04d}; map "
                           "that rule")
                break
        cats.add(e["category"])
    absent = [c for c in CATEGORIES if c not in cats]
    if absent:
        out.append("no requirement and no 'not mentioned' entry (terms searched) for: "
                   + ", ".join(absent))
    for e in data.get("not_applicable") or []:
        nums = line_numbers(e.get("lines") if isinstance(e, dict) else None)
        if not nums or len(str((e or {}).get("reason", "")).strip()) < 8:
            out.append(f"not_applicable entry {e!r}: needs lines and a reason")
            continue
        covered |= set(nums)
    uncovered = [n for n in obligation_lines(lines) if n not in covered]
    if uncovered:
        out.append(f"{len(uncovered)} guideline line(s) state an obligation (must/required/should/"
                   f"maximum/...) that no requirement or n.a. range covers: {_ranges(uncovered)[:300]}")
    warns = []
    for f in TYPED_FIELDS:
        val = field_value(project, target, f)
        if val is None or val is False or val in ("", [], {}):
            continue
        if not _prefix_match(f, sourced_fields):
            warns.append(f)
    return out, (["typed field(s) without a requirement source (fallback, check the guide): "
                  + ", ".join(warns)] if warns else [])
