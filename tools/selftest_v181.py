"""1.8.1 regression tests: Word three-line tables with per-table orientation, and the
subagent review rounds that replace the third-party review package.

Called from tools/selftest.py.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def _card(name) -> str:
    """1.12.0 (D1): a stage card plus its reference/stage_details/ long form."""
    from wfcore.registry import card_full_text
    return card_full_text(name)

sys.path.insert(0, str(ROOT / "tools"))


def with_report(args: list[str], paper: Path) -> list[str]:
    """1.11.0 adapter: a round closes against the reviewer's saved report, and each kept
    finding carries its own --kept ID reason. Older tests pass their --finding rows; this writes
    the matching numbered report so their original assertions still apply."""
    if not args or args[0] != "close" or "--report" in args:
        return args
    rows = [args[i + 1:i + 5] for i, a in enumerate(args) if a == "--finding"]
    extra = []
    for fid, _cat, status, summary in rows:
        if status == "kept":
            extra += ["--kept", fid, f"kept: {summary} (reason recorded)"]
    report = paper.parent / f"{paper.name}_report_{len(list(paper.parent.glob('*_report_*.md')))}.md"
    report.write_text("# Review\n\n" + "".join(f"- {r[0]} {r[3]}\n" for r in rows), encoding="utf-8")
    return args + extra + ["--report", str(report)]


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


def _review_paper(base: Path) -> tuple[Path, dict]:
    import selftest_v180 as v180
    p, env = v180._paper(base, None)
    plan = {"main_figures": [{"id": "Figure 1", "file": "05_figures/out/Figure1.png"}],
            "supp_figures": [], "main_tables": [{"id": "Table 1", "file": "04_tables/main/Table1.xlsx"}],
            "supp_tables": []}
    (p / "01_protocol/artifact_plan.json").write_text(json.dumps(plan), encoding="utf-8")
    (p / "07_manuscript/full_manuscript.md").write_text(v180._manuscript("## Funding\nNone."),
                                                        encoding="utf-8")
    (p / "06_refs/library.json").write_text("{}", encoding="utf-8")
    (p / "03_analysis/results").mkdir(parents=True, exist_ok=True)
    (p / "03_analysis/results/primary.json").write_text('{"hr": 1.87}', encoding="utf-8")
    from wfcore.state import State
    st = State(p, ".wf").load()
    st.data["current"] = "S19_human_review"
    st.save()
    return p, env


def run_review(tmp: Path, record, section) -> None:
    import subprocess
    import tomllib
    from wfcore import registry, reviewrounds as rr, scifreeze
    from wfcore.checks import Ctx, get, load_all
    from wfcore.checks.frozen import _approval_binding_problems
    from wfcore.state import State
    section("1.8.1 review rounds: subagent review, autonomous fixes, one question per round")
    load_all()
    pipe = registry.load()
    raw = tomllib.loads((ROOT / "pipeline/pipeline.toml").read_text(encoding="utf-8"))
    stages = {s["id"]: s for s in raw["stage"]}
    gates = {sid: [g["check"] for g in stages[sid]["gate"]] for sid in stages}
    cards = "".join(_card(sid)
                    for sid in ("S18_independent_review", "S19_human_review",
                                "S24_package_human_review", "S25_submission_audit"))
    record("default flow builds no review package (gates, outputs and cards)",
           "manuscript_review_package_current" not in gates["S19_human_review"]
           and "s19_review_release_explicit" not in gates["S19_human_review"]
           and "review_round_approved" in gates["S19_human_review"]
           and "review_round_approved" in gates["S24_package_human_review"]
           and not any("review_packages" in o for o in stages["S19_human_review"]["outputs"])
           and not any(k in cards.casefold() for k in ("review_package", "review package",
                                                        "third-party", "zip")))
    record("cards do not ask permission per change", all(
        k not in cards for k in ("逐项", "是否修改", "permission for each")))
    p, env = _review_paper(tmp / "review")

    def cli(*args):
        args = with_report(list(args), p)
        return subprocess.run([sys.executable, str(ROOT / "tools/review_round.py"), *args,
                               "--project", str(p)], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", env=env)

    def gate(sid="S19_human_review", scope="manuscript"):
        return get("review_round_approved")(Ctx(
            pipeline=pipe, state=State(p, ".wf").load(), project=p, stage=pipe.stage(sid),
            spec={"check": "review_round_approved", "scope": scope}))
    r0 = gate()
    record("a review round record is required to advance", not r0.ok and "no review round" in r0.detail,
           r0.detail)
    s1 = cli("start")
    copies = list((p / ".wf/review_text").glob("*.txt"))
    record("start lists the current files and writes fresh hash-bound table text copies",
           s1.returncode == 0 and "medpaper-reviewer" in s1.stdout and "full_manuscript.md" in s1.stdout
           and copies and "sha256:" in copies[0].read_text(encoding="utf-8"), (s1.stdout + s1.stderr)[-300:])
    open_gate = gate()
    md = p / "07_manuscript/full_manuscript.md"
    md.write_text(md.read_text(encoding="utf-8").replace("was associated", "was clearly associated"),
                  encoding="utf-8")
    c1 = cli("close", "--findings", "critical=0,major=1,minor=2",
             "--finding", "F1", "conclusion_strength", "changed", "Claim too strong",
             "--finding", "F2", "other", "kept", "Second cohort",
             "--finding", "F3", "other", "changed", "Typo", "--change",
             "07_manuscript/full_manuscript.md", "Tightened the Discussion claim",
             "--kept", "Add a second cohort", "needs data the study does not have")
    waiting = gate()
    d1 = cli("decide", "another_round", "--words", "再审一轮")
    another = gate()
    record("an open round, an unanswered round and 'another round' all keep the stage open",
           not open_gate.ok and "open" in open_gate.detail and c1.returncode == 0
           and not waiting.ok and "waiting" in waiting.detail and d1.returncode == 0
           and not another.ok and "another review round" in another.detail,
           " | ".join([open_gate.detail, waiting.detail, another.detail, c1.stderr, d1.stderr]))
    hr = (p / "07_manuscript/human_review.md").read_text(encoding="utf-8")
    record("the round record writes human_review.md (findings, changes, kept items, answers)",
           all(h in hr for h in rr.SCOPES["manuscript"]["headings"]) and "Tightened" in hr
           and "needs data" in hr and "major 1" in hr)
    s2 = cli("start", "--delta")
    rnd2 = rr.latest(p, "manuscript")
    c2 = cli("close", "--findings", "minor=0")
    d2 = cli("decide", "no_further_review", "--words", "我确认这一版")
    ok_gate = gate()
    st = State(p, ".wf").load()
    dec = st.decision("manuscript_human_reviewed") or {}
    record("'no further review' records the approval bound to the round and lets the stage advance",
           s2.returncode == 0 and rnd2["mode"] == "delta" and c2.returncode == 0 and d2.returncode == 0
           and ok_gate.ok and dec.get("value") == "NO_FURTHER_REVIEW" and "M002" in dec.get("rationale", ""),
           ok_gate.detail + (s2.stderr + c2.stderr + d2.stderr))
    record("no review package was generated in the new flow",
           not (p / "07_manuscript/review_packages").exists())
    freeze = scifreeze.build_freeze(p)
    record("the scientific freeze binds to the latest approved round",
           freeze.get("review_round_id") == "M002" and "review_package_id" not in freeze, str(freeze)[:200])
    scifreeze.freeze_path(p).write_text(json.dumps(freeze), encoding="utf-8")
    ctx = Ctx(pipeline=pipe, state=State(p, ".wf").load(), project=p,
              stage=pipe.stage("S19_human_review"), spec={})
    bound_ok = _approval_binding_problems(ctx)
    scifreeze.freeze_path(p).write_text(json.dumps({**freeze, "review_round_id": "M001"}), encoding="utf-8")
    bound_bad = _approval_binding_problems(ctx)
    record("freeze binding passes for the approved round and fails for an older one",
           bound_ok == [] and any("M001" in x for x in bound_bad), str(bound_ok + bound_bad))
    # Legacy: a pre-1.8.1 freeze bound to a review-package id still validates.
    st = State(p, ".wf").load()
    st.record_decision("manuscript_human_reviewed", "NO_FURTHER_REVIEW",
                       "user approved ZIP v001 package abcdef123456 explicitly")
    legacy = {k: v for k, v in freeze.items() if k != "review_round_id"}
    legacy.update(review_package_id="abcdef1234567890", frozen_at="2999-01-01T00:00:00Z")
    scifreeze.freeze_path(p).write_text(json.dumps(legacy), encoding="utf-8")
    ctx = Ctx(pipeline=pipe, state=State(p, ".wf").load(), project=p,
              stage=pipe.stage("S19_human_review"), spec={})
    record("an old paper whose freeze carries a legacy review_package_id still passes",
           _approval_binding_problems(ctx) == [], str(_approval_binding_problems(ctx)))
    st.record_decision("manuscript_human_reviewed", "NO_FURTHER_REVIEW",
                       f"review round M002: user said no further review")
    # Coverage: an artifact changed after the last round fails until a new (delta) round.
    (p / "05_figures/legends.md").write_text(
        (p / "05_figures/legends.md").read_text(encoding="utf-8") + "\nEdited.\n", encoding="utf-8")
    stale = gate()
    early = cli("decide", "no_further_review", "--words", "我确认这一版")
    cli("start", "--delta")
    rnd3 = rr.latest(p, "manuscript")
    cli("close", "--findings", "minor=1", "--finding", "F1", "other", "changed", "Edited legend")
    cli("decide", "no_further_review", "--words", "我确认这一版")
    fresh = gate()
    record("coverage fails when a covered file changes after the last round; a delta round fixes it",
           not stale.ok and "changed after review round M002" in stale.detail
           and "05_figures/legends.md" in rnd3["reviewed"] and fresh.ok,
           stale.detail + " | " + fresh.detail)
    data = rr.load(p)
    data["manuscript"][-1]["reviewed"] = []
    (p / rr.REL).write_text(json.dumps(data), encoding="utf-8")
    record("a delta round that skipped a changed file fails",
           any("skipped changed" in x for x in rr.problems(p, "manuscript", None)))
    record("approval cannot be recorded while a round is open or covered files drifted",
           early.returncode != 0 or "changed after" in early.stderr, early.stderr[-200:])
    # A legacy S19 paper with a review ZIP and no rounds keeps the legacy release check.
    q, _ = _review_paper(tmp / "legacy")
    (q / "07_manuscript/review_packages").mkdir(parents=True)
    (q / "07_manuscript/review_packages/latest_review_package.json").write_text("{}", encoding="utf-8")
    lg = get("review_round_approved")(Ctx(pipeline=pipe, state=State(q, ".wf").load(), project=q,
                                          stage=pipe.stage("S19_human_review"),
                                          spec={"check": "review_round_approved"}))
    record("a legacy S19 paper with a review ZIP is judged by the legacy package check",
           "legacy review package" in lg.detail, lg.detail)
    st = State(q, ".wf").load()
    st.data["pipeline_version"] = "1.8.0"
    st.save()
    st = State(q, ".wf").load()
    st.migrate_pipeline("1.8.1", [s.id for s in pipe.stages])
    events = [e for e in State(q, ".wf").load().data.get("events", [])
              if e.get("kind") == "requirements_changed"]
    record("migration to 1.8.1 records an event only (no paper file rewritten)",
           len(events) == 1 and "review_round.py" in events[0]["detail"]
           and (q / "07_manuscript/review_packages/latest_review_package.json").read_text() == "{}")


def run(tmp: Path, record, section) -> None:
    tmp.mkdir(parents=True, exist_ok=True)
    run_tables(tmp, record, section)
    run_review(tmp, record, section)
