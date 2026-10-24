"""Numeric provenance.

Rule enforced here: a number may appear in the manuscript or in a table only if
executed code already wrote it to 03_analysis/results/*.json. This is what stops
plausible-looking statistics from being invented during writing.
"""
from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation

from .. import xlsxlite
from . import Ctx, Result, check

RESULTS_GLOB = "03_analysis/results/*.json"
ALLOWLIST = "03_analysis/results/number_allowlist.tsv"

# Numbers that are conventions rather than findings.
CONVENTIONS = {
    "95", "99", "90", "100", "0.05", "0.01", "0.001", "0.025", "1.96", "0.5",
    "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "0",
}

CITE_RE = re.compile(r"\[@[^\]]*\]")
FENCE_RE = re.compile(r"```.*?```", re.S)
ARTIFACT_RE = re.compile(
    r"\b(?:supplementary\s+)?(?:fig(?:ure)?s?|tables?|panels?|appendix|eq(?:uation)?s?)\.?\s*"
    r"[A-Za-z]?\d+[A-Za-z]?(?:\s*[-,and]+\s*[A-Za-z]?\d+[A-Za-z]?)*",
    re.I,
)
# A sign directly attached to a number is part of it: "-0.42" and "−0.42" (U+2212) are the
# same finding, and "0.42" is a different one.
MINUS = "\u2212"
NUM_RE = re.compile(r"(?<![\w.])([+\-\u2212]?\d+(?:\.\d+)?)(?![\w])")
# P-value thresholds. "P<0.001" is a claim about a result, not a convention: some reported
# P value must actually be below 0.001.
P_RE = re.compile(r"\b[Pp]\s*([<>=\u2264\u2265])\s*(0?\.\d+(?:[eE][+-]?\d+)?)\b")
P_STATED_RE = re.compile(r"([<>\u2264\u2265])\s*(0?\.\d+)")


def _plain(token: str) -> str:
    return token.replace(MINUS, "-").lstrip("+")


# ---------------------------------------------------------------------------
# building the pool of legitimate values
# ---------------------------------------------------------------------------
def _walk(obj, sink: set[str]) -> None:
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        sink.add(_norm(obj))
        return
    if isinstance(obj, str):
        for m in NUM_RE.finditer(obj):
            sink.add(_norm(m.group(1)))
        return
    if isinstance(obj, dict):
        for v in obj.values():
            _walk(v, sink)
        return
    if isinstance(obj, (list, tuple)):
        for v in obj:
            _walk(v, sink)


def _norm(v) -> str:
    try:
        f = float(_plain(v) if isinstance(v, str) else v)
    except (TypeError, ValueError):
        return str(v)
    if f == int(f) and abs(f) < 1e15:
        return str(int(f))
    return repr(round(f, 10))


def _stated_thresholds(obj, sink: set[tuple[str, str]]) -> None:
    """P thresholds the analysis itself wrote as text, e.g. a formatted "<0.001"."""
    if isinstance(obj, str):
        for op, tok in P_STATED_RE.findall(obj):
            sink.add((op, _norm(tok)))
    elif isinstance(obj, dict):
        for v in obj.values():
            _stated_thresholds(v, sink)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _stated_thresholds(v, sink)


def _pool(ctx: Ctx, stated: set[tuple[str, str]] | None = None
          ) -> tuple[set[float], set[str], list[str]]:
    """-> (float pool, raw-string pool, source file names)"""
    strings: set[str] = set()
    sources: list[str] = []
    for p in ctx.glob(RESULTS_GLOB):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        sources.append(p.name)
        if isinstance(data, dict) and "environment" in data:
            # The environment receipt (package versions, seed, timestamps) is provenance of the
            # run, never of a manuscript number. Only the writers' top-level key is dropped.
            data = {k: v for k, v in data.items() if k != "environment"}
        _walk(data, strings)
        if stated is not None:
            _stated_thresholds(data, stated)
    floats: set[float] = set()
    for s in strings:
        try:
            floats.add(float(s))
        except ValueError:
            pass
    return floats, strings, sources


def _explicit_allowlist(ctx: Ctx) -> set[str]:
    """Tokens the paper declared in number_allowlist.tsv (with a reason), without conventions."""
    allowed: set[str] = set()
    p = ctx.p(ALLOWLIST)
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            token = line.split("\t")[0].strip()
            if token:
                allowed.add(token)
    return allowed


def _allowlist(ctx: Ctx) -> set[str]:
    return set(CONVENTIONS) | _explicit_allowlist(ctx)


def _decimals(token: str) -> int:
    try:
        exponent = Decimal(_plain(token)).as_tuple().exponent
    except InvalidOperation:
        return 0
    return max(0, -exponent) if isinstance(exponent, int) else 0


def _matches(token: str, floats: set[float], strings: set[str]) -> bool:
    if token in strings or _plain(token) in strings:
        return True
    try:
        val = float(_plain(token))
    except ValueError:
        return False
    if val in floats:
        return True
    # Tolerate rounding to the precision the author displayed, never a flipped sign.
    dp = _decimals(token)
    for f in floats:
        if (f < 0) != (val < 0) and f != 0 and val != 0:
            continue
        if round(f, dp) == val:
            return True
        if dp == 0 and abs(f - val) < 0.5 and f != 0:
            return True
    return False


def _scrub(text: str) -> str:
    text = FENCE_RE.sub(" ", text)
    text = CITE_RE.sub(" ", text)
    text = ARTIFACT_RE.sub(" ", text)
    text = re.sub(r"^\s*#{1,6}\s.*$", " ", text, flags=re.M)
    text = re.sub(r"\b(19|20)\d{2}\s*[-\u2013]\s*(19|20)?\d{2}\b", " ", text)  # not scrubbed values
    return text


def _p_ok(op: str, token: str, floats, stated, explicit) -> bool:
    """Is a stated P threshold backed by an executed result?"""
    if token in explicit:
        return True  # declared in number_allowlist.tsv with a reason (e.g. an alpha in Methods)
    if (op, _norm(token)) in stated:
        return True  # the analysis itself wrote this formatted threshold
    threshold = float(token)
    candidates = [f for f in floats if 0 <= f <= 1]
    if op == "<":
        return any(f < threshold for f in candidates)
    if op == "\u2264":
        return any(f <= threshold for f in candidates)
    if op == ">":
        return any(f > threshold for f in candidates)
    if op == "\u2265":
        return any(f >= threshold for f in candidates)
    return _matches(token, set(candidates), {_norm(f) for f in candidates})


_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?!\[@)")


def _discussion_lines(text: str, whole: bool) -> set[int]:
    """1-based line numbers of Discussion prose (the whole file for discussion.md)."""
    lines = text.splitlines()
    if whole:
        return set(range(1, len(lines) + 1))
    out, inside = set(), False
    for i, line in enumerate(lines, start=1):
        m = re.match(r"^#\s+(.+?)\s*$", line)
        if m:
            inside = m.group(1).strip().casefold() == "discussion"
            continue
        if inside:
            out.add(i)
    return out


def cite_external_numbers(text: str, lines: set[int], verified: set[str]) -> str:
    """1.10.0 (#7): in the Discussion, a prior study's number is allowed only in the same
    sentence as a citation of that study, every key of which is in the verified library.
    Those numbers are blanked; any other number still needs results-JSON provenance."""
    out = text.splitlines()
    for i in lines:
        if i - 1 >= len(out):
            continue
        parts = _SENT_SPLIT.split(out[i - 1])
        for j, sent in enumerate(parts):
            keys = [k for g in re.findall(r"\[([^\]]*@[^\]]*)\]", sent)
                    for k in re.findall(r"@([A-Za-z][\w:.#$%&+?<>~/-]*)", g)]
            if keys and all(k in verified for k in keys):
                parts[j] = CITE_RE.sub(" ", sent)
                parts[j] = NUM_RE.sub(" ", P_RE.sub(" ", parts[j]))
        out[i - 1] = " ".join(parts)
    return "\n".join(out)


def _verified_keys(ctx: Ctx) -> set[str]:
    from .refs import BIB, _verified_map, bib_keys
    if not ctx.p(BIB).is_file():
        return set()
    ver = _verified_map(ctx)
    return {k for k in bib_keys(ctx.read(BIB)) if (ver.get(k, {}) or {}).get("verified") is True}


def _offenders(text: str, floats, strings, allowed, stated=frozenset(),
               explicit=frozenset(), strict_lines=frozenset()) -> list[tuple[int, str]]:
    bad: list[tuple[int, str]] = []
    base_allowed, base_explicit = allowed, explicit
    for lineno, raw in enumerate(_scrub(text).splitlines(), start=1):
        # 1.10.0 (#7): number_allowlist.tsv is no side path into the Discussion.
        allowed, explicit = ((CONVENTIONS, frozenset()) if lineno in strict_lines
                             else (base_allowed, base_explicit))
        def pvalue(match, _lineno=lineno):
            op, token = match.groups()
            if not _p_ok(op, token, floats, stated, explicit):
                bad.append((_lineno, "P" + op + token))
            return " "
        raw = P_RE.sub(pvalue, raw)
        # A formatted table cell carries the threshold without the P label.
        if re.fullmatch(r"\s*[<\u2264]\s*0?\.\d+\s*", raw):
            raw = P_RE.sub(pvalue, "P" + raw.strip())
        for m in NUM_RE.finditer(raw):
            tok = m.group(1)
            if tok in allowed or _plain(tok) in allowed:
                continue
            if _matches(tok, floats, strings):
                continue
            bad.append((lineno, tok))
    return bad


# ---------------------------------------------------------------------------
# checks
# ---------------------------------------------------------------------------
@check("numbers_have_provenance")
def numbers_have_provenance(ctx: Ctx) -> Result:
    source = ctx.spec.get("source", "markdown")
    if source != "tables":
        rel = ctx.spec["path"]
        if not ctx.p(rel).exists():
            if ctx.spec.get("optional", False):
                return Result(True, "numbers_have_provenance", f"{rel}: optional file absent")
            return Result(False, "numbers_have_provenance", f"{rel} missing")

    stated: set[tuple[str, str]] = set()
    floats, strings, sources = _pool(ctx, stated)
    if not sources:
        return Result(
            False,
            "numbers_have_provenance",
            f"no result files under {RESULTS_GLOB}",
            ["Analysis code must dump every reported statistic to JSON before any prose is written."],
        )
    allowed = _allowlist(ctx)
    explicit = _explicit_allowlist(ctx)
    if source == "tables":
        offenders = []
        for p in ctx.glob("04_tables/main/*.xlsx") + ctx.glob("04_tables/supplementary/*.xlsx"):
            try:
                cells = xlsxlite.numeric_cell_values(p)
            except Exception as exc:  # noqa: BLE001 - report, do not crash the gate
                return Result(False, "numbers_have_provenance", f"cannot read {p.name}: {exc}")
            for sheet, ref, val in cells:
                if _offenders(str(val), floats, strings, allowed, stated, explicit):
                    offenders.append(f"{p.name}[{sheet}]!{ref}={val}")
        if offenders:
            uniq = sorted(set(offenders))
            return Result(
                False,
                "numbers_have_provenance",
                f"{len(uniq)} table value(s) not traceable to results JSON: " + "; ".join(uniq[:8]),
                [
                    "Tables must be generated from 03_analysis/results/*.json, not retyped.",
                    f"If a value is a legitimate constant, add it to {ALLOWLIST} with a reason.",
                ],
            )
        return Result(True, "numbers_have_provenance", f"all table values trace to {len(sources)} result file(s)")

    text = FENCE_RE.sub(" ", ctx.read(rel))
    disc = _discussion_lines(text, whole=rel.replace("\\", "/").endswith("discussion.md"))
    if disc:
        text = cite_external_numbers(text, disc, _verified_keys(ctx))
    bad = _offenders(text, floats, strings, allowed, stated, explicit, disc)
    if bad:
        shown = "; ".join(f"line {ln}: {tok}" for ln, tok in bad[:10])
        return Result(
            False,
            "numbers_have_provenance",
            f"{rel}: {len(bad)} number(s) with no provenance -> {shown}",
            [
                "Every statistic must already exist in 03_analysis/results/*.json, written by executed code.",
                f"For genuine constants (thresholds, conventions), add them to {ALLOWLIST} as 'value<TAB>reason' (never applies in the Discussion).",
                "Discussion: a prior study's number must sit in the same sentence as [@key] of that study (verified library).",
                "A 'P<0.001' needs a reported P value below 0.001; a sign must match the result's sign.",
                "Do not fix this by rounding differently. Re-run the analysis and dump the value.",
            ],
        )
    return Result(True, "numbers_have_provenance", f"{rel}: every number traces to results JSON")


@check("numbers_cross_match")
def numbers_cross_match(ctx: Ctx) -> Result:
    """Numbers attributed to 'Table N' in Results must actually appear in Table N."""
    rel = "07_manuscript/results.md"
    if not ctx.p(rel).exists():
        return Result(False, "numbers_cross_match", f"{rel} missing")
    try:
        plan = ctx.read_json("01_protocol/artifact_plan.json")
    except Exception:  # noqa: BLE001
        return Result(False, "numbers_cross_match", "artifact_plan.json unreadable")

    table_files: dict[str, list] = {}
    for entry in plan.get("main_tables", []) + plan.get("supp_tables", []):
        label = str(entry.get("id", "")).strip()
        fp = entry.get("file")
        if not label or not fp:
            continue
        p = ctx.p(fp)
        if p.exists():
            try:
                table_files[label.lower()] = [v for _, _, v in xlsxlite.numeric_cell_values(p)]
            except Exception:  # noqa: BLE001
                table_files[label.lower()] = []

    if not table_files:
        return Result(False, "numbers_cross_match", "no rendered tables found to cross-match against")

    allowed = _allowlist(ctx)
    text = FENCE_RE.sub(" ", ctx.read(rel))
    sentences = re.split(r"(?<=[.;])\s+", text)
    problems: list[str] = []
    checked = 0
    for sent in sentences:
        refs = re.findall(r"\b((?:supplementary\s+)?table\s*S?\d+)\b", sent, re.I)
        if not refs:
            continue
        pool: set[str] = set()
        matched_label = None
        for r in refs:
            key = re.sub(r"\s+", " ", r.strip().lower())
            for label, vals in table_files.items():
                if key.endswith(label.split()[-1]) or label in key:
                    matched_label = label
                    for v in vals:
                        for m in NUM_RE.finditer(str(v)):
                            pool.add(m.group(1))
        if not pool:
            continue
        checked += 1
        body = ARTIFACT_RE.sub(" ", CITE_RE.sub(" ", sent))
        for m in NUM_RE.finditer(body):
            tok = m.group(1)
            if tok in allowed or tok in pool:
                continue
            if any(abs(float(_plain(tok)) - float(_plain(v))) < 10 ** -_decimals(tok)
                   for v in pool if _is_num(v)):
                continue
            problems.append(f"{tok} cited to {matched_label} but absent from it")
    if problems:
        uniq = sorted(set(problems))
        return Result(
            False,
            "numbers_cross_match",
            f"{len(uniq)} mismatch(es): " + "; ".join(uniq[:8]),
            ["Either the sentence cites the wrong table or the table was built from different values."],
        )
    return Result(
        True,
        "numbers_cross_match",
        f"{checked} table-citing sentence(s) agree with the rendered tables",
    )


def _is_num(v) -> bool:
    try:
        float(_plain(str(v)))
        return True
    except (TypeError, ValueError):
        return False
