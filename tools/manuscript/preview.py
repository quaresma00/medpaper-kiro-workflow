#!/usr/bin/env python3
"""Render DOCX / XLSX / PDF uploads to a PNG contact sheet for the visual checks (1.9.0, #22).

    .\\.venv\\Scripts\\python.exe tools/manuscript/preview.py 08_submission/bundle/manuscript.docx
    .\\.venv\\Scripts\\python.exe tools/manuscript/preview.py 04_tables/main/Table1.xlsx --pages 1-4

Conversion: LibreOffice (soffice --headless) when installed, else Microsoft Word / Excel through
COM on Windows. Rasterising: PyMuPDF when importable, else pdftoppm. The sheet goes to the
paper's temp/preview/ with a unique per-run suffix, so an image viewer never shows a cached
older picture under the same name. Nothing is written inside the engine.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from wfcore import paths as wfpaths  # noqa: E402

COM = {
    ".docx": ("Word.Application",
              "$d = $a.Documents.Open($env:MP_IN, $false, $true); $d.SaveAs([ref]$env:MP_OUT, [ref]17); "
              "$d.Close($false)"),
    ".xlsx": ("Excel.Application",
              "$a.DisplayAlerts = $false; $d = $a.Workbooks.Open($env:MP_IN, 0, $true); "
              "$d.ExportAsFixedFormat(0, $env:MP_OUT); $d.Close($false)"),
}


def to_pdf(src: Path, work: Path) -> Path:
    if src.suffix.casefold() == ".pdf":
        return src
    out = work / (src.stem + ".pdf")
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice:
        subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", str(work), str(src)],
                       capture_output=True, timeout=300)
    elif os.name == "nt" and src.suffix.casefold() in COM:
        app, body = COM[src.suffix.casefold()]
        script = (f"$a = New-Object -ComObject {app}; $a.Visible = $false; "
                  f"try {{ {body} }} finally {{ $a.Quit() }}")
        env = {**os.environ, "MP_IN": str(src.resolve()), "MP_OUT": str(out.resolve())}
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                       capture_output=True, text=True, env=env, timeout=300)
    if not out.is_file():
        raise RuntimeError("cannot convert to PDF: install LibreOffice, or Microsoft Word/Excel")
    return out


def _pages(spec: str | None, total: int) -> list[int]:
    if not spec:
        return list(range(min(total, 12)))
    out = []
    for part in spec.split(","):
        a, _, b = part.partition("-")
        lo, hi = int(a), int(b or a)
        out.extend(range(lo - 1, min(hi, total)))
    return [p for p in out if 0 <= p < total]


def rasterise(pdf: Path, work: Path, pages: str | None, dpi: int) -> list[Path]:
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(pdf)
        out = []
        for i in _pages(pages, doc.page_count):
            pix = doc[i].get_pixmap(dpi=dpi)
            p = work / f"page-{i + 1:03d}.png"
            pix.save(p)
            out.append(p)
        return out
    except ImportError:
        pass
    exe = shutil.which("pdftoppm")
    if not exe:
        raise RuntimeError("cannot rasterise: install PyMuPDF (pip) or poppler's pdftoppm")
    first_last = []
    if pages and "-" in pages and "," not in pages:
        a, b = pages.split("-")
        first_last = ["-f", a, "-l", b]
    elif not pages:
        first_last = ["-f", "1", "-l", "12"]
    subprocess.run([exe, "-png", "-r", str(dpi), *first_last, str(pdf), str(work / "page")],
                   capture_output=True, timeout=300)
    return sorted(work.glob("page*.png"))


def contact_sheet(images: list[Path], out: Path, columns: int) -> Path:
    from PIL import Image, ImageDraw
    tiles = [Image.open(p).convert("RGB") for p in images]
    if not tiles:
        raise RuntimeError("no pages rendered")
    w = max(t.width for t in tiles)
    h = max(t.height for t in tiles)
    cols = max(1, min(columns, len(tiles)))
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * (w + 20) + 20, rows * (h + 50) + 20), "#c8c8c8")
    draw = ImageDraw.Draw(sheet)
    for i, t in enumerate(tiles):
        x, y = 20 + (i % cols) * (w + 20), 20 + (i // cols) * (h + 50)
        sheet.paste(t, (x, y + 30))
        draw.text((x, y + 8), f"page {images[i].stem.split('-')[-1].lstrip('0') or '1'}", fill="black")
    sheet.save(out)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="render uploads to a PNG contact sheet")
    ap.add_argument("files", nargs="+", type=Path, help="paper-relative or absolute DOCX/XLSX/PDF")
    ap.add_argument("--pages", help="e.g. 1-4 or 1,3,5 (default: first 12 pages)")
    ap.add_argument("--dpi", type=int, default=60)
    ap.add_argument("--columns", type=int, default=4)
    args = ap.parse_args(argv)
    proj = wfpaths.project_dir()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    outdir = wfpaths.paper_output_path(f"project/temp/preview")
    outdir.mkdir(parents=True, exist_ok=True)
    rc = 0
    for raw in args.files:
        src = raw if raw.is_absolute() else proj / raw
        if not src.is_file():
            print(f"missing: {src}")
            rc = 2
            continue
        try:
            with tempfile.TemporaryDirectory(prefix="medpaper_preview_") as tmp:
                work = Path(tmp)
                pdf = to_pdf(src, work)
                images = rasterise(pdf, work, args.pages, args.dpi)
                out = contact_sheet(images, outdir / f"{src.stem}-{stamp}.png", args.columns)
        except Exception as exc:  # noqa: BLE001
            print(f"{src.name}: preview failed: {exc}")
            rc = 2
            continue
        print(f"{src.name}: {len(images)} page(s) -> {out}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
