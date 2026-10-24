"""1.9.0 (#24): a legal end state when the author edits the upload copy by hand.

Some journal requirements cannot be met inside the workflow, and the author may choose to
finish them directly in a copy of the uploads. Before 1.9.0 the run could only stop at S25 =
REVISE. Now:

    08_submission/final_copy/<same file name as in the bundle>   the author's edited copies
    tools/final_copy.py record --edit "..." [--edit ...] --words "<author's authorisation>"
    tools/final_copy.py check                                    deterministic comparison

`check` compares each copy with the frozen bundle file of the same name: every number (values,
citation numbers, years), every figure/table reference and the file's validity must be
unchanged; registered administrative facts (author_info.json) may be added; for a double-blind
journal the review-facing copies must stay anonymous. It records hashes in .wf/final_copy.json.
S25 may then close with `submission_package_independent_audit = PASS_AUTHOR_FINAL_COPY`, which
the `final_copy_verified` gate accepts only while the recorded check matches the copies.
"""
from __future__ import annotations

import json
import re
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

DIR = "08_submission/final_copy"
REL = ".wf/final_copy.json"
SUFFIXES = (".docx", ".xlsx")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load(project: Path) -> dict:
    try:
        data = json.loads((Path(project) / REL).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    return data if isinstance(data, dict) else {}


def _save(project: Path, data: dict) -> None:
    path = Path(project) / REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def copies(project: Path) -> list[Path]:
    root = Path(project) / DIR
    return sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.casefold() in SUFFIXES) \
        if root.is_dir() else []


def text_of(path: Path) -> str:
    if path.suffix.casefold() == ".docx":
        from .packagecontent import visible_text
        return visible_text(path)
    from .xlsxlite import Workbook
    return "\n".join(str(c.value) for sh in Workbook(path).sheets for c in sh.cells if c.value)


def record(project: Path, edits: list[str], words: str) -> dict:
    if not copies(project):
        raise ValueError(f"no edited copies under {DIR}/ (copy the bundle files there first)")
    if not edits or any(len(e.strip()) < 8 for e in edits):
        raise ValueError("list every manual edit (--edit, >= 8 characters each)")
    from .reviewrounds import CONFIRM_PHRASES, is_confirmation
    if not is_confirmation(words):
        # 1.10.0 (#13): the author's exact confirmation sentence, never a recognised phrase.
        raise ValueError(f"--words must be the author's exact sentence '{CONFIRM_PHRASES[0]}' "
                         f"(or '{CONFIRM_PHRASES[1]}')")
    data = load(project)
    data.update(edits=[e.strip() for e in edits], authorised=words.strip(), recorded_at=_now(),
                check=None)
    _save(project, data)
    return data


def compare(project: Path, original: Path, copy: Path) -> list[str]:
    from . import docxaudit, journalspec, presentation
    problems = []
    try:
        with zipfile.ZipFile(copy) as zf:
            if zf.testzip():
                return [f"{copy.name}: corrupt file"]
    except zipfile.BadZipFile:
        return [f"{copy.name}: not a valid Office file"]
    admin = presentation.admin_strings(project)
    before, after = text_of(original), text_of(copy)
    for s in admin:
        before, after = before.replace(s, " "), after.replace(s, " ")
    fb, fa = presentation.text_facts(before), presentation.text_facts(after)
    for key, label in (("numbers", "numbers/citations"), ("artifacts", "figure/table references")):
        lost = Counter(fb[key]) - Counter(fa[key])
        new = Counter(fa[key]) - Counter(fb[key])
        if lost:
            problems.append(f"{copy.name}: {label} removed: " + ", ".join(sorted(lost.elements()))[:160])
        if new and key == "numbers":
            # 1.11.0 (#3b): a small correction may add numbers that already exist in the
            # executed results (n/N and its percentage checked); anything else is refused.
            untraced = [t for t in sorted(new.elements()) if not traceable(project, t)]
            if untraced:
                problems.append(f"{copy.name}: numbers added that no results JSON holds: "
                                + ", ".join(untraced)[:160])
            problems += [f"{copy.name}: {p}" for p in ratio_problems(after)]
        elif new:
            problems.append(f"{copy.name}: {label} added: " + ", ".join(sorted(new.elements()))[:160])
    target = journalspec.load(project)
    if journalspec.blinded(target) and not any(k in copy.name.casefold()
                                               for k in ("title", "cover", "copyright")):
        problems += docxaudit.blinding_problems(copy, docxaudit.identity_strings(project))
    return problems


def _pool(project: Path) -> tuple[set[float], set[str]]:
    import json
    from .checks.numbers import _walk
    strings: set[str] = set()
    for p in sorted((Path(project) / "03_analysis/results").glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            data = {k: v for k, v in data.items() if k != "environment"}
        _walk(data, strings)
    floats = set()
    for s in strings:
        try:
            floats.add(float(s))
        except ValueError:
            pass
    return floats, strings


def traceable(project: Path, token: str) -> bool:
    """A number that exists (at its displayed precision) in 03_analysis/results/*.json."""
    from .checks.numbers import _matches
    floats, strings = _pool(project)
    return _matches(token, floats, strings)


def ratio_problems(text: str) -> list[str]:
    """'a/b (p%)' must be internally consistent at the displayed precision."""
    out = []
    for m in re.finditer(r"(\d[\d,]*)\s*/\s*(\d[\d,]*)\s*\(\s*(\d+(?:\.\d+)?)\s?%", text):
        a, b = int(m.group(1).replace(",", "")), int(m.group(2).replace(",", ""))
        p = m.group(3)
        dec = len(p.split(".")[1]) if "." in p else 0
        if b and abs(100.0 * a / b - float(p)) > 0.5 * 10 ** -dec + 1e-9:
            out.append(f"'{m.group(0)})': {a}/{b} is {100.0 * a / b:.{max(dec, 1)}f}%")
    return out


def check(project: Path) -> tuple[bool, list[str]]:
    from .determinism import raw_sha256
    project = Path(project)
    data = load(project)
    if not data.get("edits"):
        return False, ["no manual-edit list recorded (tools/final_copy.py record)"]
    bundle = project / "08_submission/bundle"
    problems, files = [], {}
    found = copies(project)
    if not found:
        problems.append(f"no edited copies under {DIR}/")
    for copy in found:
        original = bundle / copy.relative_to(project / DIR)
        if not original.is_file():
            problems.append(f"{copy.name}: no frozen bundle file of the same name to compare with")
            continue
        problems += compare(project, original, copy)
        files[copy.relative_to(project).as_posix()] = raw_sha256(copy)
    data["check"] = {"at": _now(), "ok": not problems, "problems": problems, "files": files}
    _save(project, data)
    return not problems, problems


def verified(project: Path) -> list[str]:
    """Why the recorded final-copy check does not hold now (empty = it holds)."""
    from .determinism import raw_sha256
    data = load(project)
    chk = data.get("check") or {}
    if not chk.get("ok"):
        return ["the final-copy check has not passed (tools/final_copy.py check)"]
    now = {p.relative_to(project).as_posix(): raw_sha256(p) for p in copies(project)}
    if now != chk.get("files"):
        return ["the edited copies changed after the last final-copy check; run it again"]
    return []
