"""1.21.0 regression tests: the browser MCP (playwright) for web tasks - guidelines, indexing
evidence, submission-system requirements and web data captures. B1 browser scratch hygiene,
B2 ingest of browser captures (snapshot YAML, JSON strings, challenge pages, leads, --append),
B3 lookup cascade output, B4 indexing evidence + screenshot readings, B5 portal requirements,
B6 web data captures, B7 cards/steering/skill, B8 audit bundle + journal switch, release policy.
Synthetic fixtures only - no real paper, dataset, network or browser is used.
Called from tools/selftest.py.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from selftest_v1140 import _env, _envset, _gate, _out, _paper, _run, _w  # noqa: E402

SPRINGER = "https://link.springer.com/journal/228/submission-guidelines"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def run(tmp: Path, record, section, only: str = "") -> None:
    tmp.mkdir(parents=True, exist_ok=True)
    for name, fn in GROUPS:
        if not only or name in only.split():
            fn(tmp / name, record, section)


def _pin(p: Path, version: str) -> None:
    st = json.loads((p / ".wf/state.json").read_text(encoding="utf-8"))
    st["engine_pin"] = version
    (p / ".wf/state.json").write_text(json.dumps(st), encoding="utf-8")


def _snapshot_yaml(url: str = SPRINGER) -> str:
    rules = "\n".join(f"    - paragraph [ref=p{i}]: Rule {i}: manuscripts must state item {i} "
                      f"clearly in the methods section of the submitted paper." for i in range(30))
    return f"""- Page URL: {url}
- Page Title: Submission guidelines | Test Journal
- Page Snapshot:
```yaml
- generic [ref=e1]:
  - dialog "Cookie consent" [ref=e2]:
    - paragraph [ref=e3]: We use cookies to improve your experience. Accept all cookies or manage preferences.
    - button "Accept all cookies" [ref=e4] [cursor=pointer]
  - banner [ref=e5]:
    - link "Springer" [ref=e6] [cursor=pointer]:
      - /url: /
  - navigation "Journal navigation" [ref=e7]:
    - list [ref=e8]:
      - listitem [ref=e9]:
        - link "Articles menu" [ref=e10]:
          - /url: /journal/228/articles
  - main [ref=e11]:
    - heading "Submission guidelines" [level=1] [ref=e12]
    - heading "Title page" [level=2] [ref=e13]
    - list [ref=e15]:
      - listitem [ref=e16]: A concise and informative title
      - listitem [ref=e17]:
        - text: An abstract of
        - strong [ref=e18]: 150 to 250 words
    - table [ref=e19]:
      - rowgroup [ref=e20]:
        - row "Article type Words" [ref=e21]:
          - columnheader "Article type" [ref=e22]
          - columnheader "Words" [ref=e23]
        - row "Original Article 4000" [ref=e24]:
          - cell "Original Article" [ref=e25]
          - cell "4000" [ref=e26]
{rules}
    - link "Back to top" [ref=e27] [cursor=pointer]:
      - /url: "#top"
  - contentinfo [ref=e28]:
    - paragraph [ref=e29]: Footer legal notice and imprint of the publisher site
```
"""


def _jsonstr(lines: list[str]) -> str:
    return json.dumps("\n".join(lines))


# ------------------------------------------------------------------------------ B1
def run_hygiene(tmp: Path, record, section) -> None:
    from wfcore import paths, reproproof, reviewguard, revision, runner
    section("1.21.0 B1: the browser scratch folder never disturbs the paper's gates")
    p = _paper(tmp / "h", "S20_journal")
    before = revision.snapshot(p)
    guard_before = reviewguard._walk(p)
    _w(p, ".playwright-mcp/page-2026-11-07T10-00-00.yml", "- generic [ref=e1]: x\n")
    _w(p, ".playwright-mcp/console-2026-11-07T10-00-00.log", "[info] loaded\n")
    _w(p, ".playwright-mcp/guidelines_test.txt", _jsonstr(["Guide text"]))
    r = _gate(p, "no_orphans", "S20_journal")
    record("B1 no_orphans ignores .playwright-mcp/ (page dumps, console logs, captures)",
           r.ok and ".playwright-mcp" not in r.detail, r.detail)
    record("B1 browsing during an open rework round causes no drift: the revision snapshot, the "
           "review guard walk and the round's scope check skip .playwright-mcp/",
           revision.snapshot(p) == before and reviewguard._walk(p) == guard_before
           and revision.out_of_scope({"kind": "presentation", "status": "active",
                                      "allowed_files": ["08_submission/x.md"]},
                                     [".playwright-mcp/page-1.yml"]) == [])
    snap = runner.tree_snapshot(p, reproproof.SNAPSHOT_EXCLUDE)
    record("B1 reproduction snapshots and nested-paper scans skip it",
           not any(k.startswith(".playwright-mcp") for k in snap) and paths.nested_papers(p) == []
           and paths.skipped_prefixes(p)[-1] == ".playwright-mcp/")
    dry = _run(p, "tools/wf.py", "clean")
    app = _run(p, "tools/wf.py", "clean", "--apply")
    record("B1 wf clean lists the browser files as scratch and --apply deletes the folder",
           dry.returncode == 0 and "del  .playwright-mcp/guidelines_test.txt" in _out(dry)
           and "??   .playwright-mcp" not in _out(dry) and app.returncode == 0
           and not (p / ".playwright-mcp").exists(), _out(dry)[-400:])
    from wfcore import adapters
    steer = dict(adapters.paper_adapters(ROOT, p))[".kiro/steering/medpaper-pipeline.md"]
    record("B1/B7 the paper adapters know the folder; the guard hook still matches only write and "
           "discovery tools (no browser or read tools)",
           ".playwright-mcp/" in steer and "browser_close" in steer
           and "browser" not in adapters.GUARD_MATCHER and "read_file" not in adapters.GUARD_MATCHER)


# ------------------------------------------------------------------------------ B2
def run_ingest(tmp: Path, record, section) -> None:
    from wfcore import guideingest
    section("1.21.0 B2: browser captures become clean, line-numbered official sources")
    p = _paper(tmp / "g", "S20_journal")
    snap = _w(p, ".playwright-mcp/page-2026-11-07T10-00-00.yml", _snapshot_yaml())
    r = _run(p, "tools/wf.py", "guidelines", "ingest", "--from", snap, "--url", SPRINGER)
    src = (p / guideingest.SOURCE).read_text(encoding="utf-8") if (p / guideingest.SOURCE).is_file() else ""
    e = guideingest.load_index(p)[-1] if guideingest.load_index(p) else {}
    record("B2 a Playwright snapshot YAML keeps headings, list items and table rows as text and "
           "drops [ref]/[cursor] attributes, /url lines, cookie dialog, navigation, footer and "
           "'Back to top'",
           r.returncode == 0 and "L0001  # Submission guidelines" in src and "## Title page" in src
           and "- An abstract of 150 to 250 words" in src and "Original Article | 4000" in src
           and "[ref=" not in src and "/url" not in src and "cookies" not in src
           and "Articles menu" not in src and "Back to top" not in src and "imprint" not in src,
           _out(r)[-300:] + src[:600])
    record("B2 cache/index.json records method browser, final URL, page title, capture time and "
           "sha256 of the original capture",
           e.get("method") == "browser" and e.get("final_url") == SPRINGER
           and e.get("title", "").startswith("Submission guidelines") and e.get("captured_at")
           and len(e.get("sha256", "")) == 64 and (p / guideingest.CACHE / e["file"]).read_text(
               encoding="utf-8") == snap.read_text(encoding="utf-8"), json.dumps(e)[:300])
    n1 = len(guideingest.source_lines(p))
    art = _w(p, ".playwright-mcp/guidelines_artwork.txt", _jsonstr(
        ["Artwork and Illustrations Guidelines", "Back to top"]
        + [f"Figure rule {i}: supply each figure as a separate TIFF file at 300 dpi or more for "
           f"halftone images in the electronic submission." for i in range(20)]))
    a = _run(p, "tools/wf.py", "guidelines", "ingest", "--from", art, "--append", "--url",
             "https://link.springer.com/journal/228/artwork-guidelines")
    lines = guideingest.source_lines(p)
    src = (p / guideingest.SOURCE).read_text(encoding="utf-8")
    record("B2 a browser_evaluate capture saved as a JSON-encoded string is decoded; --append "
           "adds the sub-page as its own block, line numbers continue, each block keeps its URL",
           a.returncode == 0 and src.count("== source S") == 2 and "appended page" in src
           and "artwork-guidelines" in src and lines.get(n1 + 1) == "Artwork and Illustrations Guidelines"
           and max(lines) == len(lines) and "Back to top" not in src, _out(a)[-300:])
    ch = _w(p, ".playwright-mcp/guidelines_wiley.txt", _jsonstr(
        ["请稍候…", "正在进行安全验证", "bpspubs.onlinelibrary.wiley.com 需要先检查您的连接的安全性"]))
    c = _run(p, "tools/wf.py", "guidelines", "ingest", "--from", ch, "--url",
             "https://bpspubs.onlinelibrary.wiley.com/hub/journal/13652125/author-guidelines")
    cc = _w(p, ".playwright-mcp/page-cc.yml", '- heading "Client Challenge" [level=1] [ref=e1]\n'
                                              '- paragraph [ref=e2]: JavaScript is disabled.\n')
    c2 = _run(p, "tools/wf.py", "guidelines", "ingest", "--from", cc, "--url", SPRINGER)
    record("B2 challenge pages ('请稍候 / 正在进行安全验证', 'Client Challenge') are refused with a "
           "Chinese message: wait, or ask the user to complete it in the browser window",
           c.returncode == 2 and "浏览器窗口" in _out(c) and "不要尝试解验证码" in _out(c)
           and c2.returncode == 2 and "Client Challenge" in _out(c2)
           and len(guideingest.source_lines(p)) == len(lines), _out(c)[-300:] + _out(c2)[-200:])
    lead = _w(p, ".playwright-mcp/guidelines_letpub.txt", _jsonstr(
        [f"Summary line {i} of a third-party journal information page about word limits." for i in range(30)]))
    ld = _run(p, "tools/wf.py", "guidelines", "ingest", "--from", lead, "--url",
              "https://www.letpub.com.cn/index.php?journalid=1")
    idx = guideingest.load_index(p)
    record("B2 a page outside the official domains (publisher URL table, journal homepage from "
           "lookup) is stored as a lead, never as a source; a Wiley society subdomain is official",
           ld.returncode == 0 and "线索" in _out(ld) and idx[-1]["kind"] == "lead"
           and len(guideingest.source_lines(p)) == len(lines)
           and guideingest.is_official(p, "https://bpspubs.onlinelibrary.wiley.com/hub/journal/x")
           and not guideingest.is_official(p, "https://www.letpub.com.cn/x"), _out(ld)[-300:])
    q = _paper(tmp / "noappend", "S20_journal")
    art2 = _w(q, ".playwright-mcp/guidelines_artwork.txt", art.read_text(encoding="utf-8"))
    na = _run(q, "tools/wf.py", "guidelines", "ingest", "--from", art2, "--append", "--url",
              "https://link.springer.com/journal/228/artwork-guidelines")
    record("B2 --append needs a main guide page first", na.returncode == 2
           and "先导入主指南页" in _out(na), _out(na)[-200:])


# ------------------------------------------------------------------------------ B3
def run_lookup(tmp: Path, record, section) -> None:
    from selftest_v1170 import _fixtures, _nlm_urls
    from wfcore import guideingest
    section("1.21.0 B3: a blocked lookup prints the browser steps, then the manual fallback")
    q = _paper(tmp / "blocked", "S20_journal")
    home = "https://www.sciencedirect.com/journal/journal-of-tests"
    tpl = home + "/publish/guide-for-authors"
    fx = _fixtures(tmp / "fx_403", {
        "https://doaj.org/api/search/journals/issn%3A1234-5679": (200, {"results": []}, "application/json"),
        "https://api.openalex.org/sources/issn:1234-5679": (200, {
            "id": "https://openalex.org/S2", "display_name": "Journal of Tests", "homepage_url": home,
            "host_organization_name": "Elsevier BV", "is_in_doaj": False}, "application/json"),
        **_nlm_urls("1234-5679", None), tpl: (403, b"", "text/html")})
    r = _run(q, "tools/wf.py", "journal", "lookup", "--issn", "1234-5679",
             env=_env(q, MEDPAPER_HTTP_FIXTURES=fx, LOCALAPPDATA=tmp / "lad"))
    o = _out(r)
    record("B3 403 -> agent block (navigate, wait for the JS check <= ~20 s, evaluate main text "
           "with filename, ingest with --url, --append for sub-pages, stop and ask the user on "
           "verification/login, browser_close) + one Chinese line for the user + the 1.17 manual path",
           r.returncode == 0 and f"browser_navigate {tpl}" in o and "textGone" in o
           and ".playwright-mcp/guidelines_journal-of-tests.txt" in o
           and "wf guidelines ingest --from .playwright-mcp/guidelines_journal-of-tests.txt" in o
           and "--append" in o and "browser_close" in o and "请您在该窗口中完成" in o
           and f"wf guidelines ingest --from <保存的文件> --url {tpl}" in o
           and o.index("browser_navigate") < o.index("L4 请用户")
           and not (q / guideingest.SOURCE).exists(), o[-1200:])
    card = (ROOT / "pipeline/stages/S20_journal.md").read_text(encoding="utf-8")
    det = (ROOT / "reference/stage_details/S20_journal.md").read_text(encoding="utf-8")
    record("B3 the S20 card names the browser path in <= 4000 characters; the details carry the "
           "full cascade",
           "playwright" in card and "wf journal lookup" in card and "guidelines ingest" in card
           and "--append" in card and len(card) <= 4000 and "browser_wait_for" in det
           and "browser_close" in det and "lead" in det, str(len(card)))


# ------------------------------------------------------------------------------ B4
def run_indexing(tmp: Path, record, section) -> None:
    from wfcore import guideingest
    section("1.21.0 B4: MJL/JCR evidence with a screenshot; image readings confirmed once")
    p = _paper(tmp / "ix", "S20_journal")
    mjl = "https://mjl.clarivate.com/journal-profile?issn=1234-5679"
    _w(p, "08_submission/target_journal.json", {"journal": "Journal of Tests", "scie_source_url": mjl,
                                                 "jcr_quartile": "Q3"})
    r0 = _gate(p, "indexing_evidence_cited", "S20_journal")
    record("B4 counterexample: an official MJL scie_source_url without a captured page fails",
           not r0.ok and r0.blocking and "no indexing evidence" in r0.detail, r0.detail)
    cap = _w(p, ".playwright-mcp/mjl_tests.txt", _jsonstr(
        ["Journal of Tests", "ISSN 1234-5679", "Web of Science Core Collection",
         "Science Citation Index Expanded (SCIE)", "Publisher Elsevier", "Category Oncology"]))
    shot = p / ".playwright-mcp/mjl_tests.png"
    shot.write_bytes(PNG)
    r = _run(p, "tools/wf.py", "guidelines", "ingest", "--kind", "indexing", "--from", cap,
             "--screenshot", shot, "--read-from-image", "jcr_quartile=Q2", "--url", mjl)
    e = guideingest.entries(p, "indexing")[-1] if guideingest.entries(p, "indexing") else {}
    record("B4 the indexing capture and its screenshot are stored together (cache/index.json); "
           "the value read from the image is listed once for the user",
           r.returncode == 0 and e.get("screenshot") and (p / guideingest.CACHE / e["screenshot"]).read_bytes() == PNG
           and e.get("read_from_image") == {"jcr_quartile": "Q2"} and "read from image" in _out(r)
           and "confirm-image" in _out(r), _out(r)[-400:])
    r1 = _gate(p, "indexing_evidence_cited", "S20_journal")
    c = _run(p, "tools/wf.py", "guidelines", "confirm-image", "--why", "用户：核对过，JCR 分区是 Q2")
    r2 = _gate(p, "indexing_evidence_cited", "S20_journal")
    _w(p, "08_submission/target_journal.json", {"journal": "Journal of Tests", "scie_source_url": mjl,
                                                 "jcr_quartile": "Q2"})
    r3 = _gate(p, "indexing_evidence_cited", "S20_journal")
    record("B4 indexing_evidence_cited: unconfirmed reading fails -> confirm-image -> a typed "
           "field that disagrees with the reading fails -> agreeing field passes",
           not r1.ok and "not confirmed" in r1.detail and c.returncode == 0 and not r2.ok
           and "Q3" in r2.detail and r3.ok, f"{r1.detail} | {r2.detail} | {r3.detail}")
    _pin(p, "1.20.0")
    _w(p, "08_submission/target_journal.json", {"journal": "J", "scie_source_url": mjl + "&x=1"})
    r4 = _gate(p, "indexing_evidence_cited", "S20_journal")
    record("B4 a paper pinned to 1.20.0 keeps its gate set until wf migrate",
           r4.ok and "1.21.0" in r4.detail, r4.detail)


# ------------------------------------------------------------------------------ B5
PORTAL_LINES = ["Submit New Manuscript", "Step 1: Select Article Type", "Original Article", "Review",
                "Case Report", "Step 4: Attach Files", "Main Document (required)", "Figure", "Table",
                "Cover Letter (required)", "Conflict of Interest Form (required)",
                "Supplementary Material (optional)",
                "Maximum file size 50 MB; figures in TIFF or EPS format only",
                "Step 5: Additional Information", "Do you declare any competing interests?",
                "Has this manuscript been previously published?", "Funding information *"]


def run_portal(tmp: Path, record, section) -> None:
    from wfcore import compliance, layout, portal, registry
    from wfcore.checks import Ctx
    from wfcore.state import State
    section("1.21.0 B5: submission-system requirements read from the portal (on request)")
    p = _paper(tmp / "pt", "S23_package")
    _w(p, "08_submission/target_journal.json", {
        "journal": "Journal of Tests", "title_page": {"placement": "separate"},
        "required_uploads": [{"item": "Cover letter", "role": "cover_letter"}]})
    r0 = _gate(p, "portal_requirements_applied", "S23_package")
    login = _w(p, ".playwright-mcp/portal_login.txt", _jsonstr(["Editorial Manager", "Username",
                                                               "Password", "Log in"]))
    lg = _run(p, "tools/wf.py", "portal", "ingest", "--from", login, "--url",
              "https://www.editorialmanager.com/tests/default.aspx")
    cap = _w(p, ".playwright-mcp/portal_step1.txt", _jsonstr(PORTAL_LINES[:6]))
    cap2 = _w(p, ".playwright-mcp/portal_step4.txt", _jsonstr(PORTAL_LINES[6:]))
    a = _run(p, "tools/wf.py", "portal", "ingest", "--from", cap, "--url",
             "https://www.editorialmanager.com/tests/submit.aspx")
    b = _run(p, "tools/wf.py", "portal", "ingest", "--from", cap2, "--append", "--url",
             "https://www.editorialmanager.com/tests/attach.aspx")
    rec = portal.load(p)
    items = {i["item"]: i["required"] for i in rec.get("upload_items", [])}
    record("B5 nothing is required without a portal record; a login page is refused; two step "
           "pages -> portal_requirements.json (source=portal, dated, P-lines continue) with upload "
           "items, no title-page slot, limits and declaration questions",
           r0.ok and "not read" in r0.detail and lg.returncode == 2 and a.returncode == 0
           and b.returncode == 0 and rec.get("source") == "portal" and rec.get("read_at")
           and len(rec["captures"]) == 2 and rec["captures"][1]["lines"][0] == "P0007"
           and items.get("Main Document") is True and items.get("Supplementary Material") is False
           and rec["title_page_slot"] is False and any("50 MB" in x["text"] for x in rec["file_limits"])
           and any("previously published" in x["text"] for x in rec["declarations"])
           and {"Original Article", "Case Report"} <= {t["type"] for t in rec["article_types"]},
           _out(lg)[-200:] + _out(b)[-300:] + json.dumps(rec.get("upload_items"))[:300])
    r1 = _gate(p, "portal_requirements_applied", "S23_package")
    record("B5 portal_requirements_applied: a separate title page without an upload slot and a "
           "required COI form missing from required_uploads fail",
           not r1.ok and r1.blocking and "no title-page upload slot" in r1.detail
           and "Conflict of Interest" in r1.detail and "Cover Letter" not in r1.detail, r1.detail)
    _w(p, "08_submission/target_journal.json", {
        "journal": "Journal of Tests", "title_page": {"placement": "in_manuscript"},
        "required_uploads": [{"item": "Cover letter", "role": "cover_letter"},
                             {"item": "Conflict of Interest form", "portal": True}]})
    r2 = _gate(p, "portal_requirements_applied", "S23_package")
    pipe = registry.load()
    rows = compliance.build_rows(Ctx(pipe, State(p, ".wf").load(), p, pipe.stage("S23_package"), {}))
    prow = [x for x in rows if x["id"].startswith("PORTAL-")]
    dec = {d["item"]: d for d in layout.decisions(p)}
    st = _run(p, "tools/wf.py", "portal", "status")
    record("B5 fixed fields pass; the matrix gets portal rows (required_uploads / declarations, "
           "enforcement portal) for the portal to-do; the title-page decision cites the portal; "
           "wf portal status prints the Chinese summary",
           r2.ok and prow and all(x["enforcement"] == "portal" and x["portal"] for x in prow)
           and {"required_uploads", "declarations"} <= {x["category"] for x in prow}
           and "投稿系统没有题名页上传项" in dec["title_page"]["basis_zh"]
           and st.returncode == 0 and "没有题名页上传项" in _out(st), r2.detail + _out(st)[-300:])
    det = (ROOT / "reference/stage_details/S23_package.md").read_text(encoding="utf-8")
    s24 = (ROOT / "pipeline/stages/S24_package_human_review.md").read_text(encoding="utf-8")
    record("B5 the cards say: only when the user asks, read-only, stop before the final "
           "submit/approve/build-PDF step, never store credentials",
           # 1.22.0 (J3): reading the portal is a standard S24 question, asked once
           "wf portal ingest" in s24 and "ask ONCE whether to read it" in s24
           and "submit/approve/build-PDF" in det
           and "never store credentials" in det and len(s24) <= registry.CARD_MAX_CHARS)


# ------------------------------------------------------------------------------ B6
def run_data(tmp: Path, record, section) -> None:
    from wfcore import webdata
    section("1.21.0 B6: web pages that become data are dated, versioned raw sources")
    p = _paper(tmp / "d", "S04_data")
    url = "https://www.vigiaccess.org/"
    obf = _w(p, ".playwright-mcp/vigi.txt", _jsonstr(
        ["VigiAccess", "Oxali\u200bplatin", "Reported potential side effects",
         "Blood and lymphatic system disorders 1\u200b2\u200b3\u200b4", "Hepatobiliary disorders 5\u200b6\u200b7"]))
    q = "oxaliplatin; all regions; all years; MedDRA SOC"
    a = _run(p, "tools/wf.py", "data", "capture", "--from", obf, "--url", url, "--query", q,
             "--name", "vigiaccess")
    shot = p / ".playwright-mcp/vigi.png"
    shot.write_bytes(PNG)
    csv = _w(p, ".playwright-mcp/vigi_values.csv", "soc,reports\nBlood and lymphatic system disorders,1234\n")
    b = _run(p, "tools/wf.py", "data", "capture", "--from", obf, "--url", url, "--query", q,
             "--name", "vigiaccess", "--screenshot", shot, "--values-csv", csv)
    v1 = p / "02_data/raw/web/vigiaccess/v001"
    v2 = p / "02_data/raw/web/vigiaccess/v002"
    meta = json.loads((v2 / "capture.json").read_text(encoding="utf-8")) if (v2 / "capture.json").is_file() else {}
    record("B6 wf data capture stores a dated raw source with URL, query, time, method and sha256; "
           "a repeated capture of the same query is v002 (v001 untouched); obfuscated text is "
           "flagged and the screenshot reading is listed once",
           a.returncode == 0 and b.returncode == 0 and (v1 / "capture.json").is_file()
           and meta.get("query") == q and meta.get("method") == "browser" and meta.get("read_from_screenshot")
           and meta.get("obfuscated_text") and set(meta.get("files", {})) >= {"capture.txt", "screenshot.png",
                                                                            "read_from_screenshot.csv"}
           and "\u200b" not in (v2 / "capture.txt").read_text(encoding="utf-8")
           and "不要解码" in _out(a) and "read from screenshot" in _out(b), _out(a)[-300:] + _out(b)[-300:])
    r1 = _gate(p, "web_captures_traced", "S04_data")
    c = _run(p, "tools/wf.py", "data", "confirm-capture", "vigiaccess", "--note", "用户：已对照截图核对")
    r2 = _gate(p, "web_captures_traced", "S04_data")
    (v1 / "capture.txt").write_text("edited\n", encoding="utf-8")
    r3 = _gate(p, "web_captures_traced", "S04_data")
    (v1 / "capture.txt").unlink()
    nc = _gate(p, "data_not_copied", "S04_data")
    record("B6 web_captures_traced warns until the screenshot reading is verified, passes after "
           "confirm-capture, fails when a capture is edited; data_not_copied is not confused",
           not r1.ok and not r1.blocking and "verified" in r1.detail
           and c.returncode == 0 and r2.ok and not r3.ok and r3.blocking and "changed after capture" in r3.detail
           and nc.ok, f"{r1.detail} | {r2.detail} | {r3.detail} | {nc.detail}")
    with _envset(MEDPAPER_PROJECT=str(p)):
        from analysis.datasources import source_path
        sp = source_path("web:vigiaccess", "read_from_screenshot.csv")
    ls = _run(p, "tools/wf.py", "data", "list")
    s04 = (ROOT / "pipeline/stages/S04_data.md").read_text(encoding="utf-8")
    record("B6 scripts read source_path('web:<name>') (latest version); wf data list shows the "
           "capture; the S04 card has the paragraph",
           sp.resolve() == (v2 / "read_from_screenshot.csv").resolve() and "web:vigiaccess v002" in _out(ls)
           and "wf data capture" in s04 and "confirm-capture" in s04
           and len(s04) <= 4000 and webdata.latest(p, "vigiaccess") == v2, f"{sp} {_out(ls)[-300:]}")


# ------------------------------------------------------------------------------ B8
def run_switch(tmp: Path, record, section) -> None:
    from selftest_v1170 import _frozen_paper
    from wfcore import audit, guideingest, portal, webdata
    section("1.21.0 B8: audit bundle and journal switch with browser-ingested files")
    p = _frozen_paper(tmp / "sw")
    snap = _w(p, ".playwright-mcp/page-1.yml", _snapshot_yaml("https://link.springer.com/journal/9/submission-guidelines"))
    guideingest.ingest(p, snap, "https://link.springer.com/journal/9/submission-guidelines")
    cap = _w(p, ".playwright-mcp/mjl.txt", _jsonstr(["Journal A", "ISSN 1111-2222", "Science Citation "
                                                     "Index Expanded", "Web of Science Core Collection",
                                                     "Publisher Example Press", "Category Surgery Oncology"]))
    shot = p / ".playwright-mcp/mjl.png"
    shot.write_bytes(PNG)
    guideingest.ingest(p, cap, "https://mjl.clarivate.com/x", kind="indexing", screenshot=shot)
    portal.ingest(p, _w(p, ".playwright-mcp/portal.txt", _jsonstr(PORTAL_LINES)),
                  "https://www.editorialmanager.com/a/attach.aspx")
    webdata.capture(p, _w(p, ".playwright-mcp/label.txt", _jsonstr(["Drug label", "Boxed warning: hepatotoxicity"])),
                    "https://www.accessdata.fda.gov/label.pdf", "oxaliplatin label 2025", "fdalabel")
    ev = audit.evidence_files(p)
    gl = audit.guideline_files(p)
    pr = (ROOT / "tools/package_review.py").read_text(encoding="utf-8")
    idx = json.loads((p / guideingest.INDEX).read_text(encoding="utf-8"))
    record("B8 the S25 audit bundle lists browser-ingested guide sources like other originals and "
           "the evidence index (capture method), indexing capture + screenshot, portal record",
           any(x.endswith(".yml") for x in gl) and guideingest.INDEX in ev
           and "08_submission/portal_requirements.json" in ev and any(x.endswith(".png") for x in ev)
           and "evidence_files" in pr and any(e.get("method") == "browser" for e in idx["entries"]),
           str(ev) + str(gl))
    sw = _run(p, "tools/wf.py", "journal", "switch", "--to", "Journal B", "--confirm-old", "Journal A",
              "--why", "rejected after peer review: scope", "--outcome", "rejected")
    live = sorted(x.relative_to(p).as_posix() for x in (p / "08_submission").rglob("*")
                  if x.is_file() and "journal_archives" not in x.parts)
    arch = [x for x in (p / "08_submission/journal_archives").rglob("*") if x.is_file()]
    record("B8 wf journal switch archives the browser-ingested journal layer (guide captures, "
           "indexing evidence, portal record) and leaves 02_data/raw/web untouched",
           sw.returncode == 0 and not any("portal" in x or "cache/" in x for x in live)
           and any(x.name == "portal_requirements.json" for x in arch)
           and any(x.name.endswith("_screenshot.png") for x in arch)
           and (p / "02_data/raw/web/fdalabel/v001/capture.json").is_file()
           and not webdata.problems(p)[0], _out(sw)[-300:] + str(live))


# ------------------------------------------------------------------------------ B7 + release
def run_release(tmp: Path, record, section) -> None:
    from wfcore import registry
    from wfcore.state import State
    section("1.21.0 B7/release: token economy rules, one migration event, pinned papers")
    skill = (ROOT / ".kiro/skills/medpaper-pipeline/SKILL.md").read_text(encoding="utf-8")
    cli_src = (ROOT / "tools/wfcore/cli.py").read_text(encoding="utf-8")
    record("B7 SKILL.md execution economy: APIs first, snapshot only with filename, evaluate on "
           "main, never read captures into the chat, one session then browser_close, main agent "
           "browses, paywalled full text from the user; wf doctor reads no MCP configuration",
           all(s in skill for s in ("playwright", "APIs first", "browser_snapshot", "filename",
                                    "browser_evaluate", "browser_close", "subagents get the ingested",
                                    "ask the user for the PDF"))
           and "mcp.json" not in cli_src)
    q = tmp / "mig"
    q.mkdir(parents=True, exist_ok=True)
    st = State(q, ".wf").create("medpaper", "1.20.0", "S23_package")
    before = sorted(x.name for x in q.rglob("*"))
    st.migrate_pipeline("1.21.0", [s.id for s in registry.load().stages])
    st.migrate_pipeline("1.21.0", [s.id for s in registry.load().stages])
    after = sorted(x.name for x in q.rglob("*"))
    notes = [e for e in st.data.get("events", []) if e.get("kind") == "requirements_changed"
             and str(e.get("detail", "")).startswith("1.21.0")]
    gates = {(s.id, g.get("check")): g for s in registry.load().stages for g in s.gate}
    cards = {c.stem: len(c.read_text(encoding="utf-8")) for c in (ROOT / "pipeline/stages").glob("S*.md")}
    record("R pipeline 1.21.0; a 1.20.0 paper gets one 1.21.0 event and stays pinned (no paper "
           "file touched); the three new gates carry since 1.21.0; every card <= limit",
           registry.load().meta.get("version") in ("1.21.0", "1.22.0") and len(notes) == 1
           and st.engine_pin == "1.20.0" and before == after
           and all(gates[k].get("since") == "1.21.0" for k in (
               ("S04_data", "web_captures_traced"), ("S20_journal", "indexing_evidence_cited"),
               ("S23_package", "portal_requirements_applied")))
           and max(cards.values()) <= registry.CARD_MAX_CHARS, f"{len(notes)} {max(cards.values())}")
    p = _paper(tmp / "pinned", "S04_data")
    _pin(p, "1.20.0")
    _w(p, "02_data/raw/web/x/v001/capture.json", {"name": "x", "version": 1, "url": "", "query": "",
                                                   "files": {"gone.txt": "0" * 64}})
    r = _gate(p, "web_captures_traced", "S04_data")
    record("R a paper pinned to 1.20.0 does not get web_captures_traced until wf migrate --yes",
           r.ok and "1.21.0" in r.detail, r.detail)


GROUPS = [("hygiene", run_hygiene), ("ingest", run_ingest), ("lookup", run_lookup),
          ("indexing", run_indexing), ("portal", run_portal), ("data", run_data),
          ("switch", run_switch), ("release", run_release)]

if __name__ == "__main__":
    import tempfile
    results = []

    def _rec(name, ok, detail=""):
        results.append(ok)
        print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"\n     {detail}"))
        return ok
    with tempfile.TemporaryDirectory() as t:
        run(Path(t), _rec, lambda s: print(f"== {s}"), " ".join(sys.argv[1:]))
    print(f"{sum(results)}/{len(results)}")
