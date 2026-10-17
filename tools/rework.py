#!/usr/bin/env python3
"""Plan, scope and persist user-requested revision rounds (scoped, no rewind, since 1.7.0).

Default flow (schema 2):  batch [--sealed] -> (more batch) -> seal -> edit the closure ->
check -> mark -> close. Completed stages stay completed; only the affected stages' content
gates run (tools/wfcore/revision.py). Explicit full-rewind fallback: `batch --rewind` (or the
single-kind `start`) rewinds to the earliest owner as before 1.7.0 (schema 1).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wfcore import overrides, paths, registry  # noqa: E402
from wfcore import revision as scoped  # noqa: E402
from wfcore.state import State  # noqa: E402


ROUTES = {
    "study-design": "S03_protocol",
    "data": "S04_data",
    "analysis": "S05_analysis",
    "final-protocol": "S06_protocol_final",
    "artifact-plan-or-legend": "S07_artifacts",
    "methods": "S08_methods",
    "results-wording": "S09_results",
    "tables": "S10_tables",
    "figures": "S11_figures",
    "table-layout": "S10_tables",
    "figure-layout": "S11_figures",
    "references": "S13_reflib",
    "introduction": "S14_introduction",
    "discussion": "S16_discussion",
    "title-abstract-keywords": "S17_assemble",
    # 1.9.0: "journal" was read as "journal formatting"; it means switching journals.
    "journal-switch": "S20_journal",
    # CSL, target_journal.json formatting fields, docx_style.json: presentation only.
    "journal-format": "S20_journal",
    "title-page-or-statements": "S21_authors",
    "cover-letter-or-package-structure": "S23_package",
}
KIND_ALIASES = {"journal": "journal-switch"}  # rounds recorded before 1.9.0

ROUND_SCHEMA = 2
LEGACY_SCHEMA = 1
REVIEW_STAGES = set(scoped.REVIEW_STAGES)
LAYOUT_KINDS = {"figure-layout", "table-layout", "word-format-only", "journal-format"}
ADMIN_KINDS = {"title-page-or-statements", "journal-switch", "journal",
               "cover-letter-or-package-structure"}
# 1.9.0: after the S19 freeze an item's class is decided by its content when it is checked
# (wfcore/presentation.py), not by the directory it touches.
POST_FREEZE_STAGES = {"S23_package", "S24_package_human_review"}

# Only decisions whose evidence can be changed by the requested kind are invalidated.
COMMON_MANUSCRIPT_INVALIDATION = {
    "independent_publishability", "manuscript_human_reviewed", "polish_reviewed",
    "submission_files_visually_confirmed", "submission_package_user_confirmed",
    "submission_package_independent_audit",
}
PACKAGE_INVALIDATION = {
    "submission_files_visually_confirmed", "submission_package_user_confirmed",
    "submission_package_independent_audit",
}
INVALIDATE_BY_KIND = {
    "study-design": COMMON_MANUSCRIPT_INVALIDATION | {
        "analysis_converged", "go_nogo_2", "tables_visually_confirmed",
        "figures_visually_confirmed", "journal_chosen",
    },
    "data": COMMON_MANUSCRIPT_INVALIDATION | {
        "analysis_converged", "go_nogo_2", "tables_visually_confirmed",
        "figures_visually_confirmed", "journal_chosen",
    },
    "analysis": COMMON_MANUSCRIPT_INVALIDATION | {
        "analysis_converged", "go_nogo_2", "tables_visually_confirmed",
        "figures_visually_confirmed", "journal_chosen",
    },
    "final-protocol": COMMON_MANUSCRIPT_INVALIDATION | {
        "analysis_converged", "go_nogo_2", "journal_chosen",
    },
    "artifact-plan-or-legend": COMMON_MANUSCRIPT_INVALIDATION | {
        "tables_visually_confirmed", "figures_visually_confirmed", "journal_chosen",
    },
    "methods": COMMON_MANUSCRIPT_INVALIDATION,
    "results-wording": COMMON_MANUSCRIPT_INVALIDATION,
    "tables": COMMON_MANUSCRIPT_INVALIDATION | {"tables_visually_confirmed"},
    "figures": COMMON_MANUSCRIPT_INVALIDATION | {"figures_visually_confirmed"},
    "table-layout": PACKAGE_INVALIDATION | {"manuscript_human_reviewed", "tables_visually_confirmed"},
    "figure-layout": PACKAGE_INVALIDATION | {"manuscript_human_reviewed", "figures_visually_confirmed"},
    "references": COMMON_MANUSCRIPT_INVALIDATION,
    "introduction": COMMON_MANUSCRIPT_INVALIDATION,
    "discussion": COMMON_MANUSCRIPT_INVALIDATION,
    "title-abstract-keywords": COMMON_MANUSCRIPT_INVALIDATION,
    "manuscript-copyedit": COMMON_MANUSCRIPT_INVALIDATION,
    "journal": PACKAGE_INVALIDATION | {"journal_chosen", "polish_reviewed"},
    "journal-switch": PACKAGE_INVALIDATION | {"journal_chosen", "polish_reviewed"},
    "journal-format": PACKAGE_INVALIDATION,
    "title-page-or-statements": PACKAGE_INVALIDATION | {"polish_reviewed"},
    "cover-letter-or-package-structure": PACKAGE_INVALIDATION,
    "word-format-only": PACKAGE_INVALIDATION,
}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    return scoped.sha256(path)


def _round_dir(state: State) -> Path:
    return state.dir / "revisions"


def _round_path(state: State, round_id: str) -> Path:
    return _round_dir(state) / f"{round_id}.json"


def _load_round(state: State) -> tuple[Path, dict]:
    round_id = state.data.get("active_revision_round")
    if not round_id:
        raise ValueError("no active revision round")
    path = _round_path(state, str(round_id))
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"invalid revision round: {path}")
    return path, payload


def _write_round(path: Path, payload: dict) -> None:
    scoped.atomic_json(path, payload)


def _next_round_id(state: State) -> str:
    numbers = []
    for path in _round_dir(state).glob("R*.json") if _round_dir(state).exists() else []:
        if path.stem[1:].isdigit():
            numbers.append(int(path.stem[1:]))
    return f"R{max(numbers, default=0) + 1:03d}"


def _valid_project_rel(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    path = Path(value.replace("\\", "/"))
    return not path.is_absolute() and ".." not in path.parts


def _read_batch_plan(path: Path, kinds: list[str], review_stage: str, pipe,
                     rewind: bool = False) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("revision plan must contain one JSON object")
    feedback = str(payload.get("feedback_verbatim", "")).strip()
    interpretation = str(payload.get("interpretation", "")).strip()
    ambiguous = payload.get("ambiguous_or_requires_user_decision", [])
    if len(feedback) < 10:
        raise ValueError("feedback_verbatim is missing or too short")
    if len(interpretation) < 40:
        raise ValueError("interpretation must explain the requested outcome in at least 40 characters")
    if not isinstance(ambiguous, list):
        raise ValueError("ambiguous_or_requires_user_decision must be an array")
    if ambiguous:
        raise ValueError("revision plan still contains an unresolved ambiguity/user decision")
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("revision plan must contain at least one atomic item")
    normalized = []
    for index, item in enumerate(items, 1):
        if not isinstance(item, dict):
            raise ValueError(f"items[{index}] is not an object")
        kind = KIND_ALIASES.get(item.get("kind"), item.get("kind"))
        if kind not in kinds:
            raise ValueError(f"items[{index}].kind must be one of {kinds}")
        if kind == "journal-switch" and not rewind:
            # Validated at batch time (1.9.0), not discovered at seal.
            raise ValueError(
                f"items[{index}]: journal-switch replaces the whole submission tree and cannot be "
                "scoped in place: rework.py batch --rewind --plan ... (then reset-journal at S20). "
                "For CSL / target_journal.json formatting fields use kind journal-format")
        request = str(item.get("request", "")).strip()
        sources = item.get("affected_sources")
        acceptance = item.get("acceptance_criteria")
        if len(request) < 10:
            raise ValueError(f"items[{index}].request is missing or too short")
        if not isinstance(sources, list) or not sources or not all(_valid_project_rel(x) for x in sources):
            raise ValueError(f"items[{index}].affected_sources must list project-relative source paths")
        sources = [s.replace("\\", "/") for s in sources]
        if (not isinstance(acceptance, list) or not acceptance or
                not all(isinstance(x, str) and len(x.strip()) >= 8 for x in acceptance)):
            raise ValueError(f"items[{index}].acceptance_criteria must contain substantive checks")
        owner = resolve_route(kind, review_stage, pipe)
        if pipe.stage(owner).index > pipe.stage(review_stage).index:
            raise ValueError(f"{kind} belongs after {review_stage}; finish the current review first")
        default_type = ("layout" if kind in LAYOUT_KINDS else
                        "wording" if kind == "manuscript-copyedit" else
                        "administrative" if kind in ADMIN_KINDS else "scientific")
        touches_science = any(s.startswith(("02_data/", "03_analysis/", "01_protocol/protocol"))
                              for s in sources)
        if (review_stage in POST_FREEZE_STAGES and default_type == "scientific"
                and kind not in scoped.SCIENTIFIC_KINDS and not touches_science):
            default_type = "auto"  # classified by content at `rework.py check`
        change_type = item.get("change_type", default_type)
        if change_type == "auto" and (kind in scoped.SCIENTIFIC_KINDS or touches_science):
            change_type = "scientific"
        if change_type not in {"layout", "wording", "administrative", "scientific", "auto"}:
            raise ValueError("change_type must be layout, wording, administrative, scientific or auto")
        if kind in scoped.SCIENTIFIC_KINDS and change_type != "scientific":
            raise ValueError("data/design/model changes cannot be downgraded to cosmetic revisions")
        if change_type != "scientific" and any(
                s.startswith(("02_data/", "03_analysis/", "01_protocol/protocol")) for s in sources):
            raise ValueError("a non-scientific revision may not edit data, analysis or protocol sources")
        if change_type == "layout" and any(s.endswith(".md") for s in sources):
            raise ValueError("Markdown wording changes are not layout-only")
        if any(s.startswith((".wf/", "temp/")) for s in sources):
            raise ValueError("workflow state and scratch files are not revision sources")
        normalized.append({
            "kind": kind, "request": request, "owning_stage": owner,
            "change_type": change_type, "affected_sources": sources,
            "acceptance_criteria": acceptance, "status": "pending", "resolution": None,
            "changed_files": [], "validated_by": [],
        })
    return {
        "feedback_verbatim": feedback,
        "feedback_sha256": _sha256_text(feedback),
        "interpretation": interpretation,
        "items": normalized,
    }


def _clear_decisions(state: State, names: set[str]) -> list[str]:
    decisions = state.data.get("decisions", {})
    removed = sorted(name for name in names if name in decisions)
    for name in removed:
        del decisions[name]
    if removed:
        state.event("revision_decisions_invalidated", ", ".join(removed))
        state.save()
    return removed


# ---------------------------------------------------------------------------
# explicit full-rewind fallback (schema 1, the pre-1.7.0 behaviour)
# ---------------------------------------------------------------------------
def _rewind_batch(state: State, pipe, target: str, why: str) -> bool:
    current = pipe.stage(state.current)
    destination = pipe.stage(target)
    if destination.index > current.index:
        return False
    state.add_note(f"[REVISION ROUND] returning to {target}: {why}", current.id)
    state.reset_forward([stage.id for stage in pipe.stages_after(target)])
    state.rewind(target, why)
    return True


def _cmd_batch_rewind(args, project: Path, pipe, state: State, kinds: list[str]) -> int:
    active = state.data.get("active_revision_round")
    if active:
        round_path, revision = _load_round(state)
        if scoped.is_scoped(revision):
            if revision.get("status") != "collecting":
                raise ValueError("a sealed scoped round cannot switch to a full rewind; finish "
                                 "and close it, then open the rewind round")
            # Nothing was built yet: convert the collected scoped round into a rewind round.
            revision["schema_version"] = LEGACY_SCHEMA
            revision["status"] = "active"
            revision["converted_from_scoped"] = _now()
            for key in ("baseline", "baseline_documents", "rebuild_files", "allowed_files",
                        "checks", "validation_stages", "reuse_count"):
                revision.pop(key, None)
        review_stage = revision["review_stage"]
    else:
        if state.current not in REVIEW_STAGES:
            raise ValueError("a new revision round can start only while the user is reviewing at S19 or S24")
        review_stage = state.current
        round_id = _next_round_id(state)
        round_path = _round_path(state, round_id)
        revision = {
            "schema_version": LEGACY_SCHEMA, "round_id": round_id, "review_stage": review_stage,
            "created_at": _now(), "status": "active", "feedback_updates": [], "items": [],
            "full_rewind": True,
        }
    plan = _read_batch_plan(args.plan.resolve(), kinds, review_stage, pipe, rewind=True)
    first_new = len(revision["items"]) + 1
    for offset, item in enumerate(plan["items"]):
        item["id"] = f"{revision['round_id']}-{first_new + offset:02d}"
        revision["items"].append(item)
    revision["feedback_updates"].append({
        "at": _now(), "feedback_verbatim": plan["feedback_verbatim"],
        "feedback_sha256": plan["feedback_sha256"], "interpretation": plan["interpretation"],
    })
    revision["earliest_stage"] = min(
        (item["owning_stage"] for item in revision["items"]),
        key=lambda stage_id: pipe.stage(stage_id).index,
    )
    revision["updated_at"] = _now()
    _write_round(round_path, revision)
    state.data["active_revision_round"] = revision["round_id"]
    state.event("revision_round_opened" if not active else "revision_round_extended",
                f"{revision['round_id']}: {len(revision['items'])} item(s) (full rewind)")
    state.save()
    invalidations: set[str] = set()
    for item in revision["items"]:
        invalidations.update(INVALIDATE_BY_KIND[item["kind"]])
    # A late package-round correction passes the scientific-review checkpoint on its way
    # back to S24; retain the earlier S19 approval there.
    if review_stage == "S24_package_human_review":
        invalidations.discard("manuscript_human_reviewed")
    removed = _clear_decisions(state, invalidations)
    scoped.drop_receipts(state)
    target = revision["earliest_stage"]
    rewound = _rewind_batch(state, pipe, target,
                            f"{revision['round_id']} user feedback; full rewind requested")
    print(f"FULL REWIND round {revision['round_id']}: {len(revision['items'])} total item(s)")
    print(f"review return point: {review_stage}; earliest owner: {revision['earliest_stage']}")
    print(f"invalidated decisions: {', '.join(removed) if removed else 'none'}")
    print(f"current stage: {state.current}" + (" (rewound)" if rewound else " (unchanged)"))
    return 0


# ---------------------------------------------------------------------------
# scoped rounds (default)
# ---------------------------------------------------------------------------
def _baseline_documents(project: Path) -> dict:
    plan = project / "01_protocol/artifact_plan.json"
    try:
        return {"01_protocol/artifact_plan.json": json.loads(plan.read_text(encoding="utf-8"))} \
            if plan.is_file() else {}
    except (OSError, ValueError):
        return {}


def _cmd_batch(args, project: Path, pipe, state: State, kinds: list[str]) -> int:
    active = state.data.get("active_revision_round")
    if active:
        round_path, revision = _load_round(state)
        if not scoped.is_scoped(revision):
            print("legacy (schema-1) round is active: extending it with the pre-1.7.0 rewind flow")
            return _cmd_batch_rewind(args, project, pipe, state, kinds)
        if revision.get("status") != "collecting":
            if getattr(args, "merge", False):
                return _merge_into_sealed(args, project, pipe, state, kinds, round_path, revision)
            raise ValueError(
                f"{revision['round_id']} is sealed. Either add this feedback to it (batch --merge), "
                "put it first and park the open round (batch --priority, e.g. science over an "
                "unfinished layout round), or finish and close it first")
        review_stage = revision["review_stage"]
    else:
        if state.current not in REVIEW_STAGES:
            raise ValueError("a new revision round can start only while the user is reviewing at S19 or S24")
        review_stage = state.current
        round_id = _next_round_id(state)
        round_path = _round_path(state, round_id)
        revision = {
            "schema_version": ROUND_SCHEMA, "round_id": round_id, "review_stage": review_stage,
            "origin_stage": review_stage, "created_at": _now(), "status": "collecting",
            "full_builds": 0, "feedback_updates": [], "items": [],
            "baseline": scoped.snapshot(project), "baseline_documents": _baseline_documents(project),
        }
        _add_fact_baseline(project, revision)
    plan = _read_batch_plan(args.plan.resolve(), kinds, review_stage, pipe)
    if any(u.get("feedback_sha256") == plan["feedback_sha256"] for u in revision["feedback_updates"]):
        print("identical feedback already recorded; no duplicate items")
        return _seal_round(state, pipe, args.why or plan["feedback_verbatim"]) if args.sealed else 0
    first_new = len(revision["items"]) + 1
    for offset, item in enumerate(plan["items"]):
        item["id"] = f"{revision['round_id']}-{first_new + offset:02d}"
        revision["items"].append(item)
    revision["feedback_updates"].append({
        "at": _now(), "feedback_verbatim": plan["feedback_verbatim"],
        "feedback_sha256": plan["feedback_sha256"], "interpretation": plan["interpretation"],
    })
    revision["earliest_stage"] = min((i["owning_stage"] for i in revision["items"]),
                                     key=lambda sid: pipe.stage(sid).index)
    revision["updated_at"] = _now()
    _write_round(round_path, revision)
    state.data["active_revision_round"] = revision["round_id"]
    state.event("revision_round_opened" if not active else "revision_round_extended",
                f"{revision['round_id']}: {len(revision['items'])} item(s), collecting")
    state.save()
    print(f"collected {revision['round_id']}: {len(revision['items'])} item(s); nothing is built yet")
    if not args.sealed:
        print("More feedback: run batch again. When the user is done: rework.py seal --why \"<their instruction>\"")
        return 0
    return _seal_round(state, pipe, args.why or plan["feedback_verbatim"])


def _add_fact_baseline(project: Path, revision: dict) -> None:
    """Post-freeze rounds remember the reviewed facts so `check` can classify by content."""
    from wfcore import presentation, scifreeze
    if revision.get("review_stage") in POST_FREEZE_STAGES and scifreeze.is_frozen(project):
        revision["fact_baseline"] = presentation.snapshot_facts(project)
        # Frozen files already edited before the round opened cannot be compared with what
        # review saw; they are judged scientific (restore them, then open the round).
        _, drift, _ = scifreeze.verify_freeze(project)
        revision["pre_round_edits"] = sorted(d.split(":")[0] for d in drift)


def _classified(project: Path, revision: dict) -> bool:
    return "fact_baseline" in revision


def _move_science_to_s19(state: State, pipe, revision: dict, science: list[dict]) -> bool:
    for item in science:
        if pipe.stage(item["owning_stage"]).index > pipe.stage("S19_human_review").index:
            item["owning_stage"] = "S19_human_review"
    revision["deferred_package_items"] = [i for i in revision["items"] if i not in science]
    revision["items"] = science
    origin = revision["review_stage"]
    revision["review_stage"] = "S19_human_review"
    state.stage_info(origin)["status"] = "pending"
    state.stage_info("S19_human_review")["status"] = "active"
    state.data["current"] = "S19_human_review"
    state.data["resume_package_revision"] = revision["round_id"]
    state.event("revision_science_to_s19",
                f"{revision['round_id']}: post-S19 science returns to S19; S20-S23 stay done")
    return True


def _changed_since_baseline(project: Path, revision: dict) -> dict[str, str]:
    base = revision.get("baseline", {})
    now = scoped.snapshot(project)
    return {r: base.get(r, "") for r in set(base) | set(now) if base.get(r) != now.get(r)}


def _classify_for_check(project: Path, pipe, state: State, path: Path, revision: dict) -> int | None:
    """1.9.0: decide presentation vs science by content before the scoped checks run.

    Returns an exit code when the round was escalated to S19, else None (continue checking).
    """
    from wfcore import presentation
    if not _classified(project, revision) or revision.get("status") != "active":
        return None
    pending = [i for i in revision["items"] if i["change_type"] != "scientific"]
    if not pending:
        return None
    changed = _changed_since_baseline(project, revision)
    verdict = presentation.classify(project, revision["fact_baseline"], sorted(changed))
    early = revision.get("pre_round_edits") or []
    if early:
        verdict["reasons"] += [f"{rel}: edited after the freeze before this round opened "
                               "(cannot be compared with the reviewed text)" for rel in early]
        verdict["class"] = "scientific"
    revision["classification"] = verdict
    if verdict["class"] == "presentation":
        summary = "; ".join(i["request"][:120] for i in revision["items"])
        touched = presentation.record_delta(project, revision["round_id"], summary, changed)
        revision["presentation_delta"] = {"at": verdict["at"], "files": sorted(changed), **touched}
        _write_round(path, revision)
        print(f"PRESENTATION change (facts unchanged in {len(verdict['checked'])} reviewed file(s)): "
              "deterministic checks only; no return to S19, no new review round, no re-confirmation.")
        print("changed: " + (", ".join(sorted(changed)) or "none"))
        print("Show the user this change summary when reporting the round.")
        return None
    print("SCIENTIFIC change: facts differ from the reviewed version:")
    for reason in verdict["reasons"][:12]:
        print(f"  - {reason}")
    if revision["review_stage"] != "S24_package_human_review":
        _write_round(path, revision)
        print("Open the round at S24 so the science can return to S19, or restore the facts.")
        return 2
    for item in pending:
        item["change_type"] = "scientific"
    science = [i for i in revision["items"]
               if not all(s.startswith(("00_input/", "08_submission/")) for s in i["affected_sources"])]
    _move_science_to_s19(state, pipe, revision, science or revision["items"])
    names = set(revision.pop("deferred_invalidations", [])) | {"manuscript_human_reviewed"}
    revision.pop("fact_baseline", None)
    scoped.plan_scope(project, pipe, state, revision)
    _write_round(path, revision)
    removed = _clear_decisions(state, names)
    scoped.drop_receipts(state)
    state.save()
    print(f"-> back at S19 for re-review and re-freeze (as for any science change); "
          f"invalidated: {', '.join(removed) or 'none'}. Rerun rework.py check at S19.")
    return 2


def _seal_round(state: State, pipe, why: str) -> int:
    if len(why.strip()) < 10:
        raise ValueError("seal requires the user's end-of-batch or apply-now instruction (--why)")
    round_path, revision = _load_round(state)
    project = state.project
    if not scoped.is_scoped(revision):
        raise ValueError("legacy round: finish it through its recorded stage gates")
    if revision.get("status") != "collecting":
        raise ValueError(f"{revision['round_id']} is already sealed")
    science_moved = False
    if revision["review_stage"] == "S24_package_human_review":
        # Science changed after S19 is re-reviewed and re-frozen at S19 before any journal copy
        # is touched (scifreeze); package items wait for the resumed round. 1.9.0: an item is
        # science by its declared/classified content, not by the directory it edits.
        if _classified(project, revision):
            science = [i for i in revision["items"] if i["change_type"] == "scientific"]
        else:  # no scientific freeze: the pre-1.9.0 directory rule
            for item in revision["items"]:
                if item["change_type"] == "auto":
                    item["change_type"] = "scientific"
            science = [i for i in revision["items"] if any(
                not s.startswith(("00_input/", "08_submission/")) for s in i["affected_sources"])]
        if science:
            if any(any(s.startswith(("00_input/", "08_submission/")) for s in i["affected_sources"])
                   for i in science):
                raise ValueError("split scientific sources and journal-package sources into separate items")
            science_moved = _move_science_to_s19(state, pipe, revision, science)
    scoped.plan_scope(project, pipe, state, revision)
    if _classified(project, revision):
        revision["allowed_files"] = sorted(set(revision["allowed_files"])
                                           | {"08_submission/manuscript/variant.json"})
    revision.update({"status": "active", "sealed_at": _now(), "seal_instruction": why.strip()})
    _write_round(round_path, revision)
    review_stage = revision["review_stage"]
    invalidations: set[str] = set()
    deferred: set[str] = set()
    for item in revision["items"] + revision.get("deferred_package_items", []):
        names = set(INVALIDATE_BY_KIND[item["kind"]])
        if item["change_type"] != "scientific":
            names.discard("independent_publishability")
        names.discard("journal_chosen")  # in place: the chosen journal stays chosen
        if _classified(project, revision) and item["change_type"] != "scientific":
            deferred.update(names)  # kept unless the content check finds changed facts
            continue
        invalidations.update(names)
    if review_stage == "S19_human_review":
        invalidations.add("manuscript_human_reviewed")
    else:
        invalidations.discard("manuscript_human_reviewed")
        deferred.discard("manuscript_human_reviewed")
    if deferred:
        revision["deferred_invalidations"] = sorted(deferred - invalidations)
        _write_round(round_path, revision)
    removed = _clear_decisions(state, invalidations)
    scoped.drop_receipts(state)
    state.save()
    state.add_note(f"[SCOPED REVISION] {revision['round_id']} sealed; edit the closure in place, "
                   "no stage tail reset", state.current)
    print(f"sealed {revision['round_id']}: {len(revision['items'])} item(s); return point {review_stage}")
    if science_moved:
        print("post-S19 science: back at S19 for re-review and re-freeze; "
              f"{len(revision['deferred_package_items'])} package item(s) resume at S24 afterwards")
    print(f"invalidated decisions: {', '.join(removed) if removed else 'none'}")
    print(f"affected files: {len(revision['rebuild_files'])}; validate: "
          f"{', '.join(revision['validation_stages']) or 'review-stage checks only'}")
    print("next: edit only the listed files, then rework.py check / mark / close (status lists them)")
    return 0


# ---------------------------------------------------------------------------
# 1.8.0: merge, suspend/priority, resume with per-item progress, S23 layout rounds
# ---------------------------------------------------------------------------
def _merge_into_sealed(args, project: Path, pipe, state: State, kinds, round_path: Path,
                       revision: dict) -> int:
    """Fold new feedback into the sealed round and re-plan its scope (no second round)."""
    if revision["review_stage"] != state.current:
        raise ValueError("merge only at the round's own review stage; use batch --priority instead")
    plan = _read_batch_plan(args.plan.resolve(), kinds, revision["review_stage"], pipe)
    if any(u.get("feedback_sha256") == plan["feedback_sha256"] for u in revision["feedback_updates"]):
        print("identical feedback already recorded; no duplicate items")
        return 0
    first_new = len(revision["items"]) + 1
    for offset, item in enumerate(plan["items"]):
        item["id"] = f"{revision['round_id']}-{first_new + offset:02d}"
        revision["items"].append(item)
    revision["feedback_updates"].append({
        "at": _now(), "feedback_verbatim": plan["feedback_verbatim"],
        "feedback_sha256": plan["feedback_sha256"], "interpretation": plan["interpretation"],
        "merged_after_seal": True})
    revision["earliest_stage"] = min((i["owning_stage"] for i in revision["items"]),
                                     key=lambda sid: pipe.stage(sid).index)
    scoped.plan_scope(project, pipe, state, revision)
    revision.pop("validation", None)
    revision["updated_at"] = _now()
    _write_round(round_path, revision)
    state.event("revision_round_merged", f"{revision['round_id']}: +{len(plan['items'])} item(s)")
    names: set[str] = set()
    for item in plan["items"]:
        names.update(INVALIDATE_BY_KIND[item["kind"]] - {"journal_chosen"})
    if revision["review_stage"] != "S19_human_review":
        names.discard("manuscript_human_reviewed")
    _clear_decisions(state, names)
    scoped.drop_receipts(state)
    state.save()
    print(f"merged into {revision['round_id']}: now {len(revision['items'])} item(s); scope re-planned "
          f"({len(revision['rebuild_files'])} affected file(s))")
    return 0


def _cmd_suspend(args, project: Path, state: State) -> int:
    path, revision = _load_round(state)
    if not scoped.is_scoped(revision):
        raise ValueError("a legacy full-rewind round cannot be suspended")
    if revision.get("review_stage") != state.current:
        raise ValueError("this round has moved to another checkpoint; finish it there")
    why = (args.why or "").strip()
    if len(why) < 10:
        raise ValueError("suspend requires --why (e.g. 'scientific feedback takes priority')")
    revision["suspended"] = {"at": _now(), "why": why, "from_status": revision["status"],
                             "snapshot": scoped.snapshot(project)}
    revision["status"] = "suspended"
    revision.pop("validation", None)
    _write_round(path, revision)
    state.data.pop("active_revision_round", None)
    parked = state.data.setdefault("suspended_revision_rounds", [])
    if revision["round_id"] not in parked:
        parked.append(revision["round_id"])
    state.event("revision_round_suspended", f"{revision['round_id']}: {why}")
    scoped.drop_receipts(state)
    state.save()
    print(f"suspended {revision['round_id']} ({revision['suspended']['from_status']}); "
          "a new round may open now. Resume later: rework.py resume --round "
          f"{revision['round_id']}")
    return 0


def _reactivate(project: Path, pipe, state: State, round_id: str) -> None:
    if state.data.get("active_revision_round"):
        raise ValueError("close or suspend the active round before resuming another")
    parked = state.data.get("suspended_revision_rounds", [])
    if round_id not in parked:
        raise ValueError(f"{round_id} is not suspended (suspended: {', '.join(parked) or 'none'})")
    path = _round_path(state, round_id)
    revision = json.loads(path.read_text(encoding="utf-8"))
    info = revision.pop("suspended")
    snap, now = info.pop("snapshot", {}), scoped.snapshot(project)
    allowed = set(revision.get("allowed_files", []))
    rebased = []
    # Files another (closed) round changed while this one was parked become its new baseline;
    # they are not this round's unplanned changes.
    for rel in sorted(set(snap) | set(now)):
        if snap.get(rel) != now.get(rel) and rel not in allowed:
            if rel in now:
                revision.setdefault("baseline", {})[rel] = now[rel]
            else:
                revision.get("baseline", {}).pop(rel, None)
            rebased.append(rel)
    revision["status"] = info["from_status"]
    revision.setdefault("suspensions", []).append({**info, "resumed_at": _now(), "rebased": rebased})
    if revision["status"] == "active":
        scoped.plan_scope(project, pipe, state, revision)
    _write_round(path, revision)
    parked.remove(round_id)
    state.data["active_revision_round"] = round_id
    state.event("revision_round_resumed", f"{round_id}: {len(rebased)} file(s) rebased")
    scoped.drop_receipts(state)
    state.save()
    print(f"resumed {round_id}; {len(rebased)} file(s) changed meanwhile by other rounds were rebased")


def _cmd_progress(args, project: Path, state: State) -> int:
    """Record that an item is partly done, so an interrupted run resumes from it."""
    path, revision = _load_round(state)
    item = next((i for i in revision["items"] if i["id"] == args.item), None)
    if item is None:
        raise ValueError(f"unknown item {args.item}")
    if len((args.summary or "").strip()) < 10:
        raise ValueError("progress needs --summary of what is done so far")
    files = []
    for rel in args.changed_file:
        if not _valid_project_rel(rel) or not (project / rel).is_file():
            raise ValueError(f"changed file does not exist: {rel}")
        files.append({"path": Path(rel).as_posix(), "sha256": _sha256_file(project / rel)})
    if item.get("status") != "done":
        item["status"] = "in_progress"
    item.setdefault("progress", []).append({"at": _now(), "note": args.summary.strip(), "files": files})
    revision["updated_at"] = _now()
    _write_round(path, revision)
    print(f"progress recorded for {args.item}")
    return 0


def _print_resume(project: Path, state: State) -> int:
    try:
        _, revision = _load_round(state)
    except ValueError:
        parked = state.data.get("suspended_revision_rounds", [])
        print("no active revision round" + (f"; suspended: {', '.join(parked)}" if parked else ""))
        return 0
    base = revision.get("baseline", {})
    now = scoped.snapshot(project)
    changed = sorted(r for r in set(base) | set(now) if base.get(r) != now.get(r))
    print(f"{revision['round_id']}  status={revision['status']}  return={revision['review_stage']}")
    claimed: set[str] = set()
    for item in revision["items"]:
        mine = [r for r in changed if r in item.get("affected_sources", [])]
        claimed.update(mine)
        print(f"  [{item.get('status')}] {item['id']} {item['kind']}: {item['request'][:80]}")
        for note in item.get("progress", [])[-2:]:
            print(f"      progress {note['at']}: {note['note'][:100]}")
        print(f"      changed so far: {', '.join(mine) or 'none'}")
    rest = [r for r in changed if r not in claimed]
    if rest:
        print("  changed in the closure, not yet attributed to an item: " + ", ".join(rest[:12]))
    pending = [i["id"] for i in revision["items"] if i.get("status") != "done"]
    print(f"next: finish {', '.join(pending)} then rework.py check / mark / close" if pending
          else "next: rework.py check, then close")
    parked = state.data.get("suspended_revision_rounds", [])
    if parked:
        print(f"suspended rounds waiting: {', '.join(parked)} (rework.py resume --round <id>)")
    return 0


def _cmd_layout(args, project: Path, pipe, state: State) -> int:
    """S23/S24: a controlled layout round for an edit to a certified figure/table source."""
    if state.current not in ("S23_package", "S24_package_human_review"):
        raise ValueError("layout rounds are for S23/S24; earlier, edit within the owning stage")
    if state.data.get("active_revision_round"):
        raise ValueError("a round is open; add the file with batch --merge instead")
    sources = [s.replace("\\", "/") for s in args.source]
    if not sources or not all(_valid_project_rel(s) for s in sources):
        raise ValueError("layout needs --source <paper-relative figure/table script>")
    if any(s.endswith(".md") or not s.startswith(("05_figures/", "04_tables/")) for s in sources):
        raise ValueError("layout rounds cover figure/table scripts and renders only; wording "
                         "goes through a normal round")
    why = (args.why or "").strip()
    if len(why) < 20:
        raise ValueError("layout needs --why describing the visual change (>= 20 characters)")
    kind = "figure-layout" if all(s.startswith("05_figures/") for s in sources) else "table-layout"
    round_id = _next_round_id(state)
    item = {"kind": kind, "request": why, "owning_stage": ROUTES[kind], "change_type": "layout",
            "affected_sources": sources, "status": "pending", "resolution": None,
            "changed_files": [], "validated_by": [], "id": f"{round_id}-01",
            "acceptance_criteria": ["deterministic QC passes on the re-render",
                                    "the re-rendered display is visually re-confirmed"]}
    revision = {
        "schema_version": ROUND_SCHEMA, "round_id": round_id, "review_stage": state.current,
        "origin_stage": state.current, "created_at": _now(), "status": "collecting",
        "full_builds": 0, "items": [item], "earliest_stage": ROUTES[kind], "auto_layout": True,
        "feedback_updates": [{"at": _now(), "feedback_verbatim": why,
                              "feedback_sha256": _sha256_text(why),
                              "interpretation": "controlled layout-only round opened by rework.py layout"}],
        "baseline": scoped.snapshot(project), "baseline_documents": _baseline_documents(project),
    }
    _add_fact_baseline(project, revision)
    # The edit may already be on disk: the baseline must hold the certified version.
    for rel, (_, digest) in scoped.certified_hashes(project).items():
        if rel in sources:
            revision["baseline"][rel] = digest
    _write_round(_round_path(state, round_id), revision)
    state.data["active_revision_round"] = round_id
    state.event("revision_round_opened", f"{round_id}: layout round for {', '.join(sources)}")
    state.save()
    return _seal_round(state, pipe, f"layout round opened at {state.current}: {why}")


def _cmd_status(state: State, full: bool = False) -> int:
    try:
        _, revision = _load_round(state)
    except ValueError:
        print("no active revision round")
        return 0
    scoped_round = scoped.is_scoped(revision)
    print(f"{revision['round_id']}  status={revision['status']}  return={revision['review_stage']}"
          f"  {'scoped' if scoped_round else 'full-rewind (schema 1)'}")
    print(f"earliest owner: {revision.get('earliest_stage')}; current stage: {state.current}")
    if scoped_round and revision.get("status") == "active":
        print(f"full builds used: {revision.get('full_builds', 0)}/{scoped.FULL_BUILDS_MAX}")
        print(f"validate stages: {', '.join(revision.get('validation_stages', [])) or 'review-stage checks only'}")
        print(f"may change ({len(revision.get('rebuild_files', []))} affected, "
              f"{revision.get('reuse_count', 0)} protected):")
        for rel in revision.get("rebuild_files", []):
            print(f"    {rel}")
        checked = revision.get("validation", {})
        if checked:
            print(f"last check: {'PASS' if checked.get('ok') else 'FAIL'} at {checked.get('checked_at')}")
    items = revision["items"] if full else [i for i in revision["items"] if i.get("status") != "done"]
    if len(items) != len(revision["items"]):
        print(f"done items omitted: {len(revision['items']) - len(items)} (status --full)")
    for item in items:
        print(f"  [{item['status']}] {item['id']} {item['kind']} -> {item['owning_stage']}")
        print(f"      {item['request']}")
        print(f"      sources: {', '.join(item['affected_sources'])}")
        print(f"      acceptance: {'; '.join(item['acceptance_criteria'])}")
    for item in revision.get("deferred_package_items", []):
        print(f"  [deferred to S24] {item['kind']}: {item['request'][:90]}")
    return 0


def _cmd_mark(args, project: Path, state: State) -> int:
    path, revision = _load_round(state)
    if revision.get("status") == "collecting":
        raise ValueError("seal the batch before marking items")
    if state.current != revision["review_stage"]:
        raise ValueError(
            f"mark items only after the gated workflow returns to {revision['review_stage']}; "
            f"current={state.current}"
        )
    item = next((entry for entry in revision["items"] if entry["id"] == args.item), None)
    if item is None:
        raise ValueError(f"unknown item {args.item}")
    if len(args.summary.strip()) < 30:
        raise ValueError("mark summary must state what changed in at least 30 characters")
    deleted_files = getattr(args, "deleted_file", []) or []
    if not args.changed_file and not deleted_files:
        raise ValueError("mark requires at least one --changed-file (or --deleted-file)")
    if not args.validated_by:
        raise ValueError("mark requires at least one --validated-by check or inspection")
    changed = []
    changed_names: set[str] = set()
    for rel in deleted_files:
        # 1.9.0: a deletion credential. Later checks accept the file's absence and flag it
        # only if it reappears.
        if not _valid_project_rel(rel):
            raise ValueError(f"unsafe deleted-file path: {rel}")
        if (project / rel).exists():
            raise ValueError(f"--deleted-file still exists: {rel}; delete it first")
        normalized = Path(rel).as_posix()
        changed_names.add(normalized)
        changed.append({"path": normalized, "sha256": scoped.DELETED, "deleted": True})
    for rel in args.changed_file:
        if not _valid_project_rel(rel):
            raise ValueError(f"unsafe changed-file path: {rel}")
        source = project / rel
        if not source.is_file():
            raise ValueError(f"changed file does not exist: {rel}")
        normalized = Path(rel).as_posix()
        changed_names.add(normalized)
        changed.append(scoped.receipt(project, normalized))
    required_sources = {Path(rel).as_posix() for rel in item.get("affected_sources", [])}
    missing_sources = sorted(required_sources - changed_names)
    if missing_sources:
        raise ValueError(
            "mark must hash every declared affected source; missing: " + ", ".join(missing_sources)
        )
    item.update({
        "status": "done", "resolution": args.summary.strip(), "changed_files": changed,
        "validated_by": args.validated_by, "completed_at": _now(),
    })
    revision["updated_at"] = _now()
    _write_round(path, revision)
    print(f"marked {args.item} done; {len(changed)} changed file(s), {len(args.validated_by)} validation(s)")
    return 0


def _cmd_close(args, state: State, pipe=None) -> int:
    path, revision = _load_round(state)
    if revision.get("status") == "collecting":
        raise ValueError("cannot close while collecting feedback; seal and implement the batch first")
    pending = [item["id"] for item in revision["items"] if item.get("status") != "done"]
    if pending:
        raise ValueError("cannot close; pending items: " + ", ".join(pending))
    if state.current != revision["review_stage"]:
        raise ValueError(
            f"cannot close until the gated workflow returns to {revision['review_stage']}; current={state.current}"
        )
    if len(args.summary.strip()) < 40:
        raise ValueError("close summary must describe the completed round in at least 40 characters")
    project = state.project
    if scoped.is_scoped(revision):
        pipe = pipe or _pipeline(state)
        checked = revision.get("validation", {})
        if not checked.get("ok") or checked.get("input_signature") != scoped.input_signature(
                project, state, revision):
            raise ValueError("run rework.py check on the final files; typed validation labels "
                             "alone cannot close a scoped round")
        checked_at = datetime.fromisoformat(checked.get("checked_at", "1970-01-01T00:00:00+00:00"))
        if not 0 <= (datetime.now(timezone.utc) - checked_at).total_seconds() < 86400:
            raise ValueError("scoped validation expired; rerun rework.py check before closing")
        for item in revision["items"]:
            for receipt in item.get("changed_files", []):
                if not scoped.renewable(receipt["path"]) and not scoped.receipt_holds(
                        project, receipt):
                    raise ValueError("a marked file changed; mark its final version again before "
                                     f"closing ({receipt['path']})")
        scoped.refresh_evidence(project, pipe, state, revision)
        if checked.get("input_signature") != scoped.input_signature(project, state, revision):
            raise ValueError("a source changed while refreshing evidence; rerun rework.py check")
    revision.update({"status": "complete", "completed_at": _now(), "completion_summary": args.summary.strip()})
    _write_round(path, revision)
    state.data.pop("active_revision_round", None)
    scoped.drop_receipts(state)
    state.event("revision_round_closed", revision["round_id"])
    state.add_note(f"[REVISION COMPLETE] {revision['round_id']}: {args.summary.strip()}", state.current)
    state.save()
    print(f"closed {revision['round_id']}; user review may now continue")
    if revision.get("classification", {}).get("class") == "presentation":
        files = revision.get("presentation_delta", {}).get("files", [])
        print(f"presentation delta recorded ({len(files)} file(s)); the freezes were updated, not "
              "invalidated. Tell the user what changed (summary above); no re-confirmation needed.")
    if state.data.get("resume_package_revision") == revision["round_id"]:
        print("next: run an S19 review round (tools/review_round.py start --delta), get the user's no-further-review answer, "
              "scientific_freeze.py capture --force, then wf advance (resumes the S24 package round)")
    return 0


def _cmd_build(args, state: State) -> int:
    path, revision = _load_round(state)
    if revision.get("status") == "collecting":
        raise ValueError("feedback collection is open; seal before building")
    if not scoped.is_scoped(revision):
        raise ValueError("build bookkeeping applies to scoped rounds only")
    if args.scope == "full":
        if revision.get("full_builds", 0) >= scoped.FULL_BUILDS_MAX:
            raise ValueError(f"{scoped.FULL_BUILDS_MAX} full builds already used in this round; find "
                             "the unstable input and rebuild only the affected files")
        revision["full_builds"] = revision.get("full_builds", 0) + 1
    elif not args.why or len(args.why.strip()) < 10:
        raise ValueError("targeted build needs --why naming the changed artifacts")
    revision.setdefault("builds", []).append({"at": _now(), "scope": args.scope, "why": args.why})
    _write_round(path, revision)
    print(f"{args.scope} build recorded ({revision.get('full_builds', 0)}/{scoped.FULL_BUILDS_MAX} "
          "full); writers still accept only the planned closure")
    return 0


def resolve_route(kind: str, current: str, pipe) -> str:
    if kind == "manuscript-copyedit":
        current_index = pipe.stage(current).index
        if current_index < pipe.stage("S19_human_review").index:
            raise ValueError("manuscript-copyedit routing is available from S19 onward")
        return ("S22_polish" if current_index >= pipe.stage("S22_polish").index
                else "S19_human_review")
    if kind == "word-format-only":
        current_index = pipe.stage(current).index
        if current_index < pipe.stage("S23_package").index:
            raise ValueError("word-format-only routing is available after the package is built")
        return ("S23_package" if current == "S23_package"
                else "S24_package_human_review")
    return ROUTES[kind]


def _pipeline(state: State):
    """The paper's effective pipeline: config targets plus its overrides (skips included)."""
    return registry.load(state.config(), overrides.load(state.dir))


def main() -> int:
    kinds = sorted([*ROUTES, "manuscript-copyedit", "word-format-only"])
    parser = argparse.ArgumentParser(
        description="plan, scope and persist user-requested medpaper revision rounds")
    parser.add_argument("command", choices=["plan", "start", "batch", "seal", "check", "build",
                                            "refresh", "status", "mark", "close", "suspend",
                                            "resume", "progress", "layout"])
    parser.add_argument("--merge", action="store_true",
                        help="batch: add this feedback to the sealed open round and re-plan it")
    parser.add_argument("--priority", action="store_true",
                        help="batch: suspend the open round and open this feedback first")
    parser.add_argument("--round", help="resume: the suspended round to reactivate")
    parser.add_argument("--source", action="append", default=[],
                        help="layout: certified figure/table source being changed (repeatable)")
    parser.add_argument("--kind", choices=kinds)
    parser.add_argument("--why", help="user instruction (seal) or reason (start/build)")
    parser.add_argument("--plan", type=Path,
                        help="JSON plan for a new or extended multi-item revision round")
    parser.add_argument("--sealed", action="store_true",
                        help="batch: the user asked to apply this complete batch now")
    parser.add_argument("--rewind", action="store_true",
                        help="batch: explicit full-rewind fallback (pre-1.7.0 behaviour)")
    parser.add_argument("--scope", choices=["targeted", "full"], default="targeted")
    parser.add_argument("--full", action="store_true", help="status: include done items")
    parser.add_argument("--item", help="revision item id for mark")
    parser.add_argument("--changed-file", action="append", default=[],
                        help="project-relative changed source; repeat as needed")
    parser.add_argument("--validated-by", action="append", default=[],
                        help="completed gate/test/inspection; repeat as needed")
    parser.add_argument("--summary", nargs="?", const=True,
                        help="mark/close: resolution or round-completion summary; "
                             "check: bare --summary prints one result line")
    parser.add_argument("--deleted-file", action="append", default=[],
                        help="mark: a project-relative source this item deleted (records a "
                             "deletion credential; repeatable)")
    parser.add_argument("--quiet", action="store_true",
                        help="check: print failures only")
    parser.add_argument("--project", type=Path, default=None)
    args = parser.parse_args()
    project = paths.paper_from_cli(args.project)
    try:
        state = State(project, ".wf").load()
        pipe = _pipeline(state)
        if args.command == "status":
            return _cmd_status(state, args.full)
        if args.command == "batch":
            if args.plan is None:
                raise ValueError("batch requires --plan <revision-plan.json>")
            if args.rewind:
                return _cmd_batch_rewind(args, project, pipe, state, kinds)
            if args.priority and state.data.get("active_revision_round"):
                if state.current not in REVIEW_STAGES:
                    raise ValueError("a priority round opens only at S19 or S24")
                _read_batch_plan(args.plan.resolve(), kinds, state.current, pipe)  # validate first
                args.why = args.why or "suspended: newer feedback was given priority"
                _cmd_suspend(args, project, state)
            return _cmd_batch(args, project, pipe, state, kinds)
        if args.command == "suspend":
            return _cmd_suspend(args, project, state)
        if args.command == "resume":
            if args.round:
                _reactivate(project, pipe, state, args.round)
            return _print_resume(project, state)
        if args.command == "progress":
            if not args.item:
                raise ValueError("progress requires --item and --summary")
            return _cmd_progress(args, project, state)
        if args.command == "layout":
            return _cmd_layout(args, project, pipe, state)
        if args.command == "seal":
            return _seal_round(state, pipe, args.why or "")
        if args.command == "check":
            path, revision = _load_round(state)
            escalated = _classify_for_check(project, pipe, state, path, revision)
            if escalated is not None:
                return escalated
            return scoped.check_round(project, pipe, state, path, revision,
                                      quiet=args.quiet, summary=args.summary is True)
        if args.command == "refresh":
            path, revision = _load_round(state)
            if not scoped.is_scoped(revision) or revision.get("status") != "active":
                raise ValueError("refresh needs an active sealed scoped round")
            scoped.plan_scope(project, pipe, state, revision)
            revision.pop("validation", None)
            _write_round(path, revision)
            return _cmd_status(state)
        if args.command == "build":
            return _cmd_build(args, state)
        if args.command == "mark":
            if not args.item or not isinstance(args.summary, str):
                raise ValueError("mark requires --item and --summary")
            return _cmd_mark(args, project, state)
        if args.command == "close":
            if not isinstance(args.summary, str):
                raise ValueError("close requires --summary")
            return _cmd_close(args, state, pipe)
        if not args.kind or not args.why:
            raise ValueError(f"{args.command} requires --kind and --why")
        if len(args.why.strip()) < 20:
            raise ValueError("rework reason is too short; name the requested change and affected artifact")
        if args.command == "start":
            open_round = scoped.active(project)
            if scoped.is_scoped(open_round):
                raise ValueError(f"scoped round {open_round['round_id']} is open; finish it, or "
                                 "convert it while collecting with batch --rewind")
        current = state.current
        target = resolve_route(args.kind, current, pipe)
    except (FileNotFoundError, KeyError, ValueError, json.JSONDecodeError) as exc:
        print(f"rework route error: {exc}", file=sys.stderr)
        return 2
    if pipe.stage(target).index > pipe.stage(current).index:
        print(f"rework route error: {target} is ahead of current stage {current}", file=sys.stderr)
        return 2
    print(f"revision route: {args.kind}: {current} -> {target}")
    if args.command == "plan":
        return 0
    # `start`: the legacy single-kind full rewind (explicit fallback).
    tool = paths.tools_dir() / "wf.py"
    env = {**os.environ, "MEDPAPER_PROJECT": str(project),
           "MEDPAPER_ROOT": str(paths.repo_root()), "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.run(
        [sys.executable, str(tool), "loop", "--to", target, "--why",
         f"user-requested {args.kind} revision (full rewind): {args.why.strip()}"],
        text=True, env=env)
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
