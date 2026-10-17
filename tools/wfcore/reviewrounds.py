"""1.8.1 review rounds: an in-IDE reviewer subagent replaces the third-party review package.

Each round, at a review point (scope "manuscript" = S18/S19, scope "package" = S24/S25):

    start   hashes every input (current text, tables, figures / the submission bundle) and
            names what the read-only reviewer is given (all, or only the delta since the last
            round plus dependants);
    close   records the findings count by severity, the changes the agent applied on its own
            judgement (file + one line), what it deliberately did not change and why, and the
            hashes AFTER those changes;
    decide  records the user's single answer: another round, or no further review. The latter
            also records the stage's approval decision, naming the round id.

Stored in the paper at .wf/review_rounds.json. The latest approved round is what the scientific
freeze binds to (instead of a review-package id), and coverage means: nothing the round covered
changed after it closed.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

REL = ".wf/review_rounds.json"
SCOPES = {
    "manuscript": {"prefix": "M", "decision": "manuscript_human_reviewed",
                   "value": "NO_FURTHER_REVIEW", "summary": "07_manuscript/human_review.md",
                   "headings": ("Materials presented", "Independent verdict",
                                "User-requested revisions", "Revalidation",
                                "Approval to proceed")},
    "package": {"prefix": "P", "decision": "submission_package_user_confirmed", "value": "OK",
                "summary": "08_submission/package_human_review.md",
                "headings": ("Package presented", "User modifications", "Revalidation",
                             "User confirmation", "Frozen package")},
}
SEVERITIES = ("critical", "major", "minor")
ANOTHER, DONE = "another_round", "no_further_review"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")  # same as state.json


def inputs(project: Path, scope: str) -> dict[str, str]:
    """Paper-relative path -> SHA-256 of everything a round of this scope covers."""
    if scope == "manuscript":
        from .readerreview import reader_inputs
        return reader_inputs(project)
    # 1.9.0: a package round covers the uploads by visible content; internal QC, notes and
    # receipts are evidence and never reopen review.
    from .determinism import content_sha256
    from .packagefreeze import FREEZE_REL, expected_files, upload_files
    uploads = upload_files(project)
    return {rel: content_sha256(p) for rel, p in expected_files(project).items()
            if rel in uploads and rel not in (FREEZE_REL, SCOPES["package"]["summary"])}


def load(project: Path) -> dict:
    try:
        data = json.loads((Path(project) / REL).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("schema", 1)
    for scope in SCOPES:
        data.setdefault(scope, [])
    return data


def _save(project: Path, data: dict) -> None:
    path = Path(project) / REL
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def latest(project: Path, scope: str) -> dict | None:
    rounds = load(project)[scope]
    return rounds[-1] if rounds else None


def _changed_since(prev: dict | None, current: dict[str, str],
                   project: Path | None = None) -> list[str]:
    if not prev:
        return sorted(current)
    after = prev.get("after") or {}
    changed = [r for r, h in current.items() if after.get(r) != h]
    if project is None or not changed:
        return sorted(changed)
    from . import presentation
    from .determinism import raw_sha256
    out = []
    for r in changed:
        p = Path(project) / r
        old = str(after.get(r, ""))
        if old and p.is_file() and old.casefold() == raw_sha256(p).casefold():
            continue  # a pre-1.9.0 round recorded the raw hash of the same bytes
        if presentation.covered(project, r, prev.get("closed_at")):
            continue  # a presentation delta after the round (facts unchanged, 1.9.0)
        out.append(r)
    return sorted(out)


def start(project: Path, scope: str, stage: str, delta: bool = False) -> dict:
    data = load(project)
    rounds = data[scope]
    if rounds and not rounds[-1].get("closed_at"):
        raise ValueError(f"round {rounds[-1]['id']} is still open; close it first")
    if rounds and rounds[-1].get("user_decision") is None:
        raise ValueError(f"round {rounds[-1]['id']} awaits the user's answer (decide)")
    current = inputs(project, scope)
    prev = rounds[-1] if rounds else None
    if delta and prev:
        changed = _changed_since(prev, current)
        reviewed = set(changed)
        if scope == "manuscript" and changed:
            try:
                from .dependencies import closure
                reviewed |= set(closure(project, changed)) & set(current)
            except Exception:  # noqa: BLE001 - a broken plan keeps the changed files alone
                pass
        mode = "delta"
    else:
        reviewed, mode = set(current), "full"
    rid = f"{SCOPES[scope]['prefix']}{len(rounds) + 1:03d}"
    rnd = {"id": rid, "scope": scope, "stage": stage, "mode": mode, "started_at": _now(),
           "inputs": current, "reviewed": sorted(reviewed), "closed_at": None,
           "findings": {}, "changes": [], "not_changed": [], "after": {},
           "user_decision": None}
    rounds.append(rnd)
    _save(project, data)
    return rnd


def close(project: Path, scope: str, findings: dict[str, int], changes: list[dict],
          not_changed: list[dict]) -> dict:
    data = load(project)
    if not data[scope] or data[scope][-1].get("closed_at"):
        raise ValueError("no open review round; start one first")
    rnd = data[scope][-1]
    counts = {k: int(findings.get(k, 0)) for k in SEVERITIES}
    if any(v < 0 for v in counts.values()):
        raise ValueError("finding counts must be >= 0")
    for c in changes:
        if not str(c.get("file", "")).strip() or not str(c.get("summary", "")).strip():
            raise ValueError("each change needs a file and a one-line summary")
    rnd.update(findings=counts, changes=changes, not_changed=not_changed,
               after=inputs(project, scope), closed_at=_now())
    _save(project, data)
    _write_summary(project, scope, data[scope])
    return rnd


def decide(project: Path, scope: str, answer: str, words: str) -> dict:
    if answer not in (ANOTHER, DONE):
        raise ValueError(f"answer must be {ANOTHER} or {DONE}")
    if len(words.strip()) < 2:
        raise ValueError("record the user's words")
    data = load(project)
    rnd = data[scope][-1] if data[scope] else None
    if not rnd or not rnd.get("closed_at"):
        raise ValueError("close the round (report to the user) before recording the answer")
    if answer == DONE:
        drift = _changed_since(rnd, inputs(project, scope), project)
        if drift:
            raise ValueError("changed after the round closed (run another round, --delta is "
                             "fine): " + ", ".join(drift[:6]))
    rnd.update(user_decision=answer, user_words=words.strip(), decided_at=_now())
    _save(project, data)
    _write_summary(project, scope, data[scope])
    return rnd


def _write_summary(project: Path, scope: str, rounds: list[dict]) -> None:
    """The stage's human-readable review record, regenerated from the rounds (no hand edit)."""
    cfg = SCOPES[scope]
    h = cfg["headings"]
    last = rounds[-1]
    lines = [f"# {'Manuscript' if scope == 'manuscript' else 'Submission package'} review rounds",
             "", "Generated by tools/review_round.py from .wf/review_rounds.json.", "",
             f"## {h[0]}", ""]
    for r in rounds:
        lines.append(f"- {r['id']} ({r['mode']}, {r['started_at']}): {len(r['reviewed'])} of "
                     f"{len(r['inputs'])} file(s) given to the medpaper-reviewer subagent")
    lines += ["", f"## {h[1]}", ""]
    for r in rounds:
        f = r.get("findings") or {}
        lines.append(f"- {r['id']}: " + ", ".join(f"{k} {f.get(k, 0)}" for k in SEVERITIES))
    lines += ["", f"## {h[2]}", ""]
    for r in rounds:
        for c in r.get("changes", []):
            lines.append(f"- {r['id']} {c['file']}: {c['summary']}")
        for n in r.get("not_changed", []):
            lines.append(f"- {r['id']} not changed - {n.get('item', '')}: {n.get('reason', '')}")
    lines += ["", f"## {h[3]}", "",
              f"- {last['id']}: hashes after the changes recorded at {last.get('closed_at')}; "
              "the gate fails if any covered file changes afterwards.", "", f"## {h[4]}", ""]
    for r in rounds:
        if r.get("user_decision"):
            lines.append(f"- {r['id']}: {r['user_decision']} - \"{r.get('user_words', '')}\"")
    if scope == "package":
        lines += ["", "The bundle is frozen in 08_submission/package_review_freeze.json after "
                  "the user's no-further-review answer."]
    path = Path(project) / cfg["summary"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def approved_round(project: Path, scope: str) -> dict | None:
    rnd = latest(project, scope)
    return rnd if rnd and rnd.get("user_decision") == DONE else None


def problems(project: Path, scope: str, decision: dict | None) -> list[str]:
    """Why the review point cannot advance (empty = the user ended review on current files)."""
    data = load(project)
    rounds = data[scope]
    if not rounds:
        return ["no review round on record: run tools/review_round.py start, give the "
                "medpaper-reviewer subagent the listed files, apply fixes, close, report"]
    out = []
    for prev, r in zip([None] + rounds[:-1], rounds):
        if r.get("mode") == "delta":
            missed = sorted(set(_changed_since(prev, r.get("inputs", {}))) - set(r.get("reviewed", [])))
            if missed:
                out.append(f"{r['id']} delta round skipped changed file(s): " + ", ".join(missed[:6]))
    last = rounds[-1]
    if not last.get("closed_at"):
        return out + [f"round {last['id']} is open: apply the fixes, then close and report it"]
    if last.get("user_decision") is None:
        return out + [f"round {last['id']} was reported; waiting for the user's single answer "
                      "(another round, or no further review)"]
    if last["user_decision"] == ANOTHER:
        return out + [f"the user asked for another review round after {last['id']}; start it"]
    try:
        drift = _changed_since(last, inputs(project, scope), project)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return out + [f"cannot inventory the review inputs: {exc}"]
    if drift:
        out.append(f"changed after review round {last['id']} closed (needs a new round; "
                   "--delta is fine): " + ", ".join(drift[:6]))
    cfg = SCOPES[scope]
    if not decision or decision.get("value") != cfg["value"]:
        out.append(f"approval decision {cfg['decision']}={cfg['value']} is not recorded")
    elif last["id"] not in str(decision.get("rationale", "")) or \
            str(decision.get("at", "")) < str(last.get("decided_at", "")):
        out.append(f"approval decision is not bound to the latest round {last['id']}")
    return out
