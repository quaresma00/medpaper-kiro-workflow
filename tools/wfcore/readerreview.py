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


COVERAGE_REL = ".wf/review_coverage.json"
TEXT_DIR_REL = ".wf/review_text"


def _coverage(project: Path) -> dict[str, str]:
    try:
        data = json.loads((project / COVERAGE_REL).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k): str(v).upper() for k, v in data.items()} if isinstance(data, dict) else {}


def delta_inputs(project: Path) -> dict[str, str]:
    """Changed inputs since the last passing review, plus their dependants among the inputs."""
    from .dependencies import closure
    current, covered = reader_inputs(project), _coverage(project)
    changed = [r for r, h in current.items() if covered.get(r) != h]
    if not covered:
        return current
    try:
        dependants = set(closure(project, changed))
    except Exception:  # noqa: BLE001 - a broken plan falls back to the changed files alone
        dependants = set()
    return {r: h for r, h in current.items() if r in changed or r in dependants}


def evidence_block(project: Path, delta: bool = False) -> str:
    """The fenced block an agent pastes into the review report.

    delta=True lists only what changed since the last passing review (and its dependants);
    the unchanged files keep the earlier review's coverage, bound by their hashes.
    """
    payload = ({"mode": "delta", "reviewed_artifacts": delta_inputs(project)} if delta
               else {"reviewed_artifacts": reader_inputs(project)})
    return "```json\n" + json.dumps(payload, indent=2, ensure_ascii=False) + "\n```"


def write_text_copies(project: Path, rels) -> list[str]:
    """Hash-bound plain-text copies of DOCX/XLSX inputs for read-only reviewers.

    Regenerated on every call and stale copies removed, so a reviewer can never be handed an
    outdated temp extract. The first lines name the source file and its SHA-256.
    """
    from . import xlsxlite
    from .packagecontent import visible_text
    out_dir = project / TEXT_DIR_REL
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for rel in sorted(rels):
        path = project / rel
        if path.suffix.lower() not in (".docx", ".xlsx") or not path.is_file():
            continue
        if path.suffix.lower() == ".docx":
            body = visible_text(path)
        else:
            book = xlsxlite.Workbook(path)
            body = "\n\n".join(f"## sheet {s.name}\n" + "\n".join(
                "\t".join(s.row_text(r)) for r in range(1, s.max_row + 1)) for s in book.sheets)
        target = out_dir / (rel.replace("/", "__") + ".txt")
        target.write_text(f"# source: {rel}\n# sha256: {_sha256(path)}\n\n{body}\n", encoding="utf-8")
        written.append(target.relative_to(project).as_posix())
    for stale in out_dir.glob("*.txt"):
        if stale.relative_to(project).as_posix() not in written:
            stale.unlink()
    return written


def prior_coverage(project: Path) -> dict[str, set[str]]:
    """Paper-relative path -> every hash an earlier review saw (coverage record + rounds)."""
    out: dict[str, set[str]] = {}
    for rel, digest in _coverage(project).items():
        out.setdefault(rel, set()).add(digest.upper())
    try:
        from .reviewrounds import load
        rounds = load(project).get("manuscript", [])
    except Exception:  # noqa: BLE001 - unreadable rounds simply add no coverage
        rounds = []
    for rnd in rounds:
        if not rnd.get("closed_at"):
            continue
        for rel in rnd.get("reviewed", []):
            for src in (rnd.get("inputs") or {}, rnd.get("after") or {}):
                if src.get(rel):
                    out.setdefault(rel, set()).add(str(src[rel]).upper())
    return out


def record_coverage(project: Path) -> None:
    (project / COVERAGE_REL).parent.mkdir(parents=True, exist_ok=True)
    (project / COVERAGE_REL).write_text(json.dumps(reader_inputs(project), indent=2) + "\n",
                                        encoding="utf-8")


def verify(project: Path) -> list[str]:
    try:
        report = (project / REVIEW_REL).read_text(encoding="utf-8")
    except OSError as exc:
        return [f"{REVIEW_REL} unreadable: {exc}"]
    blocks = []
    delta = False
    for raw in re.findall(r"```json\s*\n(.*?)\n```", report, re.S):
        try:
            doc = json.loads(raw)
        except ValueError:
            continue
        if isinstance(doc, dict) and "reviewed_artifacts" in doc:
            blocks.append(doc["reviewed_artifacts"])
            delta = doc.get("mode") == "delta"
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
        # 1.12.0 (A4): coverage is always incremental. A file is covered when ANY earlier
        # passing review or closed manuscript review round saw exactly its current bytes;
        # only files whose hash changed since then need a (delta) review.
        known = prior_coverage(project)
        if delta and not known:
            problems.append("delta review needs an earlier passing full review on record")
        for rel, digest in claimed.items():
            known.setdefault(rel, set()).add(digest)
        current_u = {k: v.upper() for k, v in current.items()}
        uncovered = sorted(k for k, v in current_u.items() if v not in known.get(k, set()))
        never = [k for k in uncovered if k not in known]
        changed = [k for k in uncovered if k in known]
        if never:
            problems.append("reviewer was not given: " + ", ".join(never[:6]))
        if changed:
            problems.append("changed since the review (re-review only these: "
                            "review_round.py start --delta): " + ", ".join(changed[:6]))
    for heading in SECTIONS:
        match = re.search(r"(?mi)^#{1,3}\s+" + re.escape(heading) + r"\s*$\n(.*?)(?=^#{1,3}\s|\Z)",
                          report, re.S | re.M)
        if not match or len(match.group(1).strip()) < MIN_SECTION_CHARS:
            problems.append(f"needs a substantive '{heading}' section "
                            f"(>= {MIN_SECTION_CHARS} characters), not only a verdict label")
    if not problems:
        try:
            record_coverage(project)
        except (OSError, ValueError):
            pass
    return problems
