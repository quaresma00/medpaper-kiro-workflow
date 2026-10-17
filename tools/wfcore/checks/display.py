"""1.9.0 S12 display-item checks moved forward from the final audit (#18, #19).

* numbering follows first citation: within each series (main figures, main tables,
  supplementary figures, supplementary tables) the n-th first-cited item is number n;
* a table caption has one source of truth: the caption in 04_tables/table_captions.md and the
  title row of the workbook must say the same thing (the "Table N." label is ignored);
* panels of a multi-panel figure: citing the whole figure ("Figure 2") counts for all its
  panels; once any panel is cited on its own ("Figure 2C"), every panel listed in the legend
  must be cited individually somewhere.
"""
from __future__ import annotations

import re

from . import Ctx, Result, check

CITE_RE = re.compile(
    r"\b(?:(supplementary|supplemental|suppl\.?)\s+)?(figure|fig\.?|table)s?\s*(S?)(\d+)"
    r"((?:[A-Za-z](?![A-Za-z]))(?:\s*(?:[-\u2013,]|and)\s*[A-Za-z](?![A-Za-z]))*)?", re.I)
PANEL_RE = re.compile(r"\(([A-Za-z])\)")
FENCE_RE = re.compile(r"```.*?```", re.S)


def _series(kind: str, supp: bool) -> str:
    return ("supp " if supp else "main ") + ("figure" if kind.lower().startswith("fig") else "table")


def _panels(spec: str) -> set[str]:
    """'C' -> {C}; 'A-C' -> {A,B,C}; 'A and D' -> {A,D}."""
    out: set[str] = set()
    spec = (spec or "").upper()
    for a, b in re.findall(r"([A-Z])\s*[-\u2013]\s*([A-Z])", spec):
        out.update(chr(c) for c in range(ord(a), ord(b) + 1))
    spec = re.sub(r"[A-Z]\s*[-\u2013]\s*[A-Z]", " ", spec)
    out.update(re.findall(r"[A-Z]", spec.replace("AND", " ")))
    return out


def citations(text: str) -> list[tuple[str, int, set[str]]]:
    """(series, number, panels) in reading order."""
    out = []
    for m in CITE_RE.finditer(FENCE_RE.sub(" ", text)):
        supp = bool(m.group(1)) or bool(m.group(3))
        out.append((_series(m.group(2), supp), int(m.group(4)), _panels(m.group(5) or "")))
    return out


def order_problems(cites: list[tuple[str, int, set[str]]]) -> list[str]:
    seen: dict[str, list[int]] = {}
    for series, num, _ in cites:
        lst = seen.setdefault(series, [])
        if num not in lst:
            lst.append(num)
    problems = []
    for series, nums in seen.items():
        if nums != sorted(nums) or nums != list(range(1, len(nums) + 1)):
            label = series.split()[1].capitalize() + (" S" if series.startswith("supp") else " ")
            problems.append(f"{series}s are first cited in the order "
                            + ", ".join(f"{label}{n}".replace("  ", " ") for n in nums)
                            + " - renumber so the n-th first-cited item is number n")
    return problems


def legend_panels(legends: str) -> dict[tuple[str, int], set[str]]:
    out: dict[tuple[str, int], set[str]] = {}
    blocks = re.split(r"(?mi)^#{1,6}\s+(?=(?:Figure|Fig\.?)\s+S?\d+)", legends)
    for block in blocks:
        m = re.match(r"(?i)(?:Figure|Fig\.?)\s+(S?)(\d+)", block)
        if not m:
            continue
        panels = set(PANEL_RE.findall(block))
        panels = {p.upper() for p in panels}
        if len(panels) >= 2:
            out[(_series("figure", bool(m.group(1))), int(m.group(2)))] = panels
    return out


def panel_problems(cites, panels_by_fig) -> list[str]:
    problems = []
    for key, panels in sorted(panels_by_fig.items()):
        cited = set()
        for series, num, ps in cites:
            if (series, num) == key:
                cited |= ps
        if cited and cited != panels and not panels <= cited:
            label = ("Figure S" if key[0].startswith("supp") else "Figure ") + str(key[1])
            problems.append(f"{label}: panel(s) {', '.join(sorted(panels - cited))} never cited "
                            f"although panel(s) {', '.join(sorted(cited))} are cited individually "
                            "(cite every panel, or cite the whole figure only)")
    return problems


def _norm_caption(text: str) -> str:
    text = re.sub(r"(?i)^\s*(?:supplementary\s+)?table\s+S?\d+[.:]?\s*", "", text or "")
    return re.sub(r"[\s.]+", " ", text).strip().casefold()


def caption_problems(ctx: Ctx) -> list[str]:
    from .. import docxaudit, xlsxlite
    try:
        plan = ctx.read_json("01_protocol/artifact_plan.json")
    except (OSError, ValueError):
        return []
    path = ctx.p("04_tables/table_captions.md")
    if not path.is_file():
        return []
    caps = {}
    text = path.read_text(encoding="utf-8")
    for m in re.finditer(r"(?mi)^#{2,6}\s+(Table\s+S?\d+)\.?[ \t]*(.*)$\n?((?:(?!#).*\S.*\n?)*)", text):
        caps[docxaudit.canon_figure_id(m.group(1))] = m.group(2).strip() or " ".join(m.group(3).split())
    problems = []
    for e in plan.get("main_tables", []) + plan.get("supp_tables", []):
        tid = docxaudit.canon_figure_id(str(e.get("id", "")))
        f = ctx.p(str(e.get("file", "")))
        if tid not in caps or not f.is_file():
            continue
        try:
            wb = xlsxlite.Workbook(f)
        except Exception:  # noqa: BLE001
            continue
        sheet = wb.sheet(e["sheet"]) if e.get("sheet") else (wb.sheets[0] if wb.sheets else None)
        if sheet is None:
            continue
        a1 = next((c.value for c in sheet.cells if c.ref == "A1"), "") or ""
        if not re.match(r"(?i)\s*(?:supplementary\s+)?table\s+S?\d+", a1):
            continue  # no title row in the workbook: the captions file is the only source
        if _norm_caption(a1) != _norm_caption(caps[tid]):
            problems.append(f"{e.get('id')}: workbook title '{a1[:70]}' differs from "
                            f"table_captions.md '{caps[tid][:70]}'")
    return problems


@check("display_numbering_consistent")
def display_numbering_consistent(ctx: Ctx) -> Result:
    rels = ctx.spec.get("paths") or ["07_manuscript/methods.md", "07_manuscript/results.md"]
    rels = [ctx.src(r) for r in rels if ctx.psrc(r).is_file()]
    text = "\n\n".join(ctx.read(r) for r in rels)
    if not text.strip():
        return Result(False, "display_numbering_consistent", "no manuscript text to scan")
    from .. import journalspec
    text = journalspec.expand_aliases(text, journalspec.project_aliases(ctx.project))
    cites = citations(text)
    legends = ctx.read("05_figures/legends.md") if ctx.p("05_figures/legends.md").is_file() else ""
    problems = (order_problems(cites) + panel_problems(cites, legend_panels(legends))
                + caption_problems(ctx))
    if problems:
        return Result(False, "display_numbering_consistent", "; ".join(problems[:8]),
                      ["Renumber in the artifact plan, scripts, captions and text together (S07/S10/"
                       "S11 sources), then rebuild; keep one caption source per table."])
    return Result(True, "display_numbering_consistent",
                  f"{len(cites)} citation(s): first-citation order, panel coverage and captions agree")
