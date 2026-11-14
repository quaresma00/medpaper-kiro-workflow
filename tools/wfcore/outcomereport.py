"""1.25.1: confident writing never hides an unfavourable or null result, a limitation or the
uncertainty of an estimate.

Deterministic helpers for four gates (checks/v1251.py; effects_with_intervals in v1100.py):

    prespecified_outcomes_reported  every primary and secondary outcome of 01_protocol/idea.json
                                    (outcomes.primary / outcomes.secondary) is named in a Results
                                    sentence that carries its interval or cites the table/figure
                                    holding it (a supplementary display counts); the primary
                                    outcome is named in the Abstract results, whatever its
                                    direction.
    primary_first                   the first finding sentence of the Abstract results and the
                                    Discussion's first paragraph name the primary outcome.
    estimates_have_intervals        an effect estimate (HR, OR, RR, IRR, ROR, PRR, IC/IC025, MD,
                                    SMD, beta, AUC, spelled out or abbreviated, followed by its
                                    value) carries a CI or credible interval in the same
                                    sentence; counts, percentages and P values are not effect
                                    estimates.
    limitations_present             the Discussion has a limitations paragraph with at least two
                                    specific limitations and the design's essential caveat
                                    (reference/design_caveats.toml).

An outcome is recognised by its protocol name or the display-dictionary label, abbreviation or
aliases of the matching entry. The blocking parts apply to papers on 1.25.1+ (`wf migrate
--yes`); a paper pinned earlier gets warnings. `edit_regressions` lets the medical editor's
polished text through only when none of these checks that passed before the edit fails after it.
"""
from __future__ import annotations

import json
import re
import tomllib
from functools import lru_cache
from pathlib import Path

V = (1, 25, 1)
SINCE = "1.25.1"
IDEA = "01_protocol/idea.json"
CAVEATS = "design_caveats.toml"

_STOP = set("""the and for with that this from were was are any all of in on at to by or an a
per within after before during between among rate rates risk incidence""".split())
_FENCE = re.compile(r"```.*?```|<!--.*?-->", re.S)
DISPLAY_RE = re.compile(
    r"(?i)\b(?:(?:e|Supplementa(?:ry|l)\s+)?(?:Tables?|Figs?\.?|Figures?)\s*S?\d+[A-Za-z]?"
    r"|Online\s+Resources?\s+\d+|ESM\s*_?\d+|Additional\s+files?\s+\d+"
    r"|Supplementa(?:ry|l)\s+(?:Data|Materials?|Files?|Appendix)(?:\s+S?\d+)?)")
INTERVAL_RE = re.compile(r"\b(?:CIs?|CrIs?|UIs?|IC025|IC0\.025)\b|confidence\s+intervals?|"
                         r"credible\s+intervals?|uncertainty\s+intervals?|compatibility\s+"
                         r"intervals?", re.I)
_NUM = r"[-\u2212\u2013]?\d+(?:\.\d+)?"
_PER = (r"(?:per\s+(?:1|one|10|an?)[- ]?(?:unit|SD|standard[- ]deviation|point|year|kg|mmol)s?"
        r"(?:\s+(?:increase|increment|higher|lower|decrease|rise))?(?:\s+in\s+[^0-9;,()]{1,40}?)?"
        r"[\s,:=]*)?")
_SEP = (r"(?:\s*\((?:95%\s*)?(?:CI|CrI)\)\s*)?(?:\s+(?:for|of)\s+[A-Za-z][^0-9;()]{0,50}?)?"
        r"[\s,:=]*(?:(?:of|was|were|is)\s+)?" + _PER)
ABBR = r"(?:a|adjusted\s+|s)?(?:HR|OR|RR|IRR|ROR|PRR|SHR|IC025|IC|MD|SMD|WMD|AUC|AUROC|AUROCs?|C-statistic|\u03b2)s?"
WORDS = (r"hazard\s+ratios?|odds\s+ratios?|risk\s+ratios?|relative\s+risks?|rate\s+ratios?|"
         r"information\s+components?|(?:standardi[sz]ed\s+|weighted\s+)?mean\s+differences?|"
         r"area\s+under\s+the\s+(?:receiver[- ]operating[- ]characteristic\s+)?curve|beta|"
         r"regression\s+coefficients?")
EST_ABBR_RE = re.compile(r"(?<![\w-])(" + ABBR + r")(?![\w-])" + _SEP + r"(?:\s*\w+\s*=\s*)?(" + _NUM + r")(?![\w])")
EST_WORD_RE = re.compile(r"(?i)\b(" + WORDS + r")\b" + _SEP + r"(" + _NUM + r")(?![\w])")
RATIO = re.compile(r"(?i)HR|OR|RR|IRR|ROR|PRR|SHR|ratio|relative\s+risk")
DIFF = re.compile(r"(?i)MD|SMD|WMD|\u03b2|beta|difference|coefficient")
CI_BOUNDS = re.compile(r"(?i)(?:CI|CrI|interval)s?\b[^0-9\-\u2212\u2013]{0,12}(" + _NUM + r")\s*"
                       r"(?:-|\u2013|\u2014|to|,|;)\s*(" + _NUM + r")")
NULL_WORDS = re.compile(
    r"(?i)\bno\s+(?:clear|significant|statistically\s+significant|meaningful|material|"
    r"evidence\s+of\s+(?:an?\s+)?|important\s+)?(?:difference|association|effect|benefit|"
    r"increase|reduction|signal|change)s?\b|\b(?:was|were)\s+not\s+(?:significantly\s+)?"
    r"(?:associated|different|reduced|increased|lower|higher)\b|\bdid\s+not\s+(?:differ|"
    r"reduce|increase|change|improve)\b|\bnot\s+statistically\s+significant\b|\bsimilar\s+in\s+"
    r"both\b")
LIM_OPENER = re.compile(
    r"(?i)^(?:however,?\s+)?(?:this|our|the\s+present|the\s+current)\s+(?:study|analysis|work|"
    r"research)\s+(?:also\s+)?(?:has|had|have)\s+(?:several|some|a\s+few|potential|certain|"
    r"a\s+number\s+of|important|main)?\s*(?:important\s+)?limitations?\b[^.]*\.?$"
    r"|^(?:several|some|a\s+few|there\s+are\s+(?:several|some))\s+limitations?\b[^.]*\.?$"
    r"|^(?:the\s+)?(?:results|findings)\s+should\s+be\s+interpreted\s+with\s+caution\.?$")
STRENGTH = re.compile(r"(?i)\bstrengths?\b")


# ------------------------------------------------------------------ release policy
def since_1251_project(project: Path | None, stage: str | None = None) -> bool:
    """A paper created on 1.25.1+, migrated, or after a journal switch for S20-S25."""
    from .state import version_tuple
    if project is None:
        return True
    try:
        st = json.loads((Path(project) / ".wf/state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return True
    if not isinstance(st, dict):
        return True
    pin = version_tuple(str(st.get("engine_pin") or st.get("pipeline_version") or "0"))
    jp = st.get("journal_gate_pin") or {}
    if stage and stage in (jp.get("stages") or []):
        pin = max(pin, version_tuple(str(jp.get("version", "0"))))
    return pin >= V


def since_1251(ctx) -> bool:
    from .state import pin_for, version_tuple
    try:
        return version_tuple(pin_for(ctx.state, getattr(ctx.stage, "id", None))) >= V
    except Exception:  # noqa: BLE001
        return True


# ------------------------------------------------------------------ text helpers
def _norm(s: str) -> str:
    return " " + re.sub(r"[^0-9a-z\u03b2]+", " ", str(s).casefold()).strip() + " "


def _tokens(s: str) -> set[str]:
    return {w.rstrip("s") for w in _norm(s).split() if len(w) >= 3 and w not in _STOP}


def clean(text: str) -> str:
    text = _FENCE.sub(" ", text or "")
    keep = [ln for ln in text.splitlines()
            if not re.match(r"\s{0,3}#{1,6}\s", ln) and not ln.lstrip().startswith("|")]
    return "\n".join(keep)


def paragraphs(text: str) -> list[str]:
    return [" ".join(p.split()) for p in re.split(r"\n\s*\n", clean(text)) if p.strip()]


def sentences(text: str) -> list[str]:
    out = []
    for p in paragraphs(text):
        out += [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z(\[\u03b2])", p) if s.strip()]
    return out


def has_interval(s: str) -> bool:
    return bool(INTERVAL_RE.search(s))


def estimates(s: str) -> list[tuple[str, str]]:
    """(measure, value) of every effect estimate in a sentence."""
    out = [(m.group(1), m.group(2)) for m in EST_ABBR_RE.finditer(s)]
    out += [(m.group(1), m.group(2)) for m in EST_WORD_RE.finditer(s)]
    return out


def estimates_without_interval(text: str) -> list[str]:
    """Sentences reporting an effect estimate with no CI / credible interval."""
    return [s for s in sentences(text) if estimates(s) and not has_interval(s)]


# ------------------------------------------------------------------ outcomes
def _json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _names(v) -> list[str]:
    if isinstance(v, str):
        return [v] if v.strip() else []
    if isinstance(v, dict):
        n = str(v.get("name") or v.get("label") or "").strip()
        return [n] if n else []
    if isinstance(v, list):
        return [n for x in v for n in _names(x)]
    return []


def _dict_terms(project: Path) -> list[dict]:
    data = _json(Path(project) / "01_protocol/display_dictionary.json")
    if not isinstance(data, dict):
        return []
    return [t for t in (data.get("terms") or data.get("entries") or []) if isinstance(t, dict)]


def _terms(name: str, entries: list[dict]) -> list[str]:
    out = {name}
    for t in entries:
        names = [t.get("internal"), t.get("label"), t.get("abbreviation"), *(t.get("aliases") or [])]
        names = [str(x).strip() for x in names if str(x or "").strip()]
        if any(_norm(x) == _norm(name) for x in names):
            out |= set(names)
    return sorted(x for x in out if _norm(x).strip())


def declared_outcomes(project: Path) -> dict[str, list[dict]]:
    """{'primary': [{name, terms}], 'secondary': [...]} from idea.json (the protocol's structured
    fields); the protocol's 'Primary outcome:' line when idea.json names no primary outcome."""
    project = Path(project)
    idea = _json(project / IDEA)
    oc = idea.get("outcomes") if isinstance(idea, dict) else None
    prim, sec = [], []
    if isinstance(oc, dict):
        prim, sec = _names(oc.get("primary")), _names(oc.get("secondary"))
    elif oc is not None:
        prim = _names(oc)
    if not prim:
        from . import decisionrecord
        for rel in (decisionrecord.FINAL, decisionrecord.V1):
            try:
                val = decisionrecord.extract((project / rel).read_text(encoding="utf-8")).get(
                    "Primary outcome", "")
            except OSError:
                val = ""
            if val:
                prim = [" ".join(re.split(r"[,;(:]", val)[0].split()[:6])]
                break
    entries = _dict_terms(project)
    seen: set[str] = set()

    def pack(names):
        res = []
        for n in names:
            if _norm(n) in seen:
                continue
            seen.add(_norm(n))
            res.append({"name": n, "terms": _terms(n, entries)})
        return res
    p = pack(prim)
    return {"primary": p, "secondary": pack(sec)}


def mentions(text: str, terms: list[str]) -> bool:
    nt = _norm(text)
    tt = _tokens(text)
    for term in terms:
        n = _norm(term)
        if n.strip() and n in nt:
            return True
        tok = _tokens(term)
        if tok and tok <= tt:
            return True
    return False


def outcome_problems(project: Path, results: str, abstract: str | None = None) -> list[tuple[str, str]]:
    """(key, message) for each pre-specified outcome missing from the Results (or its interval /
    display) and for a primary outcome missing from the Abstract results."""
    oc = declared_outcomes(project)
    sents = sentences(results)
    out = []
    for role in ("primary", "secondary"):
        for o in oc[role]:
            hits = [s for s in sents if mentions(s, o["terms"])]
            if not hits:
                out.append((f"results:{_norm(o['name']).strip()}",
                            f"{role} outcome '{o['name']}' is not reported in the Results (name it "
                            "with its estimate and 95% CI, or cite the table/figure that holds it)"))
            elif not any(has_interval(s) or DISPLAY_RE.search(s) for s in hits):
                out.append((f"interval:{_norm(o['name']).strip()}",
                            f"{role} outcome '{o['name']}' appears in the Results without its "
                            "interval or a table/figure citation: give estimate and 95% CI"))
    if abstract is not None and oc["primary"]:
        part = abstract_results(abstract)
        for o in oc["primary"]:
            if not mentions(part, o["terms"]):
                out.append((f"abstract:{_norm(o['name']).strip()}",
                            f"the Abstract results do not report the primary outcome "
                            f"'{o['name']}' (report it first, whatever its direction)"))
    return out


def abstract_results(raw: str) -> str:
    """The Results part of a structured abstract, else the whole abstract."""
    from .crosscheck import ABS_LABEL
    raw = re.sub(r"(?mi)^\**keywords?\**\s*:.*$", "", raw or "")
    labels = [m for m in ABS_LABEL.finditer(raw) if len(m.group(1).split()) <= 5]
    res = re.compile(r"(?i)^(?:results?|findings|main\s+(?:outcomes?|results)(?:\s+and\s+measures)?|"
                     r"measurements\s+and\s+main\s+results)$")
    other = re.compile(r"(?i)^(?:background|objectives?|aims?|purpose|introduction|methods?|"
                       r"design|setting|participants|context|importance|conclusions?|"
                       r"interpretation|relevance|funding|exposures?|interventions?)$")
    labels = [m for m in labels if res.match(m.group(1).strip()) or other.match(m.group(1).strip())]
    keep = []
    for i, m in enumerate(labels):
        if res.match(m.group(1).strip()):
            end = labels[i + 1].start() if i + 1 < len(labels) else len(raw)
            keep.append(raw[m.end():end])
    return "\n".join(keep) if keep else raw


def first_finding(abstract: str) -> str:
    sents = sentences(abstract_results(abstract))
    return next((s for s in sents if estimates(s) or has_interval(s)), sents[0] if sents else "")


def first_paragraph(discussion: str) -> str:
    paras = paragraphs(discussion)
    return paras[0] if paras else ""


def _is_null(s: str) -> bool:
    if NULL_WORDS.search(s):
        return True
    est = estimates(s)
    m = CI_BOUNDS.search(s)
    if not est or not m:
        return False
    try:
        lo, hi = (float(x.replace("\u2212", "-").replace("\u2013", "-")) for x in m.groups())
    except ValueError:
        return False
    lo, hi = min(lo, hi), max(lo, hi)
    measure = est[0][0]
    if re.match(r"(?i)IC|information", measure):
        return lo <= 0
    if RATIO.search(measure):
        return lo <= 1 <= hi
    if DIFF.search(measure):
        return lo <= 0 <= hi
    return False


def primary_is_null(project: Path, results: str) -> bool:
    oc = declared_outcomes(project)
    for o in oc["primary"]:
        hits = [s for s in sentences(results) if mentions(s, o["terms"])
                and (estimates(s) or has_interval(s) or NULL_WORDS.search(s))]
        if hits and _is_null(hits[0]):
            return True
    return False


def lead_problems(project: Path, abstract: str | None, discussion: str | None,
                  results: str = "") -> tuple[list[str], bool]:
    """(problems, a secondary result leads although the primary is null)."""
    oc = declared_outcomes(project)
    if not oc["primary"]:
        return [], False
    terms = [t for o in oc["primary"] for t in o["terms"]]
    sec_terms = [t for o in oc["secondary"] for t in o["terms"]]
    null = primary_is_null(project, results)
    probs, displaced = [], False
    for where, lead in (("first finding sentence of the Abstract results",
                         first_finding(abstract) if abstract else None),
                        ("first paragraph of the Discussion",
                         first_paragraph(discussion) if discussion else None)):
        if not lead or mentions(lead, terms):
            continue
        sec = bool(sec_terms and mentions(lead, sec_terms)) or bool(estimates(lead))
        probs.append(f"the {where} does not name the primary outcome "
                     f"'{oc['primary'][0]['name']}'" + (" (null primary; a secondary result leads)"
                                                        if null and sec else "")
                     + f": {lead[:90]!r}")
        displaced = displaced or (null and sec)
    return probs, displaced


# ------------------------------------------------------------------ limitations
@lru_cache(maxsize=1)
def caveat_table() -> dict:
    from . import paths
    try:
        return tomllib.loads((paths.reference_dir() / CAVEATS).read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def design_key(project: Path) -> str | None:
    idea = _json(Path(project) / IDEA)
    if not isinstance(idea, dict):
        return None
    sd = str(idea.get("study_design") or "").strip().casefold()
    ds = idea.get("data_source")
    names = [d.get("name") for d in (ds if isinstance(ds, list) else [ds]) if isinstance(d, dict)]
    blob = " ".join(str(x or "") for x in (idea.get("design"), idea.get("title_working"), *names))
    for key, row in caveat_table().items():
        if any(re.search(p, blob, re.I) for p in row.get("design_patterns", [])):
            return key
        if sd and sd in [str(x).casefold() for x in row.get("study_design", [])]:
            return key
    return None


def _is_lim(p: str) -> bool:
    return bool(re.search(r"\blimitations?\b|\blimited\s+by\b", p, re.I))


def limitation_problems(project: Path, discussion: str) -> list[tuple[str, str]]:
    paras = paragraphs(discussion)
    lim = [p for p in paras if _is_lim(p)]
    out = []
    if not lim:
        out.append(("no_paragraph", "the Discussion has no limitations paragraph: state the "
                                    "specific limitations plainly, once, each with the likely "
                                    "direction of bias"))
    else:
        sents = [s for p in lim for s in re.split(r"(?<=[.!?])\s+(?=[A-Z(\[])", p) if s.strip()]
        specific = [s for s in sents if len(s.split()) >= 8 and not LIM_OPENER.match(s.strip())
                    and not (STRENGTH.search(s) and not _is_lim(s))]
        if len(specific) < 2:
            out.append(("too_few", f"the limitations paragraph states {len(specific)} specific "
                                   "limitation(s) (at least 2): name each limitation and its "
                                   "likely effect on the estimates"))
    key = design_key(project)
    row = caveat_table().get(key or "", {})
    text = " ".join(paras)
    if row and not all(any(re.search(p, text, re.I) for p in g) for g in row.get("groups", [])):
        out.append((f"caveat:{key}", f"the Discussion lacks the essential {key.replace('_', ' ')} "
                                     f"caveat ({row.get('caveat', '')}); state it once, in the "
                                     "limitations paragraph"))
    return out


# ------------------------------------------------------------------ R3: editor regressions
def _scopes(text: str) -> dict[str, str]:
    from .crosscheck import scopes
    return scopes(text)


def _checks_for(project: Path, section: str, text: str) -> tuple[set[str], int]:
    keys: set[str] = set()
    n_est = 0
    if section in ("results", "abstract"):
        n_est = len(estimates_without_interval(text))
    if section == "results":
        keys |= {k for k, _m in outcome_problems(project, text) if not k.startswith("abstract:")}
    elif section == "abstract":
        keys |= {k for k, _m in outcome_problems(project, "", text) if k.startswith("abstract:")}
    elif section == "discussion":
        keys |= {k for k, _m in limitation_problems(project, text)}
    elif section == "manuscript":
        sc = _scopes(text)
        res, ab, dis = sc.get("results", ""), sc.get("abstract"), sc.get("discussion")
        n_est = len(estimates_without_interval(res)) + len(estimates_without_interval(ab or ""))
        if res.strip():
            keys |= {k for k, _m in outcome_problems(project, res, ab)}
        if dis and dis.strip():
            keys |= {k for k, _m in limitation_problems(project, dis)}
    return keys, n_est


def edit_regressions(project: Path, section: str, before: str, after: str) -> list[str]:
    """Checks a), c) and d) that passed on the text before the edit and fail after it."""
    try:
        k0, n0 = _checks_for(Path(project), section, before)
        k1, n1 = _checks_for(Path(project), section, after)
    except Exception:  # noqa: BLE001 - the fact check still runs
        return []
    out = [f"the edit removed or weakened reporting that passed before ({k})"
           for k in sorted(k1 - k0)]
    if n1 > n0:
        out.append(f"the edit separated {n1 - n0} effect estimate(s) from their confidence "
                   "interval")
    return out
