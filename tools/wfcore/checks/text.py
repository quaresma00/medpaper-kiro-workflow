"""Markdown / source-text checks."""
from __future__ import annotations

import re
from pathlib import Path

from . import Ctx, Result, check

CITE_RE = re.compile(r"\[(@[^\]]+)\]")
FENCE_RE = re.compile(r"```.*?```", re.S)
INLINE_CODE_RE = re.compile(r"`[^`]*`")
HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$", re.M)

# Hard stops: text that must never survive into a deliverable.
PLACEHOLDERS = [
    "TODO", "TBD", "FIXME", "XXX", "PLACEHOLDER", "VERIFY:", "[insert",
    "lorem ipsum", "as an ai", "i cannot provide", "<your ", "xx.x", "N.NN",
]

# Soft flags: phrasing that reads as machine-generated. Reported, not blocking.
AI_TELLS = [
    "delve into", "it is worth noting", "it is important to note",
    "plays a crucial role", "plays a vital role", "paves the way",
    "in today's rapidly evolving", "ever-evolving", "landscape of",
    "tapestry", "underscores the importance", "holds immense promise",
    "cutting-edge", "seamlessly", "a testament to", "navigating the complexities",
    "unlock the potential", "revolutionize", "game-changer",
    "it is crucial to understand", "multifaceted approach", "delves",
    "in the realm of", "shedding light upon", "robust and comprehensive",
]

# Backstage language: the pipeline's own review/revision history leaking into the paper. An
# editor reads "added after independent review" as a rejected or unstable manuscript.
BACKSTAGE_RE = re.compile(
    r"\bindependent\s+(?:publishability\s+)?review(?:er)?s?\b|"
    r"\b(?:earlier|previous|prior|original|first)\s+drafts?\b|\boriginal\s+submission\b|"
    r"\b(?:earlier|previous|prior)\s+versions?\s+of\s+(?:this|the|our)\s+"
    r"(?:manuscript|paper|article|analysis|study|draft)\b|"
    r"\b(?:requested|suggested|raised|noted|flagged)\s+by\s+(?:the\s+)?(?:independent\s+)?reviewers?\b|"
    r"\bat\s+(?:the\s+)?reviewers?'?s?\s+request\b|"
    r"\bin\s+response\s+to\s+(?:the\s+)?(?:reviewers?|review|reviewer\s+comments)\b|"
    r"\b(?:added|revised|corrected|updated|changed)\s+(?:after|following)\s+(?:the\s+)?"
    r"(?:independent\s+|internal\s+)?review\b|"
    r"\b(?:this|the)\s+revised\s+(?:manuscript|version|draft)\b|\bwrongly\s+(?:kept|included|excluded)\b|"
    r"\b(?:pipeline|workflow)\s+(?:stage|step|gate)\b|"
    # 1.11.0 (#2h): review/round/internal/rerun history.
    r"\b(?:internal|external|editorial)\s+(?:review|check|audit)s?\b(?!\s+(?:board|committee|panel))|"
    r"\b(?:review|revision|audit)\s+rounds?\b|\bround\s+\d+\s+of\s+(?:the\s+)?review\b|"
    r"\b(?:re-?runs?|re-?ran|re-?running)\b|\b(?:earlier|previous|prior|original|initial)\s+"
    r"(?:analys[ie]s|runs?|results|estimates?)\s+(?:of\s+this\s+study|were|was|had)\b|"
    r"\b(?:added|introduced|included)\s+(?:after|following)\s+(?:the\s+)?(?:review|revision)\b|"
    r"\bpost\s+hoc\s*\(\s*(?:after|following)\s+review\s*\)",
    re.I)
# 1.13.0 (#8): plan-versus-practice history is internal (.wf/protocol_changes.md). A medical
# paper simply describes the analysis performed; it never narrates an initial plan, protocol
# deviations or their handling. Exception: a meta-analysis with a registered protocol (PROSPERO)
# reports deviations under PRISMA 2020 item 24c.
DEVIATION_RE = re.compile(
    r"\bprotocol\s+deviations?\b|"
    r"\bdeviat(?:ed|es|ing|ions?)\s+from\s+(?:the\s+|our\s+|this\s+)?(?:study\s+)?"
    r"(?:initial|original|pre-?specified|planned|registered)?\s*(?:study\s+)?"
    r"(?:protocol|plan|analysis\s+plan)\b|"
    r"\bdepartures?\s+from\s+(?:the\s+|our\s+)?(?:protocol|plan|it)\b|"
    r"\boriginally\s+(?:planned|specified|intended|proposed)\b|"
    r"\binitial\s+(?:study\s+)?(?:protocol|plan|analysis\s+plan)\b|"
    r"\bchanged\s+from\s+(?:the\s+)?(?:protocol|plan)\b|"
    r"\bas\s+planned\s+in\s+the\s+protocol\b|"
    r"\b(?:the\s+)?(?:study\s+)?protocol\s+(?:was|is)\s+archived\b|"
    r"\barchived,?\s+(?:unregistered\s+)?protocol\b|"
    r"方案偏离|偏离(?:了)?(?:原|初始|最初|预先|预设|既定|研究)?(?:研究)?(?:方案|计划)|"
    r"(?:最初|初始|原定|原始)(?:的)?(?:研究)?(?:方案|计划)|与(?:研究)?方案不(?:同|一致)|"
    r"按(?:研究)?方案(?:原)?计划", re.I)
# 1.13.0: the advice is simply to describe the analysis performed (1.11 suggested a label).
POST_HOC_PHRASE = "describe the analysis performed"


def deviation_reporting_allowed(project) -> bool:
    """PRISMA 2020 item 24c: a meta-analysis/systematic review with a registered protocol
    (PROSPERO ID or CRD42 number recorded in the protocol, idea or author info)."""
    from pathlib import Path
    import json as _json
    project = Path(project)
    try:
        idea = _json.loads((project / "01_protocol/idea.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        idea = {}
    if not isinstance(idea, dict) or idea.get("study_design") not in ("meta_analysis",
                                                                      "systematic_review"):
        return False
    for rel in ("01_protocol/protocol_v1.md", "01_protocol/protocol_final.md",
                "01_protocol/idea.json", "00_input/author_info.json"):
        p = project / rel
        try:
            if p.is_file() and re.search(r"PROSPERO|CRD42\d+", p.read_text(encoding="utf-8",
                                                                            errors="replace")):
                return True
        except OSError:
            continue
    return False


# 1.14.1 (B7): the registration status a reporting guideline asks for (READUS-PV 14d, STROBE,
# PRISMA 24a: "the protocol was not registered", "not registered in PROSPERO", "was not
# prospectively registered") is a required statement, not a plan-versus-practice narrative.
REGISTRATION_STATUS_RE = re.compile(
    r"\b(?:the\s+|this\s+|our\s+)?(?:study\s+|review\s+|analysis\s+)?(?:protocol|study|review|"
    r"analysis)\s+(?:was|is|has)\s+(?:not\s+)?(?:been\s+)?(?:prospectively\s+|publicly\s+)?"
    r"(?:registered|pre-?registered)\b(?:\s+(?:in|with|on|at)\s+[A-Z][\w.-]*(?:\s+[A-Z][\w.-]*)*)?|"
    r"\b(?:was|were|is|are)\s+not\s+(?:prospectively\s+|publicly\s+)?(?:registered|"
    r"pre-?registered)\b(?:\s+(?:in|with|on|at)\s+[A-Z][\w.-]*)?|"
    r"\bnot\s+(?:prospectively\s+)?registered\s+(?:in|with|on|at)\s+(?:PROSPERO|OSF|"
    r"ClinicalTrials\.gov|a\s+(?:public\s+)?registry)\b|"
    r"\bunregistered\s+protocol\b|\bno\s+(?:registered\s+)?protocol\s+was\s+registered\b", re.I)


def deviation_hits(text: str, project=None) -> list[str]:
    if project is not None and deviation_reporting_allowed(project):
        return []
    body = REGISTRATION_STATUS_RE.sub(" ", _body(text))
    return sorted({m.group(0) for m in DEVIATION_RE.finditer(body)})


def polish_allowed(project) -> dict[str, str]:
    """1.14.1 (B7): the paper's polish_allowlist.tsv patterns (lower-case) with reasons, read
    from 07_manuscript/ and from the journal copy 08_submission/manuscript/ (after S19 the
    frozen folder is read-only, so the exception lives with the copy)."""
    out: dict[str, str] = {}
    if project is None:
        return out
    for rel in ("07_manuscript/polish_allowlist.tsv", "08_submission/manuscript/polish_allowlist.tsv"):
        p = Path(project) / rel
        try:
            lines = p.read_text(encoding="utf-8").splitlines() if p.is_file() else []
        except OSError:
            lines = []
        for line in lines:
            line = line.strip()
            if line and not line.startswith("#"):
                bits = line.split("\t")
                if bits[0].strip():
                    out[bits[0].strip().lower()] = bits[1].strip() if len(bits) > 1 else ""
    return out


def unallowed(hits: list[str], allow: dict[str, str]) -> list[str]:
    """Backstage/deviation hits the paper did not allowlist (pattern in the hit or vice versa)."""
    if not allow:
        return hits
    return [h for h in hits if not any(a in h.lower() or h.lower() in a for a in allow)]


# (#10) CRediT contributor role names are journal-template text, not revision history:
# "Writing - original draft", "Writing - review & editing" (any dash, "and" or "&").
CREDIT_ROLE_RE = re.compile(
    r"\bwriting\s*[-\u2010-\u2015:,]?\s*(?:the\s+)?(?:original\s+draft(?:\s+preparation)?|"
    r"review\s*(?:&|and)\s*editing)\b", re.I)  # 1.13.0: "writing the original draft" too


def backstage_hits(text: str) -> list[str]:
    return sorted({m.group(0) for m in BACKSTAGE_RE.finditer(CREDIT_ROLE_RE.sub(" ", _body(text)))})


FORBIDDEN_VISIBLE_SYMBOLS = {
    "\u2193": "down arrow (use words such as 'lower' or 'decreased')",
}


def _body(text: str) -> str:
    text = FENCE_RE.sub(" ", text)
    text = INLINE_CODE_RE.sub(" ", text)
    return text


def _wordcount(text: str) -> int:
    t = _body(text)
    t = CITE_RE.sub(" ", t)
    t = HEADING_RE.sub(" ", t)
    t = re.sub(r"^\s*>.*$", " ", t, flags=re.M)          # blockquotes
    t = re.sub(r"[*_#>|`~\[\]()]", " ", t)
    return len([w for w in t.split() if any(ch.isalnum() for ch in w)])


def _headings(text: str) -> list[str]:
    return [h.strip() for h in HEADING_RE.findall(text)]


@check("forbidden_symbols_absent")
def forbidden_symbols_absent(ctx: Ctx) -> Result:
    paths = ctx.spec.get("paths", [])
    present = [rel for rel in paths if ctx.p(rel).is_file()]
    if not present:
        return Result(False, "forbidden_symbols_absent", "none of the target files exist")
    problems = []
    for rel in present:
        value = ctx.read(rel)
        for symbol, description in FORBIDDEN_VISIBLE_SYMBOLS.items():
            if symbol in value:
                problems.append(f"{rel}: contains {description}")
    if problems:
        return Result(False, "forbidden_symbols_absent", "; ".join(problems[:8]))
    return Result(True, "forbidden_symbols_absent",
                  f"{len(present)} source file(s) contain no forbidden visible control symbols")


@check("md_sections")
def md_sections(ctx: Ctx) -> Result:
    rel = ctx.spec["path"]
    if not ctx.p(rel).exists():
        return Result(False, "md_sections", f"{rel} missing")
    text = ctx.read(rel)
    present = [h.lower() for h in _headings(text)]
    required = ctx.spec.get("headings", [])
    missing = [h for h in required if not any(h.lower() in p for p in present)]
    if missing:
        return Result(
            False,
            "md_sections",
            f"{rel} lacks heading(s): " + "; ".join(missing),
            [f"Required headings for this stage: {', '.join(required)}"],
        )
    return Result(True, "md_sections", f"{rel}: {len(required)} required heading(s) present")


@check("md_wordcount")
def md_wordcount(ctx: Ctx) -> Result:
    rel = ctx.spec["path"]
    if not ctx.p(rel).exists():
        return Result(False, "md_wordcount", f"{rel} missing")
    n = _wordcount(ctx.read(rel))
    lo = ctx.spec_bound("min")
    hi = ctx.spec_bound("max")
    if lo is not None and n < lo:
        # 1.8.0 (from Codex 1.11): a minimum is never a reason to pad; it only advises.
        return Result(False, "md_wordcount", f"{rel}: {n} words, below the usual {lo}",
                      ["Check that nothing the reader needs is missing; do not add filler."],
                      severity="warn")
    if hi is not None and n > hi:
        return Result(
            False,
            "md_wordcount",
            f"{rel}: {n} words, target <= {hi}",
            ["Cut, do not compress into denser jargon. Adjust the target with `wf config set` if the journal differs."],
        )
    return Result(True, "md_wordcount", f"{rel}: {n} words (target {lo}-{hi})")


@check("notes_populated")
def notes_populated(ctx: Ctx) -> Result:
    rel = ctx.spec["path"]
    if not ctx.p(rel).exists():
        return Result(False, "notes_populated", f"{rel} missing")
    text = ctx.read(rel)
    required = ctx.spec.get("headings", [])
    min_chars = ctx.spec.get("min_chars_per_section", 120)
    # split on headings and measure each block
    blocks: dict[str, str] = {}
    parts = re.split(r"^\s{0,3}#{1,6}\s+", text, flags=re.M)
    for chunk in parts[1:]:
        head, _, rest = chunk.partition("\n")
        blocks[head.strip().lower()] = rest
    thin, absent = [], []
    for h in required:
        key = next((k for k in blocks if h.lower() in k), None)
        if key is None:
            absent.append(h)
        elif len(blocks[key].strip()) < min_chars:
            thin.append(f"{h} ({len(blocks[key].strip())} chars)")
    if absent or thin:
        bits = []
        if absent:
            bits.append("absent: " + ", ".join(absent))
        if thin:
            bits.append(f"under {min_chars} chars: " + ", ".join(thin))
        return Result(
            False,
            "notes_populated",
            f"{rel} -> " + "; ".join(bits),
            ["notes.md is what Introduction and Discussion are built from. Thin notes now means invented prose later."],
        )
    return Result(True, "notes_populated", f"{rel}: all {len(required)} note section(s) substantive")


PRECEDENT_ITEMS = ("comparator", "denominator", "primary outcome")
PRECEDENT_RE = re.compile(
    r"(?im)^\s*[-*]?\s*(comparator|denominator|primary\s+outcome)[^:\n]*:\s*"
    r"(precedent\s+yes|precedent\s+no|not\s+applicable)\b(.*)$")


@check("design_precedent_recorded")
def design_precedent_recorded(ctx: Ctx) -> Result:
    """Key design choices carry a literature precedent or an explicit methodological defence."""
    rel = ctx.spec["path"]
    if not ctx.p(rel).is_file():
        return Result(False, "design_precedent_recorded", f"{rel} missing")
    found: dict[str, tuple[str, str]] = {}
    for m in PRECEDENT_RE.finditer(ctx.read(rel)):
        found[re.sub(r"\s+", " ", m.group(1).lower())] = (m.group(2).lower(), m.group(3))
    problems = []
    for item in PRECEDENT_ITEMS:
        if item not in found:
            problems.append(f"no '{item.capitalize()}: precedent yes|no' line")
            continue
        verdict, rest = found[item]
        if verdict.endswith("yes") and not re.search(r"\b\d{7,8}\b|10\.\d{4,}/|\[@", rest):
            problems.append(f"{item}: precedent yes needs a PMID, DOI or [@citekey]")
        elif not verdict.endswith("yes") and len(re.sub(r"(?i)^\W*justification\s*:", "", rest).strip()) < 20:
            problems.append(f"{item}: no precedent needs a methodological justification (>= 20 chars)")
    if problems:
        return Result(False, "design_precedent_recorded", f"{rel}: " + "; ".join(problems),
                      ["Add a 'Design precedent' section: one line each for Comparator, Denominator "
                       "and Primary outcome - 'precedent yes - <PMID/DOI>' or 'precedent no - "
                       "justification: <why this choice is still sound>'."])
    return Result(True, "design_precedent_recorded",
                  "comparator, denominator and primary outcome each have a precedent or a defence")


@check("no_ai_boilerplate")
def no_ai_boilerplate(ctx: Ctx) -> Result:
    rel = ctx.spec["path"]
    if not ctx.p(rel).exists():
        if ctx.spec.get("optional", False):
            return Result(True, "no_ai_boilerplate", f"{rel}: optional file absent")
        return Result(False, "no_ai_boilerplate", f"{rel} missing")
    raw = ctx.read(rel)
    low = _body(raw).lower()
    hard = [ph for ph in PLACEHOLDERS if ph.lower() in low]
    if hard:
        return Result(
            False,
            "no_ai_boilerplate",
            f"{rel} still contains placeholder text: " + ", ".join(sorted(set(hard))),
            ["Resolve every placeholder from real data or delete the sentence."],
        )
    leaks = unallowed(backstage_hits(raw) + deviation_hits(raw, ctx.project),
                      polish_allowed(ctx.project))  # 1.14.1 (B7): the paper's allowlist
    if leaks:
        return Result(
            False, "no_ai_boilerplate",
            f"{rel} describes the pipeline's own review/draft/plan history: "
            + "; ".join(leaks[:5]),
            ["Delete it and simply describe the analysis performed. Never narrate an initial "
             "plan, protocol deviations or their handling, an internal review or an earlier "
             "draft (a registered meta-analysis reports deviations per PRISMA 2020 item 24c)."])
    soft = [ph for ph in AI_TELLS if ph in low]
    if soft:
        return Result(
            False,
            "no_ai_boilerplate",
            f"{rel}: machine-sounding phrasing -> " + "; ".join(soft[:8]),
            ["Rewrite these clauses in plain clinical prose. Warning only; it does not block."],
            severity="warn",
        )
    return Result(True, "no_ai_boilerplate", f"{rel}: no placeholders, no stock phrasing")


# ---------------------------------------------------------------------------
# 1.9.0 (#3): body text is continuous prose. A real run produced ~60 list items in Methods and
# Results; medical journals almost never print them and readers take them for generated text.
# ---------------------------------------------------------------------------
LIST_ITEM_RE = re.compile(r"(?m)^[ \t]{0,3}(?:[-*+\u2022]|\d{1,2}[.)]|\(?[a-z]\))[ \t]+\S")
BODY_SECTIONS = {"introduction", "background", "methods", "materials and methods",
                 "patients and methods", "results", "discussion", "conclusion", "conclusions"}


def list_density(text: str, whole_file: bool = False) -> tuple[int, int, list[str]]:
    """(list items, prose paragraphs, sections holding lists) in the body sections.

    A full manuscript is split on level-1 headings and only its body sections count (the
    references, legends and declarations are not prose); a section file counts as a whole."""
    text = FENCE_RE.sub(" ", text)
    if whole_file or not re.search(r"(?m)^#\s+\S", text):
        blocks = [("file", text)]
    else:
        parts = re.split(r"(?m)^#\s+(.+)$", text)
        blocks = [(parts[i].strip().casefold(), parts[i + 1]) for i in range(1, len(parts) - 1, 2)
                  if parts[i].strip().casefold() in BODY_SECTIONS]
    items = paras = 0
    where = []
    for name, block in blocks:
        n = len(LIST_ITEM_RE.findall(block))
        prose = [p for p in re.split(r"\n\s*\n", LIST_ITEM_RE.sub("", block))
                 if p.strip() and not p.lstrip().startswith("#") and len(p.split()) >= 8]
        items += n
        paras += len(prose)
        if n:
            where.append(f"{name} {n}")
    return items, paras, where


def prose_list_problem(text: str, items_max: int, share_max: float,
                       whole_file: bool = False) -> str | None:
    items, paras, where = list_density(text, whole_file)
    share = items / max(1, items + paras)
    if items > items_max or (items >= 2 and share > share_max):
        return (f"{items} list item(s) in body text ({', '.join(where)}; {share:.0%} of blocks; "
                f"limits {items_max} items / {share_max:.0%})")
    return None


@check("prose_not_lists")
def prose_not_lists(ctx: Ctx) -> Result:
    """Methods/Results/Introduction/Discussion are written as paragraphs; results in sentences."""
    rels = ctx.spec.get("paths") or [ctx.spec.get("path", "07_manuscript/full_manuscript.md")]
    items_max = int(ctx.spec.get("max_items", ctx.target("body_list_items_max", 3)))
    share_max = float(ctx.spec.get("max_share", ctx.target("body_list_share_max", 0.10)))
    problems, seen = [], 0
    for rel in rels:
        if not ctx.p(rel).is_file():
            continue
        seen += 1
        name = Path(rel).name
        bad = prose_list_problem(ctx.read(rel), items_max, share_max,
                                 whole_file=name != "full_manuscript.md")
        if bad:
            problems.append(f"{rel}: {bad}")
    if problems:
        return Result(False, "prose_not_lists", "; ".join(problems),
                      ["Rewrite the lists as continuous paragraphs: criteria, steps, covariates "
                       "and sensitivity results all read as sentences in a medical journal.",
                       "Thresholds: [targets] body_list_items_max / body_list_share_max "
                       "(paper config may change them)."])
    return Result(True, "prose_not_lists", f"{seen} file(s): body text is continuous prose")


_PY_PLOT_RES = (
    re.compile(r"\b(?:import|from)\s+(matplotlib|seaborn|plotly|altair|bokeh|plotnine)\b"),
    re.compile(r"\b(plt)\."),
    re.compile(r"\.(savefig)\s*\("),
    re.compile(r"\.(plot)\s*\("),
    re.compile(r"\.(hist)\s*\("),
    re.compile(r"\.(plot_\w+)\s*\("),
)
_R_PLOT_RE = re.compile(
    r"(?<![\w.])(?:[A-Za-z][\w.]*::)?(love\.plot|bal\.plot|plot\.roc|densityplot|xyplot|bwplot|"
    r"stripplot|dotplot|funnel|qqnorm|qqline|ggforest|ggcoxzph|plot|hist|barplot|boxplot|lines|"
    r"points|abline|segments|polygon|par|layout|image|heatmap|pheatmap|matplot|curve|pairs|"
    r"coplot|stripchart|dotchart|qplot|ggroc|forestplot|forest|grid\.draw|grid\.newpage|png|pdf|"
    r"tiff|jpeg|bmp|svg|svglite|agg_\w+|dev\.off|dev\.new|ggsurvplot|ggsurvfit|ggsave|ggplot)"
    r"\s*\(")
_LEGACY_BANNED = ["matplotlib", "seaborn", "plotly", "savefig", "plt.", "ggplot",
                  "ggsave", "pyplot", "altair", "bokeh"]


def plot_calls(name: str, text: str) -> list[str]:
    """Plotting calls in one exploratory script (comments and string contents ignored)."""
    from ..codescan import scan_py, scan_r
    suffix = name.rsplit(".", 1)[-1].casefold() if "." in name else ""
    if suffix == "py":
        code, _ = scan_py(text)
        return sorted({m.group(1) for rx in _PY_PLOT_RES for m in rx.finditer(code)})
    if suffix in ("r", "rmd", "qmd"):
        code, _ = scan_r(text)
        return sorted({m.group(1) for m in _R_PLOT_RE.finditer(code)})
    low = text.lower()
    return sorted({b for b in _LEGACY_BANNED if b in low})


@check("no_plot_calls")
def no_plot_calls(ctx: Ctx) -> Result:
    """Exploratory analysis must not produce figures."""
    hits = []
    for p in ctx.glob(ctx.spec["glob"]):
        try:
            src = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        found = plot_calls(p.name, src)
        if found:
            hits.append(f"{p.name}: {', '.join(found)}")
    if hits:
        return Result(
            False,
            "no_plot_calls",
            "plotting code in the exploratory stage -> " + "; ".join(hits),
            ["Exploratory analysis is numbers only. Figures are built in S11 from the approved artifact plan."],
        )
    return Result(True, "no_plot_calls", "exploratory code contains no plotting")
