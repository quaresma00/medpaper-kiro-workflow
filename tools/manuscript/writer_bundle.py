#!/usr/bin/env python3
"""1.12.0 (E3): the clinical writer's bundle - clinical-facing material only.

    python tools/manuscript/writer_bundle.py build --stage S09_results [--target REL] [--project DIR]
    python tools/manuscript/writer_bundle.py lint  --stage S09_results

`build` writes .wf/writer_bundle/<stage>/ for the `medpaper-clinical-writer` agent:

    MANIFEST.md              the brief, the file to write, the soft word budget, the file list
    display_dictionary.md    clinical label, abbreviation and definition of every term
    results_in_words.md      results JSON rendered as sentences with clinical labels
    tables.md / legends.md   final table text and figure legends (internal names replaced)
    protocol_summary.md      the final protocol without code, paths or identifiers
    deepread_notes.md        S16/S19: the deep-read notes
    library.md               citekeys with author, year and title
    journal_profile.md       provisional or chosen journal parameters, in words
    exemplars.md             2-3 benchmark paragraphs when the paper keeps them
    current_draft.md         the section as it stands (rewrites)

No analysis code, script, raw JSON key, log or path reaches the bundle: internal names are
replaced by their clinical labels. 1.14.0 (B): results JSON is walked through dicts AND lists;
each estimate keeps population, comparison (exposure vs reference), outcome, measure, unit,
time window, estimate, interval with its recorded confidence level (ci_level / conf_level /
level / alpha, else environment.ci_level; never assumed 95%), P and n. Anything that cannot
be named clinically is a gap listed in .wf/writer_bundle/<stage>_GAPS.md (outside the
writer's folder); `build` exits 2 and the S09 gate writer_results_mapped fails while a
required result is a gap. Inline code and code-like identifiers are mapped through the
dictionary, or replaced by a visible placeholder and listed - never silently deleted. `lint`
(also run by `build`) checks the bundle with the engineering-language rules and for internal
names.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wfcore import clinical, journalspec, paths as wfpaths  # noqa: E402

BUNDLE_DIR = ".wf/writer_bundle"
TARGETS = {"S08_methods": "07_manuscript/methods.md", "S09_results": "07_manuscript/results.md",
           "S14_introduction": "07_manuscript/introduction.md",
           "S16_discussion": "07_manuscript/discussion.md",
           "S19_human_review": "07_manuscript/full_manuscript.md"}
BUDGET_KEYS = {"S14_introduction": "intro_words_max", "S16_discussion": "discussion_words_max"}
STAT_WORDS = {
    "n": "number", "count": "number", "total": "total number", "events": "number of events",
    "pct": "percentage", "percent": "percentage", "prop": "proportion", "rate": "rate",
    "mean": "mean", "sd": "standard deviation", "median": "median", "iqr": "interquartile range",
    "q1": "lower quartile", "q3": "upper quartile", "min": "minimum", "max": "maximum",
    "hr": "hazard ratio", "or": "odds ratio", "rr": "relative risk", "ror": "reporting odds ratio",
    "prr": "proportional reporting ratio", "irr": "incidence rate ratio", "rd": "risk difference",
    "beta": "regression coefficient", "estimate": "estimate", "auc": "area under the curve",
    "p": "P value", "pvalue": "P value", "p_value": "P value",
}
# 1.14.0 (B): interval limits, levels, P values and counts are read as parts of one estimate.
MEASURES = {"hr", "or", "rr", "ror", "prr", "irr", "rd", "beta", "auc", "estimate", "est",
            "coef", "effect", "value", "md", "smd", "ratio", "difference"}
LOW_KEYS = {"low", "lower", "lcl", "ll", "lo", "ci_low", "ci_lower", "conf_low", "lower_ci"}
HIGH_KEYS = {"high", "upper", "ucl", "ul", "hi", "ci_high", "ci_upper", "conf_high", "upper_ci"}
LEVEL_KEYS = ("ci_level", "conf_level", "conf.level", "confidence_level", "level", "alpha")
P_KEYS = {"p", "pvalue", "p_value", "p.value", "pval"}
N_KEYS = {"n", "count", "events", "total", "denominator", "numerator", "n_total", "n_events"}
CONTEXT_KEYS = {
    "population": ("population", "cohort", "sample", "subgroup", "stratum", "set"),
    "comparison": ("comparison", "contrast", "exposure", "term", "group", "arm", "treatment"),
    "reference": ("reference", "comparator", "ref", "versus", "vs"),
    "outcome": ("outcome", "endpoint", "event"),
    "measure": ("measure", "scale", "metric", "statistic", "effect_measure", "type"),
    "unit": ("unit", "units"),
    "time": ("time", "timepoint", "time_point", "window", "horizon", "follow_up", "period",
             "landmark"),
    "label": ("label", "name", "analysis", "model"),
}
CONTAINERS = {"estimates", "results", "models", "rows", "items", "data", "values", "records",
              "table", "list", "groups", "by_group", "subgroups", "strata", "terms", "contrasts",
              "comparisons", "outcomes", "analyses", "effects", "coefficients"}
SKIP_KEYS = {"environment", "meta", "metadata", "provenance", "script", "inputs", "outputs",
             "schema", "seed", "written_at"}
_IDENT = re.compile(r"(?<![@\w-])[a-z][a-z0-9]*(?:_[a-z0-9]+)+(?![\w-])")
_PATH = re.compile(r"(?:[A-Za-z]:[\\/]|\b(?:0\d_\w+|tools|temp|\.wf)[\\/])[^\s)]*"
                   r"|\b[\w-]+\.(?:py|R|r|json|csv|xlsx|log|toml|txt)\b")
_PLAIN = re.compile(r"^[A-Za-z][a-z]{2,}$")
UNMAPPED = "[term without a clinical label]"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""


def _json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _code_like(s: str) -> bool:
    return bool(_IDENT.fullmatch(s) or clinical._CODE_ID.match(s) or "_" in s)


def clean(text: str, names: dict[str, str], gaps: list[str] | None = None,
          where: str = "") -> str:
    """Clinical labels for internal names; code blocks and paths removed. 1.14.0 (B): inline
    code and code-like identifiers are mapped through the display dictionary, never silently
    deleted - an unmapped one becomes a visible placeholder and is listed in `gaps`."""
    text = re.sub(r"```.*?```", "", text, flags=re.S)

    def term(raw: str) -> str:
        raw = raw.strip()
        for name, label in names.items():
            if raw.casefold() == name.casefold():
                return label
        if _code_like(raw) or _PATH.fullmatch(raw):
            if gaps is not None:
                gaps.append(f"{where}: '{raw}' has no clinical label (display dictionary)")
            return UNMAPPED
        return raw
    text = re.sub(r"`([^`\n]*)`", lambda m: term(m.group(1)) if m.group(1).strip() else "", text)
    for name, label in sorted(names.items(), key=lambda kv: -len(kv[0])):
        text = re.sub(rf"(?<![\w-]){re.escape(name)}(?![\w-])", label, text)
    text = _PATH.sub("", text)
    text = journalspec.PIPELINE_CODE_RE.sub("", text)
    return _IDENT.sub(lambda m: term(m.group(0)), text)


def _label_for(key: str, names: dict[str, str], labels_ci: dict[str, str]) -> str | None:
    return names.get(key) or labels_ci.get(key.casefold())


def _stat(key: str) -> str | None:
    k = key.casefold()
    if k in STAT_WORDS:
        return STAT_WORDS[k]
    head, _, tail = k.rpartition("_")
    if head in STAT_WORDS and tail in STAT_WORDS:
        return f"{STAT_WORDS[tail]} of the {STAT_WORDS[head]}"
    return None


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _level(d: dict, inherited: float | None) -> float | None:
    """The interval's confidence level in percent, from the record or an ancestor."""
    for key in LEVEL_KEYS:
        v = d.get(key)
        if _num(v):
            if key == "alpha":
                return round((1 - float(v)) * 100, 6)
            return round(float(v) * 100, 6) if float(v) <= 1 else float(v)
    return inherited


def _pct(level: float) -> str:
    return f"{level:g}"


def results_in_words(project: Path, data: dict | None) -> tuple[list[str], list[str]]:
    """Result sentences with clinical labels, and the gaps: every numeric result whose context
    cannot be named clinically, and every interval without a recorded confidence level. Dicts
    and lists are walked alike (1.14.0, B)."""
    names = clinical.internal_names(data)
    labels_ci = {lab.casefold(): lab for lab in clinical.labels(data)}
    ignored = {str(x.get("key", "")).casefold() for x in (data or {}).get("not_reported", []) or []
               if isinstance(x, dict) and len(str(x.get("reason", "")).strip()) >= 10}
    lines: list[str] = []
    gaps: list[str] = []
    files = sorted((project / "03_analysis/results").glob("*.json"))
    for i, f in enumerate(files, 1):
        doc = _json(f)
        if not isinstance(doc, (dict, list)):
            continue
        env = doc.get("environment") if isinstance(doc, dict) else None
        root_level = _level(env, None) if isinstance(env, dict) else None
        out: list[str] = []
        where_file = f"result set {i} ({f.stem})"

        def name_of(raw, where) -> str | None:
            """Clinical name of a key or value; None when it is code without a label."""
            s = str(raw).strip()
            lab = _label_for(s, names, labels_ci)
            if lab:
                return lab
            if s.casefold() in CONTAINERS:
                return ""
            if _code_like(s):
                gaps.append(f"{where_file} {where}: '{s}' has no clinical label")
                return None
            return s

        def context_of(d: dict, where: str) -> tuple[list[str], dict, bool]:
            ctx, extra, ok = [], {}, True
            for slot, keys in CONTEXT_KEYS.items():
                for k in keys:
                    v = d.get(k)
                    if isinstance(v, str) and v.strip():
                        lab = name_of(v, f"{where}.{k}")
                        if lab is None:
                            ok = False
                        elif lab:
                            extra[slot] = lab
                        break
            if extra.get("reference") and extra.get("comparison"):
                ctx.append(f"{extra['comparison']} vs {extra['reference']}")
            elif extra.get("comparison"):
                ctx.append(extra["comparison"])
            for slot in ("outcome", "population", "time", "label"):
                if extra.get(slot):
                    ctx.append(f"{slot}: {extra[slot]}" if slot in ("population", "time")
                               else extra[slot])
            return ctx, extra, ok

        def record(d: dict, trail: list[str], where: str, level: float | None) -> None:
            ctx, extra, ok = context_of(d, where)
            context = [c for c in trail if c] + ctx or ([fallback] if fallback else [])
            parts: dict[str, dict] = {}
            for k, v in d.items():
                if not _num(v) or k.casefold() in ignored or k.casefold() in SKIP_KEYS:
                    continue
                kk = k.casefold().replace(".", "_")
                if kk in LEVEL_KEYS or k in LEVEL_KEYS:
                    continue
                head, _, tail = kk.rpartition("_")
                if kk in P_KEYS:
                    parts.setdefault("", {})["p"] = v
                elif kk in LOW_KEYS or (tail in LOW_KEYS and head):
                    parts.setdefault("" if kk in LOW_KEYS or head == "ci" else head, {})["low"] = v
                elif kk in HIGH_KEYS or (tail in HIGH_KEYS and head):
                    parts.setdefault("" if kk in HIGH_KEYS or head == "ci" else head, {})["high"] = v
                elif kk in MEASURES:
                    parts.setdefault(kk if kk in STAT_WORDS and kk != "estimate" else "", {})["est"] = v
                elif kk in N_KEYS:
                    parts.setdefault("", {}).setdefault("n", []).append((kk, v))
                elif _stat(k):
                    out.append(f"- {_stat(k)[:1].upper() + _stat(k)[1:]}"
                               + (f", {', '.join(context)}" if context else "") + f": {v}")
                elif kk.startswith("n_") and _PLAIN.match(kk[2:]):
                    parts.setdefault("", {}).setdefault("n", []).append((kk, v))
                else:
                    own = _label_for(k, names, labels_ci)
                    if own is None:
                        gaps.append(f"{where_file} {where}.{k}: result value {v} has no clinical "
                                    "label")
                        continue
                    out.append(f"- {own}" + (f" ({', '.join(context)})" if context else "")
                               + f": {v}")
            if not parts:
                return
            if not ok or (not context and not extra.get("measure")
                          and not any(h for h in parts)):
                gaps.append(f"{where_file} {where}: an estimate whose population or comparison "
                            "has no clinical label")
                return
            shared = parts.get("", {})
            for head, part in sorted(parts.items(), key=lambda kv: kv[0] != ""):
                if head == "" and "est" not in part and len(parts) > 1:
                    continue
                if head and "est" not in part:
                    part = {**part, "est": d.get(head)} if _num(d.get(head)) else part
                if "est" not in part and "low" not in part and "high" not in part \
                        and "p" not in part:
                    for nk, nv in part.get("n", []):
                        word = STAT_WORDS.get(nk) or ("number " + nk[2:] if nk.startswith("n_") else nk)
                        out.append(f"- {word[:1].upper() + word[1:]}"
                                   + (f", {', '.join(context)}" if context else "") + f": {nv}")
                    continue
                measure = (STAT_WORDS.get(head) or STAT_WORDS.get(str(extra.get("measure", "")).casefold())
                           or extra.get("measure") or ("estimate" if "est" in part else "number"))
                bits = []
                if "est" in part:
                    bits.append(str(part["est"]))
                low, high = part.get("low", shared.get("low")), part.get("high", shared.get("high"))
                if low is not None or high is not None:
                    if level is None:
                        gaps.append(f"{where_file} {where}: CI level not recorded")
                        lvl = "CI level not recorded; "
                    else:
                        lvl = f"{_pct(level)}% CI "
                    bits.append(f"({lvl}{low if low is not None else '?'} to "
                                f"{high if high is not None else '?'})")
                p = part.get("p", shared.get("p"))
                if p is not None:
                    bits.append(f"P = {p}")
                for nk, nv in part.get("n", shared.get("n", [])):
                    bits.append(f"{STAT_WORDS.get(nk) or nk.replace('_', ' ')} = {nv}")
                if extra.get("unit"):
                    bits.append(f"unit: {extra['unit']}")
                if not bits:
                    continue
                out.append(f"- {measure[:1].upper() + measure[1:]}"
                           + (f", {', '.join(context)}" if context else "") + ": "
                           + "; ".join(bits).replace("; (", " ("))

        def walk(obj, trail: list[str], where: str, level: float | None) -> None:
            if isinstance(obj, dict):
                level = _level(obj, level)
                record(obj, trail, where, level)
                for k, v in obj.items():
                    if str(k).casefold() in SKIP_KEYS or str(k).casefold() in ignored:
                        continue
                    if isinstance(v, (dict, list)):
                        lab = name_of(k, f"{where}.{k}")
                        if lab is None:
                            n = sum(1 for _ in _leaves(v))
                            if n:
                                gaps.append(f"{where_file} {where}.{k}: {n} result value(s) under "
                                            "a name without a clinical label")
                            continue
                        walk(v, trail + [lab], f"{where}.{k}", level)
            elif isinstance(obj, list):
                nums = [v for v in obj if _num(v)]
                if nums and len(nums) == len(obj):
                    label = next((t for t in reversed(trail) if t), None)
                    if label:
                        out.append(f"- {label}: " + ", ".join(str(v) for v in nums))
                    else:
                        gaps.append(f"{where_file} {where}: {len(nums)} value(s) without a label")
                    return
                for j, v in enumerate(obj):
                    walk(v, trail, f"{where}[{j}]", level)
        before = len(gaps)
        fallback = (_label_for(f.stem, names, labels_ci)
                    or (f.stem if _PLAIN.match(f.stem) else ""))
        walk(doc, [], "$", root_level)
        if f.stem == "dataset_summary":
            del gaps[before:]  # the S04 data description is not a required result
        if out:
            lines += [f"## Result set {i}", ""] + out + [""]
    return lines, gaps


def _leaves(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _leaves(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _leaves(v)
    elif _num(obj):
        yield obj


def result_gaps(project: Path) -> list[str]:
    """1.14.0 (B): required results the writer would not get (the S09 gate reads this)."""
    return results_in_words(Path(project), clinical.dictionary(project))[1]


def _dictionary_md(data: dict | None) -> str:
    rows = ["# Display dictionary (use these labels; define each abbreviation once per scope)", ""]
    for t in (data or {}).get("terms", []) or []:
        if not isinstance(t, dict) or not str(t.get("label", "")).strip():
            continue
        abbr = str(t.get("abbreviation", "")).strip()
        rows.append(f"- **{t['label'].strip()}**" + (f" ({abbr})" if abbr else "")
                    + f": {str(t.get('definition', '')).strip()}")
    return "\n".join(rows) + "\n"


def _tables_md(project: Path, names: dict[str, str]) -> str:
    rows = ["# Final tables (text copies)", ""]
    for item in clinical.display_items(project):
        if item["kind"] != "table":
            continue
        rows += [f"## {item['id']}", "", clean(item["caption"].strip(), names), ""]
        if item["cells"]:
            rows += [" | ".join(clean(c, names) for c in item["cells"][:400]), ""]
        if item["footnotes"]:
            rows += ["Footnotes: " + " ".join(clean(c, names) for c in item["footnotes"]), ""]
    return "\n".join(rows) + "\n"


def _library_md(project: Path) -> str:
    lib = _json(project / "06_refs/library.json") or {}
    rows = ["# Reference library (cite only these keys)", ""]
    for e in lib.get("entries", []) if isinstance(lib, dict) else []:
        authors = e.get("authors") or []
        first = (authors[0].get("last") if authors and isinstance(authors[0], dict) else "") or ""
        rows.append(f"- [@{e.get('citekey')}] {first} {e.get('year', '')}. {e.get('title', '')}")
    return "\n".join(rows) + "\n"


def _journal_md(project: Path) -> str:
    rows = ["# Journal profile", ""]
    for rel in ("08_submission/target_journal.json", "01_protocol/journal_profile.json"):
        data = _json(project / rel)
        if not isinstance(data, dict):
            continue
        rows.append(f"Journal: {data.get('journal') or data.get('name') or 'provisional profile'}")
        limits = data.get("limits") or {}
        for key, label in (("main_text_words", "Main text word limit"),
                           ("abstract_words", "Abstract word limit"),
                           ("reference_limit", "Reference limit"),
                           ("display_items", "Display items")):
            if limits.get(key):
                rows.append(f"{label}: {limits[key]}")
        if data.get("spelling"):
            rows.append(f"Spelling: {data['spelling']}")
        break
    return "\n".join(rows) + "\n"


def gaps_path(project: Path, stage: str) -> Path:
    return Path(project) / BUNDLE_DIR / f"{stage}_GAPS.md"


def build(project: Path, stage: str, target: str | None = None) -> Path:
    project = Path(project)
    target = target or TARGETS.get(stage)
    if not target:
        raise ValueError(f"no default section for {stage}; pass --target 07_manuscript/<file>.md")
    data = clinical.dictionary(project)
    names = clinical.internal_names(data)
    out = project / BUNDLE_DIR / stage
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    files: dict[str, str] = {"display_dictionary.md": _dictionary_md(data)}
    words, gaps = results_in_words(project, data)
    terms: list[str] = []  # 1.14.0 (B): text identifiers without a label, listed not dropped
    files["results_in_words.md"] = "\n".join(
        ["# Results in words (copy numbers exactly; round only as the tables do)", ""] + words
        + ([f"({len(gaps)} result value(s) are not shown because they have no clinical label "
            "yet; the orchestrator is fixing the display dictionary - do not guess them.)"]
           if gaps else [])) + "\n"
    files["tables.md"] = _tables_md(project, names)
    files["legends.md"] = clean(_read(project / clinical.LEGENDS), names, terms, "legends")
    proto = next((p for p in (project / "01_protocol/protocol_final.md",
                              project / "01_protocol/protocol_v1.md") if p.is_file()), None)
    if proto:
        # 1.13.0 (#8): plan-versus-practice history never reaches the writer - a protocol
        # section on deviations (older papers) is dropped; the paper describes what was done.
        text = re.sub(r"(?ms)^#{1,6}\s+Deviations\b.*?(?=^#{1,6}\s|\Z)", "", _read(proto))
        files["protocol_summary.md"] = clean(text, names, terms, "protocol")
    if stage in ("S16_discussion", "S19_human_review"):
        notes = sorted((project / "06_refs/deepread").glob("*.md"))
        if notes:
            files["deepread_notes.md"] = "\n\n".join(clean(_read(n), names) for n in notes)
    if stage in ("S08_methods", "S14_introduction", "S16_discussion", "S19_human_review"):
        files["library.md"] = _library_md(project)
    files["journal_profile.md"] = _journal_md(project)
    ex = [project / "01_protocol/exemplars.md", *sorted((project / "06_refs/exemplars").glob("*.md"))]
    ex_text = "\n\n".join(_read(p) for p in ex if p.is_file())
    if ex_text.strip():
        files["exemplars.md"] = clean(ex_text, names)
    if (project / target).is_file():
        files["current_draft.md"] = clean(_read(project / target), names, terms, "draft")
    for name, body in files.items():
        (out / name).write_text(body, encoding="utf-8")
    # For the orchestrator, outside the writer's folder: what the writer could not be given.
    gap_file = gaps_path(project, stage)
    if gaps or terms:
        gap_file.write_text("\n".join(
            [f"# Writer bundle gaps ({stage})", "",
             f"## Results without a clinical label ({len(gaps)}; `writer_bundle.py build` "
             "fails and the S09 gate writer_results_mapped fails while any remain)", ""]
            + [f"- {g}" for g in gaps]
            + ["", "Fix: add the name to 01_protocol/display_dictionary.json (label, "
               "definition), record the CI level (ci_level) in the results, or list a "
               "non-reported value under 'not_reported' with a reason.", "",
               f"## Text identifiers without a clinical label ({len(terms)})", ""]
            + [f"- {t}" for t in sorted(set(terms))]) + "\n", encoding="utf-8")
    else:
        gap_file.unlink(missing_ok=True)
    budget = ""
    key = BUDGET_KEYS.get(stage)
    if key:
        try:
            from wfcore import registry
            budget = str(registry.effective_targets(project).get(key, ""))
        except Exception:  # noqa: BLE001
            budget = ""
    manifest = [f"# Writer bundle ({stage})", "",
                f"Write: {target}" + (f" (soft budget about {budget} words)" if budget else ""),
                "Read only the files below (all in this folder). Clinical labels only; numbers "
                "only from results_in_words.md or tables.md; citations only from library.md.", "",
                "## Files", ""] + [f"- {n}" for n in files]
    (out / "MANIFEST.md").write_text("\n".join(manifest) + "\n", encoding="utf-8")
    return out


def lint(project: Path, stage: str) -> list[str]:
    """Engineering language, internal names and code identifiers in the bundle."""
    project = Path(project)
    out = project / BUNDLE_DIR / stage
    data = clinical.dictionary(project)
    problems = []
    for f in sorted(out.glob("*.md")):
        if f.name == "MANIFEST.md":
            continue
        text = f.read_text(encoding="utf-8")
        for term, hit, _ in clinical.engineering_hits(text, clinical.allowlist(project)):
            problems.append(f"{f.name}: engineering term '{hit}' ({term})")
        problems += [f"{f.name}: {x}" for x in clinical.label_problems(text, data)
                     if "letter-code" not in x]
        problems += [f"{f.name}: code identifier '{m.group(0)}'" for m in _IDENT.finditer(text)]
        problems += [f"{f.name}: path '{m.group(0)}'" for m in _PATH.finditer(text)]
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="clinical writer bundle (1.12.0)")
    ap.add_argument("command", choices=("build", "lint"))
    ap.add_argument("--stage", required=True)
    ap.add_argument("--target", default=None, help="manuscript file to write (default per stage)")
    ap.add_argument("--project", type=Path, default=None)
    args = ap.parse_args(argv)
    project = wfpaths.paper_from_cli(args.project)
    try:
        if args.command == "build":
            out = build(project, args.stage, args.target)
            print(f"writer bundle: {out / 'MANIFEST.md'}")
            gaps = result_gaps(project)
            if gaps:
                print(f"writer bundle INCOMPLETE: {len(gaps)} required result(s) have no clinical "
                      f"label or CI level; see {gaps_path(project, args.stage)} (fix the "
                      "display dictionary / results, then build again; do not delegate yet)")
                for g in gaps[:8]:
                    print(f"  GAP {g}")
                return 2
            print("Delegate to the medpaper-clinical-writer agent with that ONE path; then run "
                  "`wf check` (engineering_language_clean) on the written section.")
        problems = lint(project, args.stage)
    except (OSError, ValueError) as exc:
        print(f"writer bundle error: {exc}", file=sys.stderr)
        return 2
    for p in problems[:20]:
        print(f"  LINT {p}")
    print(f"writer bundle lint: {'clean' if not problems else f'{len(problems)} problem(s)'}")
    return 0 if not problems else 2


if __name__ == "__main__":
    raise SystemExit(main())
