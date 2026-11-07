"""1.17.0 (J5): find a journal's official author guide by ISSN, lawfully.

    wf journal lookup --issn <ISSN> [--title <t>] [--refresh]

Cascade (each network answer is cached with its date in 08_submission/cache/lookup/):
  L0 local caches: the paper's 08_submission/cache/lookup/<issn>.json and the user-level
     read-only cache %LOCALAPPDATA%/medpaper/journal_cache/<issn>.json (both dated);
  L1 DOAJ journal record: bibjson.ref.author_instructions (open-access journals);
  L2 OpenAlex source (homepage_url, host organisation, APC, is_in_doaj) and the NLM Catalog
     (homepage, current MEDLINE indexing) through tools/pubmed/eutils.py, plus the vendored
     publisher URL-template table reference/publisher_guideline_urls.json (every pattern is a
     candidate to verify at runtime, never a source);
  L3 ONE polite GET of the best candidate (clear User-Agent, timeout, no retry, no proxy); a
     real guide page is stored and ingested (guidelines_source.txt);
  L4 403 / captcha / empty page / offline: STOP and print the exact URL with instructions to save
     the page in the browser and run `wf guidelines ingest --from <file> --url <URL>`; since
     1.21.0 first the agent-side browser steps (playwright MCP: capture to .playwright-mcp/,
     ingest; a verification or login is completed by the user in the browser window).
Third-party summaries (LetPub and similar) are leads only, never a source. SCIE/JCR: the user
exports the Master Journal List page as PDF and ingests it with --kind indexing.

Tests: MEDPAPER_HTTP_FIXTURES=<dir> (fixtures.json maps URL -> {status, file, content_type})
replaces the network; MEDPAPER_OFFLINE=1 refuses every request.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

LOOKUP_DIR = "08_submission/cache/lookup"
TEMPLATES = "reference/publisher_guideline_urls.json"
UA = ("medpaper-journal-lookup/1.17 (academic manuscript preparation; one request per lookup; "
      "contact: the author running medpaper)")
ISSN_RE = re.compile(r"^\d{4}-?\d{3}[\dXx]$")
MAX_AGE_DAYS = 90
NLM = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


class Offline(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def norm_issn(issn: str) -> str:
    s = re.sub(r"[^0-9Xx]", "", str(issn or "")).upper()
    return f"{s[:4]}-{s[4:]}" if len(s) == 8 else str(issn or "").strip()


def user_cache_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    return Path(base) / "medpaper" / "journal_cache"


# ------------------------------------------------------------------ transport
def http_get(url: str, timeout: int = 20, accept: str = "*/*") -> tuple[int, str, bytes]:
    """(status, content type, body). No retry, no proxy (ProxyHandler({}))."""
    fx = os.environ.get("MEDPAPER_HTTP_FIXTURES")
    if fx:
        table = json.loads((Path(fx) / "fixtures.json").read_text(encoding="utf-8"))
        rec = table.get(url)
        if rec is None:
            raise Offline(f"no recorded response for {url}")
        body = (Path(fx) / rec["file"]).read_bytes() if rec.get("file") else b""
        return int(rec.get("status", 200)), str(rec.get("content_type", "text/html")), body
    if os.environ.get("MEDPAPER_OFFLINE") == "1":
        raise Offline("MEDPAPER_OFFLINE=1")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
    try:
        with opener.open(req, timeout=timeout) as resp:
            return resp.status, resp.headers.get("Content-Type", ""), resp.read(4_000_000)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("Content-Type", "") if exc.headers else "", b""
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise Offline(str(exc)) from exc


def _get_json(url: str) -> dict | None:
    status, _ctype, body = http_get(url, accept="application/json")
    if status != 200 or not body:
        return None
    try:
        data = json.loads(body.decode("utf-8", errors="replace"))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


# ------------------------------------------------------------------ sources
def doaj(issn: str) -> dict:
    data = _get_json(f"https://doaj.org/api/search/journals/issn%3A{issn}") or {}
    res = data.get("results") or []
    if not res:
        return {}
    bib = res[0].get("bibjson") or {}
    ref = bib.get("ref") or {}
    apc = bib.get("apc") or {}
    return {"title": bib.get("title"), "publisher": (bib.get("publisher") or {}).get("name"),
            "author_instructions": ref.get("author_instructions"),
            "homepage": ref.get("journal"), "apc": apc.get("max") or apc.get("has_apc"),
            "in_doaj": True}


def openalex(issn: str) -> dict:
    data = _get_json(f"https://api.openalex.org/sources/issn:{issn}") or {}
    if not data.get("id"):
        return {}
    return {"title": data.get("display_name"), "homepage": data.get("homepage_url"),
            "publisher": data.get("host_organization_name"), "apc_usd": data.get("apc_usd"),
            "in_doaj": data.get("is_in_doaj"), "issn": data.get("issn")}


def nlm(issn: str) -> dict:
    """NLM Catalog via the E-utilities base of tools/pubmed/eutils.py (homepage, MEDLINE)."""
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from pubmed import eutils
        base = eutils.EUTILS
    except Exception:  # noqa: BLE001 - the constant is enough
        base = NLM
    q = urllib.parse.urlencode({"db": "nlmcatalog", "term": f"{issn}[issn]", "retmode": "json"})
    found = _get_json(f"{base}/esearch.fcgi?{q}") or {}
    ids = (found.get("esearchresult") or {}).get("idlist") or []
    if not ids:
        return {}
    q = urllib.parse.urlencode({"db": "nlmcatalog", "id": ids[0], "retmode": "json"})
    summ = (_get_json(f"{base}/esummary.fcgi?{q}") or {}).get("result") or {}
    rec = summ.get(str(ids[0])) or {}
    text = json.dumps(rec)
    home = next(iter(re.findall(r"https?://[^\s\"\\]+", json.dumps(rec.get("elocationlist")
                                                                     or rec.get("elocation") or ""))),
                None)
    medline = None
    status = str(rec.get("currentindexingstatus") or "")
    if status:
        medline = status.strip().upper() in ("Y", "YES", "CURRENTLY INDEXED FOR MEDLINE")
    elif re.search(r"(?i)currently indexed for medline", text):
        medline = True
    return {"title": rec.get("titlemainlist", [{}])[0].get("title") if isinstance(
        rec.get("titlemainlist"), list) and rec.get("titlemainlist") else rec.get("title"),
            "homepage": home, "medline_current": medline, "nlm_id": rec.get("nlmuniqueid") or ids[0]}


def templates(root: Path) -> list[dict]:
    try:
        data = json.loads((root / TEMPLATES).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [t for t in data.get("publishers", []) if isinstance(t, dict)]


def template_candidates(root: Path, info: dict) -> list[dict]:
    """Candidate guide URLs from the vendored publisher table (verify at runtime)."""
    out = []
    pub = " ".join(str(info.get(k) or "") for k in ("publisher", "publisher_oa", "publisher_nlm"))
    homes = [str(h) for h in info.get("homepages", []) if h]
    for t in templates(root):
        if not (re.search(t.get("publisher_regex", r"$^"), pub, re.I)
                or any(re.search(t.get("host_regex", r"$^"), h, re.I) for h in homes)):
            continue
        for h in homes:
            m = re.search(t.get("homepage_regex", r"$^"), h, re.I)
            if not m:
                continue
            groups = {k: v for k, v in m.groupdict().items() if v}
            groups.update({f"{k}_upper": v.upper() for k, v in list(groups.items())})
            groups.setdefault("issn", info.get("issn", ""))
            groups["issn_nodash"] = str(info.get("issn", "")).replace("-", "")
            for tpl in t.get("templates", []):
                try:
                    url = tpl.format(**groups)
                except (KeyError, IndexError):
                    continue
                out.append({"url": url, "publisher": t.get("name"), "basis": "url template "
                            "(verify at runtime)"})
    seen, uniq = set(), []
    for c in out:
        if c["url"] not in seen:
            seen.add(c["url"])
            uniq.append(c)
    return uniq


# ------------------------------------------------------------------ cascade
def _fresh(rec: dict) -> bool:
    try:
        at = datetime.strptime(str(rec.get("looked_up_at", ""))[:10], "%Y-%m-%d")
    except ValueError:
        return False
    return (datetime.now() - at).days <= MAX_AGE_DAYS


def _local(project: Path, issn: str) -> tuple[dict | None, str]:
    for where, path in (("paper cache", Path(project) / LOOKUP_DIR / f"{issn}.json"),
                        ("user cache", user_cache_dir() / f"{issn}.json")):
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(rec, dict) and _fresh(rec):
            return rec, where
    return None, ""


def lookup(project: Path, root: Path, issn: str, title: str = "", refresh: bool = False,
           fetch: bool = True) -> tuple[dict, list[str]]:
    """(record, Chinese lines to print)."""
    issn = norm_issn(issn)
    if not ISSN_RE.match(issn):
        raise ValueError(f"ISSN 格式不对：{issn}（例如 1471-2482）")
    lines = [f"期刊检索 ISSN {issn}" + (f"（{title}）" if title else "")]
    rec, where = (None, "") if refresh else _local(project, issn)
    if rec:
        lines.append(f"L0 使用本地缓存（{where}，{rec.get('looked_up_at', '')[:10]}）")
    else:
        rec = {"issn": issn, "title_hint": title, "looked_up_at": _now(), "sources": {},
               "candidates": [], "offline": []}
        for name, fn in (("doaj", doaj), ("openalex", openalex), ("nlm", nlm)):
            try:
                rec["sources"][name] = fn(issn)
            except Offline as exc:
                rec["offline"].append(f"{name}: {exc}")
                rec["sources"][name] = {}
        src = rec["sources"]
        rec["title"] = next((s.get("title") for s in src.values() if s.get("title")), title)
        rec["publisher"] = src["openalex"].get("publisher") or src["doaj"].get("publisher")
        homes = [src[k].get("homepage") for k in ("doaj", "openalex", "nlm")]
        info = {"publisher": rec["publisher"], "publisher_oa": src["doaj"].get("publisher"),
                "homepages": [h for h in homes if h], "issn": issn}
        if src["doaj"].get("author_instructions"):
            rec["candidates"].append({"url": src["doaj"]["author_instructions"],
                                      "publisher": rec["publisher"],
                                      "basis": "DOAJ bibjson.ref.author_instructions"})
        rec["candidates"] += template_candidates(root, info)
        rec["medline_current"] = src["nlm"].get("medline_current")
        rec["in_doaj"] = bool(src["doaj"]) or bool(src["openalex"].get("in_doaj"))
        rec["homepage"] = next((h for h in homes if h), None)
        out = Path(project) / LOOKUP_DIR / f"{issn}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        lines.append(f"L1/L2 DOAJ {'有' if src['doaj'] else '无'}记录；OpenAlex "
                     f"{'有' if src['openalex'] else '无'}记录；NLM Catalog "
                     f"{'有' if src['nlm'] else '无'}记录（结果已带日期缓存）")
        if rec["offline"]:
            lines.append("  离线或无法连接：" + "; ".join(rec["offline"])[:300])
    lines.append(f"刊名：{rec.get('title') or '-'}；出版商：{rec.get('publisher') or '-'}；主页："
                 f"{rec.get('homepage') or '-'}")
    if rec.get("medline_current") is not None:
        lines.append("NLM：" + ("目前被 MEDLINE 收录" if rec["medline_current"] else
                               "目前未被 MEDLINE 收录") + "（补充证据，不代表 SCIE）")
    from . import cslindex  # J6: the journal's CSL from the vendored ISSN index
    hit = cslindex.lookup(root, issn)
    if hit:
        rec["csl"] = {"style_id": hit["style_id"], "parent": hit["parent"], "issn": issn}
        lines.append(f"参考文献格式（CSL 索引）：{hit['style_id']} -> 父样式 {hit['parent']}；"
                     f"写入 target_journal.json \"csl\": {{\"style_id\": \"{hit['style_id']}\", "
                     f"\"issn\": \"{issn}\"}}，并运行 .venv\\Scripts\\python.exe "
                     f"tools/refs/csl_index.py fetch --issn {issn}")
    else:
        lines.append("CSL 索引中没有这个 ISSN：在 Zotero 样式库（zotero.org/styles）按刊名查找，或用"
                     "出版商通用样式，并在 target_journal.json \"csl\" 里写明 reason")
    cands = rec.get("candidates") or []
    for c in cands[:4]:
        lines.append(f"  候选指南网址：{c['url']}（{c['basis']}）")
    if not fetch:
        return rec, lines
    if not cands:
        lines += _manual(None, rec)
        return rec, lines
    best = cands[0]["url"]
    try:
        status, ctype, body = http_get(best)
    except Offline as exc:
        lines.append(f"L3 无法联网（{str(exc)[:120]}）")
        lines += _manual(best, rec)
        return rec, lines
    from . import guideingest
    text = ""
    if status == 200 and body and "html" in ctype.casefold():
        text = "\n".join(guideingest.clean_lines(guideingest.html_text(guideingest._decode(body))))
    elif status == 200 and body[:5] == b"%PDF-":
        text = "pdf"
    if status != 200 or not text or (text != "pdf" and guideingest.blocked(text)):
        why = {403: "403 拒绝访问", 401: "需要登录", 429: "请求过多"}.get(
            status, "验证码/拦截页或空白页" if status == 200 else f"HTTP {status}")
        lines.append(f"L3 单次请求结果：{why}，按规则停止，不重试、不绕过")
        lines += _manual(best, rec)
        rec["fetch"] = {"url": best, "status": status, "at": _now(), "result": "blocked"}
        return rec, lines
    snap = Path(project) / "08_submission/cache" / ("_fetched.pdf" if text == "pdf" else "_fetched.html")
    snap.parent.mkdir(parents=True, exist_ok=True)
    snap.write_bytes(body)
    try:
        entry = guideingest.ingest(project, snap, best, rec.get("title") or "", origin="fetched")
    finally:
        snap.unlink(missing_ok=True)
    rec["fetch"] = {"url": best, "status": status, "at": _now(), "result": "ingested",
                    "file": entry["file"]}
    lines.append(f"L3 已取得官方页面并导入：{entry['lines']} 行 -> 08_submission/guidelines_source.txt"
                 f"（原文 cache/{entry['file']}，sha256 {entry['sha256'][:12]}）")
    lines.append("guidelines_extract.md 引用指南时写行号（如 L0012）；target_journal.json "
                 f"guidelines_url = {best}")
    return rec, lines


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(text or "").casefold()).strip("-")
    return s[:40] or "journal"


def browser_steps(url: str, slug: str) -> list[str]:
    """1.21.0 (B3): the agent-side browser path (playwright MCP), printed when the GET failed,
    was blocked or the page needs JavaScript. The engine itself never drives a browser."""
    cap = f".playwright-mcp/guidelines_{slug}.txt"
    return [
        "BROWSER (agent; only if a browser tool `playwright` is in your tool list - otherwise "
        "use the manual path below):",
        f"  1. browser_navigate {url}  (its page-*.yml/console-*.log land in .playwright-mcp/: "
        "scratch, never read them into the chat)",
        "  2. JS check ('Client Challenge', 'Just a moment', '请稍候'): browser_wait_for textGone "
        "<that text>, at most ~20 s. A cookie banner: click 'necessary only' only if it hides "
        "the content.",
        "  3. browser_evaluate function `() => (document.querySelector('main')||document.body)"
        f".innerText` with filename `{cap}` (never return page text into the chat; no "
        "browser_snapshot without filename)",
        f"  4. wf guidelines ingest --from {cap} --url <final URL>; a sub-page the guide refers "
        "to for required rules (article type, artwork, editorial/AI policy): capture it the same "
        "way and add --append",
        "  5. Human verification, captcha or login: STOP, ask the user (Chinese) to complete it in "
        "the browser window, continue after the reply; never solve it or type credentials. "
        "No browser window / no tool: manual path below. Done: browser_close.",
        "给用户：如果浏览器窗口出现安全验证或登录页面，请您在该窗口中完成，完成后回复我即可继续。",
    ]


def _manual(url: str | None, rec: dict) -> list[str]:
    target = url or rec.get("homepage") or "（出版商官网上该期刊的 Instructions for Authors 页面）"
    lead = browser_steps(url or rec.get("homepage") or "<official guide URL>",
                         _slug(rec.get("title") or rec.get("issn") or ""))
    return lead + [
        "L4 请用户在自己的浏览器里取得官方投稿指南（合法方式，不用登录绕过、不用第三方代理）：",
        f"  1. 打开：{target}",
        "  2. 页面完整显示后，任选其一：Ctrl+S 另存为“网页，仅 HTML”；或 Ctrl+P 打印为 PDF；"
        "或下载出版商提供的 PDF 指南/Word 模板",
        f"  3. 运行：wf guidelines ingest --from <保存的文件> --url {target if url else '<官方网址>'}",
        "  LetPub 等第三方摘要只能作线索，不能作为来源。",
        "  SCIE/JCR 证据：在 Master Journal List 打开该刊页面，打印为 PDF，运行 wf guidelines "
        "ingest --from <PDF> --url <MJL 页面网址> --kind indexing；NLM 的 MEDLINE 状态只作补充。"
        "（浏览器：用户在窗口中登录 MJL/JCR 后，文字抓取 + browser_take_screenshot 存到 "
        ".playwright-mcp/，再 --kind indexing --screenshot <png>）"]
