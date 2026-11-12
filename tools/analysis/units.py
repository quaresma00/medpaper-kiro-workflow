"""1.23.0 (S7): units and plausibility of derived variables (doses, dose per body weight or
body-surface area, standardised equivalents).

    from analysis.units import convert, per_body_weight, derived, derived_block
    mme, unit = convert(daily_mg, "mme_oxycodone_oral")           # factor from the table
    mgkg, unit = per_body_weight(daily_mg, "mg/day", weight_kg)    # -> "mg/kg/day"
    rec = derived("dose_mg_kg_day", mgkg, unit, "daily dose divided by body weight",
                  plausible=(0.01, 50))
    write_results("dosing", {..., **derived_block(rec)})

`per_body_weight` refuses a dose whose unit is already per kilogram (the double division by
body weight), `derived` refuses values outside the declared plausible range, and the results
JSON carries `derived_variables` {name: unit, derivation, plausible_range, observed_range,
range_check}. The S05/S06 check `derived_units_checked` reads that block. Conversion factors come
only from reference/conversion_factors.json, each with a citable source; WHO DDD values change
yearly and are passed with their index year to `ddd()`.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

TABLE = Path(__file__).resolve().parents[2] / "reference" / "conversion_factors.json"


class UnitError(ValueError):
    """A derived variable has the wrong unit or an implausible value."""


def factors() -> dict:
    data = json.loads(TABLE.read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


def factor(key: str) -> dict:
    table = factors()
    if key not in table:
        raise UnitError(f"no conversion factor '{key}' in reference/conversion_factors.json; "
                        "never invent one - an addition needs a citable source")
    meta = json.loads(TABLE.read_text(encoding="utf-8"))["_meta"]["sources"]
    return {**table[key], "key": key, "citation": meta.get(table[key]["source"], "")}


def _map(values, fn):
    if hasattr(values, "map") and hasattr(values, "index"):  # pandas Series
        return values.map(lambda v: None if _missing(v) else fn(v))
    if isinstance(values, (list, tuple)):
        return [None if _missing(v) else fn(v) for v in values]
    try:
        import numpy as np
        if isinstance(values, np.ndarray):
            return fn(values)
    except ImportError:
        pass
    return None if _missing(values) else fn(values)


def _missing(v) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v))


def _flat(values) -> list[float]:
    if hasattr(values, "tolist"):
        values = values.tolist()
    if not isinstance(values, (list, tuple)):
        values = [values]
    return [float(v) for v in values if not _missing(v)]


def convert(values, key: str):
    """Apply a tabulated conversion; returns (converted values, target unit)."""
    f = factor(key)
    return _map(values, lambda v: v * f["factor"] + f.get("offset", 0)), f["to"]


def _norm_unit(unit: str) -> str:
    return str(unit or "").replace(" ", "").casefold()


def per_body_weight(dose, dose_unit: str, weight_kg, weight_unit: str = "kg"):
    """Dose divided by body weight; returns (values, unit). Refuses a dose already per kg."""
    u = _norm_unit(dose_unit)
    if "/kg" in u or "perkg" in u or "kg-1" in u:
        raise UnitError(f"dose unit '{dose_unit}' is already per kilogram: dividing by body "
                        "weight again gives a value about 50-100 times too small")
    if _norm_unit(weight_unit) != "kg":
        raise UnitError("body weight must be in kg (convert pounds first: 1 lb = 0.4536 kg)")
    if not dose_unit.strip():
        raise UnitError("declare the dose unit (e.g. 'mg/day')")
    parts = dose_unit.strip().split("/", 1)
    unit = parts[0] + "/kg" + ("/" + parts[1] if len(parts) > 1 else "")
    d, w = _flat(dose), _flat(weight_kg)
    if any(x <= 0 for x in w):
        raise UnitError("body weight must be > 0 kg")
    if isinstance(dose, (int, float)) and isinstance(weight_kg, (int, float)):
        return dose / weight_kg, unit
    if hasattr(dose, "__truediv__") and not isinstance(dose, (list, tuple)):
        return dose / weight_kg, unit
    if len(d) != len(w):
        raise UnitError("dose and body weight differ in length")
    return [None if _missing(a) or _missing(b) else a / b
            for a, b in zip(list(dose), list(weight_kg))], unit


def per_bsa(dose, dose_unit: str, bsa_m2):
    """Dose divided by body-surface area (m2); refuses a dose already per m2."""
    u = _norm_unit(dose_unit)
    if "/m2" in u or "/m^2" in u or "/m²" in u:
        raise UnitError(f"dose unit '{dose_unit}' is already per m2")
    parts = dose_unit.strip().split("/", 1)
    unit = parts[0] + "/m2" + ("/" + parts[1] if len(parts) > 1 else "")
    if isinstance(dose, (list, tuple)):
        return [None if _missing(a) or _missing(b) else a / b for a, b in zip(dose, bsa_m2)], unit
    return dose / bsa_m2, unit


def ddd(dose_mg, ddd_mg: float, index_year: int, atc: str):
    """Defined daily doses: dose / the WHO DDD of `atc` from the ATC/DDD Index of `index_year`."""
    if not isinstance(index_year, int) or index_year < 1990 or not str(atc).strip():
        raise UnitError("ddd() needs the ATC code and the ATC/DDD Index year the DDD comes from")
    if not ddd_mg or ddd_mg <= 0:
        raise UnitError("the DDD must be > 0 mg")
    return _map(dose_mg, lambda v: v / ddd_mg), f"DDD (WHO ATC/DDD Index {index_year}, {atc})"


def derived(name: str, values, unit: str, derivation: str, plausible: tuple[float, float],
            inputs: dict | None = None, source: str = "") -> dict:
    """Declare a derived variable: unit, derivation, plausible range; refuses implausible data."""
    if not str(unit).strip() or len(str(derivation).strip()) < 10:
        raise UnitError(f"{name}: declare the unit and the derivation (>= 10 characters)")
    lo, hi = float(plausible[0]), float(plausible[1])
    if not lo < hi:
        raise UnitError(f"{name}: plausible range must be (low, high)")
    vals = _flat(values)
    bad = [v for v in vals if not lo <= v <= hi]
    rec = {"unit": unit, "derivation": derivation.strip(), "plausible_range": [lo, hi],
           "observed_range": [min(vals), max(vals)] if vals else None, "n": len(vals),
           "range_check": "passed" if not bad else "failed", "inputs": inputs or {}}
    if source:
        rec["source"] = source
    if bad:
        raise UnitError(f"{name}: {len(bad)} of {len(vals)} value(s) outside the plausible range "
                        f"{lo}-{hi} {unit} (e.g. {bad[0]:.4g}); check the unit and the "
                        "derivation (a double division by body weight is the usual cause)")
    rec["name"] = name
    return rec


def derived_block(*records: dict) -> dict:
    """{"derived_variables": {name: record}} to merge into a write_results() payload."""
    return {"derived_variables": {r["name"]: {k: v for k, v in r.items() if k != "name"}
                                  for r in records}}
