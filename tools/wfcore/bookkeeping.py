"""1.22.0 (C2): a bookkeeping round at any stage - register, never edit.

Before 1.22.0 a certificate or hash mismatch outside S19/S24 (a certified file deleted, a
derived file renewed, a file replaced by an identical-in-fact version) had no compliant fix:
rework rounds open only at the review stages, so a project once copied the engine to patch it.

    rework.py bookkeep --why "..." [--deleted <path>] [--replaced <path>] [--renew <path>]

registers deletions, replacements and renewals of CERTIFIED files only (closed round, scientific
freeze or engine build receipt) and writes a closed, audited round (.wf/revisions/Rnnn.json,
kind "bookkeeping"). It refuses when the presentation/meaning classifier finds any fact or
meaning change; then a normal round (rework.py batch) is needed. No engine fork is ever needed
for a certificate or hash mismatch.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from . import revision as scoped

KIND = "bookkeeping"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Refused(ValueError):
    pass


def _freeze_entry(project: Path, rel: str) -> dict | None:
    from . import scifreeze
    try:
        if scifreeze.is_frozen(project):
            return scifreeze.load_freeze(project).get("files", {}).get(rel)
    except SystemExit:
        return None
    return None


def certified(project: Path, rel: str) -> dict | None:
    """The credential that certifies `rel` (round receipt, freeze entry or build receipt)."""
    rec = scoped.certified_receipts(project).get(rel)
    if rec:
        return {"source": f"round {rec[0]}", **rec[1]}
    entry = _freeze_entry(project, rel)
    if entry:
        return {"source": "scientific freeze", **entry}
    from . import rebuild
    for r in rebuild.receipts(project):
        if str(r.get("output")) == rel:
            return {"source": "build receipt", "sha256": r.get("output_sha256"), "derived": True}
    return None


def _science(rel: str) -> bool:
    from . import presentation
    return presentation.science_source(rel) or rel.startswith(("02_data/", "01_protocol/"))


def judge_replaced(project: Path, rel: str, cred: dict) -> str | None:
    """None = facts unchanged (presentation only); else why a normal round is needed."""
    from . import presentation
    if not (project / rel).is_file():
        return f"{rel} does not exist (use --deleted)"
    if scoped.build_receipt_current(project, rel):
        return None
    if _science(rel):
        return f"{rel} is an analysis/data/protocol source: a replacement is a science change"
    old = cred.get("facts")
    new = presentation.facts(project, rel)
    if old is None and new is None:
        return None  # a file that carries no reviewable facts (style, CSL, layout settings)
    if old is None:
        return (f"{rel}: no recorded facts to compare with, so the classifier cannot prove the "
                "replacement changed no fact")
    if not presentation.same_facts(new, old):
        return f"{rel}: numbers, citations or display references differ from the certified version"
    return None


def judge_deleted(project: Path, rel: str, cred: dict) -> str | None:
    if (project / rel).exists():
        return f"{rel} still exists; delete it first"
    if cred.get("source") == "scientific freeze" and cred.get("layer") != "presentation":
        return f"{rel} is part of the frozen scientific record: deleting it changes the science"
    if _science(rel):
        return f"{rel} is an analysis/data/protocol source: deleting it is a science change"
    return None


def judge_renew(project: Path, rel: str, cred: dict) -> str | None:
    if scoped.renewable(rel) or scoped.build_receipt_current(project, rel):
        return None
    return (f"{rel} is not a derived file with a current build receipt (rebuild it with "
            "wf rebuild first, or use a normal round)")


def run(project: Path, state, why: str, deleted: list[str], replaced: list[str],
        renew: list[str]) -> tuple[str, list[str]]:
    project = Path(project)
    why = str(why or "").strip()
    if len(why) < 10:
        raise Refused("--why 需写明登记原因（>= 10 个字符）")
    if state.data.get("active_revision_round"):
        raise Refused(f"修订轮 {state.data['active_revision_round']} 正在进行：在该轮内用 "
                      "rework.py mark 登记（--deleted-file / --changed-file）")
    todo = [("deleted", r) for r in deleted] + [("replaced", r) for r in replaced] + \
        [("renew", r) for r in renew]
    if not todo:
        raise Refused("bookkeep 需要至少一个 --deleted / --replaced / --renew")
    items, refused = [], []
    for kind, raw in todo:
        rel = Path(str(raw).replace("\\", "/")).as_posix()
        if Path(rel).is_absolute() or ".." in Path(rel).parts:
            raise Refused(f"不安全的路径：{raw}")
        cred = certified(project, rel)
        if cred is None:
            refused.append(f"{rel}: 不是受认证文件（没有修订轮证书、科学冻结记录或构建回执），无需登记")
            continue
        why_not = {"deleted": judge_deleted, "replaced": judge_replaced,
                   "renew": judge_renew}[kind](project, rel, cred)
        if why_not:
            refused.append(why_not)
            continue
        rec = ({"path": rel, "sha256": scoped.DELETED, "deleted": True} if kind == "deleted"
               else scoped.receipt(project, rel))
        items.append((kind, rel, cred, rec))
    if refused:
        raise Refused("拒绝登记（分类器发现事实或含义变化，或文件不在认证范围内；请改用正常修订轮 "
                      "rework.py batch --plan ...）：\n  " + "\n  ".join(refused))
    directory = project / ".wf" / "revisions"
    nums = [int(p.stem[1:]) for p in directory.glob("R*.json") if p.stem[1:].isdigit()] \
        if directory.is_dir() else []
    rid = f"R{max(nums, default=0) + 1:03d}"
    sig = hashlib.sha256(json.dumps([r for *_x, r in items], sort_keys=True).encode()).hexdigest()
    payload = {
        "schema_version": scoped.SCHEMA, "round_id": rid, "kind": KIND, "status": "complete",
        "review_stage": state.current, "origin_stage": state.current, "created_at": _now(),
        "completed_at": _now(), "completion_summary": why,
        "items": [{"id": f"{rid}-{i:02d}", "kind": KIND, "request": f"{kind}: {rel}",
                   "owning_stage": state.current, "change_type": "bookkeeping",
                   "affected_sources": [rel], "status": "done",
                   "resolution": f"{kind} of a certified file ({cred.get('source')}); {why}",
                   "changed_files": [rec],
                   "validated_by": ["bookkeeping classifier: no fact or meaning change"],
                   "completed_at": _now()}
                  for i, (kind, rel, cred, rec) in enumerate(items, 1)],
        "validation": {"ok": True, "input_signature": f"bookkeeping:{sig}", "checked_at": _now(),
                       "results": [{"check": "bookkeeping_classifier", "ok": True,
                                    "detail": f"{len(items)} file(s): no fact or meaning change",
                                    "severity": "block"}],
                       "artifact_hashes": {}, "artifact_deleted": []},
        "allowed_files": [rel for _k, rel, _c, _r in items],
    }
    scoped.atomic_json(scoped.round_path(project, rid), payload)
    state.event("bookkeeping_round", f"{rid}: " + ", ".join(f"{k} {r}" for k, r, _c, _x in items)
                + f" - {why}")
    state.save()
    scoped.drop_receipts(state)
    lines = [f"已登记 {rid}（记录轮，仅登记、不改内容）：{len(items)} 个文件"]
    lines += [f"  - {k}: {r}（原认证：{c.get('source')}）" for k, r, c, _x in items]
    return rid, lines
