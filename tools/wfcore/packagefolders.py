"""1.22.0 (J4): the confirmed upload set, copied read-only to a folder named by journal and date.

At the S24 confirmation (`review_round.py decide no_further_review --scope package`) the exact
upload set is copied to

    <paper>/submission_packages/<Journal_ISO_abbreviation>_<YYYY-MM-DD>/

(ASCII-safe, from the NLM ISO abbreviation in target_journal.json or the journal title; a
collision gets _v2, _v3), with UPLOAD_LIST.md (upload order, roles, the portal to-do) and a
copy of the bundle manifest that both name the folder. It is refreshed at S25 PASS when
anything changed. One folder per journal epoch; earlier journals' folders stay for the
user's records - never deleted, never reused - and the paper guard hides them from agent
discovery tools. The engine is the only writer (files are read-only).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

ROOT = "submission_packages"
INDEX = ".wf/package_folders.json"
ABBREV_KEYS = ("iso_abbreviation", "nlm_iso_abbreviation", "iso_abbrev", "nlm_abbreviation",
               "abbreviation", "journal_abbreviation")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _json(path: Path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def slug(name: str) -> str:
    """'J. Surg. Oncol.' -> 'J_Surg_Oncol'; ASCII only (accents folded, other scripts dropped)."""
    text = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode()
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")
    return re.sub(r"_+", "_", text)[:60] or "Journal"


def journal_label(target: dict) -> str:
    for k in ABBREV_KEYS:
        v = str(target.get(k) or "").strip()
        if v:
            return slug(v)
    return slug(str(target.get("journal") or ""))


def load_index(project: Path) -> dict:
    data = _json(Path(project) / INDEX)
    if not isinstance(data, dict):
        data = {}
    data.setdefault("schema", 1)
    data.setdefault("folders", [])
    return data


def _save_index(project: Path, data: dict) -> None:
    p = Path(project) / INDEX
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def current(project: Path) -> dict | None:
    from . import journalepoch
    ep = journalepoch.number(project)
    for rec in reversed(load_index(project)["folders"]):
        if int(rec.get("epoch") or 1) == ep:
            return rec
    return None


def old_folders(project: Path) -> list[Path]:
    """Folders of earlier journal epochs (hidden from agent discovery by the paper guard)."""
    cur = current(project) or {}
    return [Path(project) / r["folder"] for r in load_index(project)["folders"]
            if r.get("folder") and r.get("folder") != cur.get("folder")]


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _writable(p: Path) -> None:
    try:
        os.chmod(p, stat.S_IWRITE | stat.S_IREAD)
    except OSError:
        pass


def _readonly(p: Path) -> None:
    try:
        os.chmod(p, stat.S_IREAD)
    except OSError:
        pass


def _uploads(project: Path) -> list[tuple[str, str]]:
    """(paper-relative file, role) in manifest order; the author's final copy wins."""
    man = _json(Path(project) / "08_submission/bundle/manifest.json") or {}
    out = []
    for i in man.get("items", []) if isinstance(man, dict) else []:
        rel = str(i.get("file", "")).replace("\\", "/")
        if not rel or not (Path(project) / rel).is_file():
            continue
        final = Path(project) / "08_submission/final_copy" / Path(rel).name
        out.append((final.relative_to(project).as_posix() if final.is_file() else rel,
                    str(i.get("role", ""))))
    return out


def _new_folder(project: Path, label: str, day: str) -> Path:
    used = {r.get("folder") for r in load_index(project)["folders"]}
    base = f"{ROOT}/{label}_{day}"
    name, n = base, 1
    while name in used or (Path(project) / name).exists():
        n += 1
        name = f"{base}_v{n}"
    return Path(project) / name


def _write_lists(project: Path, folder: Path, files: list[tuple[str, str, str]]) -> None:
    from . import compliance, journalepoch
    rel = folder.relative_to(project).as_posix()
    lines = [f"# 投稿上传清单 - {journalepoch.target_name(project)}", "",
             f"投稿包文件夹：{rel}/（由引擎生成，只读；请从这里上传）", "",
             "| 顺序 | 文件 | 类型 |", "|---|---|---|"]
    lines += [f"| {i} | {name} | {role or '-'} |" for i, (name, role, _s) in enumerate(files, 1)]
    data = _json(Path(project) / compliance.MATRIX_JSON) or {}
    portal = [r for r in data.get("rows") or [] if r.get("portal")] if isinstance(data, dict) else []
    lines += ["", f"## 投稿系统中由您完成的事项（portal to-do，共 {len(portal)} 项）", ""]
    lines += [f"- {r.get('id')}：{r.get('quote') or r.get('evidence')}" for r in portal] or ["- 无"]
    from . import portal as _portal
    if not _portal.current(project):  # 1.22.0 (J3): the user declined the portal check
        lines += ["- 投稿系统未由代理读取：上传时请逐项核对上传项、必填项、文件类型与大小是否与"
                  "投稿指南一致；不一致请告诉代理（wf portal ingest + 展示层修订轮）"]
    for name in ("UPLOAD_LIST.md", "manifest.json"):
        p = folder / name
        if p.exists():
            _writable(p)
    (folder / "UPLOAD_LIST.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    man = _json(Path(project) / "08_submission/bundle/manifest.json") or {}
    if isinstance(man, dict):
        man = {**man, "package_folder": rel}
        (folder / "manifest.json").write_text(json.dumps(man, indent=2, ensure_ascii=False) + "\n",
                                              encoding="utf-8")
    for name in ("UPLOAD_LIST.md", "manifest.json"):
        if (folder / name).exists():
            _readonly(folder / name)


def create_or_refresh(project: Path, when: str = "S24") -> tuple[Path, list[str]]:
    """Copy the confirmed upload set; one folder per journal epoch (refreshed in place)."""
    from . import journalepoch, journalspec
    project = Path(project)
    data = load_index(project)
    rec = current(project)
    day = datetime.now().strftime("%Y-%m-%d")
    if rec is None:
        folder = _new_folder(project, journal_label(journalspec.load(project)), day)
        rec = {"epoch": journalepoch.number(project), "journal": journalepoch.target_name(project),
               "folder": folder.relative_to(project).as_posix(), "created_at": _now(), "files": {}}
        data["folders"].append(rec)
    folder = project / rec["folder"]
    folder.mkdir(parents=True, exist_ok=True)
    changed, files = [], []
    for rel, role in _uploads(project):
        src = project / rel
        dst = folder / Path(rel).name
        digest = _sha(src)
        files.append((dst.name, role, digest))
        if dst.is_file() and _sha(dst) == digest:
            continue
        if dst.exists():
            _writable(dst)
        shutil.copyfile(src, dst)
        _readonly(dst)
        changed.append(dst.name)
    keep = {n for n, _r, _s in files} | {"UPLOAD_LIST.md", "manifest.json"}
    for p in sorted(folder.iterdir()):
        if p.is_file() and p.name not in keep:  # a file no longer in the upload set
            _writable(p)
            p.unlink()
            changed.append(f"removed {p.name}")
    _write_lists(project, folder, files)
    rec.update(files={n: s for n, _r, s in files}, updated_at=_now(), updated_at_stage=when)
    _save_index(project, data)
    return folder, changed


def summary_zh(project: Path) -> list[str]:
    rec = current(project)
    if not rec:
        return []
    out = [f"投稿包文件夹：{rec['folder']}/（{len(rec.get('files') or {})} 个文件，只读；"
           "UPLOAD_LIST.md 列出上传顺序与投稿系统待办）"]
    olds = [r["folder"] for r in load_index(project)["folders"] if r is not rec and r.get("folder") != rec["folder"]]
    if olds:
        out.append("此前期刊的投稿包保留供您存档（不会删除或复用）：" + "、".join(olds))
    return out
