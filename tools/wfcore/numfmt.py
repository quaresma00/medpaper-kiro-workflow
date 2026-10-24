"""1.9.0 journal number style and spelling system, applied at build/render time.

Before 1.9.0 the P-value form ("<0.001"), the minus sign, thousands separators and the interval
dash were hard-coded in build scripts, and British spellings sat in table/figure scripts. Moving
to a journal with other rules meant editing a certified scientific source and returning to S19.
Now they are parameters:

    target_journal.json  "number_format": {"p_space": true, "minus": "unicode" | "hyphen",
                                           "thousands": "," | "" | "thin", "interval": " to "},
                         "spelling": "american" | "british" (prose such as "American English;
                         AMA" is read by its first word)
    .wf/config.toml      spelling = "american"   (decided at S01/S03; default american)

Table builders pass every cell through `apply_text`, the R figure helpers read the same values
from MEDPAPER_NUMFMT (exported by `wf run-script`), so switching journal or spelling is a
rebuild with unchanged facts - a presentation change under the 1.9.0 classification.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

# None = not decided: the text is left exactly as the script wrote it (no silent rewrite of a
# paper that predates 1.9.0). New papers get spelling = "american" in their config at wf new.
DEFAULT = {"p_space": None, "minus": None, "thousands": None, "interval": None, "spelling": None}
THIN = "\u2009"
# British -> American; reversed for a British-spelling journal. Word stems, matched case-aware.
SPELLING_PAIRS = (
    ("haemoglobin", "hemoglobin"), ("anaemia", "anemia"), ("oedema", "edema"),
    ("artefact", "artifact"), ("standardised", "standardized"), ("standardisation", "standardization"),
    ("randomised", "randomized"), ("randomisation", "randomization"), ("colour", "color"),
    ("tumour", "tumor"), ("paediatric", "pediatric"), ("oesophag", "esophag"),
    ("haemorrhage", "hemorrhage"), ("haemodynamic", "hemodynamic"), ("analysed", "analyzed"),
    ("leukaemia", "leukemia"), ("ischaemi", "ischemi"), ("centre", "center"),
    ("behaviour", "behavior"), ("organisation", "organization"), ("characterised", "characterized"),
    ("categorised", "categorized"), ("hospitalisation", "hospitalization"), ("optimis", "optimiz"),
    ("normalised", "normalized"), ("utilis", "utiliz"), ("haematolog", "hematolog"),
    ("oestrogen", "estrogen"), ("foetal", "fetal"), ("gynaecolog", "gynecolog"),
    ("anaesthe", "anesthe"),
)


def _spelling_word(value) -> str | None:
    text = str(value or "").strip().casefold()
    if text.startswith(("american", "us ", "us-", "us_")) or text in ("us", "en-us"):
        return "american"
    if text.startswith(("british", "uk", "en-gb")):
        return "british"
    return None


def style(project: Path | None = None) -> dict:
    """Effective number style: defaults < paper config (spelling) < target_journal.json."""
    out = dict(DEFAULT)
    if project is None:
        raw = os.environ.get("MEDPAPER_PROJECT")
        project = Path(raw) if raw else None
    if project is None:
        return out
    project = Path(project)
    cfg = project / ".wf" / "config.toml"
    if cfg.is_file():
        try:
            import tomllib
            data = tomllib.loads(cfg.read_text(encoding="utf-8"))
            sp = _spelling_word((data.get("targets") or {}).get("spelling") or data.get("spelling"))
            if sp:
                out["spelling"] = sp
        except Exception:  # noqa: BLE001 - a broken config keeps the default
            pass
    try:
        target = json.loads((project / "08_submission/target_journal.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        target = {}
    # 1.11.0 (#2a): the provisional journal profile (S06/S07) applies from the first build;
    # the chosen journal (S20) overrides it.
    from . import presentparams
    layers = [presentparams.provisional(project)]
    if isinstance(target, dict):
        pres = target.get("presentation")
        layers.append(pres if isinstance(pres, dict) else {})
    for layer in layers:
        sp = _spelling_word(layer.get("spelling"))
        if sp:
            out["spelling"] = sp
        nf = layer.get("number_format")
        if isinstance(nf, dict):
            for key in ("p_space", "minus", "thousands", "interval"):
                if key in nf:
                    out[key] = nf[key]
    if isinstance(target, dict):
        sp = _spelling_word(target.get("spelling"))
        if sp:
            out["spelling"] = sp
        nf = target.get("number_format")
        if isinstance(nf, dict):
            for key in ("p_space", "minus", "thousands", "interval"):
                if key in nf:
                    out[key] = nf[key]
    if out["thousands"] == "thin":
        out["thousands"] = THIN
    return out


def respell(text: str, spelling: str = "american") -> str:
    for brit, amer in SPELLING_PAIRS:
        src, dst = (brit, amer) if spelling != "british" else (amer, brit)
        text = re.sub(src, dst, text)
        text = re.sub(src.capitalize(), dst.capitalize(), text)
        text = re.sub(src.upper(), dst.upper(), text)
    return text


_P_RE = re.compile(r"(?<![\w.])([<>\u2264\u2265=])\s*(0?\.\d+)")
_NEG_RE = re.compile(r"(?<![\w.)\]])[-\u2212](?=\d)")
_BIG_RE = re.compile(r"(?<![\w.,\u2009])(\d{1,3}(?:[,\u2009]\d{3})+|\d{5,})(?![\w.,]\d)")
_RANGE_RE = re.compile(r"(?<=\d)\s*(?:-|\u2013|to)\s*(?=[-\u2212]?\d)")


def _group(num: str, sep: str) -> str:
    digits = re.sub(r"[,\u2009]", "", num)
    if not sep:
        return digits
    if len(digits) < 5 and sep:  # 1000-9999 keep their form in most medical styles
        return digits
    out = ""
    while len(digits) > 3:
        out = sep + digits[-3:] + out
        digits = digits[:-3]
    return digits + out


def apply_text(text: str, st: dict | None = None) -> str:
    """Restyle one display string (table cell, label): P comparators, minus, thousands, spelling.
    The interval dash is applied inside parenthesised CIs only ("1.2 (1.0-1.5)")."""
    if not isinstance(text, str) or not text:
        return text
    st = st if st is not None else style()
    if st.get("p_space") is not None:
        sp = " " if st["p_space"] else ""
        text = _P_RE.sub(lambda m: f"{m.group(1)}{sp}{m.group(2)}", text)
    if st.get("minus") in ("unicode", "hyphen"):
        text = _NEG_RE.sub("\u2212" if st["minus"] == "unicode" else "-", text)
    if st.get("thousands") is not None:
        text = _BIG_RE.sub(lambda m: _group(m.group(1), st["thousands"]), text)
    interval = st.get("interval")
    if interval:
        text = re.sub(r"\(([-\u2212]?\d[\d.]*)\s*(?:-|\u2013| to )\s*([-\u2212]?\d[\d.]*)\)",
                      lambda m: f"({m.group(1)}{interval}{m.group(2)})", text)
    if st.get("spelling") in ("american", "british"):
        text = respell(text, st["spelling"])
    return text


def env_json(project: Path | None) -> str:
    """The MEDPAPER_NUMFMT value exported to R/Python figure scripts (decided keys only)."""
    return json.dumps({k: v for k, v in style(project).items() if v is not None})
