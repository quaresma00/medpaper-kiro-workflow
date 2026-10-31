"""wf - the workflow driver.

Design intent: this CLI is the agent's only source of truth about *where it is*
and *what is allowed next*. `wf status` alone must be enough to resume work
correctly after a context reset, so it prints the invariants, the progress map,
the gate state, the last handoff and the full stage card.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shutil
import sys
from pathlib import Path

from . import adapters, checks, gates, overrides, paths, registry, runner, scifreeze
from .state import State

BAR = "=" * 78
DASH = "-" * 78
STAGE_ALIASES = {
    # v1.2 combined title/author/journal work differently. Any active legacy tail stage
    # returns to canonical assembly so the independent and human review gates cannot be
    # skipped during an in-place engine upgrade.
    "S17_frontmatter": "S17_assemble",
    "S18_journal": "S17_assemble",
    "S19_polish": "S17_assemble",
    "S20_package": "S17_assemble",
}
NON_OVERRIDABLE_GATES = {
    # Checks that were not run because required outputs are missing are not "failed and
    # forceable"; they are unknown. Forcing past them would advance on untested gates.
    "dependent_checks_pending",
    # 1.12.0 (B3): the merged "pending outputs" line (outputs_exist + dependent_checks_pending).
    "outputs_pending",
    "data_acquisition_complete",
    "reference_provenance",
    "refs_library",
    "bib_ris_match_library",
    "citekeys_resolve",
    "revision_rounds_closed",
    "s19_review_release_explicit",
    "review_round_approved",
    # Deferring a visual review is permission to batch the look, not to skip it.
    "visual_debts_cleared",
    # A deep read of the wrong paper is worse than a missing one: it puts confident, sourced
    # claims about a study nobody read into the Discussion.
    "deepread_complete",
    # Editing the reviewed manuscript to satisfy a journal is the churn the freeze exists to
    # stop; --force must not reopen that door. Capture is protected too, otherwise S19 could
    # simply force past the boundary before the journal is chosen.
    "scientific_freeze_captured",
    "scientific_freeze_intact",
    "journal_variant_ready",
    "variant_preserves_science",
    # Paper-authored code that does not consume the selected paper root can write into the
    # shared engine. This is structural isolation, not an optional style check.
    "paper_scripts_scoped",
    # Numbers must carry the environment that produced them, must re-execute identically, and
    # a "Reported" checklist row must point at text that exists.
    "results_have_environment",
    "analysis_reproduces",
    "reporting_checklist_complete",
}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def wf() -> str:
    """How to invoke this driver, phrased so a printed suggestion is copy-pasteable.

    Inside the engine directory the short relative form is right. From anywhere else - which
    is normal once the Kiro skill is installed at the user level - the absolute path is the
    only form that works, so echo that instead.
    """
    try:
        if Path.cwd().resolve() == paths.repo_root():
            return "python tools/wf.py"
    except OSError:
        pass
    argv0 = Path(sys.argv[0])
    target = argv0 if argv0.is_absolute() else paths.repo_root() / "tools" / "wf.py"
    return f'python "{target.as_posix()}"'


def _no_state_help(pipe, proj: Path) -> None:
    """Explain where the driver looked and what to do, instead of a bare 'not found'."""
    print("no paper is initialised here yet.")
    print()
    print(f"  engine        {paths.repo_root()}")
    print(f"  looked for    {proj / pipe.layout.get('state_dir', '.wf') / 'state.json'}")
    print(f"  because       {_PROJECT_SOURCE or paths.describe_project_source(pipe.layout)}")
    print()
    # 1.13.0: never list other papers to an agent; the paper is the workspace folder.
    print("the paper is the folder the user opened as the Kiro workspace; initialise it in place:")
    print(f"  {wf()} init")
    print(paths.ASK_ONCE)


def _export_paper_env(proj: Path) -> None:
    """Tell every in-process tool module which paper is active.

    tools/pubmed/eutils.py and friends resolve their project root from MEDPAPER_PROJECT and fall
    back to <engine>/project when it is unset. The driver resolves the paper through paths.py
    instead, so anything a check imports and calls in-process used to write to the engine's own
    project/ directory rather than to the paper.

    That was not theoretical: the live reference_provenance gate calls eu.efetch(..., purpose=
    "gate") in-process, and every run deposited a ~1 MB EFetch payload in <engine>/project/
    06_refs/cache/. Sixty-eight of them accumulated - engine pollution, and the gate's own
    evidence filed outside the paper it belonged to. Exporting here fixes the whole class rather
    than that one call site.
    """
    os.environ["MEDPAPER_PROJECT"] = str(proj.resolve())
    os.environ.setdefault("MEDPAPER_ROOT", str(paths.repo_root()))


ENGINE_CWD_WARNING = ("!! driving paper {p} from the ENGINE workspace via MEDPAPER_PROJECT; file "
                      "writes relative to this workspace land in the engine - open {p} as the "
                      "workspace")


def _engine_cwd_warning(proj: Path) -> str | None:
    return ENGINE_CWD_WARNING.format(p=proj) if paths.cwd_in_engine() else None


def _warn_engine_cwd(proj: Path, *, stdout: bool) -> None:
    msg = _engine_cwd_warning(proj)
    if msg:
        print(msg, file=sys.stdout if stdout else sys.stderr)


def _loc(text: str, proj: Path | None) -> str:
    return paths.localize_commands(text, proj)


_PROJECT_SOURCE = ""


def paper_header(proj: Path, source: str) -> list[str]:
    """Which paper this command acts on (1.7.1). 1.13.0: the paper comes only from the working
    directory (or MEDPAPER_PROJECT); the global marker is gone, and no other paper's path is
    ever printed (a command targeting another paper than the cwd's is refused upstream)."""
    return [f"[medpaper] paper: {proj}  ({source})"]


def _load(need_state: bool = True, warn_stderr: bool = True):
    tmp_state = State(paths.project_dir({}), ".wf")
    cfg = tmp_state.config() if tmp_state.config_file.exists() else {}
    paper_over = overrides.load(tmp_state.dir)
    pipe = registry.load(cfg, paper_over)
    proj = paths.project_dir(pipe.layout)
    if warn_stderr:
        _warn_engine_cwd(proj, stdout=False)
    global _PROJECT_SOURCE
    # Record why this paper was chosen before exporting MEDPAPER_PROJECT for in-process tools,
    # otherwise every source would read as "MEDPAPER_PROJECT".
    _PROJECT_SOURCE = paths.describe_project_source(pipe.layout)
    for line in paper_header(proj, _PROJECT_SOURCE):
        print(line, file=sys.stderr)
    _export_paper_env(proj)
    st = State(proj, pipe.layout.get("state_dir", ".wf"))
    if need_state:
        if not st.exists():
            _no_state_help(pipe, proj)
            raise SystemExit(2)
        st.load()
        st.migrate_pipeline(str(pipe.meta.get("version", "0")),
                            [stage.id for stage in pipe.stages], STAGE_ALIASES)
        _refresh_adapters(pipe, st, proj)
        history_problems = overrides.validate_against_state(paper_over, st)
        if history_problems:
            raise SystemExit(
                "refusing retrospective paper-local override:\n  "
                + "\n  ".join(history_problems)
                + "\nRestore the recorded override first, run `wf loop --to STAGE --why \"...\"`, "
                  "then change it while that stage is active.")
    return pipe, st, proj


def _refresh_adapters(pipe, st, proj: Path) -> None:
    """1.14.1 (P2): every wf command brings the paper's derived adapters (.kiro hooks and
    steering) up to the engine release - one line and one event, no user action."""
    try:
        changed = adapters.refresh_paper(proj)
    except Exception:  # noqa: BLE001 - adapters never block a paper command
        return
    if not changed:
        return
    version = pipe.meta.get("version")
    print(f"[medpaper] Kiro adapters refreshed for engine {version}: {', '.join(changed)}",
          file=sys.stderr)
    st.event("adapters_refreshed", f"engine {version}: {', '.join(changed)}")
    st.save()


def _mark(pipe, st, stage) -> str:
    if getattr(stage, "skipped", False):
        return "-"
    if st.is_done(stage.id):
        return "x"
    if st.current == stage.id:
        return ">"
    return " "


def _print_overrides(pipe) -> None:
    """Reprint the paper's workflow overrides on every status call.

    A customised workflow must never be mistaken for the standard one, especially after a
    context reset: the next agent has to know this paper skips a stage or dropped a gate, and
    why, without going looking for a config file.
    """
    notes = getattr(pipe, "override_notes", [])
    if not notes:
        return
    print("PAPER-LOCAL WORKFLOW OVERRIDES  (.wf/overrides.toml; the master pipeline is unchanged)")
    for note in notes:
        print(f"  ! {note}")
    print("  integrity gates and review stages cannot be overridden - see wfcore/overrides.py")
    print()


def _print_progress(pipe, st) -> None:
    print("PROGRESS")
    for s in pipe.stages:
        m = _mark(pipe, st, s)
        loops = st.stage_info(s.id).get("loops", 0)
        suffix = ""
        if m == ">":
            suffix = "   <-- you are here" + (f" (revisit #{loops})" if loops else "")
        elif m == "-":
            suffix = f"   SKIPPED for this paper: {getattr(s, 'skip_reason', '') or 'no reason'}"
        print(f"  [{m}] {s.index + 1:>2}. {s.id:<20} {s.title}{suffix}")


def _print_invariants(pipe, proj: Path | None = None) -> None:
    inv = pipe.policy.get("invariants", [])
    if not inv:
        return
    print("NON-NEGOTIABLE INVARIANTS")
    for i, line in enumerate(inv, 1):
        print(f"  {i}. {_loc(line, proj)}")
    print()


def _print_visual_debts(pipe, st, proj: Path | None = None) -> None:
    """Surface parked visual reviews on every status call.

    A deferred look is a promise made many stages before it comes due. Printing it here is
    what keeps it from being lost to a context reset between S11 and S23.
    """
    from .checks.statecheck import parked_visual
    mode = str(pipe.targets.get("visual_review_mode", "inline")).strip().lower()
    parked = sorted(name for name, _, _ in parked_visual(pipe, st, mode))
    if not parked:
        return
    print(f"DEFERRED VISUAL REVIEWS  (visual_review_mode = {mode})")
    for name in parked:
        print(f"  !! {name} is parked - due at S23_package, before the submission bundle")
    print(_loc("  discharge in one pass:  tools/figures/qc.py --contact-sheet", proj))
    print("  the S23 gate visual_debts_cleared is non-overridable; this cannot be dropped")
    print()


def _gate_lines(results, proj: Path | None = None) -> None:
    blocking = False
    for r in results:
        print(f"  [{r.label}] {r.check}")
        if r.detail:
            print(f"         {_loc(r.detail, proj)}")
        for h in r.hints:
            print(f"         -> {_loc(h, proj)}")
        blocking = blocking or r.blocking
    if blocking:
        # 1.11.0 (#3d): every failure has a legitimate path that is not an engine edit.
        print("  exception path: fix the paper; a journal's own names/rules go in "
              "target_journal.json; paper targets via `wf config set`; a genuine shape "
              "difference via `wf override init` (.wf/overrides.toml); only then a project-local "
              "fork (`wf engine-fork create`). Never edit the global engine.")


def _declared_and_free(pipe) -> tuple[set[str], list[str]]:
    return pipe.all_declared_outputs(), pipe.freeform + pipe.policy.get("always_allowed", [])


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,60}$")

SUBDIRS = (
    "02_data/raw", "02_data/acquisition", "02_data/derived",
    "03_analysis/code", "03_analysis/results",
    "04_tables/main", "04_tables/supplementary",
    "05_figures/code", "05_figures/out", "05_figures/qc",
    "06_refs/cache", "06_refs/fulltext", "06_refs/deepread",
    "08_submission/cache", "08_submission/bundle",
)


def _scaffold(pipe, proj: Path) -> None:
    for name in pipe.layout.get("dirs", {}):
        (proj / name).mkdir(parents=True, exist_ok=True)
        (proj / name / ".gitkeep").touch()
    for sub in SUBDIRS:
        (proj / sub).mkdir(parents=True, exist_ok=True)
        (proj / sub / ".gitkeep").touch()
    tmp = proj / pipe.layout.get("temp_dir", "temp")
    tmp.mkdir(parents=True, exist_ok=True)
    (tmp / ".gitkeep").touch()


def _record_user_files(pipe, proj: Path) -> None:
    """1.13.0: files the user already had in the folder before `wf init` (an idea note, author
    info) are the user's, never orphans; they are listed once in .wf/user_files.json."""
    state_dir = proj / pipe.layout.get("state_dir", ".wf")
    skip = {pipe.layout.get("state_dir", ".wf"), ".kiro", ".git"}
    foreign = paths.foreign_prefixes(proj)  # 1.14.1: older paper attempts stay theirs
    found = sorted(p.relative_to(proj).as_posix() for p in proj.rglob("*")
                   if p.is_file() and not set(p.relative_to(proj).parts[:1]) & skip
                   and p.name != ".gitkeep"
                   and not p.relative_to(proj).as_posix().startswith(foreign))
    if found:
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "user_files.json").write_text(
            json.dumps({"schema": 1, "files": found[:500]}, indent=1, ensure_ascii=False) + "\n",
            encoding="utf-8")


def _finish_paper(pipe, proj: Path, verb: str) -> None:
    adapters.write_adapters(proj, adapters.paper_adapters(paths.repo_root(), proj), check=False)
    st = State(proj, pipe.layout.get("state_dir", ".wf"))
    if st.exists() and "spelling" not in st.load().config().get("targets", {}):
        st.set_config("spelling", "american")  # 1.9.0 (#16): decided up front, changeable at S01/S03
    print(f"{verb} {pipe.meta.get('name')} {pipe.meta.get('version')} paper at {proj}")
    print(f"current stage: {pipe.first().id}")
    print("isolation: the paper guard hook (.kiro/hooks/medpaper-paper-guard.json) blocks other "
          "papers and engine writes; register datasets in place with `wf data add <path>` "
          "(never copy them)")
    try:
        here = paths._norm(Path.cwd()) == paths._norm(proj)
    except OSError:
        here = False
    older = paths.nested_papers(proj)
    if older:
        # 1.14.1 (P1): mentioned once; never read, moved or resumed from here.
        print("note: an older paper attempt in " + ", ".join(
            p.relative_to(proj).as_posix() + "/" for p in older[:3])
              + " is left untouched and isolated (the paper guard blocks it); this folder is "
                "the paper")
    print(f"\nput your research idea in {proj.as_posix()}/00_input/, then:")
    print(f'  python "{paths.repo_root().as_posix()}/tools/wf.py" status')
    if not here:
        print(f"\nthe user asked for this location explicitly; to work on it, open this folder "
              f"as the Kiro workspace (commands act on the workspace's paper only): {proj}")


def _archive_run(pipe, proj: Path) -> Path:
    """1.14.1 (P1): a confirmed fresh restart keeps the old run in place. The state goes to
    .wf_archive/<UTC>/wf_state/ (not '.wf', so the archive is never mistaken for a paper) and
    every pipeline output file moves alongside it; the user's own files stay where they are."""
    from datetime import datetime, timezone
    import shutil
    state_dir = pipe.layout.get("state_dir", ".wf")
    dest = proj / paths.ARCHIVE_DIR / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest.mkdir(parents=True, exist_ok=False)
    users = paths.user_files(proj)
    shutil.move(str(proj / state_dir), str(dest / "wf_state"))
    tops = {str(name) for name in list(pipe.layout.get("dirs", {})) + list(SUBDIRS)}
    tops = {Path(t).parts[0] for t in tops if t and not t.startswith("00_input")}
    tops.add(pipe.layout.get("temp_dir", "temp"))
    foreign = paths.foreign_prefixes(proj)
    for top in sorted(tops):
        root = proj / top
        if not root.is_dir():
            continue
        for p in sorted(root.rglob("*")):
            rel = p.relative_to(proj).as_posix()
            if not p.is_file() or p.name == ".gitkeep" or rel in users or rel.startswith(foreign):
                continue
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(p), str(target))
    if users:
        (proj / state_dir).mkdir(parents=True, exist_ok=True)
        (proj / state_dir / "user_files.json").write_text(
            json.dumps({"schema": 1, "files": sorted(users)[:500]}, indent=1,
                       ensure_ascii=False) + "\n", encoding="utf-8")
    return dest


def _location_refusal(target: Path, source: str) -> tuple[Path | None, str | None]:
    try:
        proj = paths.check_paper_location(target, source)
        why = paths.unsuitable_paper_dir(proj)
        if why:
            raise SystemExit(why)
    except SystemExit as exc:
        return None, f"{exc}\n{paths.ASK_ONCE}"
    return proj, None


def cmd_init(args) -> int:
    """Initialise the working directory (the Kiro workspace the user opened) as a paper, in place."""
    pipe = registry.load()
    env = os.environ.get("MEDPAPER_PROJECT")
    target = Path(env) if env else Path.cwd()
    st = State(target.resolve(), pipe.layout.get("state_dir", ".wf"))
    if st.exists() and not args.force:
        # 1.14.1 (P1): the opened folder is already this paper - resume it.
        try:
            cur = st.load().current
        except (Exception, SystemExit):  # noqa: BLE001
            cur = "?"
        print(f"this folder is already a paper (current stage {cur}); resuming it - nothing "
              "was reset")
        print(f'next:  python "{paths.repo_root().as_posix()}/tools/wf.py" status')
        print("A fresh restart in this folder (`wf init --force --yes`) archives the current run "
              f"in place under {paths.ARCHIVE_DIR}/<UTC>/ and needs one explicit confirmation "
              "from the user first.")
        return 0
    proj, why = _location_refusal(target, "MEDPAPER_PROJECT" if env else "wf init")
    if why:
        print(f"refusing to initialise: {why}")
        return 2
    if st.exists():
        if not getattr(args, "yes", False):
            print("refusing to restart: this folder is already a paper. A fresh restart moves "
                  f"the run state (.wf) and the pipeline's outputs into {paths.ARCHIVE_DIR}/<UTC>/ "
                  "in this folder (nothing is deleted; the user's own files stay where they "
                  "are). Ask the user once; only after an explicit yes run:  wf init --force --yes")
            return 2
        where = _archive_run(pipe, proj)
        print(f"archived the previous run in place: {where.relative_to(proj).as_posix()}/")
    else:
        _record_user_files(pipe, proj)
    _scaffold(pipe, proj)
    st = State(proj, pipe.layout.get("state_dir", ".wf"))
    st.create(pipe.meta.get("name", "pipeline"), pipe.meta.get("version", "0"), pipe.first().id)
    _finish_paper(pipe, proj, "initialised")
    return 0


def cmd_new(args) -> int:
    """Start a new paper: in place in the working directory (default), or under an explicit
    root / the central papers root (`--root DIR`, `--central`) only when the user asked."""
    pipe = registry.load()
    slug = (args.slug or "").strip().lower()
    if not (args.root or args.central):
        if args.slug and not SLUG_RE.match(slug):
            print(f"note: '{args.slug}' is only a label here; the paper is this folder")
        return cmd_init(args)
    if not SLUG_RE.match(slug):
        print(f"'{args.slug}' is not a usable name. Use lowercase letters, digits and hyphens,")
        print("e.g. sarcopenia-mortality")
        return 1
    try:
        if args.root:
            root = Path(args.root).expanduser()
            root = (root if root.is_absolute() else Path.cwd() / root).resolve()
            if paths.in_engine(root):
                raise paths.PaperLocationError(
                    f"--root {root} is inside, equal to or contains the medpaper engine")
        else:
            root = paths.papers_root()[0]
    except SystemExit as exc:
        print(f"refusing to create the paper: {exc}")
        return 2
    st = State(root / slug, pipe.layout.get("state_dir", ".wf"))
    if st.exists() and not args.force:
        print(f"a paper named '{slug}' already exists at {root / slug}")
        print("open that folder as the Kiro workspace to work on it")
        return 1
    proj, why = _location_refusal(root / slug, "wf new")
    if why:
        print(f"refusing to create the paper: {why}")
        return 2
    root.mkdir(parents=True, exist_ok=True)
    proj.mkdir(parents=True, exist_ok=True)
    _scaffold(pipe, proj)
    st = State(proj, pipe.layout.get("state_dir", ".wf"))
    st.create(pipe.meta.get("name", "pipeline"), pipe.meta.get("version", "0"), pipe.first().id)
    _finish_paper(pipe, proj, f"created '{slug}':")
    return 0


def cmd_use(args) -> int:
    """1.13.0: there is no global selection any more; this only says where a paper is."""
    pipe = registry.load()
    if args.slug in (None, ""):
        return cmd_papers(args)
    raw = args.slug.strip()
    state_dir = pipe.layout.get("state_dir", ".wf")
    try:
        cand = Path(raw).expanduser()
        if any(sep in raw for sep in ("/", "\\")) or cand.is_dir():
            proj = (cand if cand.is_absolute() else Path.cwd() / cand).resolve()
        else:
            proj = paths.papers_root()[0] / raw.lower()
        proj = paths.check_paper_location(proj, "wf use")
    except SystemExit as exc:
        print(f"refusing: {exc}")
        return 2
    if not (proj / state_dir / "state.json").exists():
        print(f"no initialised paper at {proj}")
        return 1
    print(f"{proj} is a paper. There is no global selection (1.13.0): open that folder as the "
          "Kiro workspace (or cd into it); commands act only on the workspace's paper.")
    return 0


def cmd_papers(args) -> int:
    """For humans only: the papers under the central papers root."""
    pipe = registry.load()
    try:
        root, source = paths.papers_root()
    except SystemExit as exc:
        print(f"papers root  !! {exc}")
        return 2
    print(f"papers root  {root}  ({source}; used only for `wf new <slug> --central`)")
    state_dir = pipe.layout.get("state_dir", ".wf")
    rows = []
    if not root.is_dir():
        print(f"no papers yet under {root}")
        return 0
    for p in paths.list_papers():
        try:
            st = State(p, state_dir).load()
            rows.append((p.name, f"{pipe.stage(st.current).index + 1}/{len(pipe.stages)}",
                         st.current))
        except Exception:  # noqa: BLE001
            rows.append((p.name, "-", "(unreadable state)"))
    if not rows:
        print("no papers yet.")
        return 0
    w = max(len(r[0]) for r in rows)
    print(f"{'':2}{'paper':<{w}}  {'stage':>6}  current")
    for name, idx, stage in rows:
        print(f"  {name:<{w}}  {idx:>6}  {stage}")
    print("\nopen a paper's folder as the Kiro workspace to work on it")
    return 0


def _engine_banner(as_json: bool) -> int:
    """`wf status` in the engine workspace: maintenance-only banner, exit 0."""
    pipe = registry.load()
    root_line, root, source, n = "", None, "", 0
    try:
        root, source = paths.papers_root()
        n = len(paths.list_papers())
        root_line = f"{root}   ({source})"
    except SystemExit as exc:
        root_line = f"!! {exc}"
    from . import integrity
    kind, changed = integrity.engine_state(use_cache=False)
    integ = kind + (f" ({len(changed)} file(s): {', '.join(changed[:4])})" if changed else "")
    if as_json:
        print(json.dumps({"engine_workspace": True, "engine": str(paths.repo_root()),
                          "papers_root": str(root) if root else None,
                          "papers_root_source": source, "papers": n, "integrity": kind},
                         indent=2, ensure_ascii=False))
        return 0
    print(BAR)
    print(f"{pipe.meta.get('name')} {pipe.meta.get('version')}  |  ENGINE WORKSPACE - maintenance only")
    print(BAR)
    print(f"engine        {paths.repo_root()}")
    print("This folder is the shared workflow. No paper may live in or write to it.")
    print("Use this workspace only to maintain pipeline/, tools/, reference/ and .kiro/.")
    print()
    print(f"papers root   {root_line}  (central root, only for `wf new <slug> --central`)")
    print(f"papers        {n}      (python tools/wf.py papers)")
    print(f"integrity     {integ}")
    print()
    print("To work on a paper, open its folder as a Kiro workspace and run `wf init` there "
          "(in place).")
    print("Engine checks: python tools/wf.py doctor  |  .\\.venv\\Scripts\\python.exe -B tools\\selftest.py")
    return 0


def cmd_status(args) -> int:
    try:
        pipe, st, proj = _load(warn_stderr=False)
    except paths.EngineWorkspace:
        return _engine_banner(args.json)
    stage = pipe.stage(st.current)
    results = gates.run_stage(pipe, st, proj, stage)
    ok, blocking, warned = gates.summarize(results)
    warning = _engine_cwd_warning(proj)

    if args.json:
        print(json.dumps({
            "engine_cwd_warning": bool(warning),
            "pipeline": pipe.meta.get("name"),
            "engine_version": pipe.meta.get("version"),
            "state_pipeline_version": st.data.get("pipeline_version"),
            "engine_pin": st.engine_pin,
            "current": stage.id,
            "index": stage.index + 1,
            "total": len(pipe.stages),
            "title": stage.title,
            "card": paths.rel(stage.card_path()),
            "gate_ok": ok,
            "blocking": blocking,
            "warnings": warned,
            "outputs": stage.outputs,
            "paper_overrides": pipe.override_notes,
            "stage_skipped": stage.skipped,
            "results": [{"check": r.check, "label": r.label, "detail": r.detail} for r in results],
        }, indent=2, ensure_ascii=False))
        return 0

    if warning:
        print(warning)
    print(BAR)
    print(f"{pipe.meta.get('name')} {pipe.meta.get('version')}  |  stage {stage.index + 1}/{len(pipe.stages)}  |  {stage.id}")
    print(stage.title)
    print(BAR)
    print(f"engine  {paths.repo_root()}" + _fork_suffix(proj))
    print(f"paper   {proj}   ({_PROJECT_SOURCE or paths.describe_project_source(pipe.layout)})")
    for line in _data_lines(proj):
        print(f"data    {line}")
    # 1.12.0 (C2): both versions, always - the engine that last opened the state and the
    # gate set the paper is pinned to (changes only with `wf migrate --yes`).
    print(f"version engine {pipe.meta.get('version')}; state recorded by "
          f"{st.data.get('pipeline_version', '?')}; paper pinned to {st.engine_pin}")
    if st.engine_pin != str(pipe.meta.get("version")):
        print(f"pin     paper pinned to engine {st.engine_pin} (engine {pipe.meta.get('version')}); "
              "completed stages keep their gate set - `wf migrate` to adopt the new one")
    if (proj / "project").is_dir():
        print(f'!! {proj / "project"} exists - "project/" in cards means this paper folder; '
              "move its contents up one level")
    print()
    _print_invariants(pipe, proj)
    _print_overrides(pipe)
    _print_tolerances(proj)
    _print_progress(pipe, st)
    print()
    print(f"GATE  ({len(results) - blocking - warned}/{len(results)} passing"
          + (f", {warned} warning(s)" if warned else "") + ")")
    if ok:
        print(f"  gate is GREEN -> you may run:  {wf()} advance --note \"...\"")
    else:
        _gate_lines([r for r in results if not r.ok], proj)
    print()

    _print_visual_debts(pipe, st, proj)

    notes = st.data.get("handoff", [])
    print("LAST HANDOFF")
    if notes:
        last = notes[-1]
        print(f"  [{last['stage']} @ {last['at']}]")
        for line in last["note"].splitlines():
            print(f"  {line}")
    else:
        print("  (none yet)")
    print()

    if stage.needs_user:
        print("!! THIS STAGE NEEDS INPUT FROM THE USER. Ask, then proceed.")
        print()

    print("DECLARED OUTPUTS FOR THIS STAGE (create these, nothing else)")
    for o in stage.outputs:
        # Show where the file actually goes: a journal-variable output moves into the variant
        # once the scientific record is frozen and a journal is chosen.
        actual = scifreeze.resolve(proj, o)
        flag = "ok " if (proj / actual).exists() else "-- "
        suffix = "" if actual == o else f"   (journal variant; declared {o})"
        print(f"  {flag} {_loc('project/' + actual, proj)}{suffix}")
    print()

    if not args.brief:
        card = stage.card_path()
        print(DASH)
        print(f"STAGE CARD  ({paths.rel(card)})")
        print(DASH)
        if card.exists():
            print(_card_text(card, proj))
        else:
            print(f"!! card file missing: {card}")
        print(DASH)
    return 0


def _data_lines(proj: Path) -> list[str]:
    from . import datasources
    lines = datasources.describe(proj)
    return lines or ["(none declared; register each dataset in place: wf data add <path>)"]


def _fork_suffix(proj: Path) -> str:
    """'  [ENGINE FORK of <base> <ver>: N file(s) differ]' when this paper runs its own fork."""
    if not paths.is_fork_root(paths.repo_root()):
        return ""
    from . import enginefork
    info = paths.fork_info() or {}
    try:
        n = len(enginefork.changed_files(proj))
    except Exception:  # noqa: BLE001
        n = "?"
    return (f"  [ENGINE FORK of {info.get('base_engine')} {info.get('base_version')}: {n} "
            f"file(s) differ; diff in .wf/engine_fork.diff]")


def handoff_lines(pipe, st, proj: Path) -> list[str]:
    """1.12.0 (E1): a compact context pack (<= ~60 lines) for a new session or a delegated step."""
    from . import reviewrounds as rr
    from .checks.statecheck import parked_visual
    stage = pipe.stage(st.current)
    details = paths.repo_root() / "reference" / "stage_details" / Path(stage.card_path()).name
    fork = paths.is_fork_root(paths.repo_root())
    out = [f"paper: {proj}  (this workspace only; never read or write another paper)",
           f"engine: {paths.repo_root()}" + (" (project-local fork)" if fork else " (read-only)")
           + _fork_suffix(proj),
           *[f"data: {d}" for d in _data_lines(proj)],
           f"engine {pipe.meta.get('version')} | state recorded by {st.data.get('pipeline_version')}"
           f" | paper pinned to {st.engine_pin}",
           f"stage: {stage.id} ({stage.index + 1}/{len(pipe.stages)}) - {stage.title}"
           + ("  [NEEDS USER INPUT]" if stage.needs_user else ""),
           f"card: {stage.card_path()}" + (f"  (details: {details})" if details.is_file() else "")]
    try:
        import copy
        local = copy.copy(stage)  # live (network) checks are skipped: the pack must be cheap
        local.gate = [g for g in stage.gate if not g.get("live")]
        results = gates.run_stage(pipe, st, proj, local, reuse=True)
        ok, blocking, warned = gates.summarize(results)
        fails = [r.check for r in results if r.blocking]
        warns = [r.check for r in results if not r.ok and not r.blocking]
        out.append(f"gate: {'GREEN' if ok else 'RED'}"
                   + (f"; failing: {', '.join(fails)}" if fails else "")
                   + (f"; warnings: {', '.join(warns)}" if warns else ""))
    except Exception as exc:  # noqa: BLE001 - the pack must print even if a check breaks
        ok = False
        out.append(f"gate: not evaluated ({type(exc).__name__})")
    rid = st.data.get("active_revision_round")
    if rid:
        try:
            rev = json.loads((st.dir / "revisions" / f"{rid}.json").read_text(encoding="utf-8"))
            items = rev.get("items", [])
            done = sum(1 for i in items if i.get("status") == "done")
            out.append(f"rework round {rid} ({rev.get('status')}): {done}/{len(items)} item(s) done")
            out += [f"  - pending {i.get('id')}: {str(i.get('request', ''))[:90]}"
                    for i in items if i.get("status") != "done"][:5]
        except (OSError, ValueError):
            out.append(f"rework round {rid}: unreadable")
    questions = []
    for scope in rr.SCOPES:
        last = rr.latest(proj, scope)
        if not last:
            continue
        if not last.get("closed_at"):
            out.append(f"review round {last['id']} ({scope}) open: close it with --report")
            continue
        pend = rr.pending_author(last)
        if pend:
            questions += [f"{last['id']} {f['id']} [{f.get('category')}] {f.get('summary', '')[:80]}"
                          for f in pend]
        if last.get("user_decision") is None:
            questions.append(f"{last['id']}: another review round, or '{rr.CONFIRM_PHRASES[0]}'?")
    mode = str(pipe.targets.get("visual_review_mode", "inline")).strip().lower()
    debts = [n for n, _, _ in parked_visual(pipe, st, mode)]
    if debts:
        out.append(f"visual looks owed at S23: {', '.join(debts)}")
    out.append("pending user questions: " + ("none" if not questions else ""))
    out += [f"  - {q}" for q in questions[:8]]
    out.append("last events:")
    out += [f"  - {e.get('at', '')} {e.get('kind')}: {str(e.get('detail', ''))[:100]}"
            for e in st.data.get("events", [])[-5:]]
    if questions:
        nxt = "ask the user the pending question(s) above; record with tools/review_round.py"
    elif ok:
        nxt = f'{wf()} advance --note "..."'
    else:
        nxt = f"fix the failing gate(s), then {wf()} check"
    out.append(f"next: {nxt}")
    return out


def cmd_handoff(args) -> int:
    pipe, st, proj = _load(warn_stderr=False)
    lines = handoff_lines(pipe, st, proj)
    if args.md:
        print("# medpaper handoff\n")
        print("\n".join(ln if ln.startswith("  ") else f"- {ln}" for ln in lines))
    else:
        print("\n".join(lines))
    return 0


def _print_tolerances(proj: Path) -> None:
    try:
        from . import reproproof
        tols, _problems = reproproof.load_tolerances(proj)
    except Exception:  # noqa: BLE001
        return
    for file, tol in sorted(tols.items()):
        print(f"tolerance  {file}  abs={tol.abs} rel={tol.rel}  reason: {tol.reason}")
    if tols:
        print()


def cmd_card(args) -> int:
    try:
        pipe, st, proj = _load(need_state=False, warn_stderr=False)
    except paths.EngineWorkspace:
        if not args.stage:
            raise
        pipe, st, proj = registry.load(), None, None
    if proj is not None:
        _warn_engine_cwd(proj, stdout=True)
    if args.stage:
        stage = pipe.resolve(args.stage)
    else:
        st.load()
        stage = pipe.stage(st.current)
    card = stage.card_path()
    if not card.exists():
        print(f"card missing: {card}")
        return 1
    print(_card_text(card, proj))
    return 0


def _card_text(card: Path, proj: Path | None) -> str:
    """The card with its details pointer made absolute (readable from a paper workspace)."""
    text = card.read_text(encoding="utf-8").rstrip()
    if proj is None:  # engine workspace: the master card, unchanged
        return text
    text = text.replace("reference/stage_details/",
                        (paths.repo_root() / "reference" / "stage_details").as_posix() + "/")
    return _loc(text, proj)


def cmd_check(args) -> int:
    pipe, st, proj = _load(warn_stderr=False)
    if not args.json:
        _warn_engine_cwd(proj, stdout=True)
    stage = pipe.resolve(args.stage) if args.stage else pipe.stage(st.current)
    results = gates.run_stage(pipe, st, proj, stage, record=True,
                              reuse=bool(getattr(args, "reuse", False)))
    ok, blocking, warned = gates.summarize(results)
    if getattr(args, "summary", False) or getattr(args, "quiet", False):
        # 1.9.0 (#21): short output for agent shells that time out or truncate long logs.
        if not getattr(args, "summary", False):
            _gate_lines([r for r in results if not r.ok], proj)
        failing = [r.check for r in results if r.blocking]
        print(f"{stage.id}: {'GREEN' if ok else 'RED'} {len(results) - blocking - warned}/"
              f"{len(results)} passing, {blocking} blocking, {warned} warning(s)"
              + (f"; failing: {', '.join(failing)}" if failing else ""))
        return 0 if ok else 2
    if args.json:
        print(json.dumps({
            "stage": stage.id, "gate_ok": ok, "blocking": blocking, "warnings": warned,
            "results": [{"check": r.check, "ok": r.ok, "label": r.label,
                         "detail": r.detail, "hints": r.hints} for r in results],
        }, indent=2, ensure_ascii=False))
        return 0 if ok else 2
    print(f"gate: {stage.id} - {stage.title}")
    print(DASH)
    if getattr(args, "all", False):
        _gate_lines(results, proj)
    else:
        # 1.12.0 (B3): failures and warnings only, plus one summary line; the full listing
        # (every PASS with its detail) goes to .wf/logs/check_<stage>.log.
        _gate_lines([r for r in results if not r.ok], proj)
        full = _write_check_log(proj, stage, results)
        if full:
            print(f"  ({len([r for r in results if r.ok])} passing check(s) not shown; full "
                  f"listing: {full}; or `wf check --all`)")
    print(DASH)
    if ok:
        print(f"GREEN ({warned} warning(s))" if warned else "GREEN")
        return 0
    failing = [r.check for r in results if r.blocking]
    print(f"RED - {blocking} blocking issue(s): {', '.join(failing)}")
    return 2


def _write_check_log(proj: Path, stage, results) -> str:
    try:
        log = proj / ".wf" / "logs" / f"check_{stage.id}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        lines = [f"gate: {stage.id} - {stage.title}"]
        for r in results:
            lines.append(f"  [{r.label}] {r.check}")
            if r.detail:
                lines.append(f"         {r.detail}")
            lines += [f"         -> {h}" for h in r.hints]
        log.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return str(log)
    except OSError:
        return ""


def cmd_migrate(args) -> int:
    """1.9.0 (#8): explicit engine migration of a pinned paper."""
    pipe, st, proj = _load(warn_stderr=False)
    engine = str(pipe.meta.get("version", "0"))
    pin = st.engine_pin
    print(f"paper pinned to engine {pin}; this engine is {engine}")
    newer = sorted({f"{s.id}: {g['check']} (since {g['since']})" for s in pipe.stages
                    for g in s.gate if g.get("since") and st.pin_excludes(s.id, g.get("since"))})
    print("gates that would start re-judging completed stages:"
          + ("" if newer else " none"))
    for line in newer:
        print(f"  {line}")
    if not args.yes:
        print("migration notes recorded for this paper:")
        for e in st.data.get("events", []):
            if e.get("kind", "").startswith("requirements_"):
                print(f"  - {e.get('detail', '')}")
        print("run `wf migrate --yes` to adopt them")
        return 0
    notes = st.migrate_pin(engine)
    print(f"pinned {pin} -> {engine}; {len(notes)} migration note(s):")
    for n in notes:
        print(f"  - {n}")
    return 0


def cmd_advance(args) -> int:
    pipe, st, proj = _load(warn_stderr=False)
    _warn_engine_cwd(proj, stdout=True)
    stage = pipe.stage(st.current)

    # A paper-local skip is itself the audited decision: the reason lives in overrides.toml,
    # is printed on every status call, and is copied into durable state here. It does not need
    # fake outputs, a fake green gate or a handoff note pretending work was done.
    if stage.skipped:
        nxt, skipped_after = pipe.transition_after(stage.id)
        chain = [(s.id, s.skip_reason, s.override_fingerprint) for s in skipped_after]
        st.skip_current(stage.id, stage.skip_reason, nxt.id if nxt else None, chain,
                        stage.override_fingerprint)
        labels = [stage.id, *[s.id for s in skipped_after]]
        print(f"paper-local override skipped: {', '.join(labels)}")
        for sid in labels:
            print(f"  {sid}: {pipe.stage(sid).skip_reason}")
        if nxt:
            print(f"now at {nxt.id} - {nxt.title}")
            print(f"\nnext:  {wf()} status")
        else:
            print("pipeline complete (remaining stages were explicitly skipped for this paper).")
        return 0

    results = gates.run_stage(pipe, st, proj, stage, reuse=True)
    ok, blocking, _ = gates.summarize(results)
    non_overridable_failures = [r for r in results if r.blocking and
                                r.check in NON_OVERRIDABLE_GATES]
    if non_overridable_failures:
        print(f"refusing to advance: {len(non_overridable_failures)} non-overridable "
              f"gate(s) failed in {stage.id}")
        print(DASH)
        _gate_lines(non_overridable_failures, proj)
        print(DASH)
        failed_names = {result.check for result in non_overridable_failures}
        if "data_acquisition_complete" in failed_names:
            print("--force cannot waive full-data acquisition. Acquire the complete "
                  "protocol-defined universe and exhaust pagination; if access is truly "
                  "source-limited, obtain and record the user's explicit authorization.")
        reference_failures = failed_names & {
            "reference_provenance", "refs_library", "bib_ris_match_library", "citekeys_resolve"
        }
        if reference_failures:
            print("--force cannot waive bibliographic provenance. Re-fetch the real PubMed "
                  "record or remove/replace the citation.")
        if "revision_rounds_closed" in failed_names:
            print("--force cannot waive an unfinished revision round. Complete every recorded "
                  "item, return through its gates, and close the round at the review stage.")
        if "review_round_approved" in failed_names:
            print("--force cannot waive a review point. Finish the subagent review round, report "
                  "it, and record the user's answer with tools/review_round.py decide.")
        if "s19_review_release_explicit" in failed_names:
            print("--force cannot waive S19 review. Present the current versioned ZIP and exact "
                  "artifact paths, then wait for the user's explicit no-further-review statement.")
        freeze_failures = failed_names & {
            "scientific_freeze_captured", "scientific_freeze_intact",
            "journal_variant_ready", "variant_preserves_science",
        }
        if freeze_failures:
            print("--force cannot waive the S19 scientific freeze or journal-variant boundary. "
                  "Freeze the reviewed science, open a fresh S20 variant, and put every "
                  "journal-specific edit under 08_submission/manuscript/.")
        if "paper_scripts_scoped" in failed_names:
            print("--force cannot run paper code that has no paper root. Use `wf run-script` and "
                  "derive paths from MEDPAPER_PROJECT or wfcore.paths.project_dir().")
        if "analysis_reproduces" in failed_names:
            print("--force cannot waive re-execution. Run reproduce.py run, make the scripts "
                  "deterministic or declare a justified tolerance (<= 1e-6), and re-run.")
        if "results_have_environment" in failed_names:
            print("--force cannot waive environment receipts. Write every results file with "
                  "write_results() from a top-level 03_analysis/code script via wf run-script.")
        if "reporting_checklist_complete" in failed_names:
            print("--force cannot waive a journal-required reporting checklist. Every item of "
                  "the required guideline needs a row whose location exists in the submitted "
                  "documents.")
        return 2
    if not ok and not args.force:
        print(f"refusing to advance: {blocking} blocking issue(s) in {stage.id}")
        print(DASH)
        _gate_lines([r for r in results if not r.ok], proj)
        print(DASH)
        print("fix them, or override deliberately with --force (recorded in state)")
        return 2

    note = args.note
    if pipe.policy.get("handoff_required", True) and not note and not st.notes_for(stage.id):
        print("refusing to advance: no handoff note recorded for this stage.")
        print(f'  {wf()} advance --note "what was produced, what was decided, what is still open"')
        print("A handoff note is how the next session (or the next you, post-compaction) picks this up.")
        return 2
    if note:
        st.add_note(note, stage.id)
    if not ok and args.force:
        st.event("force_advance", f"{stage.id} with {blocking} blocking issue(s)")
        st.add_note(f"[FORCED ADVANCE] gate had {blocking} blocking issue(s): "
                    + "; ".join(f"{r.check}: {r.detail}" for r in results if r.blocking), stage.id)

    if stage.id == "S19_human_review" and st.data.get("resume_package_revision"):
        # 1.7.0: re-approved post-S19 science goes straight back to the S24 package round;
        # S20-S23 stay completed and only the journal-copy closure is reopened.
        from . import revision
        try:
            rid = revision.resume_package(proj, pipe, st)
        except (OSError, KeyError, ValueError) as exc:
            print(f"refusing to advance: {exc}")
            return 2
        print(f"S19 closed. resumed package revision {rid} at S24_package_human_review")
        print("next:  python tools/rework.py status   (merge the science into the journal copy)")
        return 0

    nxt, skipped_between = pipe.transition_after(stage.id)
    st.complete(stage.id, nxt.id if nxt else None,
                [(s.id, s.skip_reason, s.override_fingerprint) for s in skipped_between],
                stage.override_fingerprint)
    if skipped_between:
        print("paper-local override also skipped:")
        for skipped_stage in skipped_between:
            print(f"  {skipped_stage.id}: {skipped_stage.skip_reason}")
    if nxt:
        print(f"{stage.id} closed. now at {nxt.id} - {nxt.title}")
        print(f"\nnext:  {wf()} status")
    else:
        print(f"{stage.id} closed. pipeline complete.")
    return 0


def cmd_loop(args) -> int:
    pipe, st, proj = _load()
    from . import revision
    open_round = revision.active(proj)
    if revision.is_scoped(open_round):
        print(f"refusing to loop: scoped revision {open_round.get('round_id')} is open; it is "
              "fixed in place (tools/rework.py status). Close it, or convert it while still "
              "collecting with `rework.py batch --rewind`.")
        return 2
    target = pipe.resolve(args.to)
    cur = pipe.stage(st.current)
    if target.index > cur.index:
        print(f"{target.id} is ahead of {cur.id}; use advance, not loop")
        return 1
    st.add_note(f"[LOOP] returning to {target.id}: {args.why}", cur.id)
    reset_ids = [target.id, *[s.id for s in pipe.stages_after(target.id)]]
    st.reset_forward(reset_ids[1:])
    st.clear_decisions_for(reset_ids)
    st.rewind(target.id, args.why)
    print(f"returned to {target.id} - {target.title}")
    print("stages after it are pending again; their artifacts were left untouched")
    return 0


def cmd_note(args) -> int:
    _, st, _ = _load()
    st.add_note(args.text)
    print(f"noted against {st.current}")
    return 0


def cmd_decide(args) -> int:
    _, st, _ = _load()
    # 1.10.0 (#13): user approval is never inferred from wording through `wf decide`.
    if args.name in ("manuscript_human_reviewed", "submission_package_user_confirmed"):
        print(f"{args.name} is recorded only by tools/review_round.py decide no_further_review "
              "--words \"我确认这一版\" (the user's exact sentence; 'OK'/'可以' do not count)")
        return 1
    if len(args.why.strip()) < 40:
        print("rationale too short (need >= 40 chars). A decision without a reason is a guess.")
        return 1
    from . import argtext
    if argtext.suspicious(args.why):  # 1.12.0 (C1): never store mojibake
        print(f"refusing: --why {argtext.suspicious(args.why)}; pass it with --why-file "
              "<utf-8 file> (or --why-b64)")
        return 1
    st.record_decision(args.name, args.value, args.why)
    stored = json.loads(st.file.read_text(encoding="utf-8")).get("decisions", {}).get(args.name, {})
    if argtext.suspicious(stored.get("rationale", "")):
        print("warning: the stored rationale does not read back cleanly; re-record it with --why-file")
        return 1
    st.add_note(f"[DECISION] {args.name} = {args.value}\n{args.why}")
    print(f"recorded {args.name} = {args.value}")
    return 0


def cmd_tree(args) -> int:
    pipe, st, proj = _load()
    print(f"{pipe.meta.get('name')} {pipe.meta.get('version')}  ({len(pipe.stages)} stages)")
    print(DASH)
    for s in pipe.stages:
        m = _mark(pipe, st, s)
        suffix = (f"  [paper-local skip: {s.skip_reason}]" if s.skipped else "")
        print(f"[{m}] {s.index + 1:>2}. {s.id:<20} {s.title}{suffix}")
        if args.verbose:
            for o in s.outputs:
                print(f"        out  {'ok' if (proj / o).exists() else '--'}  {o}")
            for g in s.gate:
                extra = " ".join(f"{k}={v}" for k, v in g.items() if k != "check")
                print(f"        gate {g['check']} {extra}".rstrip())
    print(DASH)
    for name, rec in st.data.get("decisions", {}).items():
        print(f"decision  {name} = {rec['value']}  ({rec['at']})")
    return 0


def cmd_clean(args) -> int:
    pipe, st, proj = _load()
    declared, allowed = _declared_and_free(pipe)
    declared = set(declared) | paths.user_files(proj)
    tmp = pipe.layout.get("temp_dir", "temp")
    scratch, orphans = [], []
    foreign = paths.foreign_prefixes(proj)  # 1.14.1: never touch an older attempt or the archive
    for p in proj.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(proj).as_posix()
        if rel.startswith(foreign):
            continue
        if rel.startswith(f"{tmp}/"):
            if p.name != ".gitkeep":
                scratch.append(rel)
            continue
        if rel in declared or any(fnmatch.fnmatch(rel, g) for g in allowed):
            continue
        orphans.append(rel)

    print(f"scratch files in project/{tmp}/: {len(scratch)}")
    for r in scratch[:40]:
        print(f"  del  {r}")
    print(f"\nundeclared files elsewhere: {len(orphans)}")
    for r in orphans[:40]:
        print(f"  ??   {r}")
    if orphans:
        print("\nundeclared files are NOT auto-deleted. Either:")
        print("  - move them into the right folder, or")
        print("  - declare them in pipeline.toml (stage outputs / [freeform].globs), or")
        print("  - delete them yourself if they were scratch")
    if not args.apply:
        print("\n(dry run; pass --apply to delete the scratch files)")
        return 0
    for r in scratch:
        (proj / r).unlink(missing_ok=True)
    st.event("clean", f"deleted {len(scratch)} scratch file(s)")
    st.save()
    print(f"\ndeleted {len(scratch)} scratch file(s)")
    return 0


def cmd_archetype(args) -> int:
    """Print one archetype instead of making the agent read the whole registry.

    reference/archetypes.toml is ~11 KB. A figure script needs exactly one entry from it, so
    reading the file is a few thousand wasted tokens per figure.
    """
    import tomllib
    p = paths.reference_dir() / "archetypes.toml"
    if not p.exists():
        print(f"missing {paths.rel(p)}")
        return 1
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    reg = data.get("archetype", {})

    if not args.name:
        universal = data.get("meta", {}).get("universal_requires", [])
        print(f"{len(reg)} archetypes. Universal requirement(s): {', '.join(universal) or 'none'}\n")
        by_domain: dict[str, list[str]] = {}
        for key, spec in reg.items():
            by_domain.setdefault(spec.get("domain", "Other"), []).append(key)
        for domain in sorted(by_domain):
            print(f"{domain}")
            for key in sorted(by_domain[domain]):
                print(f"  {key:<24} {reg[key].get('label', '')}")
        print(f"\ndetail for one:  {wf()} archetype km_survival")
        return 0

    spec = reg.get(args.name)
    if spec is None:
        close = [k for k in reg if args.name.lower() in k or k in args.name.lower()]
        print(f"'{args.name}' is not in the registry.")
        if close:
            print(f"did you mean: {', '.join(close)}")
        print(f"list them all:  {wf()} archetype")
        return 1

    universal = data.get("meta", {}).get("universal_requires", [])
    print(f"{args.name}  -  {spec.get('label', '')}")
    print(f"domain    {spec.get('domain', '')}")
    print(f"use for   {spec.get('use_for', '')}")
    req = list(dict.fromkeys(list(universal) + list(spec.get("requires", []))))
    print(f"\nrequires  (detected from the rendered figure; a miss FAILS the S11 gate)")
    for k in req:
        print(f"  {k}")
    if spec.get("advisory"):
        print(f"\nadvisory  (confirm by eye; never blocking)")
        for k in spec["advisory"]:
            print(f"  {k}")
    if spec.get("forbids"):
        print(f"\nforbids")
        for k in spec["forbids"]:
            print(f"  {k}")
    notes = (spec.get("notes") or "").strip()
    if notes:
        print("\nnotes")
        for line in notes.splitlines():
            print(f"  {line.strip()}")
    return 0


def cmd_doctor(args) -> int:
    pipe = registry.load()
    rows: list[tuple[str, str, str]] = []
    proj: Path | None = None
    selection = ("current paper", "none selected", f"initialise this folder: {wf()} init")
    try:
        proj = paths.project_dir(pipe.layout, check_engine=False)
        selection = ("current paper", "ok", f"{proj} (from the working directory)")
    except paths.EngineWorkspace:
        selection = ("current paper", "ok", "engine workspace (no paper - expected)")
    except SystemExit as exc:
        msg = str(exc).replace("\n", " ")
        selection = (("current paper", "BROKEN", msg) if isinstance(exc, paths.PaperLocationError)
                     else ("current paper", "none selected", msg[:140]))
    from . import integrity
    kind, changed = integrity.engine_state(use_cache=False)
    rows_integrity = ("engine integrity", "BROKEN" if kind in ("modified", "untagged") else "ok",
                      {"clean": "release-tagged engine, no local edits",
                       "untagged": "; ".join(changed) + " - paper commands refuse (rc 3) until "
                                   "the maintainer releases it (tag vX.Y.Z) or checks out a release",
                       "dev": "MEDPAPER_ENGINE_DEV=1 (engine development)",
                       "worktree": "maintenance worktree",
                       "fork": "project-local engine fork (edits allowed, diff recorded)",
                       "unverifiable": "no git and no ENGINE_MANIFEST.json (cannot verify)"}
                      .get(kind, "local edits: " + ", ".join(changed[:6])
                           + " - paper commands refuse until the maintainer restores them"))
    try:
        if paths.active_marker().is_file():
            rows_integrity_legacy = ("legacy wf use marker", "ok",
                                     f"{paths.active_marker()} is ignored since 1.13.0 "
                                     "(papers come from the workspace)")
        else:
            rows_integrity_legacy = None
    except SystemExit:
        rows_integrity_legacy = None

    rows.append(("python", "ok", sys.version.split()[0]))
    rows.append(("pipeline.toml", "ok" if paths.pipeline_file().exists() else "MISSING",
                 paths.rel(paths.pipeline_file())))
    rows.append(rows_integrity)
    if (paths.repo_root() / ".git").exists():
        # 1.14.0 (H): the release state of the engine checkout, also in development mode.
        info = integrity.release_info(paths.repo_root())
        rows.append(("engine release", "ok" if info["tag"] else "WARN",
                     f"HEAD {info['head']} = {info['tag']}" if info["tag"] else
                     f"HEAD {info['head']} is untagged (not a release)"))
        if info["ahead"]:
            rows.append(("engine upstream", "WARN", f"{info['ahead']} commit(s) ahead of origin "
                         "(not pushed: unreleased engine work)"))
    if rows_integrity_legacy:
        rows.append(rows_integrity_legacy)

    root = paths.repo_root()
    kiro_files = (
        root / ".kiro/skills/medpaper-pipeline/SKILL.md",
        root / ".kiro/steering/medpaper-pipeline.md",
        root / ".kiro/hooks/medpaper-status.json",
        root / ".kiro/hooks/medpaper-skill-guard.json",
        root / "tools/install_adapters.py",
        root / "tools/hooks/skill_guard.py",
        root / "reference/skill_policy.toml",
    )
    missing_kiro = [p.relative_to(root).as_posix() for p in kiro_files if not p.is_file()]
    rows.append(("Kiro integration", "ok" if not missing_kiro else "MISSING",
                 "skill + steering + 2 hooks + skill guard present" if not missing_kiro else
                 "absent: " + ", ".join(missing_kiro)))

    # Read-only reviewer/reader agents. S15, S18 and S25 delegate to these; without them the
    # agent would have to review its own work and pull full texts into the main context.
    # 1.12.0: the reviewer may write only its report, the clinical writer only manuscript prose.
    agents = {"medpaper-reviewer": ("S18, S25"), "medpaper-deepreader": ("S15"),
              "medpaper-clinical-writer": ("S08, S09, S14, S16, S19")}
    agent_state = []
    for name, used_at in agents.items():
        p = root / f".kiro/agents/{name}.md"
        if not p.is_file():
            agent_state.append(f"{name} MISSING")
            continue
        scope = adapters.agent_scope_problems(name, p.read_text(encoding="utf-8"))
        agent_state.append(f"{name} ({used_at})" + (f" TOO BROAD: {'; '.join(scope)}" if scope else ""))
    bad_agents = [s for s in agent_state if "MISSING" in s or "TOO BROAD" in s]
    rows.append(("review subagents", "ok" if not bad_agents else "BROKEN",
                 "; ".join(agent_state)))

    global_skill = Path.home() / ".kiro/skills/medpaper-pipeline/SKILL.md"
    rows.append(("global skill", "ok" if global_skill.is_file() else "not installed",
                 str(global_skill).replace(str(Path.home()), "~") if global_skill.is_file()
                 else "`/` will not find it outside this workspace: run "
                      "python tools/install_adapters.py --global"))
    for name in adapters.GLOBAL_AGENTS:
        p = adapters.global_agents_dir() / name
        rows.append((f"global {name[:-3]}", "ok" if p.is_file() else "not installed",
                     str(p).replace(str(Path.home()), "~") if p.is_file() else
                     "paper workspaces cannot delegate: python tools/install_adapters.py --global"))

    # Adapters for other agents would drift silently against this Kiro-only checkout.
    obsolete = (
        root / "AGENTS.md", root / "CLAUDE.md", root / ".agents", root / ".claude",
        root / ".agent", root / ".medpaper-target", root / "INSTALL-CODEX.md",
        root / "reference/codex-integration.md",
    )
    present_obsolete = [p.relative_to(root).as_posix() for p in obsolete if p.exists()]
    rows.append(("other-agent adapters", "ok" if not present_obsolete else "stale",
                 "none" if not present_obsolete else "remove: " + ", ".join(present_obsolete)))

    missing_cards = [s.id for s in pipe.stages if not s.card_path().exists()]
    rows.append(("stage cards", "ok" if not missing_cards else "MISSING",
                 f"{len(pipe.stages) - len(missing_cards)}/{len(pipe.stages)} present"
                 + (f" - absent: {', '.join(missing_cards)}" if missing_cards else "")))

    checks.load_all()
    used = {g["check"] for s in pipe.stages for g in s.gate}
    unknown = sorted(used - set(checks.known()))
    rows.append(("gate checks", "ok" if not unknown else "BROKEN",
                 f"{len(used)} used, {len(checks.known())} registered"
                 + (f" - unknown: {', '.join(unknown)}" if unknown else "")))

    try:
        proot, source = paths.papers_root()
        if proot.is_dir():
            rows.append(("papers root", "ok",
                         f"{proot} ({source}), {len(paths.list_papers())} paper(s)"))
        else:
            rows.append(("papers root", "ok", f"{proot} ({source}, not created yet)"))
    except SystemExit as exc:
        rows.append(("papers root", "BROKEN", str(exc).replace("\n", " ")))
    rows.append(selection)
    if proj is not None:
        nested = [p.parents[1] for pat in ("*/.wf/state.json", "*/*/.wf/state.json")
                  for p in proj.glob(pat)]
        if (proj / "project").is_dir():
            rows.append(("paper layout", "BROKEN",
                         f"{proj / 'project'} exists: the project/ alias was taken literally; "
                         "move its contents up into the paper folder"))
        elif nested:
            rows.append(("paper layout", "BROKEN",
                         "nested paper(s): " + ", ".join(str(p) for p in nested[:3])))
        else:
            rows.append(("paper layout", "ok", str(proj)))
        guard = proj / ".kiro/hooks/medpaper-paper-guard.json"
        rows.append(("paper guard hook", "ok" if guard.is_file() else "MISSING",
                     "isolation hook installed" if guard.is_file() else
                     f'python "{paths.repo_root().as_posix()}/tools/install_adapters.py" '
                     f'--paper "{proj}"'))

    # The driver is stdlib-only; the science deps belong to the engine venv, so probe
    # that interpreter rather than whichever one happens to be running this command.
    policy, policy_problems = _language_policy()
    if policy_problems:
        rows.append(("language policy", "BROKEN", "; ".join(policy_problems[:4])))
    else:
        rows.append(("language policy", "ok", "reference/language_policy.toml"))
    sci = _science_python()
    rows.append(("science venv", "ok" if sci else "absent",
                 str(sci) if sci else "create it: uv venv .venv"))
    py = (policy or {}).get("python", {})
    required = list(py.get("required_modules", ["numpy", "pandas", "openpyxl", "docx",
                                                "matplotlib"]))
    optional = list(py.get("optional_modules", ["scipy"]))
    if sci:
        found = _probe_modules(sci, required + optional)
        for mod in required + optional:
            ok = found.get(mod)
            status = "ok" if ok else ("absent" if mod in optional else "MISSING")
            rows.append((f"  {mod}", status, "importable" if ok else
                         f"uv pip install --python {sci} {mod}"))
    else:
        rows.append(("  science deps", "unknown", "cannot probe without a venv"))

    rows.extend(_r_rows(policy or {}, proj))

    for exe, why in (("pandoc", "reference rendering"), ("git", "versioning")):
        p = shutil.which(exe)
        rows.append((exe, "ok" if p else "absent", p or f"optional, used for {why}"))

    key = os.environ.get("NCBI_API_KEY") or os.environ.get("PUBMED_API_KEY")
    rows.append(("NCBI_API_KEY", "ok" if key else "not set",
                 "10 req/s" if key else "3 req/s without a key; set NCBI_API_KEY to raise it"))

    rows.extend(_engine_hygiene_rows())

    width = max(len(r[0]) for r in rows)
    bad = 0
    for name, status, detail in rows:
        if status in ("MISSING", "BROKEN") or status.startswith("TOO OLD"):
            bad += 1
        print(f"{name:<{width}}  {status:<16} {detail}")
    print(DASH)
    print("doctor: OK" if bad == 0 else f"doctor: {bad} problem(s) need attention")
    return 0 if bad == 0 else 1


_VERSION_RE = re.compile(r"^\d+(\.\d+)*$")


def _language_policy() -> tuple[dict | None, list[str]]:
    """Load and validate reference/language_policy.toml -> (data, problems)."""
    import tomllib
    p = paths.reference_dir() / "language_policy.toml"
    if not p.is_file():
        return None, [f"missing {paths.rel(p)}"]
    try:
        data = tomllib.loads(p.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        return None, [f"malformed {paths.rel(p)}: {exc}"]
    return data, validate_language_policy(data)


def validate_language_policy(data: dict) -> list[str]:
    problems: list[str] = []
    r = data.get("r", {})
    py = data.get("python", {})
    if not _VERSION_RE.match(str(r.get("min_version", ""))):
        problems.append("[r].min_version must be a dotted version")
    for table in ("required", "optional"):
        for key, value in (r.get(table) or {}).items():
            if isinstance(value, dict):
                problems.append(f"{key}: package names containing '.' must be quoted")
            elif not isinstance(value, str) or not _VERSION_RE.match(value):
                problems.append(f"[r.{table}].{key} must be a version string like \"1.2.0\"")
    overlap = set(r.get("owns", [])) & set(py.get("owns", []))
    if overlap:
        problems.append(f"[r].owns and [python].owns overlap: {sorted(overlap)}")
    required = set((r.get("required") or {}).keys())
    for task in data.get("task", []):
        lang = task.get("language")
        if lang not in ("python", "R", "either"):
            problems.append(f"task {task.get('id')}: language must be python, R or either")
        if lang == "R":
            missing = [pkg for pkg in task.get("packages", []) if pkg not in required]
            if missing:
                problems.append(f"task {task.get('id')}: packages not in [r.required]: {missing}")
    return problems


def _vtuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:4]) or (0,)


# R packages a paper's own scripts reach through an engine helper rather than library().
_R_HELPER_PACKAGES = {
    "recipe_km": ("survival", "ggsurvfit"), "recipe_cif": ("tidycmprsk", "ggsurvfit"),
    "recipe_roc": ("pROC",), "recipe_volcano": ("ggrepel",),
    "curve_table_km": ("survival",), "curve_table_cif": ("tidycmprsk",),
}
_R_USE = re.compile(r"""(?:\b(?:library|require|requireNamespace|loadNamespace)\s*\(\s*["']?"""
                    r"""([A-Za-z][A-Za-z0-9.]*)|\b([A-Za-z][A-Za-z0-9.]*):::?)""")
_R_PAPER_DIRS = ("02_data/acquisition", "03_analysis/code", "04_tables/code", "05_figures/code")
_R_BASE = ("base", "stats", "utils", "graphics", "grDevices", "methods", "grid", "tools",
           "parallel", "splines", "datasets", "compiler", "stats4", "tcltk")


def r_packages_used(proj: Path | None) -> dict[str, str]:
    """{package: first paper-relative script using it} from the paper's own R scripts."""
    used: dict[str, str] = {}
    if proj is None:
        return used
    for d in _R_PAPER_DIRS:
        base = Path(proj) / d
        if not base.is_dir():
            continue
        for f in sorted(base.rglob("*")):
            if not f.is_file() or f.suffix.casefold() != ".r":
                continue
            rel = f.relative_to(proj).as_posix()
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            text = "\n".join(line.split("#", 1)[0] for line in text.splitlines())
            for m in _R_USE.finditer(text):
                used.setdefault(m.group(1) or m.group(2), rel)
            for helper, pkgs in _R_HELPER_PACKAGES.items():
                if re.search(rf"\b{helper}\s*\(", text):
                    for pkg in pkgs:
                        used.setdefault(pkg, f"{rel} ({helper})")
    return used


def _r_rows(policy: dict, proj: Path | None = None) -> list[tuple[str, str, str]]:
    """R and its packages, scoped to what is actually needed (1.7.1).

    Engine core (the figures task + jsonlite) is required whenever R draws the figures. Any
    other package is required only when the current paper's own R scripts use it; the rest of
    [r.required] is reported for information, so a paper that never fits a Fine-Gray model is
    not blocked by a missing cmprsk."""
    import subprocess
    rows: list[tuple[str, str, str]] = []
    rscript = shutil.which("Rscript")
    if not rscript:
        return [("R", "BROKEN", "Rscript not on PATH; figures default to R (targets.figure_engine)")]
    r = policy.get("r", {})
    catalog = {k: v for k, v in (r.get("required") or {}).items() if isinstance(v, str)}
    core = {"jsonlite"} | {p for t in policy.get("task", []) if t.get("id") == "figures"
                           for p in t.get("packages", [])}
    used = {k: v for k, v in r_packages_used(proj).items() if k not in _R_BASE}
    req = {k: v for k, v in catalog.items() if k in core or k in used}
    req.update({k: "0" for k in used if k not in req})
    info = {k: v for k, v in catalog.items() if k not in req}
    opt = {k: v for k, v in (r.get("optional") or {}).items() if isinstance(v, str)
           and k not in req}
    opt.update(info)
    code = ("a <- commandArgs(trailingOnly = TRUE); "
            "cat('R\\t', R.version$major, '.', R.version$minor, '\\n', sep = ''); "
            "for (p in a) { v <- tryCatch(as.character(utils::packageVersion(p)), "
            "error = function(e) 'MISSING'); cat('pkg\\t', p, '\\t', v, '\\n', sep = '') }")
    try:
        done = subprocess.run([rscript, "--vanilla", "-e", code, *req, *opt],
                              capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [("R packages", "BROKEN", f"probe failed: {exc}")]
    if done.returncode != 0:
        return [("R packages", "BROKEN", f"probe failed: {(done.stderr or '')[-200:]}")]
    version, pkgs = "", {}
    for line in (done.stdout or "").splitlines():
        parts = line.strip().split("\t")
        if parts[0] == "R" and len(parts) == 2:
            version = parts[1]
        elif parts[0] == "pkg" and len(parts) == 3 and (parts[1] in req or parts[1] in opt):
            pkgs[parts[1]] = parts[2]
    min_v = str(r.get("min_version", "0"))
    rows.append(("R", "ok" if _vtuple(version) >= _vtuple(min_v) else "BROKEN",
                 f"{version} ({rscript})" + ("" if _vtuple(version) >= _vtuple(min_v)
                                             else f" < required {min_v}")))
    for name, minimum in req.items():
        have = pkgs.get(name, "MISSING")
        if have == "MISSING":
            why = f"used by {used[name]}" if name in used else "engine core (R figures)"
            rows.append((f"  {name}", "MISSING", f"R package needed: {why}"))
        elif minimum != "0" and _vtuple(have) < _vtuple(minimum):
            rows.append((f"  {name}", "BROKEN", f"TOO OLD {have} < {minimum}"))
        else:
            rows.append((f"  {name}", "ok", have))
    for name in opt:
        have = pkgs.get(name, "MISSING")
        rows.append((f"  {name}", "ok" if have != "MISSING" else "absent",
                     have if have != "MISSING" else
                     ("info: not used by the current paper's scripts" if name in info
                      else "optional")))
    return rows


ENGINE_TOP_LEVEL = frozenset({".git", ".gitignore", ".kiro", ".venv", "bootstrap.py", "docs",
                              "LICENSE", "pipeline", "README.md", "reference",
                              "requirements.txt", "tools", "workflow.md", "ENGINE_FORK.json",
                              "ENGINE_MANIFEST.json"})
ENGINE_DATA_SUFFIXES = (".xlsx", ".docx", ".pdf", ".csv", ".tsv", ".sav", ".dta", ".parquet",
                        ".rds", ".rdata", ".zip")


def _engine_hygiene_rows() -> list[tuple[str, str, str]]:
    """Has paper work leaked into the engine?

    The engine is maintenance-only since 1.5.0. Any paper directory, run state, scratch folder,
    data/document file or unknown top-level entry is BROKEN; nothing is deleted automatically.
    """
    root = paths.repo_root()
    offenders: list[str] = []
    for name in ("papers", "project", ".wf", ".review_stash", "temp"):
        if (root / name).exists():
            offenders.append(name + "/" + ("  (legacy .wf/active: delete it; re-select with "
                                           "wf use)" if name == ".wf" and
                                           (root / ".wf/active").exists() else ""))
    skip = {".git", ".venv"} | set(runner.ENGINE_IGNORED_CACHES)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip]
        here = Path(dirpath)
        for d in dirnames:
            if d == ".wf" and here != root:
                offenders.append((here / d).relative_to(root).as_posix() + "/")
        for f in filenames:
            if f.lower().endswith(ENGINE_DATA_SUFFIXES):
                offenders.append((here / f).relative_to(root).as_posix())
    for entry in root.iterdir():
        if entry.name not in ENGINE_TOP_LEVEL and entry.name not in runner.ENGINE_IGNORED_CACHES:
            offenders.append(entry.name + ("/" if entry.is_dir() else ""))
    offenders = sorted(dict.fromkeys(offenders))
    if offenders:
        return [("engine purity", "BROKEN",
                 "paper artifacts in the engine: " + ", ".join(offenders[:8])
                 + " - move them into the paper they belong to (never deleted automatically)")]
    return [("engine purity", "ok", "no paper artifacts in the engine")]


def _science_python() -> Path | None:
    """The venv interpreter that runs figures/tables/analysis, if it exists."""
    return runner.science_python()


def _probe_modules(python: Path, mods) -> dict[str, bool]:
    import subprocess
    code = (
        "import importlib.util, json\n"
        f"m={list(mods)!r}\n"
        "print(json.dumps({x: importlib.util.find_spec(x) is not None for x in m}))"
    )
    try:
        out = subprocess.run([str(python), "-c", code], capture_output=True, text=True, timeout=60)
        return json.loads(out.stdout.strip() or "{}")
    except Exception:  # noqa: BLE001
        return {}


def _engine_write_snapshot() -> dict[str, tuple[int, int]]:
    """Tripwire for a paper script writing anywhere into the shared engine."""
    return runner.engine_snapshot()


def cmd_run_script(args) -> int:
    """Run one paper-owned Python/R script with the selected paper exported."""
    _, _, proj = _load()
    raw = Path(args.script)
    script = (raw if raw.is_absolute() else proj / raw).resolve()
    try:
        script.relative_to(proj.resolve())
    except ValueError:
        print(f"refusing to run a script outside the paper: {script}")
        return 2
    try:
        cmd = [*runner.interpreter_for(script), str(script), *args.script_args]
    except runner.RunnerError as exc:
        print(str(exc))
        return 2
    if not script.is_file():
        print(f"paper script not found (or not .py/.R): {script}")
        return 2
    from . import revision as _revision
    drift = _revision.certified_drift(proj)
    if drift:
        # Caught at render time, not at the next review gate (1.8.0).
        print("refused: frozen or round-certified source(s) were edited outside a revision round:")
        for rel in drift[:10]:
            print(f"  {rel}")
        layout = [r for r in drift if r.startswith(("05_figures/", "04_tables/"))]
        if layout and len(layout) == len(drift):
            print("A figure/table layout change: open a controlled layout round first, e.g.\n  "
                  + _loc(f'{wf().replace("wf.py", "rework.py")} layout '
                         + " ".join(f"--source {r}" for r in layout)
                         + ' --why "<what moves and why>"', proj))
        else:
            print("Route the change through tools/rework.py (batch --plan ...; --merge or "
                  "--priority if a round is open), or restore the certified version.")
        return 2
    print(f"paper  {proj}")
    print(f"cwd    {proj}")
    print(f"run    {' '.join(cmd)}")
    sys.stdout.flush()
    from . import determinism, numfmt
    # 1.9.0: the journal number style/spelling reaches R and Python builders (#16/#17), and
    # container outputs are made byte-stable afterwards (#4).
    os.environ["MEDPAPER_NUMFMT"] = numfmt.env_json(proj)
    # 1.11.0 (#2a): provisional/confirmed journal presentation parameters (widths, font floor,
    # panel label case, line-art dpi) reach the builders from the first render.
    from . import presentparams
    os.environ["MEDPAPER_PRESENTATION"] = presentparams.env_json(proj)
    watch = ("04_tables", "05_figures/out")

    def _derived() -> dict[Path, int]:
        out = {}
        for sub in watch:
            root = proj / sub
            if root.is_dir():
                for p in root.rglob("*"):
                    if p.is_file() and p.suffix.casefold() in (".xlsx", ".docx", ".pdf"):
                        out[p] = p.stat().st_mtime_ns
        return out
    before = _derived()
    try:
        outcome = runner.run_paper_script(proj, script, args.script_args)
    except runner.RunnerError as exc:
        print(str(exc))
        return 2
    for p, mtime in _derived().items():
        if before.get(p) != mtime:
            determinism.normalize(p)
    if outcome.engine_changes:
        print("CRITICAL: the paper script changed shared-engine path(s):")
        for path in outcome.engine_changes[:12]:
            print(f"  {path}")
        print("The command is failed even if the script exited 0. Inspect/revert those engine "
              "changes before continuing; paper code may write only under the paper root.")
        return 2
    return int(outcome.returncode)


def cmd_engine_fork(args) -> int:
    """1.13.0: a project-local engine copy for this paper only (never edit the global engine)."""
    from . import enginefork
    pipe = registry.load()
    try:
        proj = paths.project_dir(pipe.layout, check_engine=False)
    except paths.EngineWorkspace as exc:
        print(str(exc))
        return 2
    action = args.action or "status"
    running_fork = paths.is_fork_root(paths.repo_root())
    have = enginefork.info(proj)
    if action == "create":
        if have:
            print(f"this paper already has an engine fork: {enginefork.fork_root(proj)}")
            return 1
        try:
            rec = enginefork.create(proj, paths.repo_root())
        except ValueError as exc:
            print(f"refused: {exc}")
            return 2
        fork = enginefork.fork_root(proj)
        st = State(proj, pipe.layout.get("state_dir", ".wf"))
        if st.exists():
            st.load().event("engine_fork", f"created from {rec['base_engine']} "
                                           f"{rec['base_version']} ({rec['base_source']})")
            st.save()
        print(f"engine fork created: {fork}  (base {rec['base_version']}, {rec['base_source']})")
        print("the paper's .kiro adapters now call the fork; edit only files under it, then "
              "record the change for the maintainer:")
        print(f'  python "{fork.as_posix()}/tools/wf.py" engine-fork diff')
        return 0
    if not have:
        print("no engine fork in this paper (it uses the global engine read-only).")
        print(f"create one only when paper overrides cannot express the need:  {wf()} "
              "engine-fork create")
        return 0 if action == "status" else 1
    if action == "diff":
        out, changes = enginefork.write_diff(proj)
        for status, rel in changes[:30]:
            print(f"  {status} {rel}")
        print(f"{len(changes)} file(s) differ from base {have.get('base_version')}; diff: {out}")
        return 0
    if action == "remove":
        out = enginefork.remove(proj)
        print(f"fork removed; adapters point at {have.get('base_engine')} again; final diff kept: "
              f"{out}")
        return 0
    changes = enginefork.changed_files(proj)
    print(f"engine fork {enginefork.fork_root(proj)}  base {have.get('base_engine')} "
          f"{have.get('base_version')} ({have.get('base_source')}); {len(changes)} file(s) differ"
          + ("" if running_fork else "  [this command ran from the global engine]"))
    return 0


def cmd_data(args) -> int:
    """1.13.0: declare the user's datasets in place (read-only, never copied)."""
    from . import datasources
    pipe = registry.load()
    proj = paths.project_dir(pipe.layout)
    action = args.action
    if action == "add":
        if not args.path:
            print("wf data add <absolute path> [--name NAME]")
            return 1
        try:
            rec = datasources.add(proj, args.path, args.name, args.note or "")
        except ValueError as exc:
            print(f"refused: {exc}")
            return 2
        st = State(proj, pipe.layout.get("state_dir", ".wf")).load()
        st.event("data_source", f"{rec['name']}: {rec['path']} ({rec['files']} file(s), in place)")
        st.save()
        print(f"registered {rec['name']}: {rec['path']}  ({rec['kind']}, {rec['files']} file(s), "
              f"{rec['bytes'] / 1e6:,.1f} MB) - read in place, read-only, never copied")
        print("analysis code: from analysis.datasources import source_path; "
              f"source_path('{rec['name']}')")
        return 0
    if action == "remove":
        ok = datasources.remove(proj, args.path or args.name or "")
        print("removed" if ok else "no such data source")
        return 0 if ok else 1
    if action == "verify":
        bad = 0
        for s in datasources.load(proj):
            p = Path(s["path"])
            if not p.exists():
                print(f"  !! {s['name']}: {p} is missing")
                bad += 1
                continue
            n = len(datasources.inventory(proj)) if args.hash else None
            kind, size, files, _ = datasources._scan(p)
            same = size == s.get("bytes") and files == s.get("files")
            bad += 0 if same else 1
            print(f"  {'ok' if same else 'CHANGED'} {s['name']}: {files} file(s), "
                  f"{size / 1e6:,.1f} MB" + (f"; {n} file hash(es) cached" if n else ""))
        return 0 if bad == 0 else 2
    lines = datasources.describe(proj)
    print("\n".join(lines) if lines else "no data sources declared (wf data add <path>)")
    return 0


def cmd_override(args) -> int:
    """Create, inspect or validate this paper's workflow overlay."""
    master = registry.load()
    proj = paths.project_dir(master.layout)
    st = State(proj, master.layout.get("state_dir", ".wf"))
    if not st.exists():
        _no_state_help(master, proj)
        return 2
    st.load()
    target = overrides.overrides_path(st.dir)

    if args.action == "init":
        if target.exists() and not args.force:
            print(f"keeping existing {paths.rel(target)}")
            print("use `wf override show`, or pass --force only to replace it with the blank template")
            return 1
        governed = [sid for sid, info in (st.data.get("stages") or {}).items()
                    if info.get("paper_override_fingerprint")]
        if target.exists() and args.force and governed:
            print("refusing to replace overrides.toml: it already governed finished stage(s): "
                  + ", ".join(governed))
            print("The file is workflow history now. Loop back before changing an entry; do not "
                  "erase the record with --force.")
            return 2
        target.write_text(overrides.TEMPLATE, encoding="utf-8")
        print(f"created paper-local template: {paths.rel(target)}")
        print("the master pipeline was not touched: pipeline/pipeline.toml")
        print("uncomment only the change this paper needs, then run:  wf override validate")
        return 0

    if not target.is_file():
        print(f"no paper-local workflow override: {paths.rel(target)}")
        print("this paper uses the unmodified master workflow")
        print("create a documented template with:  wf override init")
        return 0

    if args.action == "show":
        print(f"# {paths.rel(target)}\n")
        print(target.read_text(encoding="utf-8").rstrip())
        print("\n# effective changes")

    try:
        data = overrides.load(st.dir)
    except SystemExit as exc:
        print(exc)
        return 2
    problems = overrides.validate(data, master.stages)
    problems.extend(overrides.validate_against_state(data, st))
    if problems:
        print(f"override is INVALID ({len(problems)} problem(s)):")
        for problem in problems:
            print(f"  [FAIL] {problem}")
        print("the override has not been applied; the master workflow is unchanged")
        return 2

    effective = registry.load(st.config(), data)
    if effective.override_notes:
        for note in effective.override_notes:
            print(f"  {note}")
    else:
        print("  (none - the file is a blank template)")
    print("override is valid; changes apply only to this paper")
    print(f"paper   {proj}")
    print(f"master  {paths.pipeline_file()} (unchanged)")
    return 0


USER_LIST_KEYS = ("report_dirs",)


def _user_config_set_list(key: str, values: list[str]) -> Path:
    """Rewrite one top-level list key of ~/.medpaper/config.toml, keeping every other line."""
    import tomllib
    cfg_path = paths.user_home() / "config.toml"
    text = cfg_path.read_text(encoding="utf-8") if cfg_path.is_file() else ""
    line = f"{key} = [" + ", ".join(json.dumps(v, ensure_ascii=False) for v in values) + "]"
    pat = re.compile(rf"(?m)^{re.escape(key)}\s*=\s*\[[^\]]*\]\s*$")
    if pat.search(text):
        new = pat.sub(lambda _: line, text, count=1)
    else:
        # top-level keys must precede the first [table]
        m = re.search(r"(?m)^\[", text)
        new = (text[:m.start()] + line + "\n" + text[m.start():]) if m else \
            (text.rstrip("\n") + ("\n" if text.strip() else "") + line + "\n")
    tomllib.loads(new)  # never write a config the engine cannot read back
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(new, encoding="utf-8")
    return cfg_path


def report_dir_refusal(d: Path) -> str | None:
    """1.14.1 (P2): why a folder cannot be a report folder (engine, papers, drive roots)."""
    if d.parent == d:
        return f"{d} is a drive root"
    try:
        if paths._norm(d) == paths._norm(Path.home()):
            return f"{d} is your home folder"
    except RuntimeError:
        pass
    if paths.in_engine(d):
        return f"{d} is inside, equal to or contains the medpaper engine"
    if paths._find_upwards(d) is not None:
        return f"{d} is a paper or lies inside one"
    try:
        root = paths.papers_root()[0]
        if paths.within(d, root) or paths.within(root, d):
            return f"{d} is inside or contains the central papers root"
    except SystemExit:
        pass
    if paths.nested_papers(d):
        return f"{d} holds papers"
    return None


def cmd_config_user(args) -> int:
    """`wf config --user list | get KEY | add KEY DIR | remove KEY DIR` (user level)."""
    cfg = paths.user_config()
    if args.action == "list":
        for k in sorted(cfg):
            print(f"{k:<28} {cfg[k]}")
        return 0
    if args.key not in USER_LIST_KEYS:
        print(f"unknown user-level key '{args.key}'; known: {', '.join(USER_LIST_KEYS)}")
        return 2
    current = [str(x) for x in cfg.get(args.key, []) if isinstance(x, str)]
    if args.action == "get":
        print("\n".join(current) if current else "<unset>")
        return 0
    if args.action not in ("add", "remove") or not args.value:
        print("use: wf config --user add|remove report_dirs <folder>")
        return 2
    d = Path(args.value).expanduser()
    d = (d if d.is_absolute() else Path.cwd() / d).resolve()
    if args.action == "add":
        why = report_dir_refusal(d)
        if why:
            print(f"refusing report folder: {why}")
            return 2
        if any(paths._norm(x) == paths._norm(d) for x in current):
            print(f"{d} is already a report folder")
            return 0
        current.append(str(d))
    else:
        current = [x for x in current if paths._norm(x) != paths._norm(d)]
    where = _user_config_set_list(args.key, current)
    print(f"{args.key} = {current}   (user config {where})")
    print("paper sessions may write .md/.txt files there (never other file types or papers)")
    return 0


def cmd_config(args) -> int:
    if getattr(args, "user", False):
        if args.action in USER_LIST_KEYS:  # `wf config --user report_dirs add DIR`
            args.action, args.key = (args.key or "get"), args.action
        if args.action not in ("list", "get", "add", "remove"):
            print("use: wf config --user list | get KEY | report_dirs add|remove <folder>")
            return 2
        return cmd_config_user(args)
    if args.action not in ("list", "get", "set"):
        print("use: wf config list | get KEY | set KEY VALUE  (user level: wf config --user "
              "report_dirs add <folder>)")
        return 2
    pipe, st, _ = _load()
    if args.action == "list":
        for k, v in sorted(pipe.targets.items()):
            print(f"{k:<28} {v}")
        return 0
    if args.action == "get":
        print(pipe.targets.get(args.key, "<unset>"))
        return 0
    st.set_config(args.key, args.value)
    print(f"{args.key} = {args.value}   (project override written to {paths.rel(st.config_file)})")
    return 0


def cmd_invariants(args) -> int:
    pipe = registry.load()
    try:
        proj = paths.project_dir(pipe.layout)
    except SystemExit:
        proj = None
    for i, line in enumerate(pipe.policy.get("invariants", []), 1):
        print(f"{i}. {_loc(line, proj)}")
    return 0


def cmd_checks(args) -> int:
    checks.load_all()
    pipe = registry.load()
    used: dict[str, list[str]] = {}
    for s in pipe.stages:
        for g in s.gate:
            used.setdefault(g["check"], []).append(s.id)
    for name in checks.known():
        where = used.get(name, [])
        print(f"{name:<28} {'used by ' + ', '.join(where) if where else '(unused)'}")
    return 0


# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="wf",
        description="medpaper workflow driver. Start with: wf status",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="initialise the working directory (the Kiro workspace the "
                                    "user opened) as a paper, in place; an existing paper here "
                                    "is resumed")
    p.add_argument("--force", action="store_true",
                   help="fresh restart of an existing paper here (needs --yes after the user "
                        "confirmed; the old run is archived in place under .wf_archive/)")
    p.add_argument("--yes", action="store_true", help="the user confirmed the fresh restart")
    p.set_defaults(fn=cmd_init)

    p = sub.add_parser("new", help="start a paper in place (default); --root DIR or --central "
                                   "only when the user asked for that location")
    p.add_argument("slug", nargs="?", help="short lowercase name, e.g. sarcopenia-mortality")
    p.add_argument("--root", help="create <root>/<slug> (only on the user's explicit request)")
    p.add_argument("--central", action="store_true",
                   help="create it under the central papers root (only on explicit request)")
    p.add_argument("--force", action="store_true")
    p.add_argument("--yes", action="store_true")
    p.set_defaults(fn=cmd_new)

    p = sub.add_parser("use", help="say where a paper is (there is no global selection)")
    p.add_argument("slug", nargs="?")
    p.set_defaults(fn=cmd_use)

    p = sub.add_parser("papers", help="list papers and the stage each one is at")
    p.set_defaults(fn=cmd_papers)

    p = sub.add_parser("archetype", help="print one figure archetype's rules (not the whole registry)")
    p.add_argument("name", nargs="?", help="e.g. km_survival; omit to list all names")
    p.set_defaults(fn=cmd_archetype)

    p = sub.add_parser("status", help="where am I, what is blocking, and the full stage card")
    p.add_argument("--brief", action="store_true", help="omit the stage card")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser("card", help="print a stage card")
    p.add_argument("stage", nargs="?")
    p.set_defaults(fn=cmd_card)

    log_help = ("also write the full output (UTF-8) to this file and end it with a "
                "'[wf] finished rc=N' marker; poll the file when running in the background")
    p = sub.add_parser("check", help="run the gate for a stage without advancing")
    p.add_argument("stage", nargs="?")
    p.add_argument("--json", action="store_true")
    p.add_argument("--log", type=Path, help=log_help)
    p.add_argument("--quiet", action="store_true", help="print failing checks and one summary line")
    p.add_argument("--summary", action="store_true", help="print one summary line only")
    p.add_argument("--all", action="store_true",
                   help="also print every passing check (default: failures, warnings and one "
                        "summary line; the full listing is in .wf/logs/check_<stage>.log)")
    p.add_argument("--reuse", action="store_true",
                   help="reuse fresh receipts of unchanged pure checks (incremental re-check)")
    p.add_argument("--wait", action="store_true",
                   help="block with a heartbeat line every 25 s, then print failures + one "
                        "summary line; full output in --log (default .wf/logs/wf_check.log)")
    p.set_defaults(fn=cmd_check)

    p = sub.add_parser("handoff", help="compact context pack for a new session or delegated "
                                       "step (pass this instead of a hand-written brief)")
    p.add_argument("--md", action="store_true", help="Markdown list output")
    p.set_defaults(fn=cmd_handoff)

    p = sub.add_parser("migrate", help="adopt this engine's full gate set for completed stages "
                                       "(the paper is pinned to the engine it ran under)")
    p.add_argument("--yes", action="store_true", help="apply; without it only the notes print")
    p.set_defaults(fn=cmd_migrate)

    p = sub.add_parser("advance", help="close the current stage and move to the next")
    p.add_argument("--note", help="handoff note (required unless already noted)")
    p.add_argument("--force", action="store_true", help="advance despite a red gate; recorded in state")
    p.add_argument("--log", type=Path, help=log_help)
    p.set_defaults(fn=cmd_advance)

    p = sub.add_parser("loop", help="deliberately return to an earlier stage")
    p.add_argument("--to", required=True)
    p.add_argument("--why", required=True)
    p.set_defaults(fn=cmd_loop)

    p = sub.add_parser("note", help="append to the handoff log")
    p.add_argument("text")
    p.set_defaults(fn=cmd_note)

    p = sub.add_parser("decide", help="record a gated decision with its rationale")
    p.add_argument("name")
    p.add_argument("value")
    p.add_argument("--why", required=True)
    p.set_defaults(fn=cmd_decide)

    p = sub.add_parser("tree", help="whole pipeline with status")
    p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(fn=cmd_tree)

    p = sub.add_parser("clean", help="report scratch/undeclared files; --apply deletes scratch")
    p.add_argument("--apply", action="store_true")
    p.set_defaults(fn=cmd_clean)

    p = sub.add_parser("doctor", help="environment and wiring check")
    p.set_defaults(fn=cmd_doctor)

    p = sub.add_parser("run-script",
                       help="run a paper-owned Python script with MEDPAPER_PROJECT exported")
    p.add_argument("script", help="paper-relative .py or .R path, e.g. 03_analysis/code/01_primary.py")
    p.add_argument("script_args", nargs=argparse.REMAINDER)
    p.set_defaults(fn=cmd_run_script)

    p = sub.add_parser("engine-fork", help="project-local engine copy for this paper only "
                                           "(create | status | diff | remove)")
    p.add_argument("action", nargs="?", choices=("create", "status", "diff", "remove"))
    p.set_defaults(fn=cmd_engine_fork)

    p = sub.add_parser("data", help="declare datasets in place, read-only, never copied "
                                    "(add PATH | list | verify | remove NAME)")
    p.add_argument("action", nargs="?", default="list", choices=("add", "list", "verify", "remove"))
    p.add_argument("path", nargs="?")
    p.add_argument("--name")
    p.add_argument("--note")
    p.add_argument("--hash", action="store_true", help="verify: also (re)hash changed files")
    p.set_defaults(fn=cmd_data)

    p = sub.add_parser("override", help="paper-local workflow shape; never edits the master")
    p.add_argument("action", choices=("init", "show", "validate"))
    p.add_argument("--force", action="store_true",
                   help="init only: replace an existing file with the blank commented template")
    p.set_defaults(fn=cmd_override)

    p = sub.add_parser("config", help="view or override per-paper numeric/string targets; "
                                      "--user for user-level keys (report_dirs)")
    p.add_argument("--user", action="store_true",
                   help="user-level config (~/.medpaper/config.toml): list | get KEY | "
                        "add report_dirs DIR | remove report_dirs DIR")
    p.add_argument("action", help="list | get | set (paper); --user: list | get | add | remove, "
                                  "also as `--user report_dirs add DIR`")
    p.add_argument("key", nargs="?")
    p.add_argument("value", nargs="?")
    p.set_defaults(fn=cmd_config)

    p = sub.add_parser("invariants", help="print the non-negotiable rules")
    p.set_defaults(fn=cmd_invariants)

    p = sub.add_parser("checks", help="list registered gate checks")
    p.set_defaults(fn=cmd_checks)

    return ap


class _Tee:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, text):
        for s in self.streams:
            s.write(text)
        return len(text)

    def flush(self):
        for s in self.streams:
            s.flush()


def _run_logged(args) -> int:
    """Long gates on Windows are often cut off in the foreground; log to a file that ends with
    a completion marker so a background run can be polled."""
    from datetime import datetime, timezone
    log = args.log.resolve()
    log.parent.mkdir(parents=True, exist_ok=True)
    print(f"[wf] log: {log}", file=sys.stderr)
    rc = 1
    with log.open("w", encoding="utf-8") as fh:
        out, err = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = _Tee(out, fh), _Tee(err, fh)
        try:
            args.log = None
            rc = args.fn(args)
        except paths.EngineWorkspace as exc:
            print(str(exc))
            rc = 2
        finally:
            sys.stdout, sys.stderr = out, err
            fh.write(f"\n[wf] finished rc={rc} at "
                     f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}\n")
    return rc


def main(argv: list[str] | None = None) -> int:
    from . import argtext
    ap = build_parser()
    # 1.12.0 (C1): --why-file/--why-b64 and mis-decoded Chinese text are fixed before parsing.
    argv = argtext.fix_argv(sys.argv[1:] if argv is None else argv)
    args = ap.parse_args(argv)
    if args.cmd == "config" and not args.user and args.action == "set" and (
            not args.key or args.value is None):
        ap.error("config set needs KEY and VALUE")
    if args.cmd == "config" and not args.user and args.action == "get" and not args.key:
        ap.error("config get needs KEY")
    from . import integrity, logs
    if getattr(args, "wait", False) and not os.environ.get("MEDPAPER_WAIT_CHILD"):
        # 1.11.0 (#2g): one blocking call instead of background + sleep polling.
        from . import longrun
        try:
            proj = paths.project_dir()
            log = logs.log_path(proj, f"wf_{args.cmd}", args.log)
        except integrity.EngineModified as exc:
            print(str(exc))
            return 3
        except (SystemExit, Exception):  # noqa: BLE001 - no paper: run in the foreground
            args.wait = False
            return args.fn(args)
        return longrun.run_quiet([sys.executable, sys.argv[0], *(argv if argv is not None
                                                                  else sys.argv[1:])],
                                 log, f"wf {args.cmd}")
    if getattr(args, "log", None):
        try:
            args.log = logs.log_path(paths.project_dir(), f"wf_{args.cmd}", args.log)
        except integrity.EngineModified as exc:
            print(str(exc))
            return 3
        except (SystemExit, Exception):  # noqa: BLE001
            pass
        rc = _run_logged(args)
        _progress(args, rc)
        return rc
    rc = None
    try:
        rc = args.fn(args)
        return rc
    except integrity.EngineModified as exc:
        print(str(exc))
        rc = 3
        return 3
    except paths.EngineWorkspace as exc:
        print(str(exc))
        rc = 2
        return 2
    except SystemExit as exc:
        rc = exc.code if isinstance(exc.code, int) else 1
        raise
    except KeyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        rc = 1
        return 1
    finally:
        _progress(args, rc)


def _progress(args, rc) -> None:
    """1.11.0 (#3g): keep <paper>/.wf/progress.md current after every paper command."""
    if args.cmd in ("doctor", "checks", "papers", "invariants", "archetype", "new", "init",
                    "handoff"):
        return
    try:
        from . import progress
        progress.write(paths.project_dir(), " ".join(["wf", args.cmd] + (
            [str(args.stage)] if getattr(args, "stage", None) else [])), rc)
    except (Exception, SystemExit):  # noqa: BLE001 - no paper selected
        pass

