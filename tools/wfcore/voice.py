"""1.24.0: confident, non-defensive clinical writing - version and novelty helpers.

Organise the narrative, never select the evidence (reference/writing_voice.md). The rules
themselves live in tools/text/polish.py (SPIN_TIER_A, the tier-B additions and lint_voice);
this module only answers two questions for them:

    since_1240(ctx) / since_1240_project(project, stage)   does the blocking spin rule apply?
    novelty_clear(project)   did the S02 publishability record find no comparable prior study?

The spin rule (spin_nonsignificant) blocks for papers on 1.24.0+; a paper pinned earlier sees
it as a warning until `wf migrate --yes`. Warning-level rules apply to every paper at once.
"""
from __future__ import annotations

import json
from pathlib import Path

V = (1, 24, 0)
SINCE = "1.24.0"


def since_1240(ctx) -> bool:
    from .state import pin_for, version_tuple
    try:
        return version_tuple(pin_for(ctx.state, getattr(ctx.stage, "id", None))) >= V
    except Exception:  # noqa: BLE001
        return True


def since_1240_project(project: Path | None, stage: str | None = None) -> bool:
    """A paper created on 1.24.0+, migrated, or after a journal switch for S20-S25."""
    from .state import version_tuple
    if project is None:
        return True
    try:
        st = json.loads((Path(project) / ".wf/state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return True
    if not isinstance(st, dict):
        return True
    pin = version_tuple(str(st.get("engine_pin") or st.get("pipeline_version") or "0"))
    jp = st.get("journal_gate_pin") or {}
    if stage and stage in (jp.get("stages") or []):
        pin = max(pin, version_tuple(str(jp.get("version", "0"))))
    return pin >= V


def novelty_clear(project: Path | None) -> bool:
    """True when the S02 publishability record found no comparable prior study (count 0)."""
    if project is None:
        return False
    try:
        from . import publishability
        nov = (((publishability.load(Path(project)).get("checkpoints") or {}).get("S02") or {})
               .get("evidence") or {}).get("novelty") or {}
    except Exception:  # noqa: BLE001
        return False
    return isinstance(nov, dict) and nov.get("count") == 0
