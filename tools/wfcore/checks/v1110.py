"""1.11.0 checks: the clinical presentation layer.

Display dictionary, clinical labels, engineering-language lint, self-contained display
abbreviations, flow-diagram units, Word keep-with-next, closed review findings, provisional
journal parameters, print font size, result presentation, concise footnotes, proportion
denominators.

Every gate using these is declared with since = "1.11.0", so a paper pinned to an earlier
engine keeps its completed stages. Each failure names its legitimate exception path.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .. import clinical
from . import Ctx, Result, check

ALLOW_HINT = (f"A genuinely needed term: add it with a reason to {clinical.ALLOW_REL} "
              '({"terms": [{"term": "...", "reason": ">= 15 chars", "scope": "methods|all"}]}); '
              "never edit reference/ or the engine.")


def _target(ctx: Ctx) -> dict:
    from .. import journalspec
    return journalspec.load(ctx.project)


# ------------------------------------------------------------ 1a display dictionary (S07)
@check("display_dictionary_ready")
def display_dictionary_ready(ctx: Ctx) -> Result:
    data = clinical.dictionary(ctx.project)
    problems = clinical.dictionary_problems(data)
    if problems:
        return Result(False, "display_dictionary_ready", "; ".join(problems[:8]),
                      [f"Write {clinical.DICT_REL}: one entry per internal group, outcome, "
                       'contrast or model name: {"internal": "comp_a", "aliases": ["Composite A"], '
                       '"label": "<clinical name>", "abbreviation": "<or empty>", "definition": '
                       '"<one line>"}. Table builders, figure scripts and prose use only the label.'])
    n = len(data.get("terms", []))
    return Result(True, "display_dictionary_ready",
                  f"{n} internal name(s) mapped to clinical labels" if n
                  else "no coded internal names (reason recorded)")


def _texts(ctx: Ctx) -> list[tuple[str, str, bool]]:
    """(where, text, blocking) for the files and displays a gate spec names."""
    out = []
    for rel in ctx.spec.get("paths", []):
        rel = ctx.src(rel)
        if ctx.p(rel).is_file():
            out.append((rel, ctx.read(rel), True))
    return out + _display_texts(ctx, ctx.spec.get("displays"))


def _display_texts(ctx: Ctx, disp) -> list[tuple[str, str, bool]]:
    out = []
    if disp:
        for d in clinical.display_items(ctx.project):
            if disp == "tables" and d["kind"] != "table" or disp == "figures" and d["kind"] != "figure":
                continue
            body = "\n".join([d["caption"], *d["cells"], *d["footnotes"], *d["figure_text"]])
            out.append((d["id"], body, d["main"]))
    return out


# --------------------------------------------------------- 1a clinical labels everywhere
@check("clinical_labels_used")
def clinical_labels_used(ctx: Ctx) -> Result:
    data = clinical.dictionary(ctx.project)
    if data is None:
        return Result(False, "clinical_labels_used", f"{clinical.DICT_REL} missing",
                      ["Create the display dictionary (S07 card) before building displays."])
    problems = []
    for where, text, _ in _texts(ctx):
        hits = clinical.label_problems(text, data)
        if hits:
            problems.append(f"{where}: " + ", ".join(hits[:4]))
    if problems:
        return Result(False, "clinical_labels_used", "; ".join(problems[:8]),
                      ["Use the dictionary's clinical label in table builders (row/column "
                       "labels), R/Python figure labels (mf_label(clinical_label(...))) and prose.",
                       f"A letter code that is the field's real name: make it the label in "
                       f"{clinical.DICT_REL} with 'letter_code_reason'."])
    return Result(True, "clinical_labels_used",
                  f"{len(_texts(ctx))} source(s) use clinical labels only")


# --------------------------------------------------------- 1b engineering-language lint
def _file_hits(ctx: Ctx, rel: str, text: str, allowed) -> tuple[list[str], list[str]]:
    name = Path(rel).name.casefold()
    if "supplementary" in name:
        return [], []
    block, warn = [], []
    secs = clinical.sections(text)
    target = _target(ctx)
    if len(secs) >= 2:
        parts = [(clinical.role_of(h, target), b) for h, b in secs]
    else:
        role = next((r for r in ("methods", "results", "discussion", "introduction", "abstract",
                                 "conclusion") if r in name), "results")
        parts = [(role, text)]
    for role, body in parts:
        if role in clinical.WARN_SECTIONS:
            hits = clinical.engineering_hits(body, allowed, "methods")
            warn += [f"{rel} [Methods]: '{m}' -> {s}" for _t, m, s in hits]
        elif role in clinical.BLOCK_SECTIONS:
            hits = clinical.engineering_hits(body, allowed, role)
            block += [f"{rel} [{role.title()}]: '{m}' -> {s}" for _t, m, s in hits]
    return block, warn


@check("engineering_language_clean")
def engineering_language_clean(ctx: Ctx) -> Result:
    allowed = clinical.allowlist(ctx.project)
    block, warn = [], []
    for rel in ctx.spec.get("paths", []):
        rel = ctx.src(rel)
        if ctx.p(rel).is_file():
            b, w = _file_hits(ctx, rel, ctx.read(rel), allowed)
            block += b
            warn += w
    for where, text, main in _display_texts(ctx, ctx.spec.get("displays")):
        hits = clinical.engineering_hits(text, allowed, "display")
        (block if main else warn).extend(f"{where}: '{m}' -> {s}" for _t, m, s in hits)
    # 1.13.0 (G5): quoted labels coined during the analysis, absent from the dictionary (warn).
    ddata = clinical.dictionary(ctx.project)
    texts = [(ctx.src(r), ctx.read(ctx.src(r))) for r in ctx.spec.get("paths", [])
             if ctx.p(ctx.src(r)).is_file()]
    texts += [(w, t) for w, t, _m in _display_texts(ctx, ctx.spec.get("displays"))]
    for where, text in texts:
        warn += [f"{where}: coined label \"{x}\" -> use its clinical name and add it to "
                 f"{clinical.DICT_REL}" for x in clinical.coined_labels(text, ddata, allowed)]
    hints = ["Body Methods state principles; implementation detail (parsing, matching rules, "
             "character handling, code-level steps) goes to Supplementary Methods.", ALLOW_HINT]
    if block:
        return Result(False, "engineering_language_clean",
                      f"{len(block)} engineering term(s) in reader-facing text: " + "; ".join(block[:6]),
                      hints)
    if warn:
        return Result(False, "engineering_language_clean",
                      f"{len(warn)} implementation term(s) (advisory): " + "; ".join(warn[:6]),
                      hints, severity="warn")
    return Result(True, "engineering_language_clean", "no engineering language in reader-facing text")


# ----------------------------------------------------- 1c self-contained abbreviations
@check("display_abbreviations_defined")
def display_abbreviations_defined(ctx: Ctx) -> Result:
    target = _target(ctx)
    placement = str(target.get("abbreviation_placement", "self_contained")).strip().casefold()
    from ..state import version_tuple
    if placement in ("central", "local_required") and \
            version_tuple(ctx.state.engine_pin) < (1, 11, 0):
        # A paper that chose its placement under the pre-1.11 rule keeps it (no churn of
        # frozen legends); `wf migrate` adopts self-contained displays.
        from .artifacts import abbreviations_centralized
        res = abbreviations_centralized(ctx)
        return Result(res.ok, "display_abbreviations_defined",
                      f"legacy placement '{placement}' (engine pin {ctx.state.engine_pin}): "
                      + res.detail, res.hints)
    central_only = placement == "central_required"
    items = clinical.display_items(ctx.project)
    problems, used_all = [], set()
    for d in items:
        visible = "\n".join([d["caption"], *d["cells"], *d["figure_text"]])
        notes = "\n".join([d["caption"], *d["footnotes"], *d["figure_text"]])
        used = clinical.used_abbreviations(visible + "\n" + "\n".join(d["footnotes"]))
        used_all |= used
        if central_only:
            if re.search(r"(?i)\bAbbreviations?\s*:", notes):
                problems.append(f"{d['id']}: the journal requires one central list; remove the "
                                "local Abbreviations block")
            continue
        missing = sorted(used - clinical.defined_abbreviations(notes))
        if missing:
            problems.append(f"{d['id']}: defines not " + ", ".join(missing[:8]))
    full_rel = ctx.src("07_manuscript/full_manuscript.md")
    if ctx.spec.get("central_list") and used_all:
        full = ctx.read(full_rel) if ctx.p(full_rel).is_file() else ""
        central = clinical.central_list(full)
        if central is None:
            problems.append(f"{full_rel}: no '## Abbreviations' list (the manuscript keeps a "
                            "central list in addition to the per-display definitions)")
        else:
            lack = sorted(used_all - central)
            if lack:
                problems.append("central Abbreviations list lacks: " + ", ".join(lack[:10]))
    if problems:
        return Result(False, "display_abbreviations_defined", "; ".join(problems[:8]),
                      ["Each table footnote and figure legend defines the abbreviations it uses "
                       "('Abbreviations: CI, confidence interval; ...'), so the display reads on "
                       "its own; the manuscript also keeps one central list.",
                       "Only a journal that explicitly requires a single central list changes "
                       "this: target_journal.json abbreviation_placement = 'central_required' "
                       "with abbreviation_rule_source quoting the guide."])
    mode = "central list only (journal rule)" if central_only else "self-contained displays"
    return Result(True, "display_abbreviations_defined",
                  f"{len(items)} display item(s), {len(used_all)} abbreviation(s); {mode}")


# ------------------------------------------------------------ 1d flow diagram units
@check("flow_diagram_units")
def flow_diagram_units(ctx: Ctx) -> Result:
    problems, n = [], 0
    for d in clinical.display_items(ctx.project, include_supp=False):
        if d["kind"] != "figure" or d.get("archetype") != "flow_diagram":
            continue
        n += 1
        if not d["figure_text"]:
            problems.append(f"{d['id']}: no in-figure text in the render sidecar (re-render with "
                            "save_medpaper()/style.save())")
            continue
        problems += [f"{d['id']}: {p}" for p in clinical.flow_unit_problems(d["figure_text"])]
    if problems:
        return Result(False, "flow_diagram_units", "; ".join(problems[:6]),
                      ["Each count box states its analysis unit ('Reports screened (n = 1,204)'). "
                       "Lines read, rows, files, versions or quarters loaded are processing logs: "
                       "put data volume in a supplementary data-scale table."])
    return Result(True, "flow_diagram_units",
                  f"{n} main flow diagram(s): every count names an analysis unit" if n
                  else "no main flow diagram planned")


# ------------------------------------------------------------ 1e Word keep-with-next
@check("docx_keep_with_next")
def docx_keep_with_next(ctx: Ctx) -> Result:
    import zipfile
    from xml.etree import ElementTree as ET
    from .. import docxaudit
    files = [p for p in ctx.glob("08_submission/bundle/*.docx")
             if re.search(r"manuscript|main|tables|legend", p.name, re.I)]
    if not files:
        return Result(False, "docx_keep_with_next", "no manuscript DOCX under 08_submission/bundle/",
                      ["Build it with tools/manuscript/build_docx.py."])
    problems = []
    for p in files:
        try:
            with zipfile.ZipFile(p) as zf:
                root = ET.fromstring(zf.read("word/document.xml"))
                styles = ET.fromstring(zf.read("word/styles.xml")) \
                    if "word/styles.xml" in zf.namelist() else None
        except (OSError, KeyError, zipfile.BadZipFile, ET.ParseError) as exc:
            problems.append(f"{p.name}: unreadable ({exc})")
            continue
        problems += [f"{p.name}: {x}" for x in docxaudit.keep_problems(root, styles)]
    if problems:
        return Result(False, "docx_keep_with_next", "; ".join(problems[:6]),
                      ["Rebuild with this engine's build_docx.py (1.13.0): no keepNext/keepLines/"
                       "pageBreakBefore anywhere (Word shows them as black squares); tables "
                       "start their own section with cantSplit rows and a repeated header, each "
                       "embedded figure starts after a page break and is sized to fit with its "
                       "legend, or set figures_at_end in target_journal.json."])
    return Result(True, "docx_keep_with_next",
                  f"{len(files)} DOCX: no keep markers (no black squares); tables and figures "
                  "held by structure")


# --------------------------------------------------------------- 1f review closure
@check("review_findings_closed")
def review_findings_closed(ctx: Ctx) -> Result:
    from .. import reviewrounds as rr
    scope = ctx.spec.get("scope", "manuscript")
    problems = rr.closure_problems(ctx.project, scope)
    if problems:
        return Result(False, "review_findings_closed", "; ".join(problems[:6]),
                      ["Save the reviewer's report and close with --report <file>; every "
                       "numbered finding (all sections, incl. Reader comprehension and Medical "
                       "presentation) needs --finding ID ... changed|kept|author, and each kept "
                       "one a --kept ID \"reason\"."])
    rounds = [r for r in rr.load(ctx.project)[scope] if r.get("protocol")]
    n = sum(len(r.get("report_ids", [])) for r in rounds)
    return Result(True, "review_findings_closed",
                  f"{n} numbered finding(s) across {len(rounds)} 1.11 round(s), all closed")


# ------------------------------------------------- 2a provisional journal parameters
@check("provisional_journal_params")
def provisional_journal_params(ctx: Ctx) -> Result:
    from .. import presentparams as pp
    block = pp.provisional(ctx.project)
    if not block:
        return Result(False, "provisional_journal_params", f"{pp.PROVISIONAL} missing",
                      [f"Write {pp.PROVISIONAL} now (provisional target journal or journal type): "
                       '{"status": "provisional", "journal_or_type": "...", "font_min_pt": 8, '
                       '"figure_width_mm": {"single": 85, "1.5": 140, "double": 175}, '
                       '"panel_label_case": "upper|lower", "line_art_dpi": 600, "number_format": '
                       '{"thousands": ",", "p_space": true}, "spelling": "american", '
                       '"heading_names": {}, "source": "..."}. Tables and figures use it from the '
                       "first render; S20 confirms or replaces it (a re-render, not science)."])
    problems = pp.problems(block, pp.PROVISIONAL)
    if len(str(block.get("journal_or_type", "")).strip()) < 3:
        problems.append("journal_or_type missing")
    if problems:
        return Result(False, "provisional_journal_params", "; ".join(problems[:6]))
    return Result(True, "provisional_journal_params",
                  f"provisional presentation for {block['journal_or_type']}: font >= "
                  f"{block['font_min_pt']} pt, widths {block['figure_width_mm']}, panel labels "
                  f"{block['panel_label_case']}")


@check("presentation_params_confirmed")
def presentation_params_confirmed(ctx: Ctx) -> Result:
    from .. import presentparams as pp
    conf, prov = pp.confirmed(ctx.project), pp.provisional(ctx.project)
    if not conf:
        return Result(False, "presentation_params_confirmed",
                      f'{pp.TARGET} has no "presentation" block',
                      ['Copy the provisional values that hold for this journal and replace the '
                       'rest from the guide: "presentation": {"font_min_pt", "figure_width_mm", '
                       '"panel_label_case", "line_art_dpi", "number_format", "spelling", '
                       '"heading_names"}.'])
    problems = pp.problems({**{k: v for k, v in prov.items() if k in pp.KEYS}, **conf}, pp.TARGET)
    if problems:
        return Result(False, "presentation_params_confirmed", "; ".join(problems[:6]))
    changed = sorted(k for k in pp.KEYS if k in conf and prov.get(k) != conf.get(k))
    if changed:
        return Result(True, "presentation_params_confirmed",
                      "journal replaces provisional " + ", ".join(changed)
                      + ": re-render tables/figures (presentation; facts unchanged, no S19 return)")
    return Result(True, "presentation_params_confirmed", "journal confirms the provisional parameters")


# -------------------------------------------------- 2b final-size font in figures
@check("figure_print_font")
def figure_print_font(ctx: Ctx) -> Result:
    from .. import presentparams as pp
    floor = float(pp.params(ctx.project)["font_min_pt"])
    problems, n = [], 0
    try:
        plan = ctx.read_json("01_protocol/artifact_plan.json")
    except (OSError, ValueError):
        return Result(False, "figure_print_font", "artifact_plan.json missing")
    for e in plan.get("main_figures", []) + plan.get("supp_figures", []):
        side = ctx.p(f"05_figures/qc/{Path(str(e.get('file', ''))).stem}.artist.json")
        try:
            art = json.loads(side.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            problems.append(f"{e.get('id')}: no render sidecar")
            continue
        n += 1
        mf = art.get("min_font_pt")
        if isinstance(mf, (int, float)) and mf + 1e-6 < floor:
            problems.append(f"{e.get('id')}: smallest text {mf:g} pt < {floor:g} pt at final size")
    if problems:
        return Result(False, "figure_print_font", "; ".join(problems[:8]),
                      ["Re-render: theme_medpaper()/apply_style() now default to the journal "
                       "minimum (journal_profile.json font_min_pt, default 8 pt); remove smaller "
                       "explicit sizes (geom_text size, annotations)."])
    return Result(True, "figure_print_font", f"{n} figure(s): all text >= {floor:g} pt at print size")


# --------------------------------------------- 2c result presentation standard
_NUM_BIG = re.compile(r"(?<![\w.,\u2009])(\d{1,3}(?:[,\u2009]\d{3})+|\d{5,})(?![\w.,]\d)")
_MISSING = {"-", "\u2013", "\u2014", "NR", "n/a", "NE", "ND", "."}


@check("display_values_presented")
def display_values_presented(ctx: Ctx) -> Result:
    from ..numfmt import style
    disp = ctx.spec.get("displays", True)
    problems = []
    th = style(ctx.project).get("thousands")
    for d in clinical.display_items(ctx.project):
        if disp == "tables" and d["kind"] != "table" or disp == "figures" and d["kind"] != "figure":
            continue
        texts = d["cells"] + d["figure_text"]
        raw = clinical.raw_status_hits(texts)
        if raw:
            problems.append(f"{d['id']}: raw status text {raw[:4]}")
        symbols = {t.strip() for t in d["cells"] if t.strip() in _MISSING}
        if len(symbols) > 1:
            problems.append(f"{d['id']}: {len(symbols)} different missing/not-applicable symbols "
                            f"{sorted(symbols)} (use one, defined in the footnote)")
        big = [m.group(1) for t in texts for m in _NUM_BIG.finditer(str(t))
               if not re.fullmatch(r"(?:19|20)\d\d", m.group(1))]
        grouped = [b for b in big if re.search(r"[,\u2009]", b)]
        if grouped and len(grouped) != len(big):
            problems.append(f"{d['id']}: thousands separators used inconsistently")
        elif th and big and not grouped:
            problems.append(f"{d['id']}: the journal style groups thousands ('{th}') but "
                            f"{big[0]} is ungrouped (rebuild through threeline/numfmt)")
    if problems:
        return Result(False, "display_values_presented", "; ".join(problems[:8]),
                      ["Build cells with tools/tables/threeline.py: not_estimable(lower) for "
                       "zero-cell estimates ('Not estimable (lower 95% CI bound 19.6)'), MISSING "
                       "for absent values, fmt()/ci() for digits; numfmt applies separators.",
                       "Never print Undefined, Not fitted, NA, NaN or Inf."])
    return Result(True, "display_values_presented",
                  "display values follow the presentation standard (no raw statuses)")


# --------------------------------------------------- 2d concise table footnotes
_METHOD_WORDS = re.compile(r"\b(?:regression|model(?:l?ed|s)?|estimated|calculated|penali[sz]ed|"
                           r"bootstrap|algorithm|iteration|converge\w*|adjusted for|method)\b", re.I)
_DIAG_HEAD = re.compile(r"\b(?:collapse|merg(?:e|ed|ing)|convergence|iterations?|step|diagnostics?|"
                        r"separation|fitted|algorithm)\b", re.I)


@check("table_footnotes_concise")
def table_footnotes_concise(ctx: Ctx) -> Result:
    cap = int(ctx.target("table_footnote_words_max", 120))
    problems = []
    plan = {}
    try:
        plan = ctx.read_json("01_protocol/artifact_plan.json")
    except (OSError, ValueError):
        pass
    for d in clinical.display_items(ctx.project):
        if d["kind"] != "table":
            continue
        notes = [n.strip() for n in d["footnotes"] if n.strip()]
        words = sum(len(n.split()) for n in notes)
        if words > cap:
            problems.append(f"{d['id']}: footnotes {words} words (limit {cap}, "
                            "table_footnote_words_max)")
        for a, b in zip(notes, notes[1:]):
            if not re.search(r"[.:;)]$", a) and re.match(r"[a-z(]", b):
                problems.append(f"{d['id']}: one sentence split over footnote rows ('{a[-25:]}')")
                break
        method = [s for n in notes for s in re.split(r"(?<=[.;])\s+", n) if _METHOD_WORDS.search(s)]
        if len(method) > 2:
            problems.append(f"{d['id']}: {len(method)} method-explanation sentences in the "
                            "footnote (keep one; the rest belongs in Methods)")
        if d["main"]:
            heads = [c for c in d["cells"][1:12] if _DIAG_HEAD.search(c) and len(c) < 40]
            if heads:
                problems.append(f"{d['id']}: model-diagnostic column(s) {heads[:2]} in a main table "
                                "(move to a supplementary table)")
    if problems:
        return Result(False, "table_footnotes_concise", "; ".join(problems[:8]),
                      ["A footnote carries what the reader needs to read the table: units, "
                       "abbreviations, the estimation method in one sentence. Model diagnostics, "
                       "merge steps and convergence go to a supplementary table; long method "
                       "explanations to Methods. Write each footnote as whole sentences."])
    return Result(True, "table_footnotes_concise", f"table footnotes within {cap} words and concise")


# ------------------------------------------------ 3c proportion denominators
_PCT = re.compile(r"(?:(\d[\d,]*)\s*/\s*(\d[\d,]*)\s*\(\s*)?(?<![\d.])(\d+(?:\.\d+)?)\s?%"
                  r"(?!\s*(?:CI|CrI|PI|UI|confidence|credible|prediction|uncertainty)\b)")
_COMPARE = re.compile(r"\b(?:vs\.?|versus|compared|than|whereas|while|higher|lower|more|fewer|"
                      r"respectively)\b", re.I)


def _proportions(ctx: Ctx) -> list[dict]:
    out = []

    def walk(obj, depth=0):
        if depth > 8:
            return
        if isinstance(obj, dict):
            if {"numerator", "denominator", "population"} <= set(obj):
                out.append(obj)
            for k, v in obj.items():
                if k != "environment":
                    walk(v, depth + 1)
        elif isinstance(obj, list):
            for v in obj[:5000]:
                walk(v, depth + 1)
    for p in ctx.glob("03_analysis/results/*.json"):
        try:
            walk(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return out


@check("proportion_denominators")
def proportion_denominators(ctx: Ctx) -> Result:
    rel = ctx.src(ctx.spec["path"])
    if not ctx.p(rel).is_file():
        return Result(False, "proportion_denominators", f"{rel} missing")
    text = re.sub(r"```.*?```", " ", ctx.read(rel), flags=re.S)
    secs = clinical.sections(text)
    if len(secs) >= 2:
        text = "\n".join(b for h, b in secs if clinical.role_of(h, _target(ctx))
                         in ("abstract", "results", "discussion", "conclusions"))
    records = _proportions(ctx)
    problems, unregistered, n = [], [], 0
    for sent in re.split(r"(?<=[.;])\s+", text):
        found = []
        for m in _PCT.finditer(sent):
            n += 1
            pct = float(m.group(3))
            dec = len(m.group(3).split(".")[1]) if "." in m.group(3) else 0
            tol = 0.5 * 10 ** -dec + 1e-9
            num = int(m.group(1).replace(",", "")) if m.group(1) else None
            den = int(m.group(2).replace(",", "")) if m.group(2) else None
            if num is not None and den and abs(100.0 * num / den - pct) > tol:
                problems.append(f"'{m.group(0)}': {num}/{den} is {100.0 * num / den:.1f}%")
            hits = [r for r in records
                    if (num is None or r["numerator"] == num) and (den is None or r["denominator"] == den)
                    and int(r.get("denominator", 0) or 0) > 0
                    and abs(100.0 * int(r["numerator"]) / int(r["denominator"]) - pct) <= tol]
            if not hits:
                unregistered.append(m.group(0))
                continue
            found.append((m.group(0), {str(h["population"]) for h in hits}))
        if len(found) >= 2 and _COMPARE.search(sent):
            pops = [p for _, p in found]
            if not set.intersection(*pops):
                problems.append("compared proportions with different denominators: "
                                + " vs ".join(f"{t} [{'/'.join(sorted(p))}]" for t, p in found[:3]))
    if problems:
        return Result(False, "proportion_denominators", "; ".join(problems[:6]),
                      ["Compare proportions only over the same denominator definition, or state "
                       "both denominators in the sentence. Record each percentage with "
                       "analysis.results.proportion(numerator, denominator, population)."])
    if unregistered:
        return Result(False, "proportion_denominators",
                      f"{len(unregistered)} of {n} percentage(s) have no numerator/denominator "
                      "record: " + ", ".join(unregistered[:6]),
                      ["Store proportions with analysis.results.proportion(...) so their "
                       "denominators can be compared."], severity="warn")
    return Result(True, "proportion_denominators",
                  f"{n} percentage(s) traced to numerator/denominator records")
