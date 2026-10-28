#!/usr/bin/env python3
"""PreToolUse isolation guard for one paper workspace (1.13.0). Stdlib only, fast.

Installed into every paper by `wf init` and `install_adapters.py --paper <dir>` as
.kiro/hooks/medpaper-paper-guard.json. Kiro runs it before a matching tool call with the call
as JSON on stdin; exit 2 blocks the call and the reason on stderr is shown to the agent.

Allowed: the current paper (read/write), the global engine (read only), the paper's declared
data sources (read only), the system temp only for engine-managed medpaper_* sandboxes.
Blocked:
  - any write, delete, move or rename that touches the global engine (or ~/.medpaper and the
    user-level medpaper skill/agents, which are engine-generated);
  - any read, list, search or write that touches another paper (a folder with .wf/state.json
    that is not this paper), a folder that holds other papers, the central papers root outside
    this paper, an archive folder (medpaper_archive*, or `guard_deny` paths in
    ~/.medpaper/config.toml), or the system temp outside medpaper_* sandboxes;
  - file-tool writes outside this paper (never invent a location; data sources are read-only);
  - hand edits of the engine-owned state inside this paper (.wf/state.json, progress.md,
    review_rounds.json, revisions/, ...; ENGINE_STATE) - only engine commands write them;
  - shell commands referencing such paths (engine writes, other papers, stray temp logs).
An unparseable payload or an internal error is allowed (fail open): the engine commands refuse
other papers and a modified engine on their own (paths.project_dir, wfcore/integrity.py).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

WRITE_TOOL_RE = re.compile(r"(?i)write|replace|append|delete|remove|relocate|rename|move|edit|"
                           r"create|insert|patch")
SHELL_TOOL_RE = re.compile(r"(?i)pwsh|powershell|bash|shell|execute|command|terminal")
NAME_KEYS = ("tool_name", "toolName", "tool", "name")
INPUT_KEYS = ("tool_input", "toolInput", "input", "arguments", "args", "parameters", "params")
TARGET_KEYS = frozenset(k.casefold() for k in (
    "path", "paths", "file", "files", "file_path", "filepath", "filename", "target_file",
    "targetfile", "target", "target_path", "targetpath", "source", "source_path", "sourcepath",
    "destination", "destination_path", "destinationpath", "dest", "new_path", "newpath",
    "old_path", "oldpath", "directory", "dir", "folder", "includepattern", "include_pattern",
    "root"))
ABS_RE = re.compile(r"(?:[A-Za-z]:[\\/]|\\\\[^\\/\s\"']+[\\/])[^\s\"'<>|;,`()]*")
DOTS_RE = re.compile(r"(?:^|(?<=[\s\"'=(,]))(?:~|\.{1,2})[\\/][^\s\"'<>|;,`()]*|"
                     r"[^\s\"'<>|;,`()]*[\\/]\.\.(?:[\\/][^\s\"'<>|;,`()]*)?")
QUOTED_RE = re.compile(r"\"([^\"\r\n]+)\"|'([^'\r\n]+)'")
GLOB_CHARS = "*?["
SEG_RE = re.compile(r"\r?\n|;|&&|\|\||\|")
REDIRECT_RE = re.compile(r"(?:\d|\*)?>>?\s*(\"[^\"]+\"|'[^']+'|[^\s;|&\"']+)")
WRITE_VERBS = frozenset({
    "set-content", "add-content", "out-file", "new-item", "remove-item", "move-item",
    "copy-item", "rename-item", "clear-content", "tee-object", "expand-archive",
    "compress-archive", "rm", "del", "erase", "rd", "rmdir", "mv", "move", "cp", "copy", "ren",
    "rename", "mkdir", "md", "ni", "sc", "ac", "ri", "mi", "cpi", "rni", "clc", "robocopy",
    "xcopy", "tee", "touch", "truncate", "mklink"})
COPY_VERBS = frozenset({"copy-item", "cp", "copy", "cpi", "move-item", "mv", "move", "mi",
                        "robocopy", "xcopy"})
GIT_WRITE_RE = re.compile(r"(?i)\b(checkout|commit|apply|reset|stash|clean|restore|rm|mv|add|"
                          r"merge|pull|am|cherry-pick|rebase|revert|switch|worktree|init|clone|"
                          r"update-index)\b")
PY_WRITE_RE = re.compile(r"write_text|write_bytes|\.write\(|open\([^)]*['\"](?:w|a|x|r\+|wb|ab|"
                         r"w\+|a\+)['\"]|shutil\.(?:copy|move|rmtree)|os\.(?:remove|unlink|rename|"
                         r"replace|makedirs|mkdir|link|symlink|rmdir)|\.unlink\(|\.rename\(|"
                         r"\.replace\(\s*[\w\"']*[\\/]|\.mkdir\(|\.touch\(")
PY_ASSIGN_RE = re.compile(r"\b(\w+)\s*=\s*(?:Path\()?r?[\"']([^\"'\r\n]+)[\"']")
# 1.13.0 (G5): engine-owned paper state; agents read it, only engine commands write it. Paper-
# owned .wf files stay writable (overrides.toml, language_allowlist.json, user_files.json,
# logs/, review_bundle/<round>/report.md, writer_bundle/, engine_fork/).
_ENGINE_STATE_NAMES = ("state.json", "progress.md", "review_rounds.json", "check_receipts.json",
                       "data_sources.json", "hash_cache.json", "final_copy.json",
                       "presentation_deltas.json", "review_coverage.json", "reference_live.json")
ENGINE_STATE = frozenset(os.path.normcase(f".wf/{n}").replace("\\", "/")
                         for n in _ENGINE_STATE_NAMES)
ENGINE_STATE_DIRS = tuple(os.path.normcase(d).replace("\\", "/")
                          for d in (".wf/revisions/", ".wf/repro/rerun/", ".wf/review_reports/"))
COPY_DATA_RE = re.compile(r"(?i)\b(?:copy-item|cpi|cp|copy|robocopy|xcopy|move-item|mv|move|"
                          r"expand-archive|unzip|mklink|hardlink)\b|extractall|\.extract\(|"
                          r"\b7z\s+[xe]\b|\btar\s+-?\w*x|os\.link|shutil\.(?:copy\w*|move)")


def _norm(p: Path | str) -> str:
    return os.path.normcase(os.path.abspath(str(p)))


def _within(child: Path, parent: Path) -> bool:
    a, b = _norm(child), _norm(parent)
    try:
        return os.path.commonpath([a, b]) == b
    except ValueError:
        return False


def _trim(raw: str) -> str:
    raw = raw.strip().strip("\"'`").rstrip(",;)")
    if raw.endswith(":") and not re.fullmatch(r"[A-Za-z]:", raw):
        raw = raw[:-1]
    if raw.endswith(".") and not raw.endswith(".."):
        raw = raw[:-1]
    return raw


def _resolve(raw: str, base: Path) -> Path | None:
    raw = _trim(raw)
    if not raw or len(raw) > 1000:
        return None
    raw = re.sub(r"(?i)\$\{?env:(\w+)\}?", lambda m: os.environ.get(m[1], m[0]), raw)
    raw = os.path.expandvars(raw)
    if raw.startswith("~"):
        raw = os.path.expanduser(raw)
    if raw.startswith(("file:///", "file://")):
        raw = raw.split("://", 1)[1].lstrip("/") if re.match(r"file:///[A-Za-z]:", raw) else raw[7:]
    try:
        p = Path(raw)
        p = p if p.is_absolute() else base / p
        return Path(os.path.abspath(str(p)))
    except (OSError, ValueError):
        return None


class Guard:
    def __init__(self, paper: Path, temp: Path | None = None):
        from wfcore import datasources, paths
        self.paper = Path(os.path.abspath(str(paper)))
        self.engines = [e for e in paths.engine_roots() if not paths.is_fork_root(e)]
        home = Path.home()
        self.engine_user = [home / ".medpaper", home / ".kiro" / "skills" / "medpaper-pipeline"]
        self.kiro = home / ".kiro"
        self.data = [Path(p) for p in datasources.paths_of(self.paper)]
        try:
            self.papers_root = paths.papers_root()[0]
        except SystemExit:
            self.papers_root = None
        self.deny = []
        try:
            cfg = paths.user_config()
            self.deny = [Path(x) for x in cfg.get("guard_deny", []) if isinstance(x, str)]
        except SystemExit:
            pass
        env_temp = os.environ.get("MEDPAPER_GUARD_TEMP")
        self.temp = Path(env_temp) if env_temp else (temp or Path(tempfile.gettempdir()))
        self._memo: dict[str, str] = {}

    # ------------------------------------------------------------------ classification
    def _other_paper(self, p: Path) -> Path | None:
        for anc in [p, *p.parents]:
            if _norm(anc) == _norm(self.paper):
                return None
            try:
                if (anc / ".wf" / "state.json").is_file():
                    return anc
            except OSError:
                return None
        return None

    def _holds_paper(self, d: Path) -> bool:
        try:
            if not d.is_dir():
                return False
        except OSError:
            return False
        seen = 0
        frontier = [d]
        for _depth in range(2):
            nxt = []
            for base in frontier:
                try:
                    entries = list(os.scandir(base))
                except OSError:
                    continue
                for e in entries:
                    seen += 1
                    if seen > 4000:
                        return False
                    if not e.is_dir(follow_symlinks=False) or e.name.startswith("$"):
                        continue
                    sub = Path(e.path)
                    if _norm(sub) == _norm(self.paper) or any(_norm(sub) == _norm(x)
                                                              for x in self.engines):
                        continue
                    if (sub / ".wf" / "state.json").is_file():
                        return True
                    nxt.append(sub)
            frontier = nxt
        return False

    def classify(self, p: Path, *, directory_scan: bool = False) -> str:
        key = _norm(p) + ("|d" if directory_scan else "")
        if key in self._memo:
            return self._memo[key]
        out = self._classify(p, directory_scan)
        self._memo[key] = out
        return out

    def _classify(self, p: Path, directory_scan: bool) -> str:
        if _within(p, self.paper):
            rel = os.path.relpath(_norm(p), _norm(self.paper)).replace("\\", "/")
            if rel in ENGINE_STATE or rel.startswith(ENGINE_STATE_DIRS):
                return "paper_state"
            return "paper"
        if any(_within(p, e) for e in self.engines):
            return "engine"
        if any(_within(p, e) for e in self.engine_user) or (
                _norm(p.parent) == _norm(self.kiro / "agents") and p.name.startswith("medpaper-")):
            return "engine"
        if any(_within(p, d) for d in self.data):
            return "data"
        if self._other_paper(p) is not None:
            return "other_paper"
        if self.papers_root is not None and _within(p, self.papers_root):
            return "papers_root"
        if any(part.casefold().startswith("medpaper_archive") for part in p.parts) or any(
                _within(p, d) for d in self.deny):
            return "archive"
        if _within(p, self.temp):
            rel = Path(os.path.relpath(_norm(p), _norm(self.temp))).parts
            return "temp_sandbox" if rel and rel[0].casefold().startswith("medpaper_") else "temp"
        if _within(p, self.kiro):
            return "kiro"
        if self._holds_paper(p):  # an existing folder with other papers below it (2 levels)
            return "holds_papers"
        return "outside"

    # ------------------------------------------------------------------ decisions
    READ_DENY = {
        "other_paper": "it is another paper's folder; papers are isolated - never read, list, "
                       "search or copy another paper (ask the user for what you need)",
        "holds_papers": "this folder holds other papers; listing or searching it exposes them",
        "papers_root": "it is inside the central papers root, which holds other papers",
        "archive": "it is an archive folder; archived papers are never read",
        "temp": "it is the system temp folder; logs and scratch live in this paper "
                "(.wf/logs/, temp/) - only engine-managed medpaper_* sandboxes are allowed there",
    }
    WRITE_DENY = {
        "engine": "the shared medpaper engine is read-only for paper sessions. Legal paths: "
                  "paper overrides (wf config set, wf override init, target_journal.json), then "
                  "a project-local engine fork (wf engine-fork create)",
        "data": "it is a declared data source - read-only, used in place; derived analysis "
                "datasets go to 02_data/derived/",
        "outside": "it is outside this paper; files are written only inside the paper folder "
                   "(never invent a location such as a 'studies' folder next to the data)",
        "paper_state": "it is the engine's record of this paper (written only by wf / rework.py / "
                       "review_round.py / reproduce.py); never hand-edit it - use the command "
                       "that owns it (wf note, wf decide, wf loop, review_round.py, rework.py), "
                       "or ask the user",
        "kiro": None,
        "temp_sandbox": None,
        "paper": None,
    }

    def _deny_read(self, p: Path, cls: str, what: str) -> str | None:
        why = self.READ_DENY.get(cls)
        return f"{what} {p}: {why}" if why else None

    def _deny_write(self, p: Path, cls: str, what: str) -> str | None:
        if cls in self.READ_DENY:
            return self._deny_read(p, cls, what)
        why = self.WRITE_DENY.get(cls, self.WRITE_DENY["outside"])
        return f"{what} {p}: {why}" if why else None

    def _glob_dir(self, raw: str, base: Path) -> Path | None:
        cut = min((raw.find(c) for c in GLOB_CHARS if c in raw), default=-1)
        if cut < 0:
            return None
        head = raw[:cut]
        head = head[:max(head.rfind("/"), head.rfind("\\")) + 1] or "."
        return _resolve(head, base)

    def check_path(self, raw: str, base: Path, *, write: bool, what: str) -> str | None:
        gdir = self._glob_dir(raw, base)
        if gdir is not None:
            cls = self.classify(gdir, directory_scan=True)
            hit = self._deny_write(gdir, cls, what) if write else self._deny_read(gdir, cls, what)
            if hit:
                return hit
            return None
        p = _resolve(raw, base)
        if p is None:
            return None
        cls = self.classify(p)
        return self._deny_write(p, cls, what) if write else self._deny_read(p, cls, what)

    # ------------------------------------------------------------------ text scanning
    @staticmethod
    def path_tokens(text: str) -> list[str]:
        found: list[str] = []
        for m in QUOTED_RE.finditer(text):
            s = m.group(1) or m.group(2) or ""
            if ABS_RE.match(s) or s.startswith(("~/", "~\\", "./", ".\\", "../", "..\\")) \
                    or re.search(r"[\\/]\.\.(?:[\\/]|$)", s):
                found.append(s)
        found += [m.group(0) for m in ABS_RE.finditer(text)]
        found += [m.group(0) for m in DOTS_RE.finditer(text)]
        out, seen = [], set()
        for s in found:
            s = _trim(s)
            if s and s not in seen:
                seen.add(s)
                out.append(s)
        return out

    def scan_text(self, text: str, base: Path, what: str) -> str | None:
        for tok in self.path_tokens(text):
            hit = self.check_path(tok, base, write=False, what=what)
            if hit:
                return hit
        return None

    # ------------------------------------------------------------------ shell
    @staticmethod
    def _split(seg: str) -> list[str]:
        out, buf, q = [], [], None
        for ch in seg:
            if q:
                if ch == q:
                    q = None
                else:
                    buf.append(ch)
            elif ch in "\"'":
                q = ch
            elif ch.isspace():
                if buf:
                    out.append("".join(buf))
                    buf = []
            else:
                buf.append(ch)
        if buf:
            out.append("".join(buf))
        return out

    def check_shell(self, command: str, cwd: Path) -> str | None:
        hit = self.check_path(str(cwd), cwd, write=False, what="shell working directory")
        if hit:
            return hit
        expanded = re.sub(r"(?i)\$\{?env:(\w+)\}?", lambda m: os.environ.get(m[1], m[0]), command)
        hit = self.scan_text(expanded, cwd, "shell command references")
        if hit:
            return hit
        if COPY_DATA_RE.search(expanded):
            for tok in self.path_tokens(expanded):
                p = _resolve(tok, cwd)
                if p is not None and self.classify(p) == "data":
                    return (f"shell command copies, links or extracts the declared data source "
                            f"{p}: never copy the user's dataset into the paper - read it in "
                            "place (analysis.datasources.source_path / open_member, R "
                            "medpaper_source_path / medpaper_unz)")
        targets: list[str] = []
        for m in REDIRECT_RE.finditer(expanded):
            tgt = m.group(1).strip("\"'")
            if tgt and not tgt.startswith(("&", "$null")) and tgt.casefold() not in ("null", "nul"):
                targets.append(tgt)
        for seg in SEG_RE.split(expanded):
            toks = [t for t in self._split(seg.strip()) if t]
            while toks and toks[0] in ("&", "."):
                toks = toks[1:]
            if not toks:
                continue
            verb = Path(toks[0]).name.casefold().removesuffix(".exe")
            args = [t for t in toks[1:] if not t.startswith("-") and t not in ("&", "|")]
            if verb in COPY_VERBS:
                low = [t.casefold() for t in toks]
                dest = None
                for flag in ("-destination", "-dest"):
                    if flag in low and low.index(flag) + 1 < len(toks):
                        dest = toks[low.index(flag) + 1]
                if verb in ("robocopy", "xcopy") and len(args) >= 2:
                    targets.append(args[1])
                elif dest is not None:
                    targets.append(dest)
                elif args:
                    targets.append(args[-1])
                if verb in ("move-item", "mv", "move", "mi") and args:
                    targets.extend(args[:-1] if dest is None else args)
            elif verb in WRITE_VERBS:
                targets.extend(args)
            elif verb == "git" and GIT_WRITE_RE.search(" ".join(toks[1:])):
                low = [t.casefold() for t in toks]
                repo = toks[low.index("-c") + 1] if "-c" in low and low.index("-c") + 1 < len(toks) \
                    else str(cwd)
                targets.append(repo)
        # Python one-liners / heredocs: a line that writes names its target or a variable.
        assigned = {m[1]: m[2] for m in PY_ASSIGN_RE.finditer(expanded)}
        for line in expanded.splitlines():
            if not PY_WRITE_RE.search(line):
                continue
            targets.extend(self.path_tokens(line))
            targets.extend(re.findall(r"['\"]([^'\"\r\n]*\.wf[\\/][^'\"\r\n]+)['\"]", line))
            for var, val in assigned.items():
                if re.search(rf"\b{re.escape(var)}\b", line):
                    targets.append(val)
        for tgt in targets:
            hit = self.check_path(tgt, cwd, write=True, what="shell command writes")
            if hit:
                return hit
        return None

    # ------------------------------------------------------------------ entry
    def decide(self, payload: dict) -> str | None:
        name = ""
        for k in NAME_KEYS:
            if isinstance(payload.get(k), str):
                name = payload[k]
                break
        args = None
        for k in INPUT_KEYS:
            val = payload.get(k)
            if isinstance(val, str) and val.lstrip().startswith(("{", "[")):
                try:
                    val = json.loads(val)
                except ValueError:
                    pass
            if isinstance(val, (dict, list)):
                args = val
                break
        if args is None:
            args = {k: v for k, v in payload.items() if k not in NAME_KEYS}
        base = self.paper
        cwd_raw = (args.get("cwd") if isinstance(args, dict) else None) or payload.get("cwd")
        cwd = _resolve(cwd_raw, self.paper) if isinstance(cwd_raw, str) and cwd_raw else self.paper
        cwd = cwd or self.paper
        command = args.get("command") if isinstance(args, dict) else None
        is_shell = isinstance(command, str) and (SHELL_TOOL_RE.search(name) or not name)
        if is_shell:
            return self.check_shell(command, cwd)
        is_write = bool(WRITE_TOOL_RE.search(name)) if name else bool(
            isinstance(args, dict) and ({"text", "newstr", "content", "newStr"} & set(args)))
        problems: list[str | None] = []

        def walk(node, key=""):
            if isinstance(node, dict):
                for k, v in node.items():
                    walk(v, str(k))
            elif isinstance(node, list):
                for v in node:
                    walk(v, key)
            elif isinstance(node, str) and node:
                if key.casefold() in TARGET_KEYS or key.casefold().endswith(("path", "file")):
                    problems.append(self.check_path(node, base, write=is_write,
                                                    what=("write to" if is_write else "access to")))
                elif key.casefold() != "cwd":
                    problems.append(self.scan_text(node, base, "reference to"))
        walk(args)
        return next((p for p in problems if p), None)


def find_paper(arg: str | None) -> Path | None:
    if arg:
        p = Path(arg)
        if (p / ".wf" / "state.json").is_file():
            return p
    try:
        here = Path.cwd().resolve()
    except OSError:
        return None
    for cand in [here, *here.parents]:
        if (cand / ".wf" / "state.json").is_file():
            return cand
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="medpaper paper isolation guard (PreToolUse hook)")
    ap.add_argument("--paper", help="the paper this workspace belongs to")
    args = ap.parse_args(argv)
    try:
        raw = "" if sys.stdin is None or sys.stdin.isatty() else sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else None
    except (OSError, ValueError):
        return 0
    if not isinstance(payload, dict):
        return 0
    paper = find_paper(args.paper)
    if paper is None:
        return 0
    try:
        reason = Guard(paper).decide(payload)
    except Exception:  # noqa: BLE001 - fail open; the engine commands guard themselves
        return 0
    if reason:
        print(f"BLOCKED by the medpaper paper guard: {reason}. This workspace is the paper "
              f"{paper}; it may read and write only itself, read the engine and its declared "
              "data sources (wf data list).", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
