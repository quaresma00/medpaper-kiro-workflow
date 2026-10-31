"""Polish-stage checks: de-AI, house style, and fact preservation.

The last one matters most. A language pass rewrites sentences wholesale, which is the
easiest place in the whole pipeline to silently lose a number or a citation. The gate
compares the polished text against a pre-polish snapshot and requires the multiset of
numbers, the set of citekeys and the set of figure/table references to be identical.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

from . import Ctx, Result, check

SNAPSHOT = "07_manuscript/prepolish"
REPORT = "07_manuscript/polish_report.json"
LEGACY_SECTIONS = ["introduction.md", "methods.md", "supplementary_methods.md", "results.md", "discussion.md", "abstract.md"]


def _wanted_sections(ctx: Ctx) -> set[str]:
    if ctx.p("07_manuscript/full_manuscript.md").exists():
        return {name for name in ("full_manuscript.md", "supplementary_methods.md",
                                  "title_page.md", "statements.md")
                if ctx.psrc(f"07_manuscript/{name}").exists()}
    return {name for name in LEGACY_SECTIONS if ctx.psrc(f"07_manuscript/{name}").exists()}


def _polish_tool(ctx: Ctx) -> Path:
    return ctx.pipeline.raw and Path(__file__).resolve().parents[2] / "text" / "polish.py"


@check("polish_snapshot_exists")
def polish_snapshot_exists(ctx: Ctx) -> Result:
    snapshot_rel = ctx.src(SNAPSHOT)
    facts = ctx.p(f"{snapshot_rel}/facts.json")
    if not facts.exists():
        return Result(
            False,
            "polish_snapshot_exists",
            f"no pre-polish snapshot at project/{snapshot_rel}/facts.json",
            ["Take it BEFORE editing: .venv/Scripts/python.exe tools/text/polish.py snapshot",
             "Without it there is no way to prove the polish pass did not alter the data."],
        )
    try:
        data = json.loads(facts.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return Result(False, "polish_snapshot_exists", f"facts.json unreadable: {exc}")
    files = data.get("files", {})
    missing = [rel for rel in files if not ctx.p(rel).exists()]
    if missing:
        return Result(False, "polish_snapshot_exists",
                      "snapshotted section(s) no longer present: " + ", ".join(missing))
    have = {Path(r).name for r in files}
    wanted = _wanted_sections(ctx)
    gap = sorted(wanted - have)
    if gap:
        return Result(
            False, "polish_snapshot_exists",
            "snapshot predates these sections: " + ", ".join(gap),
            ["Re-take it: .venv/Scripts/python.exe tools/text/polish.py snapshot --force"],
        )
    return Result(True, "polish_snapshot_exists",
                  f"{len(files)} section(s) snapshotted at {data.get('snapshot_at', '?')}")


@check("polish_preserves_facts")
def polish_preserves_facts(ctx: Ctx) -> Result:
    """Delegates to the tool so the CLI and the gate can never disagree."""
    tool = Path(__file__).resolve().parents[2] / "text" / "polish.py"
    if not tool.exists():
        return Result(False, "polish_preserves_facts", f"tool missing: {tool}")
    try:
        proc = subprocess.run(
            [sys.executable, str(tool), "diff"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180,
            env={**_env(ctx)},
        )
    except Exception as exc:  # noqa: BLE001
        return Result(False, "polish_preserves_facts", f"could not run polish.py diff: {exc}")
    out = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode == 0:
        return Result(True, "polish_preserves_facts",
                      "every number, citekey and figure/table reference survived the polish")
    fails = [ln.strip() for ln in out.splitlines()
             if ": number(s)" in ln or ": citekey(s)" in ln or ": artifact ref(s)" in ln
             or "disappeared after" in ln]
    if not fails:
        fails = [ln.strip() for ln in out.splitlines() if "no snapshot" in ln or "run `" in ln]
    return Result(
        False,
        "polish_preserves_facts",
        "; ".join(fails[:6]) or out.strip()[:300],
        [f"Restore the affected text from project/{ctx.src(SNAPSHOT)}/ and redo those sentences.",
         "Polishing changes wording only. Never a value, never a citation."],
    )


@check("polish_complete")
def polish_complete(ctx: Ctx) -> Result:
    """1.12.0 (B3): one polish gate. Sub-reasons: snapshot taken before editing, lint report
    present, every number/citekey/display reference preserved. Replaces three gate lines
    (polish_snapshot_exists, polish_report, polish_preserves_facts) that always failed
    together while polishing was in progress."""
    parts: list[str] = []
    hints: list[str] = []
    snap = polish_snapshot_exists(ctx)
    if not snap.ok:
        parts.append(f"snapshot: {snap.detail}")
        hints += snap.hints[:1]
    rep = _report(ctx)
    if isinstance(rep, Result):
        parts.append(f"report: {rep.detail}")
        hints += rep.hints[:1]
    if snap.ok:  # without a snapshot there is nothing to compare against
        facts = polish_preserves_facts(ctx)
        if not facts.ok:
            parts.append(f"facts: {facts.detail}")
            hints += facts.hints
    if parts:
        return Result(False, "polish_complete", "; ".join(parts), hints)
    return Result(True, "polish_complete",
                  f"snapshot ({snap.detail}), lint report present, every number, citekey and "
                  "display reference survived the polish")


def _report_pending(ctx: Ctx):
    """The lint report, or a pending pass when it is missing: polish_complete reports that
    once (1.12.0 B3) instead of every report-reading gate failing on the same file."""
    rep = _report(ctx)
    if isinstance(rep, Result) and "missing" in rep.detail:
        return None
    return rep


@check("ai_tells_clean")
def ai_tells_clean(ctx: Ctx) -> Result:
    rep = _report_pending(ctx)
    if rep is None:
        return Result(True, "ai_tells_clean", "pending: the lint report is missing (see polish_complete)")
    if isinstance(rep, Result):
        return rep
    tier_a = [x for x in rep.get("ai_tells", []) if x.get("tier") == "A"]
    struct = [x for x in rep.get("structure", []) if x.get("severity") == "blocking"]
    if tier_a or struct:
        bits = []
        if tier_a:
            labels = Counter(x["label"] for x in tier_a)
            bits.append(f"{len(tier_a)} tier-A phrase(s): "
                        + ", ".join(f"{k} x{v}" for k, v in labels.most_common(6)))
        if struct:
            bits.append(f"{len(struct)} structural tell(s): "
                        + "; ".join(f"{x['kind']} in {Path(x['file']).name}" for x in struct[:4]))
        return Result(
            False,
            "ai_tells_clean",
            "; ".join(bits),
            ["Full detail: .venv/Scripts/python.exe tools/text/polish.py lint",
             "Rewrite the clause. Do not delete the sentence to make the check pass.",
             f"A genuine exception goes in project/07_manuscript/polish_allowlist.tsv."],
        )
    tier_b = [x for x in rep.get("ai_tells", []) if x.get("tier") == "B"]
    if tier_b:
        return Result(True, "ai_tells_clean",
                      f"no tier-A tells; {len(tier_b)} tier-B phrase(s) left for your judgement")
    return Result(True, "ai_tells_clean", "no machine-generated phrasing detected")


@check("style_consistent")
def style_consistent(ctx: Ctx) -> Result:
    rep = _report_pending(ctx)
    if rep is None:
        return Result(True, "style_consistent", "pending: the lint report is missing (see polish_complete)")
    if isinstance(rep, Result):
        return rep
    blocking = [x for x in rep.get("style", []) if x.get("severity") == "blocking"]
    if blocking:
        kinds = Counter(x["kind"] for x in blocking)
        return Result(
            False,
            "style_consistent",
            f"{len(blocking)} house-style defect(s): "
            + "; ".join(f"{k} x{v}" for k, v in kinds.most_common(8)),
            ["Full detail: .venv/Scripts/python.exe tools/text/polish.py lint",
             "These are settled by convention, not taste: fix them all."],
        )
    advisory = [x for x in rep.get("style", []) if x.get("severity") != "blocking"]
    return Result(True, "style_consistent",
                  f"house style consistent"
                  + (f"; {len(advisory)} advisory note(s)" if advisory else ""))


def _final_manuscript_docx(ctx: Ctx) -> Path | None:
    """The built manuscript DOCX listed in the bundle manifest, if S23 has built it."""
    try:
        manifest = ctx.read_json("08_submission/bundle/manifest.json")
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    for item in manifest.get("items", []):
        if str(item.get("role", "")).casefold() == "manuscript":
            path = ctx.p(str(item.get("file", "")))
            if path.suffix.casefold() == ".docx" and path.is_file():
                return path
    return None


def _display_counts(ctx: Ctx) -> tuple[int, int]:
    try:
        plan = ctx.read_json("01_protocol/artifact_plan.json")
    except (FileNotFoundError, json.JSONDecodeError):
        return 0, 0
    return len(plan.get("main_figures", [])), len(plan.get("main_tables", []))


@check("journal_limits_met")
def journal_limits_met(ctx: Ctx) -> Result:
    """Typed caps from target_journal.json against Word-compatible counts.

    Counts include numbers (Word does), cover the body from Introduction to Conclusions, and
    keep a safety margin (journal_limit_margin, default 0.97) because a portal's counter rarely
    matches ours exactly. Once S23 has built the manuscript DOCX, the final Word file is what
    gets measured. Display-item and reference caps are exact.
    """
    from .. import journalspec
    target = journalspec.load(ctx.project)
    if not target:
        return Result(False, "journal_limits_met", "08_submission/target_journal.json missing")
    caps, schema = journalspec.limits(target)
    if schema:
        return Result(False, "journal_limits_met", "; ".join(schema),
                      ['Add to target_journal.json: "limits": {"main_text_words": <int|null>, '
                       '"abstract_words": <int|null>, "reference_limit": <int|null>, '
                       '"display_items": <int|null>, "main_figures": <int|null>, '
                       '"main_tables": <int|null>, "source": "<guide URL + quoted rule>"}',
                       "Typed fields only; guideline prose is never parsed for numbers."])
    scope = journalspec.word_count_scope(target)
    docx = _final_manuscript_docx(ctx)
    if docx is not None:
        counts = journalspec.docx_counts(docx, scope, target)
        refs, basis = counts["references"], f"final DOCX {docx.name}"
    else:
        rel = ctx.src("07_manuscript/full_manuscript.md")
        if ctx.p(rel).is_file():
            text = ctx.read(rel)
        else:  # component drafts before S17 assembles the canonical file
            rel = "07_manuscript/<sections>"
            text = "\n\n".join(
                f"# {name.title()}\n\n" + ctx.read(ctx.src(f"07_manuscript/{name}.md"))
                for name in ("abstract", "introduction", "methods", "results", "discussion")
                if ctx.psrc(f"07_manuscript/{name}.md").is_file())
        counts = journalspec.markdown_counts(text, scope)
        refs, basis = _ref_count(ctx), f"{rel} (Word-compatible count)"
    # 1.9.0 (#11): at or below the cap passes (margin 1.0 by default, configurable); the old
    # 97% safety band is a warning only (journal_limit_warn_share), never a block.
    margin = float(ctx.target("journal_limit_margin", 1.0))
    warn_share = float(ctx.target("journal_limit_warn_share", 0.97))
    problems, notes, near = [], [], []
    for key, label, got in (("main_text_words", "main text", counts["main"]),
                            ("abstract_words", "abstract", counts["abstract"])):
        cap = caps[key]
        if cap is None:
            continue
        allowed = int(cap * margin)
        (problems if got > allowed else notes).append(
            f"{label} {got}/{cap} words" + (f" (margin {allowed})" if allowed != cap else ""))
        if got <= allowed and got > cap * warn_share:
            near.append(f"{label} {got}/{cap}")
    nfig, ntab = _display_counts(ctx)
    for key, label, got in (("reference_limit", "references", refs),
                            ("display_items", "main display items", nfig + ntab),
                            ("main_figures", "main figures", nfig),
                            ("main_tables", "main tables", ntab)):
        cap = caps[key]
        if cap is not None:
            (problems if got > cap else notes).append(f"{label} {got}/{cap}")
    notes.append(f"measured on {basis}")
    if problems:
        return Result(
            False,
            "journal_limits_met",
            "over the journal's limit: " + "; ".join(problems),
            ["Cut content, do not compress into denser jargon.",
             "If cutting would remove something a reviewer needs, move it to the supplement."],
        )
    if near:
        return Result(False, "journal_limits_met",
                      "within journal limits, close to the cap (portal counters may differ): "
                      + "; ".join(near) + " | " + "; ".join(notes),
                      ["Optional: check the count in the submission portal."], severity="warn")
    return Result(True, "journal_limits_met", "within journal limits: " + "; ".join(notes))


@check("draft_length_targets")
def draft_length_targets(ctx: Ctx) -> Result:
    """Before a journal is chosen, the assembled draft keeps to common medical caps
    (draft_main_words_max / draft_abstract_words_max) so S22 trims, not rewrites."""
    from .. import journalspec
    rel = ctx.src("07_manuscript/full_manuscript.md")
    if not ctx.p(rel).is_file():
        return Result(False, "draft_length_targets", f"{rel} missing")
    counts = journalspec.markdown_counts(ctx.read(rel), list(journalspec.DEFAULT_SCOPE))
    main_cap = int(ctx.target("draft_main_words_max", 4000))
    abs_cap = int(ctx.target("draft_abstract_words_max", 250))
    over = [f"{label} {got}/{cap} words" for label, got, cap in
            (("body", counts["main"], main_cap), ("abstract", counts["abstract"], abs_cap))
            if got > cap]
    if over:
        return Result(False, "draft_length_targets", "draft over the default target: " + "; ".join(over),
                      ["Cut now rather than at S22; counts are Word-compatible (numbers included).",
                       "A study that genuinely needs more space: `wf config set draft_main_words_max <n>`."])
    return Result(True, "draft_length_targets",
                  f"body {counts['main']}/{main_cap}, abstract {counts['abstract']}/{abs_cap} words")


# ---------------------------------------------------------------------------
def _report(ctx: Ctx):
    rel = ctx.src(REPORT)
    p = ctx.p(rel)
    if not p.exists():
        return Result(
            False, "polish_report", f"project/{rel} missing",
            ["Run: .venv/Scripts/python.exe tools/text/polish.py lint"],
        )
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return Result(False, "polish_report", f"{rel} invalid JSON: {exc}")


def _env(ctx: Ctx) -> dict:
    import os
    return {**os.environ,
            "MEDPAPER_PROJECT": str(ctx.project),
            "MEDPAPER_ROOT": str(Path(__file__).resolve().parents[3]),
            "PYTHONIOENCODING": "utf-8"}


def _ref_count(ctx: Ctx) -> int:
    keys: set[str] = set()
    names = (("full_manuscript.md",) if ctx.p("07_manuscript/full_manuscript.md").exists()
             else ("introduction.md", "methods.md", "results.md", "discussion.md"))
    for name in names:
        p = ctx.psrc(f"07_manuscript/{name}")
        if p.exists():
            text = p.read_text(encoding="utf-8", errors="replace")
            for grp in re.findall(r"\[([^\]]*@[^\]]*)\]", text):
                keys.update(re.findall(r"@([A-Za-z][\w:.#$%&+?<>~/-]*)", grp))
    return len(keys)


def _canonical_section_counts(text: str) -> dict[str, int]:
    """Count journal-limited sections without counting title, keywords, refs or legends."""
    matches = list(re.finditer(r"(?m)^#\s+([^#\n].*)$", text))
    out: dict[str, int] = {}
    wanted = {"abstract", "introduction", "methods", "results", "discussion"}
    for i, match in enumerate(matches):
        name = match.group(1).strip().casefold()
        if name not in wanted:
            continue
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block = text[match.end():end]
        block = re.sub(r"(?m)^Keywords\s*:.*$", "", block, flags=re.I)
        from .. import journalspec
        out[name] = journalspec.word_count(block)
    return out
