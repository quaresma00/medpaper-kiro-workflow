"""1.10.0 raw-record spot check: 10 reproducible cases traced back to the raw source.

Use from a paper script under 03_analysis/spot_check/ (run with `wf run-script`):

    from analysis.spotcheck import sample_ids, write_spot_check
    ids = sample_ids(all_subject_ids, seed=2024)           # 10 (or all when fewer)
    cases = [{"id": i, "raw_source": ["02_data/raw/demo.xpt"],
              "checks": [{"variable": "age", "raw": raw_age, "derived": derived_age}]}
             for i in ids]
    write_spot_check(cases, seed=2024, population=all_subject_ids)

A mismatch needs an "explanation" on that check (>= 20 characters), else the S06 gate fails.
"""
from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

REL = "03_analysis/spot_check.json"
K = 10


def sample_ids(ids, seed: int, k: int = K) -> list[str]:
    universe = sorted({str(i) for i in ids})
    rng = random.Random(int(seed))
    return sorted(rng.sample(universe, min(k, len(universe))))


def universe_sha256(ids) -> str:
    return hashlib.sha256("\n".join(sorted({str(i) for i in ids})).encode("utf-8")).hexdigest()


def _same(raw, derived) -> bool:
    try:
        return abs(float(raw) - float(derived)) <= 1e-9 * max(1.0, abs(float(raw)))
    except (TypeError, ValueError):
        return str(raw).strip() == str(derived).strip()


def write_spot_check(cases: list[dict], *, seed: int, population, project: Path | None = None) -> Path:
    if project is None:
        from wfcore.paths import project_dir
        project = project_dir()
    ids = sorted({str(i) for i in population})
    expected = sample_ids(ids, seed)
    if sorted(str(c.get("id")) for c in cases) != expected:
        raise ValueError("cases must be exactly sample_ids(population, seed)")
    for case in cases:
        for chk in case.get("checks", []):
            chk.setdefault("match", _same(chk.get("raw"), chk.get("derived")))
    payload = {"seed": int(seed), "population_n": len(ids), "universe_sha256": universe_sha256(ids),
               "sample": expected, "cases": cases}
    out = Path(project) / REL
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n",
                   encoding="utf-8")
    return out
