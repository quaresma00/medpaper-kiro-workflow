#!/usr/bin/env python3
"""1.17.0 (J6): the journal's citation style by ISSN.

    build  [--zip styles.zip] [--out reference/csl_issn_index.json]
           MAINTAINER ONLY (network allowed only here): read every dependent/*.csl of
           github.com/citation-style-language/styles (branch v1.0.2) and write the ISSN ->
           (dependent style, independent parent) index; independent styles that name an ISSN
           are included as their own parent. Without --zip the branch archive is downloaded.
    lookup --issn ISSN
           print the index entry (offline).
    fetch  --issn ISSN [--project DIR]
           download the dependent and parent CSL from the v1.0.2 branch (cached in the paper's
           08_submission/cache/csl/ with the date), copy the parent to
           08_submission/<parent>.csl and record target_journal.json "csl" {style_id, parent,
           issn, file, fetched_at}. Fixtures: MEDPAPER_HTTP_FIXTURES (wfcore/journallookup.py).

The styles are CC BY-SA 3.0, (c) the Citation Style Language project and contributors,
https://citationstyles.org - see reference/CSL_STYLES_ATTRIBUTION.md.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from wfcore import cslindex  # noqa: E402

ARCHIVE = "https://codeload.github.com/citation-style-language/styles/zip/refs/heads/v1.0.2"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_index(zbytes: bytes, source: str) -> dict:
    out: dict[str, list[str]] = {}
    styles = 0
    with zipfile.ZipFile(io.BytesIO(zbytes)) as z:
        for name in z.namelist():
            if not name.endswith(".csl"):
                continue
            dependent = "/dependent/" in name
            try:
                meta = cslindex.csl_meta_bytes(z.read(name))
            except Exception:  # noqa: BLE001 - a malformed style is skipped
                continue
            styles += 1
            sid = meta["id"] or Path(name).stem
            parent = meta["parent"] if dependent else sid
            if not parent:
                continue
            for issn in meta["issns"]:
                # a dependent style wins over an independent one naming the same ISSN
                if issn not in out or dependent:
                    out[issn] = [sid, parent]
    return {"schema": 1, "source": "github.com/citation-style-language/styles",
            "branch": "v1.0.2", "archive": source, "generated_at": _now(), "complete": True,
            "styles_read": styles, "license": "CC BY-SA 3.0 (citationstyles.org); see "
            "reference/CSL_STYLES_ATTRIBUTION.md", "issn": dict(sorted(out.items()))}


def cmd_build(args) -> int:
    if args.zip:
        data, source = Path(args.zip).read_bytes(), str(args.zip)
    else:
        import urllib.request
        req = urllib.request.Request(ARCHIVE, headers={"User-Agent": "medpaper-csl-index/1.17 "
                                                                     "(maintainer build)"})
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = resp.read()
        source = ARCHIVE
    index = build_index(data, source)
    out = Path(args.out) if args.out else ROOT / cslindex.INDEX
    out.write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")) + "\n",
                   encoding="utf-8")
    print(f"{len(index['issn'])} ISSN(s) from {index['styles_read']} style(s) -> {out}")
    return 0


def cmd_lookup(args) -> int:
    hit = cslindex.lookup(ROOT, args.issn)
    if not hit:
        print(f"ISSN {args.issn} 不在 CSL 索引中：在 zotero.org/styles 按刊名查找，或在 "
              "target_journal.json \"csl\" 里写明所用样式及理由（reason）")
        return 2
    print(json.dumps(hit, ensure_ascii=False))
    return 0


def _get(path: str) -> bytes:
    from wfcore import journallookup
    status, _ctype, body = journallookup.http_get(cslindex.RAW.format(path=path))
    if status != 200 or not body.lstrip().startswith(b"<"):
        raise RuntimeError(f"HTTP {status} for {path}")
    return body


def cmd_fetch(args) -> int:
    from wfcore import paths
    project = paths.paper_from_cli(args.project)
    hit = cslindex.lookup(ROOT, args.issn)
    if not hit:
        return cmd_lookup(args)
    cache = project / "08_submission/cache/csl"
    cache.mkdir(parents=True, exist_ok=True)
    got = {}
    for sid, rel in ((hit["style_id"], f"dependent/{hit['style_id']}.csl"),
                     (hit["parent"], f"{hit['parent']}.csl")):
        if sid == hit["parent"] and rel.startswith("dependent/"):
            continue
        dest = cache / f"{sid}.csl"
        if not dest.is_file():
            try:
                dest.write_bytes(_get(rel))
            except Exception as exc:  # noqa: BLE001 - offline / not found
                print(f"无法下载 {rel}（{exc}）：可从 https://github.com/citation-style-language/"
                      f"styles/tree/v1.0.2 手动下载后放到 {dest}")
                return 2
        got[sid] = dest
    parent = got[hit["parent"]]
    target = project / "08_submission" / f"{hit['parent']}.csl"
    target.write_bytes(parent.read_bytes())
    tj_path = project / "08_submission/target_journal.json"
    try:
        tj = json.loads(tj_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        tj = {}
    if isinstance(tj, dict) and tj:
        tj["csl"] = {"style_id": hit["style_id"], "parent": hit["parent"], "issn": hit["issn"],
                     "file": target.relative_to(project).as_posix(), "fetched_at": _now()[:10],
                     "source": cslindex.RAW.format(path=f"{hit['parent']}.csl")}
        tj_path.write_text(json.dumps(tj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"CSL：{hit['style_id']} -> {hit['parent']}；已写入 {target.relative_to(project).as_posix()}"
          + ("，并记录到 target_journal.json \"csl\"" if tj else "（target_journal.json 还不存在："
             "写入后补 \"csl\" 字段）"))
    print("样式来自 Citation Style Language 项目（citationstyles.org，CC BY-SA 3.0）")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="CSL style by journal ISSN (CSL styles v1.0.2)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--zip")
    b.add_argument("--out")
    for name in ("lookup", "fetch"):
        s = sub.add_parser(name)
        s.add_argument("--issn", required=True)
        s.add_argument("--project", type=Path, default=None)
    args = ap.parse_args(argv)
    return {"build": cmd_build, "lookup": cmd_lookup, "fetch": cmd_fetch}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
