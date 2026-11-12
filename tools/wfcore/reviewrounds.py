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
import re
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
    # 1.23.0 (S3): independent science review after S11 and before the Results are written.
    "science": {"prefix": "X", "decision": "science_review_proceed", "value": "PROCEED",
                "summary": ".wf/science_review.md",
                "headings": ("Materials presented", "Independent verdict",
                             "Changes before writing", "Revalidation", "Decision to proceed")},
}
# 1.23.0 (S3): what a science round covers - analyses, displays and the Methods draft.
SCIENCE_INPUTS = ("01_protocol/protocol_final.md", "01_protocol/artifact_plan.json",
                  "01_protocol/display_benchmark.json", "07_manuscript/methods.md",
                  "07_manuscript/supplementary_methods.md", "03_analysis/analysis_manifest.json",
                  "03_analysis/results/*.json", "04_tables/main/*.xlsx",
                  "04_tables/supplementary/*.xlsx", "05_figures/out/*.png",
                  "05_figures/legends.md", "04_tables/table_captions.md",
                  ".wf/publishability.json")
SCIENCE_BRIEF = """Science review brief (round {rid}, {mode}) - BEFORE the Results, Introduction, Discussion
and Abstract are written. Read every file listed in {bundle}/MANIFEST.md. Judge, as a methods
reviewer and handling editor of an SCIE journal of the target tier:
  1. suitability for an original article in that tier (or the article type you recommend:
     original article, brief report, research letter);
  2. design validity for the question; bias and confounding handling; robustness (are the
     sensitivity and validity analyses the ones a reviewer will ask for?);
  3. key analyses that comparable papers have and this paper lacks (display_benchmark.json
     lists comparable papers and their displays);
  4. display adequacy against the benchmark: number and type of main tables and figures, each
     readable on its own by a clinician (contact sheet, display_text.md);
  5. the Methods draft: can a clinician reproduce the logic; is anything missing or unclear;
  6. overclaiming risk given the precision of the main results (key_results.md).
MUST-FIX = a problem likely to cause rejection or a wrong conclusion; everything else OPTIONAL.
Number EVERY finding as F1, F2, ... with a category: numbers | grouping | conclusion_strength |
other, tag it MUST-FIX or OPTIONAL, and say what would fix it and at what rough cost.
End with: Verdict (ready to write | revise first) and Recommended article type.
Write the complete report to {bundle}/report.md - the only file you may write."""
# 1.23.0 (S3/S8): the explicit 'proceed to writing' answer of a science round.
_PROCEED = re.compile(r"(?i)继续写|开始写|进入写作|可以写|继续吧|继续推进|按你的建议|按您的建议|"
                      r"\bproceed\b|\bgo ahead\b|\bstart writing\b")
_NOT_PROCEED = re.compile(r"(?i)不继续|先别|不要写|暂停|再审|再来一轮|另一轮|\bnot\b|\bdon'?t\b|"
                          r"another round")


def is_proceed(words: str) -> bool:
    """1.23.0 (S3): the user's explicit decision to proceed to writing after a science round
    ('继续写作', '按你的建议', 'proceed'); the version confirmation sentence counts too; 'OK' and
    '可以' alone do not."""
    text = str(words or "").strip()
    if is_confirmation(text):
        return True
    return bool(_PROCEED.search(text)) and not _NOT_PROCEED.search(text)
SEVERITIES = ("critical", "major", "minor")
ANOTHER, DONE = "another_round", "no_further_review"
# 1.10.0 (#12): findings in these categories may not be closed as "kept" on the agent's own
# preference; they are changed, or handed to the author ("author") and decided by them.
CATEGORIES = ("numbers", "grouping", "conclusion_strength", "other")
PROTECTED = frozenset({"numbers", "grouping", "conclusion_strength"})
STATUSES = ("changed", "kept", "author")
# 1.10.0 (#13): approval is this exact sentence, never a recognised phrase ("OK", "可以", ...).
CONFIRM_PHRASES = ("我确认这一版", "I confirm this version")
PROTOCOL = "1.11.0"
REPORTS_DIR = ".wf/review_reports"
FINDING_ID_RE = re.compile(
    r"(?m)^[ \t>]*(?:[-*+]|\d+[.)])?[ \t]*(?:\*\*|__)?\[?(F\d{1,3})\]?(?:\*\*|__)?(?=[\s:.)\]-])")
# The orchestrator's brief to the reviewer: neutral, identical every round. It never carries
# "known deviations", "previous conclusions" or what the agent hopes to hear.
BRIEF = """Review brief (round {rid}, {scope}, {mode}). Read every file listed in {bundle}/MANIFEST.md.
Judge, from the first round on, as:
  1. a first-time clinical reader who never saw this project: what is unclear, which labels,
     abbreviations or terms you had to look up, can each table and figure be read on its own;
  2. an editor checking engineering language and self-contained displays: code names, letter
     codes, processing counts (lines/rows/files), data-handling jargon in the body, tables,
     legends and in-figure text; every abbreviation defined in each footnote/legend; each
     table and figure understandable on its own by a clinician, with no analysis-report text
     (programme names, software-output columns, scientific notation, placeholder axis titles;
     display_text.md and the display sheet when listed);
  3. a methods and journal reviewer (publication readiness, numbers, claims). When
     decision_record.md is listed (what was pre-specified, what was decided after the data
     were seen), check that no post hoc analysis is presented as confirmatory.
Number EVERY finding in EVERY section (incl. Reader comprehension and Medical presentation)
at the start of its line as F1, F2, ... with a category: numbers | grouping |
conclusion_strength | other, and say whether it is presentation or scientific.
Write the complete report to {bundle}/report.md - the only file you may write."""


def brief(project, rnd: dict, bundle) -> str:
    """The neutral brief plus the study-specific rules (1.13.0: no multi-person checks for
    automated extraction, no protocol-deviation requests outside a registered meta-analysis)."""
    from .declarations import review_rules
    if rnd.get("scope") == "science":
        text = SCIENCE_BRIEF.format(rid=rnd["id"], mode=rnd["mode"], bundle=bundle)
    else:
        text = BRIEF.format(rid=rnd["id"], scope=rnd["scope"], mode=rnd["mode"], bundle=bundle)
    try:
        rules = review_rules(project)
    except Exception:  # noqa: BLE001 - the brief must always print
        rules = []
    if rnd.get("scope") == "package":  # 1.15.0 (E4/E11): engine-owned items, checklist order
        from .audit import engine_text
        rules = [*rules, engine_text()]
    # 1.22.0 (R1/R2/R3/C6): fixed must-fix rule, delta/regression scope, engine counts, results.
    from . import convergence as cv
    conv = [cv.MUSTFIX]
    if rnd.get("mode") == "regression":
        conv.append(cv.REGRESSION_RULE)
    elif rnd.get("mode") == "delta":
        conv.append(cv.DELTA_RULE)
    try:
        conv.append(cv.counts_line(project))
    except Exception:  # noqa: BLE001 - the brief must always print
        pass
    conv.append(cv.KEY_RESULTS_RULE)
    if rnd.get("scope") in ("manuscript", "science"):  # 1.23.0 (S7/S8)
        conv.append(UNITS_IMPUTATION_RULE)
    if rnd.get("scope") == "manuscript":  # 1.23.0 (S3): science closed before writing
        try:
            conv += science_closed_rule(project)
        except Exception:  # noqa: BLE001 - the brief must always print
            pass
    rules = [*rules, *conv]
    return text + ("\n" + "\n".join(rules) if rules else "")


def science_closed_rule(project) -> list[str]:
    """1.23.0 (S3): the S18/S19 brief focuses on writing when the science was reviewed before
    writing; closed science items reopen only when results or displays changed since."""
    rounds = load(project).get("science") or []
    last = next((r for r in reversed(rounds) if r.get("user_decision") == DONE), None)
    if not last:
        return []
    now = inputs(project, "science")
    moved = sorted(r for r, h in now.items() if (last.get("after") or {}).get(r) != h
                   and (r.startswith("03_analysis/results/") or r.startswith("04_tables/")
                        or r.startswith("05_figures/out/")))
    items = [f"{f.get('id')} {str(f.get('summary', ''))[:70]}" for f in last.get("finding_list", [])][:12]
    head = (f"Science review before writing: round {last['id']} closed and the user decided to "
            "proceed. Focus this review on writing quality, consistency and readability; do not "
            "reopen the closed science items")
    if moved:
        return [head + " except where these changed since: " + ", ".join(moved[:8]) + "."]
    return [head + " (results and displays unchanged since)" + (": " + "; ".join(items) if items
                                                                  else "") + "."]


UNITS_IMPUTATION_RULE = ("Derived variables and imputation (1.23.0): check that derived doses, "
                         "doses per body weight or surface area and standardised equivalents carry "
                         "units and plausible values (derived_variables in key_results.md), and that "
                         "analyses of multiply imputed data are pooled across imputations (m, "
                         "pooling method, df) - a single imputed dataset needs a stated reason in "
                         "the Methods.")
_VERSION_WORDS = ("这一版", "此版", "本版", "这个版本", "这版")
_NOT_CONFIRM = re.compile(r"(?i)不确认|未确认|没有确认|别确认|不要确认|无需审阅|\bnot\b|\bdon'?t\b")


def is_confirmation(words: str, phrase: str = "") -> bool:
    """1.22.0 (U3): an explicit confirmation sentence - the exact phrase, or any sentence that
    contains 确认 plus 这一版/此版/本版/这个版本 (or 'I confirm this version'); 'OK', '可以',
    '好的', '没问题', '无需审阅' and negations are never a confirmation."""
    text = str(words or "").strip().strip("\"'“”‘’「」『』").strip()
    text = text.rstrip("。.!！ ").strip()
    if text == CONFIRM_PHRASES[0] or text.casefold() == CONFIRM_PHRASES[1].casefold():
        return True
    if _NOT_CONFIRM.search(text):
        return False
    if "确认" in text and any(w in text for w in _VERSION_WORDS):
        return True
    return CONFIRM_PHRASES[1].casefold() in text.casefold()


def version_id(hashes: dict[str, str]) -> str:
    """One id for the exact set of files a confirmation covers."""
    import hashlib
    blob = json.dumps(sorted(hashes.items()), separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def pending_author(rnd: dict | None) -> list[dict]:
    """Protected findings handed to the author that the author has not decided yet."""
    if not rnd:
        return []
    return [f for f in rnd.get("finding_list", [])
            if f.get("status") == "author" and not f.get("author_decision")]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")  # same as state.json


def inputs(project: Path, scope: str) -> dict[str, str]:
    """Paper-relative path -> SHA-256 of everything a round of this scope covers."""
    if scope == "manuscript":
        from .readerreview import reader_inputs
        return reader_inputs(project)
    if scope == "science":  # 1.23.0 (S3): results, displays and Methods, by content
        from .determinism import content_sha256
        out = {}
        for pat in SCIENCE_INPUTS:
            for p in sorted(Path(project).glob(pat)):
                if p.is_file() and not p.name.startswith("~$"):
                    out[p.relative_to(project).as_posix()] = content_sha256(p)
        return out
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


def start(project: Path, scope: str, stage: str, delta: bool = False, llm: bool = False) -> dict:
    data = load(project)
    rounds = data[scope]
    from . import convergence as cv
    capped = cv.capped(project, scope)
    if rounds and not rounds[-1].get("closed_at"):
        raise ValueError(f"round {rounds[-1]['id']} is still open; close it first")
    linked = None
    if rounds and rounds[-1].get("user_decision") is None:
        # 1.12.0 (C6): a delta/evidence round may start while the previous one awaits the
        # user; it is linked to that round, so no review ever happens outside review_round.
        if not delta:
            raise ValueError(f"round {rounds[-1]['id']} awaits the user's answer (decide); "
                             "a delta/evidence round may start now with --delta")
        linked = rounds[-1]["id"]
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
    # 1.22.0 (U4/J5): fast mode / a repackage epoch - the package review is compliance-only
    # (no reviewer subagent) unless the user asks for one (--llm).
    if scope == "package" and cv.review_mode(project) == "fast" and not llm:
        mode = "compliance"
    # 1.22.0 (R2): after the cap only regressions are checked.
    elif capped and prev:
        mode = "regression"
    rid = f"{SCOPES[scope]['prefix']}{len(rounds) + 1:03d}"
    rnd = {"id": rid, "scope": scope, "stage": stage, "mode": mode, "started_at": _now(),
           "inputs": current, "reviewed": sorted(reviewed), "closed_at": None,
           "findings": {}, "changes": [], "not_changed": [], "after": {},
           "user_decision": None,
           # 1.11.0 (#1f): the round closes against the reviewer's saved, numbered report.
           "protocol": PROTOCOL}
    if linked:
        rnd["linked_to"] = linked
        rounds[-1]["superseded_by"] = rid
    rounds.append(rnd)
    _save(project, data)
    return rnd


def report_ids(text: str) -> list[str]:
    """Every finding id the reviewer numbered, in every section (F1, F2, ...)."""
    seen = []
    for m in FINDING_ID_RE.finditer(text):
        if m.group(1) not in seen:
            seen.append(m.group(1))
    return seen


def preference_ids(text: str) -> list[str]:
    """Finding ids whose own line is tagged PREFERENCE (1.15.0, E4) or OPTIONAL (1.22.0, R2:
    optional findings of every scope close as one group with one reason)."""
    out = []
    for line in (text or "").splitlines():
        m = FINDING_ID_RE.match(line)
        if m and re.search(r"(?i)\b(PREFERENCE|OPTIONAL)\b", line) and not re.search(
                r"(?i)\b(BLOCKING|MINOR|MUST[- ]FIX)\b", line) and m.group(1) not in out:
            out.append(m.group(1))
    return out


ACCEPT_ALL = re.compile(r"按你的建议|按您的建议|都按建议|全部按建议|(?i:as you recommend)")


def author_accept_all(project: Path, scope: str, words: str) -> list[dict]:
    """1.22.0 (U2): '按你的建议' accepts the agent's recommendation for every pending item."""
    if not ACCEPT_ALL.search(str(words or "")):
        raise ValueError("author all needs the user's words accepting all recommendations, e.g. "
                         "'按你的建议'")
    data = load(project)
    rnd = data[scope][-1] if data[scope] else None
    if not rnd or not rnd.get("closed_at"):
        raise ValueError("no closed round to decide on")
    done = []
    for f in pending_author(rnd):
        f["author_decision"] = {"choice": f.get("recommendation") or "keep", "words": words.strip(),
                                "at": _now(), "accepted_recommendation": True}
        done.append(f)
    _save(project, data)
    _write_summary(project, scope, data[scope])
    return done


def _closure(rnd: dict) -> list[str]:
    """Numbered report findings without a closing entry (1.11.0 rounds only)."""
    if not rnd.get("protocol") or not rnd.get("closed_at"):
        return []
    if not rnd.get("report"):
        return [f"{rnd['id']}: no saved reviewer report (close --report <file>)"]
    listed = {f.get("id"): f for f in rnd.get("finding_list", [])}
    reasons = {str(n.get("item", "")).strip(): str(n.get("reason", "")).strip()
               for n in rnd.get("not_changed", [])}
    out = []
    missing = [i for i in rnd.get("report_ids", []) if i not in listed]
    if missing:
        out.append(f"{rnd['id']}: finding(s) never closed: " + ", ".join(missing[:10]))
    for fid, f in listed.items():
        if f.get("status") == "kept" and len(reasons.get(fid, "")) < 10:
            out.append(f"{rnd['id']} {fid}: kept without a reason (--kept {fid} \"why\")")
    return out


def closure_problems(project: Path, scope: str) -> list[str]:
    return [p for r in load(project)[scope] for p in _closure(r)]


BUNDLE_DIR = ".wf/review_bundle"


def write_bundle(project: Path, rnd: dict) -> Path:
    """1.11.0 (#3f): one self-contained folder a reviewer subagent reads on its own: copies of
    every reviewed text/figure file, hash-bound text copies of DOCX/XLSX, rendered DOCX pages
    (when a converter is available) and MANIFEST.md with the neutral brief."""
    import hashlib
    import os
    import shutil
    from .readerreview import write_text_copies
    project = Path(project)
    out = project / BUNDLE_DIR / rnd["id"]
    if out.exists():
        shutil.rmtree(out)
    (out / "files").mkdir(parents=True)
    lines = [f"# Review bundle {rnd['id']} ({rnd['scope']}, {rnd['mode']})", "",
             brief(project, rnd, out), "",
             "## Files (copy -> source, sha256)", ""]
    docx = []
    sheet = any((project / r).is_file() for r in ("05_figures/qc/displays_sheet.png",
                                                    "05_figures/qc/contact_sheet.png"))
    for rel in rnd["reviewed"]:
        src = project / rel
        if not src.is_file():
            continue
        if rnd.get("scope") == "science" and sheet and src.suffix.lower() in (".png", ".tif",
                                                                             ".tiff"):
            continue  # 1.23.0 (S3): the one contact sheet shows every figure (token economy)
        digest = hashlib.sha256(src.read_bytes()).hexdigest()
        if src.suffix.lower() in (".docx", ".xlsx"):
            docx += [rel] if src.suffix.lower() == ".docx" else []
            continue
        dst = out / "files" / rel.replace("/", "__")
        shutil.copyfile(src, dst)
        lines.append(f"- {dst} <- {rel} ({digest[:16]})")
    from .convergence import render_currency as _currency
    early_stale = {r for r in rnd["reviewed"] if r.endswith(".docx") and not _currency(project, r)[0]}
    for rel in write_text_copies(project, round_id=rnd["id"], rels=[r for r in rnd["reviewed"]
                                           if r.endswith((".docx", ".xlsx"))
                                           and r not in early_stale]):
        dst = out / "files" / Path(rel).name
        shutil.copyfile(project / rel, dst)
        lines.append(f"- {dst} (hash-bound text copy)")
    # 1.14.0 (D1): factual pre-specified vs post hoc record (reviewer only, never exported).
    from .decisionrecord import write as _write_record
    record = _write_record(project, out)
    if record:
        lines.append(f"- {record} (material scientific decisions: pre-specified vs decided "
                     "after the data were seen; reviewer only)")
    if rnd.get("scope") in ("manuscript", "science"):  # 1.20.0 (V6) / 1.23.0 (S3)
        lines += _display_text_files(project, out)
    if rnd.get("scope") == "science":
        lines += science_materials(project, out)
    from .reviewitems import write as _write_items  # 1.16.0: cases a gate could not decide
    listed = _write_items(project, out)
    if listed:
        lines.append(f"- {listed} (cases the deterministic checks could not decide; judge "
                     "each one in the report)")
    # 1.22.0 (R1/R3): the previous round's report, the closed/kept findings and the results.
    from . import convergence as cv
    lines += cv.previous_materials(project, rnd["scope"], rnd, out)
    kr = out / "files" / "key_results.md"
    kr.write_text(cv.key_results(project), encoding="utf-8")
    lines.append(f"- {kr} (key results from the results JSON: check every number against it)")
    stage = str(rnd.get("stage", ""))
    docx += [p.relative_to(project).as_posix() for p in project.glob("08_submission/bundle/*.docx")
             if p.relative_to(project).as_posix() not in docx]
    # 1.22.0 (C5): a stale build (inputs changed, hand edit) is never rendered for a reviewer.
    currency: dict[str, tuple[bool, str, dict]] = {rel: cv.render_currency(project, rel) for rel in docx}
    stale = [rel for rel in docx if not currency[rel][0]]
    if stale:
        lines += ["", "## Omitted stale Word builds (not a basis for judgement; rebuilt by wf rebuild)", ""]
        lines += [f"- {rel}: STALE - {currency[rel][1]}" for rel in stale]
    paths = [project / rel for rel in docx if rel not in stale]
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "manuscript"))
    if stage >= "S17" and not any("manuscript" in p.name for p in paths):
        # 1.12.0 (F3): from S17 the reviewer reads the paper as Word renders it.
        try:
            import build_docx  # tools/manuscript/build_docx.py
            from .packagecontent import visible_text
            draft = build_docx.draft_docx(project, out / "draft" / "manuscript_draft.docx")
            paths.append(draft)
            text_copy = out / "files" / "manuscript_draft.docx.txt"
            text_copy.write_text(visible_text(draft), encoding="utf-8")
            lines += [f"- {draft} (Word build of the current draft)",
                      f"- {text_copy} (its text copy)"]
        except Exception as exc:  # noqa: BLE001 - the Markdown copy above remains
            lines += ["", f"(DOCX draft build unavailable: {type(exc).__name__}: {exc}; read "
                      "the Markdown copy of full_manuscript.md)"]
    pages = []
    if stage >= "S17" and paths and os.environ.get("MEDPAPER_NO_PREVIEW") != "1":
        try:
            import preview  # tools/manuscript/preview.py
            import tempfile
            for src in paths[:3]:
                rel = src.relative_to(project).as_posix() if src.is_relative_to(project) else src.name
                cur = currency.get(rel, (True, "built for this bundle", {}))
                origin = (f"rendered from {rel} sha256 {hashlib.sha256(src.read_bytes()).hexdigest()[:16]}"
                          f"; sources " + (", ".join(f"{k} {v}" for k, v in cur[2].items()) or "-")
                          + f"; CURRENT ({cur[1]})")
                with tempfile.TemporaryDirectory(prefix="mp_bundle_") as tmp:
                    pdf = preview.to_pdf(src, Path(tmp))
                    for i, img in enumerate(preview.rasterise(pdf, Path(tmp), None, 80), 1):
                        dst = out / "preview" / f"{src.stem}-p{i:02d}.png"
                        dst.parent.mkdir(exist_ok=True)
                        shutil.copyfile(img, dst)
                        pages.append((dst, origin))
        except Exception as exc:  # noqa: BLE001 - preview is best effort; the text copies remain
            lines += ["", f"(DOCX page preview unavailable - no Word/LibreOffice converter: "
                      f"{type(exc).__name__}: {exc}; read the DOCX text copy)"]
    elif stage >= "S17" and paths:
        lines += ["", "(DOCX page preview skipped: MEDPAPER_NO_PREVIEW=1; read the DOCX text copy)"]
    if pages:
        lines += ["", "## Rendered Word pages (read them as the reader will see the paper)", ""]
        lines += [f"- {p} ({origin})" for p, origin in pages]
    (out / "MANIFEST.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def science_materials(project: Path, out: Path) -> list[str]:
    """1.23.0 (S3): results in words, the analyses done (by role) and the publishability
    checkpoints, as plain text for the science reviewer."""
    import importlib.util
    from . import clinical, paths
    from . import publishability as pb
    lines = []
    try:
        spec = importlib.util.spec_from_file_location(
            "medpaper_writer_bundle", paths.tools_dir() / "manuscript" / "writer_bundle.py")
        wb = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(wb)
        words, _gaps = wb.results_in_words(project, clinical.dictionary(project))
        dst = out / "files" / "results_in_words.md"
        dst.write_text("# Results in words (clinical labels)\n\n" + "\n".join(words) + "\n",
                       encoding="utf-8")
        lines.append(f"- {dst} (every result as a sentence with its clinical label)")
    except Exception as exc:  # noqa: BLE001 - key_results.md remains
        lines.append(f"(results in words unavailable: {type(exc).__name__}: {exc})")
    try:
        man = json.loads((Path(project) / "03_analysis/analysis_manifest.json").read_text(
            encoding="utf-8")).get("scripts", [])
    except (OSError, ValueError, AttributeError):
        man = []
    rows = [f"- {e.get('role', '?')}: {e.get('path', '')}"
            + (f" - could change: {e['decision']}" if e.get("decision") else "")
            for e in man if isinstance(e, dict)]
    dst = out / "files" / "analyses_done.md"
    dst.write_text("# Analyses done (primary, secondary, validity/sensitivity, additional)\n\n"
                   + ("\n".join(rows) or "- (no analysis_manifest.json; see results_in_words.md)")
                   + "\n", encoding="utf-8")
    lines.append(f"- {dst} (the analyses done by role, incl. sensitivity and validity checks)")
    cps = pb.load(project)["checkpoints"]
    text = ["# Publishability checkpoints", ""] + [
        f"- {s}: {e.get('verdict')} / {e.get('article_type')} - evidence: "
        + json.dumps(e.get("evidence"), ensure_ascii=False)[:600] for s, e in sorted(cps.items())]
    dst = out / "files" / "publishability.md"
    dst.write_text("\n".join(text or ["- none recorded"]) + "\n", encoding="utf-8")
    lines.append(f"- {dst} (S02/S04/S06 verdicts and their evidence)")
    return lines


def _display_text_files(project: Path, out: Path) -> list[str]:
    """1.20.0 (V6): the contact sheet of all displays and the visible-text inventory (with the
    strings the deterministic rules still flag) for the reviewer."""
    import shutil
    lines = []
    for rel in ("05_figures/qc/displays_sheet.png", "05_figures/qc/contact_sheet.png"):
        src = project / rel
        if src.is_file():
            dst = out / "files" / rel.replace("/", "__")
            shutil.copyfile(src, dst)
            lines.append(f"- {dst} (all displays in one image: can each be read on its own?)")
            break
    try:
        from . import displaytext
        inv = displaytext.inventory(project)
        if not inv["displays"]:
            return lines
        review: list[str] = []
        finds = displaytext.findings(project, inv, review)
        text = [displaytext.markdown(inv), "", f"## Strings the checks still flag ({len(finds)})", ""]
        text += [f"- {displaytext.line(f)}" for f in finds] or ["- none"]
        if review:
            text += ["", "## For your judgement", ""] + [f"- {r}" for r in review]
        dst = out / "files" / "display_text.md"
        dst.write_text("\n".join(text) + "\n", encoding="utf-8")
        lines.append(f"- {dst} (every visible string of every table and figure, by role)")
    except Exception as exc:  # noqa: BLE001 - the displays themselves remain in the bundle
        lines.append(f"(display text inventory unavailable: {type(exc).__name__}: {exc})")
    return lines


def close(project: Path, scope: str, findings: dict[str, int], changes: list[dict],
          not_changed: list[dict], finding_list: list[dict] | None = None,
          report: Path | None = None, preference_reason: str = "",
          recommendations: dict[str, str] | None = None) -> dict:
    data = load(project)
    if not data[scope] or data[scope][-1].get("closed_at"):
        raise ValueError("no open review round; start one first")
    rnd = data[scope][-1]
    text = ""
    if rnd.get("protocol"):
        if report is None or not Path(report).is_file():
            raise ValueError("save the reviewer's full report (all sections, numbered F1, F2, ...) "
                             "and pass it: close --report <file>")
        text = Path(report).read_text(encoding="utf-8", errors="replace")
        rel = f"{REPORTS_DIR}/{rnd['id']}.md"
        (Path(project) / rel).parent.mkdir(parents=True, exist_ok=True)
        (Path(project) / rel).write_text(text, encoding="utf-8")
        rnd["report"], rnd["report_ids"] = rel, report_ids(text)
    counts = {k: int(findings.get(k, 0)) for k in SEVERITIES}
    if any(v < 0 for v in counts.values()):
        raise ValueError("finding counts must be >= 0")
    for c in changes:
        if not str(c.get("file", "")).strip() or not str(c.get("summary", "")).strip():
            raise ValueError("each change needs a file and a one-line summary")
    finding_list = list(finding_list or [])
    group = []
    if preference_reason.strip():
        # 1.15.0 (E4): every finding the report tags PREFERENCE closes as ONE group with one
        # reason (not counted in the severity counts; never a protected category).
        if len(preference_reason.strip()) < 10:
            raise ValueError("--preference-group needs a reason (>= 10 characters)")
        listed = {f.get("id") for f in finding_list}
        group = [i for i in preference_ids(text) if i not in listed]
        if not group:
            raise ValueError("--preference-group: the report tags no unlisted finding PREFERENCE")
        rnd["preference_group"] = {"ids": group, "reason": preference_reason.strip()}
        not_changed = list(not_changed) + [{"item": i, "reason": preference_reason.strip()}
                                           for i in group]
    if len(finding_list) != sum(counts.values()):
        raise ValueError(f"list every finding with --finding ID CATEGORY STATUS \"one line\" "
                         f"({sum(counts.values())} counted, {len(finding_list)} listed)")
    for f in finding_list:
        if f.get("category") not in CATEGORIES or f.get("status") not in STATUSES:
            raise ValueError(f"finding {f.get('id')}: category must be {'|'.join(CATEGORIES)}, "
                             f"status {'|'.join(STATUSES)}")
        if f["category"] in PROTECTED and f["status"] == "kept":
            raise ValueError(f"finding {f['id']} ({f['category']}) cannot be kept on your own "
                             "judgement: change it, or mark it 'author' so the user decides")
        if f["category"] not in PROTECTED and f["status"] == "author":
            # 1.22.0 (U2): presentation and label findings are the agent's call - no pause.
            raise ValueError(f"finding {f['id']} (other): 展示/标签类问题由你自己决定 - 'changed' "
                             "或 'kept'（如留给排版，写明原因），不要交给作者")
    finding_list += [{"id": i, "category": "other", "status": "kept",
                      "summary": "preference (closed as a group)"} for i in group]
    # 1.22.0 (U2): a protected finding handed to the author carries the agent's recommendation
    # (default keep: had the agent agreed it would have applied the fix as 'changed').
    for f in finding_list:
        if f.get("status") == "author":
            rec = (recommendations or {}).get(f.get("id"), "keep")
            if rec not in ("change", "keep"):
                raise ValueError(f"--recommend {f.get('id')}: change or keep")
            f["recommendation"] = rec
    probe = dict(rnd, finding_list=finding_list, not_changed=not_changed, closed_at="probe")
    open_items = _closure(probe)
    if open_items:
        raise ValueError("; ".join(open_items[:6]) + " - every numbered finding, including Reader "
                         "comprehension and Medical presentation, is changed, kept with a reason, "
                         "or handed to the author")
    rnd.update(findings=counts, changes=changes, not_changed=not_changed,
               finding_list=finding_list, after=inputs(project, scope), closed_at=_now())
    from . import convergence as cv  # 1.22.0 (R2): no new must-fix -> READY
    rnd["ready"] = cv.ready(rnd, text)
    rnd["must_fix"] = cv.must_fix_ids(text)
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
    from .argtext import verify as _verify_text
    _verify_text(words, "the user's words")  # 1.12.0 (C1): no mojibake ever stored
    if answer == DONE and scope == "science" and not is_proceed(words):
        raise ValueError("not a decision to proceed: record the user's explicit words, e.g. "
                         "'继续写作' / '按你的建议' / 'proceed' ('OK' or '可以' alone do not count)")
    if answer == DONE:
        if scope != "science" and not is_confirmation(words):
            raise ValueError(f"not a confirmation: ask the user to state exactly "
                             f"'{CONFIRM_PHRASES[0]}' (or '{CONFIRM_PHRASES[1]}'); other words "
                             "('OK', '可以', '无需审阅') do not count")
        pend = pending_author(rnd)
        if pend:
            raise ValueError("author decision(s) pending: " + ", ".join(f["id"] for f in pend)
                             + " (review_round.py author ID change|keep --words ...)")
        current = inputs(project, scope)
        drift = _changed_since(rnd, current, project)
        if drift:
            raise ValueError("changed after the round closed (run another round, --delta is "
                             "fine): " + ", ".join(drift[:6]))
        rnd["confirmed_version"] = version_id(current)
    rnd.update(user_decision=answer, user_words=words.strip(), decided_at=_now())
    _save(project, data)
    stored = load(project)[scope][-1].get("user_words", "")
    if stored != words.strip():  # read back what was written
        raise ValueError("the stored user words differ from the input; re-record with --words-file")
    _write_summary(project, scope, data[scope])
    return rnd


def status_summary(project: Path, scope: str) -> dict:
    """Compact, always-valid status for `review_round.py status` (1.12.0 C6)."""
    rounds = load(project)[scope]

    def short(text, n=160):
        text = " ".join(str(text or "").split())
        return text if len(text) <= n else text[:n - 3] + "..."
    out = []
    for r in rounds[-3:]:
        out.append({
            "id": r.get("id"), "mode": r.get("mode"), "stage": r.get("stage"),
            "started_at": r.get("started_at"), "closed_at": r.get("closed_at"),
            "reviewed": len(r.get("reviewed", [])), "findings": r.get("findings") or {},
            "changes": len(r.get("changes", [])),
            "pending_author": [f.get("id") for f in pending_author(r)],
            "user_decision": r.get("user_decision"), "user_words": short(r.get("user_words")),
            "linked_to": r.get("linked_to"), "superseded_by": r.get("superseded_by"),
            "report": r.get("report")})
    return {"scope": scope, "rounds_total": len(rounds), "latest": out}


def author_decide(project: Path, scope: str, fid: str, choice: str, words: str) -> dict:
    """Record the author's decision on one protected finding handed to them."""
    if choice not in ("change", "keep"):
        raise ValueError("author decision must be change or keep")
    if len(words.strip()) < 2:
        raise ValueError("record the author's words")
    from .argtext import verify as _verify_text
    _verify_text(words, "the author's words")
    data = load(project)
    rnd = data[scope][-1] if data[scope] else None
    if not rnd or not rnd.get("closed_at"):
        raise ValueError("no closed round to decide on")
    hit = next((f for f in rnd.get("finding_list", []) if f.get("id") == fid
                and f.get("status") == "author"), None)
    if hit is None:
        raise ValueError(f"no finding {fid} awaiting the author in {rnd['id']}")
    hit["author_decision"] = {"choice": choice, "words": words.strip(), "at": _now()}
    _save(project, data)
    _write_summary(project, scope, data[scope])
    return hit


def export(project: Path, scope: str) -> Path:
    """1.10.0 (#11), only on the user's explicit request: a read-only copy of the current
    files plus a one-page change summary since the last confirmed version. Never default."""
    import zipfile
    project = Path(project)
    current = inputs(project, scope)
    rounds = load(project)[scope]
    confirmed = next((r for r in reversed(rounds) if r.get("user_decision") == DONE), None)
    base = (confirmed or {}).get("after") or {}
    changed = sorted(r for r, h in current.items() if base.get(r) != h)
    removed = sorted(set(base) - set(current))
    since = [r for r in rounds if not confirmed or r["started_at"] > confirmed.get("decided_at", "")]
    files = sorted(set(current) | {
        p.relative_to(project).as_posix()
        for pat in ("08_submission/bundle/*.docx", "08_submission/bundle/*.pdf",
                    "04_tables/main/*.xlsx", "04_tables/supplementary/*.xlsx", "05_figures/out/*.png")
        for p in project.glob(pat) if p.is_file()})
    vid = version_id(current)
    lines = [f"# Change summary ({scope}, version {vid[:12]})", "",
             "Since the last confirmed version: "
             + (f"{confirmed['id']} ({confirmed.get('decided_at')})" if confirmed else "none (first version)"),
             "", f"Changed files ({len(changed)}):"] + [f"- {r}" for r in changed[:40]]
    if removed:
        lines += ["", "Removed:"] + [f"- {r}" for r in removed[:20]]
    lines += ["", "Changes made in review rounds:"]
    lines += [f"- {r['id']} {c['file']}: {c['summary']}" for r in since for c in r.get("changes", [])][:40]
    out = project / "07_manuscript/review_packages" / f"export-{scope}-{vid[:12]}.zip"
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in files:
            info = zipfile.ZipInfo(rel, date_time=(2000, 1, 1, 0, 0, 0))
            info.external_attr = 0o444 << 16  # read-only on extraction
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, (project / rel).read_bytes())
        info = zipfile.ZipInfo("CHANGES.md", date_time=(2000, 1, 1, 0, 0, 0))
        info.external_attr = 0o444 << 16
        zf.writestr(info, "\n".join(lines) + "\n")
    return out


def _write_summary(project: Path, scope: str, rounds: list[dict]) -> None:
    """The stage's human-readable review record, regenerated from the rounds (no hand edit)."""
    cfg = SCOPES[scope]
    h = cfg["headings"]
    last = rounds[-1]
    title = {"manuscript": "Manuscript", "package": "Submission package",
             "science": "Science (before writing)"}[scope]
    lines = [f"# {title} review rounds",
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
        for f in r.get("finding_list", []):
            dec = f.get("author_decision")
            tail = (f" -> author: {dec['choice']} (\"{dec['words']}\")" if dec else
                    " -> PENDING AUTHOR DECISION" if f.get("status") == "author" else "")
            lines.append(f"- {r['id']} {f.get('id')} [{f.get('category')}] {f.get('status')}: "
                         f"{f.get('summary', '')}{tail}")
    lines += ["", f"## {h[3]}", "",
              f"- {last['id']}: hashes after the changes recorded at {last.get('closed_at')}; "
              "the gate fails if any covered file changes afterwards.", "", f"## {h[4]}", ""]
    for r in rounds:
        if r.get("user_decision"):
            lines.append(f"- {r['id']}: {r['user_decision']} - \"{r.get('user_words', '')}\""
                         + (f" (version {r['confirmed_version'][:12]})"
                            if r.get("confirmed_version") else ""))
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
    if pending_author(last):
        out.append(f"round {last['id']}: author decision pending on "
                   + ", ".join(f["id"] for f in pending_author(last)))
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
