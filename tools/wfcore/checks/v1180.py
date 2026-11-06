"""1.18.0 checks (a paper pinned earlier gets them after `wf migrate --yes`; `wf journal switch`
adopts the current gate set for S20-S25).

guideline_requirements_mapped  K2 (S20): guideline_requirements.json covers every category,
                               quotes the guide verbatim at its lines, agrees with the typed
                               fields, and every obligation sentence of guidelines_source.txt
                               is covered by a requirement or an n.a. range.
journal_fields_met             K3 (S23): abstract, title page, running title, highlights/key
                               points, cover letter, required uploads, figure files, ORCID.
compliance_matrix_complete     K4 (S23; S25 with final = true): the matrix is current, no row
                               FAILs; manual rows without evidence WARN at S23, FAIL at S25.
audit_rows_judged              K6 (S25): the audit gives a verdict for every (open) matrix row;
                               a disagreement or a missing requirement is BLOCKING (no PASS).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import Ctx, Result, check

V = (1, 18, 0)


def since_1180(ctx: Ctx) -> bool:
    from ..state import pin_for, version_tuple
    try:
        return version_tuple(pin_for(ctx.state, getattr(ctx.stage, "id", None))) >= V
    except Exception:  # noqa: BLE001
        return True


def since_1180_project(project: Path | None, stage: str = "S23_package") -> bool:
    """The same decision for code without a gate context (builders, display files)."""
    from ..state import version_tuple
    if project is None:
        return True
    try:
        st = json.loads((Path(project) / ".wf/state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return True
    pin = version_tuple(str(st.get("engine_pin") or st.get("pipeline_version") or "0"))
    jp = st.get("journal_gate_pin") or {}
    if stage in (jp.get("stages") or []):
        pin = max(pin, version_tuple(str(jp.get("version", "0"))))
    return pin >= V


def _pinned(name: str) -> Result:
    return Result(True, name, "applies from engine 1.18.0 (`wf migrate --yes` or `wf journal "
                              "switch`); paper pinned earlier")


@check("guideline_requirements_mapped")
def guideline_requirements_mapped(ctx: Ctx) -> Result:
    name = "guideline_requirements_mapped"
    if not since_1180(ctx):
        return _pinned(name)
    from .. import requirements
    probs, warns = requirements.problems(ctx.project)
    hint = ["Build the list from 08_submission/guidelines_source.txt for the chosen article type "
            "(schema reference/guideline_requirements.schema.json; details "
            "reference/stage_details/S20_journal.md 'Requirement list')."]
    if probs:
        return Result(False, name, "; ".join(probs[:8]), hint)
    n = len(requirements.load(ctx.project).get("requirements") or [])
    if warns:
        return Result(False, name, f"{n} requirement(s) mapped; " + "; ".join(warns), hint,
                      severity="warn")
    return Result(True, name, f"{n} requirement(s) mapped, quoted at their lines; every "
                              "obligation line of the guide covered")


@check("journal_fields_met")
def journal_fields_met(ctx: Ctx) -> Result:
    name = "journal_fields_met"
    if not since_1180(ctx):
        return _pinned(name)
    from .. import journalfields
    rows = journalfields.run_all(ctx.project)
    bad = [f"{n}: {d}" for n, s, d in rows if s in ("FAIL", "CANNOT_ASSESS")]
    if bad:
        return Result(False, name, "; ".join(bad[:6]),
                      ["Fix the journal copy / title page / cover letter / highlights, then "
                       "`wf rebuild`; typed fields: reference/stage_details/S20_journal.md."])
    return Result(True, name, f"{len(rows)} typed journal field(s) checked" if rows else
                  "journal sets none of the 1.18.0 typed fields (silent)")


@check("compliance_matrix_complete")
def compliance_matrix_complete(ctx: Ctx) -> Result:
    name = "compliance_matrix_complete"
    if not since_1180(ctx):
        return _pinned(name)
    from .. import compliance
    final = bool(ctx.spec.get("final"))
    probs, warns, rows = compliance.verify(ctx, final=final)
    counts = {s: sum(1 for r in rows if r["status"] == s) for s in compliance.STATUSES}
    tally = ", ".join(f"{s} {n}" for s, n in counts.items())
    if probs:
        return Result(False, name, "; ".join(probs[:5]) + (f" ({tally})" if rows else ""),
                      ["Fix the FAIL rows; record manual evidence in "
                       "08_submission/compliance_evidence.json; then `wf compliance write`."])
    if warns:
        return Result(False, name, "; ".join(warns) + f" ({tally})", severity="warn")
    return Result(True, name, f"{len(rows)} requirement row(s): {tally}")


ROW_LINE = re.compile(r"^[\s>*|#-]*\**`?(?P<id>[A-Za-z][A-Za-z0-9_.-]{0,23})`?\**\s*(?:[:|\-\u2013]|\s)")
VERDICT = re.compile(r"(?i)\b(disagree|agree)\b")
MISSING = re.compile(r"(?i)\bMISSING\b[^\n]*\bL\d{4,5}\b|\bL\d{4,5}\b[^\n]*\bmissing requirement\b")


def row_verdicts(text: str, ids) -> dict[str, tuple[str, str]]:
    """{row id: (agree|disagree, rest of the line)} from an audit report."""
    want, out = set(ids), {}
    for line in (text or "").splitlines():
        m = ROW_LINE.match(line)
        if not m or m.group("id") not in want:
            continue
        v = VERDICT.search(line[m.end():])
        if v:
            out[m.group("id")] = (v.group(1).casefold(), line[m.end():].strip()[:200])
    return out


def missing_requirements(text: str) -> list[str]:
    return [ln.strip()[:160] for ln in (text or "").splitlines() if MISSING.search(ln)]


@check("audit_rows_judged")
def audit_rows_judged(ctx: Ctx) -> Result:
    name = "audit_rows_judged"
    if not since_1180(ctx):
        return _pinned(name)
    from .. import audit, compliance
    data = compliance._json(ctx.p(compliance.MATRIX_JSON))
    if not isinstance(data, dict):
        return Result(False, name, "no 08_submission/compliance_matrix.json to audit against")
    rel = ctx.spec.get("path", audit.AUDIT_REL)
    text = ctx.read(rel) if ctx.p(rel).is_file() else ""
    if not text:
        return Result(False, name, f"{rel} missing")
    ids = audit.required_rows(ctx.project, data)
    got = row_verdicts(text, ids)
    probs = []
    missing = [i for i in ids if i not in got]
    if missing:
        probs.append(f"the audit gives no agree/disagree verdict for matrix row(s): "
                     f"{', '.join(missing[:20])}")
    dis = [i for i, (v, _r) in got.items() if v == "disagree"]
    gaps = missing_requirements(text)
    dec = (ctx.state.decision("submission_package_independent_audit") or {}).get("value")
    if (dis or gaps) and dec == "PASS":
        probs.append("PASS recorded although the audit "
                     + (f"disagrees with row(s) {', '.join(dis[:10])}" if dis else "")
                     + (" and " if dis and gaps else "")
                     + (f"reports {len(gaps)} requirement(s) missing from the list" if gaps else "")
                     + ": these are BLOCKING - decide REVISE (or fix by hand: PASS_AUTHOR_FINAL_COPY)")
    if probs:
        return Result(False, name, "; ".join(probs),
                      ["The brief asks for '- <row id>: agree|disagree - <reason>' per row and "
                       "'MISSING L00nn: <quote> - BLOCKING' per obligation absent from the list."])
    return Result(True, name, f"{len(got)} matrix row verdict(s); disagree {len(dis)}; "
                              f"missing requirements {len(gaps)}")
