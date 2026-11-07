"""1.20.0: the visible text of every table and figure, judged for a clinical reader.

    wf displays text [--md]   inventory + checks + writer bundle (also run by `wf rebuild` and
                              by the S09-S12/S23 display gates)
    wf displays apply         merge the clinical writer's wording (.wf/writer/display_wording.md)
                              into the display dictionary; footnote/legend sentences are listed
                              for the builder scripts

Inventory (.wf/display_text/inventory.json, incremental by source hash): one record per planned
display (main and supplementary) with every visible string and its role - title, column header,
row label, level, cell, cell text, footnote, caption (tables); axis title, tick label, legend
title, legend key, strip, annotation, flow box, title, legend (figures; from the render sidecar's
text_roles, older sidecars give 'figure text').

Rules (reference/display_text.toml; letters as in the release notes): a code-like strings,
b generic placeholder labels, c software-output columns in main tables, d number display,
e units and measures, f undefined letter-code labels, g technical terms to spell out and
explain (warn), h main tables wider than 8 data columns (warn). Exceptions: the paper-local
.wf/language_allowlist.json (term = the exact string, reason >= 15 chars).

Relabelling (V4): the table builder, save_medpaper() and style.save() map internal names through
the display dictionary (label, plus unit for titles/headers/row labels). On for papers pinned to
1.20.0+, or with `wf config set display_relabel true`; off for earlier pins until `wf migrate
--yes`. Numbers are never touched.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tomllib
from functools import lru_cache
from pathlib import Path

from . import clinical

V = (1, 20, 0)
INV_REL = ".wf/display_text/inventory.json"
INV_MD = ".wf/display_text/inventory.md"
STATE_REL = ".wf/display_text/bundle_state.json"
NOTES_REL = ".wf/display_text/wording_to_apply.md"
BUNDLE_REL = ".wf/writer_bundle/displays"
REPLY_REL = ".wf/writer/display_wording.md"
SCHEMA = 2
PROSE = ("title", "caption", "legend", "footnote")
WARN_RULES = ("g", "h")


@lru_cache(maxsize=1)
def rules() -> dict:
    from . import paths
    return tomllib.loads((paths.reference_dir() / "display_text.toml").read_text(encoding="utf-8"))


def _json(path: Path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _sha(*parts) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p if isinstance(p, bytes) else str(p).encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()


# ------------------------------------------------------------------ pin and relabel switch
def since_1200_project(project: Path) -> bool:
    from .state import version_tuple
    st = _json(Path(project) / ".wf/state.json")
    if not isinstance(st, dict):
        return True
    pin = version_tuple(str(st.get("engine_pin") or st.get("pipeline_version") or "0"))
    jp = st.get("journal_gate_pin") or {}  # `wf journal switch` adopted the current set
    if jp.get("stages"):
        pin = max(pin, version_tuple(str(jp.get("version", "0"))))
    return pin >= V


def since_1200(ctx) -> bool:
    from .state import pin_for, version_tuple
    try:
        return version_tuple(pin_for(ctx.state, getattr(ctx.stage, "id", None))) >= V
    except Exception:  # noqa: BLE001
        return True


def relabel_enabled(project: Path) -> bool:
    """`display_relabel` in the paper config (true/false) wins; else on from pin 1.20.0."""
    try:
        from . import registry
        raw = registry.effective_targets(Path(project)).get("display_relabel", "")
    except Exception:  # noqa: BLE001
        raw = ""
    val = str(raw).strip().casefold()
    if val in ("true", "1", "yes", "on"):
        return True
    if val in ("false", "0", "no", "off"):
        return False
    return since_1200_project(project)


def relabel_map(project: Path) -> dict:
    """{"on", "hash", "titles": internal -> 'Label, unit', "values": internal -> 'Label'}."""
    data = clinical.dictionary(Path(project)) or {}
    titles, values = {}, {}
    for t in data.get("terms", []) or []:
        if not isinstance(t, dict):
            continue
        label = str(t.get("label", "")).strip()
        unit = str(t.get("unit", "") or "").strip()
        if not label:
            continue
        title = label if not unit or unit.casefold() in label.casefold() else f"{label}, {unit}"
        for name in [t.get("internal")] + list(t.get("aliases") or []):
            name = str(name or "").strip()
            if not name:
                continue
            if name != title:
                titles[name] = title
            if name != label:
                values[name] = label
    on = relabel_enabled(project)
    body = {"titles": dict(sorted(titles.items())), "values": dict(sorted(values.items()))}
    return {"on": on, "hash": _sha(json.dumps(body, sort_keys=True, ensure_ascii=False))[:16]
            if on else "off", **body, "keep": sorted(_clinical_exact())}


def relabel_env(project: Path) -> str:
    """MEDPAPER_DISPLAY_LABELS exported by `wf run-script` (R and Python figure scripts)."""
    return json.dumps(relabel_map(project), ensure_ascii=True)  # \u escapes: safe in any code page


def active_map(project: Path | None = None) -> dict:
    """The relabel map in force inside a build: the exported env, else computed from the paper."""
    raw = os.environ.get("MEDPAPER_DISPLAY_LABELS")
    if raw:
        try:
            got = json.loads(raw)
            if isinstance(got, dict):
                return got
        except ValueError:
            pass
    if project is None:
        env = os.environ.get("MEDPAPER_PROJECT")
        project = Path(env) if env else None
    if project is None or not (Path(project) / ".wf/state.json").is_file():
        return {"on": False, "hash": "off", "titles": {}, "values": {}}
    return relabel_map(Path(project))


def labels_state(project: Path | None = None) -> str:
    """Recorded with every render (renderparams): 'off' or the hash of the map in force."""
    try:
        if project is not None and (Path(project) / ".wf/state.json").is_file():
            return str(relabel_map(Path(project)).get("hash") or "off")
        return str(active_map(None).get("hash") or "off")
    except Exception:  # noqa: BLE001
        return "off"


def unmappable(text: str) -> bool:
    """A header/row label/axis title still code-like after relabelling (builders fail on it)."""
    s = str(text or "").strip()
    if not s or s in _clinical_exact():
        return False
    return bool(_SNAKE.search(s) or _DOTTED_name(s) or _CALL.search(s) or _FORMULA.search(s)
                or _dummy(s))


def unmapped_message(text: str) -> str:
    if re.match(rules()["software_columns"]["pattern"], str(text).strip()):
        return rules()["software_columns"]["suggest"]
    return suggestion(text)


def suggestion(text: str) -> str:
    return ('add to 01_protocol/display_dictionary.json: {"internal": "%s", "label": "<clinical '
            'name>", "unit": "<if continuous>", "definition": "<one line>"}' % str(text).replace('"', "'"))


# --------------------------------------------------------------------- extraction
def _sheets(wb, entry: dict):
    if entry.get("sheet"):
        sh = wb.sheet(entry["sheet"])
        return [sh] if sh is not None else []
    if len(wb.sheets) <= 1:
        return list(wb.sheets)
    tid = str(entry.get("id", "")).strip()
    short = re.sub(r"(?i)^(?:supplementary\s+)?table\s*", "", tid)
    for sh in wb.sheets:
        if sh.name.strip().casefold() in {tid.casefold(), short.casefold(), f"table {short}".casefold()}:
            return [sh]
    return list(wb.sheets)


_NUMERIC = re.compile(r"^[\s<>≤≥=~±%.,\-\u2212\u2013\u2014()\[\]0-9eE+/:;]*(?:to|vs)?[\s<>≤≥=~±%.,\-"
                      r"\u2212\u2013\u2014()\[\]0-9eE+/:;]*$")


def _is_number_cell(text: str) -> bool:
    s = str(text).strip()
    return bool(s) and bool(re.search(r"\d", s)) and bool(_NUMERIC.match(s.replace(" to ", " ")))


def table_record(project: Path, entry: dict) -> dict:
    from . import xlsxlite
    path = Path(project) / str(entry.get("file", ""))
    rec = {"strings": [], "header": [], "body": [], "ncols": 0}
    if not path.is_file():
        return rec
    try:
        wb = xlsxlite.Workbook(path)
    except Exception:  # noqa: BLE001 - malformed workbooks are reported by tables_threeline
        return rec
    for sh in _sheets(wb, entry):
        rows = {}
        top, bottom = [], []
        for r in range(1, sh.max_row + 1):
            cells = sh.row_cells(r)
            rows[r] = {c.col: (c.value or "") for c in cells}
            specs = [wb.border_of(c) for c in cells]
            if any(s.top for s in specs):
                top.append(r)
            if any(s.bottom for s in specs):
                bottom.append(r)
        ruled = sorted(set(top) | set(bottom))
        if ruled:
            h0 = min(top) if top else ruled[0]
            h1 = min([b for b in bottom if b >= h0] or [h0])
            last = max(bottom) if bottom else sh.max_row
        else:
            h0, h1, last = 2, 2, sh.max_row
        ncols = max([max(v) for v in rows.values() if v] or [0])
        rec["ncols"] = max(rec["ncols"], ncols)
        for r in range(1, sh.max_row + 1):
            vals = rows.get(r, {})
            for c, v in sorted(vals.items()):
                text = str(v)
                if not text.strip():
                    continue
                if r < h0:
                    role = "title"
                elif r <= h1:
                    role = "column header"
                elif r <= last:
                    if c == 1:
                        role = "level" if re.match(r"^(?:\s{2,}|[\u2003\u2002\u00a0]|[-\u2013\u2022]\s)", text) \
                            else "row label"
                    else:
                        role = "cell" if _is_number_cell(text) else "cell text"
                else:
                    role = "footnote"
                rec["strings"].append({"role": role, "text": text, "row": r, "col": c})
            if h0 <= r <= h1:
                rec["header"].append([str(vals.get(c, "")) for c in range(1, ncols + 1)])
            elif h1 < r <= last:
                rec["body"].append([str(vals.get(c, "")) for c in range(1, ncols + 1)])
    return rec


def figure_record(project: Path, entry: dict) -> dict:
    side = Path(project) / "05_figures" / "qc" / f"{Path(str(entry.get('file', ''))).stem}.artist.json"
    art = _json(side) or {}
    flow = entry.get("archetype") == "flow_diagram" or art.get("archetype") == "flow_diagram"
    out = []
    roles = art.get("text_roles") if isinstance(art.get("text_roles"), list) else None
    if roles:
        for t in roles:
            if not isinstance(t, dict) or not str(t.get("text", "")).strip():
                continue
            role = str(t.get("role") or "figure text")
            if flow and role in ("annotation", "figure text"):
                role = "flow box"
            item = {"role": role, "text": str(t["text"])}
            if t.get("axis"):
                item["axis"] = str(t["axis"])
            out.append(item)
    else:
        for t in art.get("figure_text", []) or []:
            if str(t).strip():
                out.append({"role": "flow box" if flow else "figure text", "text": str(t)})
    seen, uniq = set(), []
    for item in out:
        key = (item["role"], item["text"], item.get("axis"))
        if key not in seen:
            seen.add(key)
            uniq.append(item)
    scales = art.get("axis_scales") if isinstance(art.get("axis_scales"), dict) else {}
    return {"strings": uniq, "axis_scales": scales, "sidecar": side.is_file()}


def _plan_entries(project: Path):
    plan = _json(Path(project) / clinical.PLAN) or {}
    for g in ("main_figures", "main_tables", "supp_figures", "supp_tables"):
        for e in plan.get(g, []) if isinstance(plan, dict) else []:
            if isinstance(e, dict) and str(e.get("id", "")).strip():
                yield g, e


def _source_hash(project: Path, kind: str, entry: dict, caption: str) -> str:
    parts = [kind, json.dumps(entry, sort_keys=True, ensure_ascii=False), caption, SCHEMA,
             rules().get("meta", {}).get("version", "")]
    if kind == "table":
        p = Path(project) / str(entry.get("file", ""))
        parts.append(p.read_bytes() if p.is_file() else b"<absent>")
    else:
        side = Path(project) / "05_figures/qc" / f"{Path(str(entry.get('file', ''))).stem}.artist.json"
        parts.append(side.read_bytes() if side.is_file() else b"<absent>")
    return _sha(*parts)


def inventory(project: Path, write: bool = True) -> dict:
    """Every visible string of every planned display; unchanged displays reuse their record."""
    project = Path(project)
    old = _json(project / INV_REL) or {}
    old_d = old.get("displays", {}) if isinstance(old, dict) and old.get("schema") == SCHEMA else {}
    caps = {d["id"]: d for d in clinical.display_items(project)}
    displays = {}
    for group, e in _plan_entries(project):
        eid = str(e["id"]).strip()
        kind = "figure" if group.endswith("figures") else "table"
        cap = caps.get(eid, {})
        caption = cap.get("caption", "") or ""
        h = _source_hash(project, kind, e, caption)
        prev = old_d.get(eid)
        if isinstance(prev, dict) and prev.get("hash") == h:
            displays[eid] = prev
            continue
        rec = table_record(project, e) if kind == "table" else figure_record(project, e)
        cap_role = "caption" if kind == "table" else "legend"
        lines = [ln.strip() for ln in caption.splitlines() if ln.strip()]
        title = re.sub(r"\s+", " ", lines[0]).strip(" .") if lines else ""
        strings = list(rec["strings"])
        if title:
            strings.append({"role": cap_role, "text": title})
        strings += [{"role": cap_role, "text": ln} for ln in lines[1:]]
        notes = "\n".join([caption] + [s["text"] for s in strings if s["role"] == "footnote"])
        displays[eid] = {"id": eid, "kind": kind, "main": group.startswith("main"),
                         "archetype": e.get("archetype"), "file": str(e.get("file", "")),
                         "hash": h, "title": title, "about": _about(e, title),
                         "strings": strings, "notes": notes,
                         "header": rec.get("header", []), "body": rec.get("body", []),
                         "ncols": rec.get("ncols", 0), "axis_scales": rec.get("axis_scales", {})}
    inv = {"schema": SCHEMA, "displays": displays,
           "hash": _sha(*[f"{k}:{v['hash']}" for k, v in sorted(displays.items())])}
    if write:
        p = project / INV_REL
        if (old or {}).get("hash") != inv["hash"] or not p.is_file():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(inv, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return inv


def _about(entry: dict, title: str) -> str:
    for k in ("message", "purpose", "shows", "question", "description", "content", "title"):
        v = str(entry.get(k, "") or "").strip()
        if len(v) >= 8:
            return v
    return title


def markdown(inv: dict) -> str:
    out = [f"# Display text inventory ({inv.get('hash', '')[:12]})", ""]
    for d in inv["displays"].values():
        out += [f"## {d['id']} ({'main' if d['main'] else 'supplementary'} {d['kind']})", ""]
        out += [f"- [{s['role']}] {s['text']}" for s in d["strings"]] + [""]
    return "\n".join(out)


# ----------------------------------------------------------------------------- rules
_SNAKE = re.compile(r"(?<![\w./\\])[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]*[A-Za-z0-9](?![\w])")
_DOTTED = re.compile(r"(?<![\w.])([a-z][a-z0-9]*)\.([a-z][a-z0-9]*)(?:\.[a-z0-9]+)*(?![\w(])")
_CALL = re.compile(r"(?<![\w.])(?:factor|as\.[a-z]+|after_stat|after_scale|stat|log|log2|log10|"
                   r"log1p|exp|sqrt|I|ns|rcs|bs|poly|strata|cluster|offset|relevel|interaction|"
                   r"cut|Surv|C|c)\(")
_ARTEFACT = re.compile(r"\.\.(?:count|density|prop|level|scaled)\.\.|\bUnnamed: ?\d+\b|\blevel_\d+\b|"
                       r"<NA>|\bNaN\b|\bNULL\b|(?<![\w.])-?Inf\b|\bdtype\b|\bint64\b|\bfloat64\b")
_FORMULA = re.compile(r"(?<![\w:/])[A-Za-z][A-Za-z0-9_.]*:[A-Za-z][A-Za-z0-9_.]*(?![\w:])|"
                      r"[A-Za-z_)]\s*~\s*[A-Za-z_(.1]")
_OPS = re.compile(r"==|!=|&&|\|\||(?<=[A-Za-z0-9_])\s*(?:>=|<=)\s*(?=[A-Za-z0-9_.])")
_FILE = re.compile(r"(?<![\w.])[\w-]+\.(?:csv|tsv|xlsx?|json|rds|rda|rdata|RData|py|R|txt|parquet|"
                   r"feather|sav|dta|sas7bdat|log|toml)\b|(?:[A-Za-z]:[\\/]|(?<![\w])(?:0\d_[a-z]+|"
                   r"\.wf|temp|tools)[\\/])")
_WHOLE = re.compile(r"^(?:TRUE|FALSE|True|False|NA|N/A|NaN|nan|NULL|None|Inf|-Inf|index|level_\d+|"
                    r"Unnamed: ?\d+|\(Intercept\)|Intercept)$")
_VARPREFIX = re.compile(r"^[a-z][a-z0-9_.]*:\s+\S")
_DUMMY = re.compile(r"^([a-z]{2,})([A-Z][A-Za-z0-9]*|[IVX]{1,4}|\d+)$")
_SCI = re.compile(r"(?<![\w.])[-+]?\d+(?:\.\d+)?[eE][-+]?\d+(?![\w.])")
_MANYDEC = re.compile(r"(?<![\w.])\d+\.\d{4,}(?!\d)")
_REF = re.compile(r"^\s*1(?:\.0+)?\s*\(\s*1(?:\.0+)?\s*(?:-|\u2013|\u2014|to|,)\s*1(?:\.0+)?\s*\)\s*$")
_EST = re.compile(r"^\s*([-\u2212]?\d+(?:\.\d+)?)\s*\(\s*([-\u2212]?\d+(?:\.\d+)?)\s*(?:-|\u2013|\u2014|to|,)"
                  r"\s*([-\u2212]?\d+(?:\.\d+)?)\s*\)\s*$")
_NPCT = re.compile(r"^\s*(\d[\d,\u2009]*)\s*\(\s*(\d+(?:\.\d+)?)\s*%?\s*\)\s*$")
_PLAINPCT = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*%\s*$")
_RATIO_HEAD = re.compile(r"\b(?:a?OR|a?HR|a?RR|IRR|ROR|PRR|sHR|SHR)s?\b|\bratios?\b", re.I)
_P_HEAD = re.compile(r"(?i)^\s*p(?:\s|$|-|\s*value|\s*\(|\s*for)|\bp[- ]value")
_NPCT_WORDS = re.compile(r"(?i)\bn\s*\(\s*%\s*\)|\bno\.\s*\(\s*%\s*\)|\bn/N\b|\bnumber\s*\(\s*%\s*\)|"
                         r"\bnumbers?\s+(?:and|\()\s*percentages?|\bn\s*\(percent|\bcount\s*\(\s*%")
_EFFECT = re.compile(r"(?i)\b(?:odds|hazard|risk|rate|reporting odds|proportional reporting)\s+ratio|"
                     r"\b(?:a?OR|a?HR|a?RR|IRR|ROR|PRR|sHR)\b|^\s*(?:estimate|effect(?: size)?)\s*$")
_TIME = re.compile(r"(?i)^\s*(?:time|follow-?\s?up|days?|weeks?|months?|years?)\b")
_TUNIT = re.compile(r"(?i)\b(?:days?|weeks?|months?|years?|hours?|minutes?|h|d|wk|mo|yr)\b")
_TORIGIN = re.compile(r"(?i)\b(?:since|from|after|to|post|of)\b")
_UNIT_VARS = re.compile(r"(?i)^\s*(age|weight|height|body mass index|bmi|duration|follow-up|"
                        r"follow up|time to [\w-]+|dose|interval|latency|length of stay)\s*$")


@lru_cache(maxsize=1)
def _clinical_exact() -> frozenset:
    return frozenset(rules().get("clinical_tokens", {}).get("exact", []))


def _DOTTED_name(s: str) -> str | None:
    for m in _DOTTED.finditer(s):
        a, b = m.group(1), m.group(2)
        tok = m.group(0)
        if len(a) <= 1 and len(b) <= 1 or tok.casefold() in ("e.g", "i.e", "vs.", "a.m", "p.m", "et.al"):
            continue
        return tok
    return None


def _dummy(s: str) -> str | None:
    exact = _clinical_exact()
    for tok in re.findall(r"[A-Za-z0-9]+", s):
        m = _DUMMY.match(tok)
        if not m or tok in exact:
            continue
        head, tail = m.group(1), m.group(2)
        if len(head) <= 2 and tail.isupper() and len(tail) >= 2:  # hsCRP, ctDNA
            continue
        return tok
    return None


def _project_names(project: Path) -> tuple[set, set]:
    """(code-like names, plain lowercase names) from the results JSON keys and the column
    headers of derived analysis datasets."""
    code, plain = set(), set()

    def add(k):
        k = str(k).strip()
        if len(k) < 3 or k in _clinical_exact():
            return
        if "_" in k or "." in k or re.search(r"[a-z][A-Z]|[A-Za-z]\d|\d[A-Za-z]", k):
            code.add(k)
        elif re.fullmatch(r"[a-z]+", k):
            plain.add(k)

    def walk(obj, depth=0):
        if depth > 6:
            return
        if isinstance(obj, dict):
            for k, v in list(obj.items())[:2000]:
                if k == "environment":
                    continue
                add(k)
                walk(v, depth + 1)
        elif isinstance(obj, list):
            for v in obj[:500]:
                walk(v, depth + 1)
    for p in sorted((Path(project) / "03_analysis/results").glob("*.json")):
        walk(_json(p))
    for p in sorted((Path(project) / "02_data/derived").glob("*.[ct]sv")):
        try:
            with p.open(encoding="utf-8", errors="replace") as fh:
                head = fh.readline()
        except OSError:
            continue
        sep = "\t" if p.suffix.casefold() == ".tsv" else ","
        for k in head.strip().split(sep):
            add(k.strip().strip('"'))
    return code, plain


def _number_style(project: Path) -> tuple[int, int]:
    try:
        from . import presentparams
        nf = presentparams.params(project).get("number_format") or {}
    except Exception:  # noqa: BLE001
        nf = {}
    def num(key, default):
        try:
            return int(nf.get(key, default))
        except (TypeError, ValueError):
            return default
    return num("ratio_decimals", 2), num("percent_decimals", 1)


def _dec(x: str) -> int:
    return len(x.split(".")[1]) if "." in x else 0


class _Ctx:
    def __init__(self, project: Path):
        self.project = Path(project)
        self.data = clinical.dictionary(self.project) or {}
        self.names = clinical.internal_names(self.data)
        self.units = {}
        for t in self.data.get("terms", []) or []:
            if isinstance(t, dict) and str(t.get("unit", "") or "").strip():
                for n in [t.get("internal"), t.get("label")] + list(t.get("aliases") or []):
                    if str(n or "").strip():
                        self.units[str(n).strip().casefold()] = (str(t.get("label", "")).strip(),
                                                                 str(t["unit"]).strip())
        self.code, self.plain = _project_names(self.project)
        self.allowed = clinical.allowlist(self.project)
        self.ratio_dec, self.pct_dec = _number_style(self.project)
        self.letter = re.compile(clinical.rules()["letter_codes"]["pattern"])
        self.placeholders = {w.casefold() for w in rules()["placeholders"]["words"]}
        self.software = re.compile(rules()["software_columns"]["pattern"])

    def label_for(self, s: str) -> str | None:
        return self.names.get(s) or self.names.get(s.strip())


def _code_reason(s: str, role: str, c: _Ctx) -> tuple[str, str] | None:
    """(what is code-like, suggestion) or None."""
    text = s.strip()
    prose = role in PROSE
    if text in _clinical_exact():
        return None
    lab = c.label_for(text)
    if lab and not prose:
        return text, f"use the clinical label '{lab}' (display dictionary)"
    for name, label in c.names.items():
        if ("_" in name or clinical._CODE_ID.match(name)) and \
                re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", text):
            return name, f"use the clinical label '{label}' (display dictionary)"
    if not prose:
        if _WHOLE.match(text):
            return text, ("write the category in words ('Yes'/'No', 'Not recorded', 'Reference')"
                          if text not in ("(Intercept)", "Intercept") else
                          "an intercept is not reported in a clinical table (supplementary at most)")
        if _VARPREFIX.match(text):
            return text, ("a variable name before the value (ggplot label_both): show the value "
                          "only, or name the variable clinically")
        if text in c.plain and role != "cell":
            return text, suggestion(text)
    for pat in (_FILE, _CALL, _ARTEFACT, _OPS, _FORMULA, _SNAKE):
        m = pat.search(text)
        if m:
            return m.group(0), _suggest_code(text, m.group(0), c)
    tok = _DOTTED_name(text)
    if tok:
        return tok, _suggest_code(text, tok, c)
    tok = _dummy(text)
    if tok and not prose:
        return tok, _suggest_code(text, tok, c)
    for k in c.code:
        if re.search(rf"(?<![\w.]){re.escape(k)}(?![\w.])", text):
            return k, _suggest_code(text, k, c)
    return None


def _suggest_code(text: str, hit: str, c: _Ctx) -> str:
    lab = c.label_for(hit)
    if lab:
        return f"use the clinical label '{lab}'"
    if re.match(r"(?:log|log2|log10)\(", hit):
        return "name the measure and say 'log scale' (e.g. 'Reporting odds ratio (95% CI), log scale')"
    if _OPS.fullmatch(hit.strip()) or hit.strip() in (">=", "<="):
        return "write the condition in words with \u2265/\u2264 ('Age \u226565 years')"
    return suggestion(text if len(text) <= 60 else hit)


def _cell_findings(d: dict, c: _Ctx) -> list[dict]:
    """Rule d on the table grid (columns) and rule e (n (%) labelling, row-label units)."""
    out = []
    if d["kind"] != "table" or not d.get("body"):
        return out
    header = d["header"][-1] if d.get("header") else []
    ncols = max(len(r) for r in d["body"])
    for col in range(1, ncols):
        head = header[col] if col < len(header) else ""
        is_p = bool(_P_HEAD.search(head))
        ratio = bool(_RATIO_HEAD.search(head) or _RATIO_HEAD.search(d.get("title", "")))
        # Ratio columns use the journal's decimals (so one column is consistent); baseline
        # columns legitimately mix precisions of different measures and are not judged here.
        for row in d["body"]:
            v = row[col] if col < len(row) else ""
            if not v.strip() or is_p:
                continue
            m = _EST.match(v)
            if m:
                ds = {_dec(m.group(1)), _dec(m.group(2)), _dec(m.group(3))}
                if ratio and ds != {c.ratio_dec}:
                    out.append(_f(d, "cell", v, "d", f"ratio and CI with {c.ratio_dec} decimals "
                                  "(journal number format, ratio_decimals)"))
                continue
            m = _NPCT.match(v) or _PLAINPCT.match(v)
            if m:
                # '132 (15)' may be a mean (SD): judged as a percentage only when the cell, the
                # row label or the column header says so
                said = "%" in v or "%" in row[0] or "%" in head
                if m.re is _NPCT and ("." in m.group(1) or not said):
                    continue
                if _dec(m.group(m.lastindex)) != c.pct_dec:
                    out.append(_f(d, "cell", v, "d", f"percentages with {c.pct_dec} decimal(s) "
                                  "(journal number format, percent_decimals)"))
    # e: n (%) rows need 'n (%)' in the row label, a column header or the footnote/caption
    npct_rows = [r for r in d["body"] if sum(1 for v in r[1:] if v.strip()) and
                 all(_NPCT.match(v) and "." not in _NPCT.match(v).group(1) for v in r[1:] if v.strip())]
    heads = " ".join(" ".join(h) for h in d.get("header", []))
    if npct_rows and not (_NPCT_WORDS.search(heads) or _NPCT_WORDS.search(d.get("notes", ""))):
        lacking = [r[0] for r in npct_rows if not _NPCT_WORDS.search(r[0])]
        if lacking:
            out.append(_f(d, "row label", lacking[0], "e", "count rows say what the numbers are: "
                          "'<characteristic>, n (%)' or a footnote 'Values are n (%)'"))
    # e: continuous rows carry units
    for r in d["body"]:
        label = r[0].strip()
        vals = [v for v in r[1:] if v.strip()]
        if not label or not vals or all(_NPCT.match(v) for v in vals):
            continue
        base = re.split(r",|\(", label)[0].strip().casefold()
        known = c.units.get(label.casefold()) or c.units.get(base)
        if known and known[1].casefold() not in label.casefold():
            out.append(_f(d, "row label", label, "e", f"'{known[0]}, {known[1]}' (unit from the "
                          "display dictionary)"))
        elif not known and _UNIT_VARS.match(label):
            out.append(_f(d, "row label", label, "e", f"add the unit ('{label}, years' or as "
                          "measured) and a 'unit' in the display dictionary entry"))
    return out


def _f(d: dict, role: str, text: str, rule: str, suggest: str) -> dict:
    return {"display": d["id"], "kind": d["kind"], "main": d["main"], "role": role,
            "text": str(text), "rule": rule, "suggest": suggest,
            "severity": "warn" if rule in WARN_RULES else "fail"}


def _allowed(f: dict, c: _Ctx) -> bool:
    keys = {f["text"].strip().casefold(), str(f.get("hit", "")).strip().casefold()}
    return any(c.allowed.get(k) in ("all", "display") for k in keys if k)


def findings(project: Path, inv: dict | None = None, review: list | None = None) -> list[dict]:
    """Every flagged string with its display, role, rule and a suggested clinical wording."""
    project = Path(project)
    inv = inv or inventory(project, write=False)
    c = _Ctx(project)
    out: list[dict] = []
    for d in inv["displays"].values():
        notes = d.get("notes", "")
        title = d.get("title", "")
        notes_body = notes.replace(title, " ", 1) if title else notes
        for s in d["strings"]:
            role, text = s["role"], s["text"]
            if d["main"] and role == "column header" and d["kind"] == "table" and \
                    c.software.match(text.strip()):
                out.append(_f(d, role, text, "c", rules()["software_columns"]["suggest"]))
                continue
            hit = _code_reason(text, role, c)
            if hit:
                f = _f(d, role, text, "a", hit[1])
                f["hit"] = hit[0]
                out.append(f)
                continue
            norm = re.sub(r"[\s:.()]+", " ", text).strip().casefold()
            if role in ("axis title", "legend title", "strip", "column header") and \
                    norm in c.placeholders:
                out.append(_f(d, role, text, "b", rules()["placeholders"]["suggest"]))
                continue
            if role not in PROSE and role != "level":
                if _SCI.search(text):
                    out.append(_f(d, role, text, "d", "no scientific notation: P per journal "
                                  "('<0.001'), estimates rounded"))
                    continue
                if _MANYDEC.search(text):
                    out.append(_f(d, role, text, "d", f"round to the journal format (ratios "
                                  f"{c.ratio_dec}, percentages {c.pct_dec} decimals, P '<0.001')"))
                    continue
                if _REF.match(text):
                    out.append(_f(d, role, text, "d", "the reference category shows 'Reference' "
                                  "(or '1 (Reference)')"))
                    continue
            elif _SCI.search(text):
                out.append(_f(d, role, text, "d", "no scientific notation ('P < 0.001')"))
                continue
            if role == "axis title":
                scale = str((d.get("axis_scales") or {}).get(s.get("axis", ""), ""))
                if "log" in scale.casefold() and "log" not in text.casefold():
                    out.append(_f(d, role, text, "e", "a logarithmic axis says so: '<measure> "
                                  "(95% CI), log scale'"))
                    continue
                if d.get("archetype") == "forest_plot" and _EFFECT.search(text) and \
                        not re.search(r"(?i)\bCI\b|confidence|credible", text):
                    out.append(_f(d, role, text, "e", "name the measure and the interval: "
                                  "'Hazard ratio (95% CI)'"))
                    continue
                if _TIME.match(text) and (not _TUNIT.search(text) or (
                        text.strip().casefold().startswith("time") and not _TORIGIN.search(text))):
                    out.append(_f(d, role, text, "e", "a time axis names its unit and origin: "
                                  "'Time since diagnosis, months'"))
                    continue
            if role not in PROSE or role == "title" or text == title:
                for m in c.letter.finditer(text):
                    lab = m.group(0)
                    if not re.search(rf"{re.escape(lab)}\s*(?::|=|\(|,|-|\u2013|was\b|were\b|is\b|"
                                     r"included|includes|adjusted|denotes|refers)", notes_body):
                        out.append(_f(d, role, text, "f", f"define '{lab}' in this display's "
                                      "footnote/legend (what it includes), or use its clinical name"))
                        break
        visible = "\n".join(s["text"] for s in d["strings"])
        for t in rules().get("technical", []):
            if re.search(t["pattern"], visible, re.I):
                if not re.search(t["expand"], notes, re.I):
                    out.append(_f(d, "footnote" if d["kind"] == "table" else "legend", t["term"],
                                  "g", f"spell out and explain in plain words in this display's "
                                  f"footnote/legend ({t['plain']})"))
                elif review is not None:
                    review.append(f"{d['id']}: is '{t['term']}' explained in plain words? "
                                  f"(e.g. {t['plain']})")
        if d["kind"] == "table" and d["main"] and d.get("ncols", 0) - 1 > 8:
            out.append(_f(d, "column header", f"{d['ncols'] - 1} data columns", "h",
                          "split the table or move detail columns to a supplementary table"))
        out += _cell_findings(d, c)
    seen, uniq = set(), []
    for f in out:
        key = (f["display"], f["role"], f["text"])
        if key in seen or _allowed(f, c):
            continue
        seen.add(key)
        uniq.append(f)
    return uniq


def line(f: dict) -> str:
    return f"{f['display']} [{f['role']}] '{f['text'][:70]}' -> {f['suggest']}"


# ------------------------------------------------------------------ writer bundle (V5)
def _key(f: dict) -> str:
    return _sha(f["display"], f["role"], f["text"], f["rule"])[:12]


def build_bundle(project: Path, inv: dict, finds: list[dict]) -> Path:
    """.wf/writer_bundle/displays/: only the flagged strings, each with its context, in words.
    Incremental: strings already sent and unchanged are listed as still open, not re-sent."""
    project = Path(project)
    out = project / BUNDLE_REL
    out.mkdir(parents=True, exist_ok=True)
    state = _json(project / STATE_REL) or {}
    sent = state.get("sent", {}) if isinstance(state, dict) else {}
    data = clinical.dictionary(project) or {}
    labels = []
    for t in data.get("terms", []) or []:
        if isinstance(t, dict) and str(t.get("label", "")).strip():
            u = str(t.get("unit", "") or "").strip()
            labels.append(f"- {t['label']}" + (f" (unit: {u})" if u else "")
                          + (f" - {t.get('definition')}" if t.get("definition") else ""))
    items, still = [], []
    ids = {}
    n = 0
    for f in finds:
        k = _key(f)
        n += 1
        fid = f"D{n}"
        ids[fid] = {"key": k, "display": f["display"], "role": f["role"], "text": f["text"],
                    "rule": f["rule"]}
        d = inv["displays"].get(f["display"], {})
        block = [f"### {fid} - {f['display']}: {d.get('title', '')}",
                 f"- The display shows: {d.get('about') or d.get('title', '')}",
                 f"- Where: {f['role']}",
                 f"- Text now: \"{f['text']}\"",
                 f"- Why it needs wording: {_rule_words(f['rule'])}; suggestion: {f['suggest']}"]
        (still if k in sent else items).append("\n".join(block))
    head = [f"# Display wording bundle (inventory {inv.get('hash', '')[:12]})", "",
            f"Write your answer to {REPLY_REL} as ONE table with the header",
            "| ID | Clinical wording | Unit | Definition (one line) | Footnote/legend sentence |",
            "and one row per item below (leave a cell empty when it does not apply). Clinical "
            "wording replaces the text shown; a unit only for continuous measures; a footnote or "
            "legend sentence only when the item needs an explanation (abbreviation spelled out, a "
            "technical term in plain words, what 'Model 2' includes). Never change a number.", "",
            "## Clinical labels already used in this paper", ""] + (labels or ["- (none yet)"])
    body = head + ["", f"## New or changed ({len(items)})", ""] + (items or ["(none)"])
    if still:
        body += ["", f"## Still open from the previous bundle ({len(still)})", ""] + still
    (out / "MANIFEST.md").write_text("\n".join(body) + "\n", encoding="utf-8")
    st = {"inventory": inv.get("hash"), "ids": ids,
          "sent": {**{k: v for k, v in sent.items() if k in {i["key"] for i in ids.values()}},
                   **{i["key"]: inv.get("hash") for i in ids.values()}}}
    p = project / STATE_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(st, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return out / "MANIFEST.md"


def _rule_words(rule: str) -> str:
    return {"a": "looks like a programme name, not a clinical term",
            "b": "a generic label that does not say what is shown",
            "c": "a software-output column a clinician does not use",
            "d": "number display (format, rounding, reference category)",
            "e": "unit or measure missing",
            "f": "a label not defined in this display",
            "g": "a technical term that needs a plain explanation",
            "h": "too many columns for a main table"}.get(rule, rule)


def apply_reply(project: Path) -> list[str]:
    """Merge the writer's table into the display dictionary (labels, units, definitions); every
    other wording (headers, footnotes, legends) is listed for the builder scripts."""
    project = Path(project)
    reply = project / REPLY_REL
    if not reply.is_file():
        raise ValueError(f"{REPLY_REL} missing (the clinical writer writes it from {BUNDLE_REL})")
    state = _json(project / STATE_REL) or {}
    ids = state.get("ids", {})
    rows = []
    for ln in reply.read_text(encoding="utf-8", errors="replace").splitlines():
        cells = [x.strip() for x in ln.strip().strip("|").split("|")]
        if len(cells) >= 2 and re.fullmatch(r"D\d+", cells[0]):
            rows.append((cells + [""] * 5)[:5])
    if not rows:
        raise ValueError(f"{REPLY_REL}: no rows '| D1 | ... |'")
    dpath = project / clinical.DICT_REL
    data = clinical.dictionary(project) or {"terms": []}
    terms = data.setdefault("terms", [])
    by_internal = {str(t.get("internal", "")): t for t in terms if isinstance(t, dict)}
    by_label = {str(t.get("label", "")).casefold(): t for t in terms if isinstance(t, dict)}
    changed, notes, out = 0, [], []
    for fid, wording, unit, definition, sentence in rows:
        item = ids.get(fid)
        if not item:
            out.append(f"{fid}: not in the current bundle (run `wf displays text` again)")
            continue
        text = item["text"]
        if wording and item["rule"] in ("a", "e") and item["role"] not in PROSE:
            t = by_internal.get(text) or (by_label.get(text.casefold()) if item["rule"] == "e" else None)
            if t is None:
                t = {"internal": text, "label": wording, "definition": definition or wording}
                terms.append(t)
                by_internal[text] = t
            else:
                t["label"] = wording if item["rule"] == "a" else t.get("label") or wording
                if definition:
                    t["definition"] = definition
            if unit:
                t["unit"] = unit
            changed += 1
        elif wording:
            notes.append(f"- {item['display']} [{item['role']}]: replace \"{text}\" with \"{wording}\"")
        if sentence:
            notes.append(f"- {item['display']} footnote/legend: add \"{sentence}\"")
    if changed:
        dpath.parent.mkdir(parents=True, exist_ok=True)
        dpath.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        out.append(f"{clinical.DICT_REL}: {changed} entr(y/ies) added or updated (labels, units, "
                   "definitions); the builders relabel on the next render (`wf rebuild`)")
    np_ = project / NOTES_REL
    if notes:
        np_.parent.mkdir(parents=True, exist_ok=True)
        np_.write_text("# Wording to apply in the table/figure scripts and legends\n\n"
                       + "\n".join(notes) + "\n", encoding="utf-8")
        out.append(f"{NOTES_REL}: {len(notes)} wording change(s) for the builder scripts, "
                   "05_figures/legends.md and 04_tables/table_captions.md")
    return out


def run(project: Path, md: bool = False) -> tuple[dict, list[dict], Path, list[str]]:
    """`wf displays text`: inventory + findings + writer bundle (+ markdown)."""
    project = Path(project)
    inv = inventory(project)
    review: list[str] = []
    finds = findings(project, inv, review)
    bundle = build_bundle(project, inv, finds)
    if md:
        (project / INV_MD).write_text(markdown(inv) + "\n", encoding="utf-8")
    return inv, finds, bundle, review
