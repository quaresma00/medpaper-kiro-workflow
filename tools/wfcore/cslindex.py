"""1.17.0 (J6): the journal's citation style by ISSN (CSL styles project, CC BY-SA 3.0).

reference/csl_issn_index.json maps an ISSN (print or electronic) to the dependent style that
names it and to its independent parent style; it is generated from
github.com/citation-style-language/styles (branch v1.0.2) by the maintainer command
`tools/refs/csl_index.py build`. Credit: the Citation Style Language project, citationstyles.org
(reference/CSL_STYLES_ATTRIBUTION.md). Style files are fetched at runtime from the same branch
(`tools/refs/csl_index.py fetch --issn ...`) and cached. stdlib only: gates use it.
"""
from __future__ import annotations

import json
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path

INDEX = "reference/csl_issn_index.json"
RAW = "https://raw.githubusercontent.com/citation-style-language/styles/v1.0.2/{path}"
ISSN_RE = re.compile(r"\b(\d{4})-?(\d{3}[\dXx])\b")
NS = "{http://purl.org/net/xbiblio/csl}"
_CACHE: dict[str, dict] = {}


def issns(text) -> list[str]:
    return sorted({f"{a}-{b.upper()}" for a, b in ISSN_RE.findall(str(text or ""))})


def index_path(root: Path) -> Path:
    """The vendored index (MEDPAPER_CSL_INDEX points tests at a synthetic one)."""
    return Path(os.environ.get("MEDPAPER_CSL_INDEX") or Path(root) / INDEX)


def load(root: Path) -> dict:
    path = index_path(root)
    key = str(path)
    if key not in _CACHE:
        try:
            _CACHE[key] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _CACHE[key] = {}
    return _CACHE[key]


def lookup(root: Path, issn: str) -> dict | None:
    data = load(root)
    for i in issns(issn):
        hit = (data.get("issn") or {}).get(i)
        if hit:
            return {"issn": i, "style_id": hit[0], "parent": hit[1] if len(hit) > 1 else hit[0]}
    return None


def style_id(raw: str) -> str:
    """'http://www.zotero.org/styles/vancouver' -> 'vancouver'."""
    return str(raw or "").rstrip("/").rsplit("/", 1)[-1]


def csl_meta(path: Path) -> dict:
    """id, title, ISSNs and the independent parent of one CSL file."""
    return csl_meta_bytes(Path(path).read_bytes())


def csl_meta_bytes(data: bytes) -> dict:
    root = ET.fromstring(data)
    info = root.find(f"{NS}info")
    out = {"id": "", "title": "", "issns": [], "parent": None}
    if info is None:
        return out
    out["id"] = style_id((info.findtext(f"{NS}id") or "").strip())
    out["title"] = (info.findtext(f"{NS}title") or "").strip()
    out["issns"] = issns(" ".join((e.text or "") for tag in ("issn", "eissn", "issnl")
                                  for e in info.findall(f"{NS}{tag}")))
    for link in info.findall(f"{NS}link"):
        if link.get("rel") == "independent-parent":
            out["parent"] = style_id(link.get("href", ""))
    return out


def matches(root: Path, csl_path: Path, journal_issns: list[str]) -> tuple[bool, str]:
    """Does this CSL belong to the journal? Own ISSN, or the parent the index maps it to."""
    meta = csl_meta(csl_path)
    own = set(meta["issns"]) & set(journal_issns)
    if own:
        return True, f"{csl_path.name} names ISSN {', '.join(sorted(own))}"
    for i in journal_issns:
        hit = lookup(root, i)
        if hit and meta["id"] in (hit["style_id"], hit["parent"]):
            return True, (f"{csl_path.name} is {meta['id']}, the style the CSL index gives ISSN {i} "
                          f"({hit['style_id']} -> {hit['parent']})")
    want = [lookup(root, i) for i in journal_issns]
    want = [w for w in want if w]
    return False, (f"{csl_path.name} ({meta['id'] or 'no id'}) does not name the journal ISSN "
                   f"{', '.join(journal_issns) or '?'}" + (f"; the CSL index expects "
                                                           f"{want[0]['style_id']} -> "
                                                           f"{want[0]['parent']}" if want else
                                                           "; the ISSN is not in the CSL index"))
