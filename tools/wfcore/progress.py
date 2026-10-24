"""1.11.0 (#3g): the paper's own progress file, so an interrupted agent resumes from the paper.

    <paper>/.wf/progress.md   rewritten after every wf / rework / review_round command:
                              current stage, open revision round, open review round, the last
                              command and its result. Working state lives in the paper
                              (temp/ for scratch, .wf/ for state), never in external temp folders.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

REL = ".wf/progress.md"


def project_arg(argv: list[str]) -> Path | None:
    """The --project value of a tool's command line, if any."""
    for i, a in enumerate(argv):
        if a == "--project" and i + 1 < len(argv):
            return Path(argv[i + 1])
        if a.startswith("--project="):
            return Path(a.split("=", 1)[1])
    return None


def write(project: Path, command: str, rc: int | None, detail: str = "") -> Path | None:
    try:
        project = Path(project)
        state_file = project / ".wf/state.json"
        if not state_file.is_file():
            return None
        st = json.loads(state_file.read_text(encoding="utf-8"))
        lines = ["# Paper progress (written by the engine; do not edit)", "",
                 f"- updated: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
                 f"- current stage: {st.get('current')}",
                 f"- engine pin: {st.get('engine_pin') or st.get('pipeline_version')}"]
        rev_id = st.get("active_revision_round")
        if rev_id:
            try:
                rev = json.loads((project / ".wf/revisions" / f"{rev_id}.json").read_text(encoding="utf-8"))
                lines.append(f"- open revision round: {rev_id} ({rev.get('status')}, "
                             f"{len(rev.get('items', []))} item(s); `rework.py status`)")
            except (OSError, ValueError):
                lines.append(f"- open revision round: {rev_id}")
        try:
            from . import reviewrounds as rr
            data = rr.load(project)
            for scope in rr.SCOPES:
                last = data[scope][-1] if data[scope] else None
                if last and (not last.get("closed_at") or last.get("user_decision") is None):
                    state = "open" if not last.get("closed_at") else "awaiting the user's answer"
                    lines.append(f"- review round {last['id']} ({scope}): {state}")
        except Exception:  # noqa: BLE001 - progress must never break a command
            pass
        last_note = (st.get("handoff") or [{}])[-1] if isinstance(st.get("handoff"), list) else {}
        if isinstance(last_note, dict) and last_note.get("text"):
            lines.append(f"- last handoff note: {str(last_note['text'])[:200]}")
        lines.append(f"- last command: `{command}` -> "
                     + ("rc=?" if rc is None else f"rc={rc}") + (f" ({detail[:200]})" if detail else ""))
        lines += ["", "Resume: run `wf status` (it prints the stage card); scratch goes in temp/."]
        out = project / REL
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return out
    except Exception:  # noqa: BLE001
        return None
