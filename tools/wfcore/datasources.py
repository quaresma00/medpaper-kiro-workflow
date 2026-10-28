"""1.13.0: the user's datasets are referenced in place, read-only, and never copied. Stdlib only.

A paper declares each dataset once (`wf data add <path>`); the record lives in the paper's
config (`.wf/data_sources.json`: name, absolute path, kind, bytes, files, mtime). Hashes are
computed lazily and cached by size + mtime (`.wf/hash_cache.json`), so a 3.7 GB archive folder
is hashed once, not on every gate. Analysis code reads the original location
(`analysis.datasources.source_path(name)`); archives are streamed member by member; when
extraction is unavoidable only the needed members go to a size-capped cache inside the paper.

Engine operations that would copy more than `data_copy_limit_mb` (default 200 MB) of input
data refuse instead (reproduce.py, data checks). Small derived analysis datasets may be
written in the paper (02_data/derived/).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

REL = ".wf/data_sources.json"
CACHE_REL = ".wf/hash_cache.json"
LABEL_PREFIX = "datasource:"
COPY_LIMIT_MB_DEFAULT = 200
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}$")
_CACHES: dict[str, dict] = {}


def _norm(p) -> str:
    return os.path.normcase(str(Path(p).resolve()))


def _within(child, parent) -> bool:
    a, b = _norm(child), _norm(parent)
    try:
        return os.path.commonpath([a, b]) == b
    except ValueError:
        return False


def load(project: Path) -> list[dict]:
    p = Path(project) / REL
    if not p.is_file():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    items = data.get("sources") if isinstance(data, dict) else None
    return [s for s in (items or []) if isinstance(s, dict) and s.get("name") and s.get("path")]


def save(project: Path, items: list[dict]) -> None:
    p = Path(project) / REL
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps({"schema": 1, "sources": items}, indent=2, ensure_ascii=False)
                   + "\n", encoding="utf-8")
    os.replace(tmp, p)


def paths_of(project: Path) -> list[Path]:
    return [Path(s["path"]) for s in load(project)]


def location_problem(project: Path, path: Path | str) -> str | None:
    """Why `path` cannot be registered for this paper (None = fine)."""
    from . import paths as wp
    p = Path(path).expanduser()
    if not p.is_absolute():
        return f"{path}: give the absolute path of the dataset"
    if not p.exists():
        return f"{p} does not exist"
    p = p.resolve()
    project = Path(project).resolve()
    if wp.in_engine(p):
        return f"{p} is inside the medpaper engine"
    if _within(project, p):
        return (f"the paper {project} lies inside the data folder {p}; a paper never lives in "
                "its data folder")
    if _norm(project) == _norm(p.parent):
        return (f"the paper {project} is the parent of the data folder {p}; the data folder's "
                "parent is never a working path - keep the dataset outside the paper and "
                "register it in place")
    if _within(p, project):
        return f"{p} is already inside this paper; read it there (no registration needed)"
    for anc in [p, *p.parents]:
        if (anc / ".wf" / "state.json").is_file() and _norm(anc) != _norm(project):
            return f"{p} belongs to another paper; never read another paper's data"
    return None


def _scan(p: Path) -> tuple[str, int, int, int]:
    if p.is_file():
        st = p.stat()
        return "file", st.st_size, 1, st.st_mtime_ns
    total, n, newest = 0, 0, 0
    for dirpath, _dirs, files in os.walk(p):
        for f in files:
            try:
                st = (Path(dirpath) / f).stat()
            except OSError:
                continue
            total, n, newest = total + st.st_size, n + 1, max(newest, st.st_mtime_ns)
    return "dir", total, n, newest


def add(project: Path, path: Path | str, name: str | None = None, note: str = "") -> dict:
    why = location_problem(project, path)
    if why:
        raise ValueError(why)
    p = Path(path).expanduser().resolve()
    name = (name or re.sub(r"[^a-z0-9_-]+", "-", p.stem.lower()).strip("-") or "data")[:40]
    if not NAME_RE.match(name):
        raise ValueError(f"data source name {name!r}: lowercase letters, digits, '-' or '_'")
    items = [s for s in load(project) if s["name"] != name]
    if any(_norm(s["path"]) == _norm(p) for s in items):
        raise ValueError(f"{p} is already registered")
    kind, size, n, mtime = _scan(p)
    rec = {"name": name, "path": str(p), "kind": kind, "bytes": size, "files": n,
           "mtime_ns": mtime, "read_only": True, "note": note,
           "added_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    items.append(rec)
    save(project, items)
    return rec


def remove(project: Path, name: str) -> bool:
    items = load(project)
    keep = [s for s in items if s["name"] != name]
    if len(keep) == len(items):
        return False
    save(project, keep)
    return True


def files(project: Path) -> list[tuple[str, Path]]:
    """(label, absolute path) of every file of every source; label = datasource:<name>/<rel>."""
    out: list[tuple[str, Path]] = []
    for s in load(project):
        root = Path(s["path"])
        if root.is_file():
            out.append((f"{LABEL_PREFIX}{s['name']}/{root.name}", root))
        elif root.is_dir():
            for p in sorted(x for x in root.rglob("*") if x.is_file()):
                out.append((f"{LABEL_PREFIX}{s['name']}/{p.relative_to(root).as_posix()}", p))
    return out


def resolve(project: Path, label: str) -> Path | None:
    """Absolute path of a datasource:<name>/<rel> label (None when unknown)."""
    if not isinstance(label, str) or not label.startswith(LABEL_PREFIX):
        return None
    name, _, rel = label[len(LABEL_PREFIX):].partition("/")
    for s in load(project):
        if s["name"] == name:
            root = Path(s["path"])
            if root.is_file():
                return root if rel in ("", root.name) else None
            cand = (root / rel).resolve()
            return cand if _within(cand, root) else None
    return None


# ---------------------------------------------------------------------------
# lazy hashing, cached by size + mtime
# ---------------------------------------------------------------------------
def _cache(project: Path) -> dict:
    key = _norm(project)
    if key not in _CACHES:
        p = Path(project) / CACHE_REL
        try:
            data = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
        except (OSError, ValueError):
            data = {}
        _CACHES[key] = data if isinstance(data, dict) else {}
    return _CACHES[key]


def _flush(project: Path) -> None:
    p = Path(project) / CACHE_REL
    if not p.parent.is_dir():
        return
    tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(_cache(project), indent=0, sort_keys=True), encoding="utf-8")
        os.replace(tmp, p)
    except OSError:
        tmp.unlink(missing_ok=True)


def _raw_sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def cached_sha256(project: Path | None, path: Path) -> str:
    """SHA-256 of `path`, reused while its size and mtime are unchanged."""
    path = Path(path)
    if project is None or not (Path(project) / ".wf").is_dir():
        return _raw_sha(path)
    st = path.stat()
    cache = _cache(project)
    key = _norm(path)
    hit = cache.get(key)
    if isinstance(hit, list) and len(hit) == 3 and hit[0] == st.st_size and hit[1] == st.st_mtime_ns:
        return hit[2]
    sha = _raw_sha(path)
    cache[key] = [st.st_size, st.st_mtime_ns, sha]
    _flush(project)
    return sha


def inventory(project: Path) -> list[dict]:
    """dataproof-style entries for the registered sources (hashes cached)."""
    return [{"path": label, "sha256": cached_sha256(project, p), "bytes": p.stat().st_size}
            for label, p in files(project)]


def copy_limit_bytes(project: Path | None) -> int:
    mb = COPY_LIMIT_MB_DEFAULT
    if project is not None:
        try:
            import tomllib
            cfg = Path(project) / ".wf" / "config.toml"
            if cfg.is_file():
                raw = tomllib.loads(cfg.read_text(encoding="utf-8")).get("targets", {}) \
                    .get("data_copy_limit_mb")
                if raw is not None:
                    mb = float(raw)
        except (OSError, ValueError, TypeError):
            pass
    return int(mb * 1024 * 1024)


def describe(project: Path) -> list[str]:
    """One line per declared source, for wf status / wf handoff."""
    out = []
    for s in load(project):
        size = s.get("bytes", 0) / 1e6
        state = "" if Path(s["path"]).exists() else "  !! MISSING"
        out.append(f"{s['name']}: {s['path']} ({s.get('kind')}, {s.get('files', '?')} file(s), "
                   f"{size:,.1f} MB, read-only, in place){state}")
    return out
