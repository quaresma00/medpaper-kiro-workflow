"""1.16.0 (N1): a Results/Abstract number must not be put into another result's context.

numbers_have_provenance proves that a number exists in 03_analysis/results/*.json; it cannot see
that "HR 1.52 (1.21-1.90) at 1 year in dialysis patients" was rewritten as "OR 1.52 (1.21-1.90)
at 5 years in transplant recipients". This module reads the structured facts the analysis wrote
(the same context fields the 1.14 writer bundle uses: population/cohort, comparison exposure vs
reference, outcome, measure, time point/window), finds the fact(s) carrying a sentence's numbers
and compares only EXPLICIT context tokens in that sentence:

* measure-type tokens (HR, OR, RR, IRR, ROR, PRR, AUC, 'hazard ratio', 'odds ratio', ...),
* time-window expressions ('1-year', '30-day', 'at 5 years', 'within 30 days'),
* display-dictionary labels (and their abbreviations) used for the population, exposure,
  comparator and outcome roles.

It is deliberately not clinical NLP. A sentence fails only on an explicit contradiction: it names
a different measure, time window or dictionary label for a role than EVERY fact carrying its
numbers, and those numbers identify the fact well (two numbers, or one decimal). Missing context
tokens never fail. Sentences that combine several facts, name extra labels next to the right ones
or rest on a single integer are listed for the reviewer (wfcore/reviewitems.py) instead.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

CONTEXT_KEYS = {
    "population": ("population", "cohort", "sample", "subgroup", "stratum", "set"),
    "comparison": ("comparison", "contrast", "exposure", "term", "group", "arm", "treatment"),
    "reference": ("reference", "comparator", "ref", "versus", "vs"),
    "outcome": ("outcome", "endpoint", "event"),
    "measure": ("measure", "scale", "metric", "statistic", "effect_measure", "type"),
    "time": ("time", "timepoint", "time_point", "window", "horizon", "follow_up", "period",
             "landmark"),
}
LEVEL_KEYS = {"ci_level", "conf_level", "conf.level", "confidence_level", "level", "alpha"}
SKIP_KEYS = {"environment", "meta", "metadata", "provenance", "script", "inputs", "outputs",
             "schema", "seed", "written_at"}
MEASURE_KEYS = {"hr": "hr", "ahr": "hr", "or": "or", "aor": "or", "rr": "rr", "irr": "irr",
                "ror": "ror", "prr": "prr", "auc": "auc", "shr": "shr", "c_index": "auc",
                "cindex": "auc", "c_statistic": "auc"}
# (code, acronym pattern - case-sensitive, phrase pattern - case-insensitive); longest first.
MEASURES = (
    ("ror", r"RORs?", r"reporting odds ratios?"),
    ("prr", r"PRRs?", r"proportional reporting ratios?"),
    ("irr", r"IRRs?", r"incidence rate ratios?"),
    ("shr", r"sHRs?|SHRs?", r"subdistribution hazard ratios?"),
    ("hr", r"a?HRs?", r"hazard ratios?"),
    ("or", r"a?ORs?", r"odds ratios?"),
    ("rr", r"a?RRs?", r"relative risks?|risk ratios?"),
    ("auc", r"AUCs?|AUROCs?", r"area under the (?:receiver operating characteristic )?curves?|"
                              r"c[- ]statistics?|c[- ]index"),
)
_B, _E = r"(?<![\w-])", r"(?![\w-])"
_MEASURE_RE = [(code, re.compile(f"{_B}(?:{acr}){_E}"), re.compile(f"{_B}(?:{phr}){_E}", re.I))
               for code, acr, phr in MEASURES]
_UNIT_DAYS = {"year": 365.25, "yr": 365.25, "y": 365.25, "month": 30.44, "mo": 30.44,
              "m": 30.44, "week": 7.0, "wk": 7.0, "w": 7.0, "day": 1.0, "d": 1.0}
_TIME_SENT = (re.compile(r"(?<![\w.])(\d+)-(year|month|week|day)s?\b", re.I),
              re.compile(r"\b(?:at|within|by|after)\s+(\d+)\s+(years?|months?|weeks?|days?)\b",
                         re.I))
_TIME_FACT = re.compile(r"(\d+(?:\.\d+)?)\s*-?\s*(years?|yrs?|y|months?|mo|m|weeks?|wks?|w|"
                        r"days?|d)\b", re.I)
_CI_LEVEL = re.compile(r"(?<![\w.])(?:90|95|99)\s?%\s*(?:CI|CrI|confidence|credible)", re.I)
_PROTECT = re.compile(r"\b(?:vs|e\.g|i\.e|approx|cf|ca|al)\.", re.I)
_SENT = re.compile(r"(?<=[.!?;])\s+(?=[A-Z(])")


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def norm_measure(value) -> str | None:
    s = str(value or "").strip()
    if not s:
        return None
    key = s.casefold().replace(".", "_").replace("-", "_")
    if key in MEASURE_KEYS:
        return MEASURE_KEYS[key]
    for code, acr, phr in _MEASURE_RE:
        if phr.search(s) or re.search(f"{_B}(?:{acr.pattern}){_E}", s, re.I):
            return code
    return None


def _days(n: float, unit: str) -> float | None:
    u = unit.casefold().rstrip("s") if len(unit) > 2 else unit.casefold()
    return n * _UNIT_DAYS[u] if u in _UNIT_DAYS else None


def norm_time(value) -> float | None:
    m = _TIME_FACT.search(str(value or ""))
    return _days(float(m.group(1)), m.group(2)) if m else None


def _same_time(a: float, b: float) -> bool:
    return abs(a - b) <= 0.05 * max(a, b)


# ---------------------------------------------------------------- display dictionary
def vocabulary(project: Path) -> tuple[dict[str, str], dict[str, str], dict[str, set[str]]]:
    """(internal name -> label, label/abbreviation text -> label, label -> declared roles)."""
    from . import clinical
    data = clinical.dictionary(project)
    names = clinical.internal_names(data)
    surface: dict[str, str] = {}
    roles: dict[str, set[str]] = {}
    for t in (data or {}).get("terms", []) or []:
        if not isinstance(t, dict):
            continue
        label = str(t.get("label", "")).strip()
        if len(label) < 3:
            continue
        surface[label] = label
        ab = str(t.get("abbreviation", "") or "").strip()
        if ab:
            surface[ab] = label
        role = str(t.get("role", "") or "").strip().casefold()
        role = {"comparator": "reference", "exposure": "comparison"}.get(role, role)
        if role in ("population", "comparison", "reference", "outcome"):
            roles.setdefault(label, set()).add(role)
    return names, surface, roles


def _label(value, names: dict[str, str], labels_ci: dict[str, str]) -> str | None:
    s = str(value or "").strip()
    if not s:
        return None
    s = names.get(s, s)
    return labels_ci.get(s.casefold())


# ---------------------------------------------------------------- facts
def facts(project: Path) -> list[dict]:
    """One record per estimate: its numbers and its labelled context."""
    from .checks.numbers import _norm
    names, surface, _roles = vocabulary(project)
    labels_ci = {lab.casefold(): lab for lab in set(surface.values())}
    out: list[dict] = []

    def emit(numbers: set, measure, ctx: dict, where: str) -> None:
        if not numbers:
            return
        floats = set()
        for s in numbers:
            try:
                floats.add(float(s))
            except ValueError:
                pass
        out.append({
            "where": where, "floats": floats, "strings": set(numbers),
            "measure": norm_measure(measure),
            "time": norm_time(ctx.get("time")),
            "population": _label(ctx.get("population"), names, labels_ci),
            "comparison": _label(ctx.get("comparison"), names, labels_ci),
            "reference": _label(ctx.get("reference"), names, labels_ci),
            "outcome": _label(ctx.get("outcome"), names, labels_ci),
        })

    def walk(obj, ctx: dict, where: str, depth: int = 0) -> None:
        if depth > 10:
            return
        if isinstance(obj, list):
            for i, v in enumerate(obj[:5000]):
                walk(v, ctx, f"{where}[{i}]", depth + 1)
            return
        if not isinstance(obj, dict):
            return
        own = {}
        for slot, keys in CONTEXT_KEYS.items():
            for k in keys:
                v = obj.get(k)
                if isinstance(v, str) and v.strip():
                    own[slot] = v
                    break
        merged = {**ctx, **own}
        groups: dict[str, set] = {}
        for k, v in obj.items():
            kk = str(k).casefold()
            if not _num(v) or kk in LEVEL_KEYS:
                continue
            head = kk.split("_")[0] if kk not in MEASURE_KEYS else kk
            head = head if head in MEASURE_KEYS else ""
            groups.setdefault(head, set()).add(_norm(v))
        heads = [h for h in groups if h]
        for h in heads:
            emit(groups[h] | groups.get("", set()), h, merged, where)
        if not heads and groups.get(""):
            emit(groups[""], merged.get("measure"), merged, where)
        for k, v in obj.items():
            if isinstance(v, (dict, list)) and str(k).casefold() not in SKIP_KEYS:
                walk(v, merged, f"{where}.{k}", depth + 1)

    for p in sorted((Path(project) / "03_analysis/results").glob("*.json")):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        walk(doc, {}, p.stem)
    return out


# ---------------------------------------------------------------- sentences
def _labels_in(text: str, surface: dict[str, str]) -> dict[str, list[tuple[int, int]]]:
    """label -> spans where it (or its abbreviation) appears; longest surface form first."""
    found: dict[str, list[tuple[int, int]]] = {}
    work = text
    for form in sorted(surface, key=len, reverse=True):
        flags = 0 if (form.isupper() or len(form) <= 4) else re.I
        rx = re.compile(f"{_B}{re.escape(form)}(?:s|es)?{_E}", flags)
        for m in rx.finditer(work):
            found.setdefault(surface[form], []).append(m.span())
        work = rx.sub(lambda m: " " * len(m.group(0)), work)
    return found


def _measures_in(text: str) -> set[str]:
    out, work = set(), text
    for code, acr, phr in _MEASURE_RE:
        for rx in (phr, acr):
            if rx.search(work):
                out.add(code)
                work = rx.sub(lambda m: " " * len(m.group(0)), work)
    return out


def _times_in(text: str) -> tuple[set[float], list[tuple[int, int]]]:
    vals, spans = set(), []
    for rx in _TIME_SENT:
        for m in rx.finditer(text):
            d = _days(float(m.group(1)), m.group(2))
            if d is not None:
                vals.add(d)
                spans.append(m.span())
    return vals, spans


def _role_status(sentence_vals: set, fact_vals: set) -> str:
    """'ok' | 'contradiction' | 'ambiguous' for one role of one fact."""
    if not sentence_vals or not fact_vals:
        return "ok"  # missing context never fails; a fact without the field is not judged
    hit = sentence_vals & fact_vals
    if not hit:
        return "contradiction"
    return "ok" if sentence_vals <= fact_vals else "ambiguous"


def _time_status(sent: set[float], fact: float | None) -> str:
    if not sent or fact is None:
        return "ok"
    hit = [s for s in sent if _same_time(s, fact)]
    if not hit:
        return "contradiction"
    return "ok" if len(hit) == len(sent) else "ambiguous"


def judge(segment: str, fact: dict, surface: dict[str, str], vocab: dict[str, set[str]]
          ) -> tuple[str, list[str]]:
    """Status of one fact against the explicit context tokens of one sentence segment."""
    found = _labels_in(segment, surface)
    status, why = "ok", []
    rank = {"ok": 0, "ambiguous": 1, "contradiction": 2}

    def worse(s: str, what: str) -> None:
        nonlocal status
        if s == "ok":
            return
        why.append(f"{what} {s}")
        if rank[s] > rank[status]:
            status = s

    measures = _measures_in(segment)
    if fact["measure"]:
        worse(_role_status(measures, {fact["measure"]}), f"measure {sorted(measures)} vs "
                                                         f"{fact['measure']}:")
    times, _spans = _times_in(segment)
    worse(_time_status(times, fact["time"]), "time window:")
    for role in ("population", "outcome"):
        seen = {lab for lab in found if role in vocab.get(lab, set())}
        if fact[role]:
            worse(_role_status(seen, {fact[role]}), f"{role} {sorted(seen)} vs {fact[role]}:")
    pair = {x for x in (fact["comparison"], fact["reference"]) if x}
    seen = {lab for lab in found if vocab.get(lab, set()) & {"comparison", "reference"}}
    if fact["comparison"] and seen:
        extra = seen - pair
        if not extra:
            pass
        elif fact["comparison"] not in seen:
            worse("contradiction", f"comparison {sorted(seen)} vs {sorted(pair)}:")
        else:
            worse("ambiguous", f"comparison {sorted(seen)} vs {sorted(pair)}:")
    return status, why


def check_text(project: Path, text: str, lines: set[int] | None = None,
               fact_list: list[dict] | None = None) -> tuple[list[str], list[str]]:
    """-> (contradictions that fail, sentences listed for the reviewer)."""
    from .checks.numbers import NUM_RE, THOUSANDS_RE, _matches, _scrub
    fl = facts(project) if fact_list is None else fact_list
    if not fl:
        return [], []
    _names, surface, declared = vocabulary(project)
    vocab: dict[str, set[str]] = {lab: set(r) for lab, r in declared.items()}
    for f in fl:
        for role in ("population", "comparison", "reference", "outcome"):
            if f[role]:
                vocab.setdefault(f[role], set()).add(role)
    fails, review = [], []
    for lineno, raw in enumerate(_scrub(text).splitlines(), start=1):
        if lines is not None and lineno not in lines:
            continue
        line = _PROTECT.sub(lambda m: m.group(0)[:-1] + "\u2024", THOUSANDS_RE.sub("", raw))
        for sent in _SENT.split(line):
            blank = _CI_LEVEL.sub(lambda m: " " * len(m.group(0)), sent)
            _t, tspans = _times_in(blank)
            for a, b in tspans:
                blank = blank[:a] + " " * (b - a) + blank[b:]
            tokens = []
            for m in NUM_RE.finditer(blank):
                tok = m.group(1)
                small = "." not in tok and abs(float(tok.replace("\u2212", "-"))) <= 10
                if small:
                    continue
                carrying = [i for i, f in enumerate(fl) if _matches(tok, f["floats"], f["strings"])]
                if carrying:
                    tokens.append((m.start(), m.end(), tok, set(carrying)))
            if not tokens:
                continue
            groups: list[dict] = []
            for start, end, tok, carry in tokens:
                if groups and groups[-1]["cand"] & carry:
                    g = groups[-1]
                    g["cand"] &= carry
                    g["end"], g["toks"] = end, g["toks"] + [tok]
                else:
                    groups.append({"cand": set(carry), "start": start, "end": end, "toks": [tok]})
            shown = sent.strip().replace("\u2024", ".")
            shown = shown if len(shown) <= 220 else shown[:217] + "..."
            if len(groups) == 1:
                g = groups[0]
                res = [judge(sent, fl[i], surface, vocab) for i in sorted(g["cand"])]
                if any(s == "ok" for s, _ in res):
                    continue
                strong = len(g["toks"]) >= 2 or any("." in t for t in g["toks"])
                why = "; ".join(dict.fromkeys(w for _, ws in res for w in ws))[:240]
                if all(s == "contradiction" for s, _ in res) and strong:
                    fails.append(f"line {lineno}: '{shown}' -> {why}")
                else:
                    review.append(f"line {lineno}: '{shown}' -> {why}")
                continue
            # several facts in one sentence: each judged on its own stretch of the sentence
            prev, bad = 0, []
            for k, g in enumerate(groups):
                end = len(sent) if k == len(groups) - 1 else g["end"]
                seg = sent[prev:end]
                prev = end
                res = [judge(seg, fl[i], surface, vocab) for i in sorted(g["cand"])]
                if not any(s == "ok" for s, _ in res):
                    bad += [w for _, ws in res for w in ws]
            if bad:
                review.append(f"line {lineno}: '{shown}' (combines {len(groups)} results) -> "
                              + "; ".join(dict.fromkeys(bad))[:240])
    return fails, review
