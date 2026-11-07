"""1.19.0 (M3): a Discussion that interprets instead of restating the Results.

Deterministic checks run inside the S16 section-language gate (section_language_clean with
`discussion_checks = true`, since 1.19.0) on 07_manuscript/discussion.md:

    supplementary display citations (Table S2, Figure S1, Supplementary Table 3, Online
      Resource 2, eTable 1, ESM 3, Additional file 1)        at most discussion_supp_citations_max (0)
    main display citations (Table 2, Figure 1)               at most discussion_display_citations_max (2)
    sentences carrying the paper's own result numbers (a number that also occurs in
      results.md, in a sentence without a citation - a cited prior study's number does not
      count, 1.14 C)                                          at most discussion_result_sentences_max (3)
    sentences restating a Results sentence (Jaccard >= discussion_restate_jaccard (0.6) on
      content words and numbers)                              at most discussion_restated_sentences_max (2)
    distinct verified prior studies cited                     at least discussion_prior_studies_min (5; warning)

Thresholds live in pipeline.toml [targets]; a paper changes them in its own .wf/config.toml
[targets] together with `discussion_thresholds_reason` (>= 20 characters) - never in the
engine. An override without a reason is ignored (warning).

The writer's outline (.wf/writer/discussion_outline.md, a working file that is never exported,
uploaded or frozen) is checked by discussion_outline_ready: the six labels, <= 200 words, and
every key finding F1, F2 ... compared with at least one verified citekey or 'no prior study'.
"""
from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

OUTLINE = ".wf/writer/discussion_outline.md"
OUTLINE_WORDS_MAX = 200
LABELS = ("Principal findings", "Comparison with previous studies", "Possible mechanisms",
          "Clinical and research implications", "Strengths and limitations", "Conclusion")
DEFAULTS = {"discussion_supp_citations_max": 0, "discussion_display_citations_max": 2,
            "discussion_result_sentences_max": 3, "discussion_restated_sentences_max": 2,
            "discussion_prior_studies_min": 5, "discussion_restate_jaccard": 0.6}
REASON_KEY = "discussion_thresholds_reason"
SUPP_RE = re.compile(
    r"(?i)\b(?:(?:Tables?|Figs?\.?|Figures?)\s+S\d+[A-Za-z]?"
    r"|Supplement(?:ary|al)\s+(?:Tables?|Figs?\.?|Figures?|Data|Materials?|Methods|Appendix|Files?)"
    r"(?:\s+S?\d+)?"
    r"|Online\s+Resources?\s+\d+|e(?:Table|Figure|Fig|Appendix|Methods)\s*\d+"
    r"|ESM\s*_?\d*\b|Electronic\s+supplementary\s+material|Additional\s+files?\s+\d+)")
MAIN_RE = re.compile(r"\b(?:Tables?|Figs?\.?|Figures?)\s+(?!S\d)\d+[A-Za-z]?(?:\s*(?:,|and|&|-|\u2013)\s*\d+[A-Za-z]?)*")
CITE_RE = re.compile(r"\[[^\]\n]*@[^\]\n]*\]")
KEY_RE = re.compile(r"@([A-Za-z][\w:.#$%&+?<>~/-]*)")
STOP = set("""the and for with that this these those from were was are been being have has had
which who whom whose than then there their they them its our ours we us you your not but nor
also into onto over under after before between among about above below more most less least
such each other some any all both either neither may might could would should can will shall
than very much many only own same so too just one two three per via vs versus within without
during while where when whether what how why study studies patients patient result results
found showed shown observed associated association compared higher lower""".split())
NUM_RE = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)(%?)(?![\w])")


def _strip(text: str) -> str:
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    return re.sub(r"(?m)^\s{0,3}#{1,6}\s.*$", " ", text)


def sentences(text: str) -> list[str]:
    out = []
    for para in re.split(r"\n\s*\n", _strip(text)):
        para = " ".join(para.split())
        if not para:
            continue
        out += [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z(\[])", para) if s.strip()]
    return out


def _plain(s: str) -> str:
    return MAIN_RE.sub(" ", SUPP_RE.sub(" ", CITE_RE.sub(" ", s)))


def numbers(s: str) -> set[str]:
    """Result-like numbers: decimals, percentages, integers >= 10 (years are not results)."""
    out = set()
    for m in NUM_RE.finditer(_plain(s)):
        v, pct = m.group(1), m.group(2)
        if "." not in v and not pct:
            if int(v) < 10 or (1900 <= int(v) <= 2099):
                continue
        out.add(v)
    return out


def content(s: str) -> set[str]:
    p = _plain(s).casefold()
    words = {w for w in re.findall(r"[a-z][a-z-]{2,}", p) if w not in STOP}
    return words | numbers(s)


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def thresholds(project: Path | None) -> tuple[dict, list[str]]:
    """(effective thresholds, warnings). A paper override needs discussion_thresholds_reason."""
    from . import paths, registry
    base = dict(DEFAULTS)
    try:
        base.update({k: v for k, v in tomllib.loads(paths.pipeline_file().read_text(
            encoding="utf-8")).get("targets", {}).items() if k in DEFAULTS})
    except (OSError, tomllib.TOMLDecodeError):
        pass
    eff = registry.effective_targets(project) if project is not None else {}
    changed = {k: eff[k] for k in DEFAULTS if k in eff and eff[k] != base[k]}
    if not changed:
        return base, []
    reason = str(eff.get(REASON_KEY, "")).strip()
    if len(reason) < 20:
        return base, [f"paper override of {', '.join(sorted(changed))} ignored: add "
                      f"{REASON_KEY} (>= 20 characters) to .wf/config.toml [targets]"]
    return {**base, **changed}, [f"paper thresholds {changed} ({reason[:80]})"]


def _verified(project: Path) -> set[str]:
    try:
        data = json.loads((Path(project) / "06_refs/verified.json").read_text(encoding="utf-8"))
        recs = data.get("records", data) if isinstance(data, dict) else {}
        keys = {k for k, v in recs.items() if isinstance(v, dict) and v.get("verified") is True}
        if keys:
            return keys
    except (OSError, ValueError, AttributeError):
        pass
    try:
        lib = json.loads((Path(project) / "06_refs/library.json").read_text(encoding="utf-8"))
        return {str(e.get("citekey")) for e in lib.get("entries", []) if e.get("citekey")}
    except (OSError, ValueError, AttributeError):
        return set()


def cited_keys(text: str) -> list[str]:
    out = []
    for group in CITE_RE.findall(text):
        out += KEY_RE.findall(group)
    return out


def _quote(s: str, n: int = 70) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[:n - 3] + "..."


def analyse(project: Path, text: str, results_text: str = "") -> tuple[list[str], list[str]]:
    """(blocking problems, warnings) of a Discussion."""
    t, warns = thresholds(project)
    sents = sentences(text)
    probs: list[str] = []
    supp = sorted({" ".join(m.group(0).split()) for m in SUPP_RE.finditer(_strip(text))})
    if len(supp) > int(t["discussion_supp_citations_max"]):
        probs.append(f"Discussion cites supplementary material ({', '.join(supp[:4])}): medical "
                     "journals almost never do - remove these citations; say what the finding "
                     "means and how it compares, the reader finds the detail in the Results")
    main = [" ".join(m.group(0).split()) for m in MAIN_RE.finditer(
        SUPP_RE.sub(" ", _strip(CITE_RE.sub(" ", text))))]
    if len(main) > int(t["discussion_display_citations_max"]):
        probs.append(f"Discussion cites tables/figures {len(main)} times (max "
                     f"{t['discussion_display_citations_max']}: {', '.join(main[:4])}): drop the "
                     "display references and interpret instead (what it means, why it may differ "
                     "from earlier studies)")
    res_nums = set().union(*(numbers(s) for s in sentences(results_text))) if results_text else None
    own = [s for s in sents if not CITE_RE.search(s)
           and (numbers(s) & res_nums if res_nums is not None else numbers(s))]
    if len(own) > int(t["discussion_result_sentences_max"]):
        probs.append(f"{len(own)} Discussion sentences repeat the study's own result numbers (max "
                     f"{t['discussion_result_sentences_max']}), e.g. '{_quote(own[-1])}': keep the "
                     "primary estimate once in the principal-findings sentence; elsewhere describe "
                     "direction, size and certainty in words and compare with prior studies")
    res_sents = [(s, content(s)) for s in sentences(results_text)] if results_text else []
    cut = float(t["discussion_restate_jaccard"])
    restated = []
    for s in sents:
        c = content(s)
        if len(c) < 5:
            continue
        best = max((jaccard(c, rc) for _r, rc in res_sents), default=0.0)
        if best >= cut:
            restated.append(s)
    if len(restated) > int(t["discussion_restated_sentences_max"]):
        probs.append(f"{len(restated)} Discussion sentences restate Results sentences (max "
                     f"{t['discussion_restated_sentences_max']}), e.g. '{_quote(restated[-1])}': "
                     "rewrite them as interpretation - compare with earlier studies, explain why "
                     "results differ, give the likely mechanism and the clinical implication")
    keys = set(cited_keys(text))
    ver = _verified(project)
    prior = keys & ver if ver else keys
    if len(prior) < int(t["discussion_prior_studies_min"]):
        warns.append(f"the Discussion cites {len(prior)} distinct verified prior studies (< "
                     f"{t['discussion_prior_studies_min']}): compare the findings with more of the "
                     "literature you read (agreement, disagreement and why)")
    return probs, warns


def _sections(text: str) -> dict[str, str]:
    """label -> body of an outline written with headings ('## Principal findings') or
    'Principal findings:' lead-ins."""
    pat = "|".join(re.escape(x) for x in LABELS)
    rx = re.compile(rf"(?im)^[ \t#>*_-]*({pat})\b[*_ \t]*:?[*_]*[ \t]*")
    hits = list(rx.finditer(text))
    out = {}
    for i, m in enumerate(hits):
        end = hits[i + 1].start() if i + 1 < len(hits) else len(text)
        label = next(x for x in LABELS if x.casefold() == m.group(1).casefold())
        out.setdefault(label, text[m.end():end].strip())
    return out


NO_PRIOR_RE = re.compile(r"(?i)\bno\s+(?:prior|previous|earlier|published|comparable)\s+(?:\w+\s+)?"
                         r"(?:study|studies|report|reports|data)\b")


def outline_problems(project: Path) -> list[str]:
    from . import journalspec
    path = Path(project) / OUTLINE
    if not path.is_file():
        return [f"{OUTLINE} missing: the clinical writer first writes the outline (six labels, "
                "<= 200 words), then the Discussion (writer_bundle.py build --stage S16_discussion)"]
    text = path.read_text(encoding="utf-8", errors="replace")
    out = []
    secs = _sections(text)
    missing = [x for x in LABELS if x not in secs or not secs[x].strip()]
    if missing:
        out.append("outline lacks: " + ", ".join(missing))
    words = journalspec.word_count(text)
    if words > OUTLINE_WORDS_MAX:
        out.append(f"outline has {words} words (max {OUTLINE_WORDS_MAX}): keep it a plan")
    findings = sorted(set(re.findall(r"\bF(\d+)\b", secs.get(LABELS[0], ""))), key=int)
    if not findings and LABELS[0] in secs:
        out.append("label each key finding under 'Principal findings' F1, F2, ...")
    comp = secs.get(LABELS[1], "")
    ver = _verified(project)
    for n in findings:
        lines = [ln for ln in re.split(r"\n|(?<=\.)\s+(?=F\d)", comp) if re.search(rf"\bF{n}\b", ln)]
        ok = any(NO_PRIOR_RE.search(ln) or any((k in ver) if ver else True for k in cited_keys(ln))
                 for ln in lines)
        if not ok:
            out.append(f"F{n}: the comparison part cites no verified study for it (cite one, or "
                       "state that no prior study exists)")
    return out
