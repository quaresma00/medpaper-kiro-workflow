#!/usr/bin/env python3
"""Re-execute the paper's analysis in a sandbox and prove the results are identical.

    python "<engine>/tools/reproduce.py" run [--log FILE] [--full] [--force] [--timeout SECONDS]
                                         [--keep-sandbox] [--project DIR]
    python "<engine>/tools/reproduce.py" check [--project DIR]

`run` copies the analysis inputs (02_data/** except derived/, 03_analysis/code/**, the
tolerance file, analysis manifest) into a temporary sandbox, re-runs every top-level
03_analysis/code script in the order declared by 03_analysis/analysis_manifest.json (filename
order, with a warning, when the paper has none; `--affected-only` re-runs just the scripts the
changed inputs reach and carries the rest from the previous passing proof), compares each results JSON with the original (volatile timestamps ignored),
keeps the re-run results in <paper>/.wf/repro/rerun/ as evidence and writes
03_analysis/reproducibility_report.json. Acquisition is never re-run. `check` runs the
analysis_reproduces gate logic. Exit 0 = identical, 2 = not reproduced, 1 = refused.

1.9.1: with a passing proof whose recorded hashes (scripts, manifest, data, tolerance, results,
retained re-run, engine analysis helpers) all still match, `run` executes nothing and ends
REUSED (`--force` re-runs). When something changed, the scoped (`--affected-only`) run is the
default (`--full` re-runs all). Progress is printed `[i/N] start|ok|FAIL` and the last line is
always `REPRODUCE DONE rc=N REPRODUCED|NOT REPRODUCED|REUSED`; `--log FILE` tees it.
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

from wfcore import paths, registry, reproproof as rp, runner  # noqa: E402


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
    except ValueError as exc:
        print(f"reproduce: {exc}")
        return 1
    sandbox = Path(tempfile.mkdtemp(prefix="medpaper_repro_")).resolve()
    if paths.in_engine(sandbox) or paths.within(sandbox, paper):
        shutil.rmtree(sandbox, ignore_errors=True)
        print(f"reproduce: refusing sandbox location {sandbox}")
        return 1
    scripts, order_source, order_problems = rp.ordered_scripts(paper)
    if order_problems:
        shutil.rmtree(sandbox, ignore_errors=True)
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
            shutil.rmtree(sandbox, ignore_errors=True)
            print(f"nothing changed: {why}; no script executed (use --force to re-run anyway)")
            print(f"report: {report_path}")
            print("REUSED")
            _STATE["reused"] = True
            return 0
        print(f"previous proof not reusable: {why}")
    scoped, changed, carried = None, [], {}
    if (args.affected_only or passing) and not args.full:
        scoped, changed, why = rp.affected_scripts(paper, previous)
        if scoped is not None and not scoped and args.force:
            scoped, why = None, "--force with no changed input"
        if scoped is not None:
            entries_m = rp.load_manifest(paper)[0] or []
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
    print(f"do not edit the paper while reproduce.py run is active ({len(scripts)} scripts, "
          f"order from {order_source}, timeout {timeout:g} s each)")
    sys.stdout.flush()
    started = _now()
    engine_hashes = rp.engine_inputs()
    before = runner.tree_snapshot(paper, rp.SNAPSHOT_EXCLUDE)
    inputs = []
    for rel in rp.sandbox_inputs(paper):
        src, dst = paper / rel, sandbox / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        inputs.append({"path": rel, "sha256": rp.sha256(src)})
    (sandbox / ".wf").mkdir(exist_ok=True)
    (sandbox / ".wf" / "state.json").write_text("{}", encoding="utf-8")
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
        # Downstream scripts read what unaffected scripts produced; give them the proven copies.
        derived = paper / "02_data" / "derived"
        if derived.is_dir():
            shutil.copytree(derived, sandbox / "02_data" / "derived", dirs_exist_ok=True)
        for o in carried:
            if (paper / o).is_file():
                shutil.copy2(paper / o, sandbox / o)

    prev_rows = {r.get("path"): r for r in (previous or {}).get("scripts", [])
                 if isinstance(r, dict)}
    script_rows, failed = [], None
    logs = sandbox / "_logs"
    logs.mkdir()
    n_scripts = len(scripts)
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
        (logs / f"{s.name}.log").write_text(out.stdout + "\n--- stderr ---\n" + out.stderr,
                                            encoding="utf-8")
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
    after = runner.tree_snapshot(paper, rp.SNAPSHOT_EXCLUDE)
    changes = runner.diff_snapshots(before, after)
    all_match = (failed is None and not changes and
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
        "scripts": script_rows,
        "failed_script": failed,
        "results": entries,
        "within_tolerance": within,
        "paper_changes": changes[:50],
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
    for e in entries:
        mark = "=" if e["status"] in ("match", "not_rerun_acquisition") else "!"
        extra = (f"  first difference {e['first_difference']}: {e['original_value']!r} vs "
                 f"{e['rerun_value']!r}" if e["status"] == "mismatch" else "")
        print(f"{mark} {e['file']}  {e['status']}{extra}")
    for w in within:
        print(f"~ {w['file']} {w['path']} {w['original_value']!r} vs {w['rerun_value']!r}")
    if changes:
        print("the original paper changed during the run: " + ", ".join(changes[:12]))
    if args.keep_sandbox:
        print(f"sandbox kept: {sandbox}")
    else:
        shutil.rmtree(sandbox, ignore_errors=True)
    print(f"report: {report_path}")
    print("REPRODUCED" if all_match else "NOT REPRODUCED")
    return 0 if all_match else 2


def cmd_check(args) -> int:
    paper = paths.paper_from_cli(args.project)
    out = rp.validate(paper)
    print(("PASS " if out.ok else "FAIL ") + out.detail)
    for p in out.problems[:20]:
        print(f"  - {p}")
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


def _log_target(raw: str, project: str | None) -> Path:
    log = Path(raw).resolve()
    if paths.in_engine(log):
        raise ValueError(f"--log may not point into the engine: {log}")
    try:
        paper = paths.paper_from_cli(project)
    except paths.EngineWorkspace:
        return log
    if paths.within(log, paper) and not any(paths.within(log, paper / d)
                                            for d in ("temp", ".wf", ".kiro")):
        raise ValueError(f"--log inside the paper must be under temp/ (the run would otherwise "
                         f"see the paper change): {log}")
    return log


def _run_with_progress(args) -> int:
    rc, fh, out = 1, None, sys.stdout
    try:
        if args.log:
            try:
                log = _log_target(args.log, args.project)
            except ValueError as exc:
                print(f"reproduce: {exc}")
                return 1
            log.parent.mkdir(parents=True, exist_ok=True)
            fh = log.open("w", encoding="utf-8", newline="\n")
            sys.stdout = _Tee(out, fh)
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
                   help="also write the progress to this UTF-8 file (flushed per line); it ends "
                        "with 'REPRODUCE DONE rc=N ...'")
    r.add_argument("--project", default=None)
    c = sub.add_parser("check")
    c.add_argument("--project", default=None)
    args = ap.parse_args()
    if args.command == "run":
        return _run_with_progress(args)
    try:
        return cmd_check(args)
    except paths.EngineWorkspace as exc:
        print(exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
