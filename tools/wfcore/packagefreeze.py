"""Freeze and verify the exact submission package presented to the final reviewer."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


FREEZE_REL = "08_submission/package_review_freeze.json"
MANIFEST_REL = "08_submission/bundle/manifest.json"
REQUIRED_EVIDENCE = (
    "08_submission/target_journal.json",
    "08_submission/guidelines_extract.md",
    "08_submission/docx_style.json",
    "08_submission/submission_qc.md",
    "08_submission/package_content_baseline.json",
)
OPTIONAL_EVIDENCE = (
    "07_manuscript/full_manuscript.md",
    "07_manuscript/supplementary_methods.md",
    "07_manuscript/title_page.md",
    "07_manuscript/statements.md",
    "08_submission/cover_letter.md",
    "05_figures/legends.md",
    "04_tables/table_captions.md",
    # The scientific freeze and the journal variant it produced. Freezing these at S24 means the
    # final audit can prove both what the science was and what the journal adaptation changed.
    "07_manuscript/scientific_freeze.json",
    "08_submission/manuscript/full_manuscript.md",
    "08_submission/manuscript/supplementary_methods.md",
    "08_submission/manuscript/title_page.md",
    "08_submission/manuscript/statements.md",
    "08_submission/manuscript/variant.json",
)


def _safe_path(project: Path, raw: str) -> tuple[str, Path]:
    rel = PurePosixPath(str(raw).replace("\\", "/"))
    if rel.is_absolute() or not rel.parts or ".." in rel.parts:
        raise ValueError(f"unsafe project-relative path: {raw}")
    normalized = rel.as_posix()
    path = project.joinpath(*rel.parts).resolve()
    try:
        path.relative_to(project.resolve())
    except ValueError as exc:
        raise ValueError(f"path leaves the project directory: {raw}") from exc
    return normalized, path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def expected_files(project: Path) -> dict[str, Path]:
    """Return every package and evidence file that the independent audit must see."""
    project = project.resolve()
    required = (MANIFEST_REL, *REQUIRED_EVIDENCE)
    files: dict[str, Path] = {}
    missing: list[str] = []
    for rel in required:
        normalized, path = _safe_path(project, rel)
        if not path.is_file():
            missing.append(normalized)
        else:
            files[normalized] = path
    if missing:
        raise ValueError("required review evidence missing: " + ", ".join(missing))

    try:
        manifest = json.loads(files[MANIFEST_REL].read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{MANIFEST_REL} is invalid JSON: {exc}") from exc
    for item in manifest.get("items", []):
        normalized, path = _safe_path(project, str(item.get("file", "")))
        if not path.is_file():
            raise ValueError(f"manifest item missing: {normalized}")
        files[normalized] = path

    for folder_rel in ("08_submission/bundle", "08_submission/cache",
                       "08_submission/manuscript", "08_submission/build_receipts"):
        _, folder = _safe_path(project, folder_rel)
        if folder.is_dir():
            for path in sorted(p for p in folder.rglob("*") if p.is_file()):
                rel = path.relative_to(project).as_posix()
                files[rel] = path
    if not any(rel.startswith("08_submission/cache/") for rel in files):
        raise ValueError("no cached official journal guideline snapshot is available")

    for rel in OPTIONAL_EVIDENCE:
        normalized, path = _safe_path(project, rel)
        if path.is_file():
            files[normalized] = path
    return dict(sorted(files.items()))


def upload_files(project: Path) -> set[str]:
    """1.9.0: what the user confirms is what gets uploaded - manifest items and the bundle."""
    project = Path(project).resolve()
    out: set[str] = set()
    not_uploaded: set[str] = set()
    manifest = project.joinpath(*PurePosixPath(MANIFEST_REL).parts)
    try:
        for item in json.loads(manifest.read_text(encoding="utf-8")).get("items", []):
            rel = str(item.get("file", "")).replace("\\", "/")
            # 1.14.1 (B9): a manifest item marked "upload": false is evidence, not an upload
            if item.get("upload") is False:
                not_uploaded.add(rel)
            else:
                out.add(rel)
    except (OSError, ValueError, AttributeError):
        pass
    bundle = project / "08_submission" / "bundle"
    if bundle.is_dir():
        out.update(p.relative_to(project).as_posix() for p in bundle.rglob("*")
                   if p.is_file() and p.name != "manifest.json")
    return {r for r in out if r and r not in not_uploaded}


def _records(project: Path) -> list[dict]:
    from .determinism import content_sha256
    files = expected_files(project)
    uploads = upload_files(project)
    records = []
    for rel, path in files.items():
        rec = {"path": rel, "sha256": _sha256(path), "size": path.stat().st_size,
               "role": "upload" if rel in uploads else "evidence"}
        if rec["role"] == "upload":
            rec["content_sha256"] = content_sha256(path)
        records.append(rec)
    return records


def _freeze_id(records: list[dict]) -> str:
    return hashlib.sha256(
        json.dumps(records, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest().upper()


def build_freeze(project: Path) -> dict:
    records = _records(project)
    return {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "freeze_id": _freeze_id(records),
        "algorithm": "SHA-256",
        "files": records,
    }


def apply_delta(project: Path, round_id: str, summary: str, at: str) -> list[str]:
    """Record a presentation delta (1.9.0): re-hash the package, keep the confirmed ids."""
    project = Path(project).resolve()
    path = project.joinpath(*PurePosixPath(FREEZE_REL).parts)
    payload = json.loads(path.read_text(encoding="utf-8"))
    old = {str(r.get("path")): r for r in payload.get("files", []) if isinstance(r, dict)}
    records = _records(project)
    changed = sorted({r["path"] for r in records if old.get(r["path"], {}).get("sha256") != r["sha256"]}
                     | (set(old) - {r["path"] for r in records}))
    if not changed:
        return []
    deltas = payload.setdefault("presentation_deltas", [])
    same = next((d for d in deltas if d.get("round") == round_id), None)
    if same:  # a re-check of the same round keeps the confirmed id it superseded
        same.update(at=at, summary=summary, files=sorted(set(same.get("files", [])) | set(changed)))
    else:
        deltas.append({"round": round_id, "at": at, "summary": summary,
                       "from_freeze_id": payload.get("freeze_id"), "files": changed})
    payload["files"] = records
    payload["freeze_id"] = _freeze_id(records)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return changed


def confirmed_ids(payload: dict) -> set[str]:
    """The current freeze id and every id a presentation delta superseded."""
    ids = {str(payload.get("freeze_id", ""))}
    ids.update(str(d.get("from_freeze_id", "")) for d in payload.get("presentation_deltas", [])
               if isinstance(d, dict))
    return {i for i in ids if len(i) == 64}


def write_freeze(project: Path, output: Path | None = None) -> Path:
    project = project.resolve()
    output = (output or project.joinpath(*PurePosixPath(FREEZE_REL).parts)).resolve()
    try:
        output.relative_to(project)
    except ValueError as exc:
        raise ValueError("freeze manifest must remain inside the project directory") from exc
    payload = build_freeze(project)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return output


def verify_freeze(project: Path, freeze: Path | None = None) -> tuple[bool, list[str], int]:
    project = project.resolve()
    freeze = (freeze or project.joinpath(*PurePosixPath(FREEZE_REL).parts)).resolve()
    try:
        payload = json.loads(freeze.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return False, [f"{FREEZE_REL} missing"], 0
    except json.JSONDecodeError as exc:
        return False, [f"{FREEZE_REL} invalid JSON: {exc}"], 0

    problems: list[str] = []
    if payload.get("schema_version") != 1 or payload.get("algorithm") != "SHA-256":
        problems.append("freeze manifest schema or hash algorithm is invalid")
    records = payload.get("files")
    if not isinstance(records, list):
        return False, problems + ["freeze manifest has no files list"], 0
    expected_freeze_id = hashlib.sha256(
        json.dumps(records, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest().upper()
    if payload.get("freeze_id") != expected_freeze_id:
        problems.append("freeze_id does not match the frozen file records")

    recorded: dict[str, dict] = {}
    for item in records:
        if not isinstance(item, dict) or not item.get("path"):
            problems.append("freeze manifest contains a malformed file record")
            continue
        rel = str(item["path"]).replace("\\", "/")
        if rel in recorded:
            problems.append(f"duplicate freeze record: {rel}")
        recorded[rel] = item
    try:
        expected = expected_files(project)
    except ValueError as exc:
        return False, problems + [str(exc)], len(recorded)

    # 1.9.0: only uploaded files bind the confirmation, and they bind by visible content
    # (a re-zipped DOCX/XLSX with new timestamps is the same file). Internal QC, notes,
    # receipts and caches are recorded as evidence but never invalidate the user's OK.
    from .determinism import content_sha256
    uploads = upload_files(project)

    def is_upload(rel: str) -> bool:
        role = recorded.get(rel, {}).get("role")
        return role == "upload" if role else rel in uploads
    added = sorted(r for r in set(expected) - set(recorded) if r in uploads)
    removed = sorted(r for r in set(recorded) - set(expected) if is_upload(r))
    if added:
        problems.append("not frozen: " + ", ".join(added))
    if removed:
        problems.append("frozen file now absent: " + ", ".join(removed))
    for rel in sorted(set(expected) & set(recorded)):
        if not is_upload(rel):
            continue
        item = recorded[rel]
        path = expected[rel]
        if item.get("sha256") == _sha256(path):
            continue
        if item.get("content_sha256") and item["content_sha256"] == content_sha256(path):
            continue
        problems.append(f"changed after user confirmation: {rel}")
    return not problems, problems, len(recorded)
