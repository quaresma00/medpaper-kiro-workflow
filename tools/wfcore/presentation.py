"""1.9.0 post-freeze changes are classified by content, not by directory.

Before 1.9.0 any byte change under 04_tables/, 05_figures/ or 07_manuscript/ after the S19
freeze counted as a scientific change: the paper went back to S19, through another review
round, another "no further review", a re-freeze and a new S24 confirmation - for a spelling
fix in a legend or a space in "P < 0.001".

Now a post-freeze revision item is classified when it is checked:

    facts unchanged  -> presentation: only the deterministic checks rerun, the user is shown a
                        change summary, the freezes record a presentation delta (old/new hashes
                        and the summary) instead of being invalidated, no new review round and
                        no re-confirmation;
    facts changed    -> scientific: back to S19 exactly as before.

Facts are what review certified: numbers (sign-aware, separator/minus/spacing-insensitive),
citation keys, figure/table references, table cell values, and for figures the data behind
them (sidecar source hashes, population, numbers drawn in the figure) - not styling.
"""
from __future__ import annotations

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
def strip_non_facts(text: str) -> str:
    """Remove in-word numbers and list enumerators before counting numbers (#9)."""
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


def text_facts(text: str, aliases: dict | None = None) -> dict:
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    if aliases:
        from . import journalspec
        text = journalspec.expand_aliases(text, aliases)
    keys = [k for grp in CITE_RE.findall(text) for k in KEY_RE.findall(grp.strip("[]") + "]")]
    arts = [f"{'figure' if a.lower().startswith('fig') else 'table'} {n.upper()}{(p or '').upper()}"
            for a, n, p in ART_RE.findall(text)]
    stripped = ART_RE.sub(" ", CITE_RE.sub(" ", text))
    return {"numbers": sorted(numbers(stripped)), "citekeys": sorted(keys), "artifacts": sorted(arts)}


def _xlsx_facts(path: Path) -> dict:
    from .xlsxlite import Workbook
    wb = Workbook(path)
    vals = [c.value for sh in wb.sheets for c in sh.cells if c.value]
    joined = "\n".join(str(v) for v in vals)
    return {"numbers": sorted(numbers(joined)), "artifacts": sorted(text_facts(joined)["artifacts"])}


def _sidecar(project: Path, stem: str) -> Path:
    return Path(project) / "05_figures/qc" / f"{stem}.artist.json"


def _figure_facts(project: Path, sidecar: Path) -> dict | None:
    try:
        art = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    figtext = art.get("figure_text", "")
    if isinstance(figtext, list):
        figtext = "\n".join(map(str, figtext))
    return {"sources": json.dumps(art.get("source_hashes", {}), sort_keys=True),
            "population": json.dumps(art.get("population", {}), sort_keys=True),
            "numbers": sorted(numbers(str(figtext)))}


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


def facts(project: Path, rel: str) -> dict | None:
    """Facts of one paper file, or None when the file carries no reviewable facts itself
    (a build script is judged by what it renders)."""
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


def snapshot_facts(project: Path) -> dict[str, dict]:
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
            f = facts(project, rel)
            if f is not None:
                out.setdefault(identity(rel), f)
    return out


def _diff(before: dict, after: dict) -> list[str]:
    out = []
    for key in sorted(set(before) | set(after)):
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


def classify(project: Path, before: dict[str, dict], changed: list[str]) -> dict:
    """'presentation' when every changed file keeps its facts, else 'scientific' + reasons."""
    reasons, checked = [], []
    for rel in sorted(set(changed)):
        if rel.startswith(SCIENCE_PREFIXES) or rel in SCIENCE_FILES:
            reasons.append(f"{rel}: data/analysis/protocol source changed")
            continue
        if not in_scope(rel):
            continue
        key = identity(rel)
        now = facts(project, rel) if (Path(project) / rel).is_file() else None
        old = before.get(key)
        if now is None and old is None:
            continue
        checked.append(rel)
        if now is None and not (Path(project) / rel).is_file():
            # A deleted render whose figure still exists elsewhere keeps its facts.
            if key.startswith("figure:") and facts(project, f"05_figures/qc/{key[7:]}.artist.json"):
                continue
            if any(old.get(k) for k in old):
                reasons.append(f"{rel}: deleted reviewed content")
            continue
        if old is None:
            if any(now.get(k) for k in now):
                reasons.append(f"{rel}: new content with facts")
            continue
        diff = _diff(old, now or {})
        if diff:
            reasons.append(f"{rel}: " + "; ".join(diff[:3]))
    return {"class": "scientific" if reasons else "presentation", "reasons": reasons,
            "checked": checked, "at": _now()}


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
