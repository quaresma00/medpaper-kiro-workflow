"""1.16.0 (N7): counts of every step of a join declared complex, checked at S04.

Only a paper whose `acquisition_manifest.json` declares `analysis_dataset.relationship =
"complex_join"` (repeated visits, many-to-many links, aggregation) needs this; one row per
patient needs nothing. The S04 verifier (wfcore/dataproof.join_problems) checks that the counts
add up: analysis units never grow, the units lost equal unmatched + excluded, a many-to-one
lookup does not multiply rows (duplicate keys), an aggregation states its rule and leaves one
row per unit, each step starts where the previous one ended and the last one ends at the
analysis dataset's n_rows.

    from analysis.joinlog import JoinLog
    log = JoinLog(unit_key="patient_id")
    merged = log.step("labs", before=pts, after=pts.merge(labs, on="patient_id"),
                      kind="repeated_visits", key="patient_id")
    one = log.step("first lab", before=merged,
                   after=merged.groupby("patient_id").first().reset_index(),
                   kind="aggregation", key="patient_id",
                   aggregation="first laboratory value after the index date")
    log.save()                      # -> 02_data/join_log.json

kind: many_to_one (a lookup), repeated_visits, many_to_many (state the resolution rule in
`aggregation`), aggregation, filter. unmatched / excluded: analysis units lost at this step
for lack of a match / by a stated rule. R: tools/R/medjoin.R (join_log_step, write_join_log).
"""
from __future__ import annotations

import json
from pathlib import Path

from wfcore import paths

JOIN_LOG = "02_data/join_log.json"
KINDS = ("many_to_one", "repeated_visits", "many_to_many", "aggregation", "filter")


class JoinLog:
    def __init__(self, unit_key: str):
        self.unit_key = unit_key
        self.steps: list[dict] = []

    def _units(self, obj) -> int:
        if hasattr(obj, "columns"):
            return int(obj[self.unit_key].nunique(dropna=True))
        return len({r.get(self.unit_key) for r in obj if r.get(self.unit_key) is not None})

    def step(self, name: str, before, after, kind: str, key: str, aggregation: str = "",
             unmatched: int = 0, excluded: int = 0):
        """Record one join step and return `after` unchanged (so it can wrap the merge)."""
        if kind not in KINDS:
            raise ValueError(f"kind must be one of {', '.join(KINDS)}")
        self.steps.append({
            "name": name, "kind": kind, "key": key, "aggregation": aggregation,
            "rows_before": int(len(before)), "rows_after": int(len(after)),
            "units_before": self._units(before), "units_after": self._units(after),
            "unmatched_units": int(unmatched), "excluded_units": int(excluded)})
        return after

    def save(self, path: str = JOIN_LOG) -> Path:
        target = Path(path)
        if not target.is_absolute():
            target = paths.project_dir(check_engine=False) / target
        out = paths.paper_output_path(target)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"unit_key": self.unit_key, "steps": self.steps}, indent=2)
                       + "\n", encoding="utf-8")
        return out
