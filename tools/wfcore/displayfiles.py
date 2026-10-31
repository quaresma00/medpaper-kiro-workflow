"""1.15.0 (E6): main figures and main tables also as separate upload files.

target_journal.json `separate_display_files` (default ON for 1.15.0 papers unless the journal
forbids it: false | "forbidden"). The bundle then also holds

    Fig1.tif, Fig2.tif ...      byte-identical copies of the certified TIFF masters
                                (05_figures/out/<stem>.tif next to each planned figure file)
    Table1.xlsx ...             byte-identical copies of the certified table workbooks

named per `display_file_names` ({"figure": "Fig{n}.tif", "table": "Table{n}.xlsx"} by default).
The Word tables are built from the same workbooks, so footnotes come from one source. The
manifest (and so the upload list in SUBMISSION_CHECKLIST.md) is updated automatically; items
are marked "generated_by": "separate_display_files". Masters are never resampled: a TIFF below
the journal's figure_dpi is reported, not "fixed".
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

MANIFEST = "08_submission/bundle/manifest.json"
BUNDLE = "08_submission/bundle"
TAG = "separate_display_files"


def _sha(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def _plan(project: Path) -> dict:
    try:
        return json.loads((Path(project) / "01_protocol/artifact_plan.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def tiff_master(project: Path, entry: dict) -> Path | None:
    raw = str(entry.get("file", "")).strip()
    if not raw:
        return None
    base = Path(project) / raw
    for cand in (base.with_suffix(".tif"), base.with_suffix(".tiff"), base):
        if cand.is_file() and cand.suffix.casefold() in (".tif", ".tiff"):
            return cand
    return None


def wanted(project: Path) -> tuple[list[tuple[Path, str, str]], list[str]]:
    """[(master, bundle rel, role)], problems."""
    from . import journalspec
    project = Path(project)
    target = journalspec.load(project)
    if not target or not journalspec.separate_display_files(target, project):
        return [], []
    names = journalspec.display_file_names(target)
    plan = _plan(project)
    out, problems = [], []
    for n, e in enumerate(plan.get("main_figures", []) or [], 1):
        master = tiff_master(project, e)
        if master is None:
            problems.append(f"{e.get('id', f'Figure {n}')}: no TIFF master next to {e.get('file')} "
                            "(render TIFF, or set separate_display_files false when the journal "
                            "forbids separate figure files)")
            continue
        dpi = journalspec.figure_dpi(target)
        if dpi:
            try:
                from PIL import Image
                with Image.open(master) as im:
                    have = im.info.get("dpi", (0, 0))[0]
                if have and have + 0.5 < dpi:
                    problems.append(f"{master.name}: {have:.0f} dpi < the journal's {dpi} dpi "
                                    "(re-render the master; masters are never resampled)")
            except Exception:  # noqa: BLE001 - dpi is advisory when the file cannot be read
                pass
        out.append((master, f"{BUNDLE}/{names['figure'].format(n=n)}", "figures"))
    for n, e in enumerate(plan.get("main_tables", []) or [], 1):
        src = Path(project) / str(e.get("file", ""))
        if not src.is_file() or src.suffix.casefold() != ".xlsx":
            problems.append(f"{e.get('id', f'Table {n}')}: no certified workbook at {e.get('file')}")
            continue
        out.append((src, f"{BUNDLE}/{names['table'].format(n=n)}", "tables"))
    return out, problems


def sync(project: Path) -> list[str]:
    """Copy/update the separate display files and the manifest; returns what was written."""
    project = Path(project)
    files, problems = wanted(project)
    man_path = project / MANIFEST
    if not man_path.is_file() or (not files and not problems):
        return []
    if problems:
        raise ValueError("; ".join(problems[:6]))
    from .revision import guard_outputs, record_derived
    manifest = json.loads(man_path.read_text(encoding="utf-8"))
    items = [i for i in manifest.get("items", []) if i.get("generated_by") != TAG]
    old = {i.get("file") for i in manifest.get("items", []) if i.get("generated_by") == TAG}
    written: list[str] = []
    targets = [project / rel for _m, rel, _r in files]
    guard_outputs(project, targets + [man_path])
    for master, rel, role in files:
        dest = project / rel
        if not dest.is_file() or _sha(dest) != _sha(master):
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(master, dest)
            written.append(rel)
        items.append({"file": rel, "role": role, "upload": True, "required_by": TAG,
                      "generated_by": TAG, "source": master.relative_to(project).as_posix()})
    for rel in sorted(old - {rel for _m, rel, _r in files}):
        stale = project / str(rel)
        if stale.is_file():
            stale.unlink()
            written.append(f"{rel} (removed)")
    new = {**manifest, "items": items}
    if new != manifest:
        man_path.write_text(json.dumps(new, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        written.append(MANIFEST)
    record_derived(project, [p for p in targets + [man_path] if p.is_file()])
    return written


def problems(project: Path) -> list[str]:
    """Separate display files that are missing or differ from their certified masters."""
    project = Path(project)
    files, probs = wanted(project)
    out = list(probs)
    for master, rel, _role in files:
        dest = project / rel
        if not dest.is_file():
            out.append(f"{rel} missing (run wf rebuild)")
        elif _sha(dest) != _sha(master):
            out.append(f"{rel} differs from its certified master {master.relative_to(project).as_posix()}")
    return out
