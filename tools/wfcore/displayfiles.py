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


PIL_FORMAT = {"tiff": ("TIFF", ".tif"), "png": ("PNG", ".png"), "pdf": ("PDF", ".pdf"),
              "eps": ("EPS", ".eps"), "jpeg": ("JPEG", ".jpg")}
MODES = {"rgb": "RGB", "cmyk": "CMYK", "grayscale": "L", "greyscale": "L"}


def conversion(project: Path, target: dict) -> tuple[str | None, str | None, list[str]]:
    """1.18.0 (K3): target_journal.json figure {formats, colour} -> (format, colour mode,
    problems). (None, None, []) = byte-identical TIFF copies (the default; a paper pinned
    before 1.18.0 keeps it until `wf migrate --yes`)."""
    from .checks.v1180 import since_1180_project
    spec = target.get("figure") if isinstance(target.get("figure"), dict) else {}
    if not spec or not since_1180_project(project):
        return None, None, []
    fmts = [str(f).casefold().replace("tif", "tiff").replace("tifff", "tiff").replace("jpg", "jpeg")
            for f in spec.get("formats") or []]
    mode = MODES.get(str(spec.get("colour") or spec.get("color") or "").casefold())
    if not fmts or "tiff" in fmts:
        return ("tiff", mode, []) if mode else (None, None, [])
    fmt = next((f for f in fmts if f in PIL_FORMAT), None)
    if fmt is None:
        return None, None, [f"figure.formats {spec.get('formats')}: the engine converts the TIFF "
                            "masters only to TIFF, PNG, PDF, EPS or JPEG; export the others by hand "
                            "and list them in the manifest"]
    return fmt, mode, []


def convert(master: Path, dest: Path, fmt: str, mode: str | None) -> None:
    from PIL import Image
    with Image.open(master) as im:
        dpi = im.info.get("dpi") or (300, 300)
        img = im.convert(mode) if mode and im.mode != mode else im.copy()
    if fmt in ("jpeg", "eps", "pdf") and img.mode not in ("RGB", "L", "CMYK"):
        img = img.convert("RGB")
    dest.parent.mkdir(parents=True, exist_ok=True)
    name = PIL_FORMAT[fmt][0]
    if fmt == "pdf":
        img.save(dest, name, resolution=float(dpi[0]))
    elif fmt == "tiff":
        img.save(dest, name, dpi=dpi, compression="tiff_lzw")
    else:
        img.save(dest, name, dpi=dpi)


def wanted(project: Path) -> tuple[list[tuple[Path, str, str]], list[str]]:
    """[(master, bundle rel, role)], problems."""
    from . import journalspec
    project = Path(project)
    target = journalspec.load(project)
    if not target or not journalspec.separate_display_files(target, project):
        return [], []
    names = journalspec.display_file_names(target)
    fmt, _mode, conv_problems = conversion(project, target)
    if fmt:
        names = {**names, "figure": str(Path(names["figure"]).with_suffix(PIL_FORMAT[fmt][1]))}
    plan = _plan(project)
    out, problems = [], list(conv_problems)
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
    from . import journalspec
    fmt, mode, _p = conversion(project, journalspec.load(project))
    before = {i.get("file"): i for i in manifest.get("items", []) if i.get("generated_by") == TAG}
    for master, rel, role in files:
        dest = project / rel
        item = {"file": rel, "role": role, "upload": True, "required_by": TAG,
                "generated_by": TAG, "source": master.relative_to(project).as_posix()}
        if fmt and role == "figures":
            item.update(converted_to=fmt + (f"/{mode}" if mode else ""), source_sha256=_sha(master))
            prev = before.get(rel) or {}
            if not dest.is_file() or {k: prev.get(k) for k in ("converted_to", "source_sha256")} \
                    != {k: item[k] for k in ("converted_to", "source_sha256")}:
                convert(master, dest, fmt, mode)
                written.append(rel)
        elif not dest.is_file() or _sha(dest) != _sha(master):
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(master, dest)
            written.append(rel)
        items.append(item)
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
    from . import journalspec
    fmt, _mode, _p = conversion(project, journalspec.load(project))
    try:
        listed = {i.get("file"): i for i in json.loads((project / MANIFEST).read_text(
            encoding="utf-8")).get("items", [])}
    except (OSError, ValueError):
        listed = {}
    for master, rel, role in files:
        dest = project / rel
        if not dest.is_file():
            out.append(f"{rel} missing (run wf rebuild)")
        elif fmt and role == "figures":
            if (listed.get(rel) or {}).get("source_sha256") != _sha(master):
                out.append(f"{rel} was converted from an older master (run wf rebuild)")
        elif _sha(dest) != _sha(master):
            out.append(f"{rel} differs from its certified master {master.relative_to(project).as_posix()}")
    return out
