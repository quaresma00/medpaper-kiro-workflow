"""Reuse an unchanged independent live PubMed check for a short, explicit freshness window.

`reference_provenance` with `live = true` re-fetches the whole library from NCBI. Eleven gates
declare it, so a check -> advance pair at every stage cost two full EFetch round trips and an
NCBI hiccup could stall a stage that changed nothing about the references. The receipt here
lets a later gate reuse a live check that passed recently, but only on the same evidence:

- it lives in the paper's own `.wf/` (never in the engine);
- it is bound to the SHA-256 of the raw gate EFetch XML that NCBI returned, so the payload
  cannot be edited without invalidating it;
- the XML is reparsed and every current library entry is compared against it again, so a
  changed library (new entry, edited title/DOI) misses the cache and goes back to NCBI;
- it expires after `live_reference_age_hours_max` hours (24 by default).

S13 (library construction) and S25 (final audit) never read it; they always go to NCBI.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from . import refproof
from .packagefreeze import _safe_path

REL = ".wf/reference_live.json"
GATE_PREFIX = "06_refs/cache/gate_efetch_pubmed_"
FORCED_LIVE_STAGES = frozenset({"S13_reflib", "S25_submission_audit"})


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def cached_sources(project: Path, entries: list[dict], max_hours: float = 24) -> dict | None:
    """Sources from a fresh, hash-bound gate EFetch that still matches every entry; else None."""
    try:
        payload = json.loads((project / REL).read_text(encoding="utf-8"))
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(payload["at"])).total_seconds()
        if age < 0 or age > float(max_hours) * 3600:
            return None
        sources: dict = {}
        rows = payload["payloads"]
        if not rows:
            return None
        for row in rows:
            rel, path = _safe_path(project, row["path"])
            if not rel.startswith(GATE_PREFIX):
                return None
            if refproof.file_sha256(path) != row["sha256"]:
                return None
            sources.update(refproof.parse_pubmed_payload(path.read_bytes()))
        if not entries or set(sources) != {str(e.get("pmid", "")) for e in entries}:
            return None
        if any(refproof.compare_entry_to_source(e, sources[str(e["pmid"])]) for e in entries):
            return None
        return sources
    except (OSError, ValueError, KeyError, TypeError):
        return None


def store_sources(project: Path, live_records: list[dict]) -> bool:
    """Record the gate payloads behind a passing live check. Returns False if not cacheable."""
    payloads = {}
    for row in live_records:
        rel = str(row.get("cache_file", "")).replace("\\", "/")
        if not rel.startswith(GATE_PREFIX):
            return False  # a mocked/test record or a non-independent source cannot seed the cache
        try:
            _, path = _safe_path(project, rel)
        except ValueError:
            return False
        if not path.is_file():
            return False
        payloads[rel] = {"path": rel, "sha256": refproof.file_sha256(path)}
    if not payloads:
        return False
    _atomic_json(project / REL, {"at": datetime.now(timezone.utc).isoformat(),
                                 "payloads": list(payloads.values())})
    return True
