#!/usr/bin/env python3
"""Build and audit journal-ready DOCX files with deterministic medical-manuscript styling."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

try:
    from docx import Document
    from docx.enum.section import WD_ORIENT
    from docx.enum.style import WD_STYLE_TYPE
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.opc.constants import RELATIONSHIP_TYPE
    from docx.shared import Inches, Pt, RGBColor
except ImportError as exc:  # pragma: no cover - clear deployment failure
    raise SystemExit("python-docx is required; run bootstrap.py to install pinned dependencies") from exc


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from wfcore import docxaudit, journalspec, paths as wfpaths, scifreeze  # noqa: E402
from wfcore.packagecontent import build_receipt_path  # noqa: E402

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"w": W, "r": R, "rel": PKG_REL}
TEXT_ROLES = {"manuscript", "title_page", "cover_letter", "supplementary",
              "statements", "figure_legends"}
FORBIDDEN_PARAGRAPH_CONTROLS = (
    "outlineLvl", "keepNext", "keepLines", "pageBreakBefore",
)
THEMATIC_BREAK_RE = re.compile(
    r"(?m)^\s{0,3}(?:(?:\*\s*){3,}|(?:-\s*){3,}|(?:_\s*){3,})\s*$"
)
PIPE_TABLE_DIVIDER_RE = re.compile(
    r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$"
)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _receipt_file_record(path: Path, project: Path) -> dict:
    resolved = path.resolve()
    try:
        shown = resolved.relative_to(project.resolve()).as_posix()
    except ValueError:
        shown = str(resolved)
    return {"path": shown, "sha256": _file_sha256(resolved),
            "bytes": resolved.stat().st_size}


def _write_build_receipt(args, project: Path) -> Path:
    output = args.output.resolve()
    receipt = build_receipt_path(project, output)
    sources = [_receipt_file_record(path, project) for path in args.input]
    auxiliaries = []
    for path in (getattr(args, "bibliography", None), getattr(args, "csl", None),
                 getattr(args, "style_config", None)):
        if path is not None and path.is_file():
            auxiliaries.append(_receipt_file_record(path, project))
    # Presentation inputs the builder reads besides --input (journal rules, supplementary legends).
    extra = [journalspec.TARGET]
    if args.kind == "supplementary":
        extra.append("05_figures/legends.md")
    for rel in extra:
        if (project / rel).is_file():
            auxiliaries.append(_receipt_file_record(project / rel, project))
    pdf = output.with_suffix(".pdf")
    payload_pdf = ({"pdf_output": pdf.relative_to(project.resolve()).as_posix(),
                    "pdf_sha256": _file_sha256(pdf)}
                   if getattr(args, "pdf", False) and pdf.is_file() else {})
    payload = {
        **payload_pdf,
        "schema_version": 1,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "kind": args.kind,
        "output": output.relative_to(project.resolve()).as_posix(),
        "output_sha256": _file_sha256(output),
        "sources": sources,
        "auxiliaries": auxiliaries,
        "scientific_freeze_sha256": (
            _file_sha256(scifreeze.freeze_path(project))
            if scifreeze.is_frozen(project) else ""),
    }
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8")
    return receipt


def project_root() -> Path:
    return wfpaths.project_dir()


def planned_figure_ids(project: Path | None = None) -> list[str] | None:
    """Return every planned main/supplementary figure id, or None if the plan is unusable."""
    path = (project or project_root()) / "01_protocol/artifact_plan.json"
    if not path.is_file():
        return None
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    # Main-text Figure legends carry main figures only (1.8.0); supplementary legends travel
    # with the supplementary file.
    return [str(item.get("id", "")).strip()
            for item in plan.get("main_figures", []) if str(item.get("id", "")).strip()]


def figure_legend_cap() -> int:
    try:
        data = tomllib.loads((ROOT / "pipeline/pipeline.toml").read_text(encoding="utf-8"))
        return int(data.get("targets", {}).get("figure_legend_words_max", 180))
    except (OSError, ValueError, tomllib.TOMLDecodeError):
        return 180


def load_style(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    defaults = {
        "font_family": "Times New Roman", "body_font_pt": 12,
        "title_font_pt": 14, "section_heading_font_pt": 12,
        "subsection_heading_font_pt": 12, "line_spacing": 2.0,
        "paragraph_spacing_after_pt": 0, "margins_in": 1.0,
        "paper_size": "A4", "all_text_black": True,
        "external_hyperlinks": False,
        "code_font_family": "Courier New", "code_font_pt": 8,
    }
    defaults.update(data)
    return defaults


def _ensure_style(doc, name: str, base: str, font: str, size: float,
                  bold: bool = False, italic: bool = False):
    try:
        style = doc.styles[name]
    except KeyError:
        style = doc.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
    style.base_style = doc.styles[base]
    style.font.name = font
    style.font.size = Pt(size)
    style.font.bold = bold
    style.font.italic = italic
    style.font.color.rgb = RGBColor(0, 0, 0)
    rpr = style.element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.insert(0, rfonts)
    for attr in ("ascii", "hAnsi", "eastAsia", "cs"):
        rfonts.set(qn(f"w:{attr}"), font)
    for attr in ("asciiTheme", "hAnsiTheme", "eastAsiaTheme", "cstheme"):
        rfonts.attrib.pop(qn(f"w:{attr}"), None)
    ppr = style.element.get_or_add_pPr()
    for tag in (*[f"w:{name}" for name in FORBIDDEN_PARAGRAPH_CONTROLS], "w:numPr"):
        node = ppr.find(qn(tag))
        if node is not None:
            ppr.remove(node)
    return style


def _iter_table_paragraphs(table):
    for row in table.rows:
        for cell in row.cells:
            yield from cell.paragraphs
            for nested in cell.tables:
                yield from _iter_table_paragraphs(nested)


def iter_paragraphs(doc):
    yield from doc.paragraphs
    for table in doc.tables:
        yield from _iter_table_paragraphs(table)
    for section in doc.sections:
        yield from section.header.paragraphs
        yield from section.footer.paragraphs


def _flatten_hyperlinks(doc) -> None:
    for hyperlink in list(doc.element.xpath(".//w:hyperlink")):
        parent = hyperlink.getparent()
        idx = parent.index(hyperlink)
        for child in list(hyperlink):
            hyperlink.remove(child)
            parent.insert(idx, child)
            idx += 1
        parent.remove(hyperlink)
    for part in doc.part.package.parts:
        for rel_id, rel in list(part.rels.items()):
            if rel.reltype == RELATIONSHIP_TYPE.HYPERLINK:
                part.drop_rel(rel_id)


def _replace_manual_line_breaks(doc) -> None:
    """Convert manual line breaks to real paragraphs without merging address/list lines."""
    for part in doc.part.package.parts:
        root = getattr(part, "element", None)
        if root is None:
            continue
        for element in list(root.iter(qn("w:br"))) + list(root.iter(qn("w:cr"))):
            if element.tag == qn("w:br") and element.get(qn("w:type")) not in (None, "textWrapping"):
                continue
            paragraph = next((node for node in element.iterancestors() if node.tag == qn("w:p")), None)
            if paragraph is None:
                raise ValueError("manual line break outside a paragraph cannot be converted safely")
            current, tail = element, None
            while current is not paragraph:
                parent = current.getparent()
                following = list(parent)[parent.index(current) + 1:]
                clone = deepcopy(parent)
                for child in list(clone):
                    if child.tag not in {qn("w:pPr"), qn("w:rPr")}:
                        clone.remove(child)
                if tail is not None:
                    clone.append(tail)
                for child in following:
                    clone.append(child)
                current, tail = parent, clone
            paragraph.addnext(tail)
            # A section break belongs to the final resulting paragraph only.
            ppr = paragraph.find(qn("w:pPr"))
            sect = None if ppr is None else ppr.find(qn("w:sectPr"))
            if sect is not None:
                ppr.remove(sect)
            element.getparent().remove(element)


def _remove_heading_metadata(paragraph, *, strip_numbering: bool = True) -> None:
    ppr = paragraph._p.get_or_add_pPr()
    tags = [f"w:{name}" for name in FORBIDDEN_PARAGRAPH_CONTROLS]
    if strip_numbering:
        tags.append("w:numPr")
    for tag in tags:
        node = ppr.find(qn(tag))
        if node is not None:
            ppr.remove(node)


def _source_problems(kind: str, inputs: list[Path]) -> list[str]:
    text = "\n\n".join(path.read_text(encoding="utf-8", errors="replace") for path in inputs)
    problems: list[str] = []
    if kind in {"manuscript", "figure_legends"}:
        count = len(re.findall(r"(?mi)^#\s+Figure legends\s*$", text))
        if count != 1:
            problems.append(f"source must contain exactly one '# Figure legends' heading, found {count}")
    if kind == "supplementary":
        lines = text.splitlines()
        if (any(PIPE_TABLE_DIVIDER_RE.match(line) for line in lines) or
                re.search(r"<table\b", text, re.I | re.S) or
                re.search(r"^\s*\+[=-]{3,}(?:\+[=-]{3,})+\+\s*$", text, re.M)):
            problems.append(
                "supplementary Methods contains a table; move it to the planned supplementary "
                "tables workbook and build it with tools/tables/threeline.py"
            )
        if THEMATIC_BREAK_RE.search(text):
            problems.append("supplementary Methods contains a Markdown thematic break/horizontal rule")
    return problems


def _set_run(run, font: str, size: float) -> None:
    run.font.name = font
    run.font.size = Pt(size)
    run.font.color.rgb = RGBColor(0, 0, 0)
    rpr = run._r.get_or_add_rPr()
    rstyle = rpr.find(qn("w:rStyle"))
    if rstyle is not None and rstyle.get(qn("w:val"), "").casefold() == "hyperlink":
        rpr.remove(rstyle)
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.insert(0, rfonts)
    for attr in ("ascii", "hAnsi", "eastAsia", "cs"):
        rfonts.set(qn(f"w:{attr}"), font)
    for attr in ("asciiTheme", "hAnsiTheme", "eastAsiaTheme", "cstheme"):
        rfonts.attrib.pop(qn(f"w:{attr}"), None)
    color = rpr.find(qn("w:color"))
    if color is not None:
        color.set(qn("w:val"), "000000")
        for attr in ("themeColor", "themeTint", "themeShade"):
            color.attrib.pop(qn(f"w:{attr}"), None)


def _format_references(doc, font: str, size: float) -> None:
    """Number + TAB + hanging indent for every bibliography entry (EndNote/Zotero layout)."""
    entries = [p for p in doc.paragraphs if p.style is not None and p.style.name == "Bibliography"]
    for p in entries:
        pf = p.paragraph_format
        pf.left_indent = Inches(0.5)
        pf.first_line_indent = Inches(-0.5)
        pf.tab_stops.add_tab_stop(Inches(0.5))
        # Pandoc writes the citation number and the entry as adjacent runs, with or without a
        # space between them. Rebuild the lead as "N." + TAB.
        runs = list(p.runs)
        text = "".join(r.text for r in runs)
        m = re.match(r"^\s*(\[\d+\]|\d+\.?)[ \t\u00a0]*", text)
        if not m or not runs:
            continue
        label, cut = m.group(1), m.end()
        for r in runs:
            if cut <= 0:
                break
            n = len(r.text)
            r.text = r.text[cut:] if n > cut else ""
            cut -= n
        # Dangling separators when a record has a volume but no pages/article number.
        last = [r for r in p.runs if r.text]
        if last:
            last[-1].text = re.sub(r"(?<=[\d)])\s*[:;]\s*\.?\s*$", ".", last[-1].text)
        for r in p.runs:
            r.text = re.sub(r"(?<=[\d)])\s*[:;]\s*\.?\s+(?=doi\b)", ". ", r.text, flags=re.I)
        lead = p.runs[0]._r
        new = deepcopy(lead)
        for child in list(new):
            if child.tag != qn("w:rPr"):
                new.remove(child)
        t = OxmlElement("w:t")
        t.text = label
        new.append(t)
        new.append(OxmlElement("w:tab"))
        lead.addprevious(new)


def _add_page_numbers(doc, font: str, size: float) -> None:
    """Automatic PAGE field in every section footer (page numbers are not 'field functions')."""
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    for section in doc.sections:
        footer = section.footer
        footer.is_linked_to_previous = False
        p = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
        if "PAGE" in "".join(n.text or "" for n in p._p.iter(qn("w:instrText"))):
            continue
        for r in list(p.runs):
            r._r.getparent().remove(r._r)
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        for kind, value in (("begin", None), (None, " PAGE "), ("separate", None),
                            ("text", "1"), ("end", None)):
            run = p.add_run("1" if kind == "text" else "")
            if kind in ("begin", "separate", "end"):
                fc = OxmlElement("w:fldChar")
                fc.set(qn("w:fldCharType"), kind)
                run._r.append(fc)
            elif kind is None:
                it = OxmlElement("w:instrText")
                it.set(qn("xml:space"), "preserve")
                it.text = value
                run._r.append(it)
            _set_run(run, font, size)


def normalize_docx(path: Path, style: dict, kind: str, *, legend_bold: bool = True) -> None:
    doc = Document(path)
    font = str(style["font_family"])
    body_pt = float(style["body_font_pt"])
    title_pt = float(style["title_font_pt"])
    h1_pt = float(style["section_heading_font_pt"])
    h2_pt = float(style["subsection_heading_font_pt"])
    spacing = float(style["line_spacing"])
    after = float(style["paragraph_spacing_after_pt"])
    code_font = str(style.get("code_font_family", "Courier New"))
    code_pt = float(style.get("code_font_pt", 8))

    body_style = _ensure_style(doc, "Manuscript Body", "Normal", font, body_pt)
    title_style = _ensure_style(doc, "Manuscript Title", "Normal", font, title_pt, bold=True)
    # Both Markdown section levels are flattened onto one Normal-based paragraph
    # style.  Typography may still reflect the journal's H1/H2 sizes, but Word has
    # no outline hierarchy to display or collapse.
    section_style = _ensure_style(doc, "SectionHeading", "Normal", font, h1_pt, bold=True)
    for builtin in ("Normal", "Body Text", "Title", "Subtitle", "Heading 1", "Heading 2",
                    "Heading 3", "Bibliography", "Hyperlink"):
        try:
            s = doc.styles[builtin]
        except KeyError:
            continue
        s.font.name = font
        s.font.color.rgb = RGBColor(0, 0, 0)
        if builtin == "Hyperlink":
            s.font.underline = False
        ppr = s.element.get_or_add_pPr()
        for tag in ("w:outlineLvl", "w:keepNext", "w:keepLines", "w:pageBreakBefore"):
            node = ppr.find(qn(tag))
            if node is not None:
                ppr.remove(node)

    _flatten_hyperlinks(doc)
    _replace_manual_line_breaks(doc)
    paras = list(iter_paragraphs(doc))
    nonempty_seen = 0
    for p in paras:
        original = p.style.name if p.style is not None else ""
        text = p.text.strip()
        if text:
            nonempty_seen += 1
        _remove_heading_metadata(p, strip_numbering=False)
        if original == "Title" or (kind == "manuscript" and nonempty_seen == 1):
            p.style = title_style
            size = title_pt
            _remove_heading_metadata(p)
        elif re.match(r"^Heading 1$", original, re.I):
            p.style = section_style
            size = h1_pt
            _remove_heading_metadata(p)
        elif re.match(r"^Heading [2-9]$", original, re.I):
            p.style = section_style
            size = h2_pt
            _remove_heading_metadata(p)
            if not legend_bold and re.match(r"^(?:Figure|Fig\.?)\s+S?\d+", text):
                for run in p.runs:
                    run.font.bold = False
        elif original == "Source Code":
            # Exported code: small monospace, single spaced, so long rules stay on one line.
            p.paragraph_format.line_spacing = 1.0
            p.paragraph_format.space_after = Pt(after)
            for run in p.runs:
                _set_run(run, code_font, code_pt)
            continue
        else:
            if original in {"Normal", "Body Text", "First Paragraph", "Compact"}:
                p.style = body_style
            size = body_pt
        p.paragraph_format.line_spacing = spacing
        p.paragraph_format.space_after = Pt(after)
        for run in p.runs:
            _set_run(run, font, size)
    _format_references(doc, font, body_pt)
    _add_page_numbers(doc, font, body_pt)

    margin = Inches(float(style["margins_in"]))
    for section in doc.sections:
        section.top_margin = section.bottom_margin = margin
        section.left_margin = section.right_margin = margin
        if str(style["paper_size"]).upper() == "LETTER":
            section.page_width, section.page_height = Inches(8.5), Inches(11)
        else:
            section.page_width, section.page_height = Inches(8.2677), Inches(11.6929)
        section.orientation = WD_ORIENT.PORTRAIT

    doc.save(path)
    _sanitize_package_xml(path, font)


def _sanitize_package_xml(path: Path, font: str) -> None:
    """Remove theme residue and every Word paragraph control the user prohibited."""
    with zipfile.ZipFile(path, "r") as src:
        entries = [(item, src.read(item.filename)) for item in src.infolist()]
    tmp = path.with_suffix(path.suffix + ".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as out:
        for item, blob in entries:
            if item.filename.startswith("word/") and item.filename.endswith(".xml"):
                # Word's mc:Ignorable attributes contain namespace-prefix strings; parsing
                # and reserializing them with ElementTree can rename prefixes and make Word
                # report a corrupt file. Byte replacement preserves the package exactly.
                blob = re.sub(br"Aptos(?: Display)?", font.encode("utf-8"), blob,
                              flags=re.I)
                for tag in (*FORBIDDEN_PARAGRAPH_CONTROLS, "pBdr"):
                    name = tag.encode("ascii")
                    blob = re.sub(rb"<w:" + name + rb"\b[^>]*/>", b"", blob)
                    blob = re.sub(rb"<w:" + name + rb"\b[^>]*>.*?</w:" + name + rb">",
                                  b"", blob, flags=re.S)
            out.writestr(item, blob)
    tmp.replace(path)


def docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as zf:
        root = ET.fromstring(zf.read("word/document.xml"))
    return "\n".join("".join(t.text or "" for t in p.findall(".//w:t", NS))
                       for p in root.findall(".//w:p", NS))


def _canon_figure_id(value: str) -> str:
    return docxaudit.canon_figure_id(value)


def _legend_problems(root, expected: list[str], cap: int,
                     supplementary: list[str] | None = None) -> list[str]:
    return docxaudit.legend_problems(root, expected, cap, supplementary=supplementary)


def audit_docx(path: Path, style: dict, kind: str = "",
               planned_figures: list[str] | None = None,
               legend_cap: int = 180, spec: dict | None = None) -> list[str]:
    problems: list[str] = []
    if not path.is_file():
        return [f"missing DOCX: {path}"]
    try:
        with zipfile.ZipFile(path) as zf:
            bad = zf.testzip()
            if bad:
                return [f"{path.name}: corrupt at {bad}"]
            xmls = {n: zf.read(n) for n in zf.namelist()
                    if n.startswith("word/") and n.endswith((".xml", ".rels"))}
    except zipfile.BadZipFile:
        return [f"{path.name}: invalid ZIP/DOCX"]

    document = xmls.get("word/document.xml", b"")
    try:
        root = ET.fromstring(document)
    except ET.ParseError as exc:
        return [f"{path.name}: invalid document.xml ({exc})"]
    if root.findall(".//w:hyperlink", NS):
        problems.append(f"{path.name}: hyperlink elements remain")
    if any("HYPERLINK" in (node.text or "").upper()
           for node in root.findall(".//w:instrText", NS)):
        problems.append(f"{path.name}: hyperlink field code remains")
    for name, blob in xmls.items():
        if name.endswith(".rels"):
            try:
                relroot = ET.fromstring(blob)
            except ET.ParseError:
                continue
            for rel in relroot.findall("rel:Relationship", NS):
                if rel.get("TargetMode") == "External" and "hyperlink" in rel.get("Type", "").lower():
                    problems.append(f"{path.name}: external hyperlink relationship remains")
    for name, blob in xmls.items():
        if not name.endswith(".xml"):
            continue
        part = ET.fromstring(blob)
        if any(node.get(f"{{{W}}}type") in (None, "textWrapping")
               for node in part.findall(".//w:br", NS)) or part.findall(".//w:cr", NS):
            problems.append(f"{path.name}: manual line-break control remains in {name}")
        if any("\u2193" in (node.text or "") for node in part.findall(".//w:t", NS)):
            problems.append(f"{path.name}: forbidden down-arrow character remains in {name}")
        for tag in FORBIDDEN_PARAGRAPH_CONTROLS:
            if part.findall(f".//w:{tag}", NS):
                problems.append(f"{path.name}: forbidden {tag} paragraph control remains in {name}")
        if part.findall(".//w:pBdr", NS):
            problems.append(f"{path.name}: paragraph border/horizontal-rule residue remains in {name}")
    expected_font = str(style["font_family"])
    if expected_font.casefold() == "times new roman" and any(b"Aptos" in b for b in xmls.values()):
        problems.append(f"{path.name}: Aptos remains in Word XML")
    for p in root.findall(".//w:p", NS):
        ppr = p.find("w:pPr", NS)
        pstyle = None if ppr is None else ppr.find("w:pStyle", NS)
        style_id = "" if pstyle is None else pstyle.get(f"{{{W}}}val", "")
        is_code = style_id in docxaudit.CODE_STYLES
        allowed_pts = ({float(style["title_font_pt"])} if style_id == "ManuscriptTitle" else
                       {float(style["section_heading_font_pt"]),
                        float(style["subsection_heading_font_pt"])} if style_id == "SectionHeading" else
                       {float(style["code_font_pt"])} if is_code else
                       {float(style["body_font_pt"])})
        run_font = str(style["code_font_family"]) if is_code else expected_font
        paragraph_text = "".join(t.text or "" for t in p.findall(".//w:t", NS)).strip()
        spacing_node = None if ppr is None else ppr.find("w:spacing", NS)
        line = str(int(round((1.0 if is_code else float(style["line_spacing"])) * 240)))
        if paragraph_text and (spacing_node is None or
                spacing_node.get(f"{{{W}}}line") != line or
                spacing_node.get(f"{{{W}}}after", "0") !=
                str(int(round(float(style["paragraph_spacing_after_pt"]) * 20)))):
            problems.append(f"{path.name}: inconsistent line/paragraph spacing")
        for run in p.findall(".//w:r", NS):
            if not "".join(t.text or "" for t in run.findall(".//w:t", NS)).strip():
                continue
            rpr = run.find("w:rPr", NS)
            rf = None if rpr is None else rpr.find("w:rFonts", NS)
            color = None if rpr is None else rpr.find("w:color", NS)
            size = None if rpr is None else rpr.find("w:sz", NS)
            if rf is None or any(rf.get(f"{{{W}}}{a}") != run_font for a in ("ascii", "hAnsi")):
                problems.append(f"{path.name}: a text run does not explicitly use {run_font}")
                break
            if color is None or color.get(f"{{{W}}}val", "").upper() not in {"000000", "AUTO"}:
                problems.append(f"{path.name}: a text run is not explicitly black")
                break
            if size is None or size.get(f"{{{W}}}val", "") not in {
                    str(int(round(value * 2))) for value in allowed_pts}:
                problems.append(f"{path.name}: inconsistent size in {style_id or 'body'} paragraph")
                break
        if style_id.casefold().startswith("heading"):
            problems.append(f"{path.name}: built-in outline heading style remains on visible text")
            break
    text = docx_text(path)
    if "\u2193" in text:
        problems.append(f"{path.name}: forbidden down-arrow character remains")
    if kind == "manuscript":
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        exact = {name: [i for i, line in enumerate(lines) if line.casefold() == name]
                 for name in ("abstract", "references", "figure legends")}
        keywords = [i for i, line in enumerate(lines) if line.casefold().startswith("keywords:")]
        for name, indices in exact.items():
            if len(indices) != 1:
                problems.append(f"{path.name}: expected one {name.title()} heading, found {len(indices)}")
        if len(keywords) != 1:
            problems.append(f"{path.name}: expected one Keywords line, found {len(keywords)}")
        order = [exact[name][0] if len(exact[name]) == 1 else -1
                 for name in ("abstract",)] + [keywords[0] if len(keywords) == 1 else -1] + [
                 exact[name][0] if len(exact[name]) == 1 else -1
                 for name in ("references", "figure legends")]
        if all(x >= 0 for x in order) and order != sorted(order):
            problems.append(f"{path.name}: Abstract/Keywords/References/Figure legends order is wrong")
        if planned_figures is None:
            problems.append(f"{path.name}: artifact_plan.json is missing or invalid")
        else:
            problems.extend(f"{path.name}: {problem}" for problem in
                            _legend_problems(root, planned_figures, legend_cap,
                                             (spec or {}).get("supp_figures")))
    elif kind == "figure_legends":
        count = sum(1 for line in docx_text(path).splitlines()
                    if line.strip().casefold() == "figure legends")
        if count != 1:
            problems.append(f"{path.name}: expected one Figure legends heading, found {count}")
    if kind == "supplementary" and root.findall(".//w:tbl", NS):
        problems.append(
            f"{path.name}: supplementary Methods contains a table; package it as a separate "
            "three-line supplementary table"
        )
    if kind in TEXT_ROLES:
        problems.extend(docxaudit.extra_problems(path.name, xmls, root, kind, spec, legend_cap))
    return sorted(set(problems))


# ---------------------------------------------------------------------------
# 1.8.0 presentation layer: journal rules applied to a temporary render copy. The Markdown
# sources (frozen science or the journal variant) are never rewritten by the builder.
# ---------------------------------------------------------------------------
_LEGEND_H_RE = re.compile(r"(?mi)^(#{2,6})\s+(?:Figure|Fig\.?)\s+(S?\d+)\.?[ \t]*(.*)$")


def _legend_blocks(text: str) -> list[tuple[str, str]]:
    """[(figure number, block text incl. heading)] of a '# Figure legends' style document."""
    matches = list(_LEGEND_H_RE.finditer(text))
    out = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        nxt = re.search(r"(?m)^#\s", text[m.end():end])
        if nxt:
            end = m.end() + nxt.start()
        out.append((m.group(2).upper(), text[m.start():end].rstrip()))
    return out


def supplementary_legends(project: Path) -> str:
    path = project / "05_figures/legends.md"
    if not path.is_file():
        return ""
    blocks = [b for num, b in _legend_blocks(path.read_text(encoding="utf-8")) if num.startswith("S")]
    if not blocks:
        return ""
    return "# Supplementary figure legends\n\n" + "\n\n".join(blocks) + "\n"


def _style_legends(section: str, lstyle: dict) -> str:
    prefix = lstyle.get("prefix", "Figure")
    punct = lstyle.get("end_punctuation", "any")
    case = lstyle.get("panel_label_case", "any")

    def head(m):
        rest = m.group(3).strip()
        label = f"{prefix} {m.group(2)}"
        if rest:
            label = f"{label}. {rest}" if prefix == "Figure" else f"{label} {rest}"
        if punct == "." and not label.endswith("."):
            label += "."
        elif punct == "none":
            label = label.rstrip(".")
        return f"{m.group(1)} {label}"

    section = _LEGEND_H_RE.sub(head, section)
    if case in ("lower", "upper"):
        conv = str.lower if case == "lower" else str.upper
        section = re.sub(r"\(([A-Ha-h])\)", lambda m: f"({conv(m.group(1))})", section)
    return section


def _figure_image(project: Path, entry: dict) -> Path | None:
    raw = str(entry.get("file", "")).strip()
    if not raw:
        return None
    path = project / raw
    png = path.with_suffix(".png")
    return png if png.is_file() else (path if path.is_file() else None)


def _table_markdown(project: Path, entry: dict, caption: str) -> str:
    """A main table as a Pandoc pipe table (first row = header) for journals wanting Word tables."""
    from openpyxl import load_workbook
    raw = str(entry.get("file", "")).strip()
    path = project / raw
    if not raw or not path.is_file():
        raise ValueError(f"word_tables: {entry.get('id')} workbook missing ({raw})")
    ws = load_workbook(path, data_only=True).worksheets[0]
    rows = [["" if v is None else str(v).replace("|", "\\|").replace("\n", " ") for v in row]
            for row in ws.iter_rows(values_only=True)]
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        raise ValueError(f"word_tables: {entry.get('id')} workbook is empty")
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    lines = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * width]
    lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return f"## {entry.get('id')}. {caption}".rstrip() + "\n\n" + "\n".join(lines)


def _table_captions(project: Path) -> dict[str, str]:
    path = project / "04_tables/table_captions.md"
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8")
    out = {}
    for m in re.finditer(r"(?mi)^#{2,6}\s+(Table\s+S?\d+)\.?[ \t]*(.*)$\n?((?:(?!#).*\S.*\n?)*)", text):
        caption = m.group(2).strip() or " ".join(m.group(3).split())
        out[docxaudit.canon_figure_id(m.group(1))] = caption
    return out


def _clean_pipeline_code(text: str) -> str:
    """Drop engine plumbing from exported code and reduce local paths to file names."""
    def fence(m):
        kept = [ln for ln in m.group(2).splitlines()
                if not re.search(r"wfcore|MEDPAPER_|project_dir\s*\(|sys\.path\.(?:insert|append)|"
                                 r"medresults\.R|tools[/\\]", ln)]
        return m.group(1) + "\n".join(kept) + "\n" + m.group(3)
    text = re.sub(r"(?ms)^(```[^\n]*\n)(.*?)\n?(^```)", fence, text)
    return re.sub(r"(?:(?<![\w])[A-Za-z]:[\\/]|(?<![\w./])/(?:Users|home)/)"
                  r"(?:[^\s'\"`)]*[\\/])?([^\s'\"`)\\/]+)", r"\1", text)


def _info_page(project: Path) -> str:
    target = journalspec.load(project)
    title_path = project / "07_manuscript/title.md"
    title = re.sub(r"^#\s+", "", title_path.read_text(encoding="utf-8").strip()) \
        if title_path.is_file() else ""
    lines = ["# Supplementary information", ""]
    if title:
        lines += [f"Article title: {title}", ""]
    if target.get("journal"):
        lines += [f"Journal: {target['journal']}", ""]
    try:
        info = json.loads((project / "00_input/author_info.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        info = {}
    names = []
    for a in info.get("authors", []) if isinstance(info.get("authors"), list) else []:
        names.append(a.get("name", "") if isinstance(a, dict) else str(a))
    if any(names):
        lines += ["Authors: " + ", ".join(n for n in names if n), ""]
    corr = info.get("corresponding")
    if isinstance(corr, dict):
        corr = ", ".join(str(corr[k]) for k in ("name", "email", "affiliation") if corr.get(k))
    if corr:
        lines += [f"Corresponding author: {corr}", ""]
    return "\n".join(lines) + "\n"


def prepare_source(kind: str, inputs: list[Path], project: Path, workdir: Path) -> list[Path]:
    """Apply the journal's presentation rules to a temporary copy handed to Pandoc."""
    if kind not in ("manuscript", "supplementary"):
        return inputs
    text = "\n\n".join(p.read_text(encoding="utf-8", errors="replace") for p in inputs)
    target = journalspec.load(project)
    if kind == "manuscript":
        m = re.search(r"(?mi)^#\s+Figure legends\s*$", text)
        if m:
            head, legends = text[:m.start()], text[m.start():]
            legends = _style_legends(legends, journalspec.legend_style(target))
            counts = docxaudit.plan_counts(project)
            plan = counts["plan"]
            if target.get("embed_figures") is True:
                entries = {docxaudit.canon_figure_id(str(e.get("id", ""))): e
                           for e in plan.get("main_figures", [])}
                out, last = [], 0
                blocks = list(_LEGEND_H_RE.finditer(legends))
                for i, b in enumerate(blocks):
                    end = blocks[i + 1].start() if i + 1 < len(blocks) else len(legends)
                    out.append(legends[last:end].rstrip())
                    img = _figure_image(project, entries.get(f"figure {b.group(2).lower()}", {}))
                    if img is not None:
                        out.append(f"![]({img.as_posix()}){{width=6in}}")
                    last = end
                out.append(legends[last:].rstrip())
                legends = "\n\n".join(x for x in out if x) + "\n"
            if target.get("word_tables") is True and plan.get("main_tables"):
                caps = _table_captions(project)
                tables = [_table_markdown(project, e, caps.get(
                    docxaudit.canon_figure_id(str(e.get("id", ""))), ""))
                    for e in plan.get("main_tables", [])]
                head = head.rstrip() + "\n\n# Tables\n\n" + "\n\n".join(tables) + "\n\n"
            text = head + legends
    else:
        text = _clean_pipeline_code(text)
        if target:
            text = _info_page(project) + "\n" + text
        legends = supplementary_legends(project)
        if legends:
            text = text.rstrip() + "\n\n" + legends
    out = workdir / f"render_{kind}.md"
    out.write_text(text, encoding="utf-8")
    return [out]


def collapsing_csl(csl: Path | None, workdir: Path) -> Path | None:
    """Copy of the CSL whose numeric citations collapse to ranges ([1-3, 7])."""
    if csl is None or not csl.is_file():
        return csl
    xml = csl.read_text(encoding="utf-8")
    m = re.search(r"<citation\b[^>]*>", xml)
    if not m or "collapse=" in m.group(0) or 'citation-format="numeric"' not in xml:
        return csl
    patched = m.group(0)[:-1].rstrip("/") + ' collapse="citation-number">'
    out = workdir / csl.name
    out.write_text(xml[:m.start()] + patched + xml[m.end():], encoding="utf-8")
    return out


def _convert_pdf(docx_path: Path, pdf_path: Path) -> None:
    """DOCX -> PDF with Microsoft Word (Windows) or LibreOffice; fails loudly if neither exists."""
    pdf_path.unlink(missing_ok=True)
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if os.name == "nt" and not soffice:
        script = ("$w = New-Object -ComObject Word.Application; $w.Visible = $false; "
                  "try { $d = $w.Documents.Open($env:MP_DOCX, $false, $true); "
                  "$d.SaveAs([ref]$env:MP_PDF, [ref]17); $d.Close($false) } "
                  "finally { $w.Quit() }")
        env = {**os.environ, "MP_DOCX": str(docx_path.resolve()), "MP_PDF": str(pdf_path.resolve())}
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                       capture_output=True, text=True, env=env, timeout=300)
    elif soffice:
        subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir",
                        str(pdf_path.parent), str(docx_path)], capture_output=True, timeout=300)
        produced = pdf_path.parent / (docx_path.stem + ".pdf")
        if produced != pdf_path and produced.is_file():
            produced.replace(pdf_path)
    if not pdf_path.is_file() or pdf_path.stat().st_size < 200:
        raise RuntimeError("PDF conversion failed: install Microsoft Word or LibreOffice, or set "
                           "si_format to 'docx' in target_journal.json if the journal accepts Word")


def run_pandoc(inputs: list[Path], output: Path, bibliography: Path | None,
               csl: Path | None) -> None:
    pandoc = shutil.which("pandoc")
    if not pandoc:
        raise RuntimeError("pandoc is required to render Markdown and citations")
    cmd = [pandoc, *map(str, inputs)]
    if bibliography:
        cmd += ["--citeproc", f"--bibliography={bibliography}"]
    if csl:
        cmd += [f"--csl={csl}"]
    cmd += ["--metadata=link-citations:false", "-o", str(output)]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    combined = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode:
        raise RuntimeError(combined.strip() or f"pandoc exited {proc.returncode}")
    if re.search(r"could not find citation|unresolved", combined, re.I):
        raise RuntimeError("pandoc reported an unresolved citation: " + combined.strip())


def build(args) -> int:
    project = project_root()
    if scifreeze.is_frozen(project) and args.kind in {
            "manuscript", "title_page", "supplementary", "statements"}:
        frozen = []
        for source in args.input:
            try:
                rel = source.resolve().relative_to(project.resolve()).as_posix()
            except ValueError:
                continue
            if rel.startswith("07_manuscript/"):
                frozen.append(rel)
        if frozen:
            print(
                "DOCX build refused: the scientific source is frozen after S19. Build this "
                "journal upload from 08_submission/manuscript/ instead: " + ", ".join(frozen),
                file=sys.stderr)
            return 2

    from wfcore.dependencies import guard_build
    from wfcore.revision import guard_outputs
    try:
        guard_build(project)
        guard_outputs(project, [args.output, build_receipt_path(project, args.output)])
    except ValueError as exc:
        print(f"DOCX build refused: {exc}", file=sys.stderr)
        return 2

    style = load_style(args.style_config)
    if style.get("all_text_black") is not True or style.get("external_hyperlinks") is not False:
        print("style config must require black text and prohibit external hyperlinks", file=sys.stderr)
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    receipt_path = build_receipt_path(project, args.output)
    receipt_path.unlink(missing_ok=True)
    pdf_path = args.output.with_suffix(".pdf") if getattr(args, "pdf", False) else None
    spec = docxaudit.audit_spec(project)
    try:
        source_problems = _source_problems(args.kind, args.input)
        if source_problems:
            raise ValueError("; ".join(source_problems))
        with tempfile.TemporaryDirectory(prefix="medpaper_render_") as work:
            workdir = Path(work)
            rendered = prepare_source(args.kind, args.input, project, workdir)
            run_pandoc(rendered, args.output, args.bibliography,
                       collapsing_csl(args.csl, workdir))
        normalize_docx(args.output, style, args.kind,
                       legend_bold=bool(spec["legend_style"].get("bold", True)))
        problems = audit_docx(args.output, style, args.kind,
                              planned_figure_ids() if args.kind == "manuscript" else None,
                              figure_legend_cap(), spec)
        if not problems and pdf_path is not None:
            _convert_pdf(args.output, pdf_path)
    except Exception as exc:  # noqa: BLE001
        args.output.unlink(missing_ok=True)
        receipt_path.unlink(missing_ok=True)
        print(f"DOCX build failed: {exc}", file=sys.stderr)
        return 2
    if problems:
        args.output.unlink(missing_ok=True)
        receipt_path.unlink(missing_ok=True)
        print("DOCX audit failed:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 2
    try:
        receipt = _write_build_receipt(args, project)
    except Exception as exc:  # noqa: BLE001
        args.output.unlink(missing_ok=True)
        receipt_path.unlink(missing_ok=True)
        print(f"DOCX build receipt failed: {exc}", file=sys.stderr)
        return 2
    print(f"built and audited {args.kind} -> {args.output}")
    if pdf_path is not None:
        print(f"PDF export -> {pdf_path}")
    print(f"build receipt -> {receipt}")
    return 0


def _resolve_manifest_file(manifest: Path, raw: str) -> Path:
    p = Path(raw)
    if p.is_absolute():
        return p
    project = project_root()
    return project / p


def audit_manifest(args) -> int:
    style = load_style(args.style_config)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    problems: list[str] = []
    roles: dict[str, list[Path]] = {}
    planned = planned_figure_ids()
    legend_cap = figure_legend_cap()
    spec = docxaudit.audit_spec(project_root())
    for item in manifest.get("items", []):
        role = str(item.get("role", "")).strip()
        path = _resolve_manifest_file(args.manifest, str(item.get("file", "")))
        roles.setdefault(role, []).append(path)
        if role in TEXT_ROLES and path.suffix.lower() != ".docx":
            problems.append(f"{role}: narrative upload must be DOCX, got {path.name}")
        if path.suffix.lower() == ".docx":
            problems += audit_docx(path, style, role, planned, legend_cap, spec)
    for role in ("manuscript", "title_page", "cover_letter"):
        if not any(p.suffix.lower() == ".docx" for p in roles.get(role, [])):
            problems.append(f"manifest lacks a DOCX item for role '{role}'")
    if (project_root() / "07_manuscript/supplementary_methods.md").exists():
        if not any(p.suffix.lower() == ".docx" for p in roles.get("supplementary", [])):
            problems.append("supplementary_methods.md exists but no supplementary DOCX is listed")
    if problems:
        print("submission DOCX audit failed:\n  " + "\n  ".join(sorted(set(problems))))
        return 2
    print(f"submission DOCX audit passed: {sum(len(v) for v in roles.values())} manifest item(s)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="build or audit deterministic journal DOCX files")
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("build")
    p.add_argument("--kind", required=True,
                   choices=["manuscript", "title_page", "cover_letter", "supplementary",
                            "statements", "checklist_form", "coi_forms", "figure_legends"])
    p.add_argument("--input", type=Path, action="append", required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--style-config", type=Path, required=True)
    p.add_argument("--bibliography", type=Path)
    p.add_argument("--csl", type=Path)
    p.add_argument("--pdf", action="store_true",
                   help="also export the audited DOCX to PDF (use for supplementary files "
                        "unless target_journal.json sets si_format=docx)")
    p.set_defaults(fn=build)
    p = sub.add_parser("audit")
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--style-config", type=Path, required=True)
    p.set_defaults(fn=audit_manifest)
    args = ap.parse_args()
    # `project/...` in stage cards is a logical alias for the selected paper folder; the engine
    # never holds paper files. Map every CLI path before build/audit touches the filesystem.
    for attr in ("style_config", "bibliography", "csl", "manifest"):
        value = getattr(args, attr, None)
        if value is not None:
            setattr(args, attr, wfpaths.resolve_paper_path(value))
    if getattr(args, "output", None) is not None:
        args.output = wfpaths.paper_output_path(args.output)
    if getattr(args, "input", None):
        args.input = [wfpaths.resolve_paper_path(value) for value in args.input]
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())

