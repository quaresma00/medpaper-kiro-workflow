"""Prove the S18 independent review looked at the current manuscript, tables AND figures.

A reviewer handed only the Markdown can return PASS on a paper whose figures it never saw;
the user then finds the figure problems at S19 and the whole loop runs again. The review
report therefore embeds one fenced ```json block with `reviewed_artifacts`: the SHA-256 of
every file the reviewer was given (manuscript, optional supplementary Methods, artifact plan,
legends, captions and every rendered display file in the plan). The gate recomputes the set;
any drift or omission fails. Two prose sections must show the reviewer actually read it:
`Reader comprehension` and `Medical presentation`, each at least 80 characters.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .packagefreeze import _safe_path, _sha256

REVIEW_REL = "07_manuscript/independent_publishability_review.md"
PLAN_REL = "01_protocol/artifact_plan.json"
SECTIONS = ("Reader comprehension", "Medical presentation")
MIN_SECTION_CHARS = 80
_BASE = ("07_manuscript/full_manuscript.md", PLAN_REL, "05_figures/legends.md",
         "04_tables/table_captions.md")
_OPTIONAL = ("07_manuscript/supplementary_methods.md",)


def reader_inputs(project: Path) -> dict[str, str]:
    """Paper-relative path -> SHA-256 of everything the independent reviewer must see."""
    plan = json.loads((project / PLAN_REL).read_text(encoding="utf-8"))
    files = set(_BASE)
    files.update(rel for rel in _OPTIONAL if (project / rel).is_file())
    for group in ("main_figures", "supp_figures", "main_tables", "supp_tables"):
        for entry in plan.get(group, []):
            rel = str(entry.get("file", "")).strip()
            if not rel:
                raise ValueError(f"{entry.get('id', '?')}: no rendered display file in the plan")
            files.add(rel)
    out = {}
    for rel in sorted(files):
        norm, path = _safe_path(project, rel)
        if not path.is_file():
            raise ValueError(f"review input missing: {norm}")
        out[norm] = _sha256(path)
    return out


def evidence_block(project: Path) -> str:
    """The fenced block an agent pastes into the review report."""
    payload = {"reviewed_artifacts": reader_inputs(project)}
    return "```json\n" + json.dumps(payload, indent=2, ensure_ascii=False) + "\n```"


def verify(project: Path) -> list[str]:
    try:
        report = (project / REVIEW_REL).read_text(encoding="utf-8")
    except OSError as exc:
        return [f"{REVIEW_REL} unreadable: {exc}"]
    blocks = []
    for raw in re.findall(r"```json\s*\n(.*?)\n```", report, re.S):
        try:
            doc = json.loads(raw)
        except ValueError:
            continue
        if isinstance(doc, dict) and "reviewed_artifacts" in doc:
            blocks.append(doc["reviewed_artifacts"])
    problems: list[str] = []
    if len(blocks) != 1:
        problems.append(f"{REVIEW_REL} must embed exactly one ```json block with "
                        f"reviewed_artifacts (found {len(blocks)})")
    else:
        try:
            current = reader_inputs(project)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return [f"cannot inventory the review inputs: {exc}"]
        claimed = blocks[0] if isinstance(blocks[0], dict) else {}
        claimed = {str(k): str(v).upper() for k, v in claimed.items()}
        missing = sorted(set(current) - set(claimed))
        changed = sorted(k for k in current if k in claimed and claimed[k] != current[k])
        if missing:
            problems.append("reviewer was not given: " + ", ".join(missing[:6]))
        if changed:
            problems.append("changed since the review: " + ", ".join(changed[:6]))
    for heading in SECTIONS:
        match = re.search(r"(?mi)^#{1,3}\s+" + re.escape(heading) + r"\s*$\n(.*?)(?=^#{1,3}\s|\Z)",
                          report, re.S | re.M)
        if not match or len(match.group(1).strip()) < MIN_SECTION_CHARS:
            problems.append(f"needs a substantive '{heading}' section "
                            f"(>= {MIN_SECTION_CHARS} characters), not only a verdict label")
    return problems
