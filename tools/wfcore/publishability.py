"""1.23.0 (S1): publishability checkpoints at S02, S04 and S06.

    wf publishability record --stage S02 --verdict GO --article-type original_article \
        --evidence <file.json>             (or --count METRIC=VALUE --design KEY at S04)
    wf publishability answer --stage S04 --choice continue|change|stop --words "<user>"
    wf publishability value --analysis "<name>" --could-change "<conclusion>" \
        --cost "<rough cost>" --benefit low|medium|high
    wf publishability show

Each checkpoint stores a verdict (GO | CONDITIONAL | NO-GO), the best achievable article type
and its evidence in .wf/publishability.json, and prints a few Chinese lines for the user at
once. GO continues without a question; CONDITIONAL and NO-GO stop and ask ONE question with a
recommendation (continue as is / change angle or article type / stop). S04 compares the actual
counts with the design-specific floors in reference/publishability.toml (a GO with a count
below a required floor is refused). S04 and S06 checkpoints are bound to the data summary and
the results they judged: a later change makes them stale.
"""
from __future__ import annotations

import hashlib
import json
import tomllib
from datetime import datetime, timezone
from pathlib import Path

REL = ".wf/publishability.json"
STAGES = {"S02": "S02_feasibility", "S04": "S04_data", "S06": "S06_protocol_final"}
VERDICTS = ("GO", "CONDITIONAL", "NO-GO")
ARTICLE_TYPES = ("original_article", "brief_report", "research_letter", "not_publishable")
ARTICLE_ZH = {"original_article": "原创论著（original article）",
              "brief_report": "简报/短篇（brief report / short communication）",
              "research_letter": "研究快报（research letter）",
              "not_publishable": "不宜发表"}
CHOICES = ("continue", "change", "stop")
CHOICE_ZH = {"continue": "按现状继续", "change": "调整角度或文章类型", "stop": "停止"}
BENEFITS = ("low", "medium", "high")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def thresholds() -> dict:
    from . import paths
    with open(paths.repo_root() / "reference/publishability.toml", "rb") as fh:
        return tomllib.load(fh).get("design", {})


def load(project: Path) -> dict:
    try:
        data = json.loads((Path(project) / REL).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("schema", 1)
    data.setdefault("checkpoints", {})
    data.setdefault("additional", [])
    return data


def _save(project: Path, data: dict) -> None:
    p = Path(project) / REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def bound_inputs(project: Path, stage: str) -> str:
    """What a checkpoint judged: S04 the dataset summary, S06 every results JSON."""
    project = Path(project)
    if stage == "S04":
        files = [project / "03_analysis/results/dataset_summary.json"]
    elif stage == "S06":
        files = sorted((project / "03_analysis/results").glob("*.json"))
    else:
        return ""
    h = hashlib.sha256()
    for f in files:
        if f.is_file():
            h.update(f.name.encode() + b"\0" + hashlib.sha256(f.read_bytes()).digest())
    return h.hexdigest()


def _text(v, n: int = 15) -> bool:
    return isinstance(v, str) and len(v.strip()) >= n


def evidence_problems(stage: str, ev: dict) -> list[str]:
    """What the evidence for this checkpoint lacks ([] = complete)."""
    out = []
    if stage == "S02":
        nov = ev.get("novelty") if isinstance(ev.get("novelty"), dict) else {}
        if not _text(nov.get("query"), 5):
            out.append("novelty.query: the PubMed search (same exposure + outcome + data-source "
                       "family or design)")
        if not isinstance(nov.get("count"), int) or nov.get("count") < 0:
            out.append("novelty.count: number of matching papers of the last 10 years")
        closest = nov.get("closest") or []
        if isinstance(nov.get("count"), int) and nov.get("count") > 0 and not (
                isinstance(closest, list) and closest
                and all(isinstance(c, dict) and c.get("pmid") and c.get("title") for c in closest)):
            out.append("novelty.closest: the closest papers (pmid, title, year; titles/abstracts "
                       "only)")
        for k in ("data_sufficiency", "contribution"):
            if not _text(ev.get(k)):
                out.append(f"{k}: one or two sentences")
    elif stage == "S04":
        if not ev.get("design"):
            out.append("design: a key of reference/publishability.toml")
        if not isinstance(ev.get("counts"), dict) or not ev["counts"]:
            out.append("counts: the actual counts (METRIC=VALUE)")
    elif stage == "S06":
        for k in ("precision", "duplication", "robustness"):
            if not _text(ev.get(k)):
                out.append(f"{k}: one or two sentences on the main results")
    return out


def compare_counts(design: str, counts: dict) -> tuple[list[dict], list[str]]:
    """S04: each floor of the design against the recorded count."""
    table = thresholds()
    if design not in table:
        return [], [f"unknown design '{design}' (known: {', '.join(sorted(table))})"]
    rows, probs = [], []
    for t in table[design].get("threshold", []):
        m = t["metric"]
        val = counts.get(m)
        req = bool(t.get("required", True))
        if not isinstance(val, (int, float)):
            if req:
                probs.append(f"count {m} not recorded (floor {t['min']})")
            continue
        rows.append({"metric": m, "value": val, "min": t["min"], "required": req,
                     "met": val >= t["min"], "basis": t.get("basis", "")})
    return rows, probs


def record(project: Path, stage: str, verdict: str, article_type: str, evidence: dict,
           summary: str = "") -> dict:
    if stage not in STAGES:
        raise ValueError(f"stage must be one of {', '.join(STAGES)}")
    if verdict not in VERDICTS:
        raise ValueError(f"verdict must be {' | '.join(VERDICTS)}")
    if article_type not in ARTICLE_TYPES:
        raise ValueError(f"article type must be {' | '.join(ARTICLE_TYPES)}")
    if verdict == "GO" and article_type == "not_publishable":
        raise ValueError("GO with 'not_publishable' is contradictory")
    probs = evidence_problems(stage, evidence)
    rows: list[dict] = []
    if stage == "S04" and not probs:
        rows, more = compare_counts(str(evidence["design"]), evidence["counts"])
        probs += more
        short = [r for r in rows if r["required"] and not r["met"]]
        if verdict == "GO" and short:
            probs.append("GO refused: below the design floor - " + ", ".join(
                f"{r['metric']} {r['value']} < {r['min']}" for r in short)
                + " (record CONDITIONAL or NO-GO and ask the user)")
    if probs:
        raise ValueError("; ".join(probs))
    data = load(project)
    entry = {"verdict": verdict, "article_type": article_type, "evidence": evidence,
             "thresholds": rows, "summary": summary.strip(), "at": _now(),
             "inputs_sha256": bound_inputs(project, stage), "user_decision": None}
    old = data["checkpoints"].get(stage)
    if old:
        entry["previous"] = {k: old.get(k) for k in ("verdict", "article_type", "at")}
    data["checkpoints"][stage] = entry
    _save(project, data)
    return entry


def answer(project: Path, stage: str, choice: str, words: str) -> dict:
    if choice not in CHOICES:
        raise ValueError(f"choice must be {' | '.join(CHOICES)}")
    if len(str(words).strip()) < 2:
        raise ValueError("record the user's words")
    from .argtext import verify
    verify(words, "the user's words")
    data = load(project)
    entry = data["checkpoints"].get(stage)
    if not entry:
        raise ValueError(f"no {stage} checkpoint recorded")
    entry["user_decision"] = {"choice": choice, "words": words.strip(), "at": _now()}
    _save(project, data)
    return entry


def message_zh(stage: str, entry: dict) -> list[str]:
    """The few Chinese lines sent to the user at once (GO: report only; else ONE question)."""
    v, at = entry["verdict"], ARTICLE_ZH.get(entry["article_type"], entry["article_type"])
    ev = entry.get("evidence") or {}
    out = [f"可发表性检查（{stage}）：{v}；可争取的文章类型：{at}。"]
    if stage == "S02":
        nov = ev.get("novelty") or {}
        out.append(f"近 10 年同类研究 {nov.get('count')} 篇（检索：{nov.get('query')}）；最接近的："
                   + "；".join(f"{c.get('title')}（{c.get('year', '')}）"
                              for c in (nov.get("closest") or [])[:3]) + "。")
    elif stage == "S04":
        out.append("实际数量对照设计下限：" + "；".join(
            f"{r['metric']} {r['value']}（下限 {r['min']}{'，达标' if r['met'] else '，未达标'}）"
            for r in entry.get("thresholds", [])) + "。")
    elif stage == "S06":
        out.append(f"精度：{ev.get('precision')} 重复性：{ev.get('duplication')} "
                   f"稳健性：{ev.get('robustness')}")
    if entry.get("summary"):
        out.append(entry["summary"])
    if v == "GO":
        out.append("结论：继续，不需要您回复。")
    else:
        rec = ev.get("recommendation") if ev.get("recommendation") in CHOICES else (
            "change" if v == "CONDITIONAL" else "stop")
        out.append("请您选一项（只需回复一次）：1 按现状继续；2 调整角度或文章类型；3 停止。"
                   f"我的建议：{CHOICE_ZH[rec]}。")
    return out


def value(project: Path, analysis: str, could_change: str, cost: str, benefit: str) -> dict:
    """Before an additional analysis: which conclusion it could change and its rough cost."""
    if benefit not in BENEFITS:
        raise ValueError(f"benefit must be {' | '.join(BENEFITS)}")
    if not _text(analysis, 3) or not _text(could_change, 10) or not _text(cost, 3):
        raise ValueError("name the analysis, the conclusion it could change (>= 10 characters) "
                         "and its rough cost")
    data = load(project)
    row = {"analysis": analysis.strip(), "could_change": could_change.strip(),
           "cost": cost.strip(), "benefit": benefit, "at": _now(),
           "recommendation": "skip" if benefit == "low" else "run"}
    data["additional"].append(row)
    _save(project, data)
    return row


def value_line_zh(row: dict) -> str:
    rec = "建议跳过（收益低）" if row["recommendation"] == "skip" else "建议做"
    return (f"追加分析“{row['analysis']}”：可能改变的结论：{row['could_change']}；大致成本："
            f"{row['cost']}；收益 {row['benefit']} -> {rec}。")


def problems(project: Path, stage: str) -> list[str]:
    """Why the checkpoint of this stage does not let the paper advance."""
    entry = load(project)["checkpoints"].get(stage)
    if not entry:
        return [f"no {stage} publishability checkpoint: wf publishability record --stage {stage} "
                "--verdict GO|CONDITIONAL|NO-GO --article-type ... (report it to the user at once)"]
    out = evidence_problems(stage, entry.get("evidence") or {})
    if stage in ("S04", "S06") and entry.get("inputs_sha256") != bound_inputs(project, stage):
        out.append(f"{stage} checkpoint is stale: the "
                   + ("dataset summary" if stage == "S04" else "results")
                   + " changed after it was recorded; record it again")
    if entry["verdict"] != "GO":
        dec = entry.get("user_decision") or {}
        if not dec:
            out.append(f"{stage} verdict {entry['verdict']}: ask the user ONE question with your "
                       f"recommendation, then wf publishability answer --stage {stage} --choice "
                       "continue|change|stop --words \"<the user's words>\"")
        elif dec.get("choice") == "stop":
            out.append(f"the user chose to stop at {stage} (\"{dec.get('words')}\"); do not "
                       "advance")
    return out
