"""1.14.0 (C): a real citation is not yet evidence for the sentence that carries it.

A Discussion number next to a verified citekey counts only when that number appears in the
cited source's verified text, in this order: the stored library abstract (bound to PubMed by
the S13 proof), the S15 deep-read notes (06_refs/deepread/<citekey>.md) and the identity-
verified full-text copy (06_refs/fulltext/, fulltext.py verify). Numbers are compared after
normalisation (thousands separators, unicode minus, percent signs, ranges split into their
ends) at the precision the Discussion displays. The location (abstract | notes | full text
page N | full text table) is written to .wf/citation_numbers.json.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

RECORD_REL = ".wf/citation_numbers.json"
CACHE_DIR = ".wf/cache/fulltext_text"
_NUM = re.compile(r"(?<![\w.])[+\-\u2212]?\d+(?:\.\d+)?(?![\w])")
_THOUSANDS = re.compile(r"(?<=\d)[,\u2009\u202f\u00a0](?=\d{3}(?!\d))")
_YEAR = re.compile(r"^(?:19|20)\d{2}$")


def numbers_in(text: str) -> tuple[set[float], set[str]]:
    text = _THOUSANDS.sub("", str(text or "")).replace("\u2212", "-").replace("\u2013", " ")
    strings = {m.group(0).lstrip("+") for m in _NUM.finditer(text)}
    floats = set()
    for s in strings:
        try:
            floats.add(float(s))
        except ValueError:
            pass
    return floats, strings | {s.lstrip("-") for s in strings}


def _strip_tags(blob: str) -> str:
    return re.sub(r"<[^>]+>", " ", blob)


def _fulltext_parts(project: Path, path: Path) -> list[tuple[str, str]]:
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()[:20]
    cache = Path(project) / CACHE_DIR / f"{digest}.json"
    try:
        return [tuple(x) for x in json.loads(cache.read_text(encoding="utf-8"))]
    except (OSError, ValueError, TypeError):
        pass
    parts: list[tuple[str, str]] = []
    if path.suffix.casefold() == ".pdf":
        try:
            import io
            from pypdf import PdfReader
            pages = [(p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages]
        except Exception:  # noqa: BLE001 - an unparsable PDF falls back to its raw text
            pages = [data[:8_000_000].decode("latin-1", errors="replace")]
        parts = [(f"full text page {i}", t) for i, t in enumerate(pages, 1)]
    else:
        text = data.decode("utf-8", errors="replace")
        tables = re.findall(r"(?is)<table-wrap\b.*?</table-wrap>|<table\b.*?</table>", text)
        body = re.sub(r"(?is)<table-wrap\b.*?</table-wrap>|<table\b.*?</table>", " ", text)
        parts = [("full text", _strip_tags(body))] + [("full text table", _strip_tags(t))
                                                       for t in tables]
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(parts, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return parts


class Locator:
    """Finds a cited number in its source's verified text; one instance per check run."""

    def __init__(self, project: Path):
        from . import refproof
        self.project = Path(project)
        try:
            lib = json.loads((self.project / "06_refs/library.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            lib = {}
        entries = lib.get("entries", []) if isinstance(lib, dict) else []
        self.abstracts = {str(e.get("citekey")): str(e.get("abstract") or "")
                          for e in entries if isinstance(e, dict)}
        self.fulltext = refproof.fulltext_verified(self.project)
        self._texts: dict[str, list[tuple[str, set[float], set[str]]]] = {}
        self.found: list[dict] = []

    def _sources(self, key: str):
        if key not in self._texts:
            parts: list[tuple[str, str]] = []
            if self.abstracts.get(key):
                parts.append(("abstract", self.abstracts[key]))
            notes = self.project / "06_refs/deepread" / f"{key}.md"
            if notes.is_file():
                parts.append(("notes", notes.read_text(encoding="utf-8", errors="replace")))
            if key in self.fulltext:
                try:
                    parts += _fulltext_parts(self.project, self.fulltext[key])
                except OSError:
                    pass
            self._texts[key] = [(loc, *numbers_in(t)) for loc, t in parts]
        return self._texts[key]

    def locate(self, token: str, keys: list[str]) -> str | None:
        from .checks.numbers import _matches
        if _YEAR.match(token.lstrip("+")):
            return "year"
        tok = token.replace("\u2212", "-").lstrip("+")
        for key in keys:
            for loc, floats, strings in self._sources(key):
                if _matches(tok, floats, strings):
                    return f"{key}: {loc}"
        return None

    def note(self, rel: str, line: int, token: str, where: str) -> None:
        self.found.append({"file": rel, "line": line, "number": token, "source": where})

    def save(self, rel: str) -> None:
        path = self.project / RECORD_REL
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}
        except (OSError, ValueError):
            data = {}
        data[rel] = [f for f in self.found if f["file"] == rel and f["source"] != "year"]
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        except OSError:
            pass
