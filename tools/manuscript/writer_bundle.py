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
replaced by their clinical labels, remaining code-like identifiers are removed, and result
values whose path has no clinical label are counted, not shown. `lint` (also run by `build`)
checks the bundle with the engineering-language rules and for internal names.
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
    "low": "lower 95% confidence limit", "lower": "lower 95% confidence limit",
    "ci_low": "lower 95% confidence limit", "ci_lower": "lower 95% confidence limit",
    "lcl": "lower 95% confidence limit", "high": "upper 95% confidence limit",
    "upper": "upper 95% confidence limit", "ci_high": "upper 95% confidence limit",
    "ci_upper": "upper 95% confidence limit", "ucl": "upper 95% confidence limit",
}
SKIP_KEYS = {"environment", "meta", "metadata", "provenance", "script", "inputs", "outputs"}
_IDENT = re.compile(r"(?<![@\w-])[a-z][a-z0-9]*(?:_[a-z0-9]+)+(?![\w-])")
_PATH = re.compile(r"(?:[A-Za-z]:[\\/]|\b(?:0\d_\w+|tools|temp|\.wf)[\\/])[^\s)]*"
                   r"|\b[\w-]+\.(?:py|R|r|json|csv|xlsx|log|toml|txt)\b")


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""


def _json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def clean(text: str, names: dict[str, str]) -> str:
    """Clinical labels for internal names; code, paths and identifiers removed."""
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    text = re.sub(r"`[^`\n]*`", "", text)
    for name, label in sorted(names.items(), key=lambda kv: -len(kv[0])):
        text = re.sub(rf"(?<![\w-]){re.escape(name)}(?![\w-])", label, text)
    text = _PATH.sub("", text)
    text = journalspec.PIPELINE_CODE_RE.sub("", text)
    return _IDENT.sub("", text)


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


def results_in_words(project: Path, data: dict | None) -> tuple[list[str], int]:
    names = clinical.internal_names(data)
    labels_ci = {lab.casefold(): lab for lab in clinical.labels(data)}
    lines, omitted = [], 0
    files = sorted((project / "03_analysis/results").glob("*.json"))
    for i, f in enumerate(files, 1):
        doc = _json(f)
        if not isinstance(doc, dict):
            continue
        out = []

        def walk(obj, trail):
            nonlocal omitted
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if str(k).casefold() in SKIP_KEYS:
                        continue
                    walk(v, trail + [str(k)])
                return
            if isinstance(obj, bool) or not isinstance(obj, (int, float)) or not trail:
                return
            leaf, parents = trail[-1], trail[:-1]
            stat = _stat(leaf)
            context = [_label_for(p, names, labels_ci) for p in parents]
            if stat is None:
                own = _label_for(leaf, names, labels_ci)
                if own is None or any(c is None for c in context):
                    omitted += 1
                    return
                out.append(f"- {own}" + (f" ({', '.join(context)})" if context else "")
                           + f": {obj}")
                return
            if any(c is None for c in context) or not context:
                omitted += 1
                return
            out.append(f"- {stat[:1].upper() + stat[1:]}, {', '.join(context)}: {obj}")
        walk(doc, [])
        if out:
            lines += [f"## Result set {i}", ""] + out + [""]
    return lines, omitted


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
    words, omitted = results_in_words(project, data)
    files["results_in_words.md"] = "\n".join(
        ["# Results in words (copy numbers exactly; round only as the tables do)", ""] + words
        + ([f"({omitted} value(s) have no clinical label in the display dictionary and are not "
            "shown; ask for a dictionary entry or use the tables.)"] if omitted else [])) + "\n"
    files["tables.md"] = _tables_md(project, names)
    files["legends.md"] = clean(_read(project / clinical.LEGENDS), names)
    proto = next((p for p in (project / "01_protocol/protocol_final.md",
                              project / "01_protocol/protocol_v1.md") if p.is_file()), None)
    if proto:
        # 1.13.0 (#8): plan-versus-practice history never reaches the writer - a protocol
        # section on deviations (older papers) is dropped; the paper describes what was done.
        text = re.sub(r"(?ms)^#{1,6}\s+Deviations\b.*?(?=^#{1,6}\s|\Z)", "", _read(proto))
        files["protocol_summary.md"] = clean(text, names)
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
        files["current_draft.md"] = clean(_read(project / target), names)
    for name, body in files.items():
        (out / name).write_text(body, encoding="utf-8")
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
