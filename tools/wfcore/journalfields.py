"""1.18.0 (K3): typed journal fields that were prose only, now built and checked.

target_journal.json (absent field = the journal is silent = no check):

    "abstract":     {"structured": true, "headings": ["Background", "Methods", "Results",
                     "Conclusions"], "per_section_words": 100 | {"Results": 120},
                     "total_words": 250}
    "title_page":   {"elements": ["title", "running title", "authors", "affiliations",
                     "corresponding author", "orcid", "word count"], "title_max_chars": 150,
                     "title_max_words": 25, "running_title_max_chars": 50}
    "running_title_position": "title_page" | "manuscript"
    "highlights" or "key_points": {"required": true, "n_min": 3, "n_max": 5, "max_chars": 85,
                     "label": "Highlights", "placement": "separate_file" | "manuscript"}
    "cover_letter": {"must_state": ["not under consideration elsewhere", "all authors approved"]}
    "required_uploads": ["title_page", {"item": "ICMJE COI forms", "role": "coi_forms"},
                         {"item": "copyright form", "portal": true}]
    "figure":       {"formats": ["TIFF", "EPS"], "min_dpi": 300, "max_mb": 10, "colour": "RGB"}
    "orcid_required": true | "corresponding" | "portal"

Each check returns (status, detail) with status PASS | FAIL | CANNOT_ASSESS | N.A.; the S23
gate journal_fields_met and the compliance matrix (compliance.py) use the same functions.
Highlights in a separate file: write 08_submission/manuscript/highlights.md (a '# <label>'
heading and one '- ' bullet per point) and build it like any text upload:
build_docx.py build --kind statements --input <highlights.md> --output
08_submission/bundle/highlights.docx (manifest role "highlights").
"""
from __future__ import annotations

import json
import re
from pathlib import Path

PASS, FAIL, CANNOT, NA = "PASS", "FAIL", "CANNOT_ASSESS", "N.A."
MANIFEST = "08_submission/bundle/manifest.json"
HIGHLIGHTS = "08_submission/manuscript/highlights.md"
COVER = "08_submission/cover_letter.md"
ORCID_RE = re.compile(r"\b(\d{4}-\d{4}-\d{4}-\d{3}[\dX])\b")
RUNNING_RE = re.compile(r"(?im)^[\W_]*(?:running title|running head|short title)[\W_]*[:\uff1a]"
                        r"\s*\**\s*(.+?)\s*\**\s*$")
UPLOAD_ROLES = {
    "manuscript": "manuscript", "main document": "manuscript", "main manuscript": "manuscript",
    "blinded manuscript": "manuscript", "title page": "title_page", "title_page": "title_page",
    "cover letter": "cover_letter", "cover_letter": "cover_letter", "figures": "figures",
    "figure files": "figures", "tables": "tables", "table files": "tables",
    "checklist": "checklist", "reporting checklist": "checklist", "highlights": "highlights",
    "key points": "highlights", "key messages": "highlights", "graphical abstract": "graphical_abstract",
    "supplementary material": "supplementary", "supplementary": "supplementary",
    "supplementary information": "supplementary", "electronic supplementary material": "supplementary",
    "coi forms": "coi_forms", "icmje forms": "coi_forms", "icmje coi forms": "coi_forms",
    "conflict of interest forms": "coi_forms", "copyright form": "copyright_form",
    "author form": "author_form", "statements": "statements",
}
STOP = {"that", "this", "with", "from", "have", "been", "were", "will", "your", "their", "there",
        "which", "should", "must", "into", "about", "under", "other", "also", "than", "they",
        "please", "statement", "state", "letter", "cover", "include", "including"}


def _json(path: Path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _read(path: Path) -> str:
    return Path(path).read_text(encoding="utf-8", errors="replace") if Path(path).is_file() else ""


def _src(project: Path, rel: str) -> Path:
    from . import scifreeze
    return Path(project) / scifreeze.resolve(Path(project), rel)


def _int(v) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) and v > 0 else None


def _manifest_items(project: Path) -> list[dict]:
    data = _json(Path(project) / MANIFEST)
    return [i for i in (data or {}).get("items", []) if isinstance(i, dict)] if isinstance(data, dict) else []


def _key(s: str) -> str:
    return re.sub(r"\s+", " ", str(s).strip().strip("*").rstrip(":.").strip()).casefold()


# ------------------------------------------------------------------ abstract
def abstract_parts(text: str) -> tuple[list[str], dict[str, str], str]:
    """(headings in order, heading -> body, whole abstract without Keywords) of the Abstract."""
    from . import journalspec
    body = journalspec.markdown_sections(text).get("abstract", "")
    body = re.sub(r"(?mi)^\s*\**keywords\**\s*[:\uff1a].*$", "", body)
    heads, parts, cur = [], {}, None
    pat = re.compile(r"^\s*(?:#{2,6}[ \t]+(?P<h>[^\n#]+?)[ \t]*(?:\n|$)|\*\*(?P<b>[^*\n]{2,40}?)[:.]?\*\*[:.]?\s*"
                     r"|(?P<p>[A-Z][A-Za-z /&-]{2,40}):\s+)")
    for para in re.split(r"\n\s*\n|\n(?=\s*#{2,6}\s)", body):
        m = pat.match(para)
        if m:
            cur = (m.group("h") or m.group("b") or m.group("p")).strip().rstrip(":.")
            heads.append(cur)
            parts[cur] = parts.get(cur, "") + " " + para[m.end():]
        elif cur:
            parts[cur] += " " + para
    return heads, parts, body


def abstract_check(project: Path, target: dict):
    from . import journalspec
    spec = target.get("abstract")
    if not isinstance(spec, dict):
        return NA, "journal silent on abstract structure"
    text = _read(_src(project, "07_manuscript/full_manuscript.md"))
    if not text:
        return CANNOT, "journal copy full_manuscript.md missing"
    heads, parts, body = abstract_parts(text)
    if not body.strip():
        return FAIL, "no '# Abstract' section in the journal copy"
    probs = []
    want = [str(h) for h in spec.get("headings") or [] if str(h).strip()]
    if spec.get("structured") is True or want:
        if want and [_key(h) for h in heads] != [_key(h) for h in want]:
            probs.append(f"abstract headings {heads or 'none'} must be exactly {want} in this order")
        elif not heads:
            probs.append("the journal wants a structured abstract (headed sections)")
    elif spec.get("structured") is False and heads:
        probs.append(f"the journal wants an unstructured abstract; found headings {heads}")
    per = spec.get("per_section_words")
    for h in heads:
        cap = _int(per) if not isinstance(per, dict) else _int(
            {_key(k): v for k, v in per.items()}.get(_key(h)))
        n = journalspec.word_count(parts.get(h, ""))
        if cap and n > cap:
            probs.append(f"abstract section '{h}' has {n} words > {cap}")
    total = _int(spec.get("total_words"))
    n_all = journalspec.word_count(body)
    if total and n_all > total:
        probs.append(f"abstract has {n_all} words > {total}")
    return (FAIL, "; ".join(probs)) if probs else (
        PASS, f"abstract {n_all} words" + (f", headings {heads}" if heads else ", unstructured"))


# ------------------------------------------------------------------ title page
def _title(text: str) -> str:
    m = re.search(r"(?m)^#\s+(.+)$", text) or re.search(r"(?im)^\W*title\W*[:\uff1a]\s*(.+)$", text)
    if m:
        return m.group(1).strip().strip("*")
    return next((ln.strip().strip("*") for ln in text.splitlines() if ln.strip()), "")


def _authors(project: Path) -> list[dict]:
    info = _json(Path(project) / "00_input/author_info.json") or {}
    return [a for a in (info.get("authors") or []) if isinstance(a, dict)] if isinstance(info, dict) else []


ELEMENTS = {
    "running title": RUNNING_RE, "short title": RUNNING_RE, "running head": RUNNING_RE,
    "corresponding author": re.compile(r"(?i)correspond"),
    "orcid": ORCID_RE, "email": re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),
    "word count": re.compile(r"(?i)word\s*count|words?\s*[:\uff1a]\s*\d"),
    "affiliations": re.compile(r"(?i)affiliat|department|university|hospital"),
    "conflict of interest": re.compile(r"(?i)conflicts? of interest|competing interests?"),
    "competing interests": re.compile(r"(?i)conflicts? of interest|competing interests?"),
    "number of figures": re.compile(r"(?i)(figures?|tables?)\s*[:\uff1a]\s*\d|number of (figures|tables)"),
    "number of tables": re.compile(r"(?i)(figures?|tables?)\s*[:\uff1a]\s*\d|number of (figures|tables)"),
    "reference count": re.compile(r"(?i)references?\s*[:\uff1a]\s*\d|number of references"),
    "acknowledgements": re.compile(r"(?i)acknowledg"),
}


def title_page_check(project: Path, target: dict):
    from . import journalspec
    spec = target.get("title_page")
    if not isinstance(spec, dict):
        return NA, "journal silent on title-page elements"
    text = _read(_src(project, "07_manuscript/title_page.md"))
    if not text:
        return CANNOT, "title_page.md missing"
    probs = []
    low = text.casefold()
    for el in [str(e) for e in spec.get("elements") or [] if str(e).strip()]:
        k = _key(el)
        if k == "title":
            ok = bool(_title(text))
        elif k in ("authors", "author names", "author list"):
            names = [str(a.get("name", "")).strip() for a in _authors(project)]
            ok = any(n and n.casefold() in low for n in names) if names else "author" in low
        elif k in ELEMENTS:
            ok = bool(ELEMENTS[k].search(text))
        else:
            ok = k in low
        if not ok:
            probs.append(f"title page lacks '{el}'")
    title = _title(text)
    for key, n, unit in (("title_max_chars", len(title), "characters"),
                         ("title_max_words", journalspec.word_count(title), "words")):
        cap = _int(spec.get(key))
        if cap and n > cap:
            probs.append(f"title has {n} {unit} > {cap}")
    return (FAIL, "; ".join(probs)) if probs else (PASS, f"title page: {len(spec.get('elements') or [])} "
                                                         f"element(s) present; title {len(title)} chars")


def running_title_check(project: Path, target: dict):
    from . import journalspec
    spec = target.get("title_page") if isinstance(target.get("title_page"), dict) else {}
    cap = _int(spec.get("running_title_max_chars"))
    if not cap and "running_title_position" not in target:
        return NA, "journal silent on the running title"
    tp = _read(_src(project, "07_manuscript/title_page.md"))
    m = RUNNING_RE.search(tp)
    pos = journalspec.running_title_position(target)
    probs = []
    if pos == "manuscript":
        ms = _read(_src(project, "07_manuscript/full_manuscript.md"))
        front = re.split(r"(?mi)^#\s+abstract\s*$", ms, maxsplit=1)[0]
        docx = _docx_text(project, "manuscript")
        if not RUNNING_RE.search(front) and not RUNNING_RE.search(docx):
            probs.append("the journal wants the running title on the manuscript's first page "
                         "(running_title_position manuscript; the builder inserts the title-page "
                         "running title, so rebuild)")
        m = m or RUNNING_RE.search(front) or RUNNING_RE.search(docx)
    elif not m:
        probs.append("no 'Running title:' line on the title page")
    if m and cap and len(m.group(1)) > cap:
        probs.append(f"running title has {len(m.group(1))} characters > {cap}")
    return (FAIL, "; ".join(probs)) if probs else (
        PASS, f"running title ({len(m.group(1)) if m else 0} chars) on the {pos.replace('_', ' ')}")


def _docx_text(project: Path, role: str) -> str:
    import zipfile
    for i in _manifest_items(project):
        f = Path(project) / str(i.get("file", ""))
        if str(i.get("role", "")).casefold() == role and f.suffix.casefold() == ".docx" and f.is_file():
            try:
                with zipfile.ZipFile(f) as z:
                    xml = z.read("word/document.xml").decode("utf-8", "replace")
            except (OSError, KeyError, zipfile.BadZipFile):
                return ""
            return "\n".join(re.sub(r"<[^>]+>", "", p) for p in re.findall(r"<w:p[ >].*?</w:p>", xml, re.S))
    return ""


def running_title_value(project: Path) -> str:
    m = RUNNING_RE.search(_read(_src(project, "07_manuscript/title_page.md")))
    return m.group(1).strip() if m else ""


# ------------------------------------------------------------------ highlights / key points
def highlights_spec(target: dict) -> dict | None:
    for key in ("highlights", "key_points"):
        if isinstance(target.get(key), dict):
            return {"label": "Highlights" if key == "highlights" else "Key Points", **target[key]}
    return None


def highlights_check(project: Path, target: dict):
    spec = highlights_spec(target)
    if not spec or spec.get("required") is not True:
        return NA, "highlights/key points not required"
    label = str(spec.get("label") or "Highlights")
    if spec.get("placement") == "manuscript":
        text = _read(_src(project, "07_manuscript/full_manuscript.md"))
        m = re.search(rf"(?ims)^#{{1,2}}\s*{re.escape(label)}\s*$(.*?)(?=^#{{1,2}}\s|\Z)", text)
        where = f"'{label}' section of the journal copy"
    else:
        text = _read(Path(project) / HIGHLIGHTS)
        m = re.search(rf"(?ims)^#{{1,2}}\s*{re.escape(label)}\s*$(.*)", text)
        where = HIGHLIGHTS
    if not m:
        return FAIL, (f"the journal requires {label}: write {where} with a '# {label}' heading and "
                      "one '- ' bullet per point")
    bullets = [b.strip() for b in re.findall(r"(?m)^\s*[-*\u2022]\s+(.+)$", m.group(1))]
    probs = []
    lo, hi, cap = _int(spec.get("n_min")), _int(spec.get("n_max")), _int(spec.get("max_chars"))
    if (lo and len(bullets) < lo) or (hi and len(bullets) > hi):
        probs.append(f"{label}: {len(bullets)} point(s), the journal wants {lo or 1}-{hi or '...'}")
    long = [f"#{i} {len(b)} chars" for i, b in enumerate(bullets, 1) if cap and len(b) > cap]
    if long:
        probs.append(f"{label} longer than {cap} characters (spaces included): " + ", ".join(long))
    if spec.get("placement") != "manuscript":
        items = [i for i in _manifest_items(project) if str(i.get("role", "")).casefold() == "highlights"]
        if not items:
            probs.append("no manifest upload with role 'highlights' (build_docx.py build --kind "
                         "statements --input 08_submission/manuscript/highlights.md --output "
                         "08_submission/bundle/highlights.docx)")
        for i in items:
            f = Path(project) / str(i.get("file", ""))
            if f.suffix.casefold() == ".docx" and not _built_from(project, f, HIGHLIGHTS):
                probs.append(f"{f.name} is not a current build of {HIGHLIGHTS} (rebuild it)")
    return (FAIL, "; ".join(probs)) if probs else (PASS, f"{len(bullets)} {label.lower()} within limits")


def _built_from(project: Path, output: Path, source_rel: str) -> bool:
    from . import rebuild
    for rec in rebuild.receipts(project):
        if (Path(project) / rec["output"]).resolve() == output.resolve():
            srcs = [s.get("path") for s in rec.get("sources", [])]
            return source_rel in srcs and not rebuild.stale(project, rec)
    return False


# ------------------------------------------------------------------ cover letter
def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.casefold())


def cover_letter_items(project: Path, target: dict) -> list[tuple[str, str | None]]:
    """[(item, matching sentence or None)] for cover_letter.must_state."""
    spec = target.get("cover_letter") if isinstance(target.get("cover_letter"), dict) else {}
    text = _read(Path(project) / COVER)
    sentences = [s.strip() for s in re.split(r"(?<=[.!?;])\s+|\n+", text) if s.strip()]
    out = []
    for item in [str(x) for x in spec.get("must_state") or [] if str(x).strip()]:
        if _key(item) in text.casefold():
            hit = next((s for s in sentences if _key(item) in s.casefold()), item)
            out.append((item, hit))
            continue
        keys = [k for k in _tokens(item) if len(k) >= 4 and k not in STOP] or _tokens(item)
        best, score = None, 0.0
        for s in sentences:
            toks = _tokens(s)
            got = sum(1 for k in keys if any(t.startswith(k[:5]) for t in toks))
            if keys and got / len(keys) > score:
                best, score = s, got / len(keys)
        out.append((item, best if score >= 0.6 else None))
    return out


def cover_letter_check(project: Path, target: dict):
    spec = target.get("cover_letter")
    if not isinstance(spec, dict) or not spec.get("must_state"):
        return NA, "journal silent on cover-letter content"
    if not (Path(project) / COVER).is_file():
        return CANNOT, "08_submission/cover_letter.md missing"
    items = cover_letter_items(project, target)
    miss = [i for i, s in items if s is None]
    if miss:
        return FAIL, "cover letter does not state: " + "; ".join(miss)
    return PASS, "; ".join(f"'{i}' -> \"{s[:80]}\"" for i, s in items)


# ------------------------------------------------------------------ uploads
def required_upload_roles(target: dict) -> tuple[list[tuple[str, str]], list[str]]:
    """([(item, manifest role)], problems) of required_uploads (portal items skipped)."""
    out, probs = [], []
    for e in target.get("required_uploads") or []:
        if isinstance(e, dict):
            if e.get("portal"):
                continue
            item, role = str(e.get("item") or e.get("role") or ""), str(e.get("role") or "")
        else:
            item, role = str(e), ""
        role = role or UPLOAD_ROLES.get(_key(item), "")
        if not role:
            probs.append(f"required upload '{item}': map it to a manifest role "
                         "({\"item\": ..., \"role\": ...}) or mark it {\"portal\": true}")
        else:
            out.append((item, role))
    return out, probs


def uploads_check(project: Path, target: dict):
    if not target.get("required_uploads"):
        return NA, "journal lists no required uploads"
    if not (Path(project) / MANIFEST).is_file():
        return CANNOT, "bundle manifest missing"
    pairs, probs = required_upload_roles(target)
    roles = {str(i.get("role", "")).casefold() for i in _manifest_items(project)}
    probs += [f"required upload '{item}' (role {role}) is not in the bundle manifest"
              for item, role in pairs if role.casefold() not in roles]
    return (FAIL, "; ".join(probs)) if probs else (PASS, f"{len(pairs)} required upload(s) in the manifest")


# ------------------------------------------------------------------ figures
FORMAT_EXT = {"tiff": (".tif", ".tiff"), "tif": (".tif", ".tiff"), "eps": (".eps",),
              "pdf": (".pdf",), "png": (".png",), "jpeg": (".jpg", ".jpeg"), "jpg": (".jpg", ".jpeg")}
COLOUR_MODES = {"rgb": ("RGB", "RGBA"), "cmyk": ("CMYK",), "grayscale": ("L", "LA", "1", "I;16"),
                "greyscale": ("L", "LA", "1", "I;16")}


def figure_spec(target: dict) -> dict:
    spec = target.get("figure") if isinstance(target.get("figure"), dict) else {}
    return spec


def figure_check(project: Path, target: dict):
    spec = figure_spec(target)
    if not spec:
        return NA, "journal silent on figure file format"
    figs = [Path(project) / str(i.get("file", "")) for i in _manifest_items(project)
            if str(i.get("role", "")).casefold() == "figures"
            and Path(str(i.get("file", ""))).suffix.casefold() in (".tif", ".tiff", ".eps", ".pdf",
                                                                  ".png", ".jpg", ".jpeg")]
    if not figs:
        return CANNOT, "no separate figure files in the bundle (separate_display_files off?)"
    fmts = [str(f).casefold() for f in spec.get("formats") or []]
    exts = {e for f in fmts for e in FORMAT_EXT.get(f, ())}
    dpi, mb = _int(spec.get("min_dpi")), spec.get("max_mb")
    colour = str(spec.get("colour") or spec.get("color") or "").casefold()
    probs = []
    for f in figs:
        if not f.is_file():
            probs.append(f"{f.name} missing")
            continue
        if exts and f.suffix.casefold() not in exts:
            probs.append(f"{f.name}: format not in {spec.get('formats')}")
        if isinstance(mb, (int, float)) and not isinstance(mb, bool) and f.stat().st_size > mb * 1024 * 1024:
            probs.append(f"{f.name}: {f.stat().st_size / 1048576:.1f} MB > {mb} MB")
        if f.suffix.casefold() in (".tif", ".tiff", ".png", ".jpg", ".jpeg"):
            try:
                from PIL import Image
                with Image.open(f) as im:
                    have, mode = float(im.info.get("dpi", (0, 0))[0] or 0), im.mode
            except Exception:  # noqa: BLE001 - unreadable image is a finding
                probs.append(f"{f.name}: not a readable image")
                continue
            if dpi and have and have + 0.5 < dpi:
                probs.append(f"{f.name}: {have:.0f} dpi < {dpi}")
            if colour in COLOUR_MODES and mode not in COLOUR_MODES[colour]:
                probs.append(f"{f.name}: colour mode {mode}, the journal wants {colour.upper()}")
    return (FAIL, "; ".join(probs)) if probs else (PASS, f"{len(figs)} figure file(s) meet "
                                                         f"{json.dumps(spec, ensure_ascii=False)}")


# ------------------------------------------------------------------ ORCID
def orcid_valid(value: str) -> bool:
    digits = str(value).replace("-", "")
    if not re.fullmatch(r"\d{15}[\dX]", digits):
        return False
    total = 0
    for ch in digits[:-1]:
        total = (total + int(ch)) * 2
    check = (12 - total % 11) % 11
    return digits[-1] == ("X" if check == 10 else str(check))


def orcid_check(project: Path, target: dict):
    mode = target.get("orcid_required")
    if mode in (None, False, ""):
        return NA, "journal silent on ORCID"
    authors = _authors(project)
    if not authors:
        return CANNOT, "00_input/author_info.json has no authors"
    info = _json(Path(project) / "00_input/author_info.json") or {}
    corr = info.get("corresponding") if isinstance(info, dict) else None
    corr_name = str(corr.get("name", "") if isinstance(corr, dict) else corr or "").casefold()
    need = [a for a in authors if mode != "corresponding" or a.get("corresponding") is True
            or (corr_name and str(a.get("name", "")).casefold() == corr_name)]
    probs = []
    tp = _read(_src(project, "07_manuscript/title_page.md"))
    for a in need:
        o = str(a.get("orcid", "")).strip().replace("https://orcid.org/", "")
        if not o:
            probs.append(f"{a.get('name', '?')}: no ORCID in author_info.json")
        elif not orcid_valid(o):
            probs.append(f"{a.get('name', '?')}: ORCID {o} is not valid (checksum)")
        elif mode != "portal" and o not in tp:
            probs.append(f"{a.get('name', '?')}: ORCID {o} not on the title page")
    return (FAIL, "; ".join(probs)) if probs else (PASS, f"{len(need)} author ORCID(s) valid"
                                                         + ("" if mode == "portal" else " and on the title page"))


CHECKS = {"abstract": abstract_check, "title_page": title_page_check,
          "running_title": running_title_check, "highlights": highlights_check,
          "cover_letter": cover_letter_check, "required_uploads": uploads_check,
          "figure": figure_check, "orcid": orcid_check}


def run_all(project: Path, target: dict | None = None) -> list[tuple[str, str, str]]:
    """[(name, status, detail)] for every typed field the journal sets."""
    from . import journalspec
    target = journalspec.load(project) if target is None else target
    out = []
    for name, fn in CHECKS.items():
        status, detail = fn(Path(project), target)
        if status != NA:
            out.append((name, status, detail))
    return out
