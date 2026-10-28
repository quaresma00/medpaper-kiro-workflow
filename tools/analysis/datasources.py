"""Read the paper's declared datasets in place, read-only - never copy them (1.13.0).

    from analysis.datasources import source_path, members, open_member
    raw = source_path("faers")                              # absolute folder or file
    for name in members("faers", "aers_ascii_2004q1.zip"):  # list an archive without extracting
        ...
    with open_member("faers", "aers_ascii_2004q1.zip", "ascii/DEMO04Q1.TXT") as fh:  # stream
        ...

Declare a dataset once with `wf data add <absolute path> --name faers`. In the S06 sandbox the
same calls resolve to the same original files, so nothing is copied. Extraction is a last
resort: extract_members() writes only the named members into 02_data/cache/<name>/ inside the
paper, refuses beyond data_copy_limit_mb, and clear_cache() removes the cache.
"""
from __future__ import annotations

import io
import shutil
import tarfile
import zipfile
from contextlib import contextmanager
from pathlib import Path

from wfcore import datasources as _ds
from wfcore import paths

CACHE_REL = "02_data/cache"


def _paper() -> Path:
    return paths.project_dir()


def source_path(name: str, *parts: str) -> Path:
    """Absolute path of a declared data source (optionally a file inside it)."""
    for s in _ds.load(_paper()):
        if s["name"] == name:
            base = Path(s["path"])
            p = base.joinpath(*parts) if parts else base
            if parts and not str(p.resolve()).startswith(str(base.resolve())):
                raise ValueError(f"{'/'.join(parts)} escapes the data source {name}")
            return p
    raise KeyError(f"data source {name!r} is not declared; run: wf data add <path> --name {name}")


def _archive(name: str, archive: str) -> Path:
    p = source_path(name, archive) if archive else source_path(name)
    if not p.is_file():
        raise FileNotFoundError(p)
    return p


def members(name: str, archive: str = "") -> list[str]:
    p = _archive(name, archive)
    if zipfile.is_zipfile(p):
        with zipfile.ZipFile(p) as zf:
            return [n for n in zf.namelist() if not n.endswith("/")]
    with tarfile.open(p) as tf:
        return [m.name for m in tf.getmembers() if m.isfile()]


@contextmanager
def open_member(name: str, archive: str, member: str, encoding: str | None = None,
                errors: str = "strict"):
    """Stream one member of a .zip/.tar(.gz) data source without extracting it.
    Binary file object by default; text when `encoding` is given."""
    p = _archive(name, archive)
    if zipfile.is_zipfile(p):
        zf = zipfile.ZipFile(p)
        try:
            names = {n.casefold(): n for n in zf.namelist()}
            if member.casefold() not in names:
                raise KeyError(f"{member} is not in {p.name}")
            raw = zf.open(names[member.casefold()])
            fh = io.TextIOWrapper(raw, encoding=encoding, errors=errors, newline="") \
                if encoding else raw
            try:
                yield fh
            finally:
                fh.close()
        finally:
            zf.close()
        return
    tf = tarfile.open(p)
    try:
        raw = tf.extractfile(member)
        if raw is None:
            raise KeyError(f"{member} is not a file in {p.name}")
        fh = io.TextIOWrapper(raw, encoding=encoding, errors=errors, newline="") if encoding else raw
        try:
            yield fh
        finally:
            fh.close()
    finally:
        tf.close()


def extract_members(name: str, archive: str, wanted: list[str]) -> list[Path]:
    """Last resort (a reader that needs a real file): extract only `wanted` into
    02_data/cache/<name>/, refusing when the cache would exceed data_copy_limit_mb."""
    paper = _paper()
    limit = _ds.copy_limit_bytes(paper)
    dest = paper / CACHE_REL / name
    used = sum(f.stat().st_size for f in (paper / CACHE_REL).rglob("*") if f.is_file()) \
        if (paper / CACHE_REL).is_dir() else 0
    out = []
    p = _archive(name, archive)
    with zipfile.ZipFile(p) as zf:
        infos = {i.filename.casefold(): i for i in zf.infolist()}
        for m in wanted:
            info = infos.get(m.casefold())
            if info is None:
                raise KeyError(f"{m} is not in {p.name}")
            if used + info.file_size > limit:
                raise RuntimeError(f"extracting {m} would put {(used + info.file_size) / 1e6:,.0f}"
                                   f" MB in {CACHE_REL} (limit {limit / 1e6:,.0f} MB): stream it "
                                   "with open_member() instead")
            target = (dest / info.filename).resolve()
            if not str(target).startswith(str(dest.resolve())):
                raise ValueError(f"unsafe member path {info.filename}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as fh:
                shutil.copyfileobj(src, fh)
            used += info.file_size
            out.append(target)
    return out


def clear_cache(name: str | None = None) -> None:
    root = _paper() / CACHE_REL
    target = root / name if name else root
    if target.is_dir():
        shutil.rmtree(target)
