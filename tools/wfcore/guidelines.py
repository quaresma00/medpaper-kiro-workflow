"""1.15.0 (E7): the journal guideline snapshot is dated and can be refreshed.

08_submission/guidelines_extract.md was written once at S20 and had no update path, so later
audits judged the package against an old reading. `wf guidelines refresh --from <file>`
installs a newly written extract (from the re-fetched official guide), puts a dated snapshot
line at its top and keeps the previous one in 08_submission/guidelines_history/. Audits and
checks always read 08_submission/guidelines_extract.md, i.e. the latest snapshot.
"""
from __future__ import annotations

import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

REL = "08_submission/guidelines_extract.md"
HISTORY = "08_submission/guidelines_history"
STAMP_RE = re.compile(r"(?m)^<!-- guideline snapshot: (\d{4}-\d{2}-\d{2})(?:; source: (.*?))? -->\s*$")


def snapshot_date(text: str) -> str | None:
    m = STAMP_RE.search(text or "")
    return m.group(1) if m else None


def status(project: Path) -> str:
    path = Path(project) / REL
    if not path.is_file():
        return "no guideline snapshot (08_submission/guidelines_extract.md missing)"
    text = path.read_text(encoding="utf-8", errors="replace")
    day = snapshot_date(text)
    if day is None:
        return "guideline snapshot undated (wf guidelines refresh dates it)"
    return f"guideline snapshot dated {day}"


def refresh(project: Path, src: Path, source: str = "") -> tuple[Path, str | None]:
    project = Path(project)
    if not Path(src).is_file():
        raise ValueError(f"{src} not found")
    new = Path(src).read_text(encoding="utf-8", errors="replace")
    if len(new.strip()) < 200:
        raise ValueError("the new extract is too short to be a guideline extract (>= 200 characters)")
    dest = project / REL
    archived = None
    if dest.is_file():
        old = dest.read_text(encoding="utf-8", errors="replace")
        day = snapshot_date(old) or datetime.fromtimestamp(
            dest.stat().st_mtime, timezone.utc).strftime("%Y-%m-%d")
        hist = project / HISTORY
        hist.mkdir(parents=True, exist_ok=True)
        n = len(list(hist.glob("*.md"))) + 1
        target = hist / f"guidelines_extract_{day}_{n:02d}.md"
        shutil.copyfile(dest, target)
        archived = target.relative_to(project).as_posix()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    body = STAMP_RE.sub("", new).lstrip("\n")
    stamp = f"<!-- guideline snapshot: {today}" + (f"; source: {source.strip()}" if source.strip()
                                                    else "") + " -->\n"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(stamp + body, encoding="utf-8")
    from .revision import record_derived
    record_derived(project, [dest])
    return dest, archived


def section(project: Path, pattern: str, width: int = 1200) -> str:
    """The guideline text around the first match of `pattern` (e.g. the AI/LLM-use rule)."""
    path = Path(project) / REL
    text = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
    m = re.search(pattern, text)
    if not m:
        return ""
    start = text.rfind("\n#", 0, m.start())
    start = 0 if start < 0 else start + 1
    nxt = re.search(r"(?m)^#{1,3}\s", text[m.end():])
    end = m.end() + nxt.start() if nxt else len(text)
    return text[start:min(end, start + width)].strip()
