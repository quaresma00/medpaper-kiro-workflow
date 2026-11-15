"""1.27.0: figures carry little text, and every table/figure string reads like the prose.

The user's rules: no subtitle in a figure, no explanatory text inside a figure, not much text
in a figure at all; and the de-AI, de-engineering and medical-register rules of the prose also
apply to the words inside tables and figures. Rule letters continue displaytext's a-h:

  i  titles inside the image - a whole-figure title (the legend carries the title; allowed only
     when the journal requires in-figure titles, presentation in_figure_title = true), every
     subtitle, every caption/note line under a plot, and a panel heading of a multi-panel
     figure that is longer than 6 words or reads as a sentence.
  j  explanatory or excessive text - a sentence inside the figure (annotation, legend key,
     strip, legend or axis title: 'Dashed line indicates ...', 'Adjusted for age and sex',
     'Patients who were treated with ...'), free annotation text beyond 4 words (8 for the
     table text of a forest plot); advisory: long labels (axis title > 10 words, legend key > 8,
     strip or legend title > 6, flow box > 20) and more than 30 words of free text in one
     figure. Data labels ('HR 0.82 (95% CI 0.70-0.96)', 'n = 120', 'P < 0.001', '*') are fine.
  k  phrasing in any table or figure string (titles, headers, row labels, cells, footnotes,
     captions, legends, in-figure text): tier-A AI phrasing and spin block; tier-B AI phrasing
     and the data-processing narration list of the medical editor are advisory. Engineering
     terms of the 1.11 list are already blocked by engineering_language_clean.

Severity: 'fail' for a paper on 1.27.0+ (new, migrated with `wf migrate --yes`, or after a
journal switch), 'warn' for a paper pinned earlier. Sidecars rendered before 1.27.0 (no
text_roles_version 2) cannot tell a figure title from a panel heading: a title in a
single-panel figure counts as a figure title, in a multi-panel figure as a panel heading; re-
rendering gives exact roles. Exceptions: the paper's .wf/language_allowlist.json (term = the
exact string or the matched phrase, reason >= 15 characters).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

V = (1, 27, 0)
SINCE = "1.27.0"
ROLES_VERSION = 2  # sidecars from 1.27.0 tell title, panel title, subtitle and caption apart
PANEL_TITLE_WORDS = 6
FIGURE_TITLE_WORDS = 12  # only when the journal requires in-figure titles
ANNOTATION_WORDS = 4
FOREST_TEXT_WORDS = 8
AXIS_TITLE_WORDS = 10
LEGEND_KEY_WORDS = 8
SHORT_LABEL_WORDS = 6  # strip, legend title
FLOW_BOX_WORDS = 20
FREE_TEXT_WORDS = 30
FREE_ROLES = ("title", "subtitle", "caption", "panel title", "annotation", "figure text")
SKIP_ROLES = ("tick label", "panel label", "legend")  # legend = the legends.md text

_WORD = re.compile(r"[A-Za-z\u00c0-\u024f\u0370-\u03ff\u00b5][A-Za-z\u00c0-\u024f\u0370-\u03ff\u00b5'\u2019-]*")
_STAT = frozenset({"hr", "ahr", "shr", "or", "aor", "rr", "irr", "ror", "prr", "ic", "ic025", "ci",
                   "cri", "p", "n", "auc", "smd", "md", "se", "sd", "iqr", "vs", "to", "no", "ns",
                   "nnt", "nnh", "ebgm", "eb05", "events", "reference", "ref"})
_EXPLAIN = re.compile(
    r"(?i)\b(?:indicat(?:e|es|ed|ing)|represent(?:s|ed|ing)?|denot(?:e|es|ed|ing)|show(?:s|n|ing)?|"
    r"depict(?:s|ed)?|illustrat(?:e|es|ed)|refers?\s+to|correspond(?:s|ing)?\s+to|"
    r"adjusted\s+for|stratified\s+by|weighted\s+by|matched\s+(?:on|for)|"
    r"calculated\s+(?:from|by|with|using|as)|estimated\s+(?:by|with|using|from)|derived\s+from|"
    r"error\s+bars?|(?:dashed|dotted|solid)\s+lines?|shaded\s+(?:areas?|regions?|bands?)|"
    r"(?:vertical|horizontal|reference)\s+(?:dashed\s+|dotted\s+)?lines?|"
    r"each\s+(?:dot|point|circle|square|bar|line|box|marker|symbol)|"
    r"size\s+of\s+(?:the\s+)?(?:dots?|points?|circles?|squares?|boxes|markers?))\b")
_BE = re.compile(r"(?i)\b(?:is|are|was|were|has|have|had|will|would|can|could)\b")
_ABBR_END = re.compile(r"(?i)(?:\bvs|\bno|\bet al|\be\.g|\bi\.e|\bapprox|\bfig|\bref|\bincl)\.$")
_SYMBOLS = re.compile(r"^[\s*\u2020\u2021\u00a7\u00b6#\u2016|]+$")

SUGGEST = {
    "title": "delete the title from the image - the legend carries it ('Figure 1. ...')",
    "title_allowed": f"keep an in-figure title to {FIGURE_TITLE_WORDS} words, not a sentence "
                     "(the journal asks for titles in the image)",
    "subtitle": "delete the subtitle; what it explains goes into one legend sentence",
    "caption": "delete the note under the plot; it goes into the legend",
    "panel title": f"shorten the panel heading to {PANEL_TITLE_WORDS} words or fewer, a label, not a "
                   "sentence; the explanation goes into the legend",
    "sentence": "no sentences inside a figure: keep a short label and move the explanation "
                "into the legend",
    "annotation": f"free text inside a panel: a data label or a label of at most {ANNOTATION_WORDS} "
                  "words; the explanation goes into the legend",
    "forest": f"forest-plot table text of at most {FOREST_TEXT_WORDS} words per cell; the "
              "explanation goes into the legend",
    "axis title": f"an axis title names the measure and unit in at most {AXIS_TITLE_WORDS} words "
                  "('Hazard ratio (95% CI), log scale')",
    "legend key": f"a group name of at most {LEGEND_KEY_WORDS} words (clinical label)",
    "short label": f"at most {SHORT_LABEL_WORDS} words",
    "flow box": f"a flow box gives the step, the unit and the count in at most {FLOW_BOX_WORDS} "
                "words ('Duplicate reports removed (n = 1234)')",
    "total": f"more than {FREE_TEXT_WORDS} words of free text inside the figure (titles, "
             "annotations): keep what is needed to read the plot, the rest goes into the legend",
}


# ------------------------------------------------------------------ release policy
def _pin(project: Path) -> tuple[int, ...]:
    from .state import version_tuple
    try:
        st = json.loads((Path(project) / ".wf/state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return V
    if not isinstance(st, dict):
        return V
    pin = version_tuple(str(st.get("engine_pin") or st.get("pipeline_version") or "0"))
    jp = st.get("journal_gate_pin") or {}
    if jp.get("stages"):
        pin = max(pin, version_tuple(str(jp.get("version", "0"))))
    return pin


def since_1270_project(project: Path | None) -> bool:
    """A paper created on 1.27.0+, migrated, or after a journal switch."""
    return True if project is None else _pin(project) >= V


def since_1270(ctx) -> bool:
    from .state import pin_for, version_tuple
    try:
        return version_tuple(pin_for(ctx.state, getattr(ctx.stage, "id", None))) >= V
    except Exception:  # noqa: BLE001
        return True


# ------------------------------------------------------------------ text measures
def words(text: str) -> list[str]:
    """Alphabetic words, statistical tokens (HR, CI, P, n, vs ...) not counted."""
    return [w for w in _WORD.findall(str(text or "")) if w.casefold().strip("'-") not in _STAT]


def is_data_label(text: str) -> bool:
    """A number, a statistic or a symbol: 'HR 0.82 (0.70-0.96)', 'n = 120', 'P < 0.001', '*'."""
    s = str(text or "").strip()
    if not s or _SYMBOLS.match(s):
        return True
    w = words(s)
    return len(w) <= 1 and (bool(re.search(r"\d", s)) or len(s) <= 4)


def sentence_like(text: str) -> bool:
    """An explanation rather than a label."""
    s = str(text or "").strip()
    w = words(s)
    if len(w) >= 3 and s.endswith(".") and not _ABBR_END.search(s):
        return True
    if len(w) >= 3 and _EXPLAIN.search(s):
        return True
    if len(w) >= 5 and _BE.search(s):
        return True
    return len(w) >= 6 and ";" in s


def _sidecar(project: Path, d: dict) -> dict:
    side = Path(project) / "05_figures" / "qc" / f"{Path(str(d.get('file', ''))).stem}.artist.json"
    try:
        data = json.loads(side.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def in_figure_title_allowed(project: Path) -> bool:
    try:
        from . import presentparams
        return presentparams.params(Path(project)).get("in_figure_title") is True
    except Exception:  # noqa: BLE001
        return False


# ------------------------------------------------------------------ rules i and j
def figure_findings(project: Path, d: dict, strict: bool) -> list[dict]:
    """Rules i and j for one figure record of the display-text inventory."""
    if d.get("kind") != "figure":
        return []
    side = _sidecar(project, d)
    exact = int(side.get("text_roles_version") or 1) >= ROLES_VERSION
    n_axes = side.get("n_axes") if isinstance(side.get("n_axes"), int) else 1
    arche = str(d.get("archetype") or side.get("archetype") or "")
    titles_ok = in_figure_title_allowed(project)
    out: list[dict] = []

    def add(role, text, rule, key, level="fail", why=""):
        out.append({"display": d["id"], "kind": "figure", "main": d.get("main", True),
                    "role": role, "text": str(text), "rule": rule,
                    "suggest": SUGGEST[key] + (f" ({why})" if why else ""),
                    "severity": "fail" if (strict and level == "fail") else "warn"})

    free = 0
    for s in d.get("strings", []):
        role, text = s.get("role", ""), str(s.get("text", "")).strip()
        if not text or role in SKIP_ROLES:
            continue
        n = len(words(text))
        data = is_data_label(text)
        if role in FREE_ROLES and not data and not (arche == "forest_plot" and role in
                                                    ("annotation", "figure text")):
            free += n
        if role == "title" and not exact:
            # pre-1.27.0 sidecar: one panel -> the figure's title; several -> a panel heading
            role = "title" if n_axes <= 1 else "panel title"
            why = "re-render to classify it exactly" if role == "panel title" else ""
        else:
            why = ""
        if role == "subtitle":
            add(role, text, "i", "subtitle")
        elif role == "caption":
            add(role, text, "i", "caption")
        elif role == "title":
            if not titles_ok:
                add(role, text, "i", "title")
            elif n > FIGURE_TITLE_WORDS or sentence_like(text):
                add(role, text, "i", "title_allowed")
        elif role == "panel title":
            if n > PANEL_TITLE_WORDS or sentence_like(text):
                add(role, text, "i", "panel title", "fail" if exact or n_axes > 1 else "warn", why)
        elif role in ("annotation", "figure text"):
            if data:
                continue
            limit = FOREST_TEXT_WORDS if arche == "forest_plot" else ANNOTATION_WORDS
            if sentence_like(text):
                add(role, text, "j", "sentence")
            elif n > limit:
                add(role, text, "j", "forest" if arche == "forest_plot" else "annotation")
        elif role == "flow box":
            if n > FLOW_BOX_WORDS or (_EXPLAIN.search(text) and n >= 3):
                add(role, text, "j", "flow box", "warn")
        elif role in ("axis title", "legend title", "legend key", "strip"):
            if sentence_like(text):
                add(role, text, "j", "sentence")
            else:
                cap, key = {"axis title": (AXIS_TITLE_WORDS, "axis title"),
                            "legend key": (LEGEND_KEY_WORDS, "legend key")}.get(
                                role, (SHORT_LABEL_WORDS, "short label"))
                if n > cap:
                    add(role, text, "j", key, "warn")
    if free > FREE_TEXT_WORDS:
        add("figure text", f"{free} words of free text", "j", "total", "warn")
    return out


# ------------------------------------------------------------------ rule k
_POL = []


def _polish():
    if not _POL:
        from . import sectionpolish
        _POL.append(sectionpolish._polish_module())
    return _POL[0]


def phrasing_findings(project: Path, d: dict, strict: bool) -> list[dict]:
    """Rule k: AI phrasing, spin and data-processing narration in any visible string."""
    from . import clinical
    try:
        pol = _polish()
    except Exception:  # noqa: BLE001 - without the linter module there is nothing to judge
        return []
    allowed = clinical.allowlist(Path(project))
    base = {e["term"].casefold() for e in clinical.rules().get("engineering", [])}
    tables = [(pol.AI_TIER_A, "fail", "AI phrasing"), (pol.SPIN_TIER_A, "fail", "spin"),
              (pol.AI_TIER_B, "warn", "AI phrasing")]
    out, seen = [], set()
    for s in d.get("strings", []):
        role, text = s.get("role", ""), str(s.get("text", ""))
        if role == "cell" or not re.search(r"[A-Za-z]{3}", text):
            continue
        hits = []
        for table, level, kind in tables:
            for pat, label in table:
                if re.search(pat, text, re.I) and label.casefold() not in allowed:
                    hits.append((level, f"{kind} '{label}'", label))
        for term, hit, sug in clinical.engineering_hits(text, allowed, "display", extended=True):
            if term.casefold() not in base:
                hits.append(("warn", f"data-processing wording '{hit}' -> {sug}", hit))
        for level, what, label in hits:
            key = (d["id"], role, text, what)
            if key in seen:
                continue
            seen.add(key)
            out.append({"display": d["id"], "kind": d.get("kind"), "main": d.get("main", True),
                        "role": role, "text": text, "rule": "k", "hit": label,
                        "suggest": f"{what}: write it as the prose would say it (plain clinical "
                                   "words, no stock phrase, no description of data handling)",
                        "severity": "fail" if (strict and level == "fail") else "warn"})
    return out


def findings(project: Path, d: dict, strict: bool | None = None) -> list[dict]:
    """Rules i, j (figures) and k (every display) for one inventory record."""
    if strict is None:
        strict = since_1270_project(project)
    return figure_findings(project, d, strict) + phrasing_findings(project, d, strict)
