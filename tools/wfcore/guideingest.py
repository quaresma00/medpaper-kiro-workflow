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
                        r"cf-challenge|just a moment\.\.\.|enable javascript and cookies")


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


def detect(path: Path, data: bytes) -> str:
    suf = path.suffix.casefold()
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
        body.append(f"== source S{i}: {url} | {e.get('title') or '-'} | {e['file']} | sha256 "
                    f"{e['sha256'][:12]} | {e['ingested_at'][:10]} ==")
        txt = Path(project) / CACHE / e["text"]
        for ln in (txt.read_text(encoding="utf-8").splitlines() if txt.is_file() else []):
            n += 1
            body.append(f"L{n:04d}  {ln}")
    out = project / SOURCE
    out.write_text("\n".join(head + body) + "\n", encoding="utf-8")
    return out


def ingest(project: Path, src: Path, url: str, title: str = "", kind: str = "guidelines",
           origin: str = "user_file") -> dict:
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
    ftype = detect(src, data)
    lines = clean_lines(to_text(src, data, ftype))
    text = "\n".join(lines)
    if kind == "guidelines" and blocked(text):
        raise IngestError("这个文件看起来是验证码/拦截页或空白页，而不是投稿指南正文；请在浏览器中"
                          "完整打开页面后再另存为网页（仅 HTML）或打印为 PDF")
    sha = hashlib.sha256(data).hexdigest()
    suffix = {"pdf": ".pdf", "docx": ".docx", "mhtml": ".mhtml", "html": ".html"}.get(ftype, ".txt")
    stem = f"{_today()}_{kind}_{sha[:10]}"
    cache = project / CACHE
    cache.mkdir(parents=True, exist_ok=True)
    (cache / f"{stem}{suffix}").write_bytes(data)
    (cache / f"{stem}.txt").write_text(text + "\n", encoding="utf-8")
    entry = {"file": f"{stem}{suffix}", "text": f"{stem}.txt", "sha256": sha, "url": url,
             "title": str(title or "").strip(), "kind": kind, "format": ftype, "origin": origin,
             "original_name": src.name, "ingested_at": _now(), "lines": len(lines),
             "epoch": journalepoch.number(project)}
    idx = [e for e in load_index(project) if e.get("sha256") != sha or e.get("kind") != kind]
    idx.append(entry)
    _save_index(project, idx)
    if kind == "guidelines":
        write_source(project)
    from .revision import record_derived
    record_derived(project, [cache / entry["file"]])
    return entry
