"""1.9.0 (#24): a legal end state when the author edits the upload copy by hand.

Some journal requirements cannot be met inside the workflow, and the author may choose to
finish them directly in a copy of the uploads. Before 1.9.0 the run could only stop at S25 =
REVISE. Now:

    08_submission/final_copy/<same file name as in the bundle>   the author's edited copies
    tools/final_copy.py record --edit "..." [--edit ...] --words "<author's authorisation>"
    tools/final_copy.py check                                    deterministic comparison

`check` compares each copy with the frozen bundle file of the same name: every number (values,
citation numbers, years), every figure/table reference and the file's validity must be
unchanged; registered administrative facts (author_info.json) may be added; for a double-blind
journal the review-facing copies must stay anonymous. It records hashes in .wf/final_copy.json.
S25 may then close with `submission_package_independent_audit = PASS_AUTHOR_FINAL_COPY`, which
the `final_copy_verified` gate accepts only while the recorded check matches the copies.
"""
from __future__ import annotations

import hashlib
import json
import re
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

DIR = "08_submission/final_copy"
REL = ".wf/final_copy.json"
# 1.15.0 (E8): PDFs and figure files are checked too (they were outside the comparison).
SUFFIXES = (".docx", ".xlsx", ".pdf", ".tif", ".tiff", ".png")
IMAGE_SUFFIXES = (".tif", ".tiff", ".png")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load(project: Path) -> dict:
    try:
        data = json.loads((Path(project) / REL).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    return data if isinstance(data, dict) else {}


def _save(project: Path, data: dict) -> None:
    path = Path(project) / REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def copies(project: Path) -> list[Path]:
    from .journalspec import since_1150
    root = Path(project) / DIR
    # The PDF/figure coverage is a stricter check: a paper pinned before 1.15.0 gets it after
    # `wf migrate --yes`.
    kinds = SUFFIXES if since_1150(project) else (".docx", ".xlsx")
    return sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.casefold() in kinds) \
        if root.is_dir() else []


def text_of(path: Path) -> str:
    if path.suffix.casefold() == ".docx":
        from .packagecontent import visible_text
        return visible_text(path)
    from .xlsxlite import Workbook
    return "\n".join(str(c.value) for sh in Workbook(path).sheets for c in sh.cells if c.value)


def record(project: Path, edits: list[str], words: str) -> dict:
    if not copies(project):
        raise ValueError(f"no edited copies under {DIR}/ (copy the bundle files there first)")
    if not edits or any(len(e.strip()) < 8 for e in edits):
        raise ValueError("list every manual edit (--edit, >= 8 characters each)")
    from .reviewrounds import CONFIRM_PHRASES, is_confirmation
    if not is_confirmation(words):
        # 1.10.0 (#13): the author's exact confirmation sentence, never a recognised phrase.
        raise ValueError(f"--words must be the author's exact sentence '{CONFIRM_PHRASES[0]}' "
                         f"(or '{CONFIRM_PHRASES[1]}')")
    data = load(project)
    data.update(edits=[e.strip() for e in edits], authorised=words.strip(), recorded_at=_now(),
                check=None)
    _save(project, data)
    return data


def compare(project: Path, original: Path, copy: Path) -> list[str]:
    from . import docxaudit, journalspec, presentation
    problems = []
    try:
        with zipfile.ZipFile(copy) as zf:
            if zf.testzip():
                return [f"{copy.name}: corrupt file"]
    except zipfile.BadZipFile:
        return [f"{copy.name}: not a valid Office file"]
    admin = presentation.admin_strings(project)
    before, after = text_of(original), text_of(copy)
    for s in admin:
        before, after = before.replace(s, " "), after.replace(s, " ")
    problems += compare_text(project, before, after, copy)
    fb, fa = presentation.text_facts(before), presentation.text_facts(after)
    new_refs = Counter(fa["artifacts"]) - Counter(fb["artifacts"])
    unknown = [a for a in new_refs if a not in set(fb["artifacts"])]
    if unknown:
        problems.append(f"{copy.name}: figure/table references added: " + ", ".join(sorted(unknown))[:160])
    target = journalspec.load(project)
    if journalspec.blinded(target) and not any(k in copy.name.casefold()
                                               for k in ("title", "cover", "copyright")):
        problems += docxaudit.blinding_problems(copy, docxaudit.identity_strings(project))
    return problems


def compare_text(project: Path, before: str, after: str, copy: Path,
                 line_mode: bool = True) -> list[str]:
    """Numbers, citations and meaning of `after` against the checked `before` text."""
    from . import nonfacts, presentation
    problems: list[str] = []
    # 1.15.0 (E12): digits of the reference list are not facts here (refproof verifies them).
    before, after = nonfacts.strip_reference_list(before), nonfacts.strip_reference_list(after)
    # 1.13.0 (#9): the same rule as every post-freeze change - a changed reported value or a
    # number that cannot be traced to the results is refused; traceable additions and
    # deletions are presentation (listed by `final_copy.py check`, covered by the author's
    # confirmation).
    ch = presentation.number_changes(presentation.token_seq(before), presentation.token_seq(after))
    for o, n in ch["changed"]:
        problems.append(f"{copy.name}: a reported value changed (numbers {', '.join(o)[:80]} -> "
                        f"{', '.join(n)[:80]})")
    if ch["added"]:
        index = presentation.results_index(project)
        untraced = [t for t in sorted(ch["added"]) if presentation.trace_number(project, t, index) is None]
        if untraced:
            problems.append(f"{copy.name}: numbers added that no results JSON holds: "
                            + ", ".join(untraced)[:160])
        problems += [f"{copy.name}: {p}" for p in ratio_problems(after)]
    # 1.14.0 (A): an author's final edit that keeps the numbers can still change the meaning.
    from . import meaning
    # 1.15.0 (E1a): compare with the last final copy whose meaning pairs were all resolved.
    anchor = hashlib.sha256(before.encode("utf-8")).hexdigest()
    base = meaning.confirmed_text(project, "final", copy.name, anchor)
    terms = meaning.dictionary_terms(project)
    if line_mode:
        pairs = meaning.pairs_for(before if base is None else base, after, f"{DIR}/{copy.name}",
                                  terms, line_mode=True)
    else:  # PDF text: line breaks are layout, compare the word streams
        pairs = meaning.pairs_for(None, after, f"{DIR}/{copy.name}", terms,
                                  old_seq=meaning.tokens(before if base is None else base),
                                  new_seq=meaning.tokens(after))
    gate = meaning.gate(project, "final", pairs)
    if not gate:
        meaning.confirm(project, "final", copy.name, after, anchor)
    problems += [f"{copy.name}: {p}" for p in gate]
    if not line_mode:  # PDF: display references must survive too (Word copies: compare())
        fb, fa = presentation.text_facts(before), presentation.text_facts(after)
        moved = (Counter(fb["artifacts"]) - Counter(fa["artifacts"])) + \
            (Counter(fa["artifacts"]) - Counter(fb["artifacts"]))
        if moved:
            problems.append(f"{copy.name}: figure/table references differ: "
                            + ", ".join(sorted(moved))[:160])
    return problems


PAGE_NO_RE = re.compile(r"(?m)^\s*(?:page\s+)?\d{1,3}(?:\s*(?:/|of)\s*\d{1,3})?\s*$", re.I)


def pdf_text(path: Path) -> str:
    from pypdf import PdfReader
    text = "\n".join((page.extract_text() or "") for page in PdfReader(str(path)).pages)
    return PAGE_NO_RE.sub(" ", text)


def compare_pdf(project: Path, copy: Path, data: dict) -> list[str]:
    """A PDF in the final copy: exported by the engine from a checked Word copy (provenance
    recorded), or its text holds the same numbers, citations and meaning as that Word copy
    (else as the bundle PDF of the same name)."""
    from .determinism import raw_sha256
    project = Path(project)
    rel = copy.relative_to(project).as_posix()
    prov = (data.get("pdf_from") or {}).get(rel) or {}
    src_docx = project / prov["docx"] if prov.get("docx") else None
    if src_docx and src_docx.is_file() and raw_sha256(src_docx) == prov.get("docx_sha256") \
            and raw_sha256(copy) == prov.get("pdf_sha256"):
        return []  # exported from the checked Word copy by final_copy.py export-pdf
    for cand in (copy.with_suffix(".docx"),
                 project / "08_submission/bundle" / copy.relative_to(project / DIR).with_suffix(".docx")):
        if cand.is_file():
            before = text_of(cand)
            break
    else:
        original = project / "08_submission/bundle" / copy.relative_to(project / DIR)
        if not original.is_file():
            return [f"{copy.name}: no checked Word copy or bundle PDF to compare with"]
        if raw_sha256(original) == raw_sha256(copy):
            return []
        before = pdf_text(original)
    try:
        after = pdf_text(copy)
    except Exception as exc:  # noqa: BLE001
        return [f"{copy.name}: unreadable PDF ({exc})"]
    from . import presentation
    for s in presentation.admin_strings(project):
        before, after = before.replace(s, " "), after.replace(s, " ")
    return compare_text(project, before, after, copy, line_mode=False)


def compare_image(project: Path, copy: Path) -> list[str]:
    """A figure file in the final copy must be byte-identical to a certified master (the
    bundle file of the same name or a 05_figures/out render)."""
    from .determinism import raw_sha256
    project = Path(project)
    sha = raw_sha256(copy)
    pool = [project / "08_submission/bundle" / copy.relative_to(project / DIR)]
    out = project / "05_figures/out"
    pool += sorted(out.glob("*")) if out.is_dir() else []
    if any(p.is_file() and raw_sha256(p) == sha for p in pool):
        return []
    return [f"{copy.name}: figure file differs from every certified master (05_figures/out, "
            "bundle); restore it, or regenerate the figure in a rework round"]


def export_pdf(project: Path, docx: Path) -> Path:
    """Export a checked final-copy Word file to PDF and record that provenance."""
    import sys
    from . import determinism, docxaudit, journalspec
    from .determinism import raw_sha256
    project, docx = Path(project), Path(docx)
    if not docx.is_file() or docx.suffix.casefold() != ".docx":
        raise ValueError(f"{docx}: not a Word file")
    try:
        docx.resolve().relative_to((project / DIR).resolve())
    except ValueError as exc:
        raise ValueError(f"{docx} is not in {DIR}/") from exc
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "manuscript"))
    import build_docx  # tools/manuscript/build_docx.py
    pdf = docx.with_suffix(".pdf")
    build_docx._convert_pdf(docx, pdf)
    determinism.set_pdf_lang(pdf, docxaudit.pdf_lang(journalspec.load(project)))
    determinism.normalize(pdf)
    data = load(project)
    data.setdefault("pdf_from", {})[pdf.relative_to(project).as_posix()] = {
        "docx": docx.relative_to(project).as_posix(), "docx_sha256": raw_sha256(docx),
        "pdf_sha256": raw_sha256(pdf), "at": _now()}
    _save(project, data)
    return pdf


def _pool(project: Path) -> tuple[set[float], set[str]]:
    import json
    from .checks.numbers import _walk
    strings: set[str] = set()
    for p in sorted((Path(project) / "03_analysis/results").glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            data = {k: v for k, v in data.items() if k != "environment"}
        _walk(data, strings)
    floats = set()
    for s in strings:
        try:
            floats.add(float(s))
        except ValueError:
            pass
    return floats, strings


def traceable(project: Path, token: str) -> bool:
    """A number that exists (at its displayed precision) in 03_analysis/results/*.json."""
    from .checks.numbers import _matches
    floats, strings = _pool(project)
    return _matches(token, floats, strings)


def ratio_problems(text: str) -> list[str]:
    """'a/b (p%)' must be internally consistent at the displayed precision."""
    out = []
    for m in re.finditer(r"(\d[\d,]*)\s*/\s*(\d[\d,]*)\s*\(\s*(\d+(?:\.\d+)?)\s?%", text):
        a, b = int(m.group(1).replace(",", "")), int(m.group(2).replace(",", ""))
        p = m.group(3)
        dec = len(p.split(".")[1]) if "." in p else 0
        if b and abs(100.0 * a / b - float(p)) > 0.5 * 10 ** -dec + 1e-9:
            out.append(f"'{m.group(0)})': {a}/{b} is {100.0 * a / b:.{max(dec, 1)}f}%")
    return out


def check(project: Path) -> tuple[bool, list[str]]:
    from .determinism import raw_sha256
    project = Path(project)
    data = load(project)
    if not data.get("edits"):
        return False, ["no manual-edit list recorded (tools/final_copy.py record)"]
    bundle = project / "08_submission/bundle"
    problems, files = [], {}
    found = copies(project)
    if not found:
        problems.append(f"no edited copies under {DIR}/")
    for copy in found:
        original = bundle / copy.relative_to(project / DIR)
        suffix = copy.suffix.casefold()
        if suffix == ".pdf":
            problems += compare_pdf(project, copy, data)
        elif suffix in IMAGE_SUFFIXES:
            problems += compare_image(project, copy)
        elif not original.is_file():
            problems.append(f"{copy.name}: no frozen bundle file of the same name to compare with")
            continue
        else:
            problems += compare(project, original, copy)
        files[copy.relative_to(project).as_posix()] = raw_sha256(copy)
    data["check"] = {"at": _now(), "ok": not problems, "problems": problems, "files": files}
    _save(project, data)
    return not problems, problems


def verified(project: Path) -> list[str]:
    """Why the recorded final-copy check does not hold now (empty = it holds)."""
    from .determinism import raw_sha256
    data = load(project)
    chk = data.get("check") or {}
    if not chk.get("ok"):
        return ["the final-copy check has not passed (tools/final_copy.py check)"]
    now = {p.relative_to(project).as_posix(): raw_sha256(p) for p in copies(project)}
    if now != chk.get("files"):
        return ["the edited copies changed after the last final-copy check; run it again"]
    return []
