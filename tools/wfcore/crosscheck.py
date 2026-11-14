"""1.25.0 (B3): deterministic cross-section report of the assembled manuscript.

What a single section cannot show, in one report (`polish.py crosscheck`; gate
cross_section_consistent warns at S17 right after assembly and blocks the clear errors at S22):

    terminology      one population name across the manuscript (the 1.24 per-section
                     synonym_cycling, whole manuscript); the same count never called reports in
                     one place and patients/cases in another; display-dictionary labels only
    abbreviations    defined once at first use, separately in the abstract and the body: a
                     redefinition and a use before the definition BLOCK; defined but used once warns
    near-duplicates  Introduction vs Discussion and Methods vs Results sentences with a
                     content-word Jaccard >= 0.7 (warn)
    abstract-body    every number in the abstract's results/conclusion equals a value in the
                     Results text or the tables (BLOCK on a mismatch); the abstract and Discussion
                     conclusions go to the reviewer list (strength)
    style            spelling variant and P/p style (the existing lint rules)

No paper file is changed; the report is 07_manuscript/crosscheck_report.json (the journal copy's
folder once a variant is open).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

REL = "07_manuscript/crosscheck_report.json"
MS = "07_manuscript/full_manuscript.md"
JACCARD = 0.7
MIN_CONTENT_WORDS = 6
SCOPES = ("abstract", "introduction", "methods", "results", "discussion", "conclusion")
UNITS = {"reports": "reports", "report": "reports", "cases": "cases", "case": "cases",
         "patients": "patients", "patient": "patients", "participants": "participants",
         "participant": "participants"}
STOP = set("""a an and are as at be been being between both but by can could did do does for from
had has have in into is it its may might more most no not of on or our than that the their them
then there these they this those to was we were which while who with within without would also
such each other all any per after before during over under compared versus vs""".split())
STRONG = re.compile(r"(?i)\b(?:caus\w*|prevent\w*|should\s+be|must\s+be|recommend\w*|"
                    r"definitive\w*|prove[sd]?|establish\w*|effective(?:ly)?|safe\s+to|"
                    r"reduce[sd]?\s+the\s+risk|protect\w*)\b")
ABS_RESULTS = re.compile(r"(?i)^(?:results?|findings|conclusions?|interpretation|main\s+outcomes?"
                         r"(?:\s+and\s+measures)?|measurements\s+and\s+main\s+results)$")
ABS_LABEL = re.compile(r"(?m)^[ \t]*(?:#{2,6}[ \t]*)?(?:\*\*)?([A-Za-z][A-Za-z ]{2,40}?)(?:\*\*)?"
                       r"[ \t]*[:.]?(?:\*\*)?(?=[ \t]|$)")
ABS_CONCL = re.compile(r"(?ims)^[ \t]*(?:#{2,6}[ \t]*)?(?:\*\*)?conclusions?(?:\*\*)?[ \t]*[:.]?"
                       r"(?:\*\*)?[ \t]*(.+)\Z")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _pol():
    from .sectionpolish import _polish_module
    return _polish_module()


def _resolve(project: Path, rel: str) -> str:
    try:
        from . import scifreeze
        return scifreeze.resolve(Path(project), rel)
    except Exception:  # noqa: BLE001
        return rel


def scopes(text: str) -> dict[str, str]:
    """Level-1 sections of the manuscript (Conclusion(s) joins the Discussion)."""
    heads = list(re.finditer(r"(?m)^#\s+([^#\n].*)$", text))
    out: dict[str, str] = {}
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        name = m.group(1).strip().casefold()
        key = next((s for s in SCOPES if name.startswith(s)), "")
        if key == "conclusion":
            out["discussion_conclusion"] = text[m.end():end]
            key = "discussion"
        if key:
            out[key] = out.get(key, "") + "\n\n" + text[m.end():end]
    return out


def manuscript(project: Path) -> tuple[str, str]:
    rel = _resolve(project, MS)
    p = Path(project) / rel
    if p.is_file():
        return rel, p.read_text(encoding="utf-8", errors="replace")
    parts = []
    for name in ("abstract", "introduction", "methods", "results", "discussion"):
        q = Path(project) / _resolve(project, f"07_manuscript/{name}.md")
        if q.is_file():
            parts.append(f"# {name.title()}\n\n" + re.sub(r"(?m)^#\s+.*$", "", q.read_text(
                encoding="utf-8", errors="replace"), count=1))
    return "07_manuscript/<sections>", "\n\n".join(parts)


def _sentences(pol, raw: str) -> list[str]:
    return [s for p in pol._paras(raw) for s in pol._sents(p)]


def _content(s: str) -> set[str]:
    s = re.sub(r"\[[^\]]*\]|\([^)]*\d[^)]*\)", " ", s)
    return {w for w in re.findall(r"[a-z][a-z-]{2,}", s.lower()) if w not in STOP}


def near_duplicates(pol, sc: dict[str, str]) -> list[dict]:
    out = []
    for a, b in (("introduction", "discussion"), ("methods", "results")):
        sa = [(s, _content(s)) for s in _sentences(pol, sc.get(a, ""))]
        sb = [(s, _content(s)) for s in _sentences(pol, sc.get(b, ""))]
        for s1, w1 in sa:
            if len(w1) < MIN_CONTENT_WORDS:
                continue
            for s2, w2 in sb:
                if len(w2) < MIN_CONTENT_WORDS:
                    continue
                j = len(w1 & w2) / len(w1 | w2)
                if j >= JACCARD:
                    out.append({"kind": "near_duplicate", "detail":
                                f"{a.title()} and {b.title()} share a near-identical sentence "
                                f"(Jaccard {j:.2f}): {s1[:80]!r} / {s2[:80]!r} - say it once, "
                                "in its place"})
                    break
    return out


def terminology(pol, project: Path, sc: dict[str, str], text: str) -> list[dict]:
    out = []
    intro = pol._paras(sc.get("introduction", ""))
    joined = " ".join(([intro[-1]] if intro else []) + [pol.flow(sc.get(k, "")) for k in
                                                         ("abstract", "methods", "results",
                                                          "discussion")])
    used = {t: len(re.findall(rx, joined, re.I)) for t, rx in pol.POPULATION_TERMS.items()}
    many = {t: n for t, n in used.items() if n >= 2}
    if len(many) >= 3:
        out.append({"kind": "synonym_cycling_manuscript", "detail":
                    "one population, several names across the manuscript ("
                    + ", ".join(f"{t} x{n}" for t, n in many.items())
                    + ") - use one term throughout"})
    seen: dict[str, set[str]] = {}
    body = pol._normalize_for_facts(re.sub(r"\[[^\]]*@[^\]]*\]", " ", joined))
    for m in re.finditer(r"(?<![\w.])(\d{2,}(?:\.\d+)?)\s+(?:[A-Za-z-]+\s+){0,2}?"
                         r"(reports?|cases?|patients?|participants?)\b", body, re.I):
        seen.setdefault(m.group(1), set()).add(UNITS[m.group(2).lower()])
    for num, units in sorted(seen.items()):
        if len(units) > 1:
            out.append({"kind": "unit_interchanged", "detail":
                        f"the count {num} is called {' and '.join(sorted(units))} - reports, cases "
                        "and patients are different units, never interchanged"})
    try:
        from . import clinical
        for prob in clinical.label_problems(text, clinical.dictionary(Path(project)))[:6]:
            out.append({"kind": "dictionary_label", "detail": prob})
    except Exception:  # noqa: BLE001
        pass
    return out


def _abstract_parts(raw: str) -> tuple[str, bool]:
    """The abstract's results/conclusion text (structured abstract), else all of it."""
    raw = re.sub(r"(?mi)^\**keywords?\**\s*:.*$", "", raw)
    labels = list(ABS_LABEL.finditer(raw))
    labels = [m for m in labels if len(m.group(1).split()) <= 5 and (
        ABS_RESULTS.match(m.group(1).strip()) or re.match(
            r"(?i)^(?:background|objectives?|aims?|purpose|introduction|methods?|design|setting|"
            r"participants|context|importance)$", m.group(1).strip()))]
    if not labels:
        return raw, False
    keep = []
    for i, m in enumerate(labels):
        end = labels[i + 1].start() if i + 1 < len(labels) else len(raw)
        if ABS_RESULTS.match(m.group(1).strip()):
            keep.append(raw[m.end():end])
    return "\n".join(keep), True


def _numbers(pol, text: str) -> list[str]:
    from . import presentation
    t = pol.FENCE_RE.sub(" ", text)
    t = presentation.strip_non_facts(t)
    t = pol.ART_RE.sub(" ", pol.CITE_RE.sub(" ", t))
    t = re.sub(r"(?i)\b9[059]\s*%\s*(?=(?:CI|confidence|credible|uncertainty))", " ", t)
    t = re.sub(r"(?<=\d)[\u2009\u202f\u00a0](?=\d{3}(?!\d))", "", t)
    return pol.NUM_RE.findall(pol._normalize_for_facts(t))


def _table_text(project: Path) -> str:
    try:
        plan = json.loads((Path(project) / "01_protocol/artifact_plan.json").read_text(
            encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    out = []
    for g in ("main_tables", "supp_tables"):
        for e in plan.get(g) or []:
            f = Path(project) / str((e or {}).get("file", ""))
            if f.is_file() and f.suffix.lower() == ".xlsx":
                try:
                    from . import xlsxlite
                    book = xlsxlite.Workbook(f)
                    out += [v for s in book.sheets for v in s.values()]
                except Exception:  # noqa: BLE001 - malformed workbooks are reported elsewhere
                    pass
    return "\n".join(out)


def abstract_numbers(pol, project: Path, sc: dict[str, str]) -> list[dict]:
    part, structured = _abstract_parts(sc.get("abstract", ""))
    if not part.strip():
        return []
    pool_text = sc.get("results", "") + "\n" + _table_text(project)
    if not structured:  # background and design numbers cannot be told apart from results
        pool_text += "\n" + sc.get("methods", "") + "\n" + sc.get("introduction", "")
    pool = {float(x) for x in _numbers(pol, pool_text)}
    anywhere = {float(x) for x in _numbers(pol, "\n".join(sc.values()))}
    out, seen = [], set()
    for x in _numbers(pol, part):
        v = float(x)
        if v in pool or x in seen:
            continue
        if v.is_integer() and (1900 <= v <= 2100 or (v <= 10 and v in anywhere)):
            continue  # a calendar year or a small count stated elsewhere in the text
        seen.add(x)
        out.append({"kind": "abstract_number_mismatch", "detail":
                    f"the abstract states {x}, which is not a value in the Results text or the "
                    "tables - correct the abstract (or the Results)"})
    return out


def conclusions(pol, sc: dict[str, str]) -> list[dict]:
    _part, structured = _abstract_parts(sc.get("abstract", ""))
    abs_c = ""
    raw = re.sub(r"(?mi)^\**keywords?\**\s*:.*$", "", sc.get("abstract", ""))
    m = ABS_CONCL.search(raw)
    if m:
        abs_c = pol.flow(m.group(1)).strip()
    elif not structured:
        paras = pol._paras(raw)
        abs_c = paras[-1] if paras else ""
    disc = sc.get("discussion_conclusion") or ""
    if not disc.strip():
        paras = pol._paras(sc.get("discussion", ""))
        disc = paras[-1] if paras else ""
    disc = pol.flow(disc).strip()
    if not abs_c or not disc:
        return []
    a_strong = sorted({x.group(0).lower() for x in STRONG.finditer(abs_c)})
    d_strong = sorted({x.group(0).lower() for x in STRONG.finditer(disc)})
    extra = [w for w in a_strong if w not in d_strong]
    return [{"kind": "conclusion_strength", "detail":
             "compare the strength of the abstract conclusion with the Discussion conclusion"
             + (f" - the abstract alone uses: {', '.join(extra)}" if extra else ""),
             "abstract": abs_c[:400], "discussion": disc[:400]}]


def report(project: Path, write: bool = True) -> dict:
    """The report; `write` (the polish.py command) saves it, gates and briefs only read."""
    pol = _pol()
    rel, text = manuscript(project)
    sc = scopes(text)
    blocking, warnings = [], []
    docs = [(rel if rel.endswith(".md") else MS, text)]
    for x in pol.lint_abbreviations(docs):
        item = {"kind": x["kind"], "detail": x["detail"]}
        (blocking if x["kind"] in ("abbrev_redefined", "abbrev_used_before_defined")
         else warnings).append(item)
    blocking += abstract_numbers(pol, project, sc)
    warnings += terminology(pol, project, sc, text)
    warnings += near_duplicates(pol, sc)
    for x in pol.lint_spelling(docs):
        warnings.append({"kind": x["kind"], "detail": x["detail"]})
    for x in pol.lint_style(docs[0][0], text):
        if x["kind"] in ("p_case", "p_value_style"):
            warnings.append({"kind": x["kind"], "detail": x["detail"]})
    data = {"schema": 1, "created_at": _now(), "file": rel, "blocking": blocking,
            "warnings": warnings, "for_reviewer": conclusions(pol, sc)}
    # next to the manuscript it judged (the journal copy once a variant is open; never into the
    # frozen 07_manuscript/ after S19)
    data["report"] = (Path(rel).parent / Path(REL).name).as_posix() if rel.endswith(".md") else REL
    out = Path(project) / data["report"]
    if write and Path(project, rel).is_file():
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return data


def lines(data: dict) -> list[str]:
    out = [f"cross-section report of {data['file']}: {len(data['blocking'])} blocking, "
           f"{len(data['warnings'])} warning(s), {len(data['for_reviewer'])} item(s) for the reviewer"]
    out += [f"  BLOCK {x['kind']}: {x['detail']}" for x in data["blocking"][:20]]
    out += [f"  WARN  {x['kind']}: {x['detail']}" for x in data["warnings"][:20]]
    for x in data["for_reviewer"]:
        out.append(f"  REVIEWER {x['kind']}: {x['detail']}")
        out.append(f"    abstract:   {x['abstract'][:200]}")
        out.append(f"    discussion: {x['discussion'][:200]}")
    return out
