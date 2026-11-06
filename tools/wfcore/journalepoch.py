"""1.17.0 (J1-J3): journal epochs - one target journal per epoch, nothing carried over silently.

Before 1.17.0 a journal switch after a rejection kept the previous journal's audits (the first
S25 audit of the new journal became a re-check of the old findings), review rounds, handoff
notes, helper scripts, CSL files outside 08_submission/ and, when the agent edited the S20 files
in place, the whole old submission tree. Now:

    wf journal switch --to "<new>" --confirm-old "<old>" --why "..." [--outcome rejected]

records .wf/journal_history.json (epoch, journal, outcome, dates), loops to S20, archives the
submission tree (scifreeze.reset_journal) and the journal layer of .wf/ into ONE archive folder
under 08_submission/journal_archives/, groups package review rounds by epoch, marks the old
S20+ handoff notes, carries the journal-independent facts (study design, data source, ethics/
consent/data-availability assessment, the author's AI-use answer, author list) and adopts the
current engine's gate set for S20-S25. Gates then require a fresh guideline snapshot, a variant
and target_journal.json stamped with the epoch and no file older than the epoch start
(checks/v1170.py journal_layer_clean). Archive paths are printed once, in the switch summary;
`wf journal shortlist` and `wf journal restore` read the archive themselves.
"""
from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

HISTORY = ".wf/journal_history.json"
JOURNAL_STAGES = ("S20_journal", "S21_authors", "S22_polish", "S23_package",
                  "S24_package_human_review", "S25_submission_audit")
OUTCOMES = ("rejected", "withdrawn", "other")
ARCHIVE_DIR = "08_submission/journal_archives"
TARGET = "08_submission/target_journal.json"
RESTART = "请关闭本对话，新开一个对话，输入“继续 medpaper”"
TS = "%Y-%m-%dT%H:%M:%SZ"
_STAMP_RE = re.compile(r"-(\d{8}T\d{6}Z)(?:-\d+)?$")


class SwitchError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).strftime(TS)


def seconds(stamp) -> float | None:
    """UTC timestamp (state format, archive stamp or plain date) -> POSIX seconds."""
    s = str(stamp or "").strip()
    for fmt, cut in ((TS, None), ("%Y%m%dT%H%M%SZ", None), ("%Y-%m-%dT%H:%M:%S", None),
                     ("%Y-%m-%d", 10)):
        try:
            return datetime.strptime(s[:cut] if cut else s, fmt).replace(
                tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue
    return None


def norm(name: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", " ", str(name or "").casefold()).strip()


def _json(path: Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def load(project: Path) -> dict:
    data = _json(Path(project) / HISTORY)
    data.setdefault("schema", 1)
    if not isinstance(data.get("epochs"), list):
        data["epochs"] = []
    return data


def _save(project: Path, data: dict) -> None:
    path = Path(project) / HISTORY
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def current(project: Path) -> dict:
    eps = load(project)["epochs"]
    return eps[-1] if eps else {}


def number(project: Path) -> int:
    try:
        return int(current(project).get("epoch") or 1)
    except (TypeError, ValueError):
        return 1


def target_name(project: Path) -> str:
    return str(_json(Path(project) / TARGET).get("journal", "") or "").strip()


def _archive_stamps(project: Path) -> list[float]:
    root = Path(project) / ARCHIVE_DIR
    out = []
    for d in (root.iterdir() if root.is_dir() else []):
        m = _STAMP_RE.search(d.name)
        t = seconds(m.group(1)) if m else None
        if d.is_dir() and t is not None:
            out.append(t)
    return out


def started_at(project: Path) -> float | None:
    """Start of the current journal epoch; papers that switched before 1.17.0 (archives but
    no history) use the newest archive stamp. None = first journal, nothing to compare."""
    cur = current(project)
    if cur.get("started_at") and int(cur.get("epoch") or 1) > 1:
        return seconds(cur["started_at"])
    stamps = _archive_stamps(project)
    return max(stamps) if stamps else None


def banner(project: Path) -> str | None:
    """First line of `wf status` / `wf handoff` once a journal is in play."""
    cur = current(project)
    name = target_name(project) or str(cur.get("journal", ""))
    if not name and not cur:
        return None
    return (f"journal epoch {number(project)}: {name or '(not chosen yet)'} - do not reuse rules "
            "of earlier journals")


def archive_of(project: Path, epoch: int | None = None) -> Path | None:
    """The archive folder of a previous epoch (engine-internal; never printed)."""
    eps = load(project)["epochs"]
    for e in reversed(eps):
        if e.get("archive") and (epoch is None or int(e.get("epoch", 0)) == epoch):
            p = Path(project) / e["archive"]
            return p if p.is_dir() else None
    return None


# ------------------------------------------------------------------ restore candidates
def _restore_items(project: Path) -> list[dict]:
    """Display moves and presentation-layer edits the previous journal caused."""
    from . import scifreeze
    items = []
    moves = _json(Path(project) / "08_submission/display_reallocation.json").get("moves") or []
    for m in moves if isinstance(moves, list) else []:
        if isinstance(m, dict) and m.get("id"):
            items.append({"kind": "display_move", "id": str(m["id"]), "to": str(m.get("to", "")),
                          "new_id": str(m.get("new_id", "")), "why": str(m.get("why", ""))[:200]})
    try:
        frozen = scifreeze.load_freeze(Path(project)).get("files", {})
    except SystemExit:
        frozen = {}
    for rel in scifreeze.PRESENTATION_LAYER:
        meta, p = frozen.get(rel) or {}, Path(project) / rel
        if meta.get("sha256") and p.is_file() and scifreeze._sha256(p) != meta["sha256"]:
            items.append({"kind": "presentation_edit", "file": rel})
    return items


def restore_pending(project: Path) -> list[str]:
    """Problems for journal_layer_clean: the one restore question unanswered or not applied."""
    from . import scifreeze
    cur = current(project)
    rec = cur.get("restore") or {}
    items = rec.get("items") or []
    if int(cur.get("epoch") or 1) < 2 or not items:
        return []
    if not rec.get("answer"):
        return [f"{len(items)} display/presentation change(s) made for the previous journal: ask "
                "the user ONCE whether to restore them, then `wf journal restore --answer "
                "restore|keep --why \"<the user's answer>\"`"]
    if rec["answer"] != "restore":
        return []
    out = []
    plan = _json(Path(project) / "01_protocol/artifact_plan.json")
    main_ids = {str(e.get("id")) for g in ("main_figures", "main_tables")
                for e in plan.get(g, []) or [] if isinstance(e, dict)}
    try:
        frozen = scifreeze.load_freeze(Path(project)).get("files", {})
    except SystemExit:
        frozen = {}
    for it in items:
        if it["kind"] == "display_move" and it["id"] not in main_ids:
            out.append(f"restore answered but {it['id']} is not back in the main displays")
        if it["kind"] == "presentation_edit":
            meta, p = frozen.get(it["file"]) or {}, Path(project) / it["file"]
            if p.is_file() and meta.get("sha256") and scifreeze._sha256(p) != meta["sha256"]:
                out.append(f"restore answered but {it['file']} still differs from the S19 wording")
    return out


def restore(project: Path, answer: str, why: str) -> list[str]:
    data = load(project)
    if not data["epochs"] or int(data["epochs"][-1].get("epoch") or 1) < 2:
        raise SwitchError("没有换刊记录；restore 只在 `wf journal switch` 之后使用")
    cur = data["epochs"][-1]
    rec = cur.setdefault("restore", {"items": [], "answer": None})
    if rec.get("answer"):
        raise SwitchError(f"已记录过用户的答复（{rec['answer']}，{rec.get('at')}）；只问一次")
    if answer not in ("restore", "keep"):
        raise SwitchError("--answer 只能是 restore 或 keep")
    if len(str(why).strip()) < 4:
        raise SwitchError("--why 写用户的原话")
    rec.update(answer=answer, why=str(why).strip(), at=_now())
    _save(project, data)
    lines = [f"已记录：{'恢复' if answer == 'restore' else '保持现状'}（{len(rec['items'])} 项）"]
    if answer == "restore":
        for it in rec["items"]:
            if it["kind"] == "display_move":
                lines.append(f"  - {it['id']} 移回正文：rework.py layout --source "
                             f"01_protocol/artifact_plan.json --why \"换刊后恢复 {it['id']}\"")
            else:
                lines.append(f"  - {it['file']}：改回 S19 冻结时的写法（展示层，事实不变）")
    return lines


def shortlist(project: Path) -> str:
    """The previous epochs' reject-fallback ladder, read from the archive by the engine."""
    out = []
    for e in load(project)["epochs"]:
        arch = Path(project) / e["archive"] if e.get("archive") else None
        f = arch / "journal_shortlist.md" if arch else None
        if not f or not f.is_file():
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"(?ims)^#{1,6}\s*Reject-fallback cascade\s*$(.*?)(?=^#{1,6}\s|\Z)", text)
        m2 = re.search(r"(?ims)^#{1,6}\s*Shortlist\s*$(.*?)(?=^#{1,6}\s|\Z)", text)
        body = "\n".join(x.group(1).strip() for x in (m2, m) if x)
        out.append(f"## epoch {e.get('epoch')}（{e.get('journal')}，{e.get('outcome') or '-'}）\n"
                   + (body or text[:3000]).strip())
    if not out:
        return "没有已归档的期刊短名单"
    return ("以下为旧期刊阶段的短名单与拒稿后备梯队，仅作为 S20 的起点；每个候选的 SCIE/JCR/诚信"
            "状态与投稿指南都必须用本 epoch 的新证据重新核实。\n\n" + "\n\n".join(out))


# ------------------------------------------------------------------ the switch
def _move(src: Path, dest: Path) -> bool:
    if not src.exists():
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    return True


def _carry_declarations(project: Path, archive: Path, old_epoch: int, old: str) -> list[str]:
    src = archive / "declarations_assessment.json"
    data = _json(src)
    if not data:
        return []
    ai = data.get("ai_use")
    if isinstance(ai, dict):
        ai.pop("journal_rule", None)  # journal-specific wording: regenerated from the new guide
    data["carried_from"] = {"epoch": old_epoch, "journal": old, "at": _now()}
    dest = Path(project) / "08_submission/declarations_assessment.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    out = ["伦理/知情同意/数据可用性评估" + (f"（作者已答 {len(data.get('answers') or {})} 项）"
                                       if data.get("answers") else "")]
    if isinstance(ai, dict) and "used" in ai:
        out.append("作者的 AI 使用答复（" + ("使用：" + str(ai.get("tool")) if ai.get("used")
                                          else "未使用") + "）")
    return out


def _wf_layer(project: Path, archive: Path, since: float | None, epoch: int,
              journal: str) -> list[str]:
    """Move the journal layer of .wf/ and stray CSL files into the archive."""
    project = Path(project)
    moved = []
    wfa = archive / "_wf"
    if _move(project / ".wf/audits", wfa / "audits"):
        moved.append(".wf/audits/")
    for sub in (".wf/review_bundle", ".wf/review_reports"):
        root = project / sub
        for p in sorted(root.iterdir()) if root.is_dir() else []:
            if p.name[:1] in ("A", "P") and _move(p, wfa / sub[4:] / p.name):
                moved.append(f"{sub}/{p.name}")
    scripts = project / ".wf/scripts"
    for p in sorted(scripts.rglob("*")) if scripts.is_dir() else []:
        if p.is_file() and (since is None or p.stat().st_mtime >= since - 1):
            if _move(p, wfa / "scripts" / p.relative_to(scripts)):
                moved.append(f".wf/scripts/{p.relative_to(scripts).as_posix()}")
    pats = ["*.csl", "06_refs/**/*.csl", "07_manuscript/*.csl", "temp/**/*.csl"]
    for pat in pats:
        for p in sorted(project.glob(pat)):
            rel = p.relative_to(project).as_posix()
            if p.is_file() and _move(p, archive / "_outside" / rel):
                moved.append(rel)
    from . import reviewrounds as rr
    data = rr.load(project)
    if data.get("package"):
        data.setdefault("package_epochs", []).append(
            {"epoch": epoch, "journal": journal, "archived_at": _now(), "rounds": data["package"]})
        data["package"] = []
        rr._save(project, data)
        moved.append(".wf/review_rounds.json package rounds (grouped by epoch)")
    return moved


def switch(project: Path, pipe, st, to: str, confirm_old: str, why: str,
           outcome: str = "rejected") -> list[str]:
    """Archive the whole journal layer, loop to S20 and start a new journal epoch."""
    from . import revision, scifreeze
    project = Path(project)
    to, why = str(to or "").strip(), str(why or "").strip()
    if outcome not in OUTCOMES:
        raise SwitchError(f"--outcome 只能是 {'|'.join(OUTCOMES)}")
    if len(why) < 10:
        raise SwitchError("--why 需写明换刊原因（>= 10 个字符）")
    s20 = pipe.stage("S20_journal")
    cur_stage = pipe.stage(st.current)
    if cur_stage.index < s20.index:
        raise SwitchError(f"当前在 {cur_stage.id}：换刊只在 S20 及之后使用；S20 之前直接选刊即可")
    old = target_name(project) or str(scifreeze.variant_meta(project).get("journal", "")).strip() \
        or str(current(project).get("journal", ""))
    if not old:
        raise SwitchError("还没有已选定的期刊（target_journal.json 无 journal）；在 S20 直接选刊即可")
    if norm(confirm_old) != norm(old):
        raise SwitchError(f"--confirm-old 与当前期刊不符：当前期刊是“{old}”")
    if not to or norm(to) == norm(old):
        raise SwitchError("--to 必须是另一本期刊")
    open_round = revision.active(project)
    if revision.is_scoped(open_round):
        raise SwitchError(f"修订轮 {open_round.get('round_id')} 尚未关闭；先关闭它再换刊")
    if not scifreeze.is_frozen(project):
        raise SwitchError("没有 S19 科学冻结记录，无法安全换刊（先完成 S19）")
    ok, problems, _ = scifreeze.verify_freeze(project)
    if not ok:
        raise SwitchError("冻结的科学内容已变动，拒绝换刊：" + "; ".join(problems[:4]))

    now = _now()
    data = load(project)
    if not data["epochs"]:
        first = (st.stage_info("S20_journal").get("started_at")
                 or scifreeze.variant_meta(project).get("opened_at") or "")
        data["epochs"].append({"epoch": 1, "journal": old, "started_at": first})
    prev = data["epochs"][-1]
    old_no = int(prev.get("epoch") or 1)
    new_no = old_no + 1
    items = _restore_items(project)
    archive = scifreeze.new_archive_dir(project)
    rel_archive = archive.relative_to(project).as_posix()
    engine = str(pipe.meta.get("version"))

    # 1) loop to S20 (same bookkeeping as `wf loop`)
    st.add_note(f"[JOURNAL SWITCH] {old} -> {to} ({outcome}): {why}", cur_stage.id)
    reset_ids = [s20.id, *[s.id for s in pipe.stages_after(s20.id)]]
    st.reset_forward(reset_ids[1:])
    st.clear_decisions_for(reset_ids)
    st.rewind(s20.id, f"journal switch {old} -> {to}: {why}")
    # 2) submission tree, then the journal layer of .wf/ and stray CSL files
    removed = scifreeze.reset_journal(project, archive=archive)
    since = seconds(prev.get("started_at")) if prev.get("started_at") else None
    moved = _wf_layer(project, archive, since, old_no, old)
    # 3) old S20+ handoff notes no longer count for the new epoch
    marked = 0
    for h in st.data.get("handoff", []):
        if h.get("stage") in JOURNAL_STAGES and not h.get("journal_epoch_superseded"):
            h["journal_epoch_superseded"] = old_no
            marked += 1
    with st.handoff_file.open("a", encoding="utf-8") as fh:
        fh.write(f"\n## journal epoch {new_no} started {now}: {to}\n\nS20-S25 notes above belong "
                 f"to epoch {old_no} ({old}); do not reuse its rules.\n")
    # 4) carry the journal-independent facts; stamp the new epoch
    carried = _carry_declarations(project, archive, old_no, old)
    if (project / "00_input/author_info.json").is_file():
        carried.append("作者名单与单位（00_input/author_info.json）")
    if (project / "01_protocol/idea.json").is_file():
        carried.append("研究设计与数据来源（01_protocol/idea.json）")
    tj = project / TARGET
    tj.parent.mkdir(parents=True, exist_ok=True)
    tj.write_text(json.dumps({"journal": to, "journal_epoch": new_no}, indent=2,
                             ensure_ascii=False) + "\n", encoding="utf-8")
    prev.update(ended_at=now, outcome=outcome, why=why, archive=rel_archive)
    data["epochs"].append({"epoch": new_no, "journal": to, "started_at": now, "previous": old,
                           "gate_set": engine, "carried": carried,
                           "restore": {"items": items, "answer": None}})
    _save(project, data)
    st.data["journal_gate_pin"] = {"version": engine, "stages": list(JOURNAL_STAGES),
                                   "epoch": new_no, "at": now}
    st.event("journal_switch", f"epoch {old_no} {old} ({outcome}) -> epoch {new_no} {to}: {why}")
    st.event("journal_gate_set_adopted",
             f"epoch {new_no}: S20-S25 use the engine {engine} gate set; completed science "
             f"stages keep the paper's pin {st.engine_pin}")
    st.save()

    lines = [f"已换刊：{old} -> {to}（期刊 epoch {new_no}；旧刊结果：{outcome}）",
             f"旧期刊资料已归档于：{rel_archive}/（含投稿包、指南快照、S25 审计、包审阅轮次、"
             f"辅助脚本和 CSL；共 {len(removed) + len(moved)} 项）。之后的命令不再显示这个路径。",
             f"S20-S25 采用当前引擎 {engine} 的门禁（已记录为事件）；已完成的科学阶段保持原门禁。",
             f"旧的 S20+ 交接记录已标记为 epoch {old_no}（{marked} 条），新 S20 需要新的交接记录。",
             "新期刊的投稿要求清单（08_submission/guideline_requirements.json）和合规矩阵必须根据"
             "新期刊自己的 guidelines_source.txt 逐条重新建立；旧刊的清单、矩阵和证据已随旧资料"
             "归档，不得沿用。"]
    if carried:
        lines.append("沿用、不再询问：" + "；".join(carried) + "。只重写与期刊有关的措辞。")
    if items:
        lines.append(f"旧期刊做过的展示调整 {len(items)} 项（问用户一次是否恢复，然后 `wf journal "
                     "restore --answer restore|keep --why \"用户原话\"`）：")
        lines += [f"  - {it['id']} -> {it['to'] or 'supplementary'}" if it["kind"] == "display_move"
                  else f"  - {it['file']} 的期刊阶段改动" for it in items]
    lines += ["旧刊短名单/后备梯队：`wf journal shortlist`（只作起点，须用新证据重新核实）。",
              "新对话中：wf status -> wf journal lookup --issn <ISSN> -> 被拦截时 wf guidelines "
              "ingest --from <文件> --url <官方URL> -> 写 S20 文件（含要求清单）-> open-variant "
              "-> wf rebuild",
              RESTART]
    return lines
