"""1.8.1 regression tests: Word three-line tables with per-table orientation, and the
subagent review rounds that replace the third-party review package.

Called from tools/selftest.py.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))


def _narrow_sheet(ws) -> None:
    from tables import threeline
    threeline._write_sheet(ws, {
        "sheet": "Table 1", "title": "Table 1. Baseline characteristics",
        "header": ["Characteristic", "Group A (n = 640)", "Group B (n = 644)"],
        "rows": [["Age, years", "62.1 (8.4)", "61.7 (8.9)"], ["Women, n (%)", "301 (47.0)", "312 (48.4)"],
                 ["BMI, kg/m2", "27.4 (4.1)", "27.9 (4.3)"]],
        "footnotes": ["Data are mean (SD) or n (%).", "Abbreviations: BMI, body mass index."]})


def _wide_sheet(ws) -> None:
    """Nine columns and a two-row header with merged group cells (A1:A2 vertical, B1:E1 ...)."""
    from openpyxl.styles import Border, Side
    rule = Side(style="thin", color="FF000000")
    ws.cell(row=1, column=1, value="Table 2. Adjusted hazard ratios by subgroup")
    ws.merge_cells("A1:I1")
    ws.cell(row=2, column=1, value="Subgroup")
    ws.merge_cells("A2:A3")
    ws.cell(row=2, column=2, value="Model 1")
    ws.merge_cells("B2:E2")
    ws.cell(row=2, column=6, value="Model 2")
    ws.merge_cells("F2:I2")
    for c, v in enumerate(["Events", "HR", "95% CI", "P value"] * 2, 2):
        ws.cell(row=3, column=c, value=v)
    data = [["Overall", "412", "1.21", "1.05 to 1.39", "0.008", "398", "1.18", "1.02 to 1.37", "0.03"],
            ["Women", "190", "1.30", "1.06 to 1.60", "0.01", "184", "1.27", "1.03 to 1.57", "0.03"],
            ["Men", "222", "1.14", "0.94 to 1.38", "0.19", "214", "1.11", "0.91 to 1.35", "0.30"]]
    for r, row in enumerate(data, 4):
        for c, v in enumerate(row, 1):
            ws.cell(row=r, column=c, value=v)
    for c in range(1, 10):
        ws.cell(row=2, column=c).border = Border(top=rule)
        ws.cell(row=3, column=c).border = Border(bottom=rule)
        ws.cell(row=6, column=c).border = Border(bottom=rule)
    ws.cell(row=7, column=1, value="Abbreviations: CI, confidence interval; HR, hazard ratio.")
    ws.merge_cells("A7:I7")


def tables_paper(base: Path) -> tuple[Path, dict, Path]:
    """A fixture paper with one narrow and one wide main table, built with word_tables on."""
    import selftest_v180 as v180
    from openpyxl import Workbook
    target = {"journal": "Fixture Journal", "embed_figures": False, "word_tables": True}
    p, env = v180._paper(base, target)
    plan = json.loads((p / "01_protocol/artifact_plan.json").read_text(encoding="utf-8"))
    plan["main_tables"] = [{"id": "Table 1", "file": "04_tables/main/Table1.xlsx"},
                           {"id": "Table 2", "file": "04_tables/main/Table2.xlsx"}]
    (p / "01_protocol/artifact_plan.json").write_text(json.dumps(plan), encoding="utf-8")
    for name, fill in (("Table1.xlsx", _narrow_sheet), ("Table2.xlsx", _wide_sheet)):
        wb = Workbook()
        fill(wb.active)
        wb.save(p / "04_tables/main" / name)
    (p / "04_tables/table_captions.md").write_text(
        "# Table captions\n\n## Table 1.\nBaseline characteristics of the cohort.\n\n"
        "## Table 2.\nAdjusted hazard ratios by subgroup.\n", encoding="utf-8")
    src = p / "08_submission/full_manuscript.md"
    decl = "## Funding\nNone.\n\n## Competing interests\nNone.\n\n## Ethics approval\nApproved."
    src.write_text(v180._manuscript(decl), encoding="utf-8")
    proc = v180._build(p, env, "manuscript", src, "manuscript.docx", "--bibliography",
                       p / "06_refs/refs.bib", "--csl", p / "06_refs/numeric.csl")
    if proc.returncode:
        raise RuntimeError((proc.stdout + proc.stderr).strip()[-600:])
    return p, env, p / "08_submission/bundle/manuscript.docx"


def run_tables(tmp: Path, record, section) -> None:
    import selftest_v180 as v180
    from xml.etree import ElementTree as ET
    from wfcore import docxaudit as da
    section("1.8.1 Word tables: three-line borders, new page per table, orientation per table")
    try:
        p, env, out = tables_paper(tmp / "tables")
    except Exception as exc:  # noqa: BLE001
        record("manuscript with a narrow and a wide Word table builds and passes its audit", False, str(exc))
        return
    record("manuscript with a narrow and a wide Word table builds and passes its audit", True)
    root = ET.fromstring(v180._xml(out).encode("utf-8"))
    body = root.find("w:body", da.NS)
    kids = [k for k in body if k.tag in (f"{{{da.W}}}p", f"{{{da.W}}}tbl")]
    tbls = [i for i, k in enumerate(kids) if k.tag == f"{{{da.W}}}tbl"]
    W = f"{{{da.W}}}"

    def closing(i):
        return next(k.find("w:pPr/w:sectPr", da.NS) for k in kids[i + 1:]
                    if k.find("w:pPr/w:sectPr", da.NS) is not None)
    orient = [da._sect_orientation(closing(i)) for i in tbls]
    record("narrow table -> portrait section, wide (9 columns) table -> landscape section",
           orient == ["portrait", "landscape"], str(orient))
    land = closing(tbls[1]).find("w:pgSz", da.NS)
    record("landscape section swaps the page size and keeps the margins",
           int(land.get(W + "w")) > int(land.get(W + "h"))
           and closing(tbls[1]).find("w:pgMar", da.NS).get(W + "left") == "1440")
    record("the main text after the tables returns to portrait",
           da._sect_orientation(body.find("w:sectPr", da.NS)) == "portrait")
    record("both tables start on a new page and pass the layout audit",
           len(tbls) == 2 and not da.table_layout_problems(root, {}),
           str(da.table_layout_problems(root, {})))
    t2 = kids[tbls[1]]
    rows = t2.findall("w:tr", da.NS)
    heads = [r for r in rows if r.find("w:trPr/w:tblHeader", da.NS) is not None]
    rule_under_last = all(da._ruled(da._side(tc, "bottom")[0]) for tc in heads[-1].findall("w:tc", da.NS))
    first_clean = not any(da._ruled(da._side(tc, "bottom")[0]) for tc in heads[0].findall("w:tc", da.NS))
    record("two-row merged header: rule under the last header row only, merges kept",
           len(heads) == 2 and rule_under_last and first_clean
           and t2.find(".//w:gridSpan", da.NS) is not None and t2.find(".//w:vMerge", da.NS) is not None,
           f"heads={len(heads)} under_last={rule_under_last} first_clean={first_clean}")
    t1 = kids[tbls[0]]
    t1_text = "".join(t.text or "" for t in t1.iter(W + "t"))
    after = [da._ptext(k) for k in kids[tbls[0] + 1:tbls[0] + 3]]
    record("workbook title and footnote rows stay outside the table borders",
           "Table 1." not in t1_text and "Abbreviations" not in t1_text
           and any(x.startswith("Abbreviations") for x in after), str(after))
    record("table-level borders are none; every rule is an explicit cell border",
           all(n.get(W + "val") == "nil" for n in t1.find("w:tblPr/w:tblBorders", da.NS))
           and t1.find("w:tblPr/w:tblStyle", da.NS) is None)
    with __import__("zipfile").ZipFile(out) as zf:
        xmls = {n: zf.read(n) for n in zf.namelist() if n.startswith("word/")}
    nsect = len(root.findall(".//w:sectPr", da.NS))
    record("page numbers continue in every section (one shared footer, no restart)",
           nsect >= 4 and not da.footer_page_problems(xmls), f"{nsect} sections; "
           + str(da.footer_page_problems(xmls)))
    # Audit negatives: a pandoc-style table (header-bottom rule only, no break) fails.
    bad = ET.fromstring(
        f'<w:document xmlns:w="{da.W}"><w:body><w:p><w:r><w:t>Table 1. X</w:t></w:r></w:p><w:tbl>'
        '<w:tblPr><w:tblBorders><w:top w:val="single"/></w:tblBorders></w:tblPr>'
        '<w:tblGrid><w:gridCol/><w:gridCol/></w:tblGrid>'
        '<w:tr><w:tc><w:tcPr><w:tcBorders><w:bottom w:val="single" w:sz="6"/></w:tcBorders></w:tcPr>'
        '<w:p/></w:tc><w:tc><w:tcPr><w:tcBorders><w:left w:val="single"/></w:tcBorders></w:tcPr><w:p/></w:tc></w:tr>'
        '<w:tr><w:tc><w:p/></w:tc><w:tc><w:p/></w:tc></w:tr></w:tbl><w:sectPr/></w:body></w:document>')
    issues = " | ".join(da.table_layout_problems(bad, {}))
    record("audit rejects missing top/bottom rules, vertical borders, table borders and no page break",
           all(k in issues for k in ("top rule missing", "bottom rule missing", "vertical",
                                     "table-level borders", "new page")), issues)
    record("orientation rule: >7 columns or estimated width over the text width -> landscape; "
           "override wins",
           da.table_orientation([10] * 8, 12, 9026) == "landscape"
           and da.table_orientation([20, 10, 10], 12, 9026) == "portrait"
           and da.table_orientation([40, 40], 12, 9026) == "landscape"
           and da.table_orientation([10] * 9, 12, 9026, "portrait") == "portrait")
    target = json.loads((p / "08_submission/target_journal.json").read_text(encoding="utf-8"))
    target["tables"] = {"Table 1": {"orientation": "landscape"}}
    (p / "08_submission/target_journal.json").write_text(json.dumps(target), encoding="utf-8")
    record("target_journal.json tables.<id>.orientation feeds the build and the audit",
           da.table_overrides(p).get("table 1") == "landscape"
           and any("expected landscape" in x for x in da.table_layout_problems(
               root, da.table_overrides(p))))


def run(tmp: Path, record, section) -> None:
    tmp.mkdir(parents=True, exist_ok=True)
    run_tables(tmp, record, section)
