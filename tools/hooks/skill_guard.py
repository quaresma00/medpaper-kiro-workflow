#!/usr/bin/env python3
"""PreToolUse guard for skill activation. Stdlib only.

Wired as a PreToolUse hook on the skill-activation tool. Reads the hook payload on stdin,
looks the skill up in reference/skill_policy.toml, and:

    blocked  exit 2 with the pipeline route on stderr -> activation refused
    gated    exit 0 with a permissionDecision of "ask" -> operator confirms
    allow    exit 0, silent

Steering text asks the agent not to substitute a skill for a stage. This makes it so. The
difference matters: a rule can be summarized away during context compaction, a hook cannot.

Also usable directly, which is how the self test exercises it:

    python tools/hooks/skill_guard.py --explain write-paper
    python tools/hooks/skill_guard.py --audit          # policy vs installed skills
    echo '{"tool_input":{"name":"write-paper"}}' | python tools/hooks/skill_guard.py
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(os.environ.get("MEDPAPER_ROOT") or Path(__file__).resolve().parents[2])
POLICY = ROOT / "reference" / "skill_policy.toml"

EXIT_ALLOW = 0
EXIT_BLOCK = 2


def load_policy() -> tuple[dict[str, dict], str]:
    if not POLICY.exists():
        return {}, "allow"
    try:
        data = tomllib.loads(POLICY.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        print(f"skill_guard: malformed {POLICY.name}: {exc}", file=sys.stderr)
        return {}, "allow"
    entries = {}
    for item in data.get("skill", []):
        name = str(item.get("name", "")).strip()
        if name:
            entries[name] = item
    return entries, data.get("meta", {}).get("default", "allow")


def find_skill(payload: str, known: set[str]) -> str | None:
    """Pull the skill name out of the hook payload.

    Tries the documented shapes first, then falls back to scanning every string value in the
    JSON. The fallback exists because the payload schema varies between hosts and a guard that
    silently stops matching is worse than one that occasionally over-matches.
    """
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, TypeError):
        data = None

    if isinstance(data, dict):
        for path in (("tool_input", "name"), ("toolInput", "name"), ("input", "name"),
                     ("arguments", "name"), ("params", "name"), ("name",)):
            node = data
            for key in path:
                node = node.get(key) if isinstance(node, dict) else None
                if node is None:
                    break
            if isinstance(node, str) and node.strip() in known:
                return node.strip()

        found: list[str] = []

        def walk(node) -> None:
            if isinstance(node, str):
                if node.strip() in known:
                    found.append(node.strip())
            elif isinstance(node, dict):
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)

        walk(data)
        if found:
            return found[0]

    # Last resort: the payload may not be JSON at all.
    for name in sorted(known, key=len, reverse=True):
        if re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", payload or ""):
            return name
    return None


def block_message(name: str, item: dict) -> str:
    lines = [
        f"BLOCKED by the medpaper pipeline: the skill '{name}' would replace a pipeline stage.",
        "",
        f"Use instead: {item.get('replaced_by', 'the corresponding pipeline stage')}",
        "",
        (item.get("reason") or "").strip(),
        "",
        "Its output would land outside the paths the stage declares, so that stage's gate",
        "could never pass. Run `python tools/wf.py status` and follow the stage card.",
        "",
        f"To change this decision, edit reference/skill_policy.toml (entry: {name}).",
    ]
    return "\n".join(lines)


def ask_message(name: str, item: dict) -> str:
    return (
        f"'{name}' overlaps a pipeline stage. It is permitted as a helper at: "
        f"{item.get('use_at', 'the relevant stage')}. "
        f"{(item.get('reason') or '').strip()} "
        "Confirm only if its output will land at the path the stage declares; otherwise "
        "that stage's gate will not pass."
    )


def decide(name: str | None, entries: dict, default: str) -> int:
    if not name:
        return EXIT_ALLOW
    item = entries.get(name)
    verdict = (item or {}).get("verdict", default)

    if verdict == "blocked":
        print(block_message(name, item or {}), file=sys.stderr)
        return EXIT_BLOCK
    if verdict == "gated":
        print(json.dumps({"hookSpecificOutput": {
            "permissionDecision": "ask",
            "permissionDecisionReason": ask_message(name, item or {}),
        }}))
        return EXIT_ALLOW
    return EXIT_ALLOW


def cmd_explain(name: str, entries: dict, default: str) -> int:
    item = entries.get(name)
    if item is None:
        print(f"{name}: not in the policy -> default '{default}'")
        return 0
    print(f"{name}")
    print(f"  verdict     {item.get('verdict')}")
    for key in ("replaced_by", "use_at"):
        if item.get(key):
            print(f"  {key:<11} {item[key]}")
    reason = (item.get("reason") or "").strip()
    if reason:
        print("  reason")
        for line in reason.splitlines():
            print(f"    {line.strip()}")
    return 0


def cmd_audit(entries: dict, default: str) -> int:
    """Policy coverage against what is actually installed."""
    # Only the locations Kiro actually reads. Scanning other agents' directories would mix
    # in skills this workspace never sees and make the coverage numbers meaningless.
    roots = [Path.home() / ".kiro" / "skills", ROOT / ".kiro" / "skills"]
    installed: dict[str, list[str]] = {}
    for r in roots:
        if not r.is_dir():
            continue
        for d in sorted(r.iterdir()):
            if d.is_dir() and (d / "SKILL.md").exists():
                installed.setdefault(d.name, []).append(str(r))

    counts = {"blocked": [], "gated": [], "allow": [], "unlisted": []}
    for name in sorted(installed):
        verdict = entries.get(name, {}).get("verdict", "unlisted")
        counts.setdefault(verdict, []).append(name)

    print(f"policy: {POLICY.relative_to(ROOT).as_posix()}  (default: {default})")
    print(f"installed skills found: {len(installed)}\n")
    for verdict, label in (("blocked", "BLOCKED  (activation refused)"),
                           ("gated", "GATED    (asks first)"),
                           ("allow", "ALLOW    (no interference)"),
                           ("unlisted", "UNLISTED (falls through to default)")):
        names = counts.get(verdict, [])
        print(f"{label}  {len(names)}")
        for n in names:
            print(f"  {n}")
        print()

    orphans = sorted(set(entries) - set(installed))
    if orphans:
        print(f"in the policy but not installed: {', '.join(orphans)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="skill activation guard")
    ap.add_argument("--explain", metavar="SKILL")
    ap.add_argument("--audit", action="store_true")
    args = ap.parse_args()

    entries, default = load_policy()
    if args.explain:
        return cmd_explain(args.explain, entries, default)
    if args.audit:
        return cmd_audit(entries, default)

    payload = ""
    if not sys.stdin.isatty():
        try:
            payload = sys.stdin.read()
        except Exception:  # noqa: BLE001
            payload = ""
    return decide(find_skill(payload, set(entries)), entries, default)


if __name__ == "__main__":
    sys.exit(main())
