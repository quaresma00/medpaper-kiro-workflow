#!/usr/bin/env python3
"""Check the rendered reference list against the journal's own example (1.9.0, #14).

    .\\.venv\\Scripts\\python.exe tools/manuscript/csl_check.py --csl project/08_submission/journal.csl \\
        --example "Kim JH, Lee S. Title of the article. Korean J Anesthesiol 2020; 73: 1-9."

Renders every refs.bib entry with Pandoc + the CSL (paper-local 08_submission/csl_patch.json
applied, exactly as build_docx does) and reports:
  * the punctuation skeleton of the official example next to the first rendered reference
    (letters -> a, digits -> 9), so "2020;73:1-9" vs "2020; 73: 1-9" is visible at a glance;
  * acronyms / proper nouns braced in refs.bib that came out lower-cased (text-case="sentence");
  * inconsistent capitalisation of the first word after a colon in titles;
  * hyphens inside author initials ("Kim J-H") - fix with csl_patch.json
    {"initialize_with_hyphen": false}, which build_docx puts on the <style> root (a value on
    <name> is ignored by CSL processors).
Exit 0 = no defect found; 2 = defects listed. Never edits refs.bib.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools/manuscript"))
from wfcore import paths as wfpaths  # noqa: E402


def skeleton(text: str) -> str:
    text = re.sub(r"[A-Za-z\u00C0-\u024F]+", "a", text)
    return re.sub(r"\d+", "9", text)


def render(bib: Path, csl: Path) -> list[str]:
    import build_docx
    pandoc = shutil.which("pandoc")
    if not pandoc:
        raise RuntimeError("pandoc is required")
    keys = re.findall(r"@\w+\s*\{\s*([^,\s]+)\s*,", bib.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="medpaper_csl_") as tmp:
        work = Path(tmp)
        style = build_docx.collapsing_csl(csl, work) or csl
        md = work / "refs.md"
        md.write_text("---\nnocite: |\n  " + ", ".join(f"@{k}" for k in keys) + "\n---\n",
                      encoding="utf-8")
        proc = subprocess.run([pandoc, str(md), "--citeproc", f"--bibliography={bib}",
                               f"--csl={style}", "-t", "plain", "--wrap=none"],
                              capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=300)
    if proc.returncode:
        raise RuntimeError(proc.stderr.strip()[:400])
    return [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]


def problems(refs: list[str], bib_text: str, csl_text: str) -> list[str]:
    out = []
    braced = {w for w in re.findall(r"\{([A-Za-z][\w-]*)\}", bib_text)
              if any(c.isupper() for c in w)}
    for i, ref in enumerate(refs, 1):
        for w in braced:
            low = w.lower()
            if low != w and re.search(rf"(?<![\w-]){re.escape(low)}(?![\w-])", ref) and w not in ref:
                out.append(f"ref {i}: '{w}' rendered as '{low}' (protect it; check text-case)")
        if re.search(r"\b[A-Z]-[A-Z]\b", ref.split(".")[0]):
            out.append(f"ref {i}: hyphen in author initials - csl_patch.json "
                       '{"initialize_with_hyphen": false}')
    after = [m.group(1)[0] for r in refs for m in re.finditer(r":\s+([A-Za-z])\w*", r.split(". ", 2)[1]
                                                             if r.count(". ") >= 2 else "")]
    if after and 0 < sum(c.isupper() for c in after) < len(after):
        out.append(f"first word after a colon in titles is capitalised in {sum(c.isupper() for c in after)}"
                   f" of {len(after)} references - make it consistent with the journal example")
    if re.search(r"<name\b[^>]*initialize-with-hyphen", csl_text):
        out.append("initialize-with-hyphen is set on <name>, where it is ignored; put it on <style> "
                   "(csl_patch.json initialize_with_hyphen)")
    return sorted(set(out))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="compare CSL output with the journal example")
    ap.add_argument("--csl", type=Path, required=True)
    ap.add_argument("--bib", type=Path, default=None)
    ap.add_argument("--example", help="one reference copied verbatim from the official guide")
    args = ap.parse_args(argv)
    proj = wfpaths.project_dir()

    def resolve(p: Path) -> Path:
        s = p.as_posix()
        return p if p.is_absolute() else proj / (s[len("project/"):] if s.startswith("project/") else s)
    csl, bib = resolve(args.csl), resolve(args.bib or Path("06_refs/refs.bib"))
    try:
        refs = render(bib, csl)
    except RuntimeError as exc:
        print(f"csl_check: {exc}", file=sys.stderr)
        return 2
    print(f"{len(refs)} reference(s) rendered with {csl.name}")
    if refs:
        print(f"  first:    {refs[0]}")
    if args.example:
        print(f"  example:  {args.example}")
        print(f"  skeleton example:  {skeleton(args.example)}")
        print(f"  skeleton rendered: {skeleton(refs[0]) if refs else ''}")
    found = problems(refs, bib.read_text(encoding="utf-8"), csl.read_text(encoding="utf-8"))
    for p in found:
        print(f"  DEFECT {p}")
    print("no CSL defect detected" if not found else f"{len(found)} CSL defect(s)")
    return 0 if not found else 2


if __name__ == "__main__":
    raise SystemExit(main())
