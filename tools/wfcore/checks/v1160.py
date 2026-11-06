"""1.16.0 checks (stricter checks; a paper pinned earlier gets them after `wf migrate --yes`).

table_percent_denominators  N3: a plain unweighted 'n (x%)' / 'n/N (x%)' table cell is
                            numerator / its column denominator ('N = ...' / '(n = ...)' in the
                            column header, or a proportion record with the same numerator and
                            population); the column population must match the records. No
                            denominator source: warning at S10, failure at S12.
figure_statistics_bound     N5: statistics printed as text in a figure (effect estimates, CI,
                            AUC, P, n, percentages) match a value in that figure's OWN
                            source_results, and the render receipt (script, source and output
                            hashes) is fresh, for R and Python figures alike.
displays_seen_current       N10b: the one contact-sheet look before Results (decision
                            displays_seen_before_results) is bound to the hashes of the displays
                            it saw; a changed display needs one new look.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from . import Ctx, Result, check
from .numbers import (NUM_RE, P_RE, THOUSANDS_RE, _matches, _p_ok, _since_1160,
                      _stated_thresholds, _walk)

PLAN = "01_protocol/artifact_plan.json"


def _plan(ctx: Ctx) -> dict:
    try:
        data = json.loads(ctx.p(PLAN).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _sha(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest().upper()
    except OSError:
        return None


def _pinned_out(name: str) -> Result:
    return Result(True, name, "applies from engine 1.16.0 (`wf migrate --yes`); paper pinned "
                              "earlier")


# ------------------------------------------------------------------ N3 table denominators
_CELL = re.compile(r"^\s*(\d[\d,]*)\s*(?:/\s*(\d[\d,]*)\s*)?\(\s*(\d+(?:\.\d+)?)\s*(%?)\s*\)\s*$")
_COL_N = re.compile(r"(?<![\w])[nN]\s*=\s*(\d[\d,\u2009\u202f ]*\d|\d)")
_NPCT_LABEL = re.compile(r"(?i)\b(?:n|no\.?|number)\s*(?:/\s*N\s*)?\(\s*%\s*\)")
_NOT_COUNT = re.compile(r"(?i)\b(?:mean|median|sd|iqr|range|rate|ratio|ci)\b")
_WEIGHTED = re.compile(r"(?i)\bweighted\b")


def _int(s: str) -> int:
    return int(re.sub(r"[,\u2009\u202f ]", "", s))


def _table_rows(path: Path, sheet_name: str | None):
    """(title, header cells {col: text}, body rows [{col: text}]) per sheet."""
    from .. import xlsxlite
    wb = xlsxlite.Workbook(path)
    sheets = [wb.sheet(sheet_name)] if sheet_name else wb.sheets
    for sh in [s for s in sheets if s is not None]:
        ruled = [r for r in range(1, sh.max_row + 1)
                 if any(wb.border_of(c).top or wb.border_of(c).bottom for c in sh.row_cells(r))]
        head = min(ruled) if ruled else 2
        last = max(ruled) if ruled else sh.max_row
        title = " ".join(c.value or "" for c in sh.row_cells(1)) if head > 1 else ""
        header = {c.col: str(c.value or "") for c in sh.row_cells(head)}
        body = [{c.col: str(c.value or "") for c in sh.row_cells(r)} for r in range(head + 1, last + 1)]
        yield sh.name, title, header, body


@check("table_percent_denominators")
def table_percent_denominators(ctx: Ctx) -> Result:
    name = "table_percent_denominators"
    if not _since_1160(ctx):
        return _pinned_out(name)
    from .v1110 import _proportions
    from .. import clinical
    records = [r for r in _proportions(ctx) if int(r.get("denominator", 0) or 0) > 0]
    names = clinical.internal_names(clinical.dictionary(ctx.project))
    plan = _plan(ctx)
    wrong, missing, checked = [], [], 0
    for e in list(plan.get("main_tables", [])) + list(plan.get("supp_tables", [])):
        path = ctx.p(str(e.get("file", "")))
        if not path.is_file():
            continue
        try:
            tables = list(_table_rows(path, e.get("sheet")))
        except Exception:  # noqa: BLE001 - unreadable workbooks are reported by tables_threeline
            continue
        for sheet, title, header, body in tables:
            if _WEIGHTED.search(title):
                continue
            col_n, col_pop = {}, {}
            for col, text in header.items():
                m = _COL_N.search(text)
                if m:
                    col_n[col] = _int(m.group(1))
                for r in records:
                    pop = str(r["population"])
                    if any(re.search(rf"(?i)(?<![\w-]){re.escape(x)}(?![\w-])", text)
                           for x in {pop, names.get(pop, pop)} if len(x) >= 3):
                        col_pop[col] = pop
            for col, n in col_n.items():
                if col not in col_pop:
                    pops = {str(r["population"]) for r in records if int(r["denominator"]) == n}
                    if len(pops) == 1:
                        col_pop[col] = pops.pop()
            for row in body:
                label = row.get(min(row), "") if row else ""
                for col, text in row.items():
                    if col == min(row) or _WEIGHTED.search(header.get(col, "")):
                        continue
                    m = _CELL.match(text)
                    if not m or (not m.group(4) and not _NPCT_LABEL.search(label)):
                        continue
                    if _NOT_COUNT.search(label) and not m.group(4):
                        continue
                    checked += 1
                    num, pct = _int(m.group(1)), float(m.group(3))
                    den_cell = _int(m.group(2)) if m.group(2) else None
                    dec = len(m.group(3).split(".")[1]) if "." in m.group(3) else 0
                    tol = 0.5 * 10 ** -dec + 1e-9
                    where = f"{e.get('id')}[{sheet}] '{label.strip()[:30]}' x '{header.get(col, '').strip()[:30]}' = {text.strip()}"

                    def fits(den):
                        return den and abs(100.0 * num / den - pct) <= tol
                    hits = [r for r in records if int(r["numerator"]) == num
                            and fits(int(r["denominator"]))]
                    if den_cell is not None:
                        if not fits(den_cell):
                            wrong.append(f"{where}: {num}/{den_cell} is {100.0 * num / den_cell:.{dec}f}%")
                            continue
                    elif col in col_n:
                        if not fits(col_n[col]) and not hits:
                            wrong.append(f"{where}: {num}/{col_n[col]} (column N) is "
                                         f"{100.0 * num / col_n[col]:.{dec}f}%")
                            continue
                    elif not hits:
                        missing.append(where)
                        continue
                    if hits and col in col_pop and col_pop[col] not in {str(h["population"]) for h in hits}:
                        wrong.append(f"{where}: the proportion record(s) are for "
                                     f"{sorted({str(h['population']) for h in hits})}, the column "
                                     f"is {col_pop[col]}")
    hints = ["A plain 'n (%)' cell must be n / the column denominator: put 'N = ...' (or "
             "'(n = ...)') in the column header, or record the proportion with "
             "analysis.results.proportion(numerator, denominator, population).",
             "Columns or tables marked 'weighted', and CI cells, are not judged by this rule."]
    if wrong:
        return Result(False, name, f"{len(wrong)} n (%) cell(s) disagree with their denominator: "
                      + "; ".join(wrong[:6]), hints)
    if missing:
        sev = str(ctx.spec.get("missing", "warn"))
        return Result(False, name, f"{len(missing)} n (%) cell(s) without a denominator source: "
                      + "; ".join(missing[:6]), hints, severity="warn" if sev == "warn" else "fail")
    return Result(True, name, f"{checked} n (%) cell(s) agree with their column denominators")


# ------------------------------------------------------------------ N5 figure statistics
_STAT_CS = re.compile(r"(?<![\w-])(?:a?HRs?|a?ORs?|a?RRs?|IRR|ROR|PRR|AUCs?|AUROC|SMD|MD|RD|"
                      r"CIs?|I2|NNT)(?![\w-])")
_STAT_CI = re.compile(r"hazard ratio|odds ratio|risk ratio|area under|c[- ]index|log-rank|"
                      r"\b[Pp]\s*[=<>\u2264\u2265]|(?<![\w])[nN]\s*=|"
                      r"\d\s*\(\s*[-\u2212]?\d+(?:\.\d+)?\s*(?:[-\u2013\u2014,;]|to)\s*[-\u2212]?\d|"
                      r"\d+\.\d+\s*%|\d+\s*\(\s*\d+(?:\.\d+)?\s*%\s*\)|I\u00b2", re.I)
_CI_LEVEL = re.compile(r"(?<![\w.])(?:90|95|99)\s?%\s*(?=CI|CrI|confidence|credible)", re.I)


def stat_texts(texts: list[str]) -> list[str]:
    """In-figure texts that print a statistic (not tick labels, panel letters or legend keys:
    those carry no statistic word, interval or n=)."""
    return [t for t in texts if NUM_RE.search(t) and (_STAT_CS.search(t) or _STAT_CI.search(t))]


def _source_pool(project: Path, rels: list[str]):
    strings: set[str] = set()
    stated: set = set()
    for rel in rels:
        try:
            data = json.loads((project / rel).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            data = {k: v for k, v in data.items() if k != "environment"}
        _walk(data, strings)
        _stated_thresholds(data, stated)
    floats = set()
    for s in strings:
        try:
            floats.add(float(s))
        except ValueError:
            pass
    return floats, strings, stated


def unbound_statistics(text: str, floats, strings, stated) -> list[str]:
    bad = []
    work = THOUSANDS_RE.sub("", _CI_LEVEL.sub(" ", text))

    def pval(m):
        if not _p_ok(m.group(1), m.group(2), floats, stated, frozenset()):
            bad.append("P" + m.group(1) + m.group(2))
        return " "
    work = P_RE.sub(pval, work)
    for m in NUM_RE.finditer(work):
        if not _matches(m.group(1), floats, strings):
            bad.append(m.group(1))
    return bad


def receipt_problems(project: Path, art: dict, entry: dict) -> list[str]:
    """Is the render receipt (R save_medpaper / Python figures.style.save) still fresh?"""
    png_rel = str(entry.get("file", ""))
    keys = ("script", "script_sha256", "source_hashes", "render_hashes")
    if not any(k in art for k in keys):
        return ["no render receipt (script, source and output hashes); re-render with "
                "save_medpaper() (R) or figures.style.save() (Python)"]
    out = []
    renders = art.get("render_hashes") if isinstance(art.get("render_hashes"), dict) else {}
    if png_rel not in renders:
        out.append("no bound PNG render hash")
    for rel, expected in renders.items():
        if _sha(project / rel) != str(expected).upper():
            out.append(f"output changed after rendering: {rel}")
    script = str(art.get("script") or "")
    if not script:
        out.append("the render receipt names no plotting script")
    elif _sha(project / script) != str(art.get("script_sha256", "")).upper():
        out.append(f"plotting script changed after rendering: {script}")
    sources = art.get("source_hashes") if isinstance(art.get("source_hashes"), dict) else {}
    declared = {str(s) for s in entry.get("source_results") or []}
    if set(sources) != declared:
        out.append("result sources in the render receipt differ from the plan's source_results")
    for rel, expected in sources.items():
        if _sha(project / rel) != str(expected).upper():
            out.append(f"result changed after rendering: {rel}")
    return out


@check("figure_statistics_bound")
def figure_statistics_bound(ctx: Ctx) -> Result:
    name = "figure_statistics_bound"
    if not _since_1160(ctx):
        return _pinned_out(name)
    plan = _plan(ctx)
    problems, n = [], 0
    for e in list(plan.get("main_figures", [])) + list(plan.get("supp_figures", [])):
        png_rel = str(e.get("file", ""))
        side = ctx.p(f"05_figures/qc/{Path(png_rel).stem}.artist.json")
        if not png_rel or not side.is_file():
            continue  # figures_qc_pass reports a missing render or sidecar
        try:
            art = json.loads(side.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            problems.append(f"{e.get('id')}: unreadable render sidecar")
            continue
        n += 1
        fid = e.get("id")
        problems += [f"{fid}: {p}" for p in receipt_problems(ctx.project, art, e)]
        stats = stat_texts([str(t) for t in art.get("figure_text") or []])
        if not stats:
            continue
        rels = [str(s) for s in e.get("source_results") or []]
        if not rels:
            problems.append(f"{fid}: prints statistics ({stats[0][:40]!r}) but declares no "
                            "source_results in the artifact plan")
            continue
        floats, strings, stated = _source_pool(ctx.project, rels)
        for t in stats:
            bad = unbound_statistics(t, floats, strings, stated)
            if bad:
                problems.append(f"{fid}: '{t[:50]}' -> {', '.join(bad[:4])} not in its own "
                                f"source_results ({', '.join(rels[:2])})")
    if problems:
        return Result(False, name, f"{len(problems)} problem(s): " + "; ".join(problems[:8]),
                      ["A statistic printed in a figure (HR/OR/AUC with CI, P, n, %) must come "
                       "from the figure's own source_results; pass the values from that JSON "
                       "into the plotting script, never type them.",
                       "After any change to the plotting script or its results, re-render the "
                       "figure (wf run-script ...) so the render receipt is fresh."])
    return Result(True, name, f"{n} figure(s): printed statistics match their own source_results; "
                              "render receipts fresh")


# ------------------------------------------------------------------ N10b displays look
SHEET_MANIFEST = "05_figures/qc/displays_sheet.json"
DISPLAYS_DECISION = "displays_seen_before_results"


def display_hashes(project: Path) -> dict[str, str]:
    """id -> sha256 of every planned display's rendered file (figure PNG, table workbook)."""
    try:
        plan = json.loads((Path(project) / PLAN).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out = {}
    for g in ("main_figures", "supp_figures", "main_tables", "supp_tables"):
        for e in plan.get(g, []) if isinstance(plan, dict) else []:
            rel = str(e.get("file", ""))
            h = _sha(Path(project) / rel) if rel else None
            if h:
                out[str(e.get("id"))] = h
    return out


@check("displays_seen_current")
def displays_seen_current(ctx: Ctx) -> Result:
    name = "displays_seen_current"
    if not _since_1160(ctx):
        return _pinned_out(name)
    rec = ctx.state.decision(DISPLAYS_DECISION)
    if not rec:
        return Result(True, name, f"no {DISPLAYS_DECISION} decision yet (decision_recorded "
                                  "reports it)")
    seen = rec.get("displays")
    if not isinstance(seen, dict) or not seen:
        return Result(False, name, f"{DISPLAYS_DECISION} is not bound to the displays it saw",
                      ["Make the one contact sheet and record the look again:",
                       "tools/figures/qc.py --contact-sheet --with-tables, then wf decide "
                       f"{DISPLAYS_DECISION} YES --why \"...\""])
    now = display_hashes(ctx.project)
    changed = sorted(k for k in set(now) | set(seen) if now.get(k) != seen.get(k))
    if changed:
        return Result(False, name, "display(s) changed after the look before Results: "
                      + ", ".join(changed[:8]),
                      ["One new look: tools/figures/qc.py --contact-sheet --with-tables (the "
                       "changed displays are marked CHANGED), then wf decide "
                       f"{DISPLAYS_DECISION} YES --why \"...\"."])
    return Result(True, name, f"the look before Results covers the current {len(now)} display(s)")
