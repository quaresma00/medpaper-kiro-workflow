"""1.11.0 clinical presentation layer: display dictionary, engineering-language lint,
self-contained display abbreviations, raw statistical statuses and flow-diagram units.

The analysis code names things for the programmer (comp_a, strict_contrast, "lines read");
the paper names them for a clinician. This module holds the generic rules (term lists live in
reference/clinical_language.toml) and the text sources the gates read:

    01_protocol/display_dictionary.json   S07, next to artifact_plan.json:
        {"terms": [{"internal": "comp_a", "aliases": ["Composite A"],
                    "label": "Portal vascular disease composite", "abbreviation": "PVD",
                    "definition": "one line a clinician understands"}],
         "no_internal_names_reason": "only when the analysis has no coded groups"}
    .wf/language_allowlist.json           paper-local, with reasons (never an engine edit)
"""
from __future__ import annotations

import json
import re
import tomllib
from functools import lru_cache
from pathlib import Path

DICT_REL = "01_protocol/display_dictionary.json"
ALLOW_REL = ".wf/language_allowlist.json"
LEGENDS = "05_figures/legends.md"
CAPTIONS = "04_tables/table_captions.md"
PLAN = "01_protocol/artifact_plan.json"
BLOCK_SECTIONS = ("abstract", "introduction", "results", "discussion", "conclusion", "conclusions")
WARN_SECTIONS = ("methods",)
_CODE_ID = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$|^[a-z]+[A-Z]\w*$")


@lru_cache(maxsize=1)
def rules() -> dict:
    from . import paths
    return tomllib.loads((paths.reference_dir() / "clinical_language.toml").read_text(encoding="utf-8"))


def _json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------- display dictionary (#1a)
def dictionary(project: Path) -> dict | None:
    data = _json(Path(project) / DICT_REL)
    return data if isinstance(data, dict) else None


def dictionary_problems(data: dict | None) -> list[str]:
    if data is None:
        return [f"{DICT_REL} missing or invalid JSON"]
    terms = data.get("terms")
    if not isinstance(terms, list):
        return ["'terms' must be a list"]
    if not terms and len(str(data.get("no_internal_names_reason", "")).strip()) < 20:
        return ["no terms: list every internal group/outcome/contrast name, or give "
                "'no_internal_names_reason' (>= 20 chars)"]
    problems, abbrs = [], {}
    letter = re.compile(rules()["letter_codes"]["pattern"])
    for i, t in enumerate(terms, 1):
        if not isinstance(t, dict):
            problems.append(f"term {i}: not an object")
            continue
        internal, label = str(t.get("internal", "")).strip(), str(t.get("label", "")).strip()
        tag = internal or f"term {i}"
        if not internal:
            problems.append(f"term {i}: empty 'internal'")
        if len(label) < 3:
            problems.append(f"{tag}: 'label' (the clinical name) missing")
        elif _CODE_ID.match(label) or "_" in label:
            problems.append(f"{tag}: label '{label}' looks like a code identifier")
        elif letter.search(label) and not t.get("letter_code_reason"):
            problems.append(f"{tag}: label '{label}' is a letter code; use the clinical name "
                            "(or give 'letter_code_reason' when the field itself uses it)")
        if len(str(t.get("definition", "")).strip()) < 10:
            problems.append(f"{tag}: one-line 'definition' missing")
        ab = str(t.get("abbreviation", "") or "").strip()
        if ab:
            if ab in abbrs and abbrs[ab] != label:
                problems.append(f"abbreviation {ab} used for two labels")
            abbrs[ab] = label
    return problems


def internal_names(data: dict | None) -> dict[str, str]:
    """internal name or alias -> clinical label (only names that differ from their label)."""
    out = {}
    for t in (data or {}).get("terms", []) or []:
        if not isinstance(t, dict):
            continue
        label = str(t.get("label", "")).strip()
        for name in [t.get("internal")] + list(t.get("aliases") or []):
            name = str(name or "").strip()
            if name and label and name.casefold() != label.casefold():
                out[name] = label
    return out


def labels(data: dict | None) -> list[str]:
    return [str(t.get("label", "")).strip() for t in (data or {}).get("terms", []) or []
            if isinstance(t, dict) and str(t.get("label", "")).strip()]


def label_problems(text: str, data: dict | None) -> list[str]:
    """Internal names and letter-code labels in reader-facing text."""
    known = sorted(labels(data), key=len, reverse=True)
    scrub = text
    for lab in known:  # a clinical label may contain an internal word ("reference group")
        scrub = re.sub(re.escape(lab), " ", scrub, flags=re.I)
    hits, named = [], set()
    for name, label in internal_names(data).items():
        flags = re.I if (_CODE_ID.match(name) or "_" in name) else 0
        if re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", scrub, flags):
            hits.append(f"'{name}' (use '{label}')")
            named.add(name.casefold())
    lc = rules()["letter_codes"]
    for m in re.finditer(lc["pattern"], scrub):
        tail = scrub[m.start(): m.end() + 14]
        if any(tail.startswith(x) for x in lc.get("clinical_exceptions", [])) \
                or m.group(0).casefold() in named:
            continue
        hits.append(f"'{m.group(0)}' (letter-code label; define its clinical label in {DICT_REL})")
    return sorted(set(hits))


# ---------------------------------------------------------- engineering language (#1b)
def allowlist(project: Path) -> dict[str, str]:
    """term -> scope ('methods' | 'all') for paper-local exceptions with a reason."""
    data = _json(Path(project) / ALLOW_REL) or {}
    out = {}
    for t in data.get("terms", []) if isinstance(data, dict) else []:
        if isinstance(t, dict) and len(str(t.get("reason", "")).strip()) >= 15:
            out[str(t.get("term", "")).strip().casefold()] = str(t.get("scope", "all")).strip()
    return out


def engineering_hits(text: str, allowed: dict[str, str] | None = None,
                     where: str = "all") -> list[tuple[str, str, str]]:
    """(term, matched text, suggestion) for every engineering-language hit."""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"\[[^\]\n]*@[^\]\n]*\]", " ", text)
    out = []
    for entry in rules().get("engineering", []):
        scope = (allowed or {}).get(entry["term"].casefold())
        if scope == "all" or (scope == "methods" and where == "methods"):
            continue
        for m in re.finditer(entry["pattern"], text, re.I):
            out.append((entry["term"], m.group(0), entry["suggest"]))
    return out


_QUOTED_LABEL = re.compile(r"[\"\u201c]([A-Za-z][A-Za-z\-/ ]{1,48}[A-Za-z])[\"\u201d]")


def coined_labels(text: str, data: dict | None, allowed: dict[str, str] | None = None) -> list[str]:
    """1.13.0 (G5): short quoted labels ("original rule", "record review") that are not in the
    display dictionary - names coined during the analysis that the word list cannot know."""
    known = {x.casefold() for x in labels(data)} | {x.casefold() for x in internal_names(data)}
    for t in (data or {}).get("terms", []) or []:
        if isinstance(t, dict):
            known |= {str(a).strip().casefold() for a in t.get("aliases") or []}
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    out = set()
    for m in _QUOTED_LABEL.finditer(text):
        label = " ".join(m.group(1).split())
        if 1 <= len(label.split()) <= 4 and label.casefold() not in known \
                and label.casefold() not in (allowed or {}):
            out.add(label)
    return sorted(out)


def sections(text: str) -> list[tuple[str, str]]:
    """(casefolded level-1 heading, body) of a full manuscript."""
    heads = list(re.finditer(r"(?m)^#\s+([^#\n].*)$", text))
    return [(m.group(1).strip().casefold(),
             text[m.end(): heads[i + 1].start() if i + 1 < len(heads) else len(text)])
            for i, m in enumerate(heads)]


def role_of(heading: str, target: dict | None = None) -> str:
    """Semantic role of a body heading, honouring the journal's names (1.11.0 #3d)."""
    from . import journalspec
    key = journalspec.section_role(heading, target)
    if key.startswith("abstract"):
        return "abstract"
    if key.startswith("conclusion"):
        return "conclusions"
    return key


# --------------------------------------------------------------- display text sources
def sidecar_text(project: Path, png_rel: str) -> list[str]:
    side = Path(project) / "05_figures" / "qc" / f"{Path(str(png_rel)).stem}.artist.json"
    data = _json(side) or {}
    return [str(t) for t in data.get("figure_text", []) if str(t).strip()] if isinstance(data, dict) else []


def _blocks(text: str) -> dict[str, str]:
    heads = list(re.finditer(r"(?mi)^#{2,6}\s+((?:Figure|Fig\.?|Table)\s+S?\d+)\.?(.*)$", text))
    out = {}
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        key = re.sub(r"\s+", " ", m.group(1)).replace("Fig.", "Figure").replace("Fig ", "Figure ")
        out[key.casefold()] = m.group(2) + "\n" + text[m.end():end]
    return out


def display_items(project: Path, include_supp: bool = True) -> list[dict]:
    """One record per planned display: id, kind, main?, caption/legend, table cells,
    in-figure text, footnotes."""
    project = Path(project)
    plan = _json(project / PLAN) or {}
    legends = _blocks((project / LEGENDS).read_text(encoding="utf-8", errors="replace")) \
        if (project / LEGENDS).is_file() else {}
    captions = _blocks((project / CAPTIONS).read_text(encoding="utf-8", errors="replace")) \
        if (project / CAPTIONS).is_file() else {}
    groups = ("main_figures", "main_tables") + (("supp_figures", "supp_tables") if include_supp else ())
    out = []
    for g in groups:
        for e in plan.get(g, []) if isinstance(plan, dict) else []:
            eid = str(e.get("id", "")).strip()
            key = re.sub(r"\s+", " ", eid).casefold()
            rec = {"id": eid, "kind": "figure" if g.endswith("figures") else "table",
                   "main": g.startswith("main"), "archetype": e.get("archetype"),
                   "caption": "", "cells": [], "footnotes": [], "figure_text": []}
            if rec["kind"] == "figure":
                rec["caption"] = legends.get(key, "")
                rec["figure_text"] = sidecar_text(project, e.get("file", ""))
            else:
                rec["caption"] = captions.get(key, "")
                rec["cells"], rec["footnotes"] = table_text(project, e)
            out.append(rec)
    return out


def table_text(project: Path, entry: dict) -> tuple[list[str], list[str]]:
    """(title/header/body cell texts, footnote rows) of one planned table workbook."""
    from . import xlsxlite
    path = Path(project) / str(entry.get("file", ""))
    if not path.is_file():
        return [], []
    try:
        wb = xlsxlite.Workbook(path)
    except Exception:  # noqa: BLE001 - malformed workbooks are reported by tables_threeline
        return [], []
    sheets = [wb.sheet(entry["sheet"])] if entry.get("sheet") else wb.sheets
    cells, notes = [], []
    for sh in [s for s in sheets if s is not None]:
        ruled = []
        for r in range(1, sh.max_row + 1):
            specs = [wb.border_of(c) for c in sh.row_cells(r)]
            if any(s.top or s.bottom for s in specs):
                ruled.append(r)
        last = max(ruled) if ruled else sh.max_row
        for r in range(1, sh.max_row + 1):
            texts = [c.value for c in sh.row_cells(r) if c.value]
            (notes if r > last else cells).extend(str(t) for t in texts)
    return cells, notes


# ------------------------------------------------------------- abbreviations (#1c)
_ABBR = re.compile(r"(?<![\w])([A-Z][A-Za-z0-9]*[A-Z][A-Za-z0-9]*|[a-z]{1,2}[A-Z]{2,}[a-z0-9]*)(?![\w])")


def used_abbreviations(text: str) -> set[str]:
    exempt = set(rules().get("display_abbreviations", {}).get("exempt", []))
    text = re.sub(r"\b(?:Figure|Table|Fig)\s+S?\d+[A-Za-z]?\b", " ", text)
    out = set()
    for m in _ABBR.finditer(text):
        tok = m.group(1)
        if tok in exempt or re.fullmatch(r"[A-Z]\d+|\d+[A-Z]+|Q[1-4]", tok):
            continue
        if sum(ch.isupper() for ch in tok) < 2:
            continue
        if tok.isupper() and len(tok) > 7:  # an all-capitals word, not an abbreviation
            continue
        out.add(tok)
    return out


def defined_abbreviations(text: str) -> set[str]:
    from .checks.artifacts import ABBREVIATION_LABEL_RE, abbreviation_definitions
    out = set()
    for m in ABBREVIATION_LABEL_RE.finditer(text):
        out |= set(abbreviation_definitions(m.group(1)))
    out |= set(re.findall(r"\(\s*([A-Za-z][A-Za-z0-9-]{1,14})s?\s*\)", text))
    out |= set(re.findall(r"(?:^|[;:]\s*)([A-Z][A-Za-z0-9-]{1,14})\s*(?:,|=)\s+[a-z]", text, re.M))
    return out


def central_list(text: str) -> set[str] | None:
    """Terms of the manuscript's central '## Abbreviations' (or '# Abbreviations') list."""
    from .checks.artifacts import abbreviation_definitions
    m = re.search(r"(?ms)^#{1,3}\s+(?:List of\s+)?Abbreviations\s*$\n(.*?)(?=^#{1,3}\s+|\Z)", text)
    return set(abbreviation_definitions(m.group(1))) if m else None


# --------------------------------------------------------- raw statuses (#2c)
def raw_status_hits(texts: list[str]) -> list[str]:
    pat = re.compile(rules()["raw_status"]["pattern"])
    return sorted({m.group(0) for t in texts for m in pat.finditer(str(t))})


# --------------------------------------------------------- flow diagram units (#1d)
_COUNT = re.compile(r"(?<![\w.])(?:n\s*=\s*)?\d{1,3}(?:[,\u2009 ]\d{3})+(?![\w.])|(?<![\w.])(?:n\s*=\s*)?\d+(?![\w.%])")


def flow_unit_problems(texts: list[str]) -> list[str]:
    flow = rules()["flow"]
    units = {u.casefold() for u in flow["analysis_units"]}
    proc = {u.casefold() for u in flow["processing_units"]}
    out = []
    for t in texts:
        line = " ".join(str(t).split())
        if not _COUNT.search(line) or re.fullmatch(r"[\d\s.,()-]+", line):
            continue
        words = {w.casefold() for w in re.findall(r"[A-Za-z]+", line)}
        bad = sorted(words & proc)
        if bad:
            out.append(f"'{line[:70]}': processing-log unit ({', '.join(bad)}) - count analysis "
                       "units; data volume goes to a supplementary data-scale table")
        elif not words & units:
            out.append(f"'{line[:70]}': count without its analysis unit (reports, cases, "
                       "patients, participants ...)")
    return out
