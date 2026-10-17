"""Per-paper workflow customisation, without editing the master pipeline.

A paper sometimes genuinely needs a different workflow. A case report has no cohort to acquire
and no analysis to run. A registry study needs an extra data-permission artifact. A target
journal demands a structured abstract nobody else wants. Before this module the only way to get
any of that was to edit pipeline.toml - which changes the workflow for every future paper, and
leaves the next one running a shape that was designed for a different study.

The overlay lives with the paper:

    <paper>/.wf/overrides.toml

and is applied on top of the master at load time. The master file is never touched, so two
papers can run different shapes side by side from one engine.

The asymmetry that keeps this honest
------------------------------------
Strengthening is free. Adding a gate or declaring an extra output cannot make a paper weaker,
so neither needs permission.

Weakening is fenced. Skipping a stage, relaxing a gate, or widening the freeform globs is exactly
how a workflow quietly degrades into "whatever passed", which is the failure this pipeline
exists to prevent. So:

  * PROTECTED_CHECKS can never be relaxed. These are the integrity gates - data completeness,
    reference provenance, number provenance, identity of a fetched paper, the scientific freeze,
    the visual-review debt. A paper that wants one of these off does not want this pipeline.
  * PROTECTED_STAGES can never be skipped. Independent review, the user's own review, the final
    audit. Skipping a review is not a workflow variation, it is removing the reviewer.
  * Everything else may be relaxed or skipped, but only with a substantive written reason, and
    `wf status` reprints every active override on every call so it cannot fade into the
    background.
  * An override may be added or changed for the active stage or a future one. Once a stage has
    completed, the exact override entry that governed it is fingerprinted in state; changing it
    retrospectively is refused. Loop back to the owning stage first.
  * Simple numeric/string targets are not duplicated here. Use `wf config set KEY VALUE`, which
    already writes the paper's own `.wf/config.toml`.
"""
from __future__ import annotations

import hashlib
import json
import tomllib
from pathlib import Path

OVERRIDES_REL = "overrides.toml"
SCHEMA = 1
MIN_REASON = 40
_ALLOWED_TOP = {"schema", "stage_override", "freeform"}
_ALLOWED_STAGE = {"stage", "reason", "skip", "relax_gate", "add_gate", "extra_outputs"}
_ALLOWED_FREEFORM = {"reason", "globs"}

# Relaxing any of these is refused. Keep in step with cli.NON_OVERRIDABLE_GATES - the selftest
# asserts every non-overridable gate is also unrelaxable, because a gate you cannot --force past
# but can switch off in a config file is not actually protected.
PROTECTED_CHECKS = frozenset({
    "dependent_checks_pending",
    "data_acquisition_complete",
    "reference_provenance",
    "refs_library",
    "bib_ris_match_library",
    "citekeys_resolve",
    "revision_rounds_closed",
    "s19_review_release_explicit",
    "review_round_approved",
    "visual_debts_cleared",
    "deepread_complete",
    "scientific_freeze_intact",
    "scientific_freeze_captured",
    "journal_variant_ready",
    "numbers_have_provenance",
    "polish_preserves_facts",
    "package_content_matches_baseline",
    "bundle_matches_freeze",
    "submission_audit_matches_freeze",
    "variant_preserves_science",
    "paper_scripts_scoped",
    "decision_recorded",
    "results_have_environment",
    "analysis_reproduces",
    "reporting_checklist_complete",
})

# Skipping any of these is refused: they are where a human or an independent reader looks.
PROTECTED_STAGES = frozenset({
    "S18_independent_review",
    "S19_human_review",
    "S24_package_human_review",
    "S25_submission_audit",
})


def overrides_path(state_dir: Path) -> Path:
    return state_dir / OVERRIDES_REL


def load(state_dir: Path) -> dict:
    p = overrides_path(state_dir)
    if not p.is_file():
        return {}
    try:
        return tomllib.loads(p.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise SystemExit(f"malformed {p}: {exc}")


def _entry_fingerprint(entry: dict) -> str:
    payload = json.dumps(entry, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def fingerprint_for_stage(data: dict, stage_id: str) -> str:
    entry = next((item for item in data.get("stage_override", []) or []
                  if isinstance(item, dict)
                  and str(item.get("stage", "")).strip() == stage_id), None)
    free = data.get("freeform", {}) or {}
    # A blank template has no effective overlay and should leave no history fingerprint.
    effective_free = free if isinstance(free, dict) and free.get("globs") else None
    if entry is None and effective_free is None:
        return ""
    return _entry_fingerprint({"stage_override": entry, "freeform": effective_free})


def _local_path_problem(raw: object) -> str | None:
    rel = str(raw).replace("\\", "/")
    if not rel or rel.startswith("/") or ":" in rel.split("/")[0] or ".." in rel.split("/"):
        return f"'{raw}' must be a non-empty path inside the paper"
    return None


def validate(data: dict, stages) -> list[str]:
    """Every reason a paper-local override must be refused."""
    problems: list[str] = []
    unknown_top = sorted(set(data) - _ALLOWED_TOP)
    if unknown_top:
        problems.append("unknown top-level key(s): " + ", ".join(unknown_top)
                        + ". Targets belong in .wf/config.toml (`wf config set`).")
    if data.get("schema", SCHEMA) != SCHEMA:
        problems.append(f"schema must be {SCHEMA}")

    by_id = {s.id: s for s in stages}
    known = set(by_id)
    seen: set[str] = set()

    entries = data.get("stage_override", []) or []
    if not isinstance(entries, list):
        return [*problems, "stage_override must be an array of tables ([[stage_override]])"]

    for i, entry in enumerate(entries, 1):
        where = f"stage_override #{i}"
        if not isinstance(entry, dict):
            problems.append(f"{where}: must be a TOML table")
            continue
        unknown = sorted(set(entry) - _ALLOWED_STAGE)
        if unknown:
            problems.append(f"{where}: unknown key(s): {', '.join(unknown)}")

        sid = str(entry.get("stage", "")).strip()
        if not sid:
            problems.append(f"{where}: no `stage`")
            continue
        if sid not in known:
            problems.append(f"{where}: unknown stage '{sid}'")
            continue
        stage = by_id[sid]
        if sid in seen:
            problems.append(f"{where}: '{sid}' overridden twice; merge them into one entry")
        seen.add(sid)

        skip = entry.get("skip", False)
        if not isinstance(skip, bool):
            problems.append(f"{sid}: skip must be true or false")
            skip = False
        relax = entry.get("relax_gate", []) or []
        added = entry.get("add_gate", []) or []
        extra = entry.get("extra_outputs", []) or []
        for value, key in ((relax, "relax_gate"), (added, "add_gate"),
                           (extra, "extra_outputs")):
            if not isinstance(value, list):
                problems.append(f"{sid}: {key} must be a TOML array")
        if not isinstance(relax, list):
            relax = []
        if not isinstance(added, list):
            added = []
        if not isinstance(extra, list):
            extra = []

        if not skip and not relax and not added and not extra:
            problems.append(f"{sid}: override changes nothing")
        if skip and (relax or added or extra):
            problems.append(
                f"{sid}: skip cannot be combined with relax_gate, add_gate or extra_outputs; "
                "a skipped stage neither produces outputs nor runs gates")

        reason = str(entry.get("reason", "")).strip()
        weakening = bool(skip or relax)
        if weakening and len(reason) < MIN_REASON:
            problems.append(
                f"{sid}: weakening the workflow needs a reason of at least {MIN_REASON} "
                f"characters describing why this paper differs (got {len(reason)})")

        stage_checks = {str(g.get("check", "")) for g in stage.gate}
        protected_on_stage = sorted(stage_checks & PROTECTED_CHECKS)
        if skip and sid in PROTECTED_STAGES:
            problems.append(
                f"{sid}: cannot be skipped. This is a review or audit stage; skipping it removes "
                "the reader, which is not a workflow variation.")
        if skip and protected_on_stage:
            problems.append(
                f"{sid}: cannot be skipped because it owns protected gate(s): "
                f"{', '.join(protected_on_stage)}")

        if relax and sid in PROTECTED_STAGES:
            problems.append(
                f"{sid}: gates cannot be relaxed on a protected review/audit stage. Adding a "
                "gate or output is allowed; removing any part of the review contract is not.")

        for raw_check in relax:
            check = str(raw_check).strip()
            if check not in stage_checks:
                problems.append(
                    f"{sid}: cannot relax '{check}' because that gate is not on this stage "
                    f"(present: {', '.join(sorted(stage_checks))})")
            elif check in PROTECTED_CHECKS:
                problems.append(
                    f"{sid}: gate '{check}' cannot be relaxed. It is an integrity gate - it "
                    "proves the work was actually done, not that the workflow was followed.")

        for spec in added:
            if not isinstance(spec, dict) or not str(spec.get("check", "")).strip():
                problems.append(f"{sid}: every add_gate entry needs a `check`")
                continue
            for key in ("path", "manifest"):
                if key in spec and (msg := _local_path_problem(spec[key])):
                    problems.append(f"{sid}: add_gate {key} {msg}")
            if "paths" in spec:
                if not isinstance(spec["paths"], list):
                    problems.append(f"{sid}: add_gate paths must be an array")
                else:
                    for rel in spec["paths"]:
                        if msg := _local_path_problem(rel):
                            problems.append(f"{sid}: add_gate path {msg}")

        existing_outputs = set(stage.outputs)
        for rel in extra:
            if msg := _local_path_problem(rel):
                problems.append(f"{sid}: extra output {msg}")
            elif str(rel).replace("\\", "/") in existing_outputs:
                problems.append(f"{sid}: extra output '{rel}' is already declared by the master")

    free = data.get("freeform", {}) or {}
    if not isinstance(free, dict):
        problems.append("freeform must be a table ([freeform])")
        return problems
    unknown_free = sorted(set(free) - _ALLOWED_FREEFORM)
    if unknown_free:
        problems.append("freeform: unknown key(s): " + ", ".join(unknown_free))
    globs = free.get("globs", []) or []
    if not isinstance(globs, list):
        problems.append("freeform.globs must be an array")
        globs = []
    if globs and len(str(free.get("reason", "")).strip()) < MIN_REASON:
        problems.append(
            f"freeform.globs widens where undeclared files may hide; give a reason of at least "
            f"{MIN_REASON} characters")
    for rel in globs:
        if msg := _local_path_problem(rel):
            problems.append(f"freeform glob {msg}")
    return problems


def validate_against_state(data: dict, state) -> list[str]:
    """Refuse a retrospective edit to any overlay that governed a finished stage."""
    problems: list[str] = []
    for sid, info in (state.data.get("stages") or {}).items():
        if info.get("status") not in {"done", "skipped"}:
            continue
        live = fingerprint_for_stage(data, sid)
        recorded = str(info.get("paper_override_fingerprint", ""))
        if live and not recorded:
            problems.append(
                f"{sid}: this stage already finished before this override was recorded. "
                f"Loop back to {sid}, then apply and complete it under the override.")
        elif recorded and not live:
            problems.append(
                f"{sid}: the override that governed this finished stage was removed. Restore it, "
                f"or loop back to {sid} before returning the stage to the master definition.")
        elif recorded and live != recorded:
            problems.append(
                f"{sid}: its override changed after the stage finished. Workflow history is "
                f"immutable; loop back to {sid} before changing what governed it.")
    return problems


def apply(pipeline, data: dict) -> list[str]:
    """Overlay the paper's overrides onto a freshly loaded Pipeline. Returns a human summary."""
    if not data:
        return []
    notes: list[str] = []
    by_id = {s.id: s for s in pipeline.stages}

    for entry in data.get("stage_override", []):
        sid = str(entry.get("stage", "")).strip()
        stage = by_id.get(sid)
        if stage is None:
            continue
        reason = str(entry.get("reason", "")).strip()

        if entry.get("skip"):
            stage.skipped = True
            stage.skip_reason = reason
            notes.append(f"{sid}: SKIPPED - {reason}")
            continue

        relaxed = [str(c) for c in (entry.get("relax_gate") or [])]
        if relaxed:
            before = len(stage.gate)
            stage.gate = [g for g in stage.gate if str(g.get("check")) not in relaxed]
            notes.append(f"{sid}: relaxed {before - len(stage.gate)} gate(s) "
                         f"({', '.join(relaxed)}) - {reason}")

        added = entry.get("add_gate") or []
        if added:
            stage.gate = list(stage.gate) + [dict(g) for g in added]
            notes.append(f"{sid}: added {len(added)} gate(s) "
                         f"({', '.join(str(g.get('check')) for g in added)})")

        extra = [str(r) for r in (entry.get("extra_outputs") or [])]
        if extra:
            stage.outputs = list(stage.outputs) + extra
            notes.append(f"{sid}: declares {len(extra)} extra output(s) ({', '.join(extra)})")

    globs = [str(g) for g in data.get("freeform", {}).get("globs", []) or []]
    if globs:
        pipeline.freeform = list(pipeline.freeform) + globs
        reason = str(data.get("freeform", {}).get("reason", "")).strip()
        notes.append(f"freeform: {len(globs)} extra glob(s) ({', '.join(globs)}) - {reason}")
    for stage in pipeline.stages:
        stage.override_fingerprint = fingerprint_for_stage(data, stage.id)
    return notes


TEMPLATE = '''# Per-paper workflow shape. This file belongs to this paper only.
# The master remains: pipeline/pipeline.toml
schema = 1

# Simple values do NOT go here. Use the existing per-paper config instead:
#   python tools/wf.py config set intro_words_max 600
#   python tools/wf.py config set deepread_count 7

# Strengthen one stage with an extra required artifact (no reason needed):
# [[stage_override]]
# stage = "S03_protocol"
# extra_outputs = ["01_protocol/local_data_access_approval.md"]

# Add a registered gate to one stage:
# [[stage_override]]
# stage = "S06_protocol_final"
# [[stage_override.add_gate]]
# check = "md_sections"
# path = "01_protocol/protocol_final.md"
# headings = ["Site-specific governance"]

# Mark a genuinely inapplicable stage. This is a weakening, so a substantive reason is
# mandatory. Review/audit stages and any stage owning an integrity gate cannot be skipped.
# [[stage_override]]
# stage = "S02_feasibility"
# skip = true
# reason = "At least 40 characters explaining why this stage is structurally inapplicable."

# Relax a NON-PROTECTED gate that is genuinely inappropriate for this paper type. The named
# gate must actually exist on that stage; typos are refused rather than silently doing nothing.
# [[stage_override]]
# stage = "S07_artifacts"
# relax_gate = ["md_sections"]
# reason = "At least 40 characters explaining the paper-specific incompatibility."

# Permit a paper-specific family of undeclared supporting files. This weakens orphan detection,
# so it also needs a reason. Prefer extra_outputs above when the filenames are known.
# [freeform]
# reason = "At least 40 characters explaining why filenames cannot be declared individually."
# globs = ["01_protocol/site_approvals/*.pdf"]
'''
