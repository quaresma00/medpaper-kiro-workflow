"""1.9.0 deterministic derived files and visible-content hashes (stdlib only).

Two problems from a full S01-S25 run:

* Tools rewrite derived files (xlsx, docx, PDF, TIFF, manifest.json, qc_report.json) with a
  fresh timestamp each time, so an identical rebuild produced a new SHA-256 and the next gate
  reported "changed source drifted" - and a bookkeeping-only revision round followed.
* Confirmation hashed every byte, so a container timestamp invalidated the user's OK.

`normalize(path)` makes a written file byte-stable (fixed zip entry dates and docProps
timestamps, PDF CreationDate/ModDate/ID, no TIFF DateTime). `content_sha256(path)` hashes only
what a reader sees (zip parts without docProps, PDF without dates/ID, JSON without timestamp
keys), so it is stable even for files written before normalisation existed.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from pathlib import Path

FIXED_ZIP_DATE = (1980, 1, 1, 0, 0, 0)
FIXED_ISO = "2000-01-01T00:00:00Z"
_ZIP_SUFFIXES = {".docx", ".xlsx", ".pptx"}
_PDF_DATE_RE = re.compile(rb"/(CreationDate|ModDate)\s*\((?:[^()\\]|\\.)*\)")
_PDF_ID_RE = re.compile(rb"/ID\s*\[\s*<[0-9A-Fa-f]*>\s*<[0-9A-Fa-f]*>\s*\]")
_PDF_XMP_RE = re.compile(rb"<(xmp:(?:CreateDate|ModifyDate|MetadataDate)|xmpMM:(?:DocumentID|InstanceID))>"
                         rb"[^<]*</\1>")
_TS_KEY_RE = re.compile(r"(?:^|_)(?:at|time|timestamp|generated|created|modified|date)$", re.I)
_CORE_TS_RE = re.compile(r"(<dcterms:(created|modified)[^>]*>)[^<]*(</dcterms:\2>)")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def raw_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# visible content
# ---------------------------------------------------------------------------
def _strip_json(value):
    if isinstance(value, dict):
        return {k: _strip_json(v) for k, v in sorted(value.items()) if not _TS_KEY_RE.search(str(k))}
    if isinstance(value, list):
        return [_strip_json(v) for v in value]
    return value


def content_sha256(path: Path) -> str:
    """Hash of what a reader or an uploaded portal sees; raw SHA-256 for anything else."""
    path = Path(path)
    suffix = path.suffix.casefold()
    try:
        if suffix in _ZIP_SUFFIXES:
            digest = hashlib.sha256()
            with zipfile.ZipFile(path) as zf:
                for name in sorted(zf.namelist()):
                    if name.startswith("docProps/") or name.endswith("/"):
                        continue
                    digest.update(name.encode("utf-8") + b"\0" + zf.read(name) + b"\0")
            # Bytes after the end-of-central-directory record are not part of any entry but
            # are still a different file; they must not hide behind an equal content hash.
            data = path.read_bytes()
            eocd = data.rfind(b"PK\x05\x06")
            if eocd >= 0 and len(data) >= eocd + 22:
                end = eocd + 22 + int.from_bytes(data[eocd + 20:eocd + 22], "little")
                digest.update(b"tail\0" + data[end:])
            return "c:" + digest.hexdigest()
        if suffix == ".pdf":
            data = path.read_bytes()
            data = _PDF_DATE_RE.sub(b"", data)
            data = _PDF_ID_RE.sub(b"", data)
            data = _PDF_XMP_RE.sub(b"", data)
            return "c:" + sha256_bytes(data)
        if suffix in (".tif", ".tiff"):
            try:
                from PIL import Image
                with Image.open(path) as im:
                    im.load()
                    payload = f"{im.mode}|{im.size}|{im.info.get('dpi')}".encode() + im.tobytes()
                return "c:" + sha256_bytes(payload)
            except Exception:  # noqa: BLE001 - no Pillow or unreadable: raw bytes
                return raw_sha256(path)
        if suffix == ".json" and path.name in ("manifest.json", "qc_report.json"):
            data = json.loads(path.read_text(encoding="utf-8"))
            return "c:" + sha256_bytes(json.dumps(_strip_json(data), sort_keys=True).encode("utf-8"))
    except (OSError, ValueError, zipfile.BadZipFile):
        return raw_sha256(path)
    return raw_sha256(path)


def same(path: Path, recorded: str | None, recorded_content: str | None = None) -> bool:
    """Does the file on disk still match a receipt (raw hash, or the visible-content hash)?"""
    path = Path(path)
    if not path.is_file() or not recorded:
        return False
    raw = raw_sha256(path)
    if raw.casefold() == str(recorded).casefold():
        return True
    content = content_sha256(path)
    return bool(content.startswith("c:") and content in {str(recorded), str(recorded_content or "")})


# ---------------------------------------------------------------------------
# byte-stable writers
# ---------------------------------------------------------------------------
def _normalize_zip(path: Path, blind: bool = False) -> None:
    with zipfile.ZipFile(path) as src:
        entries = [(info, src.read(info.filename)) for info in src.infolist()]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as out:
        for info, blob in entries:
            if info.filename == "docProps/core.xml":
                text = blob.decode("utf-8")
                text = _CORE_TS_RE.sub(lambda m: m.group(1) + FIXED_ISO + m.group(3), text)
                if blind:
                    text = re.sub(r"(<(dc:creator|cp:lastModifiedBy)[^>]*>)[^<]*(</\2>)",
                                  r"\1\3", text)
                blob = text.encode("utf-8")
            elif info.filename == "docProps/app.xml" and blind:
                text = blob.decode("utf-8")
                text = re.sub(r"(<(Company|Manager)>)[^<]*(</\2>)", r"\1\3", text)
                blob = text.encode("utf-8")
            fixed = zipfile.ZipInfo(info.filename, date_time=FIXED_ZIP_DATE)
            fixed.compress_type = zipfile.ZIP_DEFLATED
            fixed.external_attr = info.external_attr
            out.writestr(fixed, blob)
    data = buf.getvalue()
    if path.read_bytes() != data:
        path.write_bytes(data)


def _normalize_pdf(path: Path) -> None:
    data = path.read_bytes()

    def date(m):  # same length keeps every xref offset valid
        body = m.group(0)
        head = body[:body.index(b"(") + 1]
        inner = len(body) - len(head) - 1
        # Same rule as .mf_pdf_stable() in medfig.R, so either pass leaves identical bytes.
        stamp = (b"D:20000101000000Z" + b" " * inner)[:inner]
        return head + stamp + b")"
    new = _PDF_DATE_RE.sub(date, data)

    def ident(m):
        body = m.group(0)
        return re.sub(rb"[0-9A-Fa-f]", b"0", body)
    new = _PDF_ID_RE.sub(ident, new)
    if new != data:
        path.write_bytes(new)


def _normalize_tiff(path: Path) -> None:
    try:
        from PIL import Image
    except ImportError:
        return
    with Image.open(path) as im:
        tags = getattr(im, "tag_v2", {})
        if 306 not in tags:  # DateTime
            return
        im.load()
        info = {k: v for k, v in tags.items() if k != 306}
        dpi = im.info.get("dpi")
        copy = im.copy()
    kwargs = {"compression": "tiff_lzw", "tiffinfo": info}
    if dpi:
        kwargs["dpi"] = dpi
    copy.save(path, format="TIFF", **kwargs)


def normalize(path: Path, *, blind: bool = False) -> Path:
    """Make a written derived file byte-stable. Unknown types are left untouched."""
    path = Path(path)
    if not path.is_file():
        return path
    suffix = path.suffix.casefold()
    try:
        if suffix in _ZIP_SUFFIXES:
            _normalize_zip(path, blind=blind)
        elif suffix == ".pdf":
            _normalize_pdf(path)
        elif suffix in (".tif", ".tiff"):
            _normalize_tiff(path)
    except (OSError, ValueError, zipfile.BadZipFile):
        pass
    return path


def main(argv: list[str] | None = None) -> int:
    """`python -m wfcore.determinism FILE...` (used by the R figure saver)."""
    import sys
    for arg in (argv if argv is not None else sys.argv[1:]):
        normalize(Path(arg))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
