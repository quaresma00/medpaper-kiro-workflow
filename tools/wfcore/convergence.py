"""1.22.0: review convergence and bundle content (C5, C6, R1-R3, U2-U4, O1).

Reviews were the largest cost of real runs: every round had a fresh reviewer who could not see
the previous report, the must-fix line moved between rounds, stale Word renders were judged as
blocking every time, the engine and the reviewers counted the abstract four different ways and
'cannot verify' was written for every number. This module supplies what every review and
audit bundle now carries:

  C5  render currency - a rendered page is listed only when its DOCX is the current build of
      its sources (hashes recorded); a stale render is omitted, never shown;
  C6  engine-owned counts, computed once, with the counting rule ('do not recount');
  R1  the previous round's report and the closed/kept findings with decision and reason;
  R2  one fixed must-fix definition, round caps per scope and the regression-only mode after
      a cap (fast mode lowers the caps, safety gates are never skipped);
  R3  a key-results excerpt from the results JSON (estimates, units, CI level, population,
      comparison, model, covariates, conversions) to check numbers against;
  O1  the exact subagent call a review start prints.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

MUSTFIX = ("MUST-FIX definition (fixed, every round): a finding is MUST-FIX only when it changes "
           "a number, a conclusion, or a reader's correct understanding of the study (at S25 "
           "also: it breaks a hard journal requirement - a required file, statement, limit or "
           "format). Presentation, wording, style and taste are OPTIONAL. Tag every finding line "
           "MUST-FIX or OPTIONAL. A round with no new MUST-FIX finding is READY.")
DELTA_RULE = ("This is a delta round: judge ONLY this round's changes, regressions (something "
              "that was right and is now wrong) and NEW must-fix problems. previous_report.md and "
              "closed_findings.md list what earlier rounds decided; do not repeat closed or kept "
              "items unless they regressed.")
REGRESSION_RULE = ("The round cap for this scope is reached: check ONLY for regressions against "
                   "previous_report.md (something that was right and is now wrong) and for "
                   "numbers that contradict key_results.md. Report nothing else.")
NO_RECOUNT = ("Engine counts (computed once by the engine with the journal's counting rule; do "
              "NOT recount, quote these numbers)")
KEY_RESULTS_RULE = ("key_results.md lists the executed results (estimates with units, CI level, "
                    "population, comparison, model and covariates, conversions). Check every "
                    "number in the text against it; do not write 'cannot verify' for a number "
                    "listed there.")
CAPS = {"manuscript": 3, "package": 2, "audit": 2, "science": 3}
FAST_CAPS = {"manuscript": 2, "package": 0, "audit": 1, "science": 1}
COST = {  # U4: expected duration and credit class per stage (rough, for the user)
    "S01": ("short", "5-10 分钟"), "S02": ("medium", "15-30 分钟"), "S03": ("medium", "15-30 分钟"),
    "S04": ("long", "30-90 分钟"), "S05": ("long", "30-120 分钟"), "S06": ("medium", "15-40 分钟"),
    "S07": ("medium", "15-30 分钟"), "S08": ("medium", "15-30 分钟"), "S09": ("medium", "15-30 分钟"),
    "S10": ("medium", "15-40 分钟"), "S11": ("long", "30-90 分钟"), "S12": ("short", "5-15 分钟"),
    "S13": ("medium", "15-40 分钟"), "S14": ("medium", "15-30 分钟"), "S15": ("long", "30-60 分钟"),
    "S16": ("medium", "20-40 分钟"), "S17": ("short", "5-15 分钟"), "S18": ("long", "30-60 分钟"),
    "S19": ("medium", "按用户反馈而定"), "S20": ("medium", "15-40 分钟"), "S21": ("short", "5-15 分钟"),
    "S22": ("medium", "15-30 分钟"), "S23": ("long", "30-60 分钟"), "S24": ("medium", "按用户反馈而定"),
    "S25": ("medium", "20-40 分钟"),
}
COST_ZH = {"short": "短", "medium": "中", "long": "长"}


def _json(path: Path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ------------------------------------------------------------------ mode, caps (R2, U4, J5)
def review_mode(project: Path) -> str:
    """'fast' when the user chose it (wf config set review_mode fast) or the journal epoch is a
    repackage (J5); else 'standard'."""
    from . import journalepoch
    if journalepoch.current(project).get("repackage"):
        return "fast"
    try:
        import tomllib
        cfg = tomllib.loads((Path(project) / ".wf/config.toml").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cfg = {}
    val = str((cfg.get("targets") or {}).get("review_mode") or cfg.get("review_mode") or "")
    return "fast" if val.strip().casefold() == "fast" else "standard"


def cap(project: Path, scope: str) -> int:
    return (FAST_CAPS if review_mode(project) == "fast" else CAPS)[scope]


def rounds_used(project: Path, scope: str) -> int:
    from . import reviewrounds as rr
    return len(rr.load(project)[scope])


def capped(project: Path, scope: str) -> bool:
    return rounds_used(project, scope) >= cap(project, scope)


# ------------------------------------------------------------------ C6 engine counts
def engine_counts(project: Path) -> dict:
    """Abstract and main-text words, references, display items and pages, counted once."""
    from . import journalspec
    project = Path(project)
    target = journalspec.load(project)
    caps, _ = journalspec.limits(target)
    out: dict = {"rule": "Word-compatible count; main text = " + ", ".join(
        journalspec.word_count_scope(target)) + "; abstract without the Keywords line"}
    docx = None
    man = _json(project / "08_submission/bundle/manifest.json") or {}
    for i in man.get("items", []) if isinstance(man, dict) else []:
        f = project / str(i.get("file", ""))
        if str(i.get("role", "")).casefold() == "manuscript" and f.suffix.casefold() == ".docx" \
                and f.is_file():
            docx = f
    counts = {}
    if docx is not None:
        try:
            counts = journalspec.docx_counts(docx, journalspec.word_count_scope(target), target)
            out["source"] = docx.relative_to(project).as_posix()
        except Exception:  # noqa: BLE001
            counts = {}
    if not counts:
        for rel in ("08_submission/manuscript/full_manuscript.md", "07_manuscript/full_manuscript.md"):
            if (project / rel).is_file():
                text = (project / rel).read_text(encoding="utf-8", errors="replace")
                counts = journalspec.markdown_counts(text, journalspec.word_count_scope(target))
                from .checks.refs import actual_reference_count
                counts["references"] = actual_reference_count(text)
                out["source"] = rel
                break
    plan = _json(project / "01_protocol/artifact_plan.json") or {}
    nf = len(plan.get("main_figures") or []) if isinstance(plan, dict) else 0
    nt = len(plan.get("main_tables") or []) if isinstance(plan, dict) else 0
    out["abstract_words"] = (counts.get("abstract"), caps.get("abstract_words"))
    out["main_text_words"] = (counts.get("main"), caps.get("main_text_words"))
    out["references"] = (counts.get("references"), caps.get("reference_limit"))
    out["display_items"] = (nf + nt if plan else None, caps.get("display_items"))
    out["pages"] = (_pages(docx), None)
    return out


def _pages(docx: Path | None) -> int | None:
    if docx is None:
        return None
    import zipfile
    try:
        with zipfile.ZipFile(docx) as z:
            app = z.read("docProps/app.xml").decode("utf-8", "replace")
    except (OSError, KeyError, zipfile.BadZipFile):
        return None
    m = re.search(r"<Pages>(\d+)</Pages>", app)
    return int(m.group(1)) if m else None


def counts_line(project: Path) -> str:
    c = engine_counts(project)

    def one(label, key, unit=""):
        got, lim = c[key]
        if got is None:
            return f"{label} n/a"
        return f"{label} {got}" + (f"/{lim}" if lim else "") + unit
    parts = [one("abstract", "abstract_words", " words"), one("main text", "main_text_words", " words"),
             one("references", "references"), one("display items", "display_items"),
             one("pages", "pages")]
    return (f"{NO_RECOUNT}: " + "; ".join(parts) + f" (engine count; {c['rule']}; source "
            f"{c.get('source', '-')}).")


# ------------------------------------------------------------------ R3 key results
SKIP_KEYS = {"environment", "_receipt", "receipt", "_meta", "meta", "packages", "script",
             "script_sha256", "interpreter", "seed", "written_at", "writer"}
CONTEXT_KEYS = re.compile(r"(?i)^(units?|ci_level|ci|population|comparison|comparator|reference|"
                          r"model|model_spec|specification|covariates|adjusted_for|adjustment|"
                          r"conversion|derivation|definition|outcome|exposure|denominator|"
                          r"numerator|n|events|method|test|label)$")


def _walk(obj, path: str, out: list[str], limit: int) -> None:
    if len(out) >= limit:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k) in SKIP_KEYS:
                continue
            _walk(v, f"{path}.{k}" if path else str(k), out, limit)
    elif isinstance(obj, list):
        if obj and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in obj) \
                and len(obj) <= 4:
            out.append(f"{path} = {obj}")
            return
        for i, v in enumerate(obj[:30]):
            _walk(v, f"{path}[{i}]", out, limit)
    elif isinstance(obj, bool) or obj is None:
        return
    elif isinstance(obj, (int, float)):
        out.append(f"{path} = {obj}")
    elif isinstance(obj, str) and CONTEXT_KEYS.match(path.rsplit(".", 1)[-1].split("[")[0]):
        out.append(f"{path} = {obj[:200]}")


def key_results(project: Path, limit: int = 400) -> str:
    """Markdown excerpt of 03_analysis/results/*.json for the reviewer (R3)."""
    project = Path(project)
    lines = ["# Key results (generated from 03_analysis/results/*.json by the engine)", "",
             KEY_RESULTS_RULE, ""]
    root = project / "03_analysis/results"
    n = 0
    for f in sorted(root.glob("*.json")) if root.is_dir() else []:
        data = _json(f)
        if data is None:
            continue
        rows: list[str] = []
        _walk(data, "", rows, max(0, limit - n))
        if not rows:
            continue
        ci = data.get("ci_level") if isinstance(data, dict) else None
        lines += [f"## {f.name}" + (f" (CI level {ci})" if ci else ""), ""]
        lines += [f"- {r}" for r in rows]
        lines.append("")
        n += len(rows)
        if n >= limit:
            lines.append(f"(excerpt capped at {limit} values)")
            break
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------ C5 render currency
def render_currency(project: Path, rel: str) -> tuple[bool, str, dict]:
    """(current, why, source hashes) for a DOCX: current when its build receipt's inputs and
    bytes still match; a DOCX without a receipt is judged by what built it (none = current)."""
    from . import rebuild
    project = Path(project)
    recs = [r for r in rebuild.receipts(project) if str(r.get("output")) == rel]
    if not recs:
        return True, "no build receipt (built for this bundle)", {}
    r = recs[-1]
    srcs = {s.get("path"): str(s.get("sha256", ""))[:16] for s in r.get("sources", [])}
    why = rebuild.stale(project, r)
    if rebuild.hand_edited(project, r):
        why.append("differs from its build")
    return (not why), ("; ".join(why) or "current build of its sources"), srcs


# ------------------------------------------------------------------ R1 previous round
def previous_materials(project: Path, scope: str, rnd: dict, out: Path) -> list[str]:
    """Copy the previous round's report and write closed_findings.md (R1)."""
    from . import reviewrounds as rr
    project = Path(project)
    rounds = [r for r in rr.load(project)[scope] if r.get("id") != rnd.get("id") and r.get("closed_at")]
    if not rounds:
        return []
    prev = rounds[-1]
    lines = []
    rep = project / str(prev.get("report") or "")
    if prev.get("report") and rep.is_file():
        dst = out / "files" / "previous_report.md"
        dst.write_text(rep.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
        lines.append(f"- {dst} (the previous round's report, {prev['id']})")
    rows = ["# Closed and kept findings of earlier rounds (decision and reason)", ""]
    for r in rounds:
        reasons = {str(n.get("item")): str(n.get("reason", "")) for n in r.get("not_changed", [])}
        for f in r.get("finding_list", []):
            dec = f.get("author_decision") or {}
            st = f.get("status")
            text = {"changed": "fixed", "kept": "kept", "author": "author decides"}.get(st, st)
            if dec:
                text = f"author: {dec.get('choice')} ({dec.get('words', '')[:80]})"
            rows.append(f"- {r['id']} {f.get('id')} [{f.get('category')}] {text}: "
                        f"{str(f.get('summary', ''))[:140]}"
                        + (f" - reason: {reasons[f.get('id')][:160]}" if reasons.get(f.get("id")) else ""))
        grp = r.get("preference_group")
        if grp:
            rows.append(f"- {r['id']} optional group {', '.join(grp.get('ids', []))}: kept - "
                        f"{grp.get('reason', '')[:160]}")
    dst = out / "files" / "closed_findings.md"
    dst.write_text("\n".join(rows) + "\n", encoding="utf-8")
    lines.append(f"- {dst} (closed and kept findings with decision and reason: do not repeat)")
    return lines


def must_fix_ids(text: str) -> list[str]:
    """Finding ids whose line is tagged MUST-FIX (or BLOCKING in an audit)."""
    from .reviewrounds import FINDING_ID_RE
    out = []
    for line in (text or "").splitlines():
        m = FINDING_ID_RE.match(line)
        if m and re.search(r"(?i)\bMUST[- ]FIX\b|\bBLOCKING\b", line) \
                and not re.search(r"(?i)\bOPTIONAL\b", line) and m.group(1) not in out:
            out.append(m.group(1))
    return out


def ready(rnd: dict, text: str) -> bool:
    """R2: READY when the round found no new must-fix (tags; else critical/major counts)."""
    if re.search(r"(?i)\bMUST[- ]FIX\b|\bOPTIONAL\b", text or ""):
        return not must_fix_ids(text)
    f = rnd.get("findings") or {}
    return not (int(f.get("critical", 0)) or int(f.get("major", 0)))


def cap_summary_zh(project: Path, scope: str) -> list[str]:
    """One Chinese summary of the remaining items when a cap is reached, with a recommendation."""
    from . import reviewrounds as rr
    rounds = rr.load(project)[scope]
    last = rounds[-1] if rounds else {}
    open_items = [f for f in last.get("finding_list", []) if f.get("status") in ("kept", "author")]
    name = {"manuscript": "稿件审阅", "package": "投稿包审阅", "science": "写作前科学审阅"}[scope]
    out = [f"{name}已达到轮次上限（{cap(project, scope)} 轮，模式 {review_mode(project)}）。之后只检查回退。",
           f"剩余条目 {len(open_items)} 项："]
    out += [f"  - {f.get('id')}［{f.get('category')}］{str(f.get('summary', ''))[:80]}" for f in open_items[:12]]
    out.append("建议：剩余条目不改变数字、结论或读者的正确理解，可以按现状确认；如您希望再改，"
               "请一次性告诉我要改哪几条。")
    return out


def confirmation_zh(project: Path, scope: str) -> list[str]:
    """U3: the FIRST confirmation request states the sentence, the preconditions and every
    pending item at once."""
    from . import reviewrounds as rr
    last = rr.latest(project, scope) or {}
    pend = rr.pending_author(last)
    if scope == "science":  # 1.23.0 (S3): one question - another round, or proceed to writing
        out = ["请您二选一：再审一轮（只看改动），或回复“继续写作”（或“按你的建议”）进入写 Results。"
               "“OK / 可以”不算决定。"]
        if pend:
            out.append(f"待您决定的条目 {len(pend)} 项（每项附我的建议；回复“按你的建议”即全部采纳）：")
            out += [f"  - {f['id']}［{f.get('category')}］{str(f.get('summary', ''))[:90]} -> 建议："
                    f"{'修改' if (f.get('recommendation') or 'keep') == 'change' else '保留'}"
                    for f in pend]
        return out
    out = ["请您确认这一版：回复“我确认这一版”（或含“确认”与“这一版/此版/本版/这个版本”的同义句，"
           "或 “I confirm this version”）。“OK / 可以 / 好的 / 没问题 / 无需审阅”不算确认。",
           "确认前提：本轮已关闭；确认后文件不再改动；下列待您决定的条目已有答复。"]
    if pend:
        out.append(f"待您决定的条目 {len(pend)} 项（每项附我的建议；回复“按你的建议”即全部采纳）：")
        out += [f"  - {f['id']}［{f.get('category')}］{str(f.get('summary', ''))[:90]} -> 建议："
                f"{'修改' if (f.get('recommendation') or 'keep') == 'change' else '保留'}" for f in pend]
    else:
        out.append("没有待您决定的条目。")
    return out


def compliance_report(project: Path) -> str:
    """Fast mode / repackage: the package round's report is the engine's compliance summary."""
    from . import compliance
    zh = compliance.summary_zh(project) or ["（尚无合规矩阵：先运行 wf rebuild 或 wf compliance write）"]
    return ("# Package compliance round (fast mode; engine-generated, no reviewer subagent)\n\n"
            "## Verdict\n\nCompliance only. Open FAIL rows block S23/S25 through "
            "compliance_matrix_complete; nothing here is a reviewer finding.\n\n"
            "## Compliance summary\n\n" + "\n".join(zh) + "\n")


def subagent_call(bundle: Path, report: Path) -> str:
    """O1: the exact call - the orchestrator does not relay anything by hand."""
    return (f"invoke subagent: name=medpaper-reviewer, prompt=\"Read {bundle / 'MANIFEST.md'} and "
            f"follow it; write your complete report to {report}\" (run it in the paper's main "
            "chat; a workflow step cannot start a subagent)")


def fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
