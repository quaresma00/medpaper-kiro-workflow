"""1.14.0 (D1): a short factual record of the material scientific decisions, for reviewers.

What was pre-specified (protocol v1, written at S03 before the data were analysed) and what
was decided after the data were seen (protocol_final at S06, the internal plan-change log
.wf/protocol_changes.md, analyses marked "additional" in 03_analysis/analysis_manifest.json).
Taken only from those structured paper records - no orchestrator opinion. It is written into
the reviewer bundles (.wf/review_bundle/...) and nowhere else: never the writer bundle, the
manuscript, the supplementary files or an export. The manuscript still describes the analysis
performed and labels post hoc analyses as exploratory.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

NAME = "decision_record.md"
V1, FINAL = "01_protocol/protocol_v1.md", "01_protocol/protocol_final.md"
CHANGES, MANIFEST = ".wf/protocol_changes.md", "03_analysis/analysis_manifest.json"
ITEMS = (
    ("Primary outcome", r"primary\s+(?:outcome|end\s*-?\s*point)s?"),
    ("Exposure", r"exposures?|interventions?"),
    ("Comparator", r"comparators?|comparison\s+group|reference\s+group|control\s+group"),
    ("Main model", r"main\s+(?:model|analysis)|primary\s+(?:model|analysis|statistical\s+model)"),
)
_PRECEDENT_RE = re.compile(r"(?ims)^#{1,6}\s+Design\s+precedent\b.*?(?=^#{1,6}\s|\Z)")
CHECK_LINE = ("Check: every analysis decided after the data were seen is labelled exploratory "
              "(post hoc) in the manuscript and is never presented as confirmatory; the "
              "manuscript describes the analysis performed and never quotes this record.")


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _short(text: str, n: int = 160) -> str:
    text = " ".join(str(text).replace("|", "/").split())
    return text if len(text) <= n else text[:n - 3] + "..."


def extract(text: str) -> dict[str, str]:
    """{item: value} from 'Primary outcome: ...' lines (the Design precedent section excluded)."""
    text = _PRECEDENT_RE.sub("", text or "")
    out: dict[str, str] = {}
    for label, pat in ITEMS:
        for m in re.finditer(r"(?im)^\s*(?:[-*+]|\d+[.)])?\s*(?:\*\*|__)?(?:" + pat
                             + r")(?:\s+[A-Za-z-]+){0,3}?(?:\*\*|__)?\s*(?:\([^)\n]*\))?\s*"
                             r"(?:\*\*|__)?\s*[:：]\s*(?:\*\*|__)?\s*(\S.*)$", text):
            value = m.group(1).strip()
            if not re.match(r"(?i)(?:precedent\s+(?:yes|no)|not\s+applicable)\b", value):
                out[label] = value
                break
    return out


def _same(a: str, b: str) -> bool:
    norm = lambda s: re.sub(r"[\W_]+", " ", s.casefold()).strip()  # noqa: E731
    return norm(a) == norm(b)


def build(project: Path) -> str:
    """The record as Markdown ('' when the paper has none of the source records yet)."""
    project = Path(project)
    v1_text, final_text = _read(project / V1), _read(project / FINAL)
    changes = [ln.strip().lstrip("-*+ ").strip() for ln in _read(project / CHANGES).splitlines()
               if ln.strip() and not ln.lstrip().startswith("#")]
    try:
        scripts = json.loads(_read(project / MANIFEST) or "{}").get("scripts", [])
    except (ValueError, AttributeError):
        scripts = []
    extra = [s for s in scripts if isinstance(s, dict)
             and str(s.get("role", "")).strip().casefold() == "additional"]
    if not (v1_text or final_text or changes or extra):
        return ""
    v1, final = extract(v1_text), extract(final_text)
    lines = ["# Material scientific decisions (factual record for the reviewer only)", "",
             f"Sources: {V1} (pre-specified at S03, before the analysis), {FINAL} (S06, after "
             f"the analysis), {CHANGES} (plan changes), {MANIFEST} (analysis roles). Quoted, "
             "not interpreted. Never exported to the manuscript or supplementary files.", "",
             "| Decision | Pre-specified (protocol v1) | Final (protocol final) | Status |",
             "|---|---|---|---|"]
    for label, _ in ITEMS:
        a, b = v1.get(label, ""), final.get(label, "")
        if not a and not b:
            status = "not stated in either protocol"
        elif not a:
            status = "not stated in protocol v1 (decided after the data were seen)"
        elif not b or _same(a, b):
            status = "as pre-specified"
        else:
            status = "changed after the data were seen"
        lines.append(f"| {label} | {_short(a) or '-'} | {_short(b) or '-'} | {status} |")
    lines += ["", "## Plan changes recorded at S06 (verbatim)", ""]
    lines += [f"- {_short(c, 240)}" for c in changes[:20]] or ["- none recorded"]
    lines += ["", "## Analyses added after the planned analyses were done (role additional)", ""]
    lines += [f"- {s.get('path', '?')}: {_short(s.get('decision', ''), 200) or '(no decision line)'}"
              for s in extra[:20]] or ["- none"]
    return "\n".join(lines + ["", CHECK_LINE]) + "\n"


def write(project: Path, folder: Path) -> Path | None:
    """Write the record into a reviewer bundle folder; None when there is nothing to record."""
    text = build(project)
    if not text:
        return None
    out = Path(folder) / NAME
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return out
