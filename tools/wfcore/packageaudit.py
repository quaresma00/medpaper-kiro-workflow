"""1.26.0: the independent package audit runs at S24, before the user's confirmation.

Real runs spent more than half of their working time after S23: an S24 review round, the user's
confirmation and freeze, then an S25 audit that found new items, a loop back to S24, another
confirmation and freeze, and a re-audit. From 1.26.0 (papers created on 1.26.0, migrated with
`wf migrate --yes`, or after a journal switch) the order is:

  S24  round 1 is the full independent audit of the package as built (first-time reader, editor,
       journal compliance; every compliance-matrix row agree/disagree; obligations missing from
       the requirement list) - the same brief S25 used. The agent fixes on its own judgement and
       rebuilds. A round that changed an upload is re-audited at once (previous findings
       RESOLVED/OPEN plus new BLOCKING issues), without a message to the user. The user confirms
       ONCE, and only when the last audit round read exactly the package being confirmed; the
       freeze records that round.
  S25  no reviewer: the freeze is verified, the bound S24 audit report becomes the S25 audit file
       (`package_review.py record-audit`), the deterministic final checks run, and PASS needs the
       last audit verdict PASS (the author final copy stays the only route around a REVISE).

Nothing is read less than before: the same audit brief, matrix rows, re-audit rule and caps.
What changes is that the user confirms after the audit instead of before it, so the
"REVISE -> back to S24 -> confirm again -> audit again" loop no longer starts by default.
A freeze taken in the earlier order (no audited round in it) keeps the S25 audit.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

V = (1, 26, 0)
SINCE = "1.26.0"
AUDIT_MODES = ("audit", "recheck")
S24 = "S24_package_human_review"
FREEZE_REL = "08_submission/package_review_freeze.json"

ROUND_FULL = """S24 independent package audit ({rid}, FULL - the first audit of this package for this
journal). 1.26.0: it runs BEFORE the user's confirmation; S25 does not read the package again.
Read every file listed below in normal submission order before any QA file, as a first-time
reader, an editor and a journal-compliance reviewer. Report in exactly these sections:
{sections}. Under Verdict write `Package round: {rid}` and PASS, REVISE or BLOCKED. Number every
finding (F1, F2, ...), name file and location, and classify it BLOCKING, MINOR or PREFERENCE.
{engine}
Write your complete report to {report} - the only file you may write. If you cannot write it,
return it between <<<REPORT>>> and <<<END>>>."""

ROUND_RECHECK = """S24 package re-audit ({rid}, RE-AUDIT of the changes made after {prev}). This is NOT a
fresh full audit.
1. For every finding in previous_findings.md write one line
   `- <id> <BLOCKING|MINOR>: RESOLVED|OPEN - <file + location>`.
2. Report NEW issues only if they are BLOCKING (a required file, fact, rule, or a number/claim
   that is wrong); number them after the previous ids. New minor or preference remarks are out
   of scope for a re-audit.
Report in exactly these sections: {sections}. Under Verdict write `Package round: {rid}` and
PASS (every previous BLOCKING/MINOR finding RESOLVED or listed as an engine issue, and no new
BLOCKING issue), REVISE or BLOCKED.
{engine}
Write your complete report to {report} - the only file you may write. If you cannot write it,
return it between <<<REPORT>>> and <<<END>>>."""

_VERDICT = re.compile(r"\b(PASS|REVISE|BLOCKED)\b")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s")


# ------------------------------------------------------------------ release policy
def _pin(project: Path | None, stage: str | None) -> tuple[int, ...]:
    from .state import version_tuple
    try:
        st = json.loads((Path(project) / ".wf/state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return V
    if not isinstance(st, dict):
        return V
    pin = version_tuple(str(st.get("engine_pin") or st.get("pipeline_version") or "0"))
    jp = st.get("journal_gate_pin") or {}
    if stage and stage in (jp.get("stages") or []):
        pin = max(pin, version_tuple(str(jp.get("version", "0"))))
    return pin


def since_1260_project(project: Path | None, stage: str | None = S24) -> bool:
    """A paper created on 1.26.0+, migrated, or after a journal switch (S20-S25)."""
    if project is None:
        return True
    return _pin(project, stage) >= V


def since_1260(ctx) -> bool:
    from .state import pin_for, version_tuple
    try:
        return version_tuple(pin_for(ctx.state, getattr(ctx.stage, "id", None))) >= V
    except Exception:  # noqa: BLE001
        return True


def audit_flow(project: Path) -> bool:
    """The S24 package rounds of this paper follow the 1.26.0 order."""
    return since_1260_project(project, S24)


# ------------------------------------------------------------------ rounds
def _rounds(project: Path) -> list[dict]:
    from . import reviewrounds as rr
    return rr.load(project)["package"]


def next_mode(rounds: list[dict]) -> str:
    """Round 1 of a journal epoch is the full audit; every later round re-audits."""
    return "recheck" if any(r.get("mode") == "audit" and r.get("closed_at") for r in rounds) \
        else "audit"


def round_report(project: Path, rnd: dict | None) -> str:
    if not rnd:
        return ""
    for rel in (rnd.get("report"), f".wf/review_bundle/{rnd.get('id')}/report.md"):
        p = Path(project) / str(rel or "")
        if rel and p.is_file():
            return p.read_text(encoding="utf-8", errors="replace")
    return ""


def verdict(text: str) -> str | None:
    """PASS / REVISE / BLOCKED from the report's Verdict section (first token found)."""
    inside, sec = False, []
    for line in (text or "").splitlines():
        if re.match(r"^\s{0,3}#{1,6}\s*Verdict\b", line, re.I):
            inside = True
            continue
        if inside and _HEADING.match(line):
            break
        if inside:
            sec.append(line)
    m = _VERDICT.search("\n".join(sec))
    return m.group(1) if m else None


def changed_uploads(rnd: dict) -> list[str]:
    """Uploads whose visible content changed between the auditor's reading and the close."""
    before, after = rnd.get("inputs") or {}, rnd.get("after") or {}
    return sorted(r for r in set(before) | set(after) if before.get(r) != after.get(r))


def _sha(text: str) -> str:
    return hashlib.sha256(str(text or "").replace("\r\n", "\n").encode("utf-8")).hexdigest()


def problems(project: Path, final: bool = False, state=None) -> list[str]:
    """Why the package cannot be confirmed (S24) or passed (S25, final=True) yet."""
    project = Path(project)
    rounds = _rounds(project)
    if not any(r.get("mode") == "audit" and r.get("closed_at") for r in rounds):
        return ["no full independent package audit in this journal epoch yet: `review_round.py "
                "start --scope package` (1.26.0: round 1 is the audit)"]
    last = rounds[-1]
    rid = last.get("id")
    if last.get("mode") not in AUDIT_MODES:
        return [f"the last package round {rid} ({last.get('mode')}) is not an audit round: "
                "re-audit (`review_round.py start --delta`)"]
    if not last.get("closed_at"):
        return [f"audit round {rid} is open: fix, `wf rebuild --wait`, then `review_round.py close`"]
    text = round_report(project, last)
    if not text:
        return [f"audit round {rid} has no saved report (close --report <file>)"]
    out = []
    moved = changed_uploads(last)
    if moved:
        out.append(f"{rid} changed {len(moved)} upload(s) after the auditor read them ("
                   + ", ".join(moved[:4]) + "): re-audit at once (`review_round.py start --delta`) "
                   "before asking for the confirmation")
    v = verdict(text)
    if v is None:
        out.append(f"{rid}: the report states no PASS/REVISE/BLOCKED under 'Verdict'")
    elif v == "BLOCKED":
        out.append(f"{rid}: the audit is BLOCKED (a fact or file only the user or the portal can "
                   "supply): ask for it, rebuild, re-audit")
    if final:
        dec = (state.decision("submission_package_independent_audit") or {}).get("value") \
            if state is not None else None
        if dec == "PASS" and v != "PASS":
            out.append(f"PASS recorded, but the last audit round {rid} says {v or 'no verdict'}: "
                       "loop to S24 for a re-audit round, or finish with the author final copy "
                       "(PASS_AUTHOR_FINAL_COPY)")
        bound = freeze_round(project)
        if bound != rid:
            out.append(f"the package freeze binds round {bound or 'none'}, not the last audit "
                       f"round {rid}: confirm and freeze again at S24")
        else:
            drift = freeze_vs_round(project, last)
            if drift:
                out.append(f"the frozen uploads differ from what audit round {rid} read: "
                           + ", ".join(drift[:4]))
    return out


# ------------------------------------------------------------------ freeze binding (S24 -> S25)
def _freeze(project: Path) -> dict:
    try:
        data = json.loads((Path(project) / FREEZE_REL).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def freeze_round(project: Path) -> str:
    return str(_freeze(project).get("package_round") or "")


def freeze_binding(project: Path) -> dict:
    """Fields `package_review.py freeze` adds: the approved audit round and its version."""
    if not audit_flow(project):
        return {}
    from . import reviewrounds as rr
    rnd = rr.approved_round(project, "package")
    if not rnd or rnd.get("mode") not in AUDIT_MODES:
        return {}
    return {"package_round": rnd["id"], "confirmed_version": rnd.get("confirmed_version"),
            "audit_verdict": rnd.get("audit_verdict") or verdict(round_report(project, rnd))}


def freeze_vs_round(project: Path, rnd: dict) -> list[str]:
    """Uploads the audit round read whose frozen content differs (or is not frozen)."""
    frozen = {str(r.get("path")): str(r.get("content_sha256") or "")
              for r in _freeze(project).get("files", []) if isinstance(r, dict)
              and r.get("role") == "upload"}
    return sorted(rel for rel, h in (rnd.get("after") or {}).items() if frozen.get(rel) != h)


def audit_bound(project: Path, audit_text: str) -> tuple[bool, str]:
    """1.26.0 binding for submission_audit_matches_freeze: the S25 audit file is the saved
    report of the audit round the freeze names."""
    rid = freeze_round(project)
    if not rid:
        return False, ""
    rnd = next((r for r in _rounds(project) if r.get("id") == rid), None)
    if rnd is None:
        return False, f"the freeze names package round {rid}, which is not on record"
    rep = round_report(project, rnd)
    if not rep or _sha(rep) != _sha(audit_text):
        return False, (f"the audit file is not the saved report of audit round {rid} "
                       "(run package_review.py record-audit)")
    return True, f"the audit file is the S24 audit report of round {rid}, which the freeze binds"


def record_audit(project: Path) -> Path:
    """S25 (1.26.0): copy the bound S24 audit report verbatim to the S25 audit file."""
    from .audit import AUDIT_REL
    from .packagefreeze import verify_freeze
    project = Path(project)
    ok, probs, _n = verify_freeze(project)
    if not ok:
        raise ValueError("the package changed after the user's confirmation; return to S24: "
                         + "; ".join(probs[:4]))
    rid = freeze_round(project)
    if not rid:
        raise ValueError("this freeze predates the 1.26.0 order (no audited round in it): run the "
                         "S25 audit - package_review.py audit-start")
    rnd = next((r for r in _rounds(project) if r.get("id") == rid), None)
    src = Path(project) / str((rnd or {}).get("report") or "")
    if not rnd or not rnd.get("report") or not src.is_file():
        raise ValueError(f"no saved report for audit round {rid}")
    dest = project / AUDIT_REL
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)
    return dest


def rows_bundle(project: Path) -> Path | None:
    """The bundle whose rows_required.json the S25 audit file answers (1.26.0 freezes)."""
    rid = freeze_round(project)
    if not rid:
        return None
    b = Path(project) / ".wf/review_bundle" / rid
    return b if (b / "rows_required.json").is_file() else None


# ------------------------------------------------------------------ the round bundle
def round_brief(project: Path, rnd: dict, bundle: Path) -> str:
    from . import audit
    rounds = [r for r in _rounds(project) if r.get("id") != rnd.get("id") and r.get("closed_at")]
    prev = rounds[-1]["id"] if rounds else "-"
    tpl = ROUND_RECHECK if rnd.get("mode") == "recheck" else ROUND_FULL
    return tpl.format(rid=rnd["id"], prev=prev, sections=", ".join(audit.SECTIONS),
                      report=Path(bundle) / "report.md", engine=audit.engine_text())


def write_round_bundle(project: Path, rnd: dict) -> Path:
    """One folder the auditor reads on its own: the audit brief, the package files in place,
    the requirement list and matrix (rows to judge), previous findings for a re-audit, key
    results and engine counts."""
    from . import audit, convergence as cv
    project = Path(project)
    out = project / ".wf/review_bundle" / rnd["id"]
    if out.exists():
        shutil.rmtree(out)
    (out / "files").mkdir(parents=True)
    mode = rnd.get("mode")
    rounds = [r for r in _rounds(project) if r.get("id") != rnd.get("id") and r.get("closed_at")]
    prev_text = round_report(project, rounds[-1]) if rounds and mode == "recheck" else ""
    lines = [f"# S24 package audit bundle {rnd['id']} ({mode})", "",
             round_brief(project, rnd, out), ""]
    from .declarations import ai_fact
    fact = ai_fact(project)
    if fact:
        lines += [f"AI/LLM use is the author's recorded fact (not a pending item): "
                  f"{'used: ' + str(fact['tool']) + ' for ' + str(fact['purpose']) if fact['used'] else 'not used'}"
                  f". Statement: {fact['statement']}", ""]
    from .guidelines import status as _gstatus
    from .journalepoch import banner
    lines += [f"Guideline basis: 08_submission/guidelines_extract.md ({_gstatus(project)}), checked "
              "against the journal's own text: 08_submission/guidelines_source.txt (line-numbered "
              "L0001...) and the cached original guide files listed below. Judge compliance from "
              "the original, not from the extract alone.", f"{banner(project) or ''}", "",
              "## Files", ""]
    para = audit._matrix_rows(project, out, "recheck" if mode == "recheck" else "full", prev_text)
    if para:
        lines[3:3] = [para + ("\nList every disagree row and every MISSING obligation also as a "
                              "numbered BLOCKING finding under 'Issues requiring correction'."), ""]
    if mode == "recheck":
        items = audit.open_items(prev_text)
        (out / "previous_findings.md").write_text(
            f"# Open findings of the previous round ({rounds[-1]['id']})\n\n"
            + ("\n".join(f"- {x}" for x in items) or "- none") + "\n", encoding="utf-8")
        lines.append(f"- {out / 'previous_findings.md'} (check each: RESOLVED or OPEN)")
        if (out / "open_rows.md").is_file():
            lines.append(f"- {out / 'open_rows.md'} (compliance rows to re-check)")
    for rel in audit.package_files(project, with_freeze=False):
        if not (project / rel).is_file():
            continue
        note = ""
        if rel.endswith(".docx"):
            cur, why, _s = cv.render_currency(project, rel)
            note = " (current build)" if cur else f" (STALE: {why} - not a basis for judgement)"
        lines.append(f"- {project / rel}{note}")
    from .reviewitems import write as _write_items
    listed = _write_items(project, out)
    if listed:
        lines.append(f"- {listed} (cases the deterministic checks could not decide)")
    (out / "key_results.md").write_text(cv.key_results(project), encoding="utf-8")
    lines.append(f"- {out / 'key_results.md'} (key results from the results JSON)")
    conv = ["", cv.MUSTFIX, cv.counts_line(project), cv.KEY_RESULTS_RULE]
    if cv.review_mode(project) == "fast":
        conv.append("FAST MODE / REPACKAGE: one compliance-focused audit - journal requirements, "
                    "old-journal traces and guideline obligations; the science is frozen and was "
                    "reviewed at S18/S19: do not re-audit it.")
    if mode == "recheck" and len([r for r in rounds if r.get("mode") in AUDIT_MODES]) >= \
            cv.cap(project, "audit"):
        conv.append(cv.REGRESSION_RULE + " Still say RESOLVED or OPEN for every previous finding.")
    lines[3:3] = conv + [""]
    (out / "MANIFEST.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


# ------------------------------------------------------------------ messages for the user
def status_zh(project: Path) -> list[str]:
    """Lines for the S24 confirmation message: the last audit verdict and readiness."""
    rounds = _rounds(project)
    last = rounds[-1] if rounds else {}
    kind = {"audit": "完整审计", "recheck": "复核"}.get(last.get("mode"), str(last.get("mode")))
    v = last.get("audit_verdict") or verdict(round_report(project, last))
    out = [f"末轮审计 {last.get('id', '-')}（{kind}）结论：{v or '未写明'}。"]
    probs = problems(project)
    if probs:
        out.append("现在还不能请用户确认：" + "；".join(probs))
        return out
    out.append("审计读到的就是现在请您确认的这一版投稿包；确认后冻结的正是这一版，S25 不再重新审阅。")
    if v == "REVISE":
        out.append("注意：末轮结论为 REVISE（仍有未解决的问题）。确认后 S25 不能记 PASS，只能走作者"
                   "终稿；建议先修改并复核一轮。")
    return out
