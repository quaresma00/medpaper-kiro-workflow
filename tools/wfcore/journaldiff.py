"""1.22.0 (J1/J6/J7): what changes between journals, and nothing of the old one left behind.

J7  `wf journal diff` - at S20, one list of what differs from the previous journal epoch (or
    from the engine defaults in the first epoch): required statements, section structure,
    file naming, figure sizes, limits, APC and waivers, portal items. Each row is marked
    auto (the engine applies it), self-verify (the agent checks it) or user decision, and the
    list is shown to the user ONCE in Chinese, in the same message as the other S20 questions.
    Builder-enforceable requirements the engine cannot express (J1) are listed with their
    manual handling, at S20 - never first at S23. Stored in .wf/journal_diff.json.
J6  journal_traces_clean (S20, S23) - after a switch every current journal-layer file and the
    manuscript copy is scanned for the old journal's names, abbreviations and ISSNs,
    fingerprints of its guideline quotes, and its cover letter and journal-specific abstract
    sentences; each hit fails with file and line.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

REL = ".wf/journal_diff.json"
TARGET = "08_submission/target_journal.json"
ABBREV_KEYS = ("iso_abbreviation", "nlm_iso_abbreviation", "iso_abbrev", "nlm_abbreviation",
               "abbreviation", "journal_abbreviation", "short_title")
ISSN_KEYS = ("issn", "eissn", "e_issn", "issn_print", "issn_electronic", "pissn", "issns")
ISSN_RE = re.compile(r"\b\d{4}-\d{3}[\dXx]\b")
# Files that may legitimately name earlier journals (history, carried records, raw captures).
TRACE_SKIP = ("08_submission/journal_archives/", "08_submission/cache/", "08_submission/notes/",
              "08_submission/guidelines_history/", "08_submission/build_receipts/",
              "08_submission/journal_shortlist.md", "08_submission/declarations_assessment.json",
              "08_submission/guidelines_source.txt", "08_submission/portal_requirements.json")
DEFAULTS = {"limits": "无（引擎起草预算 4000/250 词）", "main_text_headings": "Introduction/Methods/Results/Discussion",
            "abstract": "引擎默认结构", "declarations_order": "Springer Nature 默认顺序",
            "display_file_names": "Fig{n}.tif / Table{n}.xlsx",
            "supplementary_file_pattern": "Supplemental_File_{n}_{Title}",
            "figure": "TIFF/PNG，300 dpi", "presentation.figure_width_mm": "90/140/180 mm",
            "apc": "未记录", "required_uploads": "manuscript, figures, tables, cover letter",
            "page_breaks": "allowed", "abbreviation_list": "after_keywords"}
ROWS = (  # (label_zh, field, handler)
    ("必需声明", "declarations_order", "self-verify"),
    ("章节结构", "main_text_headings", "auto"),
    ("摘要结构", "abstract", "auto"),
    ("文件命名", "display_file_names", "auto"),
    ("补充文件命名", "supplementary_file_pattern", "auto"),
    ("上传项", "required_uploads", "self-verify"),
    ("图片尺寸", "presentation.figure_width_mm", "auto"),
    ("图片格式/分辨率", "figure", "auto"),
    ("字数/篇幅限制", "limits", "auto"),
    ("分页", "page_breaks", "auto"),
    ("缩略语表位置", "abbreviation_list", "auto"),
    ("版面费与减免", "apc", "user decision"),
)
HANDLER_ZH = {"auto": "引擎自动处理", "self-verify": "代理自行核对", "user decision": "需要您决定"}
BUILDER_CATEGORIES = {"layout", "tables", "figures", "references", "title_page",
                      "section_headings", "supplementary", "abstract_structure"}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _json(path: Path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _get(d: dict, dotted: str):
    cur = d
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _apc(t: dict):
    vals = {k: t.get(k) for k in ("apc", "apc_usd", "apc_amount", "apc_waiver", "waivers",
                                  "open_access", "apc_policy") if t.get(k) not in (None, "", [])}
    return vals or None


def _fmt(v) -> str:
    if v is None:
        return "-"
    s = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
    return s if len(s) <= 90 else s[:87] + "..."


def previous_layer(project: Path) -> Path | None:
    from . import journalepoch
    ep = journalepoch.number(project)
    return journalepoch.archive_of(project, ep - 1) if ep > 1 else None


def unexpressible(project: Path) -> list[str]:
    """J1: builder-type requirements the engine cannot express, with the manual handling."""
    from . import journalspec, requirements as rq
    out = []
    target = _json(Path(project) / TARGET) or {}
    if journalspec.page_breaks(target) == "none":
        out.append("指南要求不设分页符：标题页、表格和图注连续排版；横向表格页无法使用 - 过宽的表格请"
                   "缩减列或移入补充材料（S23 构建时会报告）")
    for r in rq.load(project).get("requirements") or []:
        if not isinstance(r, dict) or r.get("enforcement") != "manual" \
                or r.get("category") not in BUILDER_CATEGORIES:
            continue
        how = str(r.get("manual_handling") or r.get("reason") or "").strip() or \
            "在 08_submission/compliance_evidence.json 记录核对位置"
        out.append(f"{r.get('id')}（{rq._ranges(rq.line_numbers(r.get('lines')))}）“"
                   f"{rq.norm(r.get('quote', ''))[:70]}”：引擎无法自动排版，人工处理：{how}")
    return out


def rows(project: Path) -> list[dict]:
    project = Path(project)
    new = _json(project / TARGET) or {}
    prev_dir = previous_layer(project)
    old = (_json(prev_dir / "target_journal.json") or {}) if prev_dir else None
    out = []
    for label, field, handler in ROWS:
        nv = _apc(new) if field == "apc" else _get(new, field)
        if old is None:
            ov, base = DEFAULTS.get(field), "engine default"
        else:
            ov, base = (_apc(old) if field == "apc" else _get(old, field)), "previous journal"
        if nv in (None, "", [], {}) and old is None:
            continue
        if nv == ov:
            continue
        out.append({"item": label, "field": field, "old": _fmt(ov), "new": _fmt(nv),
                    "handler": handler, "basis": base})
    from . import portal
    cur = portal.current(project)
    prev_portal = (_json(prev_dir / "portal_requirements.json") or {}) if prev_dir else {}
    names = lambda rec: sorted(str(i.get("item")) for i in rec.get("upload_items") or [])  # noqa: E731
    if cur and names(cur) != names(prev_portal):
        out.append({"item": "投稿系统上传项", "field": "portal", "old": _fmt(names(prev_portal) or None),
                    "new": _fmt(names(cur)), "handler": "self-verify",
                    "basis": "previous journal" if prev_dir else "engine default"})
    return out


def target_sha(project: Path) -> str:
    p = Path(project) / TARGET
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16] if p.is_file() else ""


def write(project: Path) -> tuple[list[str], dict]:
    from . import journalepoch
    project = Path(project)
    rs, ux = rows(project), unexpressible(project)
    rec = {"schema": 1, "epoch": journalepoch.number(project),
           "journal": journalepoch.target_name(project), "target_sha": target_sha(project),
           "generated_at": _now(), "rows": rs, "unexpressible": ux}
    p = project / REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    basis = "与上一期刊相比" if previous_layer(project) else "与引擎默认相比"
    lines = [f"期刊差异清单（{basis}，{rec['journal'] or '未选定'}；请在本阶段的同一条消息里一次告知用户）："]
    if not rs:
        lines.append("  - 无差异")
    for r in rs:
        lines.append(f"  - {r['item']}：{r['old']} -> {r['new']}（{HANDLER_ZH[r['handler']]}）")
    if ux:
        lines.append("引擎无法自动表达、需要人工处理的指南要求：")
        lines += [f"  - {x}" for x in ux]
    return lines, rec


def listed_problems(project: Path) -> list[str]:
    """Gate journal_difference_listed: the list exists for this epoch and this target file."""
    from . import journalepoch
    rec = _json(Path(project) / REL)
    if not isinstance(rec, dict):
        return ["no journal difference list: run `wf journal diff` and show it to the user once "
                "(in the same message as the other S20 questions)"]
    if int(rec.get("epoch") or 0) != journalepoch.number(project):
        return [f"the difference list is for epoch {rec.get('epoch')}: run `wf journal diff` again"]
    if rec.get("target_sha") != target_sha(project):
        return ["target_journal.json changed after the difference list: run `wf journal diff` "
                "again (show only the new differences)"]
    return []


# ------------------------------------------------------------------ J6 traces
def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^0-9a-z]+", " ", str(text or "").casefold())).strip()


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n{2,}", re.sub(r"(?m)^#+.*$", " ", text or ""))
    return [p.strip() for p in parts if len(_norm(p)) >= 40]


def old_identities(project: Path) -> dict:
    """Names, abbreviations, ISSNs and text fingerprints of every earlier journal epoch."""
    from . import journalepoch
    project = Path(project)
    cur = _norm(journalepoch.target_name(project))
    out = {"names": set(), "abbrevs": set(), "issns": set(), "texts": {}}
    frozen = ""
    p = project / "07_manuscript/full_manuscript.md"
    if p.is_file():
        frozen = _norm(p.read_text(encoding="utf-8", errors="replace"))
    for e in journalepoch.load(project)["epochs"][:-1]:
        name = str(e.get("journal") or "").strip()
        if name and _norm(name) != cur:
            out["names"].add(name)
        arch = project / e["archive"] if e.get("archive") else None
        if not arch or not arch.is_dir():
            continue
        tj = _json(arch / "target_journal.json") or {}
        if tj.get("journal") and _norm(tj["journal"]) != cur:
            out["names"].add(str(tj["journal"]))
        for k in ABBREV_KEYS:
            v = str(tj.get(k) or "").strip()
            if len(v) >= 3 and _norm(v) != cur:
                out["abbrevs"].add(v)
        for k in ISSN_KEYS:
            v = tj.get(k)
            for s in (v if isinstance(v, list) else [v]):
                out["issns"].update(ISSN_RE.findall(str(s or "")))
        req = _json(arch / "guideline_requirements.json") or {}
        for r in req.get("requirements") or [] if isinstance(req, dict) else []:
            q = _norm(r.get("quote", "")) if isinstance(r, dict) else ""
            if len(q) >= 40:
                out["texts"][q] = f"old guideline quote {r.get('id')}"
        cl = arch / "cover_letter.md"
        if cl.is_file():
            for s in _sentences(cl.read_text(encoding="utf-8", errors="replace")):
                out["texts"][_norm(s)] = "old cover letter"
        ms = arch / "manuscript/full_manuscript.md"
        if ms.is_file():
            from . import journalspec
            ab = journalspec.markdown_sections(ms.read_text(encoding="utf-8", errors="replace")).get("abstract", "")
            for s in _sentences(ab):
                if _norm(s) not in frozen:  # journal-specific wording, not the frozen science
                    out["texts"][_norm(s)] = "old journal's abstract"
    return out


def _files(project: Path) -> list[Path]:
    root = Path(project) / "08_submission"
    out = []
    for p in sorted(root.rglob("*")) if root.is_dir() else []:
        rel = p.relative_to(project).as_posix()
        if p.is_file() and not rel.startswith(TRACE_SKIP) and \
                p.suffix.casefold() in (".md", ".txt", ".json", ".docx", ".csl", ".tsv"):
            out.append(p)
    return out


def _text(p: Path) -> str:
    if p.suffix.casefold() == ".docx":
        try:
            from .packagecontent import visible_text
            return visible_text(p)
        except Exception:  # noqa: BLE001
            return ""
    return p.read_text(encoding="utf-8", errors="replace")


def traces(project: Path) -> list[str]:
    from . import journalepoch
    project = Path(project)
    if journalepoch.number(project) < 2:
        return []
    ids = old_identities(project)
    new_name = journalepoch.target_name(project)
    src = project / "08_submission/guidelines_source.txt"
    if src.is_file():  # the same publisher's boilerplate in the new guide is not a trace
        new_src = _norm(src.read_text(encoding="utf-8", errors="replace"))
        ids["texts"] = {t: w for t, w in ids["texts"].items() if t not in new_src}
    hits = []
    for p in _files(project):
        rel = p.relative_to(project).as_posix()
        for no, line in enumerate(_text(p).splitlines(), 1):
            probe = line.replace(new_name, " ") if new_name else line
            found = []
            for n in ids["names"]:
                if re.search(rf"(?i)(?<![\w]){re.escape(n)}(?![\w])", probe):
                    found.append(f"old journal name '{n}'")
            for a in ids["abbrevs"]:
                if re.search(rf"(?<![\w]){re.escape(a)}(?![\w])", probe):
                    found.append(f"old abbreviation '{a}'")
            for s in ids["issns"]:
                if s in probe:
                    found.append(f"old ISSN {s}")
            nl = _norm(probe)
            if len(nl) >= 40:
                for t, what in ids["texts"].items():
                    if t in nl or (len(nl) >= 60 and nl in t):
                        found.append(what)
                        break
            for f in found:
                hits.append(f"{rel}:{no}: {f}")
    return hits
