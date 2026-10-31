"""1.14.0 (A): meaning-bearing wording changes after the scientific freeze.

A change that keeps every number can still change the science: "no association" ->
"association", "associated with lower mortality" -> "reduced mortality", a deleted "causal
inference is not possible". Post-freeze changes are therefore classified in three classes:

    SAFE           no meaning-bearing change (synonyms, reordering, typos, punctuation);
    MEANING_CHECK  a meaning-bearing change was detected in aligned old/new paragraphs;
    SCIENCE        the existing rules (analysis/data/results changed, a number changed value,
                   an untraceable new number) - or a reviewer verdict "meaning changed".

Detection is cheap and lexical: per aligned paragraph pair the counts of cue classes
(negation and its scope, association vs causal wording, hedging vs certainty, comparison
direction and significance claims, limitations/caveats, population and time-window words and
the display-dictionary terms) are compared. A typo fix maps onto its corrected word, a
reordered paragraph keeps its profile, a moved paragraph cancels out.

MEANING_CHECK never rewinds. The caller writes a small bundle
(.wf/review_bundle/meaning_<context>_<digest>/: the pairs, the results in words and a neutral
brief); the read-only medpaper-reviewer subagent records one verdict per pair in that bundle's
report.md ("P01: meaning unchanged" | "P01: meaning changed - <reason>"), or the author decides
(rework.py meaning-decide). Verdicts are stored by pair hash in .wf/meaning_verdicts.json.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

VERDICTS_REL = ".wf/meaning_verdicts.json"
BUNDLE_DIR = ".wf/review_bundle"
CLASS_LABEL = {"presentation": "SAFE", "meaning_check": "MEANING_CHECK", "scientific": "SCIENCE"}


def _words(*items: str) -> frozenset[str]:
    return frozenset(w for item in items for w in item.split())


CUES: dict[str, frozenset[str]] = {
    "negation": _words("no not none neither nor without absence absent lack lacked lacking "
                       "never cannot fail failed fails nil"),
    "association": _words("associated association associations correlated correlation "
                          "correlations linked related relationship"),
    "causal": _words("cause causes caused causing causal causally causation lead leads led "
                     "prevent prevents prevented prevention protective protects protect "
                     "attributable due because induce induces induced drive drives driven "
                     "resulted consequence determines"),
    "hedging": _words("may might could possibly possible perhaps suggest suggests suggested "
                      "suggesting suggestive appear appears appeared likely unlikely potential "
                      "potentially probably plausible presumably seem seems tentative "
                      "hypothesis"),
    "certainty": _words("demonstrate demonstrates demonstrated prove proves proved proven proof "
                        "confirm confirms confirmed establish establishes established clearly "
                        "definitely definitive conclusive conclusively undoubtedly certainly"),
    "direction_up": _words("higher greater increased increase increases more elevated larger "
                           "longer excess rise rose raised exceeded"),
    "direction_down": _words("lower fewer less reduced reduction decreased decrease decreases "
                             "smaller shorter declined decline lowered"),
    "significance": _words("significant significantly significance nonsignificant "
                           "insignificant"),
    "comparison": _words("similar comparable equivalent noninferior noninferiority superior "
                         "inferior superiority inferiority difference differences differ "
                         "differed different"),
    "limitation": _words("limitation limitations limited caveat bias biases biased confounding "
                         "confounder confounders confounded residual caution cautious cautiously "
                         "generalizability generalisability generalizable uncertain uncertainty "
                         "exploratory hoc observational retrospective"),
    "population": _words("patients participants adults children women men elderly older younger "
                         "infants pediatric paediatric male female males females"),
    # Units and anchors of a time window; "after", "within" and "before" are too common in
    # ordinary prose ("after adjustment") to carry the signal on their own.
    "time": _words("day days week weeks month months year years hour hours baseline follow "
                   "postoperative preoperative perioperative term early late interim landmark"),
}
CUE_OF = {w: c for c, ws in CUES.items() for w in ws}
STOP = _words("the a an of and or in on at to for with by from as is are was were be been "
              "this that these those it its than then which who whom whose our we their")
_FENCE = re.compile(r"```.*?```", re.S)
_CITE = re.compile(r"\[[^\]\n]*@[^\]\n]*\]")
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_WORD = re.compile(r"[^\W\d_]+")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- terms
def dictionary_terms(project: Path | None) -> dict[str, str]:
    """word -> 'term:<label>' for every display-dictionary entry (label, abbreviation,
    internal name, aliases), so 'DOAC' and 'direct oral anticoagulant' are one term."""
    if project is None:
        return {}
    from . import clinical
    out: dict[str, str] = {}
    for t in (clinical.dictionary(project) or {}).get("terms", []) or []:
        if not isinstance(t, dict) or not str(t.get("label", "")).strip():
            continue
        key = "term:" + str(t["label"]).strip().casefold()
        names = [t.get("label"), t.get("abbreviation"), t.get("internal"),
                 *list(t.get("aliases") or [])]
        for name in names:
            for w in _WORD.findall(str(name or "").replace("_", " ").casefold()):
                if (len(w) >= 3 or w == str(t.get("abbreviation", "")).casefold()) \
                        and w not in STOP and w not in CUE_OF:
                    out.setdefault(w, key)
    return out


# --------------------------------------------------------------------------- profiles
def tokens(text: str) -> list[str]:
    text = _COMMENT.sub(" ", _CITE.sub(" ", _FENCE.sub(" ", text or "")))
    return _WORD.findall(text.casefold())


def _typo_map(old: list[str], new: list[str]) -> list[str]:
    """Replace a misspelt old word by its corrected new form (ratio >= 0.8, >= 4 letters)."""
    have = set(new)
    pool = [w for w in have if len(w) >= 4]
    out = []
    for w in old:
        if w in have or len(w) < 4:
            out.append(w)
            continue
        best = max(pool, key=lambda n: difflib.SequenceMatcher(None, w, n).ratio(), default=None)
        out.append(best if best and difflib.SequenceMatcher(None, w, best).ratio() >= 0.8 else w)
    return out


def profile(toks: list[str], terms: dict[str, str]) -> Counter:
    prof: Counter = Counter()
    seen_terms: set[str] = set()
    for i, w in enumerate(toks):
        cls = CUE_OF.get(w)
        if cls:
            prof[cls] += 1
            if cls in ("population", "time"):
                prof[f"{cls}:{w}"] += 1
            if cls == "negation":
                scope = [x for x in toks[i + 1:i + 6] if x not in STOP][:3]
                prof["negated:" + " ".join(scope)] += 1
        elif w in terms:
            seen_terms.add(terms[w])
    for key in seen_terms:
        prof[key] += 1
    return prof


def delta(old: list[str], new: list[str], terms: dict[str, str]) -> list[str]:
    """Meaning-bearing differences between two aligned token lists (empty = SAFE)."""
    old = _typo_map(old, new)
    a, b = profile(old, terms), profile(new, terms)
    if a == b:
        return []
    return [f"{key}: {a[key]} -> {b[key]}" for key in sorted(set(a) | set(b)) if a[key] != b[key]]


# --------------------------------------------------------------------------- pairing
def paragraphs(text: str, line_mode: bool = False) -> list[str]:
    text = _COMMENT.sub(" ", _FENCE.sub(" ", text or ""))
    parts = text.splitlines() if line_mode else re.split(r"\n\s*\n", text)
    return [" ".join(p.split()) for p in parts if p.strip()]


def _key(p: str) -> str:
    return " ".join(tokens(p))


def pairs_for(old_text: str | None, new_text: str, rel: str, terms: dict[str, str],
              old_seq: list[str] | None = None, line_mode: bool = False,
              new_seq: list[str] | None = None) -> list[dict]:
    """[{file, old, new, cues}] for every aligned paragraph pair with a meaning-bearing change."""
    out: list[dict] = []
    if old_text is None:
        if old_seq is None:
            return []
        def words(seq):
            return [t for t in seq if not re.fullmatch(r"-?\d+(?:\.\d+)?", t) and t != "zzcell"]
        old_t = words(old_seq)
        new_t = words(new_seq) if new_seq is not None else tokens(new_text)
        sm = difflib.SequenceMatcher(None, old_t, new_t, autojunk=False)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                continue
            o, n = old_t[max(0, i1 - 12):i2 + 12], new_t[max(0, j1 - 12):j2 + 12]
            cues = delta(o, n, terms)
            if cues:
                out.append({"file": rel, "old": " ".join(o), "new": " ".join(n), "cues": cues})
        return out
    po, pn = paragraphs(old_text, line_mode), paragraphs(new_text, line_mode)
    ko, kn = [_key(p) for p in po], [_key(p) for p in pn]
    sm = difflib.SequenceMatcher(None, ko, kn, autojunk=False)
    gone, came = [], []
    blocks = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "equal":
            blocks.append((list(range(i1, i2)), list(range(j1, j2))))
            gone += list(range(i1, i2))
            came += list(range(j1, j2))
    # A paragraph that only moved (same words elsewhere) is not a change.
    moved = Counter(ko[i] for i in gone) & Counter(kn[j] for j in came)
    left_old, left_new = Counter(moved), Counter(moved)

    def keep(key: str, left: Counter) -> bool:
        if left[key] > 0:
            left[key] -= 1
            return False
        return True
    for olds, news in blocks:
        olds = [i for i in olds if keep(ko[i], left_old)]
        news = [j for j in news if keep(kn[j], left_new)]
        used: set[int] = set()
        pairs = []
        for i in olds:
            best, score = None, 0.0
            for j in news:
                if j in used:
                    continue
                r = difflib.SequenceMatcher(None, ko[i].split(), kn[j].split(),
                                            autojunk=False).ratio()
                if r > score:
                    best, score = j, r
            if best is not None and score >= 0.4:
                used.add(best)
                pairs.append((po[i], pn[best]))
            else:
                pairs.append((po[i], ""))
        pairs += [("", pn[j]) for j in news if j not in used]
        for o, n in pairs:
            cues = delta(tokens(o), tokens(n), terms)
            if cues:
                out.append({"file": rel, "old": o, "new": n, "cues": cues})
    return out


def pair_hash(p: dict) -> str:
    blob = json.dumps([p.get("file"), p.get("old"), p.get("new")], ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def number(pairs: list[dict]) -> list[dict]:
    for i, p in enumerate(pairs, 1):
        p["id"] = f"P{i:02d}"
        p["hash"] = pair_hash(p)
    return pairs


# --------------------------------------------------------------------------- verdicts
def load_verdicts(project: Path) -> dict:
    try:
        data = json.loads((Path(project) / VERDICTS_REL).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_verdicts(project: Path, data: dict) -> None:
    path = Path(project) / VERDICTS_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# 1.14.1 (B1): one verdict per LINE. The 1.14.0 pattern used \s*, which crossed the newline
# after a verdict without a reason and swallowed the next line ("P02: ...") as P01's reason.
VERDICT_RE = re.compile(r"(?i)^[ \t>*+\-#|]*\**[ \t]*(P\d{1,3})\b\**[ \t]*[:\-\u2013\u2014|)\]]+"
                        r"[ \t]*\**[ \t]*meaning[ \t]+(unchanged|changed)\b\**"
                        r"[ \t]*[:\-\u2013\u2014,;.|]*[ \t]*(.*)$")


def parse_report(text: str) -> dict[str, tuple[str, str]]:
    out = {}
    for line in (text or "").splitlines():
        m = VERDICT_RE.match(line)
        if m:
            pid, verdict, why = m.groups()
            out[pid.upper()] = (verdict.casefold(), why.strip().strip("|*").strip())
    return out


def record_author(project: Path, pair: dict, verdict: str, reason: str) -> None:
    if verdict not in ("unchanged", "changed"):
        raise ValueError("verdict must be 'unchanged' or 'changed'")
    if len(reason.strip()) < 10:
        raise ValueError("an author decision needs the author's reason/words (>= 10 characters)")
    data = load_verdicts(project)
    data[pair["hash"]] = {"verdict": verdict, "reason": reason.strip(), "by": "author",
                          "file": pair.get("file"), "at": _now()}
    _save_verdicts(project, data)


def bundle_dir(project: Path, context: str, pairs: list[dict]) -> Path:
    digest = hashlib.sha256("".join(sorted(p["hash"] for p in pairs)).encode()).hexdigest()[:8]
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", context)[:40]
    return Path(project) / BUNDLE_DIR / f"meaning_{safe}_{digest}"


def bundle_pairs(project: Path, context: str) -> list[dict]:
    """The pairs of the newest bundle written for a context (for an author decision)."""
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", context)[:40]
    root = Path(project) / BUNDLE_DIR
    found = sorted(root.glob(f"meaning_{safe}_*/pairs.json"), key=lambda p: p.stat().st_mtime) \
        if root.is_dir() else []
    try:
        return json.loads(found[-1].read_text(encoding="utf-8")) if found else []
    except (OSError, ValueError):
        return []


def resolve(project: Path, context: str, pairs: list[dict]) -> tuple[list[dict], list[dict]]:
    """-> (unresolved pairs, changed pairs with 'reason'). Reviewer verdicts in the bundle's
    report.md are folded into the verdict store first."""
    pairs = number(pairs)
    data = load_verdicts(project)
    wanted = {p["hash"]: p for p in pairs}
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", context)[:40]
    root = Path(project) / BUNDLE_DIR
    dirty = False
    for report in sorted(root.glob(f"meaning_{safe}_*/report.md")) if root.is_dir() else []:
        try:
            ids = {r["id"]: r["hash"] for r in json.loads(
                (report.parent / "pairs.json").read_text(encoding="utf-8"))}
        except (OSError, ValueError, KeyError, TypeError):
            continue
        for pid, (verdict, why) in parse_report(
                report.read_text(encoding="utf-8", errors="replace")).items():
            h = ids.get(pid)
            if h in wanted and h not in data:
                data[h] = {"verdict": verdict, "reason": why, "by": "reviewer",
                           "file": wanted[h].get("file"), "at": _now(),
                           "bundle": report.parent.name}
                dirty = True
    if dirty:
        _save_verdicts(project, data)
    unresolved, changed = [], []
    for p in pairs:
        rec = data.get(p["hash"])
        if not rec:
            unresolved.append(p)
        elif rec.get("verdict") == "changed":
            changed.append({**p, "reason": rec.get("reason", ""), "by": rec.get("by")})
    return unresolved, changed


BRIEF = """Meaning check ({context}). This is NOT a full review. Read pairs.md and
results_in_words.md in this folder only. For each numbered pair decide whether the new wording
states the same scientific meaning as the old wording (direction, association or causation,
certainty, significance, comparison, limitations, population, exposure, comparator, outcome
and time window), judged against the results. Do not judge style. When decision_record.md is
listed, a post hoc analysis newly worded as confirmatory is a meaning change.
Write {report} - the only file you may write - with exactly one line per pair:
  P01: meaning unchanged
  P02: meaning changed - <one-line reason>"""


def write_bundle(project: Path, context: str, pairs: list[dict]) -> Path:
    """The small reviewer bundle for the unresolved pairs (rewritten only when missing)."""
    project = Path(project)
    pairs = number(pairs)
    out = bundle_dir(project, context, pairs)
    if (out / "MANIFEST.md").is_file():
        return out
    out.mkdir(parents=True, exist_ok=True)
    rows = [f"# Meaning check pairs ({context})", ""]
    for p in pairs:
        rows += [f"## {p['id']} ({p['file']})", "", "Old:", "", "> " + (p["old"] or "(absent)"),
                 "", "New:", "", "> " + (p["new"] or "(deleted)"), ""]
    (out / "pairs.md").write_text("\n".join(rows) + "\n", encoding="utf-8")
    words: list[str] = []
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "manuscript"))
        import writer_bundle  # tools/manuscript/writer_bundle.py
        from . import clinical
        words = writer_bundle.results_in_words(project, clinical.dictionary(project))[0][:120]
    except Exception:  # noqa: BLE001 - the pairs alone still allow a verdict
        words = ["(results in words unavailable; judge from the pairs)"]
    (out / "results_in_words.md").write_text("# Results in words\n\n" + "\n".join(words) + "\n",
                                             encoding="utf-8")
    (out / "pairs.json").write_text(json.dumps(
        [{k: p[k] for k in ("id", "hash", "file", "old", "new")} for p in pairs], indent=1,
        ensure_ascii=False) + "\n", encoding="utf-8")
    manifest = [f"# Meaning-check bundle {out.name}", "",
                BRIEF.format(context=context, report=out / "report.md"), "", "## Files", "",
                f"- {out / 'pairs.md'}", f"- {out / 'results_in_words.md'}"]
    from .decisionrecord import write as _write_record  # 1.14.0 (D1): reviewer only
    record = _write_record(project, out)
    if record:
        manifest.append(f"- {record}")
    (out / "MANIFEST.md").write_text("\n".join(manifest) + "\n", encoding="utf-8")
    return out


def instructions(project: Path, context: str, pairs: list[dict]) -> str:
    out = write_bundle(project, context, pairs)
    return (f"{len(pairs)} meaning-bearing wording change(s) need a verdict: run the read-only "
            f"medpaper-reviewer subagent on {out / 'MANIFEST.md'} only (it writes one line per "
            "pair to report.md), or record the author's decision (rework.py meaning-decide). "
            "'meaning changed' routes to the SCIENCE path (S19 only with '我确认回退').")


def gate(project: Path, context: str, pairs: list[dict]) -> list[str]:
    """Problems for a context that must not proceed with unresolved/changed meaning."""
    if not pairs:
        return []
    unresolved, changed = resolve(project, context, pairs)
    problems = [f"{p['file']} {p['id']}: meaning changed ({p.get('by')}): {p['reason'][:120]}"
                for p in changed]
    if unresolved:
        problems.append(instructions(project, context, unresolved))
    return problems
