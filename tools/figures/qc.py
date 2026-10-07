#!/usr/bin/env python3
"""Deterministic figure QC. Run this before spending a look at the figure.

    .venv/Scripts/python.exe tools/figures/qc.py --all
    .venv/Scripts/python.exe tools/figures/qc.py --figure "Figure 1"
    .venv/Scripts/python.exe tools/figures/qc.py --crop "Figure 1" --cols 2 --rows 1 --cell B

Reads PNGs with matplotlib.image (no Pillow needed) and merges the artist-level
sidecars that style.save() writes. Results go to 05_figures/qc/qc_report.json, which
the S11 gate reads.

What this cannot do: judge whether the figure is readable. That still needs a human or
a model looking at the image. Passing QC is necessary, not sufficient.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.image as mpimg  # noqa: E402
import numpy as np  # noqa: E402

_TOOLS = Path(__file__).resolve().parents[1]
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))
from wfcore import paths as wfpaths  # noqa: E402

MM_PER_IN = 25.4
WIDTHS_MM = {"single": 90.0, "1.5": 140.0, "double": 180.0}


def repo_root() -> Path:
    return wfpaths.repo_root()


def project_root() -> Path:
    return wfpaths.project_dir()


def _say(msg: str) -> None:
    """Print a hint with engine commands and the project/ alias valid from the agent's cwd."""
    try:
        proj = project_root()
    except SystemExit:
        proj = None
    print(wfpaths.localize_commands(msg, proj))


# The artist-audit sidecar schema shared by style.audit_figure (Python) and save_medpaper (R).
SIDECAR_KEYS = ("figure", "archetype", "n_axes", "min_font_pt", "max_font_pt", "min_line_pt",
                "text_clipped_at_edge", "axes_tightbbox_overlaps", "glyph_warnings",
                "tick_label_collisions", "interior_voids", "elements", "figure_text")
# Provenance keys written by save_medpaper() since 1.6.0; legacy sidecars without them still
# validate, but an R figure without them only warns until it is re-rendered.
PROVENANCE_KEYS = ("script", "script_sha256", "source_hashes", "render_hashes")
SIDECAR_OPTIONAL_KEYS = ("engine", *PROVENANCE_KEYS)


def targets() -> dict:
    """[targets] from pipeline.toml with the paper's .wf/config.toml overrides."""
    from wfcore import registry
    return registry.effective_targets(project_root())


def width_mm(width_class: str, tgt: dict) -> float:
    key = {"single": "column_width_mm_single", "double": "column_width_mm_double",
           "1.5": "column_width_mm_1_5"}.get(width_class)
    try:
        return float(tgt.get(key, WIDTHS_MM.get(width_class, 90.0)))
    except (TypeError, ValueError):
        return WIDTHS_MM.get(width_class, 90.0)


def _schema_problems(art: dict, png_stem: str) -> list[str]:
    from figures import elements as el
    problems = []
    keys = set(art)
    missing = [k for k in SIDECAR_KEYS if k not in keys]
    extra = sorted(keys - set(SIDECAR_KEYS) - set(SIDECAR_OPTIONAL_KEYS))
    if missing:
        problems.append("missing key(s): " + ", ".join(missing))
    if extra:
        problems.append("unknown key(s): " + ", ".join(extra))
    if "engine" in art and art["engine"] not in ("R", "python"):
        problems.append(f"engine must be R or python, got {art['engine']!r}")
    if art.get("figure") != png_stem:
        problems.append(f"figure {art.get('figure')!r} != PNG stem {png_stem!r}")
    if "archetype" in art and art["archetype"] is not None and not isinstance(art["archetype"], str):
        problems.append("archetype must be a string or null")
    n_axes = art.get("n_axes")
    if not isinstance(n_axes, int) or isinstance(n_axes, bool) or n_axes < 0:
        problems.append("n_axes must be an integer >= 0")
    for k in ("min_font_pt", "max_font_pt", "min_line_pt"):
        v = art.get(k)
        if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float))):
            problems.append(f"{k} must be a number or null")
    for k in ("text_clipped_at_edge", "axes_tightbbox_overlaps", "glyph_warnings",
              "tick_label_collisions", "interior_voids", "figure_text"):
        if k in art and not isinstance(art[k], list):
            problems.append(f"{k} must be a list")
    elements = art.get("elements")
    if not isinstance(elements, dict):
        problems.append("elements must be an object")
    else:
        absent = [k for k in el.DETECTORS if k not in elements]
        if absent:
            problems.append("elements lacks detector(s): " + ", ".join(absent[:5]))
        bad = [k for k, v in elements.items() if not (isinstance(v, dict)
               and isinstance(v.get("found"), bool) and isinstance(v.get("evidence", ""), str))]
        if bad:
            problems.append("malformed element record(s): " + ", ".join(bad[:5]))
    if isinstance(art.get("figure_text"), list) and not all(
            isinstance(t, str) for t in art["figure_text"]):
        problems.append("figure_text must hold strings")
    return problems


def load_plan() -> dict:
    p = project_root() / "01_protocol" / "artifact_plan.json"
    if not p.exists():
        raise SystemExit("01_protocol/artifact_plan.json missing - QC needs the plan for target widths")
    return json.loads(p.read_text(encoding="utf-8"))


def load_archetypes() -> dict:
    import tomllib
    p = repo_root() / "reference" / "archetypes.toml"
    if not p.exists():
        return {}
    return tomllib.loads(p.read_text(encoding="utf-8"))


def plan_figures(plan: dict) -> list[dict]:
    return list(plan.get("main_figures", [])) + list(plan.get("supp_figures", []))


# ---------------------------------------------------------------------------
# pixel analysis
# ---------------------------------------------------------------------------
def read_png(path: Path) -> np.ndarray:
    arr = mpimg.imread(str(path))          # float 0..1 or uint8
    if arr.dtype != np.uint8:
        arr = (np.clip(arr, 0, 1) * 255).astype(np.uint8)
    if arr.ndim == 2:
        arr = np.dstack([arr] * 3)
    if arr.shape[2] == 4:                  # composite over white
        a = arr[:, :, 3:4].astype(np.float32) / 255.0
        arr = (arr[:, :, :3].astype(np.float32) * a + 255.0 * (1 - a)).astype(np.uint8)
    return arr[:, :, :3]


def content_bbox(rgb: np.ndarray, white: int = 250) -> tuple[int, int, int, int] | None:
    ink = np.any(rgb < white, axis=2)
    rows = np.where(ink.any(axis=1))[0]
    cols = np.where(ink.any(axis=0))[0]
    if rows.size == 0 or cols.size == 0:
        return None
    return int(cols[0]), int(rows[0]), int(cols[-1]), int(rows[-1])


def grey_regions(rgb: np.ndarray, lo: int = 100, hi: int = 200,
                 min_area: int = 40) -> list[dict]:
    """Connected mid-grey regions - candidate leftover grey footnotes.

    Only meaningful for vector-style statistical plots. Photographic, blot, IHC and
    heat-map panels put large amounts of legitimate pixel data in this band, so the
    result is reported as a hint, never as a failure.
    """
    r, g, b = rgb[:, :, 0].astype(np.int16), rgb[:, :, 1].astype(np.int16), rgb[:, :, 2].astype(np.int16)
    neutral = (np.abs(r - g) < 12) & (np.abs(g - b) < 12) & (np.abs(r - b) < 12)
    mask = neutral & (r >= lo) & (r <= hi)
    if not mask.any():
        return []
    try:
        from scipy import ndimage
        lab, n = ndimage.label(mask)
        out = []
        for sl in ndimage.find_objects(lab):
            h = sl[0].stop - sl[0].start
            w = sl[1].stop - sl[1].start
            area = int(mask[sl].sum())
            if area < min_area:
                continue
            aspect = w / max(h, 1)
            out.append({"x": int(sl[1].start), "y": int(sl[0].start), "w": int(w), "h": int(h),
                        "area": area, "aspect": round(aspect, 2),
                        "text_like": bool(1.5 < aspect < 60 and 4 <= h <= 40)})
        out.sort(key=lambda d: -d["area"])
        _ = n
        return out[:25]
    except ImportError:
        return [{"note": "scipy not installed; only the total mid-grey pixel count is available",
                 "grey_pixels": int(mask.sum())}]


# ---------------------------------------------------------------------------
def qc_figure(entry: dict, tgt: dict, arch_reg: dict | None = None) -> dict:
    fid = str(entry.get("id", "?"))
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str, severity: str = "fail") -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail, "severity": severity})

    png_rel = entry.get("file", "")
    png = project_root() / png_rel if png_rel else None
    if not png or not png.exists():
        add("png_exists", False, f"{png_rel or '(no file in plan)'} not rendered")
        return {"id": fid, "png": png_rel, "checks": checks, "ok": False, "visual_reviewed": False}
    add("png_exists", True, png_rel)

    rgb = read_png(png)
    h_px, w_px = rgb.shape[:2]

    width_class = entry.get("width", "single")
    target_mm = width_mm(width_class, tgt)
    eff_dpi = w_px / (target_mm / MM_PER_IN)
    dpi_min = float(tgt.get("figure_dpi_min", 300))
    add("effective_dpi", eff_dpi >= dpi_min,
        f"{w_px}x{h_px} px at {width_class} width ({target_mm:.0f} mm) = {eff_dpi:.0f} dpi "
        f"(floor {dpi_min:.0f})")

    bbox = content_bbox(rgb)
    if bbox is None:
        add("has_content", False, "the image is blank")
    else:
        x0, y0, x1, y1 = bbox
        m = {"left": x0, "top": y0, "right": w_px - 1 - x1, "bottom": h_px - 1 - y1}
        pct = {k: 100.0 * v / (w_px if k in ("left", "right") else h_px) for k, v in m.items()}
        add("has_content", True,
            "margins px " + ", ".join(f"{k}={v}" for k, v in m.items())
            + " | % " + ", ".join(f"{k}={v:.1f}" for k, v in pct.items()))
        add("not_clipped", all(v >= 1 for v in m.values()),
            "content touches the canvas edge on: "
            + ", ".join(k for k, v in m.items() if v < 1) if any(v < 1 for v in m.values())
            else "content clear of all four edges")
        worst = max(pct.values())
        add("no_excess_whitespace", worst <= 8.0,
            f"largest margin {worst:.1f}% of the canvas"
            + ("" if worst <= 8.0 else " - constrained layout is probably not doing its job"))
        pairs = [("left", "right"), ("top", "bottom")]
        asym = []
        for a, b in pairs:
            lo, hi = sorted((m[a], m[b]))
            if hi > 6 and lo > 0 and hi / lo > 2.0:
                asym.append(f"{a}/{b} = {m[a]}/{m[b]} px")
            elif hi > 6 and lo == 0:
                asym.append(f"{a}/{b} = {m[a]}/{m[b]} px")
        add("margins_symmetric", not asym,
            "asymmetric: " + "; ".join(asym) if asym else "opposing margins within 2x")

    greys = grey_regions(rgb)
    textish = [g for g in greys if g.get("text_like")]
    add("no_grey_footnote_text", not textish,
        f"{len(textish)} text-shaped mid-grey region(s), largest at "
        f"({textish[0]['x']},{textish[0]['y']}) {textish[0]['w']}x{textish[0]['h']} px"
        if textish else "no text-shaped mid-grey regions",
        severity="warn")

    tiff_rel = entry.get("tiff", "")
    tiff = project_root() / tiff_rel if tiff_rel else None
    add("tiff_master", bool(tiff and tiff.exists()),
        f"{tiff_rel} ({tiff.stat().st_size // 1024} KB)" if tiff and tiff.exists()
        else f"{tiff_rel or '(none declared)'} missing - journals want TIFF or EPS")

    archetype = entry.get("archetype")
    elements_found: dict = {}
    engine = None
    sidecar = project_root() / "05_figures" / "qc" / f"{Path(png_rel).stem}.artist.json"
    if sidecar.exists():
        art = json.loads(sidecar.read_text(encoding="utf-8"))
        schema = _schema_problems(art, Path(png_rel).stem)
        add("artist_audit_schema", not schema,
            "; ".join(schema) if schema else "sidecar schema valid")
        engine = art.get("engine", "python")
        if engine == "R":
            if any(k in art for k in PROVENANCE_KEYS):
                problems = _r_provenance_problems(art, entry, png_rel)
                add("r_render_provenance", not problems,
                    "; ".join(problems[:6]) if problems
                    else "R script, result inputs and rendered outputs match the render receipt")
            else:
                add("r_render_provenance", False,
                    "legacy R sidecar has no provenance receipt; re-render with save_medpaper() "
                    "to bind the figure to its script and results", severity="warn")
        policy = str(tgt.get("figure_engine", "R")).strip()
        if policy.casefold() not in ("r", "python"):
            add("figure_engine_valid", False,
                f"targets.figure_engine must be R or python, got {policy!r}")
        elif policy.casefold() != str(engine).casefold():
            add("engine_matches_policy", False,
                f"rendered with {engine}, figure_engine = {policy} (mixing is allowed per "
                "figure; confirm it is deliberate)", severity="warn")
        font_min = float(tgt.get("figure_font_pt_min", 6.0))
        line_min = float(tgt.get("figure_line_pt_min", 0.5))
        mf, ml = art.get("min_font_pt"), art.get("min_line_pt")
        add("min_font_size", mf is None or mf >= font_min,
            f"smallest text {mf} pt (floor {font_min} pt)")
        add("min_line_width", ml is None or ml >= line_min,
            f"thinnest line {ml} pt (floor {line_min} pt)")
        ov = art.get("axes_tightbbox_overlaps", [])
        add("no_panel_overlap", not ov,
            f"{len(ov)} panel bounding-box overlap(s): {ov[:3]}" if ov
            else f"{art.get('n_axes', 0)} axes, no tightbbox overlap")
        cl = art.get("text_clipped_at_edge", [])
        add("no_text_clipped", not cl,
            f"{len(cl)} clipped text element(s): {[c['text'] for c in cl[:3]]}" if cl
            else "no text clipped at the canvas edge")

        gw = art.get("glyph_warnings", [])
        add("no_missing_glyphs", not gw,
            f"{len(gw)} character(s) have no glyph in this font and will print as boxes: "
            f"{[g[:60] for g in gw[:2]]}" if gw
            else "every character has a glyph in the embedded font")
        tc = art.get("tick_label_collisions", [])
        add("no_tick_label_collision", not tc,
            f"{len(tc)} collision(s): "
            + "; ".join(f"axes {c['axes']} {c['axis']}-axis {c['labels']} overlap by "
                        f"{c['overlap_px']} px" for c in tc[:3]) if tc
            else "adjacent tick labels are clear of each other")
        iv = art.get("interior_voids", [])
        add("no_interior_void", not iv,
            f"{len(iv)} dead band(s) between panels: "
            + "; ".join(f"axes {v['axes']} {v['direction']} gap {v['gap_pct']}%"
                        for v in iv[:3])
            + ". Reduce gridspec hspace/wspace, or the panel ratios." if iv
            else "no wasted space between panels")

        elements_found = art.get("elements", {})
        base = elements_found.get("baseline_zero", {})
        if base:
            add("bar_baseline_zero", bool(base.get("found")), base.get("evidence", ""))

        if archetype and arch_reg:
            checks.extend(_archetype_checks(archetype, elements_found, arch_reg))
    else:
        add("artist_audit_present", False,
            f"no sidecar at 05_figures/qc/{Path(png_rel).stem}.artist.json - "
            "render through save_medpaper() (R, tools/figures/R/medfig.R) or "
            "figures.style.save() (Python) so fonts, line widths, glyphs, tick "
            "collisions and archetype elements can be measured")

    blocking = [c for c in checks if not c["ok"] and c["severity"] == "fail"]
    return {
        "id": fid,
        "png": png_rel,
        "engine": engine,
        "archetype": archetype,
        "width_class": width_class,
        "pixels": [w_px, h_px],
        "effective_dpi": round(eff_dpi, 1),
        "grey_regions": greys[:5],
        "checks": checks,
        "ok": not blocking,
        "visual_reviewed": False,
    }


def _r_provenance_problems(art: dict, entry: dict, png_rel: str) -> list[str]:
    """Does the R render receipt still describe the script, results and bytes on disk?"""
    from wfcore.packagefreeze import _safe_path, _sha256
    project = project_root()
    problems: list[str] = []

    def digest(rel: str) -> str | None:
        try:
            _, path = _safe_path(project, rel)
        except ValueError:
            return None
        return _sha256(path) if path.is_file() else None

    renders = art.get("render_hashes") or {}
    if not isinstance(renders, dict) or png_rel not in renders:
        problems.append("no bound PNG render receipt")
        renders = renders if isinstance(renders, dict) else {}
    for rel, expected in renders.items():
        if digest(rel) != str(expected).upper():
            problems.append(f"render changed after save_medpaper: {rel}")
    script = str(art.get("script") or "")
    planned = str(entry.get("script") or "")
    if planned and script != planned:
        problems.append(f"drawn by {script or 'an unidentified script'}, plan says {planned}")
    if script and digest(script) != str(art.get("script_sha256", "")).upper():
        problems.append(f"R script changed after render: {script}")
    sources = art.get("source_hashes") or {}
    if not isinstance(sources, dict):
        sources = {}
        problems.append("source_hashes must be an object")
    if "source_results" in entry:
        declared = {str(s) for s in entry.get("source_results") or []}
        if set(sources) != declared:
            problems.append("result sources in the render receipt differ from the plan's "
                            "source_results")
    for rel, expected in sources.items():
        if digest(rel) != str(expected).upper():
            problems.append(f"result changed after render: {rel}")
    return problems


def _archetype_checks(archetype: str, found: dict, reg: dict) -> list[dict]:
    """Mandatory-element checks for the declared chart type."""
    spec = (reg.get("archetype") or {}).get(archetype)
    if spec is None:
        return [{"name": "archetype_known", "ok": False, "severity": "fail",
                 "detail": f"'{archetype}' is not in reference/archetypes.toml "
                           f"(known: {', '.join(sorted((reg.get('archetype') or {})))})"}]
    out = [{"name": "archetype_known", "ok": True, "severity": "fail",
            "detail": f"{archetype}: {spec.get('label', '')}"}]

    universal = (reg.get("meta") or {}).get("universal_requires", [])
    for key in list(dict.fromkeys(list(universal) + list(spec.get("requires", [])))):
        rec = found.get(key)
        if rec is None:
            out.append({"name": f"element:{key}", "ok": False, "severity": "warn",
                        "detail": f"no detector for '{key}' - check it by eye"})
            continue
        out.append({"name": f"element:{key}", "ok": bool(rec.get("found")),
                    "severity": "fail",
                    "detail": (rec.get("evidence", "") if rec.get("found")
                               else f"MISSING for a {archetype} figure. {rec.get('evidence', '')}")})
    for key in spec.get("forbids", []):
        rec = found.get(key) or {}
        out.append({"name": f"forbidden:{key}", "ok": not rec.get("found"),
                    "severity": "fail",
                    "detail": rec.get("evidence", "") or "absent, as required"})
    # Advisory items split by whether a detector exists. Reporting an undetectable item as
    # "missing" would train the reader to ignore the whole line.
    advisory = list(spec.get("advisory", []))
    undetectable = [k for k in advisory if k not in found]
    detected_absent = [k for k in advisory if k in found and not found[k].get("found")]
    if undetectable or detected_absent:
        bits = []
        if undetectable:
            bits.append("no detector, confirm by eye: " + ", ".join(undetectable))
        if detected_absent:
            bits.append("detected as absent: " + ", ".join(detected_absent))
        note = (spec.get("notes") or "").strip().splitlines()
        out.append({"name": "archetype_advisory", "ok": False, "severity": "warn",
                    "detail": f"{archetype} - " + "; ".join(bits)
                              + (f" | {note[0]}" if note else "")})
    return out


def crop(fid: str, rows: int, cols: int, cell: str) -> int:
    plan = load_plan()
    entry = next((e for e in plan_figures(plan) if str(e.get("id")) == fid), None)
    if entry is None:
        raise SystemExit(f"{fid} is not in the artifact plan")
    png = project_root() / entry["file"]
    rgb = read_png(png)
    h, w = rgb.shape[:2]
    idx = ord(cell.upper()) - ord("A")
    if not 0 <= idx < rows * cols:
        raise SystemExit(f"cell {cell} is outside a {rows}x{cols} grid")
    r, c = divmod(idx, cols)
    y0, y1 = int(h * r / rows), int(h * (r + 1) / rows)
    x0, x1 = int(w * c / cols), int(w * (c + 1) / cols)
    out = project_root() / "05_figures" / "qc" / "crops" / f"{Path(entry['file']).stem}_{cell.upper()}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    mpimg.imsave(str(out), rgb[y0:y1, x0:x1])
    rel = out.relative_to(project_root()).as_posix()
    _say(f"cropped {fid} cell {cell.upper()} ({x1 - x0}x{y1 - y0} px) -> project/{rel}")
    print(f"now look at it:  read_file {out}")
    return 0


def contact_sheet(max_px: int = 1400) -> int:
    """Tile every planned figure into one PNG so the visual pass costs one image, not N.

    Reviewing 6 figures one at a time means 6 images in context. The sheet is a single load
    at a resolution that still shows overlap, clipping, colour and clutter. Anything the
    sheet makes you suspicious of gets a full-resolution --crop follow-up; that is the point
    of the two-step, not a shortcut around it.
    """
    plan = load_plan()
    entries = plan_figures(plan)
    if not entries:
        raise SystemExit("the artifact plan declares no figures")

    tiles: list[tuple[str, np.ndarray]] = []
    missing: list[str] = []
    for e in entries:
        png = project_root() / str(e.get("file", ""))
        if not png.exists():
            missing.append(str(e.get("id")))
            continue
        tiles.append((str(e.get("id")), read_png(png)))
    if not tiles:
        raise SystemExit("no rendered PNGs found - render the figures first")

    cols = 1 if len(tiles) == 1 else 2
    rows = (len(tiles) + cols - 1) // cols
    # Downscale each tile by an integer stride: cheap, and it keeps text edges honest
    # rather than smoothing away the aliasing we are looking for.
    cell_w = max(1, max_px // cols)
    scaled: list[np.ndarray] = []
    for _, rgb in tiles:
        stride = max(1, int(np.ceil(rgb.shape[1] / cell_w)))
        scaled.append(rgb[::stride, ::stride])

    pad, label_h = 12, 34
    cw = max(t.shape[1] for t in scaled)
    ch = max(t.shape[0] for t in scaled)
    sheet = np.full((rows * (ch + label_h + pad) + pad, cols * (cw + pad) + pad, 3), 255, np.uint8)
    placed: list[tuple[str, int, int]] = []
    for i, (tile, (fid, _)) in enumerate(zip(scaled, tiles)):
        r, c = divmod(i, cols)
        y = pad + r * (ch + label_h + pad) + label_h
        x = pad + c * (cw + pad)
        sheet[y:y + tile.shape[0], x:x + tile.shape[1]] = tile
        placed.append((fid, r, c))

    out = project_root() / "05_figures" / "qc" / "contact_sheet.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    # Draw the id labels with matplotlib so the sheet is self-describing without a font blit.
    import matplotlib.pyplot as plt
    dpi = 100
    fig = plt.figure(figsize=(sheet.shape[1] / dpi, sheet.shape[0] / dpi), dpi=dpi)
    ax = fig.add_axes([0, 0, 1, 1]); ax.imshow(sheet); ax.axis("off")
    for fid, r, c in placed:
        ax.text(pad + c * (cw + pad), pad + r * (ch + label_h + pad) + label_h - 10,
                fid, fontsize=13, fontweight="bold", color="#000000", va="bottom")
    fig.savefig(str(out), dpi=dpi, facecolor="white")
    plt.close(fig)

    rel = out.relative_to(project_root()).as_posix()
    _say(f"contact sheet: {len(tiles)} figure(s) in a {rows}x{cols} grid -> project/{rel}")
    if missing:
        print(f"  NOT RENDERED (absent from the sheet): {', '.join(missing)}")
    print(f"\nlook at it in one load:  read_file {out}")
    print("then, per figure you inspected:")
    _say('  tools/figures/qc.py --confirm "Figure 1" --note "<what you saw / what you changed>"')
    print("crop in at full resolution on anything the sheet makes you doubt:")
    _say('  tools/figures/qc.py --crop "Figure 1" --cols 2 --cell B')
    return 0


def confirm(fid: str, note: str) -> int:
    """Record that a rendered figure was actually looked at.

    The flag is bound to the PNG's SHA-256 (legacy reports: its mtime), so a re-render that
    changes the bytes invalidates it - the same binding the QC pass already uses. This exists so the report is never hand-edited, which
    is exactly the failure mode the rest of the pipeline refuses to trust.
    """
    if len(note.strip()) < 20:
        raise SystemExit("--note must say what you saw, in at least 20 characters")
    qc_path = project_root() / "05_figures" / "qc" / "qc_report.json"
    if not qc_path.exists():
        raise SystemExit(wfpaths.localize_commands(
            "no qc_report.json - run deterministic QC first: tools/figures/qc.py --all",
            project_root()))
    report = json.loads(qc_path.read_text(encoding="utf-8"))
    figs = report.get("figures", [])
    entry = next((f for f in figs if str(f.get("id")) == fid), None)
    if entry is None:
        have = ", ".join(str(f.get("id")) for f in figs) or "(none)"
        raise SystemExit(f"{fid} has no QC entry. Present: {have}")

    rel = entry.get("png", "") or ""
    if ((entry.get("png_sha256") or entry.get("png_mtime") is not None)
            and not _same_render(entry, _png_sha256(rel), _mtime(rel))):
        raise SystemExit(
            f"{fid} was re-rendered after its last QC run - the QC report is stale.\n"
            "Re-run: tools/figures/qc.py --all, look at the new render, then confirm."
        )
    entry["visual_reviewed"] = True
    entry["review_rounds"] = int(entry.get("review_rounds", 0)) + 1
    entry.setdefault("review_log", []).append({"at": _now(), "note": note.strip()})
    qc_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    pending = [str(f.get("id")) for f in figs if not f.get("visual_reviewed")]
    print(f"{fid}: visual review recorded (round {entry['review_rounds']})")
    print(f"  still unlooked-at: {', '.join(pending) if pending else 'none'}")
    if not pending:
        print('\nall figures reviewed. Now record the stage decision:')
        _say('  tools/wf.py decide figures_visually_confirmed YES --why "<per figure: what you saw>"')
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="deterministic figure QC")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--figure", help="one figure id, e.g. \"Figure 1\"")
    ap.add_argument("--crop", help="figure id to crop")
    ap.add_argument("--rows", type=int, default=1)
    ap.add_argument("--cols", type=int, default=2)
    ap.add_argument("--cell", default="A")
    ap.add_argument("--contact-sheet", action="store_true",
                    help="tile every rendered figure into one PNG for a single-load visual pass")
    ap.add_argument("--confirm", metavar="FIGURE_ID",
                    help="record that this figure's render was visually inspected")
    ap.add_argument("--note", default="", help="what you saw (required with --confirm)")
    args = ap.parse_args()

    if args.contact_sheet:
        return contact_sheet()
    if args.confirm:
        return confirm(args.confirm, args.note)
    if args.crop:
        return crop(args.crop, args.rows, args.cols, args.cell)
    if not (args.all or args.figure):
        ap.error("pass --all, --figure ID, --crop ID, --contact-sheet, or --confirm ID")

    plan = load_plan()
    tgt = targets()
    entries = plan_figures(plan)
    if args.figure:
        entries = [e for e in entries if str(e.get("id")) == args.figure]
        if not entries:
            raise SystemExit(f"{args.figure} is not in the artifact plan")

    qc_path = project_root() / "05_figures" / "qc" / "qc_report.json"
    previous = {}
    if qc_path.exists():
        try:
            previous = {f["id"]: f for f in json.loads(qc_path.read_text(encoding="utf-8")).get("figures", [])}
        except json.JSONDecodeError:
            pass

    arch_reg = load_archetypes()
    results = []
    for e in entries:
        res = qc_figure(e, tgt, arch_reg)
        # A visual review is bound to the PNG bytes: a changed render invalidates it, while a
        # re-render that reproduces identical bytes keeps it (no needless second look).
        old = previous.get(res["id"])
        live_sha = _png_sha256(e.get("file", ""))
        if old and _same_render(old, live_sha, _mtime(e.get("file", ""))):
            res["visual_reviewed"] = old.get("visual_reviewed", False)
            res["review_rounds"] = old.get("review_rounds", 0)
            if old.get("review_log"):
                res["review_log"] = old["review_log"]
        res["png_sha256"] = live_sha
        res["png_mtime"] = _mtime(e.get("file", ""))
        results.append(res)

    if args.figure:
        merged = [previous[k] for k in previous if k != args.figure] + results
    else:
        merged = results

    qc_path.parent.mkdir(parents=True, exist_ok=True)
    qc_path.write_text(json.dumps(
        {"generated_at": _now(), "figures": merged}, indent=2, ensure_ascii=False), encoding="utf-8")

    fails = 0
    for res in results:
        print(f"\n{res['id']}  {res.get('png', '')}")
        for c in res["checks"]:
            tag = "PASS" if c["ok"] else ("FAIL" if c["severity"] == "fail" else "WARN")
            print(f"  [{tag}] {c['name']:<24} {c['detail']}")
        if not res["ok"]:
            fails += 1
    print(f"\n{len(results) - fails}/{len(results)} figure(s) pass deterministic QC")
    _say("report: project/05_figures/qc/qc_report.json")
    print("\nQC is not verification - it cannot judge colour semantics, legibility or clutter.")
    if str(tgt.get("visual_review_mode", "inline")).strip().lower() == "deferred":
        print("visual_review_mode = deferred: do not look yet. Get this green, then park the look:")
        _say('  tools/wf.py decide figures_visually_confirmed DEFER --why "QC green: <summary>"')
        print("The whole backlog is discharged in one contact-sheet pass at S23, which")
        print("visual_debts_cleared (non-overridable) refuses to let you skip.")
    else:
        print("visual_review_mode = inline: open each PNG now, then record what you saw:")
        _say('  tools/figures/qc.py --confirm "Figure 1" --note "<what you saw>"')
    return 0 if fails == 0 else 2


def _png_sha256(rel: str) -> str | None:
    if not rel:
        return None
    p = project_root() / rel
    if not p.is_file():
        return None
    import hashlib
    return hashlib.sha256(p.read_bytes()).hexdigest().upper()


def _same_render(entry: dict, live_sha: str | None, live_mtime: float | None) -> bool:
    """Is the PNG on disk the one this QC entry judged? SHA-256 first; legacy entries by mtime."""
    if entry.get("png_sha256"):
        return live_sha is not None and entry["png_sha256"] == live_sha
    if entry.get("png_mtime") is not None:
        return live_mtime is not None and entry["png_mtime"] == live_mtime
    return False


def _mtime(rel: str) -> float | None:
    if not rel:
        return None
    p = project_root() / rel
    return round(p.stat().st_mtime, 3) if p.exists() else None


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


if __name__ == "__main__":
    sys.exit(main())
