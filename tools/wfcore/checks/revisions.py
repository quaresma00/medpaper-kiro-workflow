"""Gates for source-routed manuscript and submission-package revisions."""
from __future__ import annotations

import hashlib
import json

from . import Ctx, Result, check
from ..packagecontent import verify_baseline
from ..reviewpackage import verify as verify_review_package
from ..revision import DELETED, receipt_holds, renewable


def _sha256(path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@check("revision_rounds_closed")
def revision_rounds_closed(ctx: Ctx) -> Result:
    active = ctx.state.data.get("active_revision_round")
    if active:
        try:
            active_payload = json.loads(
                (ctx.state.dir / "revisions" / f"{active}.json").read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            return Result(False, "revision_rounds_closed", f"active round {active} is unreadable: {exc}")
        scoped = active_payload.get("schema_version") == 2
        # A legacy full-rewind round travels back through the stage gates; a scoped round
        # never leaves its review checkpoint, so it is never "in transit".
        if not scoped and active_payload.get("review_stage") != ctx.stage.id:
            return Result(
                True, "revision_rounds_closed",
                f"revision round {active} is in transit to {active_payload.get('review_stage')}",
            )
        return Result(
            False, "revision_rounds_closed", f"revision round {active} is still active",
            [
                "Run tools/rework.py status; complete every atomic item.",
                ("Then tools/rework.py check, mark each item and close." if scoped else
                 "At the review stage, mark final changed files/checks and run tools/rework.py close."),
            ],
        )
    directory = ctx.state.dir / "revisions"
    if not directory.exists():
        return Result(True, "revision_rounds_closed", "no revision rounds recorded")
    problems = []
    count = 0
    latest_receipts: dict[str, tuple[str, str, str]] = {}
    rounds = []
    for path in sorted(directory.glob("R*.json")):
        count += 1
        try:
            revision = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            problems.append(f"{path.name}: unreadable ({exc})")
            continue
        if revision.get("status") == "suspended":
            problems.append(f"{path.name}: suspended round must be resumed and closed "
                            f"(tools/rework.py resume --round {path.stem})")
            continue
        if revision.get("schema_version") not in {1, 2} or revision.get("status") != "complete":
            problems.append(f"{path.name}: not a completed schema-1/2 revision round")
            continue
        rounds.append((path, revision))
    # Scoped (schema-2) rounds also bind every file their checks certified. Only the newest
    # completed round's set is compared: a later round re-certifies (or rebuilds) them.
    latest_scoped = rounds[-1] if rounds and rounds[-1][1].get("schema_version") == 2 else None
    for path, revision in rounds:
        if revision.get("schema_version") == 2:
            proof = revision.get("validation", {})
            if not proof.get("ok") or not proof.get("input_signature") or not proof.get("results"):
                problems.append(f"{path.name}: no executed scoped-check evidence")
        items = revision.get("items")
        if not isinstance(items, list) or not items:
            problems.append(f"{path.name}: no revision items")
            continue
        for item in items:
            item_id = item.get("id", "unknown")
            if item.get("status") != "done" or not item.get("validated_by"):
                problems.append(f"{path.name}/{item_id}: not completed and validated")
                continue
            changed = item.get("changed_files")
            if not isinstance(changed, list) or not changed:
                problems.append(f"{path.name}/{item_id}: no changed-file proof")
                continue
            for receipt in changed:
                rel = receipt.get("path") if isinstance(receipt, dict) else None
                expected = receipt.get("sha256") if isinstance(receipt, dict) else None
                if not rel or not expected:
                    problems.append(f"{path.name}/{item_id}: malformed changed-file proof")
                    continue
                # A later completed revision may legitimately supersede the same source.
                # Keep every old receipt as history, but compare the working tree only with
                # the newest completed receipt for each path.
                if not renewable(str(rel)):
                    latest_receipts[str(rel)] = (path.name, str(item_id), receipt)
    if latest_scoped:
        path, revision = latest_scoped
        val = revision.get("validation", {})
        content = val.get("artifact_content", {})
        for rel, expected in val.get("artifact_hashes", {}).items():
            if not renewable(rel):
                latest_receipts[rel] = (path.name, "scoped validation",
                                        {"path": rel, "sha256": expected,
                                         "content_sha256": content.get(rel)})
        for rel in val.get("artifact_deleted", []):
            latest_receipts[rel] = (path.name, "scoped validation",
                                    {"path": rel, "sha256": DELETED, "deleted": True})
    # 1.9.0: every drifted file is listed at once (not the first few), and a credential holds
    # on visible content, so an identical rebuild with new container timestamps is not drift.
    missing, drifted, back = [], [], []
    for rel, (round_name, item_id, rec) in sorted(latest_receipts.items()):
        source = ctx.project / rel
        if rec.get("deleted") or rec.get("sha256") == DELETED:
            if source.exists():
                back.append(f"{rel} ({round_name})")
        elif not source.is_file():
            missing.append(f"{rel} ({round_name}/{item_id})")
        elif not receipt_holds(ctx.project, rec):
            drifted.append(f"{rel} ({round_name})")
    detail = problems[:8]
    if missing:
        detail.append(f"{len(missing)} changed source(s) missing: " + ", ".join(missing))
    if drifted:
        detail.append(f"{len(drifted)} changed source(s) drifted after latest closure: "
                      + ", ".join(drifted))
    if back:
        detail.append(f"{len(back)} deleted source(s) reappeared: " + ", ".join(back))
    if detail:
        return Result(False, "revision_rounds_closed", "; ".join(detail),
                      ["Open ONE round covering every file listed (rework.py batch), or restore them; "
                       "a deleted source is credited with rework.py mark --deleted-file."]
                      if drifted or missing or back else [])
    return Result(True, "revision_rounds_closed", f"{count} revision round(s) closed with source hashes and validations")


@check("manuscript_review_package_current")
def manuscript_review_package_current(ctx: Ctx) -> Result:
    ok, details, manifest = verify_review_package(ctx.project)
    if not ok or manifest is None:
        return Result(
            False,
            "manuscript_review_package_current",
            "; ".join(details[:8]),
            [
                "Return to S19 and run tools/manuscript/review_package.py build.",
                "Present the printed ZIP path and every review-material path to the user.",
            ],
        )
    return Result(
        True,
        "manuscript_review_package_current",
        f"S19 review ZIP v{manifest['package_revision']:03d} matches "
        f"{len(manifest['source_files'])} current review file(s)",
    )


@check("reader_review_coverage")
def reader_review_coverage(ctx: Ctx) -> Result:
    """S18: the independent review saw the exact current text, tables and rendered figures."""
    from .. import readerreview
    problems = readerreview.verify(ctx.project)
    if problems:
        return Result(
            False, "reader_review_coverage", "; ".join(problems[:6]),
            ["Print the evidence block and give the reviewer exactly those files, including "
             "every rendered figure PNG: .venv/Scripts/python.exe "
             "tools/review_round.py start --scope manuscript",
             "Paste the printed ```json block into the review report, and write the reviewer's "
             "'Reader comprehension' and 'Medical presentation' findings under those headings."],
        )
    n = len(readerreview.reader_inputs(ctx.project))
    return Result(True, "reader_review_coverage",
                  f"independent review is bound to {n} current file(s), rendered figures included")


@check("s19_review_release_explicit")
def s19_review_release_explicit(ctx: Ctx) -> Result:
    ok, details, manifest = verify_review_package(ctx.project)
    if not ok or manifest is None:
        return Result(
            False, "s19_review_release_explicit",
            "current S19 review ZIP is not valid: " + "; ".join(details[:6]),
            ["Build, verify and present the current S19 review ZIP before requesting approval."],
        )
    decision = ctx.state.decision("manuscript_human_reviewed")
    if not decision or decision.get("value") != "NO_FURTHER_REVIEW":
        return Result(
            False, "s19_review_release_explicit",
            "the user has not explicitly stated that no further review is needed for the current ZIP",
            [
                "Remain at S19 and invite the user or a third party to review the listed materials.",
                "Advance only after an explicit no-further-review statement; generic 'continue' is insufficient.",
            ],
        )
    package_token = str(manifest["package_id"])[:12]
    rationale = str(decision.get("rationale", ""))
    if package_token not in rationale:
        return Result(
            False, "s19_review_release_explicit",
            f"approval is not bound to current S19 review package {package_token}",
            ["Record the exact presented ZIP revision/package ID in the decision rationale."],
        )
    if str(decision.get("at", "")) < str(manifest.get("created_at", "")):
        return Result(
            False, "s19_review_release_explicit",
            "approval predates the current S19 review ZIP; present the new ZIP and ask again",
        )
    return Result(
        True, "s19_review_release_explicit",
        f"user explicitly ended review for S19 ZIP v{manifest['package_revision']:03d} "
        f"({package_token})",
    )


@check("review_round_approved")
def review_round_approved(ctx: Ctx) -> Result:
    """1.8.1 S19/S24: the latest subagent review round is closed, reported, answered with
    'no further review', bound to the approval decision, and nothing it covered changed since.

    A paper that reached S19 with a legacy (pre-1.8.1) review ZIP and no rounds keeps passing
    through the legacy package release check."""
    from .. import reviewrounds as rr
    scope = str(ctx.spec.get("scope", "manuscript"))
    cfg = rr.SCOPES[scope]
    if scope == "manuscript" and not rr.load(ctx.project)[scope] and \
            (ctx.project / "07_manuscript/review_packages/latest_review_package.json").is_file():
        legacy = s19_review_release_explicit(ctx)
        return Result(legacy.ok, "review_round_approved",
                      "legacy review package: " + legacy.detail, legacy.hints)
    if scope == "package" and not rr.load(ctx.project)[scope]:
        # Pre-1.8.1 S24: the user's OK plus the package freeze (verified by bundle_matches_freeze).
        decision = ctx.state.decision(cfg["decision"]) or {}
        frozen = (ctx.project / "08_submission/package_review_freeze.json").is_file()
        migrated = [m.get("at", "") for m in ctx.state.data.get("pipeline_migrations", [])
                    if str(m.get("to", "")) == "1.8.1"]
        if decision.get("value") == cfg["value"] and frozen and migrated and \
                str(decision.get("at", "")) < str(migrated[0]):
            return Result(True, "review_round_approved",
                          "legacy S24 confirmation (before 1.8.1 review rounds) with a package freeze")
    problems = rr.problems(ctx.project, scope, ctx.state.decision(cfg["decision"]))
    if problems:
        return Result(False, "review_round_approved", "; ".join(problems[:6]), [
            "One round: .venv/Scripts/python.exe tools/review_round.py start [--delta]; invoke "
            "the medpaper-reviewer subagent on the printed files; apply the fixes you judge "
            "improve the paper; review_round.py close --findings ... --change FILE \"...\"; "
            "report once; ask: another round or no further review?",
            "Record the answer: review_round.py decide another_round|no_further_review "
            "--words \"<user's words>\""])
    rnd = rr.latest(ctx.project, scope)
    return Result(True, "review_round_approved",
                  f"{len(rr.load(ctx.project)[scope])} review round(s); user ended review after "
                  f"{rnd['id']}; covered files unchanged since")


@check("package_content_matches_baseline")
def package_content_matches_baseline(ctx: Ctx) -> Result:
    ok, details, count = verify_baseline(ctx.project)
    if not ok:
        return Result(
            False,
            "package_content_matches_baseline",
            "; ".join(details[:8]),
            [
                "For content edits, run tools/rework.py and rebuild from the owning source stage.",
                "For format-only edits, restore the original visible text; recapture only at S23 after a legitimate rebuild.",
            ],
        )
    return Result(True, "package_content_matches_baseline",
                  details[0] if details else f"{count} DOCX visible-text baseline(s) match")

