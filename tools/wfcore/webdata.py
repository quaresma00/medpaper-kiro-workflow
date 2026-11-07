"""1.21.0 (B6): web pages that enter the paper as facts - public pharmacovigilance dashboards
(VigiAccess, the FAERS public dashboard), drug labels on regulator sites, registry pages.

    wf data capture --from <capture> --url <URL> --query "<exact query and filters>" --name <short>
                    [--screenshot <png>] [--values-csv <csv read from the screenshot>]

Each capture is a dated, versioned raw source under 02_data/raw/web/<name>/v001/ (original
capture, clean text, screenshot, capture.json with URL, query, time, method and sha256 of every
file); a repeated capture of the same query becomes v002, never an overwrite. The files are part
of the raw inventory (tools/data_manifest.py sync; the acquisition manifest cites them), so
analysis numbers trace to them; scripts read them with source_path('web:<name>') (latest
version). When the page text is obfuscated (VigiAccess inserts invisible characters) the
numbers are read from the screenshot into a small CSV next to it, marked 'read from
screenshot', and listed once for the user or reviewer to verify (`wf data confirm-capture
<name> --note "<words>"`; the confirmation lives in .wf/web_captures.json so the raw files
never change). 02_data/raw/web/ is data, not journal layer: `wf journal switch` leaves it.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT_REL = "02_data/raw/web"
CONFIRM_REL = ".wf/web_captures.json"
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}$")
_INVISIBLE = re.compile("[\u200b-\u200f\u2060-\u2064\ufeff\u00ad]")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def versions(project: Path, name: str) -> list[Path]:
    base = Path(project) / ROOT_REL / name
    return sorted(p for p in base.glob("v[0-9][0-9][0-9]") if p.is_dir()) if base.is_dir() else []


def latest(project: Path, name: str) -> Path | None:
    v = versions(project, name)
    return v[-1] if v else None


def _confirmations(project: Path) -> dict:
    try:
        data = json.loads((Path(project) / CONFIRM_REL).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def capture(project: Path, src: Path, url: str, query: str, name: str,
            screenshot: Path | None = None, values_csv: Path | None = None) -> dict:
    from . import guideingest
    project, src = Path(project), Path(src)
    name = str(name or "").strip()
    if not NAME_RE.match(name):
        raise ValueError(f"--name {name!r}: lowercase letters, digits, '-' or '_' (<= 41)")
    if not re.match(r"(?i)^https?://", str(url or "")):
        raise ValueError("--url 必须是网页的完整网址（https://...）")
    if len(str(query or "").strip()) < 3:
        raise ValueError("--query 必须写明完整检索式和筛选条件（药物名、事件、时间范围、地区等）")
    if not src.is_file():
        raise ValueError(f"找不到文件 {src}")
    for extra in (screenshot, values_csv):
        if extra is not None and not Path(extra).is_file():
            raise ValueError(f"找不到文件 {extra}")
    data = src.read_bytes()
    ftype, lines, meta = guideingest.read_capture(src, data)
    raw_text = "\n".join(lines)
    obfuscated = len(_INVISIBLE.findall(raw_text)) >= 5
    text = _INVISIBLE.sub("", raw_text)
    why = guideingest.challenge(text, "data")
    if why:
        raise ValueError(guideingest.CHALLENGE_ZH.format(why=why))
    n = len(versions(project, name)) + 1
    dest = project / ROOT_REL / name / f"v{n:03d}"
    while dest.exists():
        n += 1
        dest = project / ROOT_REL / name / f"v{n:03d}"
    dest.mkdir(parents=True)
    suffix = {"snapshot": ".yml", "json": ".json", "jsonstr": ".json", "html": ".html",
              "pdf": ".pdf"}.get(ftype, ".txt")
    files = {}
    (dest / f"capture_original{suffix}").write_bytes(data)
    (dest / "capture.txt").write_text(text + "\n", encoding="utf-8")
    if screenshot is not None:
        shutil.copyfile(screenshot, dest / f"screenshot{Path(screenshot).suffix.casefold() or '.png'}")
    if values_csv is not None:
        shutil.copyfile(values_csv, dest / "read_from_screenshot.csv")
    for p in sorted(dest.iterdir()):
        files[p.name] = _sha(p)
    final_url = str(meta.get("url") or "").strip()
    rec = {"schema": 1, "name": name, "version": n, "url": str(url).strip(),
           "final_url": final_url if final_url.startswith("http") else str(url).strip(),
           "title": str(meta.get("title") or ""), "query": str(query).strip(),
           "captured_at": guideingest._captured_at(src, meta), "stored_at": _now(),
           "method": "browser", "format": ftype, "original_name": src.name,
           "obfuscated_text": obfuscated, "read_from_screenshot": values_csv is not None,
           "files": files}
    (dest / "capture.json").write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n",
                                       encoding="utf-8")
    rec["dir"] = dest.relative_to(project).as_posix()
    return rec


def all_captures(project: Path) -> list[dict]:
    out = []
    base = Path(project) / ROOT_REL
    for meta in sorted(base.glob("*/v[0-9][0-9][0-9]/capture.json")) if base.is_dir() else []:
        try:
            rec = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            rec = {"broken": True}
        rec["dir"] = meta.parent.relative_to(project).as_posix()
        out.append(rec)
    return out


def confirm(project: Path, name: str, words: str) -> list[str]:
    conf = _confirmations(project)
    done = []
    for rec in all_captures(project):
        if rec.get("name") == name and rec.get("read_from_screenshot") and rec["dir"] not in conf:
            conf[rec["dir"]] = {"words": words, "at": _now()}
            done.append(rec["dir"])
    if done:
        p = Path(project) / CONFIRM_REL
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(conf, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return done


def problems(project: Path) -> tuple[list[str], list[str]]:
    """(blocking, warnings) for web_captures_traced."""
    bad, warn = [], []
    conf = _confirmations(project)
    caps = all_captures(project)
    newest = {}
    for rec in caps:
        newest[rec.get("name")] = max(newest.get(rec.get("name"), 0), int(rec.get("version") or 0))
    for rec in caps:
        d = rec["dir"]
        if rec.get("broken"):
            bad.append(f"{d}/capture.json is unreadable")
            continue
        if len(str(rec.get("query", "")).strip()) < 3 or not str(rec.get("url", "")).startswith("http"):
            bad.append(f"{d}: URL and exact query must be recorded")
        for fname, sha in (rec.get("files") or {}).items():
            p = Path(project) / d / fname
            if not p.is_file():
                bad.append(f"{d}/{fname} is missing")
            elif _sha(p) != sha:
                bad.append(f"{d}/{fname} changed after capture (captures are never edited; "
                           "capture again -> next version)")
        if rec.get("read_from_screenshot") and d not in conf:
            warn.append(f"{d}/read_from_screenshot.csv: values read from the screenshot are not "
                        "yet verified by the user or reviewer (wf data confirm-capture "
                        f"{rec.get('name')} --note \"<words>\")")
        elif rec.get("obfuscated_text") and not rec.get("read_from_screenshot") \
                and int(rec.get("version") or 0) == newest.get(rec.get("name")):
            warn.append(f"{d}: the page text is obfuscated; read the numbers from the screenshot "
                        "into read_from_screenshot.csv (capture again with --values-csv)")
    return bad, warn


def describe(project: Path) -> list[str]:
    out = []
    conf = _confirmations(project)
    for rec in all_captures(project):
        if rec.get("broken"):
            continue
        mark = ""
        if rec.get("read_from_screenshot"):
            mark = "; values read from screenshot" + (" (verified)" if rec["dir"] in conf else
                                                     " - NOT yet verified")
        out.append(f"web:{rec['name']} v{rec['version']:03d}: {rec['final_url']} | query: "
                   f"{rec['query'][:80]} | {rec['captured_at'][:10]} ({rec['dir']}{mark})")
    return out
