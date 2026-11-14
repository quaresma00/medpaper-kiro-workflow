"""1.26.0: the run record - where a paper's time and credits go.

Every retrospective so far had to estimate from memory how long each stage took, how often the
gates failed, how many subagent calls, reproductions and rebuilds ran and how long the run sat
waiting for the user. Engine commands now append one line each to <paper>/.wf/run_ledger.jsonl
(time, stage, kind, a few fields) and `wf report` turns it into one table per stage
(.wf/run_report.md). The record only observes: it never changes a paper file, never affects a
gate and never fails a command.
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REL = ".wf/run_ledger.jsonl"
REPORT_REL = ".wf/run_report.md"
IDLE_MINUTES = 15
_FMT = "%Y-%m-%dT%H:%M:%SZ"


def _now() -> str:
    return datetime.now(timezone.utc).strftime(_FMT)


def _ts(stamp) -> float | None:
    try:
        return datetime.strptime(str(stamp), _FMT).replace(tzinfo=timezone.utc).timestamp()
    except (TypeError, ValueError):
        return None


def _state(project: Path) -> dict:
    try:
        data = json.loads((Path(project) / ".wf/state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def log(project, kind: str, **fields) -> None:
    """Append one record; silently does nothing outside a paper or on any error."""
    try:
        project = Path(project)
        st = _state(project)
        if not st:
            return
        rec = {"at": _now(), "stage": fields.pop("stage", None) or st.get("current") or "",
               "kind": kind}
        rec.update({k: v for k, v in fields.items() if v is not None})
        path = project / REL
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 - the record never breaks a command
        pass


def entries(project) -> list[dict]:
    path = Path(project) / REL
    out = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict) and _ts(rec.get("at")) is not None:
            out.append(rec)
    return sorted(out, key=lambda r: _ts(r["at"]))


def _dur(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    minutes = int(round(seconds / 60))
    if minutes < 60:
        return f"{minutes} 分钟"
    return f"{minutes // 60} 小时 {minutes % 60:02d} 分"


def _stage_order(project: Path) -> list[str]:
    try:
        from . import registry
        return [s.id for s in registry.load().stages]
    except Exception:  # noqa: BLE001
        return sorted((_state(project).get("stages") or {}).keys())


def summary(project) -> dict:
    """Per-stage numbers from state.json, the ledger and the review rounds."""
    project = Path(project)
    st = _state(project)
    stages = st.get("stages") or {}
    led = entries(project)
    per: dict[str, dict] = {}

    def row(sid: str) -> dict:
        return per.setdefault(sid, {"wall": None, "idle": 0.0, "checks": 0, "red": 0,
                                    "failing": Counter(), "subagents": Counter(), "repro": 0,
                                    "repro_s": 0.0, "rebuilds": 0, "cmd_s": 0.0})
    now = datetime.now(timezone.utc).timestamp()
    for sid, info in stages.items():
        if not isinstance(info, dict):
            continue
        a = _ts(info.get("started_at"))
        b = _ts(info.get("completed_at")) or (now if info.get("status") == "active" else None)
        if a is not None and b is not None and b >= a:
            row(sid)["wall"] = b - a
    for prev, rec in zip([None] + led[:-1], led):
        r = row(str(rec.get("stage") or "?"))
        if prev is not None:
            gap = _ts(rec["at"]) - _ts(prev["at"])
            if gap > IDLE_MINUTES * 60:  # charged to the stage where the run stopped
                row(str(prev.get("stage") or "?"))["idle"] += gap
        kind = rec.get("kind")
        if kind == "check":
            r["checks"] += 1
            if int(rec.get("blocking") or 0):
                r["red"] += 1
                r["failing"].update(rec.get("failing") or [])
        elif kind == "subagent":
            r["subagents"][str(rec.get("agent") or "subagent")] += 1
        elif kind == "reproduce":
            r["repro"] += 1
            r["repro_s"] += float(rec.get("seconds") or 0)
        elif kind == "cmd":
            r["cmd_s"] += float(rec.get("seconds") or 0)
            if str(rec.get("name", "")).startswith("wf rebuild"):
                r["rebuilds"] += 1
    rounds = {}
    waits = 0.0
    try:
        from . import reviewrounds as rr
        data = rr.load(project)
        for scope in rr.SCOPES:
            rounds[scope] = len(data[scope])
            for r in data[scope]:
                a, b = _ts(r.get("closed_at")), _ts(r.get("decided_at"))
                if a is not None and b is not None and b > a:
                    waits += b - a
    except Exception:  # noqa: BLE001
        pass
    deep = len(list((project / "06_refs/deepread").glob("*.md"))) if \
        (project / "06_refs/deepread").is_dir() else 0
    return {"per": per, "rounds": rounds, "round_waits": waits, "deepread_notes": deep,
            "ledger": len(led), "first": led[0]["at"] if led else None}


def report(project, write: bool = True) -> list[str]:
    """The Chinese table for the user (also written to .wf/run_report.md)."""
    project = Path(project)
    s = summary(project)
    per = s["per"]
    order = [sid for sid in _stage_order(project) if sid in per] + sorted(
        sid for sid in per if sid not in _stage_order(project))
    names = {"medpaper-reviewer": "审稿", "medpaper-clinical-writer": "写作",
             "medpaper-medical-editor": "编辑", "medpaper-deepreader": "精读"}
    lines = ["# 运行记录（wf report）", "",
             "| 阶段 | 用时 | 无命令空档 | 检查（红） | 常见失败 | 子代理 | 复现 | 重建 |",
             "|---|---|---|---|---|---|---|---|"]
    tot = Counter()
    for sid in order:
        r = per[sid]
        fail = "、".join(f"{k}×{v}" for k, v in r["failing"].most_common(2)) or "-"
        subs = "、".join(f"{names.get(k, k)}{v}" for k, v in r["subagents"].items()) or "-"
        repro = f"{r['repro']}（{_dur(r['repro_s'])}）" if r["repro"] else "-"
        lines.append(f"| {sid} | {_dur(r['wall'])} | {_dur(r['idle']) if r['idle'] else '-'} | "
                     f"{r['checks']}（{r['red']}） | {fail} | {subs} | {repro} | "
                     f"{r['rebuilds'] or '-'} |")
        tot["wall"] += r["wall"] or 0
        tot["idle"] += r["idle"]
        tot["checks"] += r["checks"]
        tot["red"] += r["red"]
        tot["subagents"] += sum(r["subagents"].values())
        tot["repro"] += r["repro"]
        tot["rebuilds"] += r["rebuilds"]
    rnd = s["rounds"]
    lines += ["", f"合计：用时 {_dur(tot['wall'])}，其中无引擎命令的空档 {_dur(tot['idle'])}"
              f"（超过 {IDLE_MINUTES} 分钟的间隔，多为等待您回复或等待额度恢复，也可能是长段写作）；"
              f"检查 {tot['checks']} 次（红 {tot['red']} 次）；子代理调用 {tot['subagents']} 次；"
              f"复现 {tot['repro']} 次；重建 {tot['rebuilds']} 次。",
              f"审阅轮次：写作前科学审阅 {rnd.get('science', 0)} 轮，稿件 {rnd.get('manuscript', 0)} 轮，"
              f"投稿包 {rnd.get('package', 0)} 轮；轮次结束到您答复，合计 {_dur(s['round_waits'])}。"
              f"精读笔记 {s['deepread_notes']} 篇。",
              "", f"来源：阶段时间取自 .wf/state.json；审阅轮次取自 .wf/review_rounds.json；其余取自 "
              f"{REL}（1.26.0 起记录，{s['ledger']} 条" + (f"，最早 {s['first']}" if s["first"] else "")
              + "）。更早的阶段只有用时。"]
    if write:
        try:
            out = project / REPORT_REL
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError:
            pass
    return lines
