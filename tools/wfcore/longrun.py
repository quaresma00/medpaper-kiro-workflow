"""1.11.0 (#2g): long commands that an agent shell can wait for without polling.

`--wait` runs the same command as a child with its full output in a log file, prints one
heartbeat line every `heartbeat` seconds (so a shell with an idle timeout sees progress), stops
at `max_seconds`, and finally prints only the failure lines plus one summary line. The details
stay in the log. Used by `wf check`, `rework.py check`, `reproduce.py run` and `build_docx.py`.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

FAIL_RE = re.compile(r"\b(FAIL|BLOCK\w*|RED|ERROR|error|NOT REPRODUCED|refused|STOPPED|Traceback)\b")
MAX_FAIL_LINES = 20


def summarize(text: str) -> tuple[list[str], str]:
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    fails = [ln[:300] for ln in lines if FAIL_RE.search(ln)]
    tail = next((ln for ln in reversed(lines) if not ln.startswith("[wf] finished")), "")
    return fails[:MAX_FAIL_LINES], tail[:300]


def run_quiet(cmd: list[str], log: Path, label: str = "command", max_seconds: int = 3600,
              heartbeat: int = 60) -> int:
    log = Path(log)
    log.parent.mkdir(parents=True, exist_ok=True)
    cmd = [c for c in cmd if c not in ("--wait",)]
    if "--log" in cmd:  # the child writes to stdout -> our log; drop its own --log pair
        i = cmd.index("--log")
        del cmd[i:i + 2]
    env = {**os.environ, "MEDPAPER_WAIT_CHILD": "1", "PYTHONIOENCODING": "utf-8"}
    start = time.monotonic()
    with log.open("w", encoding="utf-8") as fh:
        proc = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT, env=env)
        nxt = heartbeat
        while True:
            try:
                rc = proc.wait(timeout=1)
                break
            except subprocess.TimeoutExpired:
                pass
            el = time.monotonic() - start
            if el >= max_seconds:
                proc.kill()
                rc = 124
                fh.write(f"\n[{label}] stopped after {max_seconds} s\n")
                break
            if el >= nxt:
                print(f"[{label}] running {int(el)} s (log: {log})", flush=True)
                nxt += heartbeat
        fh.write(f"\n[wf] finished rc={rc}\n")
    fails, tail = summarize(log.read_text(encoding="utf-8", errors="replace"))
    for ln in fails:
        print(ln)
    print(f"[{label}] rc={rc} in {int(time.monotonic() - start)} s; {len(fails)} failure line(s); "
          f"last: {tail}; full log: {log}", flush=True)
    return rc


def wrap(argv: list[str], log: Path | None, label: str, default_log: Path) -> int | None:
    """Return the child's exit code when this invocation should run as a waited child."""
    if os.environ.get("MEDPAPER_WAIT_CHILD") or "--wait" not in argv:
        return None
    return run_quiet([sys.executable, *argv], log or default_log, label)
