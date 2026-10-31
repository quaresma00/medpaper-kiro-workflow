"""1.15.0 (E12): render-time reference fixes that never touch refs.bib.

refs.bib is built from the PubMed record and verified by refproof, so it is never edited by
hand. Some PubMed fields render badly, e.g. pages "731-40; discussion 741-2". Two fixes apply
when a Word file is rendered (a patched temporary copy of the bibliography goes to Pandoc):

- a default rule drops a '; discussion ...' tail from page fields
  (target_journal.json reference_rules.drop_discussion_pages, default on for 1.15.0 papers);
- 06_refs/ref_overrides.json, validated per citekey:
      {"smith2010": [{"field": "pages", "value": "731-40", "reason": "<why>"}]}
  The value must be consistent with the PubMed-derived field: it may only shorten it (its
  letters/digits appear in the source field in order) or, for pages, write the same range in
  full ("731-740" for "731-40"). Nothing else can be invented.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REL = "06_refs/ref_overrides.json"
FIELDS = ("pages", "title", "journal", "volume", "number", "year", "doi")
ENTRY_RE = re.compile(r"@\w+\s*\{\s*([^,\s]+)\s*,")
DISCUSSION_RE = re.compile(r"(?i)\s*;\s*discussion\b.*$")


def load(project: Path) -> dict[str, list[dict]]:
    path = Path(project) / REL
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, list[dict]] = {}
    if isinstance(data, list):
        for row in data:
            if isinstance(row, dict) and row.get("citekey"):
                out.setdefault(str(row["citekey"]), []).append(row)
    elif isinstance(data, dict):
        for key, rows in data.items():
            rows = [rows] if isinstance(rows, dict) else rows
            out[str(key)] = [r for r in rows or [] if isinstance(r, dict)]
    return out


def _entries(bib: str) -> dict[str, tuple[int, int]]:
    """citekey -> (start, end) span of its entry in the .bib text."""
    out = {}
    starts = [(m.start(), m.group(1)) for m in ENTRY_RE.finditer(bib)]
    for i, (s, key) in enumerate(starts):
        out[key] = (s, starts[i + 1][0] if i + 1 < len(starts) else len(bib))
    return out


def _field_re(field: str) -> re.Pattern:
    return re.compile(rf"(?is)(\b{field}\s*=\s*)(\{{(?:[^{{}}]|\{{[^{{}}]*\}})*\}}|\"[^\"]*\"|\d+)")


def field(entry: str, name: str) -> str | None:
    m = _field_re(name).search(entry)
    if not m:
        return None
    v = m.group(2)
    return v[1:-1] if v[:1] in "{\"" else v


def _expand(rng: str) -> list[tuple[int, int]]:
    out = []
    for a, b in re.findall(r"(\d+)\s*[-\u2013]\s*(\d+)", rng):
        if len(b) < len(a):
            b = a[:len(a) - len(b)] + b
        out.append((int(a), int(b)))
    out += [(int(x), int(x)) for x in re.findall(r"(?<![\d-])(\d+)(?![\d-])", rng)]
    return out


def consistent(name: str, value: str, source: str | None) -> bool:
    if source is None:
        return False
    if name == "pages":
        mine, theirs = _expand(value), _expand(source)
        return bool(mine) and all(r in theirs for r in mine)
    norm = lambda s: re.sub(r"[^0-9a-z]+", "", s.casefold())  # noqa: E731
    v, s = norm(value), norm(source)
    it = iter(s)
    return bool(v) and all(ch in it for ch in v)


def problems(project: Path, bib_path: Path | None = None) -> list[str]:
    try:
        rows = load(project)
    except (OSError, ValueError) as exc:
        return [f"{REL}: not valid JSON ({exc})"]
    if not rows:
        return []
    bib_path = bib_path or Path(project) / "06_refs/refs.bib"
    bib = bib_path.read_text(encoding="utf-8", errors="replace") if bib_path.is_file() else ""
    spans = _entries(bib)
    out = []
    for key, items in rows.items():
        if key not in spans:
            out.append(f"{REL}: {key} is not in refs.bib")
            continue
        entry = bib[slice(*spans[key])]
        for r in items:
            name, value = str(r.get("field", "")).casefold(), str(r.get("value", ""))
            if name not in FIELDS:
                out.append(f"{REL}: {key}.{name}: field must be one of {', '.join(FIELDS)}")
            elif len(str(r.get("reason", "")).strip()) < 10:
                out.append(f"{REL}: {key}.{name}: give a reason (>= 10 characters)")
            elif not consistent(name, value, field(entry, name)):
                out.append(f"{REL}: {key}.{name}='{value}' is not consistent with the PubMed "
                           f"field '{field(entry, name)}' (an override may only shorten it or "
                           "write the same page range in full)")
    return out


def patch(project: Path, bib_text: str, drop_discussion: bool) -> tuple[str, list[str]]:
    """The bibliography text Pandoc renders, and what was changed."""
    rows = load(project)
    spans = _entries(bib_text)
    changes = []
    pieces, last = [], 0
    for key, (s, e) in sorted(spans.items(), key=lambda kv: kv[1][0]):
        entry = bib_text[s:e]
        new = entry
        if drop_discussion:
            pages = field(new, "pages")
            if pages and DISCUSSION_RE.search(pages):
                short = DISCUSSION_RE.sub("", pages)
                new = _field_re("pages").sub(lambda m: m.group(1) + "{" + short + "}", new, count=1)
                changes.append(f"{key}.pages: '{pages}' -> '{short}'")
        for r in rows.get(key, []):
            name, value = str(r.get("field", "")).casefold(), str(r.get("value", ""))
            if field(new, name) is not None:
                new = _field_re(name).sub(lambda m: m.group(1) + "{" + value + "}", new, count=1)
                changes.append(f"{key}.{name} -> '{value}' ({r.get('reason', '')})")
        pieces.append(bib_text[last:s] + new)
        last = e
    pieces.append(bib_text[last:])
    return "".join(pieces), changes


def render_copy(project: Path, bib: Path | None, workdir: Path,
                drop_discussion: bool) -> Path | None:
    """A patched copy of the bibliography in `workdir` (the original when nothing applies)."""
    if bib is None or not Path(bib).is_file() or Path(bib).suffix.casefold() != ".bib":
        return bib
    bad = problems(project, Path(bib))
    if bad:
        raise ValueError("; ".join(bad[:4]))
    text = Path(bib).read_text(encoding="utf-8", errors="replace")
    new, changes = patch(project, text, drop_discussion)
    if not changes:
        return bib
    out = Path(workdir) / "render_refs.bib"
    out.write_text(new, encoding="utf-8")
    return out
