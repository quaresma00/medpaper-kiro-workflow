"""1.9.0 post-freeze changes are classified by content, not by directory.

Before 1.9.0 any byte change under 04_tables/, 05_figures/ or 07_manuscript/ after the S19
freeze counted as a scientific change: the paper went back to S19, through another review
round, another "no further review", a re-freeze and a new S24 confirmation - for a spelling
fix in a legend or a space in "P < 0.001".

Now a post-freeze revision item is classified when it is checked (1.13.0 rule, classify()):

    scientific    -> (a) analysis code, data, manifest or results changed, (b) a reported
                     number changed value, or (c) a new number cannot be traced to the frozen
                     results JSON: back to S19 (only after the user's words '我确认回退');
    presentation  -> everything else, including new numbers traceable to the results,
                     deletions and reviewer-driven wording/structure edits: only the
                     deterministic checks rerun (provenance, denominators, citations), the user
                     is shown a change summary listing every added number with its source, the
                     freezes record a presentation delta instead of being invalidated, no new
                     review round and no re-confirmation.

1.14.0 (A): a third class between them - MEANING_CHECK (wfcore/meaning.py): numbers unchanged
but negation, causal/association, hedging, direction, limitation or group/time wording changed
in an aligned paragraph. Never a rewind by itself; a per-pair reviewer/author verdict decides
('meaning changed' -> scientific). The labels shown are SAFE / MEANING_CHECK / SCIENCE.

Facts are what review certified: numbers (sign-aware, separator/minus/spacing-insensitive),
citation keys, figure/table references, table cell values, and for figures the data behind
them (sidecar source hashes, population, numbers drawn in the figure) - not styling.
"""
from __future__ import annotations

import difflib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

LEDGER = ".wf/presentation_deltas.json"
SCIENCE_PREFIXES = ("02_data/", "03_analysis/")
SCIENCE_FILES = {"01_protocol/protocol_v1.md", "01_protocol/protocol_final.md"}
# Content the S19 review certified. Title page, statements, cover letter, author data and the
# built uploads are administrative or derived and never classify a change as scientific.
FACT_FILES = ("04_tables/", "05_figures/", "06_refs/refs.bib", "06_refs/library.json",
              "07_manuscript/", "08_submission/manuscript/full_manuscript.md",
              "08_submission/manuscript/supplementary_methods.md")
ADMIN_TEXT = ("title_page.md", "statements.md")
IMAGE_SUFFIXES = (".png", ".tif", ".tiff", ".pdf", ".svg", ".eps", ".jpg", ".jpeg")

NUM_RE = re.compile(r"(?<![\w.])[-\u2212]?\d+(?:\.\d+)?(?![\w])")
CITE_RE = re.compile(r"\[[^\]\n]*@[^\]\n]*\]")
KEY_RE = re.compile(r"@([A-Za-z0-9_][\w:.#$%&+?<>~/-]*?)(?=[\s;,\]]|$)")
ART_RE = re.compile(r"\b(?:supplementary\s+)?(Figure|Fig\.?|Table)\s*(S?\d+)([A-Za-z])?", re.I)
# Numbers that are part of a name or a compound word, not a reported value:
# ICD-10, COVID-19, SF-36, 5-minute, 2-second, 30-day; and enumerators (1)-(4), "1." list marks.
IN_WORD_RE = re.compile(r"\b[A-Za-z][A-Za-z]*-\d+[A-Za-z]?\b|\b\d+(?:\.\d+)?-(?=[A-Za-z])")
ENUM_RE = re.compile(r"(?<![\w)])\(\s*\d{1,2}\s*\)|^[ \t]{0,3}\d{1,2}[.)][ \t]+", re.M)
THOUSANDS_RE = re.compile(r"(?<=\d)[,\u2009\u202f\u00a0](?=\d{3}(?!\d))")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# fact extraction
# ---------------------------------------------------------------------------
# 1.11.0 (#2e): numbers that only label or sequence something - "Online Resource 2",
# "Supplementary File 3", "Appendix 1", "Panel 2", "Item 12", "Step 3", "Box 1" - are not facts.
LABEL_NUM_RE = re.compile(
    r"\b(?:Online\s+Resources?|Electronic\s+Supplementary\s+Materials?|ESM|Additional\s+files?|"
    r"Supplementary\s+(?:Files?|Materials?|Data|Appendix|Appendices|Methods|Information|Notes?|Text)|"
    r"Supplemental\s+(?:Files?|Materials?|Data|Digital\s+Content)|Appendix|Appendices|Annex|"
    r"Data\s+Supplement|eTable|eFigure|eAppendix|eMethods|Panels?|Items?|Steps?|Boxes|Box|"
    r"Sections?|Chapters?|Footnotes?|Online\s+Supplement)\s*(?:S?\d+[A-Za-z]?)"
    r"(?:\s*(?:,|and|-|\u2013|to)\s*S?\d+[A-Za-z]?)*", re.I)


def strip_non_facts(text: str) -> str:
    """Remove label/sequence numbers, in-word numbers and list enumerators (#9, 1.11.0)."""
    text = LABEL_NUM_RE.sub(" ", text)
    text = IN_WORD_RE.sub(" ", text)
    return ENUM_RE.sub(" ", text)


def admin_strings(project: Path) -> list[str]:
    """User-registered administrative facts (ethics/IRB approval, registration, grant numbers)
    from 00_input/author_info.json: an explicit "administrative_facts" list plus every string
    value holding a digit under a key that names such an identifier."""
    try:
        info = json.loads((Path(project) / "00_input/author_info.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out: list[str] = []
    key_re = re.compile(r"ethic|irb|approval|registr|grant|fund|award|permit|protocol_(?:no|number|id)",
                        re.I)

    def walk(value, admin_key: bool) -> None:
        if isinstance(value, dict):
            for k, v in value.items():
                walk(v, admin_key or bool(key_re.search(str(k))) or k == "administrative_facts")
        elif isinstance(value, list):
            for v in value:
                walk(v, admin_key)
        elif isinstance(value, str) and admin_key and re.search(r"\d", value):
            out.append(value.strip())
    walk(info, False)
    if isinstance(info, dict) and isinstance(info.get("administrative_facts"), list):
        out += [str(x).strip() for x in info["administrative_facts"] if str(x).strip()]
    return sorted({s for s in out if s}, key=len, reverse=True)


def strip_admin(text: str, admin: list[str], rel: str = "") -> str:
    """Drop registered administrative facts from title-page/declaration text."""
    if not admin:
        return text

    def scrub(block: str) -> str:
        for s in admin:
            block = block.replace(s, " ")
        return block
    name = Path(rel).name
    if name in ADMIN_TEXT:
        return scrub(text)
    m = re.search(r"(?mi)^#\s+Declarations(?: and Statements)?\s*$", text)
    if not m:
        return text
    nxt = re.search(r"(?m)^#\s+", text[m.end():])
    end = m.end() + nxt.start() if nxt else len(text)
    return text[:m.start()] + scrub(text[m.start():end]) + text[end:]


def numbers(text: str) -> list[str]:
    text = THOUSANDS_RE.sub("", strip_non_facts(text))
    return [n.replace("\u2212", "-") for n in NUM_RE.findall(text)]


# ---------------------------------------------------------------------------
# 1.13.0 (#9): positional facts - which number changed value, which is new, which was deleted
# ---------------------------------------------------------------------------
TOKEN_RE = re.compile(r"(?<![\w.])[-\u2212]?\d+(?:\.\d+)?(?![\w])|[^\W\d_]+")
NUMBER_TOKEN_RE = re.compile(r"-?\d+(?:\.\d+)?")
CELL_SEP = "zzcell"
_SENT_RE = re.compile(r"(?<=[.!?])\s+(?!\[@)")


def token_seq(text: str, aliases: dict | None = None) -> list[str]:
    """Words and reported numbers in reading order (for a positional diff). Numbers in cited
    sentences stay in: a changed literature value is still a changed value."""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    if aliases:
        from . import journalspec
        text = journalspec.expand_aliases(text, aliases)
    text = ART_RE.sub(" ", CITE_RE.sub(" ", text))
    text = THOUSANDS_RE.sub("", strip_non_facts(text))
    return [t.replace("\u2212", "-").casefold() for t in TOKEN_RE.findall(text)]


def _isnum(tok: str) -> bool:
    return bool(NUMBER_TOKEN_RE.fullmatch(tok))


def cited_numbers(text: str) -> set[str]:
    """Numbers in sentences that cite a source belong to that source (the 1.10.0 rule): a new
    one is traced to the citation, not to the results JSON."""
    out: set[str] = set()
    for line in re.sub(r"```.*?```", " ", text, flags=re.S).split("\n"):
        for s in _SENT_RE.split(line):
            if CITE_RE.search(s):
                out.update(t for t in token_seq(s) if _isnum(t))
    return out


ORDER_KEYS = ("seq", "text")  # 1.14.0: "text" feeds the meaning check, never fact identity


def same_facts(a: dict | None, b: dict | None) -> bool:
    """Fact identity ignores reading order (seq only feeds the positional diff), so a freeze or
    baseline taken before 1.13.0 still compares equal after a wording edit."""
    if a is None or b is None:
        return a is b
    return ({k: v for k, v in a.items() if k not in ORDER_KEYS}
            == {k: v for k, v in b.items() if k not in ORDER_KEYS})


def number_changes(old: list[str], new: list[str]) -> dict:
    """{changed: [(old values, new values)], added: [...], deleted: [...]} from a positional
    diff: a number replaced by a different one in place is a changed value; a number in new
    text is added; a number in removed text is deleted."""
    out: dict = {"changed": [], "added": [], "deleted": []}
    sm = difflib.SequenceMatcher(None, old, new, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        o = [t for t in old[i1:i2] if _isnum(t)]
        n = [t for t in new[j1:j2] if _isnum(t)]
        if tag == "delete":
            out["deleted"] += o
        elif tag == "insert":
            out["added"] += n
        else:
            lost, gained = Counter(o) - Counter(n), Counter(n) - Counter(o)
            # A value replaced in place (a short replacement, or the same words around it) is
            # a changed value; a rewritten passage is a deletion plus an addition.
            ow = {t for t in old[i1:i2] if not _isnum(t)}
            nw = {t for t in new[j1:j2] if not _isnum(t)}
            small = (i2 - i1) <= 3 and (j2 - j1) <= 3
            similar = len(ow & nw) / max(1, len(ow | nw)) >= 0.5
            if lost and gained and (small or similar):
                out["changed"].append((sorted(lost.elements()), sorted(gained.elements())))
            else:
                out["added"] += list(gained.elements())
                out["deleted"] += list(lost.elements())
    return out


def results_index(project: Path) -> list[tuple[str, str, object]]:
    """(results file, JSON path, value) for every number the executed analysis wrote."""
    project = Path(project)
    out: list[tuple[str, str, object]] = []
    root = project / "03_analysis/results"
    for p in sorted(root.glob("*.json")) if root.is_dir() else []:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            data = {k: v for k, v in data.items() if k != "environment"}
        rel = p.relative_to(project).as_posix()

        def walk(o, path: str) -> None:
            if isinstance(o, bool):
                return
            if isinstance(o, (int, float)):
                out.append((rel, path, o))
            elif isinstance(o, str):
                for m in NUM_RE.finditer(THOUSANDS_RE.sub("", o)):
                    out.append((rel, path, m.group(0)))
            elif isinstance(o, dict):
                for k, v in o.items():
                    walk(v, f"{path}.{k}")
            elif isinstance(o, list):
                for i, v in enumerate(o):
                    walk(v, f"{path}[{i}]")
        walk(data, "$")
    return out


def trace_number(project: Path, token: str, index=None) -> str | None:
    """Where a number comes from: '<results file> <JSON path>', 'convention',
    'number_allowlist.tsv', or None when it cannot be traced to the executed results."""
    from .checks.numbers import CONVENTIONS, _matches, _norm, _plain
    tok = str(token).replace("\u2212", "-")
    if tok in CONVENTIONS or _plain(tok) in CONVENTIONS:
        return "convention"
    allow = Path(project) / "03_analysis/results/number_allowlist.tsv"
    if allow.is_file():
        for line in allow.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.split("\t")[0].strip() in (tok, _plain(tok)):
                return "number_allowlist.tsv"
    for rel, path, v in (index if index is not None else results_index(project)):
        try:
            f = float(_plain(v) if isinstance(v, str) else v)
        except (TypeError, ValueError):
            continue
        if _matches(tok, {f}, {_norm(v)}):
            return f"{rel} {path}"
    return None


def text_facts(text: str, aliases: dict | None = None) -> dict:
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    if aliases:
        from . import journalspec
        text = journalspec.expand_aliases(text, aliases)
    keys = [k for grp in CITE_RE.findall(text) for k in KEY_RE.findall(grp.strip("[]") + "]")]
    arts = [f"{'figure' if a.lower().startswith('fig') else 'table'} {n.upper()}{(p or '').upper()}"
            for a, n, p in ART_RE.findall(text)]
    stripped = ART_RE.sub(" ", CITE_RE.sub(" ", text))
    return {"numbers": sorted(numbers(stripped)), "citekeys": sorted(keys), "artifacts": sorted(arts),
            "seq": token_seq(text)}  # 1.13.0: reading order, for the positional diff


def _xlsx_facts(path: Path) -> dict:
    from .xlsxlite import Workbook
    wb = Workbook(path)
    vals = [c.value for sh in wb.sheets for c in sh.cells if c.value]
    joined = "\n".join(str(v) for v in vals)
    return {"numbers": sorted(numbers(joined)), "artifacts": sorted(text_facts(joined)["artifacts"]),
            "seq": token_seq(f" {CELL_SEP} ".join(str(v) for v in vals))}


def _sidecar(project: Path, stem: str) -> Path:
    return Path(project) / "05_figures/qc" / f"{stem}.artist.json"


def _figure_facts(project: Path, sidecar: Path) -> dict | None:
    try:
        art = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    figtext = art.get("figure_text", "")
    if isinstance(figtext, list):
        figtext = f" {CELL_SEP} ".join(map(str, figtext))
    return {"sources": json.dumps(art.get("source_hashes", {}), sort_keys=True),
            "population": json.dumps(art.get("population", {}), sort_keys=True),
            "numbers": sorted(numbers(str(figtext).replace(CELL_SEP, "\n"))),
            "seq": token_seq(str(figtext))}


def _bib_facts(text: str) -> dict:
    entries = re.findall(r"@\w+\s*\{\s*([^,\s]+)\s*,", text)
    ids = re.findall(r"(?im)^\s*(doi|pmid|year|volume|pages)\s*=\s*[{\"]?([^}\",\n]+)", text)
    return {"citekeys": sorted(entries), "ids": sorted(f"{k.lower()}={v.strip()}" for k, v in ids)}


def identity(rel: str) -> str:
    """Rendered copies of one figure share facts (PNG, TIFF, PDF and the sidecar)."""
    p = Path(rel)
    if rel.startswith("05_figures/") and (p.suffix.casefold() in IMAGE_SUFFIXES
                                          or rel.endswith(".artist.json")):
        return "figure:" + p.name.split(".")[0]
    return rel


def reviewed_text(project: Path, rel: str) -> str:
    """The text the meaning check compares (registered administrative facts removed)."""
    path = Path(project) / rel
    return strip_admin(path.read_text(encoding="utf-8", errors="replace"),
                       admin_strings(project), rel)


def facts(project: Path, rel: str, with_text: bool = False) -> dict | None:
    """Facts of one paper file, or None when the file carries no reviewable facts itself
    (a build script is judged by what it renders). 1.14.0: `with_text` keeps the Markdown
    text too (rework baselines, presentation-layer freeze), for the meaning check."""
    out = _facts(project, rel)
    if with_text and out is not None and rel.endswith(".md") and (Path(project) / rel).is_file():
        out["text"] = reviewed_text(project, rel)
    return out


def _facts(project: Path, rel: str) -> dict | None:
    project = Path(project)
    path = project / rel
    if not path.is_file():
        return None
    suffix = path.suffix.casefold()
    try:
        if rel.startswith("05_figures/") and (suffix in IMAGE_SUFFIXES or rel.endswith(".artist.json")):
            return _figure_facts(project, _sidecar(project, Path(rel).name.split(".")[0]))
        if suffix in (".md", ".txt", ".tsv", ".csv"):
            from . import journalspec
            text = strip_admin(path.read_text(encoding="utf-8", errors="replace"),
                               admin_strings(project), rel)
            return text_facts(text, journalspec.project_aliases(project))
        if suffix == ".xlsx":
            return _xlsx_facts(path)
        if suffix == ".bib":
            return _bib_facts(path.read_text(encoding="utf-8", errors="replace"))
        if rel == "06_refs/library.json":
            data = json.loads(path.read_text(encoding="utf-8"))
            return {"citekeys": sorted(data) if isinstance(data, dict) else []}
    except (OSError, ValueError, KeyError):
        from .determinism import raw_sha256
        return {"raw": raw_sha256(path)}
    return None


def in_scope(rel: str) -> bool:
    if rel.endswith(".artist.json"):
        return True
    if "/qc/" in rel or Path(rel).name in ("manifest.json", "variant.json"):
        return False
    return rel.startswith(FACT_FILES)


def snapshot_facts(project: Path, with_text: bool = False) -> dict[str, dict]:
    """{identity: facts} for every reviewable file (taken when a post-freeze round opens)."""
    project = Path(project)
    out: dict[str, dict] = {}
    for prefix in ("04_tables", "05_figures", "06_refs", "07_manuscript", "08_submission/manuscript"):
        root = project / prefix
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or "prepolish" in path.parts or "review_packages" in path.parts:
                continue
            rel = path.relative_to(project).as_posix()
            if not in_scope(rel):
                continue
            f = facts(project, rel, with_text)
            if f is not None:
                out.setdefault(identity(rel), f)
    return out


def _diff(before: dict, after: dict) -> list[str]:
    out = []
    for key in sorted((set(before) | set(after)) - set(ORDER_KEYS)):
        b, a = before.get(key), after.get(key)
        if isinstance(b, list) or isinstance(a, list):
            lost = Counter(b or []) - Counter(a or [])
            new = Counter(a or []) - Counter(b or [])
            if lost:
                out.append(f"{key} lost: " + ", ".join(sorted(lost.elements()))[:120])
            if new:
                out.append(f"{key} added: " + ", ".join(sorted(new.elements()))[:120])
        elif b != a:
            out.append(f"{key} changed")
    return out


def science_source(rel: str) -> bool:
    """1.13.0 (#9a): analysis code, analysis data, the manifest/tolerances and the results."""
    from . import reproproof
    return (rel.startswith(("03_analysis/code/", "03_analysis/results/"))
            or rel in (reproproof.MANIFEST_REL, reproproof.TOLERANCE_REL,
                       "02_data/acquisition_manifest.json")
            or (rel.startswith("02_data/") and reproproof.counts_as_input(rel)))


def classify(project: Path, before: dict[str, dict], changed: list[str]) -> dict:
    """1.13.0 (#9): SCIENCE only when (a) analysis code, data, manifest or results changed,
    (b) a reported number changed value, or (c) a new number cannot be traced to the frozen
    results JSON. New numbers traceable to the results, deletions and wording/structure edits
    are PRESENTATION-TRACEABLE: deterministic checks only, every added number listed with its
    source, no return to S19, no new review round, no invalidated confirmation."""
    project = Path(project)
    reasons, checked, added, deleted = [], [], [], []
    index = None
    from . import meaning
    terms = meaning.dictionary_terms(project)
    pairs: list[dict] = []
    from . import journalspec
    aliases = journalspec.project_aliases(project)

    def meaning_pairs(rel: str, old: dict | None, new_text: str) -> None:
        # 1.14.0 (A): wording that keeps every number can still change the science.
        if rel.endswith(".md") and old:
            legacy = old.get("text") is None  # baseline taken before 1.14.0: reading order only
            pairs.extend(meaning.pairs_for(old.get("text"), new_text, rel, terms, old.get("seq"),
                                           new_seq=token_seq(new_text, aliases) if legacy else None))
    for rel in sorted(set(changed)):
        if science_source(rel):
            reasons.append(f"{rel}: analysis code, data, manifest or results changed")
            continue
        if not in_scope(rel):
            continue
        key = identity(rel)
        now = facts(project, rel) if (project / rel).is_file() else None
        old = before.get(key)
        if now is None and old is None:
            continue
        checked.append(rel)
        if now is None:
            # A deleted render whose figure still exists elsewhere keeps its facts; any other
            # deletion is presentation (listed for the user, never a rewind).
            if key.startswith("figure:") and facts(project, f"05_figures/qc/{key[7:]}.artist.json"):
                continue
            deleted += [{"file": rel, "number": n} for n in (old.get("numbers") or [])]
            meaning_pairs(rel, old, "")
            continue
        if rel.endswith(".md"):
            meaning_pairs(rel, old, reviewed_text(project, rel))
        old = old or {}
        for k, why in (("sources", "the data behind the figure changed"),
                       ("population", "the population drawn in the figure changed")):
            if old and old.get(k) != now.get(k):
                reasons.append(f"{rel}: {why}")
        if old.get("raw") and old.get("raw") != now.get("raw"):
            reasons.append(f"{rel}: unreadable reviewed content changed")
        if old.get("seq") is not None and now.get("seq") is not None:
            ch = number_changes(old["seq"], now["seq"])
        else:  # a baseline taken before 1.13.0 has no reading order: multiset fallback
            lost = Counter(old.get("numbers") or []) - Counter(now.get("numbers") or [])
            gained = Counter(now.get("numbers") or []) - Counter(old.get("numbers") or [])
            both = bool(lost and gained)
            ch = {"changed": [(sorted(lost.elements()), sorted(gained.elements()))] if both else [],
                  "added": [] if both else list(gained.elements()),
                  "deleted": [] if both else list(lost.elements())}
        for o, n in ch["changed"]:
            reasons.append(f"{rel}: a reported value changed: {', '.join(o)[:60]} -> "
                           f"{', '.join(n)[:60]}")
        deleted += [{"file": rel, "number": x} for x in ch["deleted"]]
        if ch["added"] and index is None:
            index = results_index(project)
        cited = (cited_numbers((project / rel).read_text(encoding="utf-8", errors="replace"))
                 if ch["added"] and rel.endswith(".md") else set())
        mine = []
        for x in ch["added"]:
            src = "cited reference" if x in cited else trace_number(project, x, index)
            if src is None:
                reasons.append(f"{rel}: new number {x} cannot be traced to the frozen results "
                               "(03_analysis/results/*.json)")
            else:
                mine.append({"file": rel, "number": x, "source": src})
        added += mine
        if mine and rel.endswith(".md"):
            from .finalcopy import ratio_problems
            text = (project / rel).read_text(encoding="utf-8", errors="replace")
            for prob in ratio_problems(text):
                if any(a["number"] in prob for a in mine):
                    reasons.append(f"{rel}: inconsistent proportion {prob}")
    cls = "scientific" if reasons else ("meaning_check" if pairs else "presentation")
    return {"class": cls, "label": meaning.CLASS_LABEL[cls], "reasons": reasons,
            "checked": checked, "added_numbers": added, "deleted_numbers": deleted,
            "meaning_pairs": meaning.number(pairs), "at": _now()}


def change_summary(verdict: dict) -> list[str]:
    """Lines for the user: each added number with its source, and the deleted numbers."""
    out = []
    for a in (verdict.get("added_numbers") or [])[:30]:
        out.append(f"  + {a['number']}  in {a['file']}  <- {a['source']}")
    dels = verdict.get("deleted_numbers") or []
    if dels:
        out.append("  - deleted: " + ", ".join(f"{d['number']} ({Path(d['file']).name})"
                                              for d in dels[:30]))
    return out


# ---------------------------------------------------------------------------
# presentation deltas: the freezes are updated, never invalidated
# ---------------------------------------------------------------------------
def load_ledger(project: Path) -> list[dict]:
    try:
        data = json.loads((Path(project) / LEDGER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return data if isinstance(data, list) else []


def covered(project: Path, rel: str, since: str | None) -> bool:
    """A file changed after a review round by a presentation delta recorded after it."""
    from .determinism import content_sha256, raw_sha256
    path = Path(project) / rel
    if not path.is_file():
        return False
    raw, content = raw_sha256(path), None
    for entry in load_ledger(project):
        if since and str(entry.get("at", "")) < str(since):
            continue
        rec = entry.get("files", {}).get(rel)
        if not rec:
            continue
        if str(rec.get("new", "")).casefold() in (raw.casefold(), raw.upper().casefold()):
            return True
        content = content or content_sha256(path)
        if rec.get("content") and rec["content"] == content:
            return True
    return False


def record_delta(project: Path, round_id: str, summary: str, files: dict[str, str]) -> dict:
    """Write the presentation delta into the ledger and both freezes.

    `files` maps each changed paper file to its hash before the round (round baseline).
    """
    from . import packagefreeze, scifreeze
    from .determinism import content_sha256, raw_sha256
    project = Path(project)
    at = _now()
    entry = {"round": round_id, "at": at, "summary": summary, "files": {}}
    for rel, old in sorted(files.items()):
        p = project / rel
        entry["files"][rel] = ({"old": old, "new": raw_sha256(p), "content": content_sha256(p)}
                               if p.is_file() else {"old": old, "new": "DELETED"})
    ledger = [e for e in load_ledger(project) if e.get("round") != round_id]  # re-check replaces
    ledger.append(entry)
    path = project / LEDGER
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ledger, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    touched = {"scientific_freeze": [], "package_freeze": []}
    if scifreeze.is_frozen(project):
        freeze = scifreeze.load_freeze(project)
        delta = {}
        for rel, meta in freeze.get("files", {}).items():
            p = project / rel
            if p.is_file() and scifreeze._sha256(p) != meta.get("sha256"):
                delta[rel] = {"old": meta.get("sha256"), "new": scifreeze._sha256(p)}
                meta.update(sha256=delta[rel]["new"], bytes=p.stat().st_size)
        if delta:
            deltas = freeze.setdefault("presentation_deltas", [])
            same = next((d for d in deltas if d.get("round") == round_id), None)
            if same:
                for rel, rec in delta.items():
                    same["files"][rel] = {"old": same["files"].get(rel, rec)["old"], "new": rec["new"]}
                same.update(at=at, summary=summary)
            else:
                deltas.append({"round": round_id, "at": at, "summary": summary, "files": delta})
            scifreeze.freeze_path(project).write_text(
                json.dumps(freeze, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            touched["scientific_freeze"] = sorted(delta)
            meta = scifreeze.variant_meta(project)
            if meta:
                live = scifreeze._sha256(scifreeze.freeze_path(project))
                meta.setdefault("rebinds", []).append(
                    {"at": at, "from": meta.get("freeze_sha256"), "to": live,
                     "reason": f"presentation delta {round_id}"})
                meta["freeze_sha256"] = live
                (project / scifreeze.VARIANT_DIR / "variant.json").write_text(
                    json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    pf = project / packagefreeze.FREEZE_REL
    if pf.is_file():
        touched["package_freeze"] = packagefreeze.apply_delta(project, round_id, summary, at)
    return touched
