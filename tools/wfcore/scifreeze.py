"""Freeze the settled scientific manuscript, then adapt a copy for each journal.

The problem this solves: journal requirements are presentation requirements - word caps,
abstract shape, reference style, column width, title-page format, which statements are
mandatory. Before this module existed, S21 and S22 applied them by editing
`07_manuscript/` in place, so choosing a different journal re-edited the manuscript that
review had already settled. Two journals meant two rounds of churn through the same
scientific text, and nothing recorded what had drifted.

The split:

    07_manuscript/            the science. Frozen when the user closes S19 review.
                              Claims, numbers, citations, structure. Never edited for a
                              journal, and a gate refuses to let it change.

    08_submission/manuscript/ the journal variant. A copy taken at S20 once the journal is
                              known. This is what S21/S22 adapt and S23 renders to DOCX.
                              Switching journals throws this away and takes a fresh copy;
                              the frozen science is untouched.

What is deliberately NOT frozen: rendered artifacts. Figure PNG/TIFF are re-rendered at the
chosen journal's column width and palette, and table workbooks are rebuilt into its format.
Those are presentation. Their *content* - legends, captions, the numbers behind them - is
frozen, so a re-render cannot change what a figure says.

Compatibility: with no freeze file on disk every resolver below returns the `07_manuscript/`
path, so a project that predates this module behaves exactly as it did.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

FREEZE_REL = "07_manuscript/scientific_freeze.json"
VARIANT_DIR = "08_submission/manuscript"
SOURCE_DIR = "07_manuscript"

# The scientific record. A change to any of these after S19 is a change to the science and
# must go back through review via tools/rework.py, never sideways through a journal edit.
REQUIRED_SCIENTIFIC = (
    "07_manuscript/full_manuscript.md",
    "06_refs/refs.bib",
    "06_refs/library.json",
)
OPTIONAL_SCIENTIFIC = (
    "07_manuscript/supplementary_methods.md",
    "07_manuscript/title.md",
    "07_manuscript/abstract.md",
    "07_manuscript/keywords.md",
    "07_manuscript/introduction.md",
    "07_manuscript/methods.md",
    "07_manuscript/results.md",
    "07_manuscript/discussion.md",
    "07_manuscript/statements.md",
    "05_figures/legends.md",
    "04_tables/table_captions.md",
    "06_refs/refs.ris",
    "06_refs/verified.json",
)

# Scientific prose copied from the reviewed source when a journal is selected. Only these
# participate in the science-preservation delta.
ADAPTED_TEXT_FILES = (
    "full_manuscript.md",
    "supplementary_methods.md",
    "title_page.md",
    "statements.md",
)

# Everything a journal-specific pass owns. Reports/snapshots belong beside the variant; writing
# them under 07_manuscript/ after S19 would violate the read-only boundary even if they did not
# alter full_manuscript.md itself.
VARIANT_FILES = (*ADAPTED_TEXT_FILES,
                 "polish_report.json", "polish_log.md", "polish_allowlist.tsv")
VARIANT_PREFIXES = ("prepolish/",)

# Produced after S20 and therefore invalid the moment the journal variant is replaced. S20's
# target/guideline/style files are deliberately not here: `open_variant --force` is called after
# those have been refreshed for the new journal. `reset-journal` clears the whole submission
# tree before a clean S20 rerun.
JOURNAL_DOWNSTREAM = (
    "08_submission/cover_letter.md",
    "08_submission/bundle",
    "08_submission/package_content_baseline.json",
    "08_submission/submission_qc.md",
    "08_submission/package_human_review.md",
    "08_submission/package_review_freeze.json",
    "08_submission/independent_submission_audit.md",
    "08_submission/build_receipts",
)

# Fact classes that must survive journal adaptation. Prose may be tightened to fit a word cap;
# a number, a citation or a figure/table reference may not quietly vanish while doing it.
NUM_RE = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?![\w.])")
CITE_RE = re.compile(r"\[@([^\]]+)\]")
ART_RE = re.compile(r"\b(Figure|Table)\s+(S?\d+)", re.I)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# resolution
# ---------------------------------------------------------------------------
def freeze_path(project: Path) -> Path:
    return project / FREEZE_REL


def is_frozen(project: Path) -> bool:
    return freeze_path(project).is_file()


def variant_exists(project: Path) -> bool:
    return (project / VARIANT_DIR / "full_manuscript.md").is_file()


def resolve(project: Path, rel: str) -> str:
    """Map a 07_manuscript-relative artifact to whichever copy is currently authoritative.

    Before the variant is opened this is the identity function, which is what keeps every
    existing gate spec and every in-flight project working unchanged.
    """
    rel = rel.replace("\\", "/")
    if not rel.startswith(f"{SOURCE_DIR}/"):
        return rel
    name = rel[len(SOURCE_DIR) + 1:]
    if ((name in VARIANT_FILES
         or any(name == prefix.rstrip("/") or name.startswith(prefix)
                for prefix in VARIANT_PREFIXES))
            and variant_exists(project)):
        return f"{VARIANT_DIR}/{name}"
    return rel


def resolve_all(project: Path, rels) -> list[str]:
    return [resolve(project, r) for r in rels]


# ---------------------------------------------------------------------------
# capture
# ---------------------------------------------------------------------------
def scientific_files(project: Path) -> tuple[dict[str, Path], list[str]]:
    files, missing = {}, []
    for rel in REQUIRED_SCIENTIFIC:
        p = project / rel
        if p.is_file() and p.stat().st_size > 0:
            files[rel] = p
        else:
            missing.append(rel)
    for rel in OPTIONAL_SCIENTIFIC:
        p = project / rel
        if p.is_file() and p.stat().st_size > 0:
            files[rel] = p
    return files, missing


def build_freeze(project: Path) -> dict:
    files, missing = scientific_files(project)
    if missing:
        raise SystemExit("cannot freeze; missing scientific source(s): " + ", ".join(missing))
    return {
        "schema": 1,
        "frozen_at": _now(),
        "note": "Scientific record settled at S19. Journal adaptation happens in "
                f"{VARIANT_DIR}/, never here.",
        "files": {rel: {"sha256": _sha256(p), "bytes": p.stat().st_size}
                  for rel, p in sorted(files.items())},
    }


def write_freeze(project: Path, *, force: bool = False) -> Path:
    path = freeze_path(project)
    if path.exists() and not force:
        raise SystemExit(
            f"{FREEZE_REL} already exists. Re-freezing discards the record that review closed "
            f"on this exact text.\n"
            f"  Legitimate reason to re-freeze: a rework round reopened a scientific stage and "
            f"the manuscript was genuinely rebuilt.\n"
            f"  Then pass --force."
        )
    payload = build_freeze(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def load_freeze(project: Path) -> dict:
    path = freeze_path(project)
    if not path.is_file():
        raise SystemExit(f"{FREEZE_REL} missing; the scientific record was never frozen")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{FREEZE_REL} is invalid JSON: {exc}")


def verify_freeze(project: Path) -> tuple[bool, list[str], int]:
    """Has any frozen scientific file changed since review closed?"""
    freeze = load_freeze(project)
    entries = freeze.get("files", {})
    if not entries:
        return False, [f"{FREEZE_REL} records no files"], 0
    problems = []
    for rel, meta in sorted(entries.items()):
        p = project / rel
        if not p.is_file():
            problems.append(f"{rel}: frozen scientific file is gone")
            continue
        if _sha256(p) != meta.get("sha256"):
            problems.append(f"{rel}: edited after the scientific freeze")
    return not problems, problems, len(entries)


# ---------------------------------------------------------------------------
# the journal variant
# ---------------------------------------------------------------------------
def _remove(path: Path) -> bool:
    if path.is_dir():
        shutil.rmtree(path)
        return True
    if path.exists():
        path.unlink()
        return True
    return False


def clear_journal_downstream(project: Path) -> list[str]:
    """Remove every S21+ artifact that cannot belong to a replacement journal variant."""
    removed = []
    for rel in JOURNAL_DOWNSTREAM:
        if _remove(project / rel):
            removed.append(rel)
    return removed


def reset_journal(project: Path) -> list[str]:
    """Start S20 from a blank submission area while leaving the scientific freeze intact."""
    ok, problems, _ = verify_freeze(project)
    if not ok:
        raise SystemExit("refusing journal reset: frozen science has drifted:\n  "
                         + "\n  ".join(problems))
    root = project / "08_submission"
    removed = []
    if root.exists():
        removed = [p.relative_to(project).as_posix() for p in root.rglob("*") if p.is_file()]
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    return removed


def open_variant(project: Path, journal: str, *, force: bool = False) -> tuple[Path, list[str]]:
    """Take a fresh journal-adaptation copy from the frozen scientific source."""
    ok, problems, _ = verify_freeze(project)
    if not ok:
        raise SystemExit(
            "refusing to open a journal variant: the frozen scientific source has changed.\n  "
            + "\n  ".join(problems)
            + "\nRoute the change through tools/rework.py to the stage that owns it, or restore "
              "the frozen text. A variant taken from drifted science is not traceable to review."
        )
    dest = project / VARIANT_DIR
    existing_meta = variant_meta(project) if dest.exists() else {}
    old_journal = str(existing_meta.get("journal", "")).strip()
    if force and old_journal and old_journal.casefold() != journal.strip().casefold():
        raise SystemExit(
            f"refusing to replace journal '{old_journal}' with '{journal}' in place. A journal "
            "switch must clear the entire old submission tree, not just manuscript/:\n"
            f"  loop to S20, then scientific_freeze.py reset-journal --confirm-journal "
            f"\"{old_journal}\"")
    if dest.exists() and any(dest.iterdir()) and not force:
        raise SystemExit(
            f"{VARIANT_DIR} already holds a variant. Switching journals means discarding the "
            f"previous adaptation:\n  --force to replace it. The frozen science is untouched "
            f"either way."
        )
    # `--force` means a NEW journal variant, not an in-place overwrite. Delete the directory
    # first so a title page, polish report, snapshot or journal-only statement from journal A
    # cannot survive merely because journal B has not generated its replacement yet.
    if dest.exists() and force:
        shutil.rmtree(dest)
    if force:
        clear_journal_downstream(project)
    dest.mkdir(parents=True, exist_ok=True)
    copied = []
    for name in ADAPTED_TEXT_FILES:
        src = project / SOURCE_DIR / name
        if src.is_file() and src.stat().st_size > 0:
            shutil.copy2(src, dest / name)
            copied.append(name)
    meta = {
        "schema": 1,
        "journal": journal,
        "opened_at": _now(),
        "from_freeze": freeze_path(project).name,
        "freeze_sha256": _sha256(freeze_path(project)),
        "files": copied,
        "note": "Journal-specific adaptation only: word caps, abstract shape, reference style, "
                "title page, required statements. Numbers, citations and artifact references "
                "must survive - see variant_delta().",
    }
    (dest / "variant.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return dest, copied


def variant_meta(project: Path) -> dict:
    p = project / VARIANT_DIR / "variant.json"
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _facts(text: str) -> dict:
    stripped = CITE_RE.sub(" ", text)
    stripped = ART_RE.sub(" ", stripped)
    return {
        "numbers": NUM_RE.findall(stripped),
        "citekeys": [k.strip() for group in CITE_RE.findall(text)
                     for k in group.split(";") if k.strip()],
        "artifacts": [f"{kind.lower()} {num.upper()}" for kind, num in ART_RE.findall(text)],
    }


def variant_delta(project: Path) -> tuple[bool, list[str], dict]:
    """What did journal adaptation change, and did any science fall out?

    Word count is expected to move - that is the whole point of a journal word cap. A number,
    a citation or a figure/table reference going missing is a different thing: it means content
    was dropped to fit, which is a scientific decision and needs the user, not a silent trim.
    """
    from collections import Counter
    if not variant_exists(project):
        return False, [f"{VARIANT_DIR}/full_manuscript.md missing; no variant has been opened"], {}
    problems, summary = [], {}
    for name in ADAPTED_TEXT_FILES:
        src, var = project / SOURCE_DIR / name, project / VARIANT_DIR / name
        if not var.is_file():
            continue
        if not src.is_file():
            # title_page.md is authored at S21 and has no frozen counterpart.
            summary[name] = {"words_before": 0,
                             "words_after": len(var.read_text(encoding="utf-8").split()),
                             "origin": "authored in the variant"}
            continue
        before = src.read_text(encoding="utf-8", errors="replace")
        after = var.read_text(encoding="utf-8", errors="replace")
        fb, fa = _facts(before), _facts(after)
        entry = {"words_before": len(before.split()), "words_after": len(after.split())}
        for field in ("numbers", "citekeys", "artifacts"):
            lost = Counter(fb[field]) - Counter(fa[field])
            if lost:
                items = ", ".join(sorted(lost.elements()))[:160]
                entry[f"{field}_lost"] = items
                problems.append(f"{name}: {field} dropped during journal adaptation: {items}")
        entry["words_delta"] = entry["words_after"] - entry["words_before"]
        summary[name] = entry
    return not problems, problems, summary
