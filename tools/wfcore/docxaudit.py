"""Word-package audits shared by tools/manuscript/build_docx.py and the docx_bundle_ready gate.

Stdlib only. Each function takes the parsed document.xml root (and, where needed, the raw XML
parts) and returns human-readable problems; an empty list means the property holds.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from xml.etree import ElementTree as ET

from . import journalspec

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
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


# 1.11.0 (#1e) set keepNext/keepLines to bind captions, tables and legends; Word shows each as
# a black square. 1.13.0 (#10): none may remain anywhere (keep_problems); layout is structural.
HEADING_STYLES = {"SectionHeading", "ManuscriptTitle"}
TABLE_CAPTION_RE = re.compile(r"^(?:Supplementary\s+)?Table\s+S?\d+[.:]", re.I)


def is_heading(style_id: str) -> bool:
    return style_id in HEADING_STYLES or style_id.casefold().startswith(("heading", "title"))


def _has(p, tag: str) -> bool:
    return p.find(f"w:pPr/w:{tag}", NS) is not None


def heading_keep_problems(root) -> list[str]:
    bad = [_ptext(p)[:30] for p in root.iter(f"{{{W}}}p")
           if is_heading(_style_id(p)) and (_has(p, "keepNext") or _has(p, "keepLines"))
           and not TABLE_CAPTION_RE.match(_ptext(p)) and not LEGEND_HEAD_RE.match(_ptext(p))]
    return [f"heading(s) carry keepNext/keepLines (collapse marker): {bad[:3]}"] if bad else []


KEEP_MARKERS = ("keepNext", "keepLines", "pageBreakBefore")


def table_footnote_rows(root) -> set[int]:
    """1.14.0 (D3): ids of the paragraphs in the last row of each table - the only place a
    keepNext may stand (it keeps the table footnote on the table's page)."""
    out: set[int] = set()
    for tbl in root.iter(f"{{{W}}}tbl"):
        rows = tbl.findall("w:tr", NS)
        if rows:
            out.update(id(p) for p in rows[-1].iter(f"{{{W}}}p"))
    return out


def _allowed_keep(p, allowed: set[int]) -> bool:
    """A last-table-row paragraph carrying keepNext and no other keep marker."""
    return id(p) in allowed and _has(p, "keepNext") and not any(
        _has(p, t) for t in KEEP_MARKERS if t != "keepNext")


def stray_markers(part, tag: str) -> int:
    """How many `tag` markers in an XML part stand anywhere but the D3 table-footnote row."""
    nodes = part.findall(f".//w:{tag}", NS)
    if tag != "keepNext" or not nodes:
        return len(nodes)
    allowed = table_footnote_rows(part)
    ok = sum(1 for p in part.iter(f"{{{W}}}p") if _allowed_keep(p, allowed))
    return max(0, len(nodes) - ok)
# An embedded figure keeps at least this share of the usable page height (or its natural size
# if smaller); a legend too long to share that page continues on the next page by design.
# build_docx.figure_size and keep_problems share this value.
FIGURE_MIN_PAGE_FRACTION = 0.55
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"


def style_marker_problems(styles_root) -> list[str]:
    """1.13.0 (#10): styles (followed through basedOn) and docDefaults carrying a keep marker."""
    if styles_root is None:
        return []
    styles = {s.get(f"{{{W}}}styleId"): s for s in styles_root.iter(f"{{{W}}}style")}

    def own(s) -> bool:
        ppr = s.find("w:pPr", NS)
        return ppr is not None and any(ppr.find(f"w:{t}", NS) is not None for t in KEEP_MARKERS)
    bad = []
    for sid, s in styles.items():
        cur, seen = s, set()
        while cur is not None and id(cur) not in seen:
            seen.add(id(cur))
            if own(cur):
                bad.append(sid)
                break
            base = cur.find("w:basedOn", NS)
            cur = styles.get(base.get(f"{{{W}}}val")) if base is not None else None
    dd = styles_root.find("w:docDefaults/w:pPrDefault/w:pPr", NS)
    if dd is not None and any(dd.find(f"w:{t}", NS) is not None for t in KEEP_MARKERS):
        bad.append("docDefaults")
    return [f"style(s) carry keepNext/keepLines/pageBreakBefore (directly or via basedOn): "
            f"{sorted(bad)[:5]}"] if bad else []


def _usable_height_in(body) -> float:
    sp = body.find("w:sectPr", NS) if body is not None else None
    if sp is None:
        return 9.7
    pg, mar = sp.find("w:pgSz", NS), sp.find("w:pgMar", NS)
    h = int((pg.get(f"{{{W}}}h") if pg is not None else None) or 16838)
    top = int((mar.get(f"{{{W}}}top") if mar is not None else None) or 1440)
    bottom = int((mar.get(f"{{{W}}}bottom") if mar is not None else None) or 1440)
    return (h - top - bottom) / 1440


def keep_problems(root, styles_root=None) -> list[str]:
    """1.13.0 (#10): the Word layout audit (replaces the 1.11 keep-with-next audit).

    Zero keepNext/keepLines/pageBreakBefore in document.xml and in the effective styles (1.14.0
    D3: except keepNext on the last row of each table, which keeps its footnote with it), plus
    structure: every table row cantSplit; each embedded figure starts after an explicit page
    break, is followed by its legend, and image + estimated legend fit the usable page
    height. (Tables starting their own section are checked by table_layout_problems.)"""
    body = root.find("w:body", NS)
    if body is None:
        return ["no document body"]
    out = []
    allowed = table_footnote_rows(root)  # 1.14.0 (D3): keepNext on each table's last row only
    marked = [(_ptext(p)[:30] or "(empty)") for p in root.iter(f"{{{W}}}p")
              if any(_has(p, t) for t in KEEP_MARKERS) and not _allowed_keep(p, allowed)]
    if marked:
        out.append(f"{len(marked)} paragraph(s) carry keepNext/keepLines/pageBreakBefore (black "
                   f"squares in Word): {marked[:3]}")
    out += style_marker_problems(styles_root)
    kids = [k for k in body if k.tag in (f"{{{W}}}p", f"{{{W}}}tbl")]
    usable = _usable_height_in(body)
    for i, el in enumerate(kids):
        if el.tag == f"{{{W}}}tbl":
            if any(r.find("w:trPr/w:cantSplit", NS) is None for r in el.findall("w:tr", NS)):
                out.append("a table row can split across pages (no cantSplit)")
            continue
        if el.find(".//w:drawing", NS) is None:
            continue
        j = i - 1
        while j >= 0 and kids[j].tag == f"{{{W}}}p" \
                and kids[j].find(".//w:br[@w:type='page']", NS) is None \
                and kids[j].find("w:pPr/w:sectPr", NS) is None and i - j <= 2 \
                and (not _ptext(kids[j]) or is_heading(_style_id(kids[j]))):
            j -= 1
        if j < 0 or (kids[j].find(".//w:br[@w:type='page']", NS) is None
                     and kids[j].find("w:pPr/w:sectPr", NS) is None):
            out.append("an embedded figure does not start on a new page (no page-break run "
                       "before it)")
        nxt = kids[i + 1] if i + 1 < len(kids) else None
        if nxt is None or nxt.tag != f"{{{W}}}p" or not LEGEND_HEAD_RE.match(_ptext(nxt)):
            out.append("an embedded figure is not followed by its legend")
            continue
        ext = el.find(f".//{{{WP}}}extent")
        img_h = int(ext.get("cy", "0")) / 914400 if ext is not None else 0.0
        legend_chars, k = 0, i + 1
        while k < len(kids) and kids[k].tag == f"{{{W}}}p" \
                and kids[k].find(".//w:br[@w:type='page']", NS) is None \
                and kids[k].find(".//w:drawing", NS) is None and k - i <= 12:
            legend_chars += len(_ptext(kids[k])) + 60
            k += 1
        legend_h = legend_chars / 95 * 0.25
        floor = usable * FIGURE_MIN_PAGE_FRACTION
        # Not a defect: the image is no larger than the readable floor, or the legend is too
        # long to share a page with a readable image - the legend then continues overleaf.
        by_design = img_h <= floor + 0.05 or legend_h > usable - floor
        if img_h + legend_h > usable + 0.05 and not by_design:
            out.append(f"figure '{_ptext(nxt)[:24]}': image ({img_h:.1f} in) and legend do not "
                       f"fit one page ({usable:.1f} in usable)")
    return sorted(set(out))


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
            "main_tables": counts["main_tables"],
            "line_numbers": journalspec.line_numbers(target),
            "table_orientation": table_overrides(project, counts["plan"])}


def line_number_problems(root, mode: str) -> list[str]:
    """1.12.0 (C7): every section carries w:lnNumType with the journal's restart rule."""
    if mode not in ("continuous", "per_page"):
        return []
    want = "continuous" if mode == "continuous" else "newPage"
    sects = root.findall(".//w:sectPr", NS)
    bad = [i + 1 for i, sp in enumerate(sects)
           if (ln := sp.find("w:lnNumType", NS)) is None
           or (ln.get(f"{{{W}}}restart") or "newPage") != want]
    if not sects or bad:
        return [f"line numbers ({mode}) required by the journal are missing or wrong in "
                f"section(s) {bad or [1]}; rebuild with build_docx.py"]
    return []


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


_PAGE_FIELD_RE = re.compile(rb'(?:w:instr="\s*PAGE\b|<w:instrText[^>]*>\s*PAGE\b)')


def footer_page_problems(xmls: dict[str, bytes]) -> list[str]:
    document = xmls.get("word/document.xml", b"")
    if b"footerReference" not in document:
        return ["no footer is attached to the document (automatic page numbers missing)"]
    footers = {n: b for n, b in xmls.items() if n.startswith("word/footer") and n.endswith(".xml")}
    if not any(_PAGE_FIELD_RE.search(b) for b in footers.values()):
        return ["footer has no PAGE field (automatic page numbers missing)"]
    # 1.8.1: every section shows the page number. Later sections inherit the first section's
    # footer (no own reference) or reference a footer that also has PAGE; numbering continues.
    try:
        root = ET.fromstring(document)
    except ET.ParseError:
        return []
    rels = {}
    try:
        for rel in ET.fromstring(xmls.get("word/_rels/document.xml.rels", b"<x/>")):
            rels[rel.get("Id")] = "word/" + rel.get("Target", "").lstrip("/").removeprefix("word/")
    except ET.ParseError:
        pass
    sects = root.findall(".//w:sectPr", NS)
    problems = []
    for i, sp in enumerate(sects):
        refs = [r for r in sp.findall("w:footerReference", NS)
                if r.get(f"{{{W}}}type", "default") == "default"]
        if i == 0 and not refs:
            problems.append("the first section has no footer (page numbers missing)")
        for r in refs:
            blob = footers.get(rels.get(r.get(f"{{{R}}}id", ""), ""), b"")
            if rels and not _PAGE_FIELD_RE.search(blob):
                problems.append(f"section {i + 1} footer has no PAGE field")
        start = sp.find("w:pgNumType", NS)
        if i and start is not None and start.get(f"{{{W}}}start"):
            problems.append(f"section {i + 1} restarts page numbering")
    return problems


# ---------------------------------------------------------------------------
# 1.8.1 Word tables: true three-line borders, one table per page, orientation per table.
# ---------------------------------------------------------------------------
TABLE_ID_RE = re.compile(r"^((?:Supplementary\s+)?Table\s+S?\d+)\b", re.I)
TABLE_RULE_THICK, TABLE_RULE_THIN = 12, 6  # eighths of a point: 1.5 pt and 0.75 pt
TABLE_CHAR_CAP = 40   # longer cells wrap; they do not widen the table further
TABLE_MAX_PORTRAIT_COLUMNS = 7


def table_width_estimate(col_chars: list[int], font_pt: float) -> int:
    """Estimated natural table width in twips (average glyph ~0.5 em + default cell margins)."""
    return int(sum(min(c, TABLE_CHAR_CAP) * font_pt * 10 + 216 for c in col_chars))


def table_orientation(col_chars: list[int], font_pt: float, text_width: int,
                      override: str = "auto") -> str:
    if override in ("portrait", "landscape"):
        return override
    if (len(col_chars) > TABLE_MAX_PORTRAIT_COLUMNS
            or table_width_estimate(col_chars, font_pt) > text_width):
        return "landscape"
    return "portrait"


def table_overrides(project: Path, plan: dict | None = None) -> dict[str, str]:
    """{canonical table id: portrait|landscape|auto} from artifact_plan entries
    ("orientation") or target_journal.json tables.<id>.orientation; the plan wins."""
    out: dict[str, str] = {}
    target = journalspec.load(project)
    tables = target.get("tables") if isinstance(target.get("tables"), dict) else {}
    for key, val in tables.items():
        if isinstance(val, dict) and val.get("orientation") in ("portrait", "landscape", "auto"):
            out[canon_figure_id(str(key))] = val["orientation"]
    plan = plan if plan is not None else plan_counts(project)["plan"]
    for e in plan.get("main_tables", []) if isinstance(plan, dict) else []:
        if isinstance(e, dict) and e.get("orientation") in ("portrait", "landscape", "auto"):
            out[canon_figure_id(str(e.get("id", "")))] = e["orientation"]
    return out


def _cell_text(tc) -> str:
    return " ".join(_ptext(p) for p in tc.findall("w:p", NS)).strip()


def _span(tc) -> int:
    node = tc.find("w:tcPr/w:gridSpan", NS)
    return int(node.get(f"{{{W}}}val", "1")) if node is not None else 1


def word_table_columns(tbl) -> list[int]:
    """Max text length per grid column over unspanned cells (same rule the builder uses)."""
    ncol = len(tbl.findall("w:tblGrid/w:gridCol", NS))
    chars = [0] * ncol
    for tr in tbl.findall("w:tr", NS):
        col = 0
        for tc in tr.findall("w:tc", NS):
            span = _span(tc)
            if span == 1 and col < ncol:
                chars[col] = max(chars[col], len(_cell_text(tc)))
            col += span
    return chars


def _side(tc, side: str) -> tuple[str, int]:
    node = tc.find(f"w:tcPr/w:tcBorders/w:{side}", NS)
    if node is None:
        return "", 0
    return node.get(f"{{{W}}}val", ""), int(node.get(f"{{{W}}}sz", "0") or 0)


def _ruled(val: str) -> bool:
    return val not in ("", "nil", "none")


def _sect_orientation(sp) -> str:
    pg = sp.find("w:pgSz", NS)
    if pg is None:
        return "portrait"
    w, h = int(pg.get(f"{{{W}}}w", "0") or 0), int(pg.get(f"{{{W}}}h", "0") or 0)
    if pg.get(f"{{{W}}}orient") == "landscape" and w > h:
        return "landscape"
    return "portrait" if w <= h and pg.get(f"{{{W}}}orient") != "landscape" else "mixed"


def _text_width(sp) -> int:
    pg, mar = sp.find("w:pgSz", NS), sp.find("w:pgMar", NS)
    if pg is None:
        return 9026
    w = min(int(pg.get(f"{{{W}}}w", "11906")), int(pg.get(f"{{{W}}}h", "16838")))
    if mar is None:
        return w - 2880
    return w - int(mar.get(f"{{{W}}}left", "1440")) - int(mar.get(f"{{{W}}}right", "1440"))


def table_layout_problems(root, overrides: dict[str, str] | None = None) -> list[str]:
    """Three-line borders, a page/section break before each table, orientation per table."""
    body = root.find("w:body", NS)
    if body is None:
        return []
    kids = [k for k in body if k.tag in (f"{{{W}}}p", f"{{{W}}}tbl")]  # skip bookmarks
    body_sect = body.find("w:sectPr", NS)
    text_width = _text_width(body_sect) if body_sect is not None else 9026
    problems: list[str] = []
    for i, tbl in enumerate(kids):
        if tbl.tag != f"{{{W}}}tbl":
            continue
        # Caption (and the Tables heading) above the table, then a section break before them.
        label, j = f"table {i}", i - 1
        while j >= 0 and kids[j].tag == f"{{{W}}}p" and _ptext(kids[j]) \
                and kids[j].find("w:pPr/w:sectPr", NS) is None and i - j <= 3:
            m = TABLE_ID_RE.match(_ptext(kids[j]))
            if m and label.startswith("table "):
                label = m.group(1)
            j -= 1
        broken = j >= 0 and (kids[j].find("w:pPr/w:sectPr", NS) is not None
                             or kids[j].find(".//w:br[@w:type='page']", NS) is not None)
        if not broken:
            problems.append(f"{label} does not start on a new page (no section/page break before it)")
        tblb = tbl.find("w:tblPr/w:tblBorders", NS)
        if tblb is not None and any(_ruled(n.get(f"{{{W}}}val", "")) for n in tblb):
            problems.append(f"{label}: table-level borders are set; three-line rules must be cell borders")
        rows = tbl.findall("w:tr", NS)
        if not rows:
            continue
        nhead = 0
        for tr in rows:
            if tr.find("w:trPr/w:tblHeader", NS) is None:
                break
            nhead += 1
        nhead = max(1, min(nhead, len(rows) - 1)) if len(rows) > 1 else 1
        last = len(rows) - 1
        for r, tr in enumerate(rows):
            for tc in tr.findall("w:tc", NS):
                top, bottom = _side(tc, "top"), _side(tc, "bottom")
                if r == 0 and (not _ruled(top[0]) or top[1] < TABLE_RULE_THICK):
                    problems.append(f"{label}: top rule missing on the header row")
                if r == nhead - 1 and not _ruled(bottom[0]):
                    problems.append(f"{label}: rule under the (last) header row missing")
                if r == last and (not _ruled(bottom[0]) or bottom[1] < TABLE_RULE_THICK):
                    problems.append(f"{label}: bottom rule missing on the last body row")
                if r and _ruled(top[0]):
                    problems.append(f"{label}: inner horizontal rule (top border on row {r + 1})")
                if r not in (nhead - 1, last) and _ruled(bottom[0]):
                    problems.append(f"{label}: inner horizontal rule (bottom border on row {r + 1})")
                if any(_ruled(_side(tc, s)[0]) for s in ("left", "right", "start", "end",
                                                          "insideV", "insideH")):
                    problems.append(f"{label}: vertical/inner cell border present")
        # Its own section: the next sectPr after the table closes the table's section.
        close = next((k for k in kids[i + 1:] if k.tag == f"{{{W}}}tbl"
                      or k.find("w:pPr/w:sectPr", NS) is not None), None)
        if close is None or close.tag == f"{{{W}}}tbl":
            problems.append(f"{label}: no section break after the table (next content shares its page)")
            continue
        sp = close.find("w:pPr/w:sectPr", NS)
        font = 12.0
        sz = tbl.find(".//w:r/w:rPr/w:sz", NS)
        if sz is not None:
            font = int(sz.get(f"{{{W}}}val", "24")) / 2
        want = table_orientation(word_table_columns(tbl), font, text_width,
                                 (overrides or {}).get(canon_figure_id(label), "auto"))
        got = _sect_orientation(sp)
        if got != want:
            problems.append(f"{label}: page orientation {got}, expected {want}")
    return sorted(set(problems))


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
    if spec.get("word_tables") and tables:
        problems += table_layout_problems(root, spec.get("table_orientation"))
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
            out += [f"{name}: {p}" for p in line_number_problems(root, spec.get("line_numbers", "none"))]
    if role in ("supplementary", "manuscript"):
        text = "\n".join(t for t, _, _ in paragraphs(root))
        out += [f"{name}: {p}" for p in pipeline_code_problems(text)]
    return out


# ---------------------------------------------------------------------------
# 1.9.0 (#13): double-blind review files carry no author identity
# ---------------------------------------------------------------------------
REVIEW_EXEMPT_ROLES = {"title_page", "cover_letter", "copyright_form", "author_form"}


def identity_strings(project) -> list[str]:
    """Author names and e-mail addresses from 00_input/author_info.json."""
    import json as _json
    from pathlib import Path as _Path
    try:
        info = _json.loads((_Path(project) / "00_input/author_info.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out: set[str] = set()

    def person(p) -> None:
        if isinstance(p, dict):
            for key in ("name", "full_name", "email"):
                if isinstance(p.get(key), str) and len(p[key].strip()) >= 4:
                    out.add(p[key].strip())
        elif isinstance(p, str) and len(p.strip()) >= 4:
            out.add(p.strip())
    for a in info.get("authors", []) if isinstance(info.get("authors"), list) else []:
        person(a)
    person(info.get("corresponding"))
    return sorted(out, key=len, reverse=True)


def blinding_problems(path, ids: list[str]) -> list[str]:
    """Author names/e-mails in a review-facing DOCX (body, headers, notes, docProps) or PDF."""
    import re as _re
    import zipfile as _zip
    from pathlib import Path as _Path
    path = _Path(path)
    if not ids or not path.is_file():
        return []
    texts: list[tuple[str, str]] = []
    if path.suffix.casefold() == ".docx":
        with _zip.ZipFile(path) as zf:
            for name in zf.namelist():
                if not name.endswith(".xml"):
                    continue
                blob = zf.read(name).decode("utf-8", errors="replace")
                if name.startswith("word/"):
                    blob = "".join(_re.findall(r"<w:t(?:\s[^>]*)?>([^<]*)</w:t>", blob))
                elif name.startswith("docProps/"):
                    blob = _re.sub(r"<[^>]+>", " ", blob)
                else:
                    continue
                texts.append((name, blob))
    elif path.suffix.casefold() == ".pdf":
        texts.append(("pdf", path.read_bytes().decode("latin-1", errors="replace")))
    problems = []
    for where, text in texts:
        folded = text.casefold()
        hits = [s for s in ids if s.casefold() in folded]
        if hits:
            part = "metadata" if where.startswith("docProps/") or where == "pdf" else "text"
            problems.append(f"{path.name}: author identity in {part} ({where}): "
                            + ", ".join(sorted(set(hits))[:3]))
    return problems
