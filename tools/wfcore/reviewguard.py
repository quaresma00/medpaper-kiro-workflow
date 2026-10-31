"""1.15.0 (E2): a review may write its report and nothing else.

The medpaper-reviewer subagent may write exactly one file - the report.md path printed by
`review_round.py start` / `rework.py check` - and its prompt says so. The host cannot be
trusted to enforce that, so the engine checks it: when a review bundle is written a cheap
snapshot (size + mtime) of the paper's own files is taken; when the report is ingested
(`review_round.py close`, meaning verdicts) every paper file that changed between the
snapshot and the moment the report was written is listed and the report is refused. Edits the
agent makes AFTER the report was written (applying the findings) are not "during the review".

Fallback for hosts where the subagent cannot write: `review_round.py ingest --from <file>` and
`rework.py meaning-ingest --from <file>` take a saved reply or a host workflow-state JSON and
copy the text between <<<REPORT>>> and <<<END>>> verbatim (never paraphrased).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

DIR = ".wf/review_guard"
SKIP_TOP = {".wf", "temp", ".kiro", ".git", ".venv", "__pycache__", ".wf_archive"}
START, END = "<<<REPORT>>>", "<<<END>>>"


def _walk(project: Path) -> dict[str, list[int]]:
    out: dict[str, list[int]] = {}
    project = Path(project)
    for top, dirs, files in os.walk(project):
        rel_top = os.path.relpath(top, project)
        if rel_top == ".":
            dirs[:] = [d for d in dirs if d not in SKIP_TOP]
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in files:
            full = os.path.join(top, name)
            try:
                st = os.stat(full)
            except OSError:
                continue
            rel = os.path.relpath(full, project).replace("\\", "/")
            out[rel] = [st.st_size, st.st_mtime_ns]
    return out


def take(project: Path, key: str) -> Path:
    path = Path(project) / DIR / f"{key}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"at": time.time(), "files": _walk(project)}), encoding="utf-8")
    return path


def problems(project: Path, key: str, report: Path, declared=()) -> list[str]:
    """Paper files changed between the bundle snapshot and the report's write time. Files the
    caller declares as its own fixes (review_round close --change FILE) are not counted."""
    from .journalspec import since_1150
    if not since_1150(project):
        return []  # a stricter check: papers pinned before 1.15.0 get it after wf migrate --yes
    try:
        snap = json.loads((Path(project) / DIR / f"{key}.json").read_text(encoding="utf-8"))
        t_report = Path(report).stat().st_mtime
    except (OSError, ValueError):
        return []  # no snapshot (bundle from an older engine) or no report: nothing to judge
    t0, before = float(snap.get("at", 0)), snap.get("files") or {}
    mine = {str(d).replace("\\", "/").strip() for d in declared}
    out = []
    for rel, sig in sorted(_walk(project).items()):
        if before.get(rel) == sig or rel in mine:
            continue
        mtime = sig[1] / 1e9
        if t0 - 1 <= mtime <= t_report + 1:
            out.append(rel)
    return out


def extract_report(text: str) -> str:
    """The report verbatim: from a saved reply, or the newest string holding the markers in
    a host workflow-state JSON."""
    text = text or ""
    try:
        data = json.loads(text)
    except ValueError:
        data = None
    if data is not None:
        found: list[str] = []

        def walk(x):
            if isinstance(x, str):
                if START in x:
                    found.append(x)
            elif isinstance(x, dict):
                for v in x.values():
                    walk(v)
            elif isinstance(x, list):
                for v in x:
                    walk(v)
        walk(data)
        if not found:
            return ""
        text = found[-1]
    if START not in text:
        return text.strip() + "\n" if text.strip() else ""
    body = text.rsplit(START, 1)[1]
    for end in (END, "<<<END REPORT>>>", "<<</REPORT>>>"):
        if end in body:
            body = body.split(end, 1)[0]
            break
    return body.strip("\n") + "\n"


def ingest(project: Path, src: Path, dest: Path) -> Path:
    """Write the extracted report to `dest`, dated like the saved source (so edits made after
    the reviewer replied do not count as made during the review)."""
    from .argtext import read_text_retry
    raw = read_text_retry(Path(src))
    report = extract_report(raw)
    if not report.strip():
        raise ValueError(f"no report found in {src} (expected text between {START} and {END})")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(report, encoding="utf-8")
    t = Path(src).stat().st_mtime
    os.utime(dest, (t, t))
    return dest
