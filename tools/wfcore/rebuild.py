"""1.15.0 (E3): one command rebuilds the submission package after an edit.

Before 1.15.0 one text edit needed, by hand and in order: build_docx (per file) -> audit ->
submission_qc write -> package_content capture --replace -> polish lint/diff -> rework check.
`wf rebuild` (package scope) runs the steps in dependency order for the affected outputs only:

    1. polish lint + diff        when the journal copy changed (08_submission/manuscript/)
    2. every engine-built upload whose build receipt no longer matches its inputs
       (Word builds, supplementary figure PDFs, workbook info sheets), from the receipt
    3. separate display files (main figure TIFFs, table workbooks) when the journal wants them
    4. build_docx audit --manifest, submission_qc write
    5. package_content capture (--replace inside an open round or at S23; otherwise verify)
    6. rework check --quiet when a revision round is open

Derived outputs are recorded into the open round by each tool (1.14.1 B2). Every step's full
output goes to .wf/logs/rebuild.log; stdout keeps failures and one summary line.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

RECEIPTS = "08_submission/build_receipts"
MANIFEST = "08_submission/bundle/manifest.json"
STYLE = "08_submission/docx_style.json"


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest().upper()


def _abs(project: Path, raw: str) -> Path:
    p = Path(raw)
    return p if p.is_absolute() else Path(project) / p


def receipts(project: Path) -> list[dict]:
    root = Path(project) / RECEIPTS
    out = []
    for path in sorted(root.glob("*.json")) if root.is_dir() else []:
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(rec, dict) and rec.get("output") and rec.get("kind"):
            rec["_receipt"] = path
            out.append(rec)
    return out


def stale(project: Path, rec: dict) -> list[str]:
    """Why a receipt's output must be rebuilt (empty = current)."""
    why = []
    out = _abs(project, rec["output"])
    if not out.is_file():
        return ["output missing"]
    for item in [*rec.get("sources", []), *rec.get("auxiliaries", [])]:
        p = _abs(project, item.get("path", ""))
        if not p.is_file():
            why.append(f"{item.get('path')} missing")
        elif _sha(p).upper() != str(item.get("sha256", "")).upper():
            why.append(f"{item.get('path')} changed")
    if rec.get("pdf_output") and not _abs(project, rec["pdf_output"]).is_file():
        why.append("PDF missing")
    return why


def hand_edited(project: Path, rec: dict) -> bool:
    out = _abs(project, rec["output"])
    return out.is_file() and _sha(out) != str(rec.get("output_sha256", "")).upper()


def build_command(project: Path, rec: dict) -> list[str]:
    """The builder call that reproduces a receipt (new receipts store their arguments)."""
    tools = Path(__file__).resolve().parents[1]
    kind = rec["kind"]
    if kind in ("esm_figures", "esm_xlsx"):
        return [sys.executable, str(tools / "supplementary.py"), "rebuild", "--receipt",
                str(rec["_receipt"])]
    args = rec.get("args") or {}
    cmd = [sys.executable, str(tools / "manuscript/build_docx.py"), "build", "--kind", kind]
    for s in rec.get("sources", []):
        cmd += ["--input", str(_abs(project, s["path"]))]
    cmd += ["--output", str(_abs(project, rec["output"]))]
    style = args.get("style_config")
    bib, csl = args.get("bibliography"), args.get("csl")
    for a in rec.get("auxiliaries", []):
        path = str(a.get("path", ""))
        low = path.casefold()
        if style is None and low.endswith(".json") and "target_journal" not in low:
            style = path
        elif bib is None and low.endswith((".bib", ".json")) and "refs" in low:
            bib = path
        elif csl is None and low.endswith(".csl"):
            csl = path
    cmd += ["--style-config", str(_abs(project, style or STYLE))]
    if bib:
        cmd += ["--bibliography", str(_abs(project, bib))]
    if csl:
        cmd += ["--csl", str(_abs(project, csl))]
    if rec.get("pdf_output") or args.get("pdf"):
        cmd.append("--pdf")
    if args.get("esm_number"):
        cmd += ["--esm-number", str(args["esm_number"])]
    return cmd


class _Log:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = path.open("w", encoding="utf-8")
        self.failures: list[str] = []
        self.done: list[str] = []

    def run(self, label: str, cmd: list[str], project: Path, ok_codes=(0,)) -> int:
        env = {**os.environ, "MEDPAPER_PROJECT": str(project), "PYTHONIOENCODING": "utf-8",
               "MEDPAPER_WAIT_CHILD": "1"}
        self.fh.write(f"\n=== {label}\n$ {' '.join(cmd)}\n")
        self.fh.flush()
        # list arguments, never a shell: Chinese paths reach the tool unchanged (UTF-8).
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", env=env, cwd=str(project), timeout=1800)
        out = (proc.stdout or "") + (proc.stderr or "")
        self.fh.write(out + f"\n[rc={proc.returncode}]\n")
        self.fh.flush()
        if proc.returncode not in ok_codes:
            tail = [ln.strip() for ln in out.splitlines() if ln.strip()][-4:]
            self.failures.append(f"FAIL {label} (rc={proc.returncode}): " + " | ".join(tail)[:400])
        else:
            self.done.append(label)
        return proc.returncode

    def note(self, text: str) -> None:
        self.fh.write(text + "\n")
        self.fh.flush()

    def close(self) -> None:
        self.fh.close()


def _state(project: Path) -> dict:
    try:
        return json.loads((Path(project) / ".wf/state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def plan(project: Path, everything: bool = False) -> tuple[list[dict], list[str]]:
    """(receipts to rebuild, notes) without running anything."""
    todo, notes = [], []
    for rec in receipts(project):
        why = stale(project, rec)
        if hand_edited(project, rec) and not everything:
            notes.append(f"{rec['output']}: differs from its build (hand edit?) - not rebuilt; "
                         "use rework.py layout for Word-only edits or --all to rebuild it")
            continue
        if why or everything:
            rec["_why"] = why or ["--all"]
            todo.append(rec)
    return todo, notes


def run(project: Path, everything: bool = False, dry: bool = False) -> int:
    project = Path(project)
    tools = Path(__file__).resolve().parents[1]
    py = sys.executable
    st = _state(project)
    in_round = bool(st.get("active_revision_round"))
    todo, notes = plan(project, everything)
    for n in notes:
        print(n)
    if dry:
        for rec in todo:
            print(f"would rebuild {rec['output']} ({'; '.join(rec['_why'])[:160]})")
        print(f"rebuild dry run: {len(todo)} output(s) affected")
        return 0
    log = _Log(project / ".wf/logs/rebuild.log")
    try:
        journal_copy = project / "08_submission/manuscript"
        snap = [p for p in (project / "07_manuscript/prepolish/facts.json",
                            project / "08_submission/manuscript/prepolish/facts.json") if p.is_file()]
        copy_changed = any("08_submission/manuscript/" in w for rec in todo for w in rec["_why"])
        if journal_copy.is_dir() and snap and (copy_changed or everything):
            log.run("polish lint", [py, str(tools / "text/polish.py"), "lint"], project)
            log.run("polish diff", [py, str(tools / "text/polish.py"), "diff"], project)
        for rec in todo:
            log.run(f"build {rec['output']}", build_command(project, rec), project)
        from . import displayfiles
        try:
            made = displayfiles.sync(project)
            if made:
                log.done.append(f"display files ({len(made)})")
                log.note("display files: " + ", ".join(made))
        except ValueError as exc:
            log.failures.append(f"FAIL display files: {exc}")
        if (project / MANIFEST).is_file():
            log.run("audit", [py, str(tools / "manuscript/build_docx.py"), "audit", "--manifest",
                              str(project / MANIFEST), "--style-config", str(project / STYLE)],
                    project)
            log.run("submission_qc", [py, str(tools / "manuscript/submission_qc.py"), "write"],
                    project)
        cap = (in_round or st.get("current") == "S23_package") and (project / MANIFEST).is_file()
        base = project / "08_submission/package_content_baseline.json"
        if cap:
            log.run("package capture", [py, str(tools / "package_content.py"), "capture",
                                        *(["--replace"] if base.is_file() else [])], project)
        elif base.is_file():
            log.run("package verify", [py, str(tools / "package_content.py"), "verify"], project)
        if in_round:
            log.run("rework check", [py, str(tools / "rework.py"), "check", "--quiet"], project)
    finally:
        log.close()
    for f in log.failures:
        print(f)
    print(f"[rebuild] {len(todo)} output(s) rebuilt; steps ok: {len(log.done)}; failures: "
          f"{len(log.failures)}; details: {log.path}")
    return 2 if log.failures else 0
