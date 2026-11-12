"""1.23.0 checks (a paper pinned earlier gets them after `wf migrate --yes`; stages not yet
completed then follow them).

publishability_checkpoint   S1 (S02, S04, S06): verdict GO | CONDITIONAL | NO-GO with the best
                            achievable article type and its evidence; CONDITIONAL/NO-GO need the
                            user's one answer; S04/S06 are bound to what they judged.
derived_units_checked       S7 (S05, S06): derived dose / standardised variables used in results
                            carry a declared unit and a passed plausibility check.
imputation_pooled           S8 (S05, S06): analyses of multiply imputed data are pooled (m,
                            pooling method, df recorded) or the single imputed dataset is declared
                            with a reason and a Methods sentence.
"""
from __future__ import annotations

import json
import re

from . import Ctx, Result, check

V = (1, 23, 0)


def since_1230(ctx: Ctx) -> bool:
    from ..state import pin_for, version_tuple
    try:
        return version_tuple(pin_for(ctx.state, getattr(ctx.stage, "id", None))) >= V
    except Exception:  # noqa: BLE001
        return True


def _pinned(name: str) -> Result:
    return Result(True, name, "applies from engine 1.23.0 (`wf migrate --yes`); paper pinned "
                              "earlier")


def _results(ctx: Ctx) -> list[tuple[str, object]]:
    out = []
    for p in sorted(ctx.p("03_analysis/results").glob("*.json")):
        try:
            out.append((p.name, json.loads(p.read_text(encoding="utf-8"))))
        except (OSError, ValueError):
            continue
    return out


def _walk(obj, fn, path: str = "") -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "environment":
                continue
            fn(k, v, path)
            _walk(v, fn, f"{path}.{k}" if path else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _walk(v, fn, f"{path}[{i}]")


# ------------------------------------------------------------------------------ S1
@check("publishability_checkpoint")
def publishability_checkpoint(ctx: Ctx) -> Result:
    name = "publishability_checkpoint"
    if not since_1230(ctx):
        return _pinned(name)
    from .. import publishability as pb
    stage = str(getattr(ctx.stage, "id", ""))[:3]
    if stage not in pb.STAGES:
        return Result(True, name, f"no publishability checkpoint at {stage}")
    probs = pb.problems(ctx.project, stage)
    if probs:
        return Result(False, name, "; ".join(probs[:5]),
                      ["Report the verdict to the user in Chinese at once (the command prints "
                       "the lines); GO continues without a question, CONDITIONAL/NO-GO ask ONE "
                       "question with a recommendation."])
    e = pb.load(ctx.project)["checkpoints"][stage]
    tail = "" if e["verdict"] == "GO" else f"; user: {e['user_decision']['choice']}"
    return Result(True, name, f"{stage}: {e['verdict']}, {e['article_type']}{tail}")


# ------------------------------------------------------------------------------ S7
DERIVED_KEY = re.compile(r"(?i)(?:per_?kg|mg_?kg|_kg_|_kg$|per_?bsa|_m2(?:_|$)|\bmme\b|^mme|_mme|"
                         r"\bddd\b|_ddd|equivalent|_equiv|standardi[sz]ed_dose|cumulative_dose|"
                         r"daily_dose|dose_per)")


@check("derived_units_checked")
def derived_units_checked(ctx: Ctx) -> Result:
    name = "derived_units_checked"
    if not since_1230(ctx):
        return _pinned(name)
    declared: dict[str, dict] = {}
    probs: list[str] = []
    keys: dict[str, str] = {}
    for fname, data in _results(ctx):
        blk = data.get("derived_variables") if isinstance(data, dict) else None
        if isinstance(blk, dict):
            for var, rec in blk.items():
                declared[var.casefold()] = rec if isinstance(rec, dict) else {}
                if not isinstance(rec, dict) or not str(rec.get("unit", "")).strip():
                    probs.append(f"{fname}: derived variable '{var}' has no unit")
                elif rec.get("range_check") != "passed":
                    probs.append(f"{fname}: derived variable '{var}' did not pass its plausibility "
                                 f"range {rec.get('plausible_range')}")

        def seen(k, _v, path, fname=fname):
            if k != "derived_variables" and DERIVED_KEY.search(k) and not path.startswith(
                    "derived_variables"):
                keys.setdefault(k, f"{fname}:{path + '.' if path else ''}{k}")
        _walk(data, seen)
    undeclared = [loc for k, loc in keys.items()
                  if not any(d in k.casefold() or k.casefold() in d for d in declared)]
    probs += [f"{loc}: derived dose/standardised value without a declared unit and range check"
              for loc in undeclared[:8]]
    if probs:
        return Result(False, name, "; ".join(probs[:8]),
                      ["Derive it with analysis.units (Python) or tools/R/medunits.R: "
                       "per_body_weight()/convert() and derived(name, values, unit, derivation, "
                       "plausible=(low, high)); put derived_block(...) into write_results(). "
                       "Factors only from reference/conversion_factors.json."])
    return Result(True, name, f"{len(declared)} derived variable(s) with unit and passed range "
                              "check; no undeclared dose/standardised value in the results")


# ------------------------------------------------------------------------------ S8
IMPUTE_CODE = re.compile(r"\bmice\s*::\s*mice\b|\bmice\s*\(|IterativeImputer|KNNImputer|"
                         r"\bmissForest\b|\bamelia\s*\(|\bmiceforest\b|statsmodels\.imputation|"
                         r"\bMICEData\b|\baregImpute\b|\bjomo\s*\(|\bmitml\b|"
                         r"\bmultiple[ _]imputation\b", re.I)
FIRST_ONLY = re.compile(r"\bcomplete\s*\(\s*\w+\s*,\s*(?:action\s*=\s*)?1L?\s*\)|"
                        r"\.complete\(\s*1\s*\)|imputed\[\s*0\s*\]|imputations\[\s*0\s*\]",
                        re.I)


@check("imputation_pooled")
def imputation_pooled(ctx: Ctx) -> Result:
    name = "imputation_pooled"
    if not since_1230(ctx):
        return _pinned(name)
    uses, first = [], []
    for p in sorted(ctx.p("03_analysis/code").rglob("*")):
        if p.is_file() and p.suffix.casefold() in (".py", ".r"):
            text = re.sub(r"(?m)#.*$", "", p.read_text(encoding="utf-8", errors="replace"))
            rel = p.relative_to(ctx.project).as_posix()
            if IMPUTE_CODE.search(text):
                uses.append(rel)
            if FIRST_ONLY.search(text):
                first.append(rel)
    blocks = []
    for fname, data in _results(ctx):
        def grab(k, v, _path, fname=fname):
            if k == "imputation" and isinstance(v, dict):
                blocks.append((fname, v))
        _walk(data, grab)
    probs = []
    single = False
    for fname, b in blocks:
        if b.get("m_used") == 1:
            single = True
            if len(str(b.get("reason", "")).strip()) < 20 or not b.get("methods_sentence"):
                probs.append(f"{fname}: single imputed dataset without a declared reason and "
                             "Methods sentence (single_imputation(reason))")
        elif not (isinstance(b.get("m"), int) and b["m"] >= 2 and b.get("pooling") and "df" in b):
            probs.append(f"{fname}: imputation block lacks m >= 2, the pooling method or df")
    if uses and not blocks:
        probs.append("multiple imputation in " + ", ".join(uses[:3]) + " but no results JSON "
                     "records m, the pooling method and df")
    if first and uses and not single:
        probs.append("only the first imputed dataset is analysed in " + ", ".join(first[:3])
                     + " (pool across all imputations, or declare single_imputation(reason))")
    if probs:
        return Result(False, name, "; ".join(probs[:6]),
                      ["Pool by default: Python analysis.imputation.rubin()/bootstrap_within() + "
                       "imputation_block(); R tools/R/medimpute.R medpaper_pool() (mice::pool) + "
                       "medpaper_imputation_block(). One imputed dataset only with "
                       "single_imputation(reason) - its sentence goes into the Methods."])
    if not uses and not blocks:
        return Result(True, name, "no multiple imputation in the analysis")
    return Result(True, name, f"{len(blocks)} imputation record(s): pooled across imputations"
                  + ("; single-dataset use declared with a Methods sentence" if single else ""))
