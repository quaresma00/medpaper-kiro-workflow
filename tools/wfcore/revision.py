"""Scoped revision rounds (schema 2, 1.7.0): owners supply rules; the stage tail is not rewound.

A user's feedback at S19 (science) or S24 (journal package) used to rewind the state machine to
the earliest owning stage and replay every later stage. A scoped round instead:

  1. collects one or more feedback messages (`status = collecting`), building nothing;
  2. is sealed once, which plans the dependency closure (dependencies.closure), the stages
     whose gates must re-validate it and the exact files that may change;
  3. is checked in place (`check_round`): only the non-lifecycle gates of the affected
     stages run, and a whole-paper snapshot diff fails any file changed outside the scope;
  4. closes with the checked hashes recorded, so later drift is still caught.

Completed stages stay completed. Paper-local skipped stages never enter validation. A change
to 03_analysis always carries `analysis_reproduces`. Science changed after S19 is reviewed at
S19 again, re-frozen, and then merged into the journal copy by a resumed package round.
Ported from the Codex engine's revision.py and adapted to this engine's layout
(08_submission/manuscript/ journal copy, scifreeze, overrides, reproproof, gatecache).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .packagefreeze import _safe_path

SCHEMA = 2
REVIEW_STAGES = ("S19_human_review", "S24_package_human_review")
SCIENTIFIC_KINDS = {"study-design", "data", "analysis", "final-protocol"}
# Approval/lifecycle gates: they certify a review checkpoint or a stage transition, not the
# content of a revised file, so a scoped round never runs them in place.
LIFECYCLE_CHECKS = {
    "no_future_artifacts", "single_section_written", "temp_clean", "revision_rounds_closed",
    "manuscript_review_package_current", "s19_review_release_explicit", "review_round_approved",
    "scientific_freeze_captured", "bundle_matches_freeze", "submission_audit_matches_freeze",
    "paper_override_skip",
}
NO_INPLACE_STAGES = {"S19_human_review", "S24_package_human_review", "S25_submission_audit"}
# Review checkpoint records and freezes: written after a round closes, verified by their own
# gates at advance, and never part of a revision's scope.
LIFECYCLE_FILES = {
    "07_manuscript/human_review.md", "07_manuscript/scientific_freeze.json",
    "08_submission/package_human_review.md", "08_submission/package_review_freeze.json",
    "08_submission/independent_submission_audit.md",
}
# 08_submission/notes/ is the declared place for the agent's own plans and check records
# (1.8.0); like .wf/ and temp/ it is never a deliverable, so it is never an unplanned change.
SNAPSHOT_SKIP = (".wf/", "temp/", "07_manuscript/review_packages/",
                 "08_submission/journal_archives/", "08_submission/notes/")
SCIENCE_FILES = {"01_protocol/protocol_v1.md", "01_protocol/protocol_final.md"}
S06_OUTPUTS = ("01_protocol/protocol_final.md", "01_protocol/protocol_diff.md",
               "03_analysis/reproducibility_report.json")
S19_CONSISTENCY = ("manuscript_structure", "assembly_matches_sources",
                   "supplementary_methods_clean", "citekeys_resolve",
                   "numbers_have_provenance", "artifact_refs_consistent")
FULL_BUILDS_MAX = 2


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# 1.9.0: indexes the tools rewrite on every deterministic rebuild. Their content is derived from
# certified sources (the tables, figures and sidecars themselves stay certified), so a rewrite
# renews them instead of opening a bookkeeping round.
DERIVED_RENEWABLE = {"04_tables/manifest.json", "05_figures/qc/qc_report.json"}
DELETED = "DELETED"


def renewable(rel: str) -> bool:
    """Re-fetchable evidence/cache. Refreshing it is maintenance, never a content edit."""
    rel = rel.replace("\\", "/")
    return (rel == "06_refs/verified.json" or rel in DERIVED_RENEWABLE
            or rel.startswith(("06_refs/cache/", "08_submission/cache/")))


def receipt(project: Path, rel: str) -> dict:
    """A changed-file credential: raw SHA-256 plus the visible-content hash (1.9.0), so an
    identical rebuild with new container timestamps still matches."""
    from .determinism import content_sha256
    path = Path(project) / rel
    out = {"path": rel, "sha256": sha256(path)}
    content = content_sha256(path)
    if content.startswith("c:"):
        out["content_sha256"] = content
    return out


def receipt_holds(project: Path, rec: dict) -> bool:
    """Does the working tree still match a credential (deletion credentials included)?"""
    from .determinism import same
    path = Path(project) / str(rec.get("path", ""))
    if rec.get("deleted") or rec.get("sha256") == DELETED:
        return not path.exists()
    return same(path, rec.get("sha256"), rec.get("content_sha256"))


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def round_path(project: Path, round_id: str) -> Path:
    return project / ".wf" / "revisions" / f"{round_id}.json"


def active(project: Path) -> dict | None:
    state = project / ".wf/state.json"
    if not state.is_file():
        return None
    try:
        round_id = json.loads(state.read_text(encoding="utf-8")).get("active_revision_round")
        if not round_id:
            return None
        return json.loads(round_path(project, str(round_id)).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def is_scoped(revision: dict | None) -> bool:
    return bool(revision) and revision.get("schema_version") == SCHEMA


def drop_receipts(state) -> None:
    """A rework invalidates every short-lived gate receipt (gatecache), not just changed ones."""
    (state.dir / "check_receipts.json").unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# snapshot / scope
# ---------------------------------------------------------------------------
def snapshot(project: Path) -> dict[str, str]:
    """Hash deliverables and sources; large raw/cache/full-text trees are bound by file stat.

    Detects accidental scope drift, not same-privilege timestamp forgery; data and reference
    integrity gates still validate their own receipts.
    """
    out: dict[str, str] = {}
    for path in sorted(project.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.name == ".gitkeep":
            continue
        rel = path.relative_to(project).as_posix()
        if rel.startswith(SNAPSHOT_SKIP) or rel in LIFECYCLE_FILES:
            continue
        if rel.startswith("02_data/raw/") or "/cache/" in rel or "/fulltext/" in rel:
            st = path.stat()
            out[rel] = f"stat:{st.st_size}:{st.st_mtime_ns}"
        else:
            out[rel] = sha256(path)
    return out


def input_signature(project: Path, state, revision: dict, files: dict | None = None) -> str:
    from .gatecache import _engine_hashes
    files = snapshot(project) if files is None else files
    payload = {"files": {r: h for r, h in files.items() if not renewable(r)},
               "engine": _engine_hashes(), "decisions": state.data.get("decisions", {}),
               "config": state.config(), "scope": revision.get("allowed_files", []),
               "checks": revision.get("checks", []), "stages": revision.get("validation_stages", [])}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def permits(project: Path, stage: str) -> bool:
    revision = active(project)
    return bool(is_scoped(revision) and revision.get("status") == "active"
                and stage in revision.get("validation_stages", []))


SCOPE_EXEMPT = ("temp/", ".wf/", ".kiro/", "08_submission/notes/")


def out_of_scope(revision: dict | None, rels: list[str]) -> list[str]:
    """1.11.0 (#2e): paper files a write would touch outside the sealed round's scope."""
    if not (is_scoped(revision) and revision.get("status") == "active"):
        return []
    allowed = set(revision.get("allowed_files", [])) | set(revision.get("rebuild_files", []))
    return sorted(r for r in rels if r not in allowed and not r.startswith(SCOPE_EXEMPT))


def guard_outputs(project: Path, outputs: list[Path]) -> None:
    """Builders call this before writing: only the sealed closure may be rebuilt."""
    revision = active(project)
    if not revision:
        return
    if revision.get("status") == "collecting":
        raise ValueError("feedback collection is open; seal the batch (tools/rework.py seal) "
                         "before building")
    if not is_scoped(revision) or revision.get("status") != "active":
        return  # a legacy (schema-1) round finishes through its recorded stage gates
    allowed = set(revision.get("allowed_files", []))
    for path in outputs:
        try:
            rel = Path(path).resolve().relative_to(project.resolve()).as_posix()
        except ValueError as exc:
            raise ValueError(f"revision output leaves the paper: {path}") from exc
        if rel.startswith("temp/"):
            continue
        if rel not in allowed:
            raise ValueError(f"out-of-scope build during {revision.get('round_id')}: {rel}; "
                             "only the planned dependency closure may be rebuilt (rework.py status)")


def certified_receipts(project: Path) -> dict[str, tuple[str, dict]]:
    """rel -> (round id, credential) like certified_hashes, keeping content/deletion data."""
    directory = project / ".wf" / "revisions"
    rounds = []
    for path in sorted(directory.glob("R*.json")) if directory.is_dir() else []:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if data.get("status") == "complete":
            rounds.append(data)
    out: dict[str, tuple[str, dict]] = {}
    for data in rounds:
        for item in data.get("items", []):
            for rec in item.get("changed_files", []) or []:
                if isinstance(rec, dict) and rec.get("path") and not renewable(rec["path"]):
                    out[rec["path"]] = (data.get("round_id", "?"), rec)
    if rounds and rounds[-1].get("schema_version") == SCHEMA:
        val = rounds[-1].get("validation", {})
        content = val.get("artifact_content", {})
        for rel, digest in val.get("artifact_hashes", {}).items():
            if not renewable(rel):
                out[rel] = (rounds[-1].get("round_id", "?"),
                            {"path": rel, "sha256": digest, "content_sha256": content.get(rel)})
        for rel in val.get("artifact_deleted", []):
            out[rel] = (rounds[-1].get("round_id", "?"), {"path": rel, "sha256": DELETED,
                                                          "deleted": True})
    return out


def certified_hashes(project: Path) -> dict[str, tuple[str, str]]:
    """rel -> (round id, sha256) for every file the newest closed rounds certified."""
    directory = project / ".wf" / "revisions"
    out: dict[str, tuple[str, str]] = {}
    rounds = []
    for path in sorted(directory.glob("R*.json")) if directory.is_dir() else []:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if data.get("status") == "complete":
            rounds.append(data)
    for data in rounds:
        for item in data.get("items", []):
            for receipt in item.get("changed_files", []) or []:
                if isinstance(receipt, dict) and receipt.get("path") and not renewable(receipt["path"]):
                    out[receipt["path"]] = (data.get("round_id", "?"), str(receipt.get("sha256", "")))
    if rounds and rounds[-1].get("schema_version") == SCHEMA:
        for rel, digest in rounds[-1].get("validation", {}).get("artifact_hashes", {}).items():
            if not renewable(rel):
                out[rel] = (rounds[-1].get("round_id", "?"), digest)
    return out


def certified_drift(project: Path) -> list[str]:
    """Frozen or round-certified sources edited outside any open round's scope.

    Detected the moment a render is attempted (wf run-script) instead of at the next S19/S24
    gate, so a figure-layout tweak at S23 is routed into a layout round straight away.
    """
    from . import scifreeze
    drift = []
    for rel, (_, rec) in certified_receipts(project).items():
        if not receipt_holds(project, rec):
            drift.append(rel)
    try:
        current = json.loads((project / ".wf/state.json").read_text(encoding="utf-8")).get("current")
    except (OSError, ValueError):
        current = None
    # At S19 the freeze is legitimately re-captured after a science round; S19 gates own it.
    if scifreeze.is_frozen(project) and current != "S19_human_review":
        try:
            entries = scifreeze.load_freeze(project).get("files", {})
        except SystemExit:
            entries = {}
        from . import presentation
        for rel, meta in entries.items():
            p = project / rel
            if not p.is_file() or scifreeze._sha256(p) != meta.get("sha256"):
                # 1.11.0 (#3a): a presentation-layer edit with unchanged facts is not drift.
                if p.is_file() and meta.get("layer") == "presentation" \
                        and meta.get("facts") is not None \
                        and presentation.same_facts(presentation.facts(project, rel), meta["facts"]):
                    continue
                drift.append(rel)
    revision = active(project)
    allowed = set(revision.get("allowed_files", [])) if is_scoped(revision) else set()
    if revision and not is_scoped(revision):
        return []  # a legacy rewind round re-runs every stage gate anyway
    return sorted({r for r in drift if r not in allowed})


def scope_problems(project: Path, revision: dict, files: dict | None = None) -> list[str]:
    before = revision.get("baseline", {})
    now = snapshot(project) if files is None else files
    allowed = set(revision.get("allowed_files", []))
    stages = set(revision.get("validation_stages", []))
    changed = {r for r in set(before) | set(now) if before.get(r) != now.get(r)}

    def maintenance(rel: str) -> bool:
        if renewable(rel):
            return True
        # S11 QC scratch (contact sheet, crops, qc report); figure renders are never exempt.
        return (bool(stages & {"S11_figures", "S23_package", "S09_results"})
                and rel.startswith("05_figures/qc/")
                and not rel.endswith(".artist.json"))
    return [f"unplanned change: {rel}" for rel in sorted(changed - allowed) if not maintenance(rel)]


# ---------------------------------------------------------------------------
# planning
# ---------------------------------------------------------------------------
def _resolved_outputs(project: Path, stage) -> set[str]:
    from . import scifreeze
    return {scifreeze.resolve(project, o) for o in stage.outputs}


def _applicable(pipeline, state, sid: str, review: str) -> bool:
    stage = pipeline.stage(sid)
    if getattr(stage, "skipped", False) or state.status_of(sid) == "skipped":
        return False  # a paper-local skip never re-enters validation
    return stage.index < pipeline.stage(review).index


def plan_scope(project: Path, pipeline, state, revision: dict) -> None:
    """Compute rebuild closure, validation stages, checks and the allowed write set."""
    from .dependencies import closure
    items = revision["items"]
    review = revision["review_stage"]
    if any(i["kind"] in ("journal", "journal-switch") for i in items):
        raise ValueError("a journal switch replaces the whole submission tree and cannot be "
                         "scoped in place; use the full fallback: rework.py batch --rewind "
                         "(then reset-journal at S20)")
    sources = sorted({s.replace("\\", "/") for i in items for s in i["affected_sources"]})
    for rel in sources:
        _safe_path(project, rel)
    rebuild: set[str] = set()
    for item in items:
        ct = "scientific" if item["change_type"] == "auto" else item["change_type"]  # widest closure
        rebuild.update(closure(project, item["affected_sources"], change_type=ct,
                               baseline_documents=revision.get("baseline_documents")))
    if review == "S19_human_review":
        # Never rewrite a journal layer while scientific approval is pending.
        rebuild = {r for r in rebuild if not r.startswith("08_submission/")}
    stages = {i["owning_stage"] for i in items}
    science = any(r.startswith(("02_data/", "03_analysis/")) or r in SCIENCE_FILES
                  for r in set(sources) | rebuild)
    if science:
        stages.update({"S05_analysis", "S06_protocol_final"})
        rebuild.update(S06_OUTPUTS)
    prefix_stage = (("04_tables/", "S10_tables"), ("05_figures/", "S11_figures"),
                    ("06_refs/", "S13_reflib"), ("07_manuscript/", "S17_assemble"),
                    ("08_submission/bundle/", "S23_package"))
    for prefix, sid in prefix_stage:
        if any(r.startswith(prefix) for r in rebuild):
            stages.add(sid)
    variant = "08_submission/manuscript/"
    if rebuild & {variant + "full_manuscript.md", variant + "supplementary_methods.md"}:
        stages.add("S22_polish")
    if rebuild & {variant + "title_page.md", variant + "statements.md", "00_input/author_info.json"}:
        stages.add("S21_authors")
    for stage in pipeline.stages:
        if stage.id in NO_INPLACE_STAGES or stage.id == "S18_independent_review":
            continue
        if _resolved_outputs(project, stage) & rebuild:
            stages.add(stage.id)
    substantive = any(i["change_type"] == "scientific" for i in items)
    if substantive and review == "S19_human_review":
        stages.add("S18_independent_review")
        if any(r.startswith(("04_tables/", "05_figures/", "03_analysis/results/")) for r in rebuild):
            stages.add("S12_reconcile")
    stages.update(revision.get("extra_validation_stages", []))
    stages = {s for s in stages if s not in NO_INPLACE_STAGES and _applicable(pipeline, state, s, review)}
    if review == "S23_package":
        # _applicable already drops S23 itself (index not below the review stage).
        stages.discard("S23_package")

    checks = []
    for sid in sorted(stages, key=lambda s: pipeline.stage(s).index):
        for spec in pipeline.stage(sid).gate:
            if spec.get("check") not in LIFECYCLE_CHECKS:
                checks.append({"stage": sid, "spec": spec})
    review_stage = pipeline.stage(review)
    # An S23 layout round runs mid-build: the package gates are S23's own exit, not the round's.
    for spec in ([] if review == "S23_package" else review_stage.gate):
        name = spec.get("check")
        if review == "S19_human_review" and name in S19_CONSISTENCY:
            checks.append({"stage": review, "spec": spec})
        elif review != "S19_human_review" and name not in LIFECYCLE_CHECKS | {
                "outputs_exist", "md_sections", "decision_recorded"}:
            checks.append({"stage": review, "spec": spec})
    touches_analysis = any(r.startswith("03_analysis/") for r in set(sources) | rebuild)
    if touches_analysis and not any(c["spec"].get("check") == "analysis_reproduces" for c in checks):
        checks.append({"stage": "S06_protocol_final", "spec": {"check": "analysis_reproduces"}})
    unique = {json.dumps(row, sort_keys=True): row for row in checks}

    controls: set[str] = set()
    for sid in stages:
        for output in _resolved_outputs(project, pipeline.stage(sid)):
            if (output.endswith(("manifest.json", "qc_report.json", "_review.md", "_qc.md",
                                 "moved_to_legend.md", "polish_report.json", "polish_log.md"))
                    or output in {"08_submission/package_content_baseline.json",
                                  "08_submission/reporting_checklist.md",
                                  "08_submission/bundle/SUBMISSION_CHECKLIST.md",
                                  "08_submission/submission_qc.md",
                                  "07_manuscript/reconciliation.md"}):
                controls.add(output)
    if "S05_analysis" in stages:
        controls.update({"03_analysis/analysis_log.md", "03_analysis/notes.md",
                         "03_analysis/method_scan.md"})
    if "S22_polish" in stages:
        controls.update(variant + "prepolish/" + n for n in
                        ("full_manuscript.md", "supplementary_methods.md", "title_page.md",
                         "statements.md", "facts.json"))
        controls.add(variant + "polish_allowlist.tsv")
    if revision.get("resume_from_science"):
        controls.add(variant + "variant.json")
    if "S23_package" in stages:  # deferred visual review is discharged at S23 via qc.py
        controls.add("05_figures/qc/qc_report.json")
    if "S18_independent_review" in stages:
        controls.update(pipeline.stage("S18_independent_review").outputs)
    allowed = (rebuild | controls) - LIFECYCLE_FILES
    revision.update({
        "rebuild_files": sorted(rebuild), "validation_stages": sorted(
            stages, key=lambda s: pipeline.stage(s).index),
        "checks": list(unique.values()), "allowed_files": sorted(allowed),
        "requires_independent_science_review": substantive and review == "S19_human_review",
        "reuse_count": len(set(revision.get("baseline", {})) - allowed),
    })


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------
def _run(pipeline, state, project: Path, row: dict):
    from . import checks
    from .checks import Ctx, Result
    from .gates import _resolve_manuscript_paths
    from .gates import pinned_out
    spec = _resolve_manuscript_paths(row["spec"], project)
    if pinned_out(state, row["stage"], spec):
        return Result(True, str(spec.get("check")), f"not in the paper's pinned engine "
                      f"{state.engine_pin} for completed {row['stage']}")
    fn = checks.get(spec.get("check"))
    if fn is None:
        return Result(False, str(spec.get("check")), "unknown check")
    try:
        result = fn(Ctx(pipeline, state, project, pipeline.stage(row["stage"]), spec))
    except Exception as exc:  # noqa: BLE001
        result = Result(False, spec.get("check", "?"), f"{type(exc).__name__}: {exc}")
    if "severity" in spec and not result.ok:
        result.severity = spec["severity"]
    return result


def validate(project: Path, pipeline, state, revision: dict):
    from . import checks
    from .checks import Result
    checks.load_all()
    files = snapshot(project)
    problems = scope_problems(project, revision, files)
    results = [Result(not problems, "revision_scope_unchanged",
                      "; ".join(problems[:10]) or "files outside the revision scope are unchanged")]
    seen = set()
    for row in revision.get("checks", []):
        spec = row["spec"]
        contextual = spec.get("check") in {"outputs_exist", "decision_recorded",
                                           "reference_provenance"}
        identity = json.dumps([row["stage"] if contextual else None, spec], sort_keys=True)
        if identity in seen:
            continue
        seen.add(identity)
        results.append(_run(pipeline, state, project, row))
    # Checks may renew evidence but must never alter the sources they certify.
    after = snapshot(project)
    drift = {r for r in set(files) | set(after) if not renewable(r) and files.get(r) != after.get(r)}
    if drift:
        results.append(Result(False, "validation_source_drift", ", ".join(sorted(drift)[:10])))
    return results, input_signature(project, state, revision, after), after


def check_round(project: Path, pipeline, state, path: Path, revision: dict, *,
                quiet: bool = False, summary: bool = False) -> int:
    from .determinism import content_sha256
    if revision.get("status") != "active":
        raise ValueError("seal the feedback batch before checking (tools/rework.py seal)")
    if not is_scoped(revision):
        raise ValueError("a legacy (schema-1) round is validated by the normal stage gates")
    results, signature, files = validate(project, pipeline, state, revision)
    allowed = set(revision.get("allowed_files", []))
    hashes = {r: (h if not h.startswith("stat:") else sha256(project / r))
              for r, h in files.items() if r in allowed and not renewable(r)}
    content = {}
    for rel in hashes:
        c = content_sha256(project / rel)
        if c.startswith("c:"):
            content[rel] = c
    revision["validation"] = {
        "input_signature": signature, "ok": not any(r.blocking for r in results),
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "artifact_hashes": hashes,
        "artifact_content": content,
        "artifact_deleted": sorted(r for r in revision.get("baseline", {})
                                   if r in allowed and r not in files and not renewable(r)),
        "renewable_evidence": {r: h for r, h in files.items() if renewable(r)},
        "results": [{"check": r.check, "ok": r.ok, "detail": r.detail[:300],
                     "severity": r.severity} for r in results],
    }
    atomic_json(path, revision)
    if not summary:
        for result in results:
            if not result.ok:
                print(f"[{result.label}] {result.check}: {result.detail}")
                for hint in ([] if quiet else result.hints[:2]):
                    print(f"    -> {hint}")
    failed = [r.check for r in results if r.blocking]
    if not (quiet and not summary and not failed):
        print(f"Scoped checks: {sum(r.ok for r in results)}/{len(results)} "
              f"({len(revision.get('validation_stages', []))} stage(s)); checkpoint stays "
              f"{state.current}" + (f"; failing: {', '.join(failed)}" if summary and failed else ""))
    return 0 if revision["validation"]["ok"] else 2


def refresh_evidence(project: Path, pipeline, state, revision: dict) -> None:
    """On close: renewed evidence reruns its real (non-pure) gates; pure gates are reused.

    Refreshing a cache or PubMed receipt is not a content change, so it never counts as scope
    drift or invalidates the input signature - but the refreshed evidence must still pass.
    """
    from . import checks
    from .gatecache import INPUTS, depends_on
    current = {r: h for r, h in snapshot(project).items() if renewable(r)}
    recorded = revision.get("validation", {}).get("renewable_evidence") or {}
    if current == recorded:
        return
    drifted = sorted(r for r in set(current) | set(recorded) if current.get(r) != recorded.get(r))
    checks.load_all()
    failures = []
    for row in revision.get("checks", []):
        # 1.14.0 (F): a pure check is reused only when none of the files it reads drifted.
        if row["spec"].get("check") in INPUTS and not depends_on(project, row["spec"], drifted):
            continue
        result = _run(pipeline, state, project, row)
        if result.blocking:
            failures.append(f"{result.check}: {result.detail}")
    if failures:
        raise ValueError("renewed evidence is invalid: " + "; ".join(failures[:8]))


# ---------------------------------------------------------------------------
# post-S19 science: re-review at S19, then resume the package round at S24
# ---------------------------------------------------------------------------
def resume_package(project: Path, pipeline, state) -> str:
    """After renewed S19 approval and re-freeze, reopen only the package closure at S24."""
    from .dependencies import closure
    prior_id = state.data["resume_package_revision"]
    directory = state.dir / "revisions"
    prior = json.loads((directory / f"{prior_id}.json").read_text(encoding="utf-8"))
    if prior.get("status") != "complete":
        raise ValueError("the scientific round must close before package adaptation resumes")
    numbers = [int(p.stem[1:]) for p in directory.glob("R*.json") if p.stem[1:].isdigit()]
    round_id = f"R{max(numbers, default=0) + 1:03d}"
    now = snapshot(project)
    changed = [r for r in sorted(set(prior.get("rebuild_files", [])) |
                                 {s for i in prior["items"] for s in i["affected_sources"]})
               if prior.get("baseline", {}).get(r) != now.get(r)]
    dependants = sorted({r for r in closure(project, changed) if r.startswith("08_submission/")}
                        | {"08_submission/manuscript/variant.json"})
    items = list(prior.get("deferred_package_items", []))
    items.append({
        "kind": "manuscript-copyedit", "change_type": "administrative",
        "owning_stage": "S22_polish", "affected_sources": dependants,
        "request": "Merge the newly approved scientific changes into the journal copy and every "
                   "affected upload; keep unrelated journal edits; rebind the variant "
                   "(scientific_freeze.py rebind-variant).",
        "acceptance_criteria": ["The journal copy carries every re-approved scientific change",
                                "variant_preserves_science and journal_variant_ready pass",
                                "Unrelated journal edits are preserved"],
        "status": "pending", "resolution": None, "changed_files": [], "validated_by": [],
    })
    for index, item in enumerate(items, 1):
        item["id"] = f"{round_id}-{index:02d}"
    revision = {
        "schema_version": SCHEMA, "round_id": round_id, "status": "active",
        "review_stage": "S24_package_human_review", "origin_stage": "S24_package_human_review",
        "earliest_stage": "S21_authors", "resume_from_science": prior_id,
        "created_at": _now(), "sealed_at": _now(), "full_builds": 0,
        "feedback_updates": prior.get("feedback_updates", []), "items": items,
        "baseline": now, "extra_validation_stages": ["S21_authors", "S22_polish", "S23_package"],
    }
    plan_scope(project, pipeline, state, revision)
    atomic_json(directory / f"{round_id}.json", revision)
    state.data.pop("resume_package_revision", None)
    state.data["active_revision_round"] = round_id
    drop_receipts(state)
    state.complete("S19_human_review", "S24_package_human_review")
    state.event("revision_package_resumed", f"{prior_id} -> {round_id}; S20-S23 history preserved")
    state.save()
    return round_id
