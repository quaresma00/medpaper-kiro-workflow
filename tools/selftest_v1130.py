"""1.13.0 regression tests from two real paper runs: isolation and working path (G1), data
never copied and one reproduction (G2), rewind rule / multi-person checks / protocol deviations
(G3), section polishing and Word without keep markers (G4), extras (G5). Synthetic fixtures
only - no real paper or dataset is read.

Called from tools/selftest.py.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from contextlib import contextmanager, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
WF = ROOT / "tools/wf.py"


def _env(**extra) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in ("MEDPAPER_PROJECT", "MEDPAPER_ROOT")}
    env["PYTHONIOENCODING"] = "utf-8"
    for k, v in extra.items():
        if v is None:
            env.pop(k, None)
        else:
            env[k] = str(v)
    return env


def _run(cmd, env=None, cwd=None, inp=None, timeout=600) -> subprocess.CompletedProcess:
    return subprocess.run([str(c) for c in cmd], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=env or _env(), cwd=str(cwd) if cwd else None,
                          input=inp, timeout=timeout)


def _wf(*args, env=None, cwd=None) -> subprocess.CompletedProcess:
    return _run([sys.executable, WF, *args], env=env, cwd=cwd)


def _out(p) -> str:
    return (p.stdout or "") + (p.stderr or "")


def _paper(path: Path) -> Path:
    from wfcore import registry
    from wfcore.state import State
    pipe = registry.load()
    path.mkdir(parents=True, exist_ok=True)
    State(path, ".wf").create(pipe.meta["name"], pipe.meta["version"], pipe.first().id)
    return path


@contextmanager
def _envset(**kv):
    old = {k: os.environ.get(k) for k in kv}
    for k, v in kv.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = str(v)
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _w(p: Path, rel: str, text) -> Path:
    t = p / rel
    t.parent.mkdir(parents=True, exist_ok=True)
    t.write_text(text if isinstance(text, str) else json.dumps(text), encoding="utf-8")
    return t


# ------------------------------------------------------------------------------ G1
def run_g1(tmp: Path, record, section) -> None:
    from wfcore import cli, datasources, integrity, paths
    section("1.13.0 G1: working path in place, isolation, engine integrity, engine fork")
    papers_root = Path(os.environ["MEDPAPER_PAPERS_ROOT"])

    ideas = tmp / "ideas"
    ws = ideas / "anticoag-idea"
    ws.mkdir(parents=True)
    (ws / "idea.md").write_text("# idea\n", encoding="utf-8")
    p = _wf("init", cwd=ws)
    record("G1 wf init makes the opened workspace folder the paper, in place (user files kept "
           "and never orphans; paper guard hook installed)",
           p.returncode == 0 and (ws / ".wf/state.json").is_file()
           and (ws / ".kiro/hooks/medpaper-paper-guard.json").is_file()
           and "idea.md" in paths.user_files(ws) and (ws / "idea.md").is_file(), _out(p)[-200:])
    c = _wf("clean", cwd=ws)
    record("G1 the user's own files are not reported as undeclared", "idea.md" not in c.stdout,
           c.stdout[-150:])
    ws2 = tmp / "ideas2" / "second"
    ws2.mkdir(parents=True)
    p = _wf("new", "second-paper", cwd=ws2)
    record("G1 wf new without --root/--central initialises the working directory in place",
           p.returncode == 0 and (ws2 / ".wf/state.json").is_file()
           and not (papers_root / "second-paper").exists(), _out(p)[-160:])
    p = _wf("init", cwd=ideas)
    record("G1 a folder that already holds another paper is refused, asks the user once and "
           "names no other paper", p.returncode == 2 and "already contains" in p.stdout
           and "anticoag-idea" not in p.stdout and "Ask the user once" in p.stdout,
           p.stdout[-220:])
    record("G1 a drive root and the home folder are never a paper",
           "drive root" in (paths.unsuitable_paper_dir(Path(ws.anchor)) or "")
           and "home folder" in (paths.unsuitable_paper_dir(Path.home()) or ""))

    # data sources in place
    data = tmp / "userdata" / "raw"
    data.mkdir(parents=True)
    (data / "a.csv").write_text("x\n1\n", encoding="utf-8")
    inner = ws / "datacopy"
    inner.mkdir()
    p = _wf("data", "add", str(data), "--name", "faers", cwd=ws)
    s = _wf("status", "--brief", cwd=ws)
    h = _wf("handoff", cwd=ws)
    record("G1 wf data add registers a dataset in place; status and handoff print the paper, "
           "the declared data sources and the engine path",
           p.returncode == 0 and "faers" in s.stdout and str(data) in s.stdout
           and "engine  " in s.stdout and "data: faers" in h.stdout and "engine:" in h.stdout
           and "paper:" in h.stdout, s.stdout[:240] + " | " + h.stdout[:200])
    other = _paper(tmp / "neighbours" / "other-paper")
    probs = [datasources.location_problem(ws, ideas), datasources.location_problem(ws, inner),
             datasources.location_problem(ws, other), datasources.location_problem(ws, "rel/x")]
    record("G1 a data folder holding the paper, a data folder whose parent is the paper, "
           "another paper's folder and a relative path are refused",
           all(probs) and "inside the data folder" in probs[0] and "parent" in probs[1]
           and "another paper" in probs[2] and "absolute" in probs[3], str(probs)[:300])
    calls = []
    real_sha = datasources._raw_sha

    def counting(path):
        calls.append(path)
        return real_sha(path)
    datasources._CACHES.clear()
    with patch.object(datasources, "_raw_sha", counting):
        first = datasources.inventory(ws)
        datasources._CACHES.clear()
        again = datasources.inventory(ws)
    record("G1 dataset hashes are computed lazily, once, and cached by size + mtime",
           len(calls) == 1 and first == again and first[0]["path"] == "datasource:faers/a.csv",
           str(first)[:160])

    # engine integrity
    with _envset(MEDPAPER_ENGINE_DEV=None):
        g = tmp / "git_engine"
        (g / "tools").mkdir(parents=True)
        (g / "tools/a.py").write_text("x = 1\n", encoding="utf-8")
        git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid",
               "-c", "commit.gpgsign=false", "-C", str(g)]
        _run(["git", "init", "-q", str(g)])
        _run([*git, "add", "-A"])
        _run([*git, "commit", "-q", "-m", "x"])
        clean = integrity.engine_state(g, use_cache=False)
        (g / "tools/a.py").write_text("x = 2\n", encoding="utf-8")
        modified = integrity.engine_state(g, use_cache=False)
        m = tmp / "zip_engine"
        (m / "tools").mkdir(parents=True)
        (m / "tools/a.py").write_text("x = 1\n", encoding="utf-8")
        unverifiable = integrity.engine_state(m, use_cache=False)[0]
        integrity.write_manifest(m)
        m_clean = integrity.engine_state(m, use_cache=False)[0]
        (m / "tools/b.py").write_text("y = 1\n", encoding="utf-8")
        m_mod = integrity.engine_state(m, use_cache=False)
        wt = tmp / "wt_engine"
        wt.mkdir()
        (wt / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
        fk = tmp / "fork_engine"
        fk.mkdir()
        (fk / "ENGINE_FORK.json").write_text("{}", encoding="utf-8")
        kinds = (integrity.engine_state(wt, use_cache=False)[0],
                 integrity.engine_state(fk, use_cache=False)[0])
    with _envset(MEDPAPER_ENGINE_DEV="1"):
        dev = integrity.engine_state(g, use_cache=False)[0]
    record("G1 engine integrity: git clean/modified, release-manifest clean/modified, "
           "unverifiable, maintenance worktree, fork and MEDPAPER_ENGINE_DEV",
           clean == ("clean", []) and modified[0] == "modified" and "tools/a.py" in modified[1]
           and unverifiable == "unverifiable" and m_clean == "clean"
           and m_mod[0] == "modified" and "tools/b.py" in m_mod[1]
           and kinds == ("worktree", "fork") and dev == "dev",
           str([clean, modified, unverifiable, m_clean, m_mod, kinds, dev])[:300])
    buf = StringIO()
    with patch.object(integrity, "engine_state",
                      return_value=("modified", ["tools/wfcore/checks/numbers.py"])), \
            _envset(MEDPAPER_PROJECT=ws):
        try:
            paths.project_dir()
            refused = ""
        except integrity.EngineModified as exc:
            refused = str(exc)
        with redirect_stdout(buf):
            rc = cli.main(["check"])
    record("G1 a modified global engine refuses paper commands and names the legal paths "
           "(paper overrides first, then a project-local fork)",
           "tools/wfcore/checks/numbers.py" in refused and "wf config set" in refused
           and "engine-fork" in refused and rc == 3 and "REFUSED" in buf.getvalue(),
           refused[:200])
    copy = tmp / "engine_copy"
    for tree in ("tools", "pipeline", "reference", ".kiro"):
        shutil.copytree(ROOT / tree, copy / tree,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    integrity.write_manifest(copy)
    tgt = copy / "tools/wfcore/numfmt.py"
    tgt.write_text(tgt.read_text(encoding="utf-8") + "\n# local edit\n", encoding="utf-8")
    p = _run([sys.executable, copy / "tools/wf.py", "status", "--brief"],
             env=_env(MEDPAPER_ENGINE_DEV=None), cwd=ws)
    q = _run([sys.executable, copy / "tools/reproduce.py", "check"],
             env=_env(MEDPAPER_ENGINE_DEV=None), cwd=ws)
    record("G1 end to end: an engine that differs from its release manifest refuses wf and "
           "reproduce.py", p.returncode == 3 and "REFUSED" in p.stdout
           and "tools/wfcore/numfmt.py" in p.stdout and q.returncode != 0 and "REFUSED" in _out(q),
           _out(p)[-200:] + " | " + _out(q)[-120:])
    shutil.rmtree(copy, ignore_errors=True)

    # project-local engine fork
    fp = tmp / "fork_ws"
    fp.mkdir()
    _wf("init", cwd=fp)
    p = _wf("engine-fork", "create", cwd=fp)
    fork = fp / ".wf/engine_fork"
    try:
        info = json.loads((fork / "ENGINE_FORK.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        info = {}
    steering = (fp / ".kiro/steering/medpaper-pipeline.md").read_text(encoding="utf-8")
    guard = (fp / ".kiro/hooks/medpaper-paper-guard.json").read_text(encoding="utf-8")
    from wfcore import registry
    ver = str(registry.load().meta.get("version"))
    record("G1 wf engine-fork create copies tools/pipeline/reference into <paper>/.wf/"
           "engine_fork (no .git, no .venv), records base version + hashes and re-points the "
           "paper's adapters", p.returncode == 0 and (fork / "tools/wf.py").is_file()
           and not (fork / ".git").exists() and not (fork / ".venv").exists()
           and info.get("base_version") == ver and len(info.get("files", {})) > 50
           and fork.as_posix() in steering and fork.as_posix() in guard, _out(p)[-200:])
    FW = fork / "tools/wf.py"
    s = _run([sys.executable, FW, "status", "--brief"], cwd=fp)
    record("G1 the fork drives its own paper (only the fork folder counts as engine)",
           s.returncode == 0 and "ENGINE FORK" in s.stdout, _out(s)[-200:])
    code = ("import sys; sys.path.insert(0, sys.argv[1]); from wfcore import paths; "
            "print(paths.in_engine(sys.argv[2]), paths.in_engine(sys.argv[3]), "
            "paths.in_engine(sys.argv[4]))")
    gp = _run([sys.executable, "-c", code, fork / "tools", ROOT / "tools/x.py", fp,
               fork / "tools/x.py"], cwd=fp)
    record("G1 from a fork the global engine stays protected and the paper is not 'over the "
           "engine'", gp.stdout.split() == ["True", "False", "True"], _out(gp)[-160:])
    o = _run([sys.executable, FW, "status", "--brief"], env=_env(MEDPAPER_PROJECT=other), cwd=tmp)
    record("G1 a fork drives no other paper", o.returncode != 0 and "belongs to" in _out(o),
           _out(o)[-160:])
    edit = fork / "tools/wfcore/numfmt.py"
    edit.write_text(edit.read_text(encoding="utf-8") + "\n# paper-local fix\n", encoding="utf-8")
    d = _run([sys.executable, FW, "engine-fork", "diff"], cwd=fp)
    diff_file = fp / ".wf/engine_fork.diff"
    hd = _run([sys.executable, FW, "handoff"], cwd=fp)
    import selftest_v180 as v180
    gate = v180._gate(fp, "engine_fork_recorded", "S25_submission_audit")
    record("G1 wf engine-fork diff records the change for the maintainer; handoff and the S25 "
           "check show it", d.returncode == 0 and "M tools/wfcore/numfmt.py" in d.stdout
           and diff_file.is_file() and "+# paper-local fix" in diff_file.read_text(encoding="utf-8")
           and "1 file(s) differ" in hd.stdout and gate.ok and "1 changed file" in gate.detail,
           _out(d)[-160:] + " | " + gate.detail)
    r = _wf("engine-fork", "remove", cwd=fp)
    steering = (fp / ".kiro/steering/medpaper-pipeline.md").read_text(encoding="utf-8")
    record("G1 wf engine-fork remove deletes the fork, keeps the diff and points the adapters "
           "back at the global engine", r.returncode == 0 and not fork.exists()
           and diff_file.is_file() and ROOT.as_posix() in steering
           and fork.as_posix() not in steering, _out(r)[-160:])
    run_guard(tmp, record, ws)


def run_guard(tmp: Path, record, hook_paper: Path) -> None:
    from wfcore import datasources
    sys.path.insert(0, str(ROOT / "tools/hooks"))
    import paper_guard
    hook = json.loads((hook_paper / ".kiro/hooks/medpaper-paper-guard.json").read_text(
        encoding="utf-8"))["hooks"][0]
    record("G1 the paper guard is a v1 PreToolUse command hook matching the file, search, "
           "shell and subagent tools", hook["trigger"] == "PreToolUse"
           and hook["action"]["type"] == "command" and "paper_guard.py" in hook["action"]["command"]
           and "--paper" in hook["action"]["command"]
           and all(t in hook["matcher"] for t in ("read_file", "list_directory", "grep_search",
                                                   "file_search", "fs_write", "str_replace",
                                                   "delete_file", "smart_relocate",
                                                   "execute_pwsh", "[Ss]ub_?[Aa]gent")))
    g = tmp / "guard"
    cur = _paper(g / "ws" / "paper_a")
    other = _paper(g / "ws" / "paper_b")
    central = g / "central"
    _paper(central / "c1")
    data = g / "data"
    _w(data, "raw.csv", "x\n1\n")
    datasources.add(cur, data, "d")
    archive = g / "medpaper_archive_2026"
    _w(archive, "x.md", "x")
    systemp = g / "systemp"
    (systemp / "medpaper_repro_abc").mkdir(parents=True)
    E = ROOT.as_posix()

    def sh(cmd, cwd=None):
        return {"tool_name": "execute_pwsh", "tool_input": {"command": cmd, "cwd": str(cwd or cur)}}

    cases = [
        ("read own file", {"tool_name": "read_file", "tool_input": {"path": "01_protocol/idea.json"}}, False),
        ("read an engine card", {"tool_name": "read_file", "tool_input": {"path": f"{E}/pipeline/stages/S01_intake.md"}}, False),
        ("fs_write into the engine", {"tool_name": "fs_write", "tool_input": {"path": f"{E}/tools/wfcore/checks/numbers.py", "text": "x"}}, True),
        ("str_replace in the engine", {"tool_name": "str_replace", "tool_input": {"path": f"{E}/tools/wfcore/bibrules.py", "oldStr": "a", "newStr": "b"}}, True),
        ("read another paper", {"tool_name": "read_file", "tool_input": {"path": str(other / "02_data/acquisition/01_acquire.py")}}, True),
        ("list a folder holding other papers", {"tool_name": "list_directory", "tool_input": {"path": str(g / "ws")}}, True),
        ("relative escape to a sibling paper", {"tool_name": "read_file", "tool_input": {"path": "../paper_b/notes.md"}}, True),
        ("grep inside another paper", {"tool_name": "grep_search", "tool_input": {"query": "x", "includePattern": str(other) + "/**/*.py"}}, True),
        ("glob over sibling papers", {"tool_name": "file_search", "tool_input": {"query": "x", "includePattern": str(g / "ws") + "/*/02_data"}}, True),
        ("the central papers root", {"tool_name": "list_directory", "tool_input": {"path": str(central)}}, True),
        ("an archive folder", {"tool_name": "read_file", "tool_input": {"path": str(archive / "x.md")}}, True),
        ("read a declared data source", {"tool_name": "read_file", "tool_input": {"path": str(data / "raw.csv")}}, False),
        ("write a declared data source", {"tool_name": "fs_write", "tool_input": {"path": str(data / "raw.csv"), "text": "x"}}, True),
        ("write to an invented location", {"tool_name": "fs_write", "tool_input": {"path": str(g / "studies/new/a.md"), "text": "x"}}, True),
        ("delete a paper file", {"tool_name": "delete_file", "tool_input": {"targetFile": "temp/x.txt"}}, False),
        ("relocate out of the paper", {"tool_name": "smart_relocate", "tool_input": {"sourcePath": "temp/x.txt", "destinationPath": str(g / "elsewhere.txt")}}, True),
        ("shell: read another paper", sh(f'Get-Content "{other}\\notes.md"'), True),
        ("shell: engine command, log in the paper", sh(f'python "{E}/tools/wf.py" status *> .wf/logs/status.txt'), False),
        ("shell: write into the engine", sh(f'Set-Content -Path "{E}/tools/x.py" -Value 1'), True),
        ("shell: git checkout in the engine", sh(f'git -C "{E}" checkout -- tools/wfcore/bibrules.py'), True),
        ("shell: python one-liner writes the engine", sh(f"python -c \"from pathlib import Path; p = Path(r'{E}/tools/x.py'); p.write_text('1')\""), True),
        ("shell: stray log in the system temp", sh(f'python x.py *> "{systemp}\\repro12.txt"'), True),
        ("shell: clean an engine-managed sandbox", sh(f'Remove-Item -Recurse -Force "{systemp}\\medpaper_repro_abc"'), False),
        ("shell: relative escape", sh("Get-ChildItem ..\\paper_b\\02_data"), True),
        ("shell: cwd in another paper", sh("Get-ChildItem", cwd=other), True),
        ("shell: copy an engine template into the paper", sh(f'Copy-Item "{E}/tools/analysis/results.py" temp/results_copy.py'), False),
        ("subagent prompt naming another paper", {"tool_name": "invoke_subagent", "tool_input": {"prompt": f"Compare with {other}\\07_manuscript"}}, True),
        ("subagent prompt about this paper", {"tool_name": "invoke_subagent", "tool_input": {"prompt": "Review .wf/review_bundle/M001/report.md"}}, False),
    ]
    wrong = []
    with _envset(MEDPAPER_PAPERS_ROOT=central, MEDPAPER_GUARD_TEMP=systemp):
        guard = paper_guard.Guard(cur)
        for label, payload, blocked in cases:
            try:
                got = guard.decide(payload)
            except Exception as exc:  # noqa: BLE001
                got = f"ERROR {exc!r}"
                blocked = not blocked
            if bool(got) != blocked:
                wrong.append(f"{label}: {'allowed' if not got else got[:90]}")
    record(f"G1 paper guard: {len(cases)} tool shapes allow the paper/engine reads/data reads/"
           "sandboxes and block other papers, the central root, archives, stray temp, data "
           "writes, invented locations and every engine write", not wrong, "; ".join(wrong)[:600])
    env = _env(MEDPAPER_PAPERS_ROOT=central, MEDPAPER_GUARD_TEMP=systemp)
    gpath = ROOT / "tools/hooks/paper_guard.py"
    deny = _run([sys.executable, gpath, "--paper", cur], env=env, inp=json.dumps(cases[2][1]))
    junk = _run([sys.executable, gpath, "--paper", cur], env=env, inp="not json {")
    ok_ = _run([sys.executable, gpath, "--paper", cur], env=env, inp=json.dumps(cases[0][1]))
    record("G1 paper guard as a process: exit 2 with the reason on stderr; unparseable payload "
           "and allowed calls exit 0", deny.returncode == 2
           and "BLOCKED by the medpaper paper guard" in deny.stderr and "engine-fork" in deny.stderr
           and junk.returncode == 0 and ok_.returncode == 0, deny.stderr[-200:])


def run(tmp: Path, record, section) -> None:
    tmp.mkdir(parents=True, exist_ok=True)
    run_g1(tmp / "g1", record, section)
