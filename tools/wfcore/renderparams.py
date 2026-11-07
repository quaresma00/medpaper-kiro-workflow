"""1.17.0 (J7): presentation parameters recorded at render time.

Figures (R save_medpaper and Python style.save) write the parameters they rendered with into
their artist sidecar ("presentation"); the table builders (tables/threeline.py) record theirs in
04_tables/render_params.json. presentation_params_confirmed compares them with the journal's
current parameters, so figures rendered for the previous journal (width, dpi, font floor, panel
label case; number format and spelling in tables) block until `wf rebuild` re-renders them - a
presentation re-render, never a science change.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

TABLES = "04_tables/render_params.json"
QC = "05_figures/qc"
FIG_KEYS = ("figure_width_mm", "line_art_dpi", "font_min_pt", "panel_label_case")
TAB_KEYS = ("number_format", "spelling")


def _canon(v):
    if isinstance(v, bool) or v is None or isinstance(v, str):
        return v
    if isinstance(v, (int, float)):
        f = round(float(v), 3)
        return int(f) if f.is_integer() else f
    if isinstance(v, dict):
        return {str(k): _canon(x) for k, x in sorted(v.items())}
    if isinstance(v, list):
        return [_canon(x) for x in v]
    return v


def snapshot(keys, project: Path | None = None) -> dict:
    from . import presentparams
    p = presentparams.params(project)
    out = {k: p.get(k) for k in keys}
    if "number_format" in keys or "spelling" in keys:
        try:
            from . import numfmt
            st = numfmt.style(project) if project is not None else numfmt.style()
            if isinstance(st, dict):
                out["number_format"] = {**(out.get("number_format") or {}),
                                        **{k: v for k, v in st.items() if k != "spelling"}}
                if st.get("spelling"):
                    out["spelling"] = st["spelling"]
        except Exception:  # noqa: BLE001 - presentparams alone stands
            pass
    try:  # 1.20.0 (V4/V8): the display-dictionary relabel map in force ('off' or its hash)
        from . import displaytext
        out["display_labels"] = displaytext.labels_state(project)
    except Exception:  # noqa: BLE001
        pass
    return _canon(out)


def figure_snapshot() -> dict:
    return snapshot(FIG_KEYS)


def record_table(path: Path) -> None:
    """Called by tables/threeline.py after a workbook is written inside a paper."""
    raw = os.environ.get("MEDPAPER_PROJECT")
    if not raw:
        return
    project = Path(raw).resolve()
    try:
        rel = Path(path).resolve().relative_to(project).as_posix()
    except ValueError:
        return
    f = project / TABLES
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data.setdefault("schema", 1)
    data.setdefault("tables", {})[rel] = {
        "params": snapshot(TAB_KEYS, project), "script": os.environ.get("MEDPAPER_SCRIPT", ""),
        "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def records(project: Path) -> list[dict]:
    """[{display, kind, script, params|None}] for every rendered figure and recorded table."""
    project = Path(project)
    out = []
    qc = project / QC
    for side in sorted(qc.glob("*.artist.json")) if qc.is_dir() else []:
        try:
            art = json.loads(side.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        pres = art.get("presentation")
        out.append({"display": side.name.replace(".artist.json", ""), "kind": "figure",
                    "script": art.get("script") or "",
                    "params": pres if isinstance(pres, dict) and pres else None})
    try:
        tabs = json.loads((project / TABLES).read_text(encoding="utf-8")).get("tables", {})
    except (OSError, ValueError, AttributeError):
        tabs = {}
    for rel, rec in sorted(tabs.items()):
        if (project / rel).is_file():
            out.append({"display": rel, "kind": "table", "script": rec.get("script") or "",
                        "params": rec.get("params")})
    return out


def mismatches(project: Path, require: bool) -> list[dict]:
    """Displays rendered with other parameters than the journal's current ones. `require`:
    a display without a record (rendered before 1.17.0) counts as a mismatch."""
    project = Path(project)
    want = {"figure": snapshot(FIG_KEYS, project), "table": snapshot(TAB_KEYS, project)}
    out = []
    for rec in records(project):
        cur = want[rec["kind"]]
        if rec["params"] is None:
            if require:
                out.append({**rec, "diff": ["no render parameters recorded (rendered before 1.17.0)"]})
            continue
        got = _canon(rec["params"])
        diff = [f"{k} {json.dumps(got.get(k), ensure_ascii=False)} -> "
                f"{json.dumps(cur.get(k), ensure_ascii=False)}"
                for k in cur if k in got and got.get(k) != cur.get(k)]
        if diff:
            out.append({**rec, "diff": diff})
    return out
