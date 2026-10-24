"""1.11.0 (#2a): presentation parameters decided early, used by every builder from the start.

    01_protocol/journal_profile.json   S06/S07: provisional target journal or journal type
        {"status": "provisional", "journal_or_type": "Springer clinical journal (provisional)",
         "font_min_pt": 8, "figure_width_mm": {"single": 84, "1.5": 129, "double": 174},
         "panel_label_case": "lower", "line_art_dpi": 600,
         "number_format": {"thousands": ",", "p_space": true}, "spelling": "american",
         "heading_names": {"methods": "Methods"}, "source": "<guide URL or 'journal type default'>"}
    08_submission/target_journal.json  S20: "presentation": {same keys} confirms or replaces it.

Effective value: engine defaults < journal_profile.json < target_journal.json "presentation".
A change at S20 is a presentation re-render (facts unchanged), never a science change.
Builders read it through params(); R/Python figure scripts get MEDPAPER_PRESENTATION from
`wf run-script`.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

PROVISIONAL = "01_protocol/journal_profile.json"
TARGET = "08_submission/target_journal.json"
KEYS = ("font_min_pt", "figure_width_mm", "panel_label_case", "line_art_dpi", "number_format",
        "spelling", "heading_names", "in_figure_title")
# in_figure_title (1.12.0 F1): false = the journal puts titles in the legend only.
DEFAULTS = {"font_min_pt": 8.0, "figure_width_mm": {"single": 90.0, "1.5": 140.0, "double": 180.0},
            "panel_label_case": "upper", "line_art_dpi": 600, "number_format": {},
            "spelling": None, "heading_names": {}, "in_figure_title": None}


def _json(path: Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def provisional(project: Path) -> dict:
    return _json(Path(project) / PROVISIONAL)


def confirmed(project: Path) -> dict:
    block = _json(Path(project) / TARGET).get("presentation")
    return block if isinstance(block, dict) else {}


def params(project: Path | None = None) -> dict:
    if project is None:
        raw = os.environ.get("MEDPAPER_PROJECT")
        project = Path(raw) if raw else None
    out = json.loads(json.dumps(DEFAULTS))
    if project is not None:
        try:
            from . import registry
            tg = registry.effective_targets(Path(project))
            out["figure_width_mm"] = {"single": float(tg.get("column_width_mm_single", 90.0)),
                                      "1.5": float(tg.get("column_width_mm_1_5", 140.0)),
                                      "double": float(tg.get("column_width_mm_double", 180.0))}
        except Exception:  # noqa: BLE001 - defaults stand
            pass
        for layer in (provisional(project), confirmed(project)):
            for key in KEYS:
                if layer.get(key) is None:
                    continue
                if isinstance(out.get(key), dict) and isinstance(layer[key], dict):
                    out[key] = {**out[key], **layer[key]}
                else:
                    out[key] = layer[key]
    return out


def problems(block: dict, where: str) -> list[str]:
    out = []
    fp = block.get("font_min_pt")
    if not isinstance(fp, (int, float)) or isinstance(fp, bool) or not 5 <= fp <= 14:
        out.append(f"{where}: font_min_pt must be a number 5-14 (final print size)")
    w = block.get("figure_width_mm")
    if not isinstance(w, dict) or not all(isinstance(w.get(k), (int, float)) for k in ("single", "double")):
        out.append(f"{where}: figure_width_mm needs single and double (mm)")
    if block.get("panel_label_case") not in ("upper", "lower"):
        out.append(f"{where}: panel_label_case must be upper or lower")
    dpi = block.get("line_art_dpi")
    if not isinstance(dpi, int) or isinstance(dpi, bool) or dpi < 300:
        out.append(f"{where}: line_art_dpi must be an integer >= 300")
    if not isinstance(block.get("number_format", {}), dict):
        out.append(f"{where}: number_format must be an object")
    if block.get("spelling") not in ("american", "british"):
        out.append(f"{where}: spelling must be american or british")
    if not isinstance(block.get("heading_names", {}), dict):
        out.append(f"{where}: heading_names must be an object")
    return out


def env_json(project: Path | None) -> str:
    return json.dumps(params(project))
