"""1.17.0 (J4): import an official author guide the user saved, as the guideline source.

Publisher pages often answer an automated GET with 403 or a captcha. The lawful route is the
user's own browser: "save page as" (HTML only, complete, or a single-file web archive), print to
PDF, the publisher's PDF guide or a Word template, then

    wf guidelines ingest --from <file> --url <official URL> [--title <t>] [--kind indexing]

The original is stored in 08_submission/cache/ (sha256, date, URL, epoch in cache/index.json),
converted to clean text (HTML: trafilatura when installed, else the stdlib parser keeping
headings and list items; PDF: pypdf, pdfplumber when installed; DOCX: stdlib zip/XML; TXT) and
written to 08_submission/guidelines_source.txt with stable line numbers L0001... Since 1.17.0
guidelines_extract.md cites these line numbers (guidelines_sourced). --kind indexing keeps an
exported Master Journal List / JCR page as SCIE/JCR evidence without adding it to the guide.
"""
from __future__ import annotations

import email
import hashlib
import html
import json
import re
import zipfile
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

CACHE = "08_submission/cache"
INDEX = "08_submission/cache/index.json"
SOURCE = "08_submission/guidelines_source.txt"
KINDS = ("guidelines", "indexing")
LINE_RE = re.compile(r"^L(\d{4,5})  (.*)$")
CITE_RE = re.compile(r"\bL(\d{4,5})(?:\s*[-\u2013]\s*L?(\d{4,5}))?\b")
CAPTCHA_RE = re.compile(r"(?i)captcha|are you a robot|verify you are human|access denied|"
                        r"cf-challenge|just a moment\.\.\.|enable javascript and cookies|"
                        r"client challenge|security verification|checking your browser|"
                        r"attention required|403 forbidden|请稍候|正在进行安全验证|安全验证|人机验证")
# 1.21.0 (B2): browser captures (tools of the `playwright` MCP server; the engine never calls them)
BROWSER_FORMATS = ("snapshot", "json", "jsonstr")
CHALLENGE_ZH = ("这是验证/拦截页面（{why}），不是正文：先等几秒让页面自动完成检查（browser_wait_for "
                "textGone，最多约 20 秒）后重新抓取；仍需人工验证或登录时，请用户在浏览器窗口中完成，"
                "用户回复后再抓取。不要尝试解验证码、不要输入账号密码")
BOILERPLATE_EXACT = {"back to top", "skip to main content", "skip to content", "skip to main navigation",
                     "skip to navigation", "accept all cookies", "accept all", "reject all",
                     "necessary only", "only necessary", "cookie settings", "manage cookies",
                     "cookie preferences", "close", "menu", "search", "share", "print", "top"}
_COOKIE_RE = re.compile(r"(?i)\bcookies?\b.*\b(accept|consent|preferences|we use|privacy|manage|"
                        r"settings)\b|\b(accept|consent|we use)\b.*\bcookies?\b")


class IngestError(ValueError):
    pass


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ------------------------------------------------------------------ conversion
class _Text(HTMLParser):
    BLOCK = {"p", "div", "section", "article", "br", "tr", "table", "ul", "ol", "dl", "dt", "dd",
             "blockquote", "pre", "header", "footer", "main", "figure", "figcaption", "td", "th"}
    SKIP = {"script", "style", "noscript", "svg", "template", "iframe", "head", "nav", "button",
            "form", "select"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self.buf: list[str] = []
        self.skip = 0
        self.prefix = ""
        self.title = ""
        self._in_title = False

    def _flush(self):
        text = re.sub(r"\s+", " ", "".join(self.buf)).strip()
        if text:
            self.lines.append(self.prefix + text)
        self.buf, self.prefix = [], ""

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
        if tag in self.SKIP:
            self.skip += 1
            return
        if re.fullmatch(r"h[1-6]", tag):
            self._flush()
            self.prefix = "#" * int(tag[1]) + " "
        elif tag == "li":
            self._flush()
            self.prefix = "- "
        elif tag in self.BLOCK:
            self._flush()

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
            return
        if re.fullmatch(r"h[1-6]", tag) or tag == "li" or tag in self.BLOCK:
            self._flush()

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if not self.skip:
            self.buf.append(data)


def html_text(raw: str) -> str:
    try:
        import trafilatura  # optional (Apache-2.0); keeps headings
        out = trafilatura.extract(raw, output_format="markdown", include_tables=True,
                                  include_links=False, favor_recall=True)
        if out and len(out.strip()) >= 200:
            return out
    except Exception:  # noqa: BLE001 - not installed or failed: the stdlib parser below
        pass
    parser = _Text()
    parser.feed(raw)
    parser.close()
    parser._flush()
    return "\n".join(parser.lines)


def _mhtml_html(data: bytes) -> str:
    msg = email.message_from_bytes(data)
    for part in msg.walk():
        if part.get_content_type() == "text/html":
            payload = part.get_payload(decode=True) or b""
            return payload.decode(part.get_content_charset() or "utf-8", errors="replace")
    raise IngestError("网页归档文件里没有 HTML 部分")


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    m = re.search(rb"charset=[\"']?([\w-]+)", data[:4000])
    return data.decode(m.group(1).decode() if m else "latin-1", errors="replace")


def pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader
        return "\n".join((pg.extract_text() or "") for pg in PdfReader(str(path)).pages)
    except ImportError:
        pass
    try:
        import pdfplumber  # optional (MIT)
        with pdfplumber.open(str(path)) as pdf:
            return "\n".join((pg.extract_text() or "") for pg in pdf.pages)
    except ImportError as exc:
        raise IngestError("读取 PDF 需要 pypdf（引擎 .venv 已带）；请用 .venv 的 Python 运行") from exc


def docx_text(path: Path) -> str:
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    import xml.etree.ElementTree as ET
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    lines = []
    for p in root.iter(f"{ns}p"):
        text = "".join(t.text or "" for t in p.iter(f"{ns}t")).strip()
        if not text:
            continue
        style = p.find(f"{ns}pPr/{ns}pStyle")
        val = style.get(f"{ns}val", "") if style is not None else ""
        m = re.search(r"(?i)heading\s*(\d)", val)
        lines.append(("#" * int(m.group(1)) + " " if m else "- " if p.find(f"{ns}pPr/{ns}numPr")
                      is not None else "") + text)
    return "\n".join(lines)


# ------------------------------------------------------------------ browser captures (1.21.0 B2)
_NODE_RE = re.compile(r'^(?P<ind>\s*)-\s(?P<body>.*)$')
_ROLE_RE = re.compile(r'^(?P<role>/?[A-Za-z][\w-]*)(?:\s+"(?P<name>(?:[^"\\]|\\.)*)")?'
                      r'(?P<attrs>(?:\s*\[[^\]]*\])*)(?:\s*:\s?(?P<value>.*))?$')
_DROP = {"banner", "navigation", "contentinfo", "button", "img", "image", "searchbox", "textbox",
         "combobox", "checkbox", "radio", "switch", "slider", "spinbutton", "/url", "/placeholder",
         "separator", "progressbar", "menu", "menubar", "menuitem", "tablist", "tab", "dialog",
         "alertdialog", "option", "listbox", "iframe", "tooltip", "status", "alert"}
_LINE = {"paragraph", "listitem", "term", "definition", "caption", "blockquote", "note",
         "figcaption", "cell", "gridcell", "columnheader", "rowheader"}
_STRUCT = _LINE | {"heading", "row", "list", "table", "rowgroup", "grid", "article", "region",
                   "section", "main", "group", "document", "complementary", "form", "figure"}


class _Node:
    __slots__ = ("role", "name", "value", "level", "children")

    def __init__(self, role="", name="", value="", level=0):
        self.role, self.name, self.value, self.level, self.children = role, name, value, level, []


def _unq(s: str) -> str:
    s = (s or "").strip()
    if len(s) >= 2 and s[0] == s[-1] == '"':
        try:
            return str(json.loads(s))
        except ValueError:
            return s[1:-1]
    if len(s) >= 2 and s[0] == s[-1] == "'":
        return s[1:-1].replace("''", "'")
    return s


def _parse_snapshot(raw: str) -> tuple[_Node, dict]:
    root, meta = _Node("root"), {}
    stack: list[tuple[int, _Node]] = [(-1, root)]
    for line in raw.replace("\r", "").split("\n"):
        m = re.match(r"^\s*-?\s*Page (URL|Title|Snapshot):\s*(.*)$", line)
        if m:
            if m.group(1) != "Snapshot":
                meta["url" if m.group(1) == "URL" else "title"] = m.group(2).strip()
            continue
        if line.strip().startswith("```") or not line.strip():
            continue
        m = _NODE_RE.match(line)
        if not m:  # a continuation of the previous scalar
            if stack[-1][1] is not root:
                stack[-1][1].value = (stack[-1][1].value + " " + line.strip()).strip()
            continue
        ind, body = len(m.group("ind")), m.group("body").strip()
        if body[:1] in "\"'":
            node = _Node("text", value=_unq(body.rstrip(":")))
        else:
            r = _ROLE_RE.match(body)
            if not r:
                node = _Node("text", value=body)
            else:
                lv = re.search(r"\[level=(\d)\]", r.group("attrs") or "")
                name = r.group("name") or ""
                try:
                    name = json.loads(f'"{name}"') if name else ""
                except ValueError:
                    pass
                node = _Node(r.group("role"), name, _unq(r.group("value") or ""),
                             int(lv.group(1)) if lv else 0)
        while stack and stack[-1][0] >= ind:
            stack.pop()
        stack[-1][1].children.append(node)
        stack.append((ind, node))
    return root, meta


def _dropped(n: _Node) -> bool:
    if n.role in _DROP:
        return True
    return n.role in ("region", "complementary", "generic", "group") and bool(
        re.search(r"(?i)cookie|consent", n.name or ""))


def _has_struct(n: _Node) -> bool:
    return any((c.role in _STRUCT or _has_struct(c)) for c in n.children if not _dropped(c))


def _inline(n: _Node) -> str:
    parts = [n.value] if n.value else []
    for c in n.children:
        if _dropped(c) or c.role in _STRUCT:
            continue
        t = _inline(c)
        if t:
            parts.append(t)
    if not parts and n.role in ("link", "text", "cell", "gridcell", "columnheader", "rowheader",
                                "listitem", "paragraph", "term", "definition", "caption",
                                "strong", "emphasis", "code"):
        parts = [n.name] if n.name else []
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def _render(n: _Node, out: list[str]) -> None:
    if _dropped(n):
        return
    if n.role == "heading":
        text = n.name or _inline(n)
        if text:
            out.append("#" * max(1, min(n.level or 2, 6)) + " " + text)
        return
    if n.role == "row":
        cells = [_inline(c) for c in n.children if c.role in ("cell", "gridcell", "columnheader",
                                                              "rowheader")]
        cells = [c for c in cells if c]
        if cells:
            out.append(" | ".join(cells))
        return
    if n.role in _LINE:
        text = _inline(n)
        if text:
            out.append(("- " if n.role == "listitem" else "") + text)
        for c in n.children:
            if c.role in _STRUCT and not _dropped(c):
                _render(c, out)
        return
    if n.role not in _STRUCT and n.role != "root" and not _has_struct(n):
        text = _inline(n)
        if text:
            out.append(text)
        return
    if n.value:
        out.append(n.value)
    for c in n.children:
        _render(c, out)


def snapshot_text(raw: str) -> tuple[str, dict]:
    """Playwright accessibility snapshot (YAML) -> clean text, keeping the heading hierarchy;
    [ref=..]/[cursor=..]/[box=..] attributes and /url lines are dropped."""
    root, meta = _parse_snapshot(raw)
    out: list[str] = []
    _render(root, out)
    return "\n".join(out), meta


def json_capture(raw: str) -> tuple[str, dict]:
    """browser_evaluate saved with `filename`: a JSON-encoded string (one line with \\n escapes)
    or an object {text|innerText, url, title, captured_at}."""
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise IngestError(f"无法解析浏览器保存的 JSON：{exc}") from exc
    meta: dict = {}
    if isinstance(data, dict):
        for k in ("url", "title", "captured_at"):
            if isinstance(data.get(k), str):
                meta[k] = data[k]
        data = data.get("text") or data.get("innerText") or data.get("content") or ""
    if isinstance(data, list):
        data = "\n".join(str(x) for x in data)
    if not isinstance(data, str):
        raise IngestError("浏览器保存的 JSON 里没有页面文字（应为字符串或含 text 的对象）")
    return data, meta


def strip_boilerplate(lines: list[str]) -> list[str]:
    """Conservative: UI words alone on a line, cookie/consent banners, short copyright footers."""
    out = []
    for ln in lines:
        key = re.sub(r"[\s\u2191\u2303^>|\-:]+$", "", re.sub(r"^[\s\u2191\u2303^<|\-]+", "", ln))
        if key.casefold() in BOILERPLATE_EXACT:
            continue
        if len(ln) < 500 and _COOKIE_RE.search(ln):
            continue
        if len(ln) < 200 and re.match(r"^(?:©|\(c\)\s|copyright\s*©)", ln, re.I):
            continue
        out.append(ln)
    return out


def challenge(text: str, kind: str = "guidelines") -> str | None:
    """Why a capture is a verification/login/blocked page instead of content (None = fine)."""
    words = len(re.findall(r"[A-Za-z\u4e00-\u9fff]+", text))
    m = CAPTCHA_RE.search(text)
    if m and words < 600:
        return m.group(0)
    floor = {"guidelines": 120, "indexing": 15, "portal": 10, "data": 3}.get(kind, 120)
    if words < floor:
        return f"文字太少（{words} 个词）"
    return None


def detect(path: Path, data: bytes) -> str:
    suf = path.suffix.casefold()
    if suf in (".yml", ".yaml"):
        return "snapshot"
    if suf == ".json":
        return "json"
    if suf in (".txt", "") and data.lstrip()[:1] == b'"':
        try:
            if isinstance(json.loads(_decode(data)), str):
                return "jsonstr"
        except ValueError:
            pass
    if data[:5] == b"%PDF-" or suf == ".pdf":
        return "pdf"
    if data[:2] == b"PK" or suf == ".docx":
        return "docx"
    if suf in (".mht", ".mhtml") or re.match(rb"(?is)\s*(MIME-Version|From:|Content-Type: multipart)",
                                              data[:300]):
        return "mhtml"
    if suf in (".html", ".htm", ".xhtml", ".shtml", ".aspx", ".php") or re.match(
            rb"(?is)\s*(<!doctype html|<html|<\?xml)", data[:500]):
        return "html"
    if suf in (".txt", ".md", ""):
        return "text"
    raise IngestError(f"不支持的文件类型 {suf}：请另存为网页（仅 HTML）、打印为 PDF，或用 .docx/.txt")


def read_capture(path: Path, data: bytes) -> tuple[str, list[str], dict]:
    """(format, clean lines, meta {url, title, captured_at}) of any accepted file. Browser
    captures also lose conservative boilerplate (cookie banners, 'Back to top', footers)."""
    ftype = detect(path, data)
    meta: dict = {}
    if ftype == "snapshot":
        text, meta = snapshot_text(_decode(data))
    elif ftype in ("json", "jsonstr"):
        text, meta = json_capture(_decode(data))
    else:
        text = to_text(path, data, ftype)
        if ftype == "html":
            m = re.search(r"(?is)<title[^>]*>(.*?)</title>", _decode(data)[:20000])
            if m:
                meta["title"] = html.unescape(re.sub(r"\s+", " ", m.group(1))).strip()
    lines = clean_lines(text)
    if ftype in BROWSER_FORMATS or _in_browser_dir(path):
        lines = clean_lines("\n".join(strip_boilerplate(lines)))
    return ftype, lines, meta


def _in_browser_dir(path: Path) -> bool:
    return any(part.casefold() == ".playwright-mcp" for part in Path(path).resolve().parts)


def to_text(path: Path, data: bytes, kind: str) -> str:
    if kind == "pdf":
        return pdf_text(path)
    if kind == "docx":
        return docx_text(path)
    if kind == "mhtml":
        return html_text(_mhtml_html(data))
    if kind == "html":
        return html_text(_decode(data))
    return _decode(data)


def clean_lines(text: str) -> list[str]:
    out, prev = [], None
    for ln in html.unescape(text).replace("\r", "\n").split("\n"):
        ln = re.sub(r"[ \t\u00a0\u2009\u202f]+", " ", ln).strip()
        if not ln or ln == prev:
            continue
        out.append(ln)
        prev = ln
    return out


def blocked(text: str) -> bool:
    """A bot-protection page or an empty shell instead of the guide."""
    words = len(re.findall(r"[A-Za-z\u4e00-\u9fff]+", text))
    return words < 120 or (bool(CAPTCHA_RE.search(text)) and words < 600)


# ------------------------------------------------------------------ cache index
def load_index(project: Path) -> list[dict]:
    try:
        data = json.loads((Path(project) / INDEX).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [e for e in data.get("entries", [])] if isinstance(data, dict) else []


def _save_index(project: Path, entries: list[dict]) -> None:
    p = Path(project) / INDEX
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"schema": 1, "entries": entries}, indent=2, ensure_ascii=False) + "\n",
                 encoding="utf-8")


def entries(project: Path, kind: str = "guidelines", epoch: int | None = None) -> list[dict]:
    return [e for e in load_index(project) if e.get("kind") == kind
            and (epoch is None or int(e.get("epoch") or 1) == epoch)]


def source_lines(project: Path) -> dict[int, str]:
    p = Path(project) / SOURCE
    out = {}
    for ln in (p.read_text(encoding="utf-8", errors="replace").splitlines() if p.is_file() else []):
        m = LINE_RE.match(ln)
        if m:
            out[int(m.group(1))] = m.group(2)
    return out


def source_epoch(project: Path) -> int | None:
    p = Path(project) / SOURCE
    head = p.read_text(encoding="utf-8", errors="replace")[:600] if p.is_file() else ""
    m = re.search(r"journal epoch (\d+)", head)
    return int(m.group(1)) if m else None


def cited_lines(text: str) -> list[int]:
    out = []
    for m in CITE_RE.finditer(text or ""):
        a = int(m.group(1))
        b = int(m.group(2)) if m.group(2) else a
        out.extend(range(a, min(b, a + 400) + 1))
    return out


def write_source(project: Path) -> Path:
    """guidelines_source.txt from this epoch's guideline entries (latest file per URL, in
    first-ingest order); line numbers continue across sources."""
    from . import journalepoch
    project = Path(project)
    ep = journalepoch.number(project)
    latest: dict[str, dict] = {}
    order: list[str] = []
    for e in entries(project, "guidelines", ep):
        if e["url"] not in latest:
            order.append(e["url"])
        latest[e["url"]] = e
    head = [f"# guidelines_source.txt - journal epoch {ep}: {journalepoch.target_name(project)}",
            "# Official author instructions as ingested (wf guidelines ingest / wf journal lookup).",
            "# Cite lines as L0001 in guidelines_extract.md. Do not edit by hand."]
    body, n = [], 0
    for i, url in enumerate(order, 1):
        e = latest[url]
        extra = (" | appended page" if e.get("append") else "") + \
            (" | browser capture" if e.get("method") == "browser" else "")
        body.append(f"== source S{i}: {url} | {e.get('title') or '-'} | {e['file']} | sha256 "
                    f"{e['sha256'][:12]} | {e['ingested_at'][:10]}{extra} ==")
        txt = Path(project) / CACHE / e["text"]
        for ln in (txt.read_text(encoding="utf-8").splitlines() if txt.is_file() else []):
            n += 1
            body.append(f"L{n:04d}  {ln}")
    out = project / SOURCE
    out.write_text("\n".join(head + body) + "\n", encoding="utf-8")
    return out


# ------------------------------------------------------------------ official domains (1.21.0 B2)
_SLD = {"co", "com", "ac", "org", "net", "gov", "edu", "or", "ne", "go"}
INDEXING_DOMAINS = ("clarivate.com", "nih.gov", "doaj.org")


def reg_domain(url_or_host: str) -> str:
    """'https://bpspubs.onlinelibrary.wiley.com/x' -> 'wiley.com' (eTLD+1 heuristic)."""
    s = str(url_or_host or "").strip()
    host = re.sub(r"(?i)^[a-z][a-z0-9+.-]*://", "", s).split("/")[0].split(":")[0].strip(".").lower()
    parts = [p for p in host.split(".") if p]
    if len(parts) >= 3 and len(parts[-1]) == 2 and parts[-2] in _SLD:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def official_domains(project: Path, kind: str = "guidelines") -> set[str]:
    """Publisher URL-template table domains + the journal homepage/candidate domains from
    `wf journal lookup` (+ Clarivate/NLM/DOAJ for indexing evidence)."""
    from . import journallookup, paths
    doms: set[str] = set()
    for t in journallookup.templates(paths.repo_root()):
        for u in t.get("templates", []):
            doms.add(reg_domain(re.sub(r"\{[^}]*\}", "x", str(u))))
        for alt in str(t.get("host_regex", "")).split("|"):
            alt = alt.replace("\\.", ".").strip("^$()")
            if re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", alt):
                doms.add(reg_domain(alt))
    for p in sorted((Path(project) / journallookup.LOOKUP_DIR).glob("*.json")):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        urls = [rec.get("homepage")] + [c.get("url") for c in rec.get("candidates") or []
                                        if isinstance(c, dict)]
        for s in (rec.get("sources") or {}).values():
            if isinstance(s, dict):
                urls += [s.get("homepage"), s.get("author_instructions")]
        doms.update(reg_domain(u) for u in urls if isinstance(u, str) and u.startswith("http"))
    if kind == "indexing":
        doms.update(INDEXING_DOMAINS)
    doms.discard("")
    return doms


def is_official(project: Path, url: str, kind: str = "guidelines") -> bool:
    return reg_domain(url) in official_domains(project, kind)


def _captured_at(src: Path, meta: dict) -> str:
    raw = str(meta.get("captured_at") or "").strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}", raw):
        return raw
    return datetime.fromtimestamp(src.stat().st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ingest(project: Path, src: Path, url: str, title: str = "", kind: str = "guidelines",
           origin: str = "user_file", *, append: bool = False, screenshot: Path | None = None,
           read_from_image: dict | None = None, method: str | None = None) -> dict:
    """Store a guide/indexing capture. 1.21.0 (B2/B4): browser captures (snapshot YAML,
    browser_evaluate JSON strings, text from .playwright-mcp/) are cleaned, challenge pages
    refused, a non-official domain is kept as a lead (kind 'lead', never a source); --append
    adds a sub-page block; --screenshot keeps the image with indexing evidence."""
    from . import journalepoch
    project, src = Path(project), Path(src)
    url = str(url or "").strip()
    if kind not in KINDS:
        raise IngestError(f"--kind 只能是 {'|'.join(KINDS)}")
    if not re.match(r"(?i)^https?://", url):
        raise IngestError("--url 必须是官方页面的完整网址（https://...）")
    if not src.is_file():
        raise IngestError(f"找不到文件 {src}")
    data = src.read_bytes()
    ftype, lines, meta = read_capture(src, data)
    browser = method == "browser" or ftype in BROWSER_FORMATS or _in_browser_dir(src)
    text = "\n".join(lines)
    if browser:
        why = challenge(text, kind)
        if why:
            raise IngestError(CHALLENGE_ZH.format(why=why))
    elif kind == "guidelines" and blocked(text):
        raise IngestError("这个文件看起来是验证码/拦截页或空白页，而不是投稿指南正文；请在浏览器中"
                          "完整打开页面后再另存为网页（仅 HTML）或打印为 PDF")
    final_url = str(meta.get("url") or "").strip()
    final_url = final_url if final_url.startswith("http") else url
    ep = journalepoch.number(project)
    if append and kind == "guidelines" and not entries(project, "guidelines", ep):
        raise IngestError("--append 只用于补充页面（文章类型、编辑政策、图片要求等）：先导入主指南页")
    stored_kind = kind
    if browser and not (is_official(project, final_url, kind) and is_official(project, url, kind)):
        stored_kind = "lead"
    shot = Path(screenshot) if screenshot else None
    if shot is not None and not shot.is_file():
        raise IngestError(f"找不到截图 {shot}")
    sha = hashlib.sha256(data).hexdigest()
    suffix = {"pdf": ".pdf", "docx": ".docx", "mhtml": ".mhtml", "html": ".html",
              "snapshot": ".yml", "json": ".json", "jsonstr": ".json"}.get(ftype, ".txt")
    stem = f"{_today()}_{stored_kind}_{sha[:10]}"
    cache = project / CACHE
    cache.mkdir(parents=True, exist_ok=True)
    original = cache / f"{stem}{suffix}"
    if suffix == ".txt" and browser:  # the clean text gets <stem>.txt; keep the original apart
        original = cache / f"{stem}_original.txt"
    original.write_bytes(data)
    (cache / f"{stem}.txt").write_text(text + "\n", encoding="utf-8")
    entry = {"file": original.name, "text": f"{stem}.txt", "sha256": sha, "url": url,
             "title": str(title or meta.get("title") or "").strip(), "kind": stored_kind,
             "format": ftype, "origin": origin, "original_name": src.name,
             "ingested_at": _now(), "lines": len(lines), "epoch": ep}
    if browser:
        entry.update({"method": "browser", "final_url": final_url,
                      "captured_at": _captured_at(src, meta)})
    if append:
        entry["append"] = True
    if stored_kind == "lead":
        entry["lead_for"] = kind
    if shot is not None:
        sdata = shot.read_bytes()
        sname = f"{stem}_screenshot{shot.suffix.casefold() or '.png'}"
        (cache / sname).write_bytes(sdata)
        entry.update({"screenshot": sname, "screenshot_sha256": hashlib.sha256(sdata).hexdigest()})
    if read_from_image:
        entry["read_from_image"] = {str(k): str(v) for k, v in read_from_image.items()}
        entry["image_values_confirmed"] = None
    idx = [e for e in load_index(project) if e.get("sha256") != sha or e.get("kind") != stored_kind]
    idx.append(entry)
    _save_index(project, idx)
    if stored_kind == "guidelines":
        write_source(project)
    from .revision import record_derived
    record_derived(project, [cache / entry["file"]])
    return entry


def unconfirmed_image_values(project: Path, epoch: int | None = None) -> list[dict]:
    """Indexing/policy values read only from a screenshot that the user has not confirmed."""
    return [e for e in load_index(project) if e.get("read_from_image")
            and not e.get("image_values_confirmed")
            and (epoch is None or int(e.get("epoch") or 1) == epoch)]


def confirm_image_values(project: Path, words: str) -> list[dict]:
    from . import journalepoch
    ep = journalepoch.number(project)
    idx = load_index(project)
    done = []
    for e in idx:
        if e.get("read_from_image") and not e.get("image_values_confirmed") \
                and int(e.get("epoch") or 1) == ep:
            e["image_values_confirmed"] = {"words": words, "at": _now()}
            done.append(e)
    if done:
        _save_index(project, idx)
    return done
