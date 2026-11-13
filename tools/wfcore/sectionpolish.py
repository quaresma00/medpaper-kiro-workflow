"""1.23.0 (S5): every prose section drafted by the clinical writer and polished right away by
an independent medical editor - receipts, not assembly-time polishing.

    writer_bundle.py receipt  --stage S08_methods [--section methods]   bundle hash -> draft hash
    writer_bundle.py edit     --section methods      editor bundle (.wf/editor_bundle/<section>/)
    writer_bundle.py polished --section methods      fact check + lint -> section file = polished

Receipts live in .wf/writer/<section>/receipt.json (draft.md and polished.md beside them). The
editor (medpaper-medical-editor, or the clinical writer in edit mode) writes only
.wf/editor_bundle/<section>/polished.md: medical register, de-AI phrasing, no engineering /
computer / data-processing narration, lists to prose, sentence length, abbreviations - numbers,
citekeys and table/figure references unchanged. The rubric: a clinician who never saw the
code understands every sentence. After polishing the section file must equal the polished
text; a later edit is detected paragraph by paragraph and only the changed paragraphs are
re-polished. Gate section_polished (since 1.23.0) at each writing stage.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

WRITER_DIR = ".wf/writer"
EDITOR_DIR = ".wf/editor_bundle"
BUNDLE_DIR = ".wf/writer_bundle"
EDITOR = "medpaper-medical-editor"
# section -> (stage that writes it, file)
SECTIONS = {
    "legends": ("S07_artifacts", "05_figures/legends.md"),
    "table_captions": ("S07_artifacts", "04_tables/table_captions.md"),
    "methods": ("S08_methods", "07_manuscript/methods.md"),
    "supplementary_methods": ("S08_methods", "07_manuscript/supplementary_methods.md"),
    "results": ("S09_results", "07_manuscript/results.md"),
    "introduction": ("S14_introduction", "07_manuscript/introduction.md"),
    "discussion": ("S16_discussion", "07_manuscript/discussion.md"),
    "abstract": ("S17_assemble", "07_manuscript/abstract.md"),
    "title": ("S17_assemble", "07_manuscript/title.md"),
    "cover_letter": ("S23_package", "08_submission/cover_letter.md"),
}
LINT_EXEMPT = {"supplementary_methods"}  # implementation detail belongs there
RUBRIC = """Rubric: a clinician who never saw the code understands every sentence.
- Medical register: what was done to which patients/reports and why, in clinical words; never
  how the data were processed (parsed, merged/joined on a key, collapsed or filtered rows,
  flagged, deduplicated by key, normalised strings, mapped codes, coded as 0/1, script,
  pipeline, column, field, string, record, snapshot, quarterly files, lines read, regex, token).
  Rewrite, e.g. 'duplicate reports were removed following the FDA-recommended approach'.
- De-AI: no stock phrases (delve, pivotal, underscore the importance, it is worth noting,
  plays a crucial role, not only ... but also); plain verbs; varied, mostly short sentences
  (about 15-25 words); continuous paragraphs, no bullet lists.
- Abbreviations defined at first use; the clinical labels of the display dictionary.
- Defensive writing (1.24.0): organise the narrative, never select the evidence.
  E1 remove prebuttals ('we emphasize that', 'we do not claim', 'it should be noted that'),
  'for a fair comparison', empty 'Taken together, these findings demonstrate' summaries and
  self-weakening adverbs (unfortunately, merely, disappointingly).
  E2 one caveat per claim; a repeated caveat stays only in the limitations paragraph.
  E3 remove sentence-final ', highlighting/underscoring/emphasising/showcasing ...' tails;
  'serves as'/'stands as' -> 'is'; one name for the same population; reports, cases and
  patients are different analysis units, never merged.
  E4 before deleting ask 'would removing it mislead a reader?'; never delete the only causal,
  signal or design caveat, a pre-specified outcome or a negative result; keep normal
  transitions with a citation ('Prior studies have shown [@key]', 'Moreover', 'In contrast');
  'trend toward significance' / 'marginally significant' -> estimate + CI + plain conclusion.
- NEVER change a number, a citation [@key] or a table/figure reference; never add a claim."""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text.replace("\r\n", "\n")) if p.strip()]


def _dir(project: Path, section: str) -> Path:
    return Path(project) / WRITER_DIR / section


def receipt(project: Path, section: str) -> dict | None:
    try:
        data = json.loads((_dir(project, section) / "receipt.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _save(project: Path, section: str, data: dict) -> None:
    d = _dir(project, section)
    d.mkdir(parents=True, exist_ok=True)
    (d / "receipt.json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                                    encoding="utf-8")


def _file(project: Path, section: str) -> Path:
    if section not in SECTIONS:
        raise ValueError(f"unknown section '{section}' (known: {', '.join(SECTIONS)})")
    return Path(project) / SECTIONS[section][1]


def bundle_hash(project: Path, stage: str) -> str:
    d = Path(project) / BUNDLE_DIR / stage
    if not (d / "MANIFEST.md").is_file():
        return ""
    h = hashlib.sha256()
    for f in sorted(d.glob("*.md")):
        h.update(f.name.encode() + b"\0" + f.read_bytes())
    return h.hexdigest()


def record_draft(project: Path, stage: str, section: str) -> dict:
    """The clinical writer's draft, bound to the writer bundle it came from."""
    f = _file(project, section)
    if not f.is_file():
        raise ValueError(f"{SECTIONS[section][1]} does not exist yet (the clinical writer writes it)")
    bh = bundle_hash(project, stage)
    if not bh:
        raise ValueError(f"no writer bundle for {stage}: writer_bundle.py build --stage {stage} "
                         "and delegate to medpaper-clinical-writer first")
    text = f.read_text(encoding="utf-8")
    d = _dir(project, section)
    d.mkdir(parents=True, exist_ok=True)
    (d / "draft.md").write_text(text, encoding="utf-8")
    old = receipt(project, section) or {}
    data = {"schema": 1, "section": section, "file": SECTIONS[section][1], "stage": stage,
            "writer": "medpaper-clinical-writer", "bundle_sha256": bh, "draft_sha256": _sha(text),
            "drafted_at": _now(), "polished_sha256": None, "history": old.get("history", [])}
    if old.get("polished_sha256"):
        data["history"].append({k: old.get(k) for k in ("draft_sha256", "polished_sha256",
                                                         "polished_at")})
        data["paragraphs"] = old.get("paragraphs", [])
    _save(project, section, data)
    return data


def changed_paragraphs(project: Path, section: str) -> list[int]:
    """1-based numbers of the paragraphs that differ from the last polished text."""
    rec = receipt(project, section) or {}
    old = set(rec.get("paragraphs") or [])
    f = _file(project, section)
    if not f.is_file():
        return []
    return [i for i, p in enumerate(paragraphs(f.read_text(encoding="utf-8")), 1)
            if _sha(p) not in old]


def build_edit(project: Path, section: str) -> Path:
    """The editor's bundle: the section text, the paragraphs to polish and the rubric."""
    f = _file(project, section)
    rec = receipt(project, section)
    if not rec:
        raise ValueError(f"no writer receipt for {section}: writer_bundle.py receipt --stage "
                         f"{SECTIONS[section][0]} --section {section} first")
    text = f.read_text(encoding="utf-8")
    todo = changed_paragraphs(project, section) if rec.get("paragraphs") else []
    out = Path(project) / EDITOR_DIR / section
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    (out / "section.md").write_text(text, encoding="utf-8")
    scope = (f"Polish ONLY paragraphs {', '.join(map(str, todo))} (counted by blank lines); keep "
             "every other paragraph exactly as it is." if todo else "Polish the whole section.")
    manifest = [f"# Medical editor bundle ({section}: {SECTIONS[section][1]})", "",
                "Read section.md. Write the complete polished section (all paragraphs, in order) "
                f"to {(out / 'polished.md').as_posix()} - the only file you may write.", "",
                scope, "", RUBRIC]
    if section in LINT_EXEMPT:
        manifest.append("- Supplementary Methods may keep necessary implementation detail, "
                        "written as plain sentences.")
    voice_ref = writing_voice_file()
    if voice_ref is not None:  # 1.24.0 (C): the adapted rules with examples
        shutil.copyfile(voice_ref, out / "writing_voice.md")
        manifest += ["", "Also read writing_voice.md (confident, not defensive: examples)."]
    hits = warning_hits(project, section, text)
    if hits:  # 1.24.0 (B4)
        manifest += ["", "## Warning-level findings in the draft (fix each, unless the keep-list "
                     "test says keep: would removing it mislead a reader?)", ""]
        manifest += [f"- {h}" for h in hits[:30]]
    (out / "MANIFEST.md").write_text("\n".join(manifest) + "\n", encoding="utf-8")
    return out


def writing_voice_file() -> Path | None:
    """reference/writing_voice.md (1.24.0), or None when the engine copy lacks it."""
    from . import paths
    p = paths.repo_root() / "reference" / "writing_voice.md"
    return p if p.is_file() else None


def _polish_module():
    from . import paths
    spec = importlib.util.spec_from_file_location("medpaper_polish_mod",
                                                  paths.tools_dir() / "text" / "polish.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def language_problems(project: Path, section: str, text: str) -> list[str]:
    """Engineering/data-processing narration (1.11 + 1.23 lists) and tier-A AI phrasing."""
    from . import clinical
    out = []
    if section not in LINT_EXEMPT:
        for term, hit, sug in clinical.engineering_hits(text, clinical.allowlist(project),
                                                        "all", extended=True):
            out.append(f"engineering '{hit}' ({term}) -> {sug}")
    try:
        pol = _polish_module()
        from . import voice
        table = list(pol.AI_TIER_A)
        if voice.since_1240_project(project, SECTIONS.get(section, ("",))[0]):
            table += pol.SPIN_TIER_A  # 1.24.0 (B1): spin blocks for papers on 1.24.0+
        for pat, label in table:
            if re.search(pat, text, re.I):
                out.append(f"AI phrasing '{label}'")
    except Exception:  # noqa: BLE001 - the engineering lint above still runs
        pass
    return out


def warning_hits(project: Path, section: str, text: str) -> list[str]:
    """1.24.0 (B4): warning-level hits (tier B, defensive writing) - listed, never blocking."""
    try:
        pol = _polish_module()
        return pol.voice_warnings(SECTIONS[section][1], text, Path(project),
                                  SECTIONS[section][0])
    except Exception:  # noqa: BLE001
        return []


def fact_problems(before: str, after: str, rel: str = "") -> list[str]:
    try:
        pol = _polish_module()
        a, b = pol.facts(before, rel), pol.facts(after, rel)
    except Exception as exc:  # noqa: BLE001
        return [f"fact check unavailable: {exc}"]
    out = []
    for k in ("numbers", "citekeys", "artifacts"):
        if a[k] != b[k]:
            gone = sorted(set(a[k]) - set(b[k]))[:6]
            new = sorted(set(b[k]) - set(a[k]))[:6]
            out.append(f"{k} changed (removed {gone or '-'}, added {new or '-'})")
    return out


def accept_polished(project: Path, section: str, polished: Path | None = None) -> dict:
    """Check the editor's text against the current section (facts unchanged, language clean),
    write it to the section file and record polished hash and paragraph hashes."""
    rec = receipt(project, section)
    if not rec:
        raise ValueError(f"no writer receipt for {section}")
    src = Path(polished) if polished else Path(project) / EDITOR_DIR / section / "polished.md"
    if not src.is_file():
        raise ValueError(f"{src} missing: the medical editor writes it")
    new = src.read_text(encoding="utf-8")
    f = _file(project, section)
    old = f.read_text(encoding="utf-8")
    probs = fact_problems(old, new, SECTIONS[section][1]) + language_problems(project, section, new)
    if probs:
        raise ValueError("polished text refused: " + "; ".join(probs[:8]))
    f.write_text(new, encoding="utf-8")
    d = _dir(project, section)
    (d / "polished.md").write_text(new, encoding="utf-8")
    rec.update(polished_sha256=_sha(new), polished_at=_now(), editor=EDITOR,
               paragraphs=[_sha(p) for p in paragraphs(new)])
    _save(project, section, rec)
    return rec


def problems(project: Path, section: str, optional: bool = False) -> list[str]:
    f = _file(project, section)
    if not f.is_file():
        return [] if optional else [f"{SECTIONS[section][1]} missing"]
    rec = receipt(project, section)
    rel = SECTIONS[section][1]
    if not rec or not rec.get("bundle_sha256") or not rec.get("draft_sha256"):
        return [f"{rel}: no writer receipt (drafted by medpaper-clinical-writer from the "
                f"{SECTIONS[section][0]} writer bundle; writer_bundle.py receipt --stage "
                f"{SECTIONS[section][0]} --section {section})"]
    if not rec.get("polished_sha256"):
        return [f"{rel}: not polished by the medical editor yet (writer_bundle.py edit --section "
                f"{section}, then polished --section {section})"]
    text = f.read_text(encoding="utf-8")
    out = []
    if _sha(text) != rec["polished_sha256"]:
        ch = changed_paragraphs(project, section)
        out.append(f"{rel}: edited after polishing (paragraph(s) {', '.join(map(str, ch)) or '?'}); "
                   f"re-polish only these: writer_bundle.py edit --section {section}")
    out += [f"{rel}: {p}" for p in language_problems(project, section, text)[:4]]
    return out
