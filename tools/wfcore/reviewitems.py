"""1.16.0: items a gate cannot decide mechanically, listed for the reviewer.

A deterministic check that meets a case it cannot judge safely (a Results sentence combining
several results, a label next to the right one, a figure statistic it cannot map) does not
fail and does not stay silent: it lists the case here, keyed by its source, and the next
review bundle (review_round.py start / S25 audit-start) carries the list as
`reviewer_items.md`. Each check run replaces its own source's list, so a fixed sentence
disappears. This is a list in .wf/, not a stage, a decision or a second state.
"""
from __future__ import annotations

import json
from pathlib import Path

REL = ".wf/reviewer_items.json"


def _load(project: Path) -> dict:
    try:
        data = json.loads((Path(project) / REL).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def note(project: Path, source: str, items: list[str]) -> None:
    """Replace the listed items of one source (an empty list clears it)."""
    data = _load(project)
    if items:
        data[source] = list(dict.fromkeys(items))[:50]
    elif source in data:
        del data[source]
    else:
        return
    p = Path(project) / REL
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except OSError:
        pass  # best effort: the gate verdict does not depend on this list


def items(project: Path) -> list[tuple[str, str]]:
    return [(src, it) for src, lst in sorted(_load(project).items())
            for it in (lst if isinstance(lst, list) else [])]


def write(project: Path, out: Path) -> Path | None:
    """reviewer_items.md in a review bundle folder; None when nothing is listed."""
    found = items(project)
    if not found:
        return None
    lines = ["# Items for the reviewer (not decidable by the deterministic checks)", "",
             "Judge each one in the report: is the sentence or display correct as written? "
             "Name the item and say 'correct' or what must change.", ""]
    last = None
    for src, it in found:
        if src != last:
            lines += ["", f"## {src}", ""]
            last = src
        lines.append(f"- {it}")
    dst = Path(out) / "reviewer_items.md"
    dst.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return dst
