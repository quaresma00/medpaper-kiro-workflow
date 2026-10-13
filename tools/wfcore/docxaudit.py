"""Word-package audits shared by tools/manuscript/build_docx.py and the docx_bundle_ready gate.

Stdlib only. Each function takes the parsed document.xml root (and, where needed, the raw XML
parts) and returns human-readable problems; an empty list means the property holds.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import journalspec

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W}
CODE_STYLES = {"SourceCode"}
LEGEND_HEAD_RE = re.compile(r"^((?:Figure|Fig\.?)\s+S?\d+)\.?\s*(.*)$", re.I)
REF_NUMBER_RE = re.compile(r"^\s*(\[\d+\]|\d+\.?)$")


def canon_figure_id(value: str) -> str:
    value = re.sub(r"\s+", " ", value.strip().rstrip(".")).casefold()
    return re.sub(r"^fig\.?\s", "figure ", value)


def _ptext(p) -> str:
    return "".join(t.text or "" for t in p.findall(".//w:t", NS)).strip()


def _style_id(p) -> str:
    node = p.find("w:pPr/w:pStyle", NS)
    return "" if node is None else node.get(f"{{{W}}}val", "")


def paragraphs(root) -> list[tuple[str, str, object]]:
    return [(_ptext(p), _style_id(p), p) for p in root.findall(".//w:body/w:p", NS)]


def plan_counts(project: Path) -> dict:
    """Main figure ids, main table ids and their files, from the artifact plan."""
    path = Path(project) / "01_protocol/artifact_plan.json"
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        plan = {}
    def ids(group):
        return [str(e.get("id", "")).strip() for e in plan.get(group, []) if str(e.get("id", "")).strip()]
    return {"main_figures": ids("main_figures"), "supp_figures": ids("supp_figures"),
            "main_tables": ids("main_tables"), "supp_tables": ids("supp_tables"), "plan": plan}


def audit_spec(project: Path) -> dict:
    target = journalspec.load(project)
    counts = plan_counts(project)
    return {"legend_style": journalspec.legend_style(target),
            "reference_separator": journalspec.reference_separator(target),
            "embed_figures": target.get("embed_figures") is True,
            "word_tables": target.get("word_tables") is True,
            "main_figures": counts["main_figures"], "supp_figures": counts["supp_figures"],
            "main_tables": counts["main_tables"]}


def legend_problems(root, expected: list[str], cap: int, label: str = "",
                    supplementary: list[str] | None = None) -> list[str]:
    paras = [(t, s) for t, s, _ in paragraphs(root) if t]
    try:
        start = next(i for i, (value, _) in enumerate(paras)
                     if value.casefold() == "figure legends") + 1
    except StopIteration:
        return ["Figure legends heading is missing"]
    heads: list[tuple[int, str, str]] = []
    for i in range(start, len(paras)):
        value, sid = paras[i]
        if sid == "SectionHeading" and value.casefold() in ("tables", "supplementary figure legends"):
            break
        m = LEGEND_HEAD_RE.match(value)
        if m and sid == "SectionHeading":
            heads.append((i, m.group(1), m.group(2)))
    blocks: dict[str, tuple[int, int]] = {}
    for j, (idx, fid, suffix) in enumerate(heads):
        end = heads[j + 1][0] if j + 1 < len(heads) else len(paras)
        content = "\n".join([suffix] + [v for v, _ in paras[idx + 1:end]]).strip()
        blocks[canon_figure_id(fid)] = (len(content),
                                        len(re.findall(r"\b[A-Za-z][A-Za-z0-9'-]*\b", content)))
    wanted = {canon_figure_id(x): x for x in expected}
    supp = {canon_figure_id(x) for x in (supplementary or [])}
    problems: list[str] = []
    seen = [canon_figure_id(h[1]) for h in heads]
    dups = sorted({x for x in seen if seen.count(x) > 1})
    if dups:
        problems.append("duplicate figure legend heading(s): " + ", ".join(dups))
    for idx, fid, _ in heads:
        if idx + 1 < len(paras) and re.match(rf"^{re.escape(fid)}\b", paras[idx + 1][0], re.I):
            problems.append(f"{fid} is repeated at the start of its legend body")
    for key, display in wanted.items():
        if key not in blocks:
            problems.append(f"{label}Figure legends lacks {display}")
            continue
        chars, words = blocks[key]
        if chars < 40:
            problems.append(f"{label}{display} legend is only {chars} characters")
        if words > cap:
            problems.append(f"{label}{display} legend is {words} words (maximum {cap})")
    misplaced = sorted(k for k in set(blocks) - set(wanted) if k in supp or re.match(r"figure s\d", k))
    if misplaced:
        problems.append(f"{label}supplementary legend(s) in the main-text Figure legends: "
                        + ", ".join(misplaced) + " - they go with the supplementary file")
    extras = sorted(set(blocks) - set(wanted) - set(misplaced))
    if extras:
        problems.append(f"{label}unplanned figure legend(s): " + ", ".join(extras))
    return problems


def legend_style_problems(root, style: dict) -> list[str]:
    """Prefix, bold label, panel-label case and end punctuation, as configured at S20."""
    problems: list[str] = []
    prefix = style.get("prefix", "Figure")
    in_legends = False
    for text, sid, p in paragraphs(root):
        if not text:
            continue
        if sid == "SectionHeading" and text.casefold() == "figure legends":
            in_legends = True
            continue
        if not in_legends:
            continue
        if sid == "SectionHeading" and text.casefold() in ("tables", "supplementary figure legends"):
            break
        m = LEGEND_HEAD_RE.match(text)
        if m and sid == "SectionHeading":
            label = m.group(1)
            used = re.match(r"^(Figure|Fig\.?)", label).group(1)
            if used != prefix:
                problems.append(f"legend label '{label}' does not use the journal prefix '{prefix}'")
            runs = [r for r in p.findall(".//w:r", NS)
                    if "".join(t.text or "" for t in r.findall("w:t", NS)).strip()]
            if runs:
                bnode = runs[0].find("w:rPr/w:b", NS)
                # SectionHeading is a bold paragraph style; an explicit run property wins.
                is_bold = (bnode.get(f"{{{W}}}val", "true") not in ("0", "false")
                           if bnode is not None else True)
                if bool(style.get("bold", True)) != is_bold:
                    problems.append(f"legend label '{label}' bold={is_bold}, journal wants "
                                    f"bold={bool(style.get('bold', True))}")
            punct = style.get("end_punctuation", "any")
            if punct == "." and not text.rstrip().endswith("."):
                problems.append(f"legend heading '{label}' must end with a full stop")
            elif punct == "none" and text.rstrip().endswith("."):
                problems.append(f"legend heading '{label}' must not end with a full stop")
            continue
        case = style.get("panel_label_case", "any")
        labels = re.findall(r"\(([A-Ha-h])\)", text)
        if case == "lower" and any(x.isupper() for x in labels):
            problems.append("legend panel labels must be lower case, e.g. (a)")
        elif case == "upper" and any(x.islower() for x in labels):
            problems.append("legend panel labels must be upper case, e.g. (A)")
    return sorted(set(problems))


def reference_problems(root, separator: str = "space") -> list[str]:
    """Numbered entries use "N. " + text (one space, no TAB) by default, or number + TAB with a
    hanging indent when the journal sets reference_separator "tab"; no dangling colon."""
    problems: list[str] = []
    entries = [p for t, s, p in paragraphs(root) if t and s == "Bibliography"]
    if not entries:
        return problems
    if separator != "tab":
        for p in entries:
            if p.find(".//w:r/w:tab", NS) is not None or "\t" in _ptext(p):
                problems.append("reference entries contain a TAB; use the number + one space")
                break
        for p in entries:
            if re.match(r"^\s*(\[\d+\]|\d+\.)(?:\s{2,}|\u00a0)", _ptext(p)):
                problems.append("reference number is followed by more than one space")
                break
        for p in entries:
            if re.search(r"(?<=[\d)])\s*[:;]\s*\.?\s*(?:doi\b|$)", _ptext(p), re.I):
                problems.append(f"reference has a dangling ':' or ';' with no pages: {_ptext(p)[:80]}")
                break
        return problems
    for p in entries:
        ind = p.find("w:pPr/w:ind", NS)
        if ind is None or int(ind.get(f"{{{W}}}hanging", "0") or 0) <= 0:
            problems.append("reference entries lack a hanging indent")
            break
    numbered = 0
    for p in entries:
        lead, tab = "", False
        for r in p.findall(".//w:r", NS):
            for child in r:
                if child.tag == f"{{{W}}}t":
                    lead += child.text or ""
                elif child.tag == f"{{{W}}}tab":
                    tab = True
                    break
            if tab:
                break
        if tab and REF_NUMBER_RE.match(lead):
            numbered += 1
        elif re.match(r"^\s*(\[\d+\]|\d+\.)", _ptext(p)):
            problems.append("numbered reference entries separate the number with a space, not a TAB")
            break
    for p in entries:
        if re.search(r"(?<=[\d)])\s*[:;]\s*\.?\s*(?:doi\b|$)", _ptext(p), re.I):
            problems.append(f"reference has a dangling ':' or ';' with no pages: {_ptext(p)[:80]}")
            break
    return problems


def footer_page_problems(xmls: dict[str, bytes]) -> list[str]:
    document = xmls.get("word/document.xml", b"")
    if b"footerReference" not in document:
        return ["no footer is attached to the document (automatic page numbers missing)"]
    for name, blob in xmls.items():
        if name.startswith("word/footer") and name.endswith(".xml") and re.search(
                rb'(?:w:instr="\s*PAGE\b|<w:instrText[^>]*>\s*PAGE\b)', blob):
            return []
    return ["footer has no PAGE field (automatic page numbers missing)"]


def display_problems(root, spec: dict, role: str) -> list[str]:
    if role != "manuscript":
        return []
    problems = []
    drawings = len(root.findall(".//w:drawing", NS))
    nfig = len(spec.get("main_figures", []))
    if spec.get("embed_figures"):
        if drawings < nfig:
            problems.append(f"journal requires embedded figures: {drawings}/{nfig} main figures embedded")
    elif drawings:
        problems.append("figures are embedded but target_journal.json does not set embed_figures")
    tables = len(root.findall(".//w:body/w:tbl", NS))
    ntab = len(spec.get("main_tables", []))
    if spec.get("word_tables") and tables < ntab:
        problems.append(f"journal requires Word tables: {tables}/{ntab} main tables present")
    return problems


def pipeline_code_problems(text: str) -> list[str]:
    hits = sorted({m.group(0)[:40] for m in journalspec.PIPELINE_CODE_RE.finditer(text)})
    if hits:
        return ["pipeline-internal code or local path in a submission file: " + ", ".join(hits[:5])]
    return []


def extra_problems(name: str, xmls: dict[str, bytes], root, role: str, spec: dict | None,
                   cap: int = 180) -> list[str]:
    """Everything 1.8.0 added: page numbers, references, legends, displays, SI hygiene."""
    out = [f"{name}: {p}" for p in footer_page_problems(xmls)]
    if role == "manuscript":
        out += [f"{name}: {p}" for p in reference_problems(
            root, (spec or {}).get("reference_separator", "space"))]
        if spec is not None:
            out += [f"{name}: {p}" for p in legend_style_problems(root, spec["legend_style"])]
            out += [f"{name}: {p}" for p in display_problems(root, spec, role)]
    if role in ("supplementary", "manuscript"):
        text = "\n".join(t for t, _, _ in paragraphs(root))
        out += [f"{name}: {p}" for p in pipeline_code_problems(text)]
    return out
