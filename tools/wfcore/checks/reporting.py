"""Reporting-guideline checklist gate (S23/S24/S25), on demand only.

Since 1.7.3 no checklist is chosen or filled pre-emptively. The gate enforces one only when the
chosen journal's author guidelines require it (target_journal.json `journal_requires_checklist`,
recorded at S20), or PRISMA for a systematic review / meta-analysis; otherwise it passes as not
required.
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

from . import Ctx, Result, check
from .. import paths

REGISTRY_REL = "reporting_guidelines.toml"
CHECKLIST_REL = "08_submission/reporting_checklist.md"
JOURNAL_REL = "08_submission/target_journal.json"
MANUSCRIPT_REL = "08_submission/manuscript/full_manuscript.md"
DEFAULT_DOCUMENTS = {
    "Supplementary Methods": "08_submission/manuscript/supplementary_methods.md",
    "Title page": "08_submission/manuscript/title_page.md",
    "Statements": "08_submission/manuscript/statements.md",
}
_B_LEFT = r"(?<![A-Za-z0-9+\-])"
_B_RIGHT = r"(?![A-Za-z0-9+\-])"
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_GUIDELINE_LINE = re.compile(r"^\s*[-*]?\s*Guideline:\s*(.+?)\s*$", re.I)
HEADER = ["item", "status", "location", "evidence", "reason"]
LEGACY_HEADER = ["item", "status", "location", "reason"]
# A section heading proves a place exists, not that the item is reported there. Every Reported
# row therefore carries a verbatim quote that must be found inside that location's text.
EVIDENCE_MIN_CHARS = 25
EVIDENCE_MAX_REUSE = 3


def load_registry(path: Path | None = None) -> dict:
    p = path or (paths.reference_dir() / REGISTRY_REL)
    return tomllib.loads(p.read_text(encoding="utf-8")).get("guideline", {})


def registry_problems(reg: dict) -> list[str]:
    problems, seen = [], {}
    for gid, g in reg.items():
        aliases = g.get("aliases") or []
        if not aliases:
            problems.append(f"{gid}: aliases empty")
        for a in aliases:
            k = a.casefold()
            if k in seen and seen[k] != gid:
                problems.append(f"alias {a} used by {seen[k]} and {gid}")
            seen[k] = gid
        items = g.get("items", [])
        if g.get("verify") is True and items:
            problems.append(f"{gid}: verify = true must ship no items")
        if g.get("verify") is False and not items:
            problems.append(f"{gid}: verify = false needs items")
        ids = [i.get("id") for i in items]
        if len(ids) != len(set(ids)):
            problems.append(f"{gid}: duplicate item ids")
    return problems


def _alias_re(alias: str) -> str:
    return re.escape(alias).replace(r"\ ", r"[\s-]+")


def detect_guidelines(text: str, reg: dict | None = None) -> list[str]:
    reg = reg if reg is not None else load_registry()
    found: list[tuple[int, str]] = []
    for sensitive in (False, True):
        pairs = [(a, gid) for gid, g in reg.items() if bool(g.get("case_sensitive")) == sensitive
                 for a in g.get("aliases", [])]
        if not pairs:
            continue
        pairs.sort(key=lambda p: -len(p[0]))
        lookup = {(a if sensitive else a.casefold()): gid for a, gid in pairs}
        rx = re.compile(_B_LEFT + "(" + "|".join(_alias_re(a) for a, _ in pairs) + ")" + _B_RIGHT,
                        0 if sensitive else re.I)
        for m in rx.finditer(text):
            key = re.sub(r"[\s-]+", " ", m.group(1))
            gid = None
            for a, g in pairs:
                if re.fullmatch(_alias_re(a), m.group(1), 0 if sensitive else re.I):
                    gid = g
                    break
            if gid is None:
                gid = lookup.get(key if sensitive else key.casefold())
            if gid:
                found.append((m.start(), gid))
    out: list[str] = []
    for _, gid in sorted(found):
        if gid not in out:
            out.append(gid)
    return out


def resolve_alias(value: str, reg: dict) -> str | None:
    v = re.sub(r"\s+", " ", value.strip()).casefold()
    for gid, g in reg.items():
        if v == gid.casefold() or any(v == re.sub(r"\s+", " ", a).casefold()
                                      for a in g.get("aliases", [])):
            return gid
    return None


_COMBINE = re.compile(r"\s+\+\s+|\s*[,;&/]\s*|\s+and\s+", re.I)


def split_guidelines(value: str, reg: dict) -> tuple[list[str], list[str]]:
    """'STROBE + RECORD' -> (['STROBE', 'RECORD'], []). A name that resolves whole (TRIPOD+AI)
    is never split; '+' without spaces is split only when every piece resolves."""
    whole = resolve_alias(value, reg)
    if whole:
        return [whole], []
    ids, bad = [], []
    for part in (p for p in _COMBINE.split(value) if p.strip()):
        gid = resolve_alias(part, reg)
        pieces = [gid] if gid else [resolve_alias(x, reg) for x in part.split("+") if x.strip()]
        if not pieces or None in pieces:
            bad.append(part.strip())
            continue
        ids += [g for g in pieces if g not in ids]
    return ids, bad


def normalise_heading(h: str) -> str:
    h = re.sub(r"[*_`]", "", h)
    h = re.sub(r"^\s*\d+(?:\.\d+)*\.?\s+", "", h)
    h = re.sub(r"\s+", " ", h).strip().rstrip(":").strip()
    return h.casefold()


def headings(text: str) -> tuple[list[str], str | None]:
    out, title = [], None
    in_fence = False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = _HEADING.match(line)
        if m:
            if title is None and len(m.group(1)) == 1:
                title = m.group(2)
            out.append(normalise_heading(m.group(2)))
    return out, title


def protocol_section(text: str) -> str | None:
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = _HEADING.match(line)
        if m and "reporting guideline" in m.group(2).casefold():
            level = len(m.group(1))
            body = []
            for nxt in lines[i + 1:]:
                n = _HEADING.match(nxt)
                if n and len(n.group(1)) <= level:
                    break
                body.append(nxt)
            return "\n".join(body)
    return None


def protocol_guidelines(section: str, reg: dict) -> tuple[list[str], list[str]]:
    """-> (guideline ids, problems). Explicit `Guideline:` lines win over prose detection."""
    explicit = [m.group(1) for m in (_GUIDELINE_LINE.match(l) for l in section.splitlines()) if m]
    if explicit:
        ids, problems = [], []
        for v in explicit:
            gids, bad = split_guidelines(v, reg)
            for b in bad:
                problems.append(f"unregistered guideline on a Guideline: line: {b}")
            ids += [g for g in gids if g not in ids]
        return ids, problems
    return detect_guidelines(section, reg), []


def parse_checklist(text: str) -> tuple[dict[str, list[dict]], list[str]]:
    blocks: dict[str, list[dict]] = {}
    problems: list[str] = []
    current = None
    header_ok: dict[str, bool] = {}
    for line in text.splitlines():
        m = _GUIDELINE_LINE.match(line)
        if m:
            current = m.group(1).strip()
            blocks.setdefault(current, [])
            header_ok[current] = False
            continue
        if current is None or not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not header_ok[current]:
            if [c.casefold() for c in cells[:5]] != HEADER:
                problems.append(f"{current}: table header must be "
                                f"{' | '.join(h.capitalize() for h in HEADER)}"
                                + (" (1.7.1 added the Evidence column: a verbatim quote from "
                                   "the manuscript at that location)"
                                   if [c.casefold() for c in cells[:4]] == LEGACY_HEADER else ""))
            header_ok[current] = True
            continue
        if all(re.fullmatch(r":?-+:?", c) for c in cells if c):
            continue
        cells += [""] * (5 - len(cells))
        blocks[current].append({"item": cells[0], "status": cells[1], "location": cells[2],
                                "evidence": cells[3], "reason": cells[4]})
    return blocks, problems


def norm_quote(text: str) -> str:
    """Whitespace-, case- and markdown-emphasis-insensitive form used for evidence matching."""
    t = re.sub(r"[*_`]", "", text)
    t = t.replace("\u201c", "").replace("\u201d", "").replace("\u2018", "'").replace("\u2019", "'")
    t = t.strip().strip('"').strip()
    return re.sub(r"\s+", " ", t).casefold()


def section_text(text: str, wanted: str) -> str:
    """Body of every section whose normalised heading is `wanted`, subsections included."""
    out, level, in_fence = [], None, False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
        m = None if in_fence else _HEADING.match(line)
        if m:
            if level is not None and len(m.group(1)) <= level:
                level = None
            if level is None and normalise_heading(m.group(2)) == wanted:
                level = len(m.group(1))
                out.append(m.group(2))
                continue
        if level is not None:
            out.append(line)
    return "\n".join(out)


_META = re.compile(r"meta[\s-]?analy|systematic\s+review", re.I)
_NONE = {"", "none", "no", "not required", "n/a", "na", "false"}


def _design_text(ctx: Ctx) -> str:
    for rel in ("01_protocol/protocol_final.md", "01_protocol/protocol_v1.md"):
        if ctx.p(rel).is_file():
            text = ctx.read(rel)
            body = section_text(text, "design")
            return body if body.strip() else ""
    return ""


# 1.11.0 (#3d): a negated mention ("no meta-analysis", "not a systematic review", "without a
# meta-analysis", "meta-analysis was not performed", "rather than a meta-analysis") states
# what the study is NOT. Negation is judged within the clause on both sides of the mention.
_NEG_BEFORE = re.compile(r"\b(?:no|not|nor|without|neither|rather\s+than|instead\s+of|"
                         r"other\s+than|unlike|never)\s+(?:(?:a|an|any|formal|the|quantitative|"
                         r"pooled|separate|full)\s+)*$", re.I)
_NEG_AFTER = re.compile(r"^[\w\s,'()-]{0,40}?\b(?:was|were|is|are|will\s+be|has\s+been|have\s+been)?"
                        r"\s*(?:not|n't|never)\s+(?:be\s+)?(?:performed|conducted|done|planned|"
                        r"undertaken|carried\s+out|feasible|possible|appropriate|used|applicable)\b"
                        r"|^[\w\s,'-]{0,20}?\b(?:is|was)\s+not\s+applicable\b", re.I)


def meta_mentioned_affirmatively(text: str) -> bool:
    for m in _META.finditer(text):
        before = re.split(r"[.;:!?\n]", text[:m.start()])[-1]
        after = re.split(r"[.;:!?\n]", text[m.end():])[0]
        # the matched stem ("meta-analy") leaves the rest of the word: "sis was not performed"
        after = re.sub(r"^[a-z]*", "", after, flags=re.I)
        if _NEG_BEFORE.search(before) or _NEG_AFTER.search(after):
            continue
        return True
    return False


def is_meta_analysis(ctx: Ctx) -> bool:
    """A systematic review / meta-analysis. 1.11.0: the structured study_design in
    01_protocol/idea.json (1.10.0) decides when present; otherwise the protocol's Design section
    is read with negation handled ("no meta-analysis" is not a meta-analysis)."""
    import json
    try:
        idea = json.loads(ctx.read("01_protocol/idea.json"))
    except (OSError, ValueError):
        idea = {}
    design = str(idea.get("study_design", "")).strip().casefold() if isinstance(idea, dict) else ""
    if design:
        return design in ("meta_analysis", "systematic_review")
    return meta_mentioned_affirmatively(_design_text(ctx))


def journal_requirement(ctx: Ctx) -> str | None:
    """The checklist the chosen journal demands (target_journal.json), or None."""
    import json
    p = ctx.p(JOURNAL_REL)
    if not p.is_file():
        return None
    try:
        value = json.loads(p.read_text(encoding="utf-8")).get("journal_requires_checklist")
    except (OSError, ValueError, AttributeError):
        return None
    if value is None or value is False:
        return None
    value = str(value).strip()
    return None if value.casefold() in _NONE else value


@check("reporting_checklist_complete")
def reporting_checklist_complete(ctx: Ctx) -> Result:
    """On demand only (1.7.3): enforced when the target journal requires a checklist
    (`journal_requires_checklist` in target_journal.json), or PRISMA for a meta-analysis.
    Otherwise it passes as not required."""
    name = "reporting_checklist_complete"
    sev = ctx.spec.get("severity", "fail")
    required = journal_requirement(ctx)
    if required is None and not is_meta_analysis(ctx):
        return Result(True, name, "not required: the target journal requires no reporting "
                                  "checklist (journal_requires_checklist unset)")
    try:
        reg = load_registry()
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return Result(False, name, f"reference/{REGISTRY_REL} unreadable: {exc}", severity=sev)
    if required is None:
        ids, problems, source = ["PRISMA"], [], "meta-analysis design"
    else:
        ids, bad = split_guidelines(required, reg)
        problems = [f"unregistered guideline in journal_requires_checklist: {b}" for b in bad]
        source = f"{JOURNAL_REL} journal_requires_checklist"
    if problems or not ids:
        return Result(False, name, "; ".join(problems) or f"{source}: no guideline named",
                      ["Use a name from reference/reporting_guidelines.toml, or add the "
                       "journal's checklist there from the engine workspace."], severity=sev)
    unverified = [g for g in ids if reg[g].get("verify")]
    if unverified:
        return Result(False, name, "; ".join(
            f"item list for {g} is not shipped (verify = true); populate it from "
            f"{reg[g].get('source', 'the official checklist')} in the engine workspace and set "
            "verify = false" for g in unverified), severity=sev)

    rel = ctx.spec.get("path", CHECKLIST_REL)
    if not ctx.p(rel).is_file():
        return Result(False, name, f"{rel} missing (required by {source})", ["Write it at S23 "
                      "against the journal variant: one `Guideline: <name>` line and an Item | "
                      "Status | Location | Evidence | Reason table per guideline."], severity=sev)
    man_rel = ctx.spec.get("manuscript", MANUSCRIPT_REL)
    if not ctx.p(man_rel).is_file():
        return Result(False, name, f"{man_rel} missing (open the journal variant first)",
                      severity=sev)
    documents = dict(ctx.spec.get("documents", DEFAULT_DOCUMENTS))
    doc_heads: dict[str, list[str] | None] = {}
    doc_texts: dict[str, str] = {}
    problems = []
    names_cf = [n.casefold() for n in documents]
    if len(set(names_cf)) != len(names_cf) or "title" in names_cf:
        return Result(False, name, "documents spec: names must be unique and not 'Title'",
                      severity=sev)
    for dname, drel in documents.items():
        p = (ctx.project / drel).resolve()
        if not paths.within(p, ctx.project):
            return Result(False, name, f"documents spec: {drel} escapes the paper", severity=sev)
        text = p.read_text(encoding="utf-8") if p.is_file() else ""
        doc_heads[dname.casefold()] = headings(text)[0] if text.strip() else None
        doc_texts[dname.casefold()] = text
    main_text = ctx.read(man_rel)
    main_heads, title = headings(main_text)

    def scope(token: str) -> str | None:
        """The text a location token points at, or None when it does not resolve."""
        t = token.strip()
        if not t:
            return None
        if t.casefold() == "title":
            return title
        if ">" in t:
            doc, head = (x.strip() for x in t.split(">", 1))
            hs = doc_heads.get(doc.casefold())
            if not hs or normalise_heading(head) not in hs:
                return None
            return section_text(doc_texts[doc.casefold()], normalise_heading(head))
        if normalise_heading(t) in main_heads:
            return section_text(main_text, normalise_heading(t))
        if doc_heads.get(t.casefold()) is not None:
            return doc_texts[t.casefold()]
        return None

    def resolves(token: str) -> bool:
        return scope(token) is not None

    blocks, problems = parse_checklist(ctx.read(rel))
    # One block per guideline, or one combined block ('Guideline: STROBE + RECORD') whose
    # Item cells carry the guideline as a prefix ('RECORD 6.1') so ids never clash.
    gid_rows: dict[str, list[dict]] = {}
    for label, rows in blocks.items():
        gids, bad = split_guidelines(label, reg)
        if bad or not gids:
            problems.append(f"checklist names an unregistered guideline: {label}")
            continue
        if len(gids) == 1:
            gid_rows.setdefault(gids[0], []).extend(rows)
            continue
        for r in rows:
            m = re.match(r"^(.+?)\s+(\S+)$", r["item"])
            gid = resolve_alias(m.group(1), reg) if m else None
            if gid not in gids:
                problems.append(f"{label}: item '{r['item']}' in a combined block needs a "
                                f"guideline prefix ({' / '.join(gids)} <id>)")
                continue
            gid_rows.setdefault(gid, []).append(dict(r, item=m.group(2)))
    if set(gid_rows) != set(ids):
        problems.append(f"checklist blocks do not match the requirement: checklist "
                        f"{sorted(gid_rows)}, required {sorted(ids)} ({source})")
    unresolved_all = []
    no_evidence: list[str] = []
    not_found: list[str] = []
    reuse: dict[str, list[str]] = {}
    for gid, rows in gid_rows.items():
        if gid not in ids:
            continue
        want = [i["id"] for i in reg[gid].get("items", [])]
        got = [r["item"] for r in rows]
        missing = [i for i in want if i not in got]
        dup = sorted({i for i in got if got.count(i) > 1})
        unknown = [i for i in got if i not in want]
        if missing:
            problems.append(f"{gid}: missing item(s) {', '.join(missing[:12])}")
        if dup:
            problems.append(f"{gid}: duplicated item(s) {', '.join(dup)}")
        if unknown:
            problems.append(f"{gid}: unknown item id(s) {', '.join(unknown[:8])}")
        for r in rows:
            status = r["status"].casefold()
            if status == "reported":
                tokens = [t for t in r["location"].split(";")]
                if not r["location"].strip():
                    problems.append(f"{gid} {r['item']}: Reported needs a location")
                for t in tokens:
                    if not resolves(t):
                        unresolved_all.append(f"{gid} {r['item']}: '{t.strip()}'")
                quote = norm_quote(r.get("evidence", ""))
                if len(quote) < EVIDENCE_MIN_CHARS:
                    no_evidence.append(f"{gid} {r['item']}")
                else:
                    reuse.setdefault(quote, []).append(f"{gid} {r['item']}")
                    scopes = [s for s in (scope(t) for t in tokens) if s is not None]
                    if scopes and not any(quote in norm_quote(s) for s in scopes):
                        not_found.append(f"{gid} {r['item']}: \"{r['evidence'][:50]}\"")
            elif status == "not applicable":
                if len(r["reason"].strip()) < 20:
                    problems.append(f"{gid} {r['item']}: Not applicable needs a reason of >= 20 "
                                    "characters")
            else:
                problems.append(f"{gid} {r['item']}: status must be Reported or Not applicable, "
                                f"got '{r['status']}'")
    if no_evidence:
        problems.append(f"Reported row(s) without a verbatim Evidence quote of >= "
                        f"{EVIDENCE_MIN_CHARS} characters: {', '.join(no_evidence[:10])}")
    if not_found:
        problems.append("Evidence quote(s) not found in the stated location's text: "
                        + "; ".join(not_found[:5]))
    overused = [f"{len(v)} items ({', '.join(v[:4])})" for v in reuse.values()
                if len(v) > EVIDENCE_MAX_REUSE]
    if overused:
        problems.append(f"the same Evidence quote is reused for more than {EVIDENCE_MAX_REUSE} "
                        f"items, so it cannot be specific evidence: {'; '.join(overused[:3])}")
    if unresolved_all:
        avail = [f"main manuscript: {', '.join(main_heads[:20])}"]
        for dname, hs in doc_heads.items():
            avail.append(f"{dname}: " + ("(absent)" if hs is None else ", ".join(hs[:20])))
        problems.append("unresolved location(s) " + "; ".join(unresolved_all[:6])
                        + " | available headings - " + " | ".join(avail))
    if problems:
        return Result(False, name, "; ".join(problems[:8]),
                      ["Locations: a main-manuscript heading, `Title`, `<Document> > <heading>` "
                       "(Supplementary Methods, Title page, Statements) or a bare document name.",
                       "Evidence: copy the sentence that actually reports the item, verbatim, "
                       "from that location (>= 25 characters). A heading is not evidence; if "
                       "no sentence reports it, fix the manuscript or mark Not applicable with "
                       "a reason."],
                      severity=sev)
    return Result(True, name, f"{', '.join(ids)}: every item reported with a quote found at its "
                              "location, or justified as not applicable")
