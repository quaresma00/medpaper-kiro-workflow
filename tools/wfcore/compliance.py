"""1.18.0 (K4/K5): the compliance matrix - one row per guideline requirement.

Generated (never hand-edited) from 08_submission/guideline_requirements.json by
`tools/manuscript/submission_qc.py write` (so by `wf rebuild`) or `wf compliance write`:

    08_submission/compliance_matrix.json / .md
      auto     measured from the built files (word counts, keywords, abstract, title page,
               highlights, cover letter, uploads, figure files, ORCID, CSL, declarations ...)
      builder  the upload that applies the typed field has a current build receipt
      manual   the agent records where the package meets it in
               08_submission/compliance_evidence.json {"R07": {"file": "...", "where": "..."}}
               (or {"status": "cannot_assess", "reason": "..."}); WARN at S23 until filled,
               FAIL at S25
      portal   the user does it in the submission system (CANNOT_ASSESS, portal to-do)
      n.a.     its reason; categories the guide is silent on are N.A. rows too

Status values: PASS, FAIL, WARN, CANNOT_ASSESS (with reason), N.A.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from . import requirements as rq

MATRIX_JSON = "08_submission/compliance_matrix.json"
MATRIX_MD = "08_submission/compliance_matrix.md"
EVIDENCE = "08_submission/compliance_evidence.json"
MANIFEST = "08_submission/bundle/manifest.json"
PASS, FAIL, WARN, CANNOT, NA = "PASS", "FAIL", "WARN", "CANNOT_ASSESS", "N.A."
STATUSES = (PASS, FAIL, WARN, CANNOT, NA)

# rule.field prefix -> measurement; the longest matching prefix wins.
FIELD_MEASURE = {
    "limits.main_text_words": "words", "limits.abstract_words": "words",
    "limits.reference_limit": "words", "limits.display_items": "displays",
    "limits.main_figures": "displays", "limits.main_tables": "displays",
    "keywords": "keywords", "abstract": "abstract", "title_page": "title_page",
    "title_page.running_title_max_chars": "running_title", "running_title_position": "running_title",
    "highlights": "highlights", "key_points": "highlights", "cover_letter": "cover_letter",
    "required_uploads": "required_uploads", "figure": "figure", "figure_dpi": "figure",
    "orcid_required": "orcid", "csl": "csl", "declarations_order": "declarations",
}
CHECK_MEASURE = {
    "word_limits": "words", "reference_limit": "words", "display_items": "displays",
    "keywords": "keywords", "abstract": "abstract", "title_page": "title_page",
    "running_title": "running_title", "highlights": "highlights", "cover_letter": "cover_letter",
    "required_uploads": "required_uploads", "figure_files": "figure", "orcid": "orcid",
    "csl": "csl", "declarations_order": "declarations", "page_numbers": "page_numbers",
    "ai_statement": "ai_statement", "reference_format": "reference_format",
}
QC_ROWS = {"declarations": "Declarations order", "page_numbers": "Automatic page numbers",
           "ai_statement": "AI/LLM-use statement", "reference_format": "References: number"}
BUILDER_ROLE = {"title_page": "title_page", "running_title": "title_page",
                "cover_letter": "cover_letter", "supplementary": "supplementary",
                "highlights": "highlights"}


def _measure_name(field: str, check: str) -> str | None:
    if check:
        return CHECK_MEASURE.get(check)
    best = None
    for key, name in FIELD_MEASURE.items():
        if (field == key or field.startswith(key + ".")) and (best is None or len(key) > len(best[0])):
            best = (key, name)
    return best[1] if best else None


def measurable(field: str, check: str) -> bool:
    return _measure_name(str(field or ""), str(check or "")) is not None


def _json(path: Path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _manuscript_docx(project: Path) -> Path | None:
    data = _json(Path(project) / MANIFEST) or {}
    for i in data.get("items", []) if isinstance(data, dict) else []:
        f = Path(project) / str(i.get("file", ""))
        if str(i.get("role", "")).casefold() == "manuscript" and f.suffix.casefold() == ".docx" and f.is_file():
            return f
    return None


class _Measure:
    """Measurements shared by all rows of one matrix build (computed once, lazily)."""

    def __init__(self, ctx, qc_rows=None):
        from . import journalspec
        self.ctx, self.project = ctx, Path(ctx.project)
        self.target = journalspec.load(self.project)
        self._counts = self._qc = None
        self._qc_rows = qc_rows

    def counts(self):
        from . import journalspec
        if self._counts is None:
            path = _manuscript_docx(self.project)
            self._counts = journalspec.docx_counts(path, journalspec.word_count_scope(self.target),
                                                   self.target) if path else {}
        return self._counts

    def qc(self):
        if self._qc is None:
            if self._qc_rows is not None:
                self._qc = self._qc_rows
            else:
                from . import submissionqc
                try:
                    self._qc = submissionqc.measure(self.ctx)
                except Exception as exc:  # noqa: BLE001 - a broken measurement is a row, not a crash
                    self._qc = [{"item": "measure", "status": "FAIL", "evidence": str(exc)}]
        return self._qc

    def run(self, name: str, field: str):
        from . import journalfields, journalspec
        t, p = self.target, self.project
        if name == "words":
            c = self.counts()
            if not c:
                return CANNOT, "manuscript.docx not built (manifest role manuscript)"
            caps, _ = journalspec.limits(t)
            soft = journalspec.soft_limits(t)
            keys = [field.split(".", 1)[1]] if field.startswith("limits.") else \
                ["main_text_words", "abstract_words", "reference_limit"]
            got = {"main_text_words": c.get("main", 0), "abstract_words": c.get("abstract", 0),
                   "reference_limit": c.get("references", 0)}
            out, bad, warn = [], [], []
            for k in keys:
                if caps.get(k) is None:
                    continue
                line = f"{k} {got[k]} / {caps[k]}"
                out.append(line)
                if got[k] > caps[k]:
                    (warn if k in soft else bad).append(line + (" (estimated cap)" if k in soft else ""))
            if bad:
                return FAIL, "over the cap: " + "; ".join(bad)
            if warn:
                return WARN, "; ".join(warn)
            return PASS, "; ".join(out) or "no typed cap set"
        if name == "displays":
            plan = _json(p / "01_protocol/artifact_plan.json") or {}
            nf, nt = len(plan.get("main_figures") or []), len(plan.get("main_tables") or [])
            caps, _ = journalspec.limits(t)
            have = {"display_items": nf + nt, "main_figures": nf, "main_tables": nt}
            keys = [field.split(".", 1)[1]] if field.startswith("limits.") else list(have)
            bad = [f"{k} {have[k]} > {caps[k]}" for k in keys if caps.get(k) is not None and have[k] > caps[k]]
            return (FAIL, "; ".join(bad)) if bad else (
                PASS, f"{nf} main figure(s), {nt} main table(s)")
        if name == "keywords":
            text = (p / self.ctx.src("07_manuscript/full_manuscript.md"))
            body = text.read_text(encoding="utf-8", errors="replace") if text.is_file() else ""
            m = re.search(r"(?mi)^\s*\**keywords\**\s*[:\uff1a]\**\s*(.+)$", body)
            if not m:
                return FAIL, "no 'Keywords:' line in the journal copy"
            probs = journalspec.keyword_problems(m.group(1), journalspec.keyword_rules(t))
            return (FAIL, "; ".join(probs)) if probs else (PASS, f"keywords: {m.group(1).strip()[:120]}")
        if name in journalfields.CHECKS:
            return journalfields.CHECKS[name](p, t)
        if name == "csl":
            from . import cslindex, paths
            from .checks.v1170 import _journal_issns
            csl = t.get("csl") if isinstance(t.get("csl"), dict) else {}
            files = [p / csl["file"]] if csl.get("file") else sorted(p.glob("08_submission/*.csl"))
            files = [f for f in files if f.is_file()]
            if len(files) != 1:
                return FAIL, f"{len(files)} CSL file(s) in 08_submission/ (need exactly the journal's one)"
            try:
                ok, why = cslindex.matches(paths.repo_root(), files[0], _journal_issns(t))
            except Exception as exc:  # noqa: BLE001
                return FAIL, f"{files[0].name} unreadable: {exc}"
            if not ok and len(str(csl.get("reason", "")).strip()) >= 20:
                return PASS, f"{why}; recorded reason: {str(csl['reason'])[:100]}"
            return (PASS if ok else FAIL), why
        if name in QC_ROWS:
            row = next((r for r in self.qc() if str(r.get("item", "")).startswith(QC_ROWS[name])), None)
            if row is None:
                return NA, "not measured for this paper"
            st = {"N/A": NA}.get(row["status"], row["status"])
            return st, str(row.get("evidence", ""))[:300]
        return CANNOT, f"no measurement named {name}"


def _builder(project: Path, req: dict) -> tuple[str, str]:
    from . import displayfiles, rebuild
    field = str((req.get("rule") or {}).get("field", ""))
    if req.get("category") == "figures" or field.startswith(("figure.", "separate_display_files",
                                                              "display_file_names")):
        files, _ = displayfiles.wanted(project)
        if files:
            probs = displayfiles.problems(project)
            return (FAIL, "; ".join(probs[:3])) if probs else (
                PASS, f"{len(files)} display file(s) generated from the certified masters")
    role = BUILDER_ROLE.get(str(req.get("category")), "manuscript")
    kind = "statements" if role == "highlights" else role
    recs = [r for r in rebuild.receipts(project) if r.get("kind") == kind]
    if not recs:
        return FAIL, f"no build receipt for the {role} upload (build it with build_docx.py)"
    for r in recs:
        why = rebuild.stale(project, r)
        if why:
            return FAIL, f"{r['output']} is stale ({'; '.join(why)[:120]}): wf rebuild"
        if rebuild.hand_edited(project, r):
            return FAIL, f"{r['output']} differs from its build (hand edit)"
    return PASS, f"{', '.join(Path(r['output']).name for r in recs)} built by the engine from the " \
                 f"current target_journal.json/docx_style.json"


def _manual(project: Path, req: dict, evidence: dict) -> tuple[str, str]:
    ev = evidence.get(str(req.get("id"))) if isinstance(evidence, dict) else None
    if not isinstance(ev, dict):
        return WARN, f"evidence location missing: add it to {EVIDENCE}"
    if str(ev.get("status", "")).casefold() in ("cannot_assess", "cannot assess"):
        reason = str(ev.get("reason", "")).strip()
        return (CANNOT, reason) if len(reason) >= 8 else (WARN, "cannot_assess needs a reason")
    f, where = str(ev.get("file", "")).strip(), str(ev.get("where", "")).strip()
    if not f or len(where) < 3:
        return WARN, f"evidence needs a file and a location (paragraph/line) in {EVIDENCE}"
    if not (Path(project) / f).is_file():
        return FAIL, f"evidence file {f} does not exist"
    return PASS, f"{f}: {where}"[:300]


def _short(text: str, n: int = 140) -> str:
    s = rq.norm(text)
    return s if len(s) <= n else s[: n - 3] + "..."


def build_rows(ctx, qc_rows=None) -> list[dict]:
    project = Path(ctx.project)
    data = rq.load(project)
    evidence = _json(project / EVIDENCE) or {}
    m = _Measure(ctx, qc_rows)
    rows = []
    for r in data.get("requirements") or []:
        if not isinstance(r, dict):
            continue
        rule = r.get("rule") if isinstance(r.get("rule"), dict) else {}
        enf = r.get("enforcement")
        if enf == "auto":
            name = _measure_name(str(rule.get("field", "")), str(rule.get("check", "")))
            status, ev = m.run(name, str(rule.get("field", ""))) if name else (
                CANNOT, "no engine measurement for this rule")
        elif enf == "builder":
            status, ev = _builder(project, r)
        elif enf == "manual":
            status, ev = _manual(project, r, evidence)
        elif enf == "portal":
            status, ev = CANNOT, "portal: the user does this in the submission system"
        else:
            status, ev = NA, str(r.get("reason", "")).strip() or "not applicable"
        if status == NA and enf == "auto":
            status, ev = CANNOT, f"cannot assess: {ev}"
        rows.append({"id": str(r.get("id")), "category": str(r.get("category")),
                     "lines": rq._ranges(rq.line_numbers(r.get("lines"))), "enforcement": enf,
                     "status": status, "evidence": str(ev).replace("\n", " ")[:400],
                     "quote": _short(r.get("quote", "")), "portal": enf == "portal"})
    for e in data.get("not_mentioned") or []:
        if isinstance(e, dict):
            rows.append({"id": f"NM-{e.get('category')}", "category": str(e.get("category")),
                         "lines": "", "enforcement": "n.a.", "status": NA,
                         "evidence": "guide silent; searched: " + ", ".join(map(str, e.get("searched") or [])),
                         "quote": "", "portal": False})
    return rows


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12] if path.is_file() else ""


def render(project: Path, rows: list[dict]) -> tuple[str, str]:
    data = rq.load(project)
    counts = {s: sum(1 for r in rows if r["status"] == s) for s in STATUSES}
    payload = {"schema": 1, "journal": data.get("journal"), "journal_epoch": data.get("journal_epoch"),
               "article_type": data.get("article_type"),
               "requirements_sha256": _sha(Path(project) / rq.REQ_REL), "counts": counts, "rows": rows}
    js = json.dumps(payload, indent=1, ensure_ascii=False) + "\n"
    lines = [f"# Compliance matrix - {data.get('journal')} ({data.get('article_type') or '-'})", "",
             "Generated from 08_submission/guideline_requirements.json by `wf compliance write` / "
             "`wf rebuild`; do not edit. Manual evidence: 08_submission/compliance_evidence.json.", "",
             "Counts: " + ", ".join(f"{s} {n}" for s, n in counts.items()), "",
             "| ID | Category | Lines | Enforcement | Status | Evidence / reason | Requirement |",
             "|---|---|---|---|---|---|---|"]
    cell = lambda s: str(s).replace("|", "/")  # noqa: E731
    lines += [f"| {r['id']} | {r['category']} | {r['lines']} | {r['enforcement']} | {r['status']} | "
              f"{cell(r['evidence'])[:220]} | {cell(r['quote'])} |" for r in rows]
    portal = [r for r in rows if r["portal"]]
    lines += ["", "## Portal to-do (the user, in the submission system)", ""]
    lines += [f"- {r['id']} ({r['lines']}): {r['quote']}" for r in portal] or ["- none"]
    return js, "\n".join(lines) + "\n"


def write(ctx, qc_rows=None) -> list[dict]:
    project = Path(ctx.project)
    if not (project / rq.REQ_REL).is_file():
        return []
    rows = build_rows(ctx, qc_rows)
    js, md = render(project, rows)
    (project / MATRIX_JSON).write_text(js, encoding="utf-8")
    (project / MATRIX_MD).write_text(md, encoding="utf-8")
    from .revision import record_derived
    record_derived(project, [project / MATRIX_JSON, project / MATRIX_MD])
    return rows


def verify(ctx, final: bool = False) -> tuple[list[str], list[str], list[dict]]:
    """(blocking problems, warnings, rows) for compliance_matrix_complete."""
    project = Path(ctx.project)
    if not (project / rq.REQ_REL).is_file():
        return [f"{rq.REQ_REL} missing (S20 requirement list)"], [], []
    rows = build_rows(ctx)
    js, md = render(project, rows)
    probs, warns = [], []
    for rel, want in ((MATRIX_JSON, js), (MATRIX_MD, md)):
        p = project / rel
        if not p.is_file() or p.read_text(encoding="utf-8") != want:
            probs.append(f"{rel} is stale or hand-edited: wf compliance write (or wf rebuild)")
    fails = [r for r in rows if r["status"] == FAIL]
    if fails:
        probs.append(f"{len(fails)} requirement(s) FAIL: " + "; ".join(
            f"{r['id']} {r['evidence'][:90]}" for r in fails[:6]))
    pending = [r for r in rows if r["status"] == WARN]
    if pending:
        msg = (f"{len(pending)} row(s) WARN (manual evidence missing or estimated cap): "
               + ", ".join(r["id"] for r in pending[:12]))
        (probs if final and any(r["enforcement"] == "manual" for r in pending) else warns).append(msg)
    return probs, warns, rows


ZH_STATUS = {PASS: "通过", FAIL: "未通过", WARN: "警告", CANNOT: "无法评估", NA: "不适用"}


def summary_zh(project: Path) -> list[str]:
    """K5: the short Chinese compliance summary shown to the user at S24."""
    data = _json(Path(project) / MATRIX_JSON)
    if not isinstance(data, dict):
        return []
    rows = data.get("rows") or []
    c = data.get("counts") or {}
    cat = lambda r: rq.CATEGORIES.get(r.get("category"), r.get("category"))  # noqa: E731
    out = [f"投稿指南合规矩阵（{data.get('journal')}，{len(rows)} 条）：" + "、".join(
        f"{ZH_STATUS[s]} {c.get(s, 0)}" for s in STATUSES)]
    for title, sel in (("未通过", lambda r: r["status"] == FAIL),
                       ("无法评估（需要您确认）", lambda r: r["status"] == CANNOT and not r.get("portal")),
                       ("投稿系统中由您完成", lambda r: r.get("portal")),
                       ("警告", lambda r: r["status"] == WARN)):
        items = [r for r in rows if sel(r)]
        if items:
            out.append(f"{title}：")
            out += [f"- {r['id']}［{cat(r)}］{(r.get('quote') or r.get('evidence'))[:70]}"
                    f"（{r.get('lines') or '-'}）：{r.get('evidence', '')[:60]}" for r in items]
    return out
