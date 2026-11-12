"""1.21.0 (B5): what the journal's submission system asks for, read from the portal itself.

Optional, only when the user asks (S23/S24). After the user has logged into the submission
system in the browser window, the agent reads the submission steps WITHOUT changing anything
(article types, upload item types and whether a title-page slot exists, required fields,
declaration questions, file size/format limits), saves captures under .playwright-mcp/ and runs

    wf portal ingest --from <capture> [--append] --url <URL>

-> 08_submission/portal_requirements.json (source=portal, dated; captures kept in
08_submission/cache/portal/). The engine extracts a draft (each item cites its P-line); the
agent checks it against the listed lines. It feeds required_uploads (target_journal.json),
title_page.placement (no title-page slot -> in_manuscript), the portal to-do list and the
compliance matrix (category required_uploads, enforcement portal); `portal_requirements_applied`
(S23, since 1.21.0) checks the journal fields against it. Portal files are journal layer:
`wf journal switch` archives them with the rest of 08_submission/. Filling fields or uploading
needs an explicit instruction from the user in that chat; the final submit/approve/build-PDF
step is always the user's; credentials are never stored.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

REL = "08_submission/portal_requirements.json"
CACHE = "08_submission/cache/portal"
LINE_FMT = "P{:04d}"
_ITEM_RE = re.compile(
    r"(?i)\b(title page|main document|manuscript(?: file)?|blinded manuscript|anonymi[sz]ed manuscript|"
    r"figures?|tables?|supplementa(?:ry|l)(?: material| file| information)?s?|electronic supplementary material|"
    r"cover letter|response to reviewers|conflict of interest|coi(?: form)?s?|disclosure forms?|"
    r"copyright(?: form| transfer)?|licen[cs]e(?: agreement| form)?|checklist|graphical abstract|"
    r"highlights|author agreement|ethics(?: approval)?(?: document)?|data(?: set| file)?|video|"
    r"key points|permissions?)\b")
_CORE_ITEMS = re.compile(r"(?i)^(main document|manuscript(?: file)?|blinded manuscript|"
                         r"anonymi[sz]ed manuscript|figures?|tables?)$")
_TYPES_RE = re.compile(r"(?i)\b(original (?:article|research|investigation|paper)|research (?:article|paper)|"
                       r"review(?: article)?|systematic review|meta-analysis|case report|case series|"
                       r"brief report|short communication|letter(?: to the editor)?|research letter|"
                       r"editorial|commentary|perspective|technical note)\b")
_LIMIT_RE = re.compile(r"(?i)\b\d+(?:\.\d+)?\s*(?:mb|gb|kb)\b|\bmax(?:imum)?\b.*\b(?:size|files?)\b|"
                       r"\.(?:docx?|pdf|tiff?|eps|jpe?g|png|xlsx?|rtf|tex)\b|\b(?:docx?|pdf|tiff?|eps|"
                       r"jpe?g|png)\b.*\b(?:format|only|accepted|allowed)\b")
_DECL_RE = re.compile(r"(?i)\b(declare|conflicts? of interest|competing interests?|funding|ethic|consent|"
                      r"data availability|clinical trial registration|previously published|preprint|"
                      r"generative ai|large language model|artificial intelligence)\b")
_REQ_RE = re.compile(r"(?i)\(required\)|\brequired\b|\bmandatory\b|\*\s*$|^\s*\*")
_OPT_RE = re.compile(r"(?i)\boptional\b|\bif applicable\b|\bnot required\b")
_LOGIN_RE = re.compile(r"(?i)\b(password|log ?in|sign ?in|username)\b")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load(project: Path) -> dict:
    try:
        data = json.loads((Path(project) / REL).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def current(project: Path) -> dict:
    """The portal record of the current journal epoch ({} when absent or of an earlier one)."""
    from . import journalepoch
    data = load(project)
    if data and int(data.get("journal_epoch") or 1) != journalepoch.number(project):
        return {}
    return data


def _required(line: str) -> bool | None:
    if _OPT_RE.search(line):
        return False
    if _REQ_RE.search(line):
        return True
    return None


def extract(lines: list[tuple[str, str]]) -> dict:
    """Draft structure from P-numbered lines [(P0001, text)] (the agent checks it)."""
    items, types, limits, decls, fields = [], [], [], [], []
    seen_items, seen_types = set(), set()
    for pid, text in lines:
        t = text.strip()
        m = _ITEM_RE.search(t)
        if m and len(t) <= 90 and not t.endswith("?"):
            name = re.sub(r"\s+", " ", m.group(1)).strip()
            key = name.casefold().rstrip("s")
            if key not in seen_items:
                seen_items.add(key)
                items.append({"item": name, "required": _required(t), "line": pid, "text": t[:160]})
        for tm in _TYPES_RE.finditer(t) if len(t) <= 120 else ():
            k = tm.group(1).casefold()
            if k not in seen_types:
                seen_types.add(k)
                types.append({"type": tm.group(1), "line": pid})
        if _LIMIT_RE.search(t) and len(t) <= 300:
            limits.append({"text": t[:200], "line": pid})
        is_item = bool(m and len(t) <= 90 and not t.endswith("?"))
        if _DECL_RE.search(t) and (t.endswith("?") or len(t) <= 300) and not is_item:
            decls.append({"text": t[:200], "line": pid})
        if _REQ_RE.search(t) and len(t) <= 120 and not m:
            fields.append({"text": t[:160], "line": pid})
    slot = None
    if any(re.search(r"(?i)title page", i["item"]) for i in items):
        slot = True
    elif len(items) >= 2:
        slot = False
    return {"article_types": types, "upload_items": items, "title_page_slot": slot,
            "file_limits": limits, "declarations": decls, "required_fields": fields}


def ingest(project: Path, src: Path, url: str, append: bool = False) -> dict:
    from . import guideingest, journalepoch
    project, src = Path(project), Path(src)
    url = str(url or "").strip()
    if not re.match(r"(?i)^https?://", url):
        raise guideingest.IngestError("--url 必须是投稿系统页面的完整网址（https://...）")
    if not src.is_file():
        raise guideingest.IngestError(f"找不到文件 {src}")
    data = src.read_bytes()
    ftype, lines, meta = guideingest.read_capture(src, data)
    text = "\n".join(lines)
    why = guideingest.challenge(text, "portal")
    words = len(re.findall(r"[A-Za-z\u4e00-\u9fff]+", text))
    if not why and _LOGIN_RE.search(text) and words < 80:
        why = "登录页"
    if why:
        raise guideingest.IngestError(guideingest.CHALLENGE_ZH.format(why=why))
    ep = journalepoch.number(project)
    rec = current(project) if append else {}
    if append and not rec:
        raise guideingest.IngestError("--append 只用于同一投稿系统的后续步骤页面：先导入第一页")
    sha = hashlib.sha256(data).hexdigest()
    cache = project / CACHE
    cache.mkdir(parents=True, exist_ok=True)
    day = _now()[:10]
    suffix = {"snapshot": ".yml", "json": ".json", "jsonstr": ".json", "html": ".html",
              "pdf": ".pdf"}.get(ftype, ".txt")
    name = f"{day}_portal_{sha[:10]}{suffix}"
    (cache / name).write_bytes(data)
    numbered = list(rec.get("lines") or [])
    start = len(numbered) + 1
    for i, ln in enumerate(lines, start):
        numbered.append(f"{LINE_FMT.format(i)}  {ln}")
    final_url = str(meta.get("url") or "").strip()
    captures = list(rec.get("captures") or [])
    captures.append({"url": url, "final_url": final_url if final_url.startswith("http") else url,
                     "title": str(meta.get("title") or ""), "file": f"cache/portal/{name}",
                     "sha256": sha, "format": ftype, "method": "browser",
                     "captured_at": guideingest._captured_at(src, meta), "ingested_at": _now(),
                     "lines": [LINE_FMT.format(start), LINE_FMT.format(len(numbered))]})
    pairs = [(ln[:5], ln[7:]) for ln in numbered]
    out = {"schema": 1, "source": "portal", "journal_epoch": ep,
           "journal": journalepoch.target_name(project), "read_at": day,
           "note": "Read from the submission system (nothing changed there). Draft extraction: "
                   "check each item against its P-line; feed target_journal.json required_uploads "
                   "and title_page.placement from it.",
           "captures": captures, **extract(pairs), "lines": numbered}
    p = project / REL
    p.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    from .revision import record_derived
    record_derived(project, [p, cache / name])
    try:  # 1.22.0 (J3): the next paper to this journal starts with these requirements
        cache_store(project, out)
    except (OSError, SystemExit):
        pass
    return out


# ------------------------------------------------------------------ 1.22.0 (J3) reconciliation
RULE_ZH = ("核对规则：上传项、必填项、文件类型与大小以投稿系统为准；稿件格式以投稿指南为准（除非投稿"
           "系统另有规定）。")


def _cache_file(project: Path) -> Path:
    from . import journalspec, packagefolders, paths
    label = packagefolders.journal_label(journalspec.load(project))
    return paths.user_home() / "portal_cache" / f"{label}.json"


def cache_store(project: Path, rec: dict) -> Path:
    """User-level cache per journal (dated); never holds credentials (captures are page text)."""
    f = _cache_file(project)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"journal": rec.get("journal"), "cached_at": _now(), "record": rec},
                            indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return f


def cached(project: Path) -> dict | None:
    try:
        data = json.loads(_cache_file(project).read_text(encoding="utf-8"))
    except (OSError, ValueError, SystemExit):
        return None
    return data if isinstance(data, dict) and isinstance(data.get("record"), dict) else None


def use_cache(project: Path) -> dict:
    """Start this paper's portal record from the user-level cache of the same journal."""
    from . import journalepoch
    c = cached(project)
    if not c:
        raise ValueError("没有这本期刊的投稿系统缓存（只有读取过一次投稿系统后才有）")
    rec = dict(c["record"], journal_epoch=journalepoch.number(project),
               journal=journalepoch.target_name(project), from_cache=c.get("cached_at"),
               note="From the user-level cache of an earlier paper to this journal (dated): "
                    "check it against the current submission system before relying on it.")
    p = Path(project) / REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return rec


def reconcile_zh(project: Path) -> list[str]:
    """Every difference between the portal record and the journal fields, in Chinese."""
    from . import journalspec, layout
    rec = current(project)
    if not rec:
        c = cached(project)
        return (["尚未读取投稿系统。" + (f"已有 {str(c.get('cached_at'))[:10]} 读取的同一期刊缓存："
                                     "wf portal use-cache（仍须与当前系统核对）。" if c else "")
                 + "用户不让读取时，投稿包文件夹的 UPLOAD_LIST.md 列出上传时要核对的事项。"])
    target = journalspec.load(project)
    out = [RULE_ZH]
    place = layout.title_page_placement(target, project)
    if rec.get("title_page_slot") is False and place in ("separate", "both") \
            and not journalspec.blinded(target):
        out.append(f"  - 差异：投稿系统没有题名页上传项，但 title_page.placement = {place} -> 改为 "
                   "in_manuscript（题名页放在正文首页），并从 required_uploads 删去单独题名页")
    for p in problems(project):
        m = re.search(r"requires '([^']+)' \(([^)]*)\)", p)
        if m:
            out.append(f"  - 差异：投稿系统要求上传“{m.group(1)}”（{m.group(2)}），target_journal.json "
                       "required_uploads 未列出 -> 补上（用户在系统中填写的项标 portal: true）")
    for x in rec.get("file_limits") or []:
        out.append(f"  - 核对：投稿系统文件限制“{x['text'][:80]}”（{x['line']}）-> 与 figure.formats/"
                   "max_mb 及上传文件格式一致")
    if len(out) == 1:
        out.append("  - 投稿系统与当前期刊设置没有发现差异。")
    out.append("有差异时：在展示层修订轮中改 target_journal.json/期刊副本，然后 wf rebuild；用户投稿后"
               "反馈的差异同样用 wf portal ingest + 展示层修订轮处理。")
    return out


def summary_zh(rec: dict) -> list[str]:
    if not rec:
        return []
    items = rec.get("upload_items") or []
    req = lambda i: {True: "必需", False: "可选", None: "未注明"}[i.get("required")]  # noqa: E731
    slot = {True: "有题名页上传项", False: "没有题名页上传项（题名页放在正文首页：title_page.placement "
                                        "in_manuscript）", None: "未能判断是否有题名页上传项"}[rec.get("title_page_slot")]
    out = [f"投稿系统要求（{rec.get('read_at')}，{len(rec.get('captures') or [])} 页）：{slot}"]
    if items:
        out.append("上传项：" + "；".join(f"{i['item']}（{req(i)}，{i['line']}）" for i in items[:14]))
    if rec.get("article_types"):
        out.append("文章类型：" + "、".join(t["type"] for t in rec["article_types"][:10]))
    for key, label in (("file_limits", "文件大小/格式"), ("declarations", "声明问题"),
                       ("required_fields", "必填项")):
        if rec.get(key):
            out.append(f"{label}：" + "；".join(f"{x['text'][:70]}（{x['line']}）" for x in rec[key][:6]))
    return out


def problems(project: Path) -> list[str]:
    """Journal fields that contradict the portal record (gate portal_requirements_applied)."""
    from . import journalfields, journalspec, layout
    rec = current(project)
    if not rec:
        return []
    target = journalspec.load(project)
    out = []
    place = layout.title_page_placement(target, project)
    if rec.get("title_page_slot") is False and place in ("separate", "both") \
            and not journalspec.blinded(target):
        out.append(f"the submission system has no title-page upload slot "
                   f"({REL}), but title_page.placement is {place}: put the title page on the "
                   "manuscript's first page (in_manuscript) and drop the separate title page from "
                   "required_uploads")
    listed = []
    for e in target.get("required_uploads") or []:
        if isinstance(e, str):
            listed.append(e.casefold())
        elif isinstance(e, dict):
            listed += [str(e.get("item", "")).casefold(), str(e.get("role", "")).casefold()]
    listed = [x for x in listed if x]
    pairs, _ = journalfields.required_upload_roles(target)
    roles = {r.casefold() for _i, r in pairs}
    for it in rec.get("upload_items") or []:
        name = str(it.get("item", ""))
        if it.get("required") is not True or _CORE_ITEMS.match(name):
            continue
        k = name.casefold().rstrip("s")
        role = k.replace(" ", "_")
        if role in roles or any(k in x or x.rstrip("s") in k for x in listed):
            continue
        out.append(f"the submission system requires '{name}' ({it.get('line')}) but "
                   "target_journal.json required_uploads does not list it: add it "
                   "({\"item\": ..., \"role\": ...}, or {\"item\": ..., \"portal\": true} when the "
                   "user fills it in the system)")
    return out
