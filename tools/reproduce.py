#!/usr/bin/env python3
"""Re-execute the paper's analysis in a sandbox and prove the results are identical.

    python "<engine>/tools/reproduce.py" run [--wait] [--log FILE] [--full] [--force]
                                         [--timeout SECONDS] [--keep-sandbox] [--project DIR]
    python "<engine>/tools/reproduce.py" check [--project DIR]

`run` re-runs every top-level 03_analysis/code script in the order declared by
03_analysis/analysis_manifest.json (filename order, with a warning, when the paper has none),
compares each results JSON with the original (volatile timestamps ignored), keeps the re-run
results in <paper>/.wf/repro/rerun/ as evidence and writes 03_analysis/reproducibility_report.json.
Acquisition is never re-run. `check` runs the analysis_reproduces gate logic and prints the
cheapest next command. Exit 0 = identical, 2 = not reproduced, 1 = refused.

1.13.0: the sandbox is <paper>/.wf/repro/sandboxes/run_*/ (one run per paper, lock file).
1.14.0: scripts, configs and in-paper inputs are copied (never hard-linked: a link is the same
file, so a script writing the sandbox path would change the original); declared data sources
are read in place, read-only, through .wf/data_sources.json. Copying more than
data_copy_limit_mb (default 200 MB) is refused. Every data source and in-place input is
checked before and after the run (size + mtime + cached sha256; a full hash when they differ);
a change is CRITICAL and invalidates the run. Each sandbox carries an owner marker (paper, pid,
host, start); the next run removes only this paper's sandboxes whose process is gone, and
unmarked medpaper_repro_* folders in the system temp only when older than 12 h and referenced
by no running process - others are listed. Logs: one file per command in .wf/logs/.

1.9.1: with a passing proof whose recorded hashes (scripts, manifest, data, tolerance, results,
retained re-run, the engine helpers the paper uses) all still match, `run` executes nothing and
ends REUSED (`--force` re-runs). When something changed, only the affected scripts re-run by
default (`--full` re-runs all). The last line is always
`REPRODUCE DONE rc=N REPRODUCED|NOT REPRODUCED|REUSED`.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wfcore import datasources, logs, paths, registry, reproproof as rp, runner  # noqa: E402


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _timeout(raw: str) -> float:
    try:
        t = float(raw)
    except ValueError:
        t = float("nan")
    if not math.isfinite(t) or t <= 0 or t > 86400:
        raise SystemExit("--timeout must be a positive number of seconds <= 86400")
    return t


def cmd_run(args) -> int:
    try:
        timeout = _timeout(args.timeout)
    except SystemExit as exc:
        print(exc)
        return 1
    paper = paths.paper_from_cli(args.project)
    busy = rp.acquire_lock(paper)
    if busy:
        print(f"reproduce: refused: {busy}")
        return 1
    try:
        freed, kept = rp.cleanup_stale(paper)
        if freed:
            print(f"cleaned {len(freed)} leftover sandbox(es) of interrupted runs "
                  f"({sum(n for _, n in freed) / 1e6:,.0f} MB freed)")
        for why in kept[:5]:
            print(f"left in place: {why}")
        return _run(args, paper, timeout)
    finally:
        rp.release_lock(paper)


def _run(args, paper: Path, timeout: float) -> int:
    tols, problems = rp.load_tolerances(paper)
    if problems:
        print("reproduce: tolerance file refused:")
        for p in problems:
            print(f"  - {p}")
        return 1
    try:
        report_path = paths.output_within(paper, f"project/{rp.REPORT_REL}")
        rerun = paths.output_within(paper, f"project/{rp.RERUN_DIR}")
        rerun_new = paths.output_within(paper, f"project/{rp.RERUN_DIR}.new")
        sandbox_root = paths.output_within(paper, f"project/{rp.SANDBOX_DIR}")
    except ValueError as exc:
        print(f"reproduce: {exc}")
        return 1
    scripts, order_source, order_problems = rp.ordered_scripts(paper)
    if order_problems:
        print("reproduce: analysis manifest refused:")
        for p in order_problems:
            print(f"  - {p}")
        return 1
    if order_source == "filename":
        print(f"WARNING: no {rp.MANIFEST_REL}; scripts run in FILENAME order. Declare the order "
              "(and each script's inputs/outputs) there so a rename cannot reorder the analysis.")
    previous = None
    if report_path.is_file():
        try:
            previous = json.loads(report_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            previous = None
    passing = isinstance(previous, dict) and bool(previous.get("all_match"))
    if passing and not (args.force or args.full):
        ok, why = rp.reuse_reason(paper, previous)
        if ok:
            print(f"nothing changed: {why}; no script executed (use --force to re-run anyway)")
            print(f"report: {report_path}")
            print("REUSED")
            _STATE["reused"] = True
            return 0
        print(f"previous proof not reusable: {why}")
    entries_m = rp.load_manifest(paper)[0] or []
    scoped, changed, carried = None, [], {}
    if (args.affected_only or passing) and not args.full:
        scoped, changed, why = rp.affected_scripts(paper, previous)
        if scoped is not None and not scoped and args.force:
            scoped, why = None, "--force with no changed input"
        if scoped is not None:
            prev_carried = previous.get("carried_results") or {}
            for e in entries_m:
                if e["path"] in scoped:
                    continue
                for o in e["outputs"]:
                    if not o.startswith(rp.RESULTS_DIR + "/"):
                        continue
                    if not (rerun / Path(o).name).is_file():
                        scoped, why = None, f"no retained re-run of {o} to carry"
                        break
                    carried[o] = prev_carried.get(o) or {
                        "started_at": previous.get("started_at"),
                        "generated_at": previous.get("generated_at")}
                if scoped is None:
                    break
        if scoped is None:
            carried = {}
            print(f"affected-only: full re-run instead ({why})")
        else:
            print(f"affected-only: re-running {len(scoped)} of {len(scripts)} script(s) "
                  f"({why}); changed inputs: {', '.join(changed[:6]) or 'none'} "
                  "(--full re-runs everything)")
    print(f"do not edit the paper's analysis code or data while reproduce.py run is active "
          f"({len(scripts)} scripts, order from {order_source}, timeout {timeout:g} s each)")
    sys.stdout.flush()
    sandbox_root.mkdir(parents=True, exist_ok=True)
    sandbox = Path(tempfile.mkdtemp(prefix="run_", dir=sandbox_root)).resolve()
    rp.write_marker(sandbox, paper)  # 1.14.0 (D): owner marker for safe cleanup
    budget = rp.Budget(datasources.copy_limit_bytes(paper))
    try:
        return _execute(args, paper, sandbox, budget, scripts, order_source, previous, scoped,
                        changed, carried, entries_m, tols, timeout, report_path, rerun, rerun_new)
    except rp.DataCopyRefused as exc:
        print(f"reproduce: refused: {exc}")
        return 1
    finally:
        if args.keep_sandbox:
            print(f"sandbox kept: {sandbox}")
        else:
            rp._rmtree(sandbox)


def _execute(args, paper, sandbox, budget, scripts, order_source, previous, scoped, changed,
             carried, entries_m, tols, timeout, report_path, rerun, rerun_new) -> int:
    started = _now()
    engine_hashes = rp.engine_inputs(paper)
    before = runner.tree_snapshot(paper, rp.SNAPSHOT_EXCLUDE)
    # 1.14.0 (D): every data source and every in-place paper input is checked before and after.
    guard = rp.integrity_snapshot(paper, [paper / r for r in rp.sandbox_inputs(paper)
                                          if r.startswith("02_data/")])
    inputs = []
    for rel in rp.sandbox_inputs(paper):
        if rel.startswith(rp.DATASOURCE_PREFIX):
            # declared data sources are read in place (absolute path, read-only); never copied
            inputs.append({"path": rel, "sha256": rp.input_sha(paper, rel)})
            continue
        src, dst = paper / rel, sandbox / rel
        if rel.startswith("02_data/"):
            rp.provide(src, dst, budget)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        inputs.append({"path": rel, "sha256": rp.input_sha(paper, rel)})
    (sandbox / ".wf").mkdir(exist_ok=True)
    (sandbox / ".wf" / "state.json").write_text("{}", encoding="utf-8")
    ds_file = paper / datasources.REL
    if ds_file.is_file():
        shutil.copy2(ds_file, sandbox / datasources.REL)
    (sandbox / rp.RESULTS_DIR).mkdir(parents=True, exist_ok=True)
    (sandbox / "02_data" / "derived").mkdir(parents=True, exist_ok=True)
    acq = paper / rp.ACQ_RESULT
    acq_scripts = sorted(p.relative_to(paper).as_posix()
                         for p in (paper / "02_data/acquisition").rglob("*")
                         if p.is_file() and p.suffix.casefold() in (".py", ".r")) \
        if (paper / "02_data/acquisition").is_dir() else []
    if acq.is_file():
        try:
            obj = json.loads(acq.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            obj = {}
        env = obj.get("environment") if isinstance(obj, dict) else None
        if isinstance(env, dict) and str(env.get("script", "")).startswith(rp.ACQ_PREFIX):
            shutil.copy2(acq, sandbox / rp.ACQ_RESULT)
    if scoped is not None:
        # Downstream scripts read what unaffected scripts produced: their declared outputs are
        # linked (never rewritten - their producers do not run); other derived files are
        # copied within the budget so a re-run script cannot overwrite the paper's file.
        carried_outputs = {o for e in entries_m if e["path"] not in scoped for o in e["outputs"]
                           if not o.startswith(rp.RESULTS_DIR + "/")}
        rerun_outputs = {o for e in entries_m if e["path"] in scoped for o in e["outputs"]}
        derived = paper / "02_data" / "derived"
        for p in sorted(derived.rglob("*")) if derived.is_dir() else []:
            rel = p.relative_to(paper).as_posix()
            if p.is_file() and rel not in rerun_outputs and rel not in carried_outputs:
                rp.provide(p, sandbox / rel, budget, prefer_copy=True)
        for o in sorted(carried_outputs):
            src = paper / o
            if src.is_file():
                rp.provide(src, sandbox / o, budget)
            elif src.is_dir():
                for p in sorted(src.rglob("*")):
                    if p.is_file():
                        rp.provide(p, sandbox / p.relative_to(paper), budget)
        for o in carried:
            if (paper / o).is_file():
                shutil.copy2(paper / o, sandbox / o)
    print(f"sandbox {sandbox}: {budget.copied / 1e6:,.1f} MB of paper inputs copied (no "
          "links); declared data sources read in place")

    prev_rows = {r.get("path"): r for r in (previous or {}).get("scripts", [])
                 if isinstance(r, dict)}
    script_rows, failed = [], None
    script_log = logs.log_path(paper, "reproduce_scripts")
    n_scripts = len(scripts)
    with script_log.open("w", encoding="utf-8") as slog:
        for idx, s in enumerate((sandbox / p.relative_to(paper) for p in scripts), 1):
            rel = s.relative_to(sandbox).as_posix()
            tag = f"[{idx}/{n_scripts}]"
            if scoped is not None and rel not in scoped:
                row = dict(prev_rows.get(rel) or {"path": rel, "exit_code": 0})
                row.update(path=rel, sha256=rp.sha256(paper / rel), carried=True)
                script_rows.append(row)
                print(f"{tag} carried {rel}  (unaffected; proven by the previous run)")
                continue
            print(f"{tag} start {rel}")
            row = {"path": rel, "sha256": rp.sha256(paper / rel),
                   "language": "python" if s.suffix.casefold() == ".py" else "R",
                   "exit_code": None, "seconds": 0.0, "timed_out": False}
            try:
                out = runner.run_paper_script(sandbox, s, timeout=timeout, capture=True)
            except runner.RunnerError as exc:
                row["exit_code"] = 2
                script_rows.append(row)
                failed = rel
                print(f"{tag} FAIL {rel}: {exc}")
                break
            slog.write(f"===== {rel} (rc={out.returncode}, {out.seconds:.1f} s)\n{out.stdout}\n"
                       f"--- stderr ---\n{out.stderr}\n")
            slog.flush()
            row.update(exit_code=out.returncode, seconds=round(out.seconds, 2),
                       timed_out=out.timed_out)
            script_rows.append(row)
            status = "ok" if out.returncode == 0 and not out.engine_changes else "FAIL"
            print(f"{tag} {status} {rel} ({out.seconds:.1f} s)")
            if out.engine_changes:
                print("  CRITICAL: the script changed the engine: " + ", ".join(out.engine_changes[:5]))
            if out.returncode != 0 or out.timed_out or out.engine_changes:
                failed = rel
                if out.stderr.strip():
                    print("    " + out.stderr.strip().splitlines()[-1][:200])
                print(f"    full script output: {script_log}")
                break

    # retain the evidence: whatever the sandbox produced replaces the previous re-run set
    if rerun_new.exists():
        shutil.rmtree(rerun_new)
    rerun_new.mkdir(parents=True)
    carried_names = {Path(o).name for o in carried}
    for p in sorted((sandbox / rp.RESULTS_DIR).glob("*.json")):
        if p.name not in carried_names:
            shutil.copy2(p, rerun_new / p.name)
    for name in carried_names:
        if (rerun / name).is_file():
            shutil.copy2(rerun / name, rerun_new / name)
    if rerun.exists():
        shutil.rmtree(rerun)
    os.replace(rerun_new, rerun)

    entries, within = rp.compare(paper, rerun, tols)
    damaged = rp.integrity_changes(guard)
    for label in damaged:
        print(f"CRITICAL: a data source or in-place input changed during the run: {label} - "
              "the run is invalid; restore the file from its origin and find the script that "
              "wrote it (data are read-only)")
    after = runner.tree_snapshot(paper, rp.SNAPSHOT_EXCLUDE)
    # 1.13.0: only analysis inputs and results can invalidate a run; notes, documentation and
    # manuscript edits meanwhile are recorded, not fatal.
    changes, side_edits = rp.split_paper_changes(runner.diff_snapshots(before, after))
    all_match = (failed is None and not changes and not damaged and
                 all(e["status"] in ("match", "not_rerun_acquisition") for e in entries))
    tp = paper / rp.TOLERANCE_REL
    report = {
        "schema": 1,
        "engine_version": str(registry.load().meta.get("version", "")),
        "started_at": started,
        "generated_at": _now(),
        "timeout_seconds": timeout,
        "rerun_dir": rp.RERUN_DIR,
        "tolerance_sha256": rp.sha256(tp) if tp.is_file() else None,
        "engine_inputs": engine_hashes,
        "order_source": order_source,
        "mode": "affected-only" if scoped is not None else "full",
        "changed_inputs": changed if scoped is not None else [],
        "carried_results": carried,
        "inputs": inputs,
        "manifest_entries": [{k: e[k] for k in ("path", "inputs", "outputs", "after")}
                             for e in entries_m],
        "sandbox": {"location": rp.SANDBOX_DIR, "data_files_linked": budget.linked,
                    "data_bytes_copied": budget.copied,
                    "data_sources_in_place": sum(1 for i in inputs
                                                 if i["path"].startswith(rp.DATASOURCE_PREFIX))},
        "scripts": script_rows,
        "failed_script": failed,
        "data_integrity": {"ok": not damaged, "checked": len(guard), "changed": damaged[:50]},
        "results": entries,
        "within_tolerance": within,
        "paper_changes": changes[:50],
        "non_analysis_edits": side_edits[:50],
        "not_rerun": {"acquisition_scripts": acq_scripts,
                      "permitted_result": rp.ACQ_RESULT,
                      "reason": "acquisition is network-bound and is not re-executed; "
                                "dataset_summary is its only output and an input to the analysis"},
        "all_match": all_match,
    }
    tmp = report_path.with_name(report_path.name + ".tmp")
    tmp.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n",
                   encoding="utf-8")
    os.replace(tmp, report_path)

    def short(v) -> str:  # 1.11.0 (#2g): never dump a whole JSON value to the console
        s = repr(v)
        return s if len(s) <= 80 else s[:77] + "..."
    for e in entries:
        mark = "=" if e["status"] in ("match", "not_rerun_acquisition") else "!"
        extra = (f"  first difference {e['first_difference']}: {short(e['original_value'])} vs "
                 f"{short(e['rerun_value'])}" if e["status"] == "mismatch" else "")
        if mark == "!" or len(entries) <= 12:
            print(f"{mark} {e['file']}  {e['status']}{extra}")
    for w in within[:10]:
        print(f"~ {w['file']} {w['path']} {short(w['original_value'])} vs {short(w['rerun_value'])}")
    matched = sum(e["status"] in ("match", "not_rerun_acquisition") for e in entries)
    print(f"results: {matched}/{len(entries)} match; details in the report")
    if changes:
        print("the original paper changed during the run: " + ", ".join(changes[:12]))
    if side_edits:
        print(f"note: {len(side_edits)} non-analysis file(s) edited meanwhile (not analysis "
              "inputs; the run stays valid)")
    print(f"report: {report_path}")
    print("REPRODUCED" if all_match else "NOT REPRODUCED")
    return 0 if all_match else 2


def cmd_check(args) -> int:
    paper = paths.paper_from_cli(args.project)
    out = rp.validate(paper)
    print(("PASS " if out.ok else "FAIL ") + out.detail)
    for p in out.problems[:20]:
        print(f"  - {p}")
    print("next: " + rp.next_step(paper))
    return 0 if out.ok else 2


_STATE = {"reused": False}


class _Tee:
    """Console + log file, flushed on every write so a background run can be followed."""

    def __init__(self, *streams):
        self.streams = streams

    def write(self, text):
        for s in self.streams:
            s.write(text)
            s.flush()
        return len(text)

    def flush(self):
        for s in self.streams:
            s.flush()


def _run_with_progress(args) -> int:
    rc, fh, out = 1, None, sys.stdout
    try:
        if args.log:
            log = logs.log_path(paths.paper_from_cli(args.project), "reproduce", args.log)
            fh = log.open("w", encoding="utf-8", newline="\n")
            sys.stdout = _Tee(out, fh)
            print(f"log: {log}")
        rc = cmd_run(args)
    except paths.EngineWorkspace as exc:
        print(exc)
        rc = 1
    finally:
        verdict = "REUSED" if _STATE["reused"] and rc == 0 else (
            "REPRODUCED" if rc == 0 else "NOT REPRODUCED")
        print(f"REPRODUCE DONE rc={rc} {verdict}")
        sys.stdout = out
        if fh:
            fh.close()
    return rc


def main() -> int:
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(description="re-execute the analysis and prove identical results")
    sub = ap.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run")
    r.add_argument("--timeout", default="3600")
    r.add_argument("--keep-sandbox", action="store_true")
    r.add_argument("--affected-only", action="store_true",
                   help="re-run only the scripts the changed inputs reach (the default since "
                        "1.9.1 whenever a passing proof exists; needs analysis_manifest.json)")
    r.add_argument("--full", action="store_true",
                   help="re-run every script even when a passing proof could scope the run")
    r.add_argument("--force", action="store_true",
                   help="re-run even when nothing changed since the passing proof")
    r.add_argument("--log", default=None,
                   help="also write the progress to this UTF-8 file in .wf/logs/ (a path "
                        "elsewhere is redirected there); it ends with 'REPRODUCE DONE rc=N ...'")
    r.add_argument("--project", default=None)
    c = sub.add_parser("check")
    c.add_argument("--project", default=None)
    r.add_argument("--wait", action="store_true",
                   help="block with heartbeat lines; print failures + one summary line (log has all)")
    args = ap.parse_args()
    if args.command == "run" and args.wait:
        from wfcore import longrun
        log = logs.log_path(paths.paper_from_cli(args.project), "reproduce", args.log)
        return longrun.run_quiet([sys.executable, *sys.argv], log, "reproduce", max_seconds=4 * 3600)
    if args.command == "run":
        return _run_with_progress(args)
    try:
        return cmd_check(args)
    except paths.EngineWorkspace as exc:
        print(exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
