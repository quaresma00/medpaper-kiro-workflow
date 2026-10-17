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
                              Switching journals moves it (and the old package) to
                              08_submission/journal_archives/<journal>-<UTC>/ and takes a
                              fresh copy; the frozen science is untouched.

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
    # The executed results every number in the text traces to. A glob: at least one file must
    # match, and every match is hashed. (Rendered figures/tables stay unfrozen; see above.)
    "03_analysis/results/*.json",
)
FREEZE_SCHEMA = 2
ARCHIVE_DIR = "08_submission/journal_archives"
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
    # Checklist locations point at headings of one journal variant.
    "08_submission/reporting_checklist.md",
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
def _is_glob(rel: str) -> bool:
    return any(ch in rel for ch in "*?[")


def uncovered_required(entries: dict) -> list[str]:
    """Required scientific paths (or globs) that a freeze record does not cover."""
    import fnmatch
    out = []
    for rel in REQUIRED_SCIENTIFIC:
        if _is_glob(rel):
            if not any(fnmatch.fnmatchcase(k, rel) for k in entries):
                out.append(rel)
        elif rel not in entries:
            out.append(rel)
    return out


def scientific_files(project: Path) -> tuple[dict[str, Path], list[str]]:
    files, missing = {}, []
    for rel in REQUIRED_SCIENTIFIC:
        if _is_glob(rel):
            found = [p for p in sorted(project.glob(rel)) if p.is_file() and p.stat().st_size > 0]
            if not found:
                missing.append(rel)
            for p in found:
                files[p.relative_to(project).as_posix()] = p
            continue
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
    payload = {
        "schema": FREEZE_SCHEMA,
        "frozen_at": _now(),
        "note": "Scientific record settled at S19. Journal adaptation happens in "
                f"{VARIANT_DIR}/, never here.",
        "files": {rel: {"sha256": _sha256(p), "bytes": p.stat().st_size}
                  for rel, p in sorted(files.items())},
    }
    # Bind the freeze to the S19 review ZIP the user released, so the gate can prove the frozen
    # text is the reviewed text (scientific_freeze_intact checks the decision rationale).
    # 1.8.1: bind to the latest subagent review round the user ended; legacy papers without
    # rounds keep binding to their review-package id.
    from . import reviewrounds
    approved = reviewrounds.approved_round(project, "manuscript")
    latest = project / "07_manuscript/review_packages/latest_review_package.json"
    if approved:
        payload["review_round_id"] = approved["id"]
    elif latest.is_file():
        try:
            package_id = str(json.loads(latest.read_text(encoding="utf-8")).get("package_id", ""))
        except (OSError, json.JSONDecodeError):
            package_id = ""
        if package_id:
            payload["review_package_id"] = package_id
    return payload


def _s19_approval_at(project: Path) -> str | None:
    """Timestamp of the S19 NO_FURTHER_REVIEW decision, or None when there is none."""
    try:
        state = json.loads((project / ".wf/state.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    decision = state.get("decisions", {}).get("manuscript_human_reviewed") or {}
    return str(decision.get("at", "")) if decision.get("value") == "NO_FURTHER_REVIEW" else None


def write_freeze(project: Path, *, force: bool = False) -> Path:
    path = freeze_path(project)
    if path.exists() and not force:
        # Identical science needs no --force: re-capturing after a re-recorded S19 approval only
        # re-stamps the time, so the freeze no longer predates the approval (1.8.0).
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            old = {}
        new = build_freeze(project)
        if (old.get("files") == new.get("files")
                and old.get("review_package_id") == new.get("review_package_id")
                and old.get("review_round_id") == new.get("review_round_id")):
            approved = _s19_approval_at(project)
            if approved and str(old.get("frozen_at", "")) < approved:
                old.setdefault("restamps", []).append(
                    {"from": old.get("frozen_at"), "to": new["frozen_at"],
                     "reason": "identical content re-captured after the S19 approval"})
                old["frozen_at"] = new["frozen_at"]
                tmp = path.with_suffix(".json.tmp")
                tmp.write_text(json.dumps(old, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                tmp.replace(path)
            return path
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


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(text).casefold()).strip("-")
    return slug[:60] or "journal"


def _journal_name(project: Path) -> str:
    name = str(variant_meta(project).get("journal", "")).strip()
    if name:
        return name
    try:
        meta = json.loads((project / "08_submission/target_journal.json").read_text(encoding="utf-8"))
        return str(meta.get("journal", "")).strip()
    except (OSError, json.JSONDecodeError, AttributeError):
        return ""


def new_archive_dir(project: Path) -> Path:
    """A fresh 08_submission/journal_archives/<journal-slug>-<UTC stamp>/ (not yet created)."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = project / ARCHIVE_DIR / f"{_slug(_journal_name(project))}-{stamp}"
    out, n = base, 1
    while out.exists():
        n += 1
        out = base.with_name(f"{base.name}-{n}")
    return out


def _archive(project: Path, rel: str, archive: Path) -> bool:
    """Move one submission-tree path into `archive`, keeping its path below 08_submission/."""
    src = project / rel
    if not src.exists():
        return False
    dest = archive / Path(rel).relative_to("08_submission")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    return True


def clear_journal_downstream(project: Path, archive: Path | None = None) -> list[str]:
    """Move every S21+ artifact that cannot belong to a replacement journal variant aside.

    Nothing is deleted: a journal switch after a rejection must not lose the previous
    journal's adapted text and package. They go to 08_submission/journal_archives/, which no
    gate reads.
    """
    archive = archive or new_archive_dir(project)
    removed = []
    for rel in JOURNAL_DOWNSTREAM:
        if _archive(project, rel, archive):
            removed.append(rel)
    return removed


def reset_journal(project: Path) -> list[str]:
    """Start S20 from a blank submission area while leaving the scientific freeze intact.

    The old submission tree is archived under 08_submission/journal_archives/, not deleted.
    Returns the original paths of the files that were moved aside.
    """
    ok, problems, _ = verify_freeze(project)
    if not ok:
        raise SystemExit("refusing journal reset: frozen science has drifted:\n  "
                         + "\n  ".join(problems))
    root = project / "08_submission"
    archives = project / ARCHIVE_DIR
    removed: list[str] = []
    if root.exists():
        children = [p for p in root.iterdir() if p.resolve() != archives.resolve()]
        if children:
            archive = new_archive_dir(project)
            for child in children:
                files = [child] if child.is_file() else [p for p in child.rglob("*") if p.is_file()]
                removed.extend(p.relative_to(project).as_posix() for p in files)
                _archive(project, child.relative_to(project).as_posix(), archive)
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
    # `--force` means a NEW journal variant, not an in-place overwrite. Move the directory
    # aside first so a title page, polish report, snapshot or journal-only statement from the
    # previous variant cannot survive merely because the new one has not generated its
    # replacement yet. It is archived, never deleted.
    if force:
        archive = new_archive_dir(project)
        if dest.exists():
            _archive(project, VARIANT_DIR, archive)
        clear_journal_downstream(project, archive)
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


def rebind_variant(project: Path) -> dict:
    """Bind the existing journal copy to a new freeze after a re-approved scientific change.

    Used only by a resumed package round (tools/rework.py): the science was re-reviewed at S19
    and re-frozen, the agent merged the changed passages into 08_submission/manuscript/ while
    keeping unrelated journal edits, and variant_preserves_science must hold before rebinding.
    Opening a fresh variant instead would throw the journal edits away.
    """
    ok, problems, _ = verify_freeze(project)
    if not ok:
        raise SystemExit("refusing to rebind: the freeze does not match the scientific files:\n  "
                         + "\n  ".join(problems))
    if not variant_exists(project):
        raise SystemExit(f"no journal variant in {VARIANT_DIR}/ to rebind")
    ok, problems, _ = variant_delta(project)
    if not ok:
        raise SystemExit("refusing to rebind: the journal copy is missing re-approved science:\n  "
                         + "\n  ".join(problems[:8]))
    meta = variant_meta(project)
    live = _sha256(freeze_path(project))
    if meta.get("freeze_sha256") == live:
        return meta
    meta.setdefault("rebinds", []).append({"at": _now(), "from": meta.get("freeze_sha256"),
                                           "to": live})
    meta["freeze_sha256"] = live
    (project / VARIANT_DIR / "variant.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return meta


def variant_meta(project: Path) -> dict:
    p = project / VARIANT_DIR / "variant.json"
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


KEY_RE = re.compile(r"@([A-Za-z0-9_][\w:.#$%&+?<>~/-]*?)(?=[\s;,\]]|$)")
SUPP_LEGEND_RE = re.compile(r"(?ms)^#{2,6}\s+(?:Figure|Fig\.?)\s+S\d+\b.*?(?=^#{1,6}\s|\Z)")


def _facts(text: str, aliases: dict | None = None) -> dict:
    """Numbers, citekeys and artifact references. Citekeys are compared as a multiset whatever
    the grouping, so '[@a] [@b]' and the collapsible '[@a; @b]' are the same citations; a
    journal alias ('Online Resource 2') counts as the canonical ids it stands for; and
    supplementary legend blocks are ignored because 1.8.0 moves them to the supplementary file."""
    from . import journalspec
    text = SUPP_LEGEND_RE.sub(" ", text)
    if aliases:
        text = journalspec.expand_aliases(text, aliases)
    stripped = CITE_RE.sub(" ", text)
    stripped = ART_RE.sub(" ", stripped)
    return {
        "numbers": NUM_RE.findall(stripped),
        "citekeys": [k for group in CITE_RE.findall(text) for k in KEY_RE.findall("@" + group)],
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
    from . import journalspec
    aliases = journalspec.project_aliases(project)
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
        fb, fa = _facts(before), _facts(after, aliases)
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
