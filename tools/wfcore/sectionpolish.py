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
- Keep what a medical paper must report (1.25.1): the primary outcome comes first, whatever
  its direction. Never remove, soften or move behind a secondary result a null or
  unfavourable result statement, a confidence interval or a limitation; uncertainty is shown
  by intervals and stated assumptions, not by hedging words. The 'polished' step re-checks
  outcomes reported, estimates with intervals and the limitations paragraph and refuses an
  edit that breaks one of them.
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


def reporting_regressions(project: Path, section: str, before: str, after: str) -> list[str]:
    """1.25.1 (R3): pre-specified outcomes reported, estimates with intervals and the
    limitations paragraph (checks a, c, d) that passed before the edit must still pass."""
    from . import outcomereport
    return outcomereport.edit_regressions(project, section, before, after)


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
    probs += reporting_regressions(project, section, old, new)
    if probs:
        raise ValueError("polished text refused: " + "; ".join(probs[:8]))
    f.write_text(new, encoding="utf-8")
    d = _dir(project, section)
    (d / "polished.md").write_text(new, encoding="utf-8")
    rec.update(polished_sha256=_sha(new), polished_at=_now(), editor=EDITOR,
               paragraphs=[_sha(p) for p in paragraphs(new)])
    _save(project, section, rec)
    return rec


# ------------------------------------------------------------------ 1.25.0 (B2): after assembly
MANUSCRIPT = "manuscript"
MANUSCRIPT_REL = "07_manuscript/full_manuscript.md"
PROSE_SCOPES = ("abstract", "introduction", "methods", "results", "discussion", "conclusion")
_MARK = re.compile(r"(?m)^<!--\s*paragraph\s+(\d+)\s*-->\s*$")


def manuscript_rel(project: Path) -> str:
    """The assembled manuscript: 07_manuscript/, or the journal copy once a variant is open."""
    try:
        from . import scifreeze
        return scifreeze.resolve(Path(project), MANUSCRIPT_REL)
    except Exception:  # noqa: BLE001
        return MANUSCRIPT_REL


def _strip_heads(p: str) -> str:
    return "\n".join(ln for ln in p.splitlines() if not re.match(r"\s{0,3}#{1,6}\s", ln)).strip()


def _nhash(p: str) -> str:
    return _sha(re.sub(r"\s+", " ", _strip_heads(p)).strip())


def prose_paragraphs(text: str) -> list[tuple[int, str]]:
    """(paragraph number counted by blank lines over the whole file, text without heading lines)
    for the prose of Abstract to Conclusion; Keywords, references, legends and statements are
    not prose sections."""
    out, scope = [], ""
    for i, p in enumerate(paragraphs(text), 1):
        for ln in p.splitlines():
            m = re.match(r"\s{0,3}#\s+(.+)$", ln)
            if m:
                name = m.group(1).strip().casefold()
                scope = next((s for s in PROSE_SCOPES if name.startswith(s)), "")
        rest = _strip_heads(p)
        if scope and rest and not re.match(r"(?i)\**keywords?\**\s*:", rest):
            out.append((i, rest))
    return out


def _ms_receipt(project: Path) -> dict:
    try:
        d = json.loads((_dir(project, MANUSCRIPT) / "receipt.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    return d if isinstance(d, dict) else {}


def polished_hashes(project: Path) -> tuple[set[str], str]:
    """Paragraph hashes that already passed the medical editor: every section's polished text
    and every manuscript receipt; a paper without section receipts (written before 1.23) uses
    the S22 pre-polish snapshot as its baseline."""
    hs: set[str] = set()
    basis = "section receipts"
    for sec in SECTIONS:
        f = _dir(project, sec) / "polished.md"
        if f.is_file():
            hs |= {_nhash(p) for p in paragraphs(f.read_text(encoding="utf-8"))}
    if not hs:
        basis = "pre-polish snapshot (no section receipts)"
        try:
            from . import scifreeze
            snap = Path(project) / scifreeze.resolve(Path(project), "07_manuscript/prepolish")
            f = snap / "full_manuscript.md"
            if f.is_file():
                hs |= {_nhash(p) for p in paragraphs(f.read_text(encoding="utf-8"))}
        except Exception:  # noqa: BLE001
            pass
    for rec in (_ms_receipt(project).get("files") or {}).values():
        hs |= set(rec.get("paragraphs") or [])
    return hs, basis


def manuscript_changed(project: Path) -> list[int]:
    """Prose paragraphs of the assembled manuscript changed since their last polished receipt."""
    f = Path(project) / manuscript_rel(project)
    if not f.is_file():
        return []
    known, _basis = polished_hashes(project)
    return [i for i, p in prose_paragraphs(f.read_text(encoding="utf-8")) if _nhash(p) not in known]


def build_manuscript_edit(project: Path) -> Path:
    """Editor bundle with ONLY the changed paragraphs (changed.md); unchanged ones are never sent."""
    rel = manuscript_rel(project)
    f = Path(project) / rel
    if not f.is_file():
        raise ValueError(f"{rel} does not exist (assembled at S17)")
    todo = set(manuscript_changed(project))
    if not todo:
        raise ValueError("no paragraph changed since its last polished receipt - nothing to send")
    out = Path(project) / EDITOR_DIR / MANUSCRIPT
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    paras = dict(prose_paragraphs(f.read_text(encoding="utf-8")))
    (out / "changed.md").write_text("\n\n".join(f"<!-- paragraph {i} -->\n{paras[i]}"
                                                for i in sorted(todo)) + "\n", encoding="utf-8")
    manifest = [f"# Medical editor bundle (changed paragraphs of {rel})", "",
                f"Read changed.md: {len(todo)} paragraph(s) edited after assembly. Write "
                f"{(out / 'polished.md').as_posix()} - the only file you may write - with the same "
                "'<!-- paragraph N -->' markers, each followed by that paragraph polished (one "
                "paragraph each, no headings). Every other paragraph stays as it is.", "", RUBRIC]
    voice_ref = writing_voice_file()
    if voice_ref is not None:
        shutil.copyfile(voice_ref, out / "writing_voice.md")
        manifest += ["", "Also read writing_voice.md (confident, not defensive: examples)."]
    (out / "MANIFEST.md").write_text("\n".join(manifest) + "\n", encoding="utf-8")
    return out


def accept_manuscript(project: Path, polished: Path | None = None) -> dict:
    """Merge the editor's paragraphs into the manuscript (facts unchanged, language clean) and
    record the hashes of its prose paragraphs as polished."""
    rel = manuscript_rel(project)
    f = Path(project) / rel
    src = Path(polished) if polished else Path(project) / EDITOR_DIR / MANUSCRIPT / "polished.md"
    if not src.is_file():
        raise ValueError(f"{src} missing: the medical editor writes it")
    marks = list(_MARK.finditer(src.read_text(encoding="utf-8")))
    raw = src.read_text(encoding="utf-8")
    new = {int(m.group(1)): raw[m.end():(marks[k + 1].start() if k + 1 < len(marks) else len(raw))]
           .strip() for k, m in enumerate(marks)}
    todo = set(manuscript_changed(project))
    if set(new) != todo:
        raise ValueError(f"polished.md must hold exactly paragraphs {sorted(todo)} (got {sorted(new)})")
    if any(not t or re.search(r"\n\s*\n", t) or _strip_heads(t) != t for t in new.values()):
        raise ValueError("each polished paragraph must be one paragraph without headings")
    text = f.read_text(encoding="utf-8")
    paras = dict(prose_paragraphs(text))
    old_t = "\n\n".join(paras[i] for i in sorted(todo))
    new_t = "\n\n".join(new[i] for i in sorted(todo))
    probs = fact_problems(old_t, new_t, rel) + language_problems(project, MANUSCRIPT, new_t)
    if probs:
        raise ValueError("polished paragraphs refused: " + "; ".join(probs[:8]))
    chunks = re.split(r"(\n\s*\n)", text.replace("\r\n", "\n"))
    n = 0
    for k, ch in enumerate(chunks):
        if k % 2 or not ch.strip():
            continue
        n += 1
        if n in new:
            heads = [ln for ln in ch.strip().splitlines() if re.match(r"\s{0,3}#{1,6}\s", ln)]
            lead = ch[:len(ch) - len(ch.lstrip())]
            chunks[k] = lead + "\n".join(heads + [new[n]])
    merged = "".join(chunks)
    regress = reporting_regressions(project, MANUSCRIPT, text, merged)  # 1.25.1 (R3)
    if regress:
        raise ValueError("polished paragraphs refused: " + "; ".join(regress[:8]))
    f.write_text(merged, encoding="utf-8")
    rec = _ms_receipt(project)
    rec.setdefault("schema", 1)
    entry = rec.setdefault("files", {}).setdefault(rel, {"paragraphs": [], "history": []})
    entry["paragraphs"] = sorted(set(entry["paragraphs"]) | {_nhash(p) for _i, p in
                                                             prose_paragraphs(merged)})
    entry["history"].append({"paragraphs": sorted(todo), "polished_at": _now(), "editor": EDITOR})
    d = _dir(project, MANUSCRIPT)
    d.mkdir(parents=True, exist_ok=True)
    (d / "receipt.json").write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n",
                                    encoding="utf-8")
    return {"file": rel, "paragraphs": sorted(todo)}


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
