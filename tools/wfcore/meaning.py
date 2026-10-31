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

MEANING_CHECK never rewinds. The caller writes a small bundle (the pairs, the results in words
and a neutral brief); the medpaper-reviewer subagent records one verdict per pair in that
bundle's report.md ("P01: meaning unchanged - why" | "P01: meaning changed - why"), or the
author decides (rework.py meaning-decide).

1.15.0 (E1): pairs are aligned SENTENCES inside changed paragraphs, hashed on their normalised
words, so an identical pair is never asked twice; the journal copy and the final copy are
compared with their last confirmed version (all pairs 'unchanged'), not with the original
again; while a revision round is open every context shares ONE bundle
(.wf/review_bundle/meaning_<round>/, stable ids P01..); the author may override any pair,
including a reviewer's 'changed', by id or hash (the overridden verdict and the author's words
are kept). Verdicts live in .wf/meaning_verdicts.json (1.14 paragraph hashes still count).
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
                pair = {"file": rel, "old": " ".join(o), "new": " ".join(n), "cues": cues}
                out.append({**pair, "legacy": legacy_hash(pair)})
        return out
    po, pn = paragraphs(old_text, line_mode), paragraphs(new_text, line_mode)
    for o, n in _align(po, pn):
        cues = delta(tokens(o), tokens(n), terms)
        if not cues:
            continue
        para = legacy_hash({"file": rel, "old": o, "new": n})
        # 1.15.0 (E1b): judge per aligned SENTENCE pair, so a one-word edit in a long paragraph
        # does not re-open the paragraph's other (already judged) sentences. A paragraph added
        # or deleted as a whole stays one pair; cues that only cancel across sentences fall
        # back to the paragraph pair.
        sub = []
        if o and n:
            for a, b in _align(sentences(o), sentences(n)):
                c = delta(tokens(a), tokens(b), terms)
                if c:
                    sub.append({"file": rel, "old": a, "new": b, "cues": c, "para": para})
        out += sub or [{"file": rel, "old": o, "new": n, "cues": cues, "legacy": para}]
    return out


_SENT = re.compile(r"(?<=[.!?;])\s+(?=[\"'(\[]?[A-Z0-9])")


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT.split(text or "") if s.strip()]


def _align(po: list[str], pn: list[str]) -> list[tuple[str, str]]:
    """Changed (old, new) unit pairs of two unit lists; units that only moved are no change."""
    ko, kn = [_key(p) for p in po], [_key(p) for p in pn]
    sm = difflib.SequenceMatcher(None, ko, kn, autojunk=False)
    gone, came = [], []
    blocks = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "equal":
            blocks.append((list(range(i1, i2)), list(range(j1, j2))))
            gone += list(range(i1, i2))
            came += list(range(j1, j2))
    moved = Counter(ko[i] for i in gone) & Counter(kn[j] for j in came)
    left_old, left_new = Counter(moved), Counter(moved)

    def keep(key: str, left: Counter) -> bool:
        if left[key] > 0:
            left[key] -= 1
            return False
        return True
    pairs: list[tuple[str, str]] = []
    for olds, news in blocks:
        olds = [i for i in olds if keep(ko[i], left_old)]
        news = [j for j in news if keep(kn[j], left_new)]
        used: set[int] = set()
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
    return pairs


def legacy_hash(p: dict) -> str:
    """The 1.14 whole-paragraph hash (file + exact text): verdicts stored under it still count."""
    blob = json.dumps([p.get("file"), p.get("old"), p.get("new")], ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def pair_hash(p: dict) -> str:
    """1.15.0 (E1b): normalised words of the old and new sentence (no file, case, spacing,
    punctuation, citations or numbers), so an identical pair is never asked twice."""
    blob = " ".join(tokens(p.get("old") or "")) + "\x1f" + " ".join(tokens(p.get("new") or ""))
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

def _verdict(data: dict, p: dict) -> dict | None:
    """The stored verdict of a pair: its normalised hash, else (verdicts from 1.14) the
    whole-paragraph hash of the pair itself or of the paragraph a sentence pair came from."""
    for key in (p.get("hash"), p.get("legacy"), p.get("para")):
        if key and key in data:
            return data[key]
    return None


def record_author(project: Path, pair: dict, verdict: str, reason: str) -> dict:
    """1.15.0 (E1d): the author may decide ANY pair, including one a reviewer judged
    'changed'; the overridden verdict is kept with the author's exact words."""
    if verdict not in ("unchanged", "changed"):
        raise ValueError("verdict must be 'unchanged' or 'changed'")
    if len(reason.strip()) < 10:
        raise ValueError("an author decision needs the author's reason/words (>= 10 characters)")
    data = load_verdicts(project)
    prev = _verdict(data, pair)
    rec = {"verdict": verdict, "reason": reason.strip(), "by": "author",
           "file": pair.get("file"), "old": pair.get("old"), "new": pair.get("new"), "at": _now()}
    if prev and prev.get("by") != "author":
        rec["overrides"] = {k: prev.get(k) for k in ("verdict", "reason", "by")}
    data[pair["hash"]] = rec
    _save_verdicts(project, data)
    return rec


def overrides(project: Path, hashes=None) -> list[str]:
    """Author decisions that replaced a reviewer verdict (for the round summary)."""
    out = []
    for h, rec in sorted(load_verdicts(project).items()):
        if rec.get("by") == "author" and rec.get("overrides") and (hashes is None or h in hashes):
            was = rec["overrides"]
            out.append(f"[{h[:8]}] {rec.get('file')}: reviewer '{was.get('verdict')}' "
                       f"({str(was.get('reason') or '')[:60]}) -> author '{rec['verdict']}': "
                       f"\"{rec['reason'][:160]}\"")
    return out


# --------------------------------------------------------------------------- one bundle
ROUNDS_DIR = ".wf/meaning_rounds"


def _safe(key: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", str(key))[:40]


def active_round(project: Path) -> str | None:
    try:
        st = json.loads((Path(project) / ".wf/state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    rid = st.get("active_revision_round") if isinstance(st, dict) else None
    return str(rid) if rid else None


def bundle_key(project: Path, context: str) -> str:
    """1.15.0 (E1c): while a revision round is open every context (round edits, submission
    copy, final copy, presentation layer) shares ONE bundle for that round."""
    return active_round(project) or context


def _registry_path(project: Path, key: str) -> Path:
    return Path(project) / ROUNDS_DIR / f"{_safe(key)}.json"


def _load_registry(project: Path, key: str) -> dict:
    try:
        data = json.loads(_registry_path(project, key).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("key", key)
    data.setdefault("ids", {})
    data.setdefault("pairs", {})
    data.setdefault("current", {})
    return data


def _save_registry(project: Path, key: str, data: dict) -> None:
    path = _registry_path(project, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def register(project: Path, context: str, pairs: list[dict]) -> list[dict]:
    """Normalised hashes and STABLE ids (P01, P02, ... per round/context, never reused);
    duplicates (the same sentence pair seen by two contexts) collapse to one entry."""
    key = bundle_key(project, context)
    reg = _load_registry(project, key)
    out, seen = [], set()
    for p in pairs:
        p["hash"] = pair_hash(p)
        pid = reg["ids"].get(p["hash"])
        if pid is None:
            pid = f"P{len(reg['ids']) + 1:02d}"
            reg["ids"][p["hash"]] = pid
        p["id"] = pid
        entry = reg["pairs"].setdefault(p["hash"], {k: p.get(k) for k in (
            "id", "hash", "file", "old", "new", "cues", "legacy", "para")})
        entry.setdefault("contexts", [])
        if context not in entry["contexts"]:
            entry["contexts"].append(context)
        if p["hash"] not in seen:
            seen.add(p["hash"])
            out.append(p)
    reg["current"][context] = sorted(seen)
    _save_registry(project, key, reg)
    return out


def known_pairs(project: Path) -> list[dict]:
    """Every pair ever put to a meaning check in this paper (registries + 1.14 bundles)."""
    root = Path(project)
    out: dict[str, dict] = {}
    for reg in sorted((root / ROUNDS_DIR).glob("*.json")) if (root / ROUNDS_DIR).is_dir() else []:
        try:
            data = json.loads(reg.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for h, p in (data.get("pairs") or {}).items():
            out.setdefault(h, {**p, "key": data.get("key")})
    for pj in sorted((root / BUNDLE_DIR).glob("meaning_*/pairs.json")) \
            if (root / BUNDLE_DIR).is_dir() else []:
        try:
            for p in json.loads(pj.read_text(encoding="utf-8")):
                out.setdefault(p["hash"], {**p, "key": pj.parent.name})
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return list(out.values())


def find_pair(project: Path, ref: str, context: str | None = None) -> dict | None:
    """A pair by its id in the open round/context bundle (P03) or by (a prefix of) the hash
    printed in the check output."""
    ref = str(ref or "").strip().strip("[]")
    if not ref:
        return None
    if re.fullmatch(r"(?i)P\d{1,3}", ref):
        key = bundle_key(project, context or "")
        reg = _load_registry(project, key)
        for h, pid in reg["ids"].items():
            if pid == ref.upper() and h in reg["pairs"]:
                return reg["pairs"][h]
        legacy = bundle_pairs(project, context) if context else []
        return next((p for p in legacy if p.get("id") == ref.upper()), None)
    if re.fullmatch(r"[0-9a-fA-F]{6,16}", ref):
        hits = [p for p in known_pairs(project) if str(p.get("hash", "")).startswith(ref.lower())]
        if len({p["hash"] for p in hits}) == 1:
            return hits[0]
        data = load_verdicts(project)
        keys = [h for h in data if h.startswith(ref.lower())]
        if len(keys) == 1:
            rec = data[keys[0]]
            return {"hash": keys[0], "file": rec.get("file"), "old": rec.get("old"),
                    "new": rec.get("new"), "id": keys[0][:8]}
    return None


# --------------------------------------------------------------------------- reports
_GUARD_NOTES: list[str] = []


def _id_map(folder: Path) -> dict[str, str]:
    try:
        ids = json.loads((folder / "ids.json").read_text(encoding="utf-8"))
        return {pid: h for h, pid in ids.items()}
    except (OSError, ValueError, AttributeError):
        pass
    try:
        return {r["id"]: r["hash"] for r in json.loads((folder / "pairs.json").read_text(
            encoding="utf-8"))}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def ingest_reports(project: Path) -> list[str]:
    """Fold every reviewer report.md (and archived report_<n>.md) of every meaning bundle into
    the verdict store. A report written while a paper file changed is refused (E2)."""
    from . import reviewguard
    root = Path(project) / BUNDLE_DIR
    data = load_verdicts(project)
    dirty, notes = False, []
    folders = sorted(root.glob("meaning_*")) if root.is_dir() else []
    for folder in folders:
        reports = sorted(folder.glob("report*.md"))
        if not reports:
            continue
        ids = _id_map(folder)
        try:
            meta = {p["hash"]: p for p in json.loads((folder / "pairs.json").read_text(
                encoding="utf-8"))}
        except (OSError, ValueError, KeyError, TypeError):
            meta = {}
        for report in reports:
            bad = reviewguard.problems(project, folder.name, report)
            if bad:
                notes.append(f"{folder.name}/{report.name} refused: paper file(s) changed "
                             f"during the review: {', '.join(bad[:5])}")
                continue
            for pid, (verdict, why) in parse_report(
                    report.read_text(encoding="utf-8", errors="replace")).items():
                h = ids.get(pid)
                if h and h not in data:
                    m = meta.get(h, {})
                    data[h] = {"verdict": verdict, "reason": why, "by": "reviewer",
                               "file": m.get("file"), "old": m.get("old"), "new": m.get("new"),
                               "at": _now(), "bundle": folder.name}
                    dirty = True
    if dirty:
        _save_verdicts(project, data)
    _GUARD_NOTES[:] = notes
    return notes


def resolve(project: Path, context: str, pairs: list[dict]) -> tuple[list[dict], list[dict]]:
    """-> (unresolved pairs, changed pairs with 'reason'). Reviewer verdicts in the bundle
    reports are folded into the verdict store first; ids are stable per round."""
    pairs = register(project, context, pairs)
    ingest_reports(project)
    data = load_verdicts(project)
    unresolved, changed = [], []
    for p in pairs:
        rec = _verdict(data, p)
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
Write {report} - the only file you may write - with exactly one line per pair, each with a
short reason:
  P01: meaning unchanged - <one-line reason>
  P02: meaning changed - <one-line reason>
If you cannot write files, return exactly these lines between the markers <<<REPORT>>> and
<<<END>>> in your reply."""


def bundle_dir(project: Path, context: str, pairs: list[dict] | None = None) -> Path:
    return Path(project) / BUNDLE_DIR / f"meaning_{_safe(bundle_key(project, context))}"


def bundle_pairs(project: Path, context: str | None) -> list[dict]:
    """The pairs of the newest 1.14-style bundle written for a context."""
    if not context:
        return []
    root = Path(project) / BUNDLE_DIR
    found = sorted(root.glob(f"meaning_{_safe(context)}*/pairs.json"),
                   key=lambda p: p.stat().st_mtime) if root.is_dir() else []
    try:
        return json.loads(found[-1].read_text(encoding="utf-8")) if found else []
    except (OSError, ValueError):
        return []


def write_bundle(project: Path, context: str, pairs: list[dict]) -> Path:
    """ONE bundle per open round (else per context) holding every still-unresolved pair of
    all its contexts; rewritten only when that set changes (an older report is archived as
    report_<n>.md and still counts, ids are stable)."""
    from . import reviewguard
    project = Path(project)
    key = bundle_key(project, context)
    pairs = register(project, context, pairs)
    reg = _load_registry(project, key)
    data = load_verdicts(project)
    current = sorted({h for hs in reg["current"].values() for h in hs} | {pair_hash(p) for p in pairs})
    todo = [reg["pairs"][h] for h in current if h in reg["pairs"] and not _verdict(data, reg["pairs"][h])]
    todo += [p for p in pairs if p.get("hash") not in reg["pairs"]]
    todo.sort(key=lambda p: p.get("id", ""))
    out = bundle_dir(project, context)
    want = [{k: p.get(k) for k in ("id", "hash", "file", "old", "new")} for p in todo]
    try:
        have = json.loads((out / "pairs.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        have = None
    if have == want and (out / "MANIFEST.md").is_file():
        return out
    out.mkdir(parents=True, exist_ok=True)
    if (out / "report.md").is_file():
        n = len(list(out.glob("report_*.md"))) + 1
        (out / "report.md").replace(out / f"report_{n}.md")
    rows = [f"# Meaning check pairs ({key})", ""]
    for p in todo:
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
    (out / "pairs.json").write_text(json.dumps(want, indent=1, ensure_ascii=False) + "\n",
                                    encoding="utf-8")
    (out / "ids.json").write_text(json.dumps(reg["ids"], indent=1) + "\n", encoding="utf-8")
    manifest = [f"# Meaning-check bundle {out.name}", "",
                BRIEF.format(context=key, report=out / "report.md"), "", "## Files", "",
                f"- {out / 'pairs.md'}", f"- {out / 'results_in_words.md'}"]
    from .decisionrecord import write as _write_record  # 1.14.0 (D1): reviewer only
    record = _write_record(project, out)
    if record:
        manifest.append(f"- {record}")
    (out / "MANIFEST.md").write_text("\n".join(manifest) + "\n", encoding="utf-8")
    reviewguard.take(project, out.name)
    return out


def instructions(project: Path, context: str, pairs: list[dict]) -> str:
    out = write_bundle(project, context, pairs)
    n = len(json.loads((out / "pairs.json").read_text(encoding="utf-8")))
    notes = " ".join(_GUARD_NOTES)
    return ((notes + " ") if notes else "") + (
        f"{n} meaning-bearing wording change(s) need a verdict (one bundle for "
        f"{bundle_key(project, context)}): pass the medpaper-reviewer subagent this ONE path "
        f"{out / 'MANIFEST.md'} (it writes one line per pair to {out / 'report.md'}; if it "
        "cannot write, save its reply and run rework.py meaning-ingest --from <file>), or "
        "record the author's decision (rework.py meaning-decide --pair <id|hash>). 'meaning "
        "changed' routes to the SCIENCE path (S19 only with '我确认回退').")


def changed_line(p: dict) -> str:
    return (f"{p['file']} {p['id']} [{p['hash'][:8]}]: meaning changed ({p.get('by')}): "
            f"{str(p.get('reason') or '')[:120]} (the author may override: rework.py "
            f"meaning-decide --pair {p['hash'][:8]} --verdict unchanged --words \"<author's words>\")")


def gate(project: Path, context: str, pairs: list[dict]) -> list[str]:
    """Problems for a context that must not proceed with unresolved/changed meaning."""
    if not pairs:
        return []
    unresolved, changed = resolve(project, context, pairs)
    problems = [changed_line(p) for p in changed]
    if unresolved:
        problems.append(instructions(project, context, unresolved))
    return problems


# --------------------------------------------------------------------------- increments
CONFIRMED_REL = ".wf/meaning_confirmed.json"


def confirmed_text(project: Path, context: str, key: str, anchor: str) -> str | None:
    """1.15.0 (E1a): the last version of a copy whose every meaning pair was resolved
    'unchanged' - later checks compare against it, not against the original again."""
    try:
        data = json.loads((Path(project) / CONFIRMED_REL).read_text(encoding="utf-8"))
        rec = data[context][key]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return rec.get("text") if rec.get("anchor") == anchor else None


def confirm(project: Path, context: str, key: str, text: str, anchor: str) -> None:
    path = Path(project) / CONFIRMED_REL
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    prev = (data.get(context) or {}).get(key) or {}
    if prev.get("anchor") == anchor and prev.get("text") == text:
        return
    data.setdefault(context, {})[key] = {"anchor": anchor, "text": text, "at": _now(),
                                         "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def ingest_file(project: Path, src: Path, context: str | None = None) -> tuple[Path, int]:
    """E2 fallback: the reviewer's saved reply (or a host workflow-state JSON) -> the bundle's
    report.md, verbatim between <<<REPORT>>> and <<<END>>>."""
    from . import reviewguard
    from .argtext import read_text_retry
    report = reviewguard.extract_report(read_text_retry(Path(src)))
    if not report or not parse_report(report):
        raise ValueError("no meaning verdict lines (P01: meaning unchanged|changed ...) found "
                         "between <<<REPORT>>> markers")
    key = active_round(project) or context
    folder = (Path(project) / BUNDLE_DIR / f"meaning_{_safe(key)}") if key else None
    if folder is None or not (folder / "pairs.json").is_file():
        root = Path(project) / BUNDLE_DIR
        found = sorted(root.glob("meaning_*/pairs.json"), key=lambda p: p.stat().st_mtime) \
            if root.is_dir() else []
        if not found:
            raise ValueError("no meaning-check bundle to attach the report to")
        folder = found[-1].parent
    dest = reviewguard.ingest(project, Path(src), folder / "report.md")
    return dest, len(parse_report(report))
