"""1.21.0 checks (a paper pinned earlier gets them after `wf migrate --yes`; `wf journal switch`
adopts the current gate set for S20-S25).

indexing_evidence_cited      B4 (S20): an official Clarivate scie_source_url is backed by an
                             indexing capture of this journal epoch (wf guidelines ingest --kind
                             indexing), and every value read only from a screenshot was confirmed
                             by the user once (wf guidelines confirm-image) and equals the typed
                             field it supports.
portal_requirements_applied  B5 (S23): when the submission system was read (wf portal ingest,
                             only on the user's request), target_journal.json agrees with it - no
                             separate title page without an upload slot, every required upload
                             item listed in required_uploads.
web_captures_traced          B6 (S04): web pages captured as data (wf data capture) are unchanged
                             since capture and carry URL + exact query; values read from a
                             screenshot are verified once (a warning until then).
"""
from __future__ import annotations

import json

from . import Ctx, Result, check

V = (1, 21, 0)


def since_1210(ctx) -> bool:
    from ..state import pin_for, version_tuple
    try:
        return version_tuple(pin_for(ctx.state, getattr(ctx.stage, "id", None))) >= V
    except Exception:  # noqa: BLE001
        return True


def _pinned(name: str) -> Result:
    return Result(True, name, "applies from engine 1.21.0 (`wf migrate --yes` or `wf journal "
                              "switch`); paper pinned earlier - the new commands work now")


def _json(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


@check("indexing_evidence_cited")
def indexing_evidence_cited(ctx: Ctx) -> Result:
    name = "indexing_evidence_cited"
    if not since_1210(ctx):
        return _pinned(name)
    from .. import guideingest, journalepoch
    tj = _json(ctx.p("08_submission/target_journal.json"))
    ep = journalepoch.number(ctx.project)
    ev = guideingest.entries(ctx.project, "indexing", ep)
    urls = {str(e.get("url", "")).strip() for e in ev} | {str(e.get("final_url", "")).strip() for e in ev}
    problems = []
    scie = str(tj.get("scie_source_url") or "").strip()
    if scie.startswith("http") and guideingest.reg_domain(scie) == "clarivate.com" and scie not in urls:
        problems.append(f"scie_source_url {scie} has no indexing evidence of journal epoch {ep}: "
                        "capture the MJL/JCR page (text + screenshot) and run wf guidelines ingest "
                        "--kind indexing --from <capture> --screenshot <png> --url <that URL>")
    for e in guideingest.unconfirmed_image_values(ctx.project, ep):
        problems.append(f"values read only from the screenshot {e.get('screenshot') or e['file']} "
                        f"({', '.join(f'{k}={v}' for k, v in e['read_from_image'].items())}) are "
                        "not confirmed: list them once for the user, then wf guidelines "
                        "confirm-image --why \"<用户原话>\"")
    for e in ev:
        for k, v in (e.get("read_from_image") or {}).items():
            if k in tj and str(tj[k]).strip().casefold() != str(v).strip().casefold():
                problems.append(f"target_journal.json {k} = {tj[k]!r} but the screenshot reading "
                                f"recorded {v!r} ({e['file']})")
    if problems:
        return Result(False, name, "; ".join(problems[:5]),
                      ["MJL/JCR need a login: the user logs in in the browser window; the agent "
                       "saves a text capture and a screenshot under .playwright-mcp/ and ingests "
                       "them; never type credentials."])
    return Result(True, name, f"{len(ev)} indexing evidence capture(s) in journal epoch {ep}; "
                              "screenshot readings confirmed")


@check("portal_requirements_applied")
def portal_requirements_applied(ctx: Ctx) -> Result:
    name = "portal_requirements_applied"
    if not since_1210(ctx):
        return _pinned(name)
    from .. import portal
    rec = portal.current(ctx.project)
    if not rec:
        return Result(True, name, "submission system not read (optional; only when the user asks)")
    probs = portal.problems(ctx.project)
    if probs:
        return Result(False, name, "; ".join(probs[:5]),
                      ["Fix target_journal.json (required_uploads, title_page.placement), then "
                       "wf rebuild --wait; the portal record itself is never edited by hand."])
    return Result(True, name, f"journal fields agree with the submission system "
                              f"({len(rec.get('upload_items') or [])} upload item(s), read "
                              f"{rec.get('read_at')})")


@check("web_captures_traced")
def web_captures_traced(ctx: Ctx) -> Result:
    name = "web_captures_traced"
    if not since_1210(ctx):
        return _pinned(name)
    from .. import webdata
    caps = webdata.all_captures(ctx.project)
    if not caps:
        return Result(True, name, "no web page captured as data")
    bad, warn = webdata.problems(ctx.project)
    hints = ["Capture again (a new version) instead of editing a capture; wf data capture --from "
             "<capture> --url <URL> --query \"...\" --name <name> [--screenshot] [--values-csv]."]
    if bad:
        return Result(False, name, "; ".join(bad[:6]), hints)
    if warn:
        return Result(False, name, "; ".join(warn[:6]), hints, severity="warn")
    return Result(True, name, f"{len(caps)} web capture(s) unchanged, with URL, query and date")
