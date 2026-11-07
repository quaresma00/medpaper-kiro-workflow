"""1.19.0 (M1/M2/M4/M5): where the title page, figures and tables go, and how supplementary
files are named - typed fields of target_journal.json, never the agent's judgment.

    "title_page": {"placement": "in_manuscript" | "separate" | "both", ...}
    "figures":    {"placement": "separate_files" | "in_text" | "end_of_manuscript",
                   "also_separate": true}            (in_text/end_of_manuscript + separate files)
    "tables":     {"placement": "end_of_manuscript" | "in_text"}
    "supplementary_file_pattern": "ESM_{n}"          (only a mandated naming rule of the guide)

Defaults when the field is absent (new papers; a paper pinned before 1.19.0 after `wf migrate
--yes` or a journal switch): title page in the manuscript (first page, then a page break, then
the abstract) - plus a separate title-page file only when required_uploads lists one ('both');
a blinded journal always gets a separate title page and an anonymous manuscript. Figures as
separate files (legends on their own page at the end, no images in the manuscript). Tables
each on its own page after the references. Supplementary files Supplemental_File_{n}_{Title}.
An explicit field is honoured on the next build of every paper (`wf rebuild`). A non-default
placement or a naming pattern is valid only with a guideline requirement (rule.field = the
field, quote + lines; checks/v1190.py layout_from_guideline). A pinned paper without the
fields keeps its legacy layout (embed_figures / word_tables / agent-chosen file names).
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

V = (1, 19, 0)
TITLE_PAGE = ("in_manuscript", "separate", "both")
FIGURES = ("separate_files", "in_text", "end_of_manuscript")
TABLES = ("end_of_manuscript", "in_text")
DEFAULT_SUPP_PATTERN = "Supplemental_File_{n}_{Title}"
MANIFEST = "08_submission/bundle/manifest.json"
COVER = "08_submission/cover_letter.md"
# requirement rule.field (and legacy aliases) + the categories that may source it
SOURCES = {
    "title_page": (("title_page.placement",), ("title_page", "required_uploads", "layout")),
    "figures": (("figures.placement", "embed_figures", "figures_at_end", "figures.also_separate"),
                ("figures", "layout", "required_uploads")),
    "tables": (("tables.placement", "word_tables"), ("tables", "layout")),
    "supplementary": (("supplementary_file_pattern",), ("supplementary", "required_uploads")),
    "abbreviations": (("abbreviation_list",), ("layout", "section_headings", "declarations")),
}
SUPP_KINDS = ("supplementary", "esm_figures", "esm_xlsx", "checklist_form")


def _json(path: Path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _target(project: Path | None) -> dict:
    from . import journalspec
    return journalspec.load(project) if project is not None else {}


def since_1190_project(project: Path | None, stage: str = "S23_package") -> bool:
    """New defaults: a paper created on 1.19.0+, migrated, or after a journal switch (S20-S25)."""
    from .state import version_tuple
    if project is None:
        return True
    st = _json(Path(project) / ".wf/state.json")
    if not isinstance(st, dict):
        return True
    pin = version_tuple(str(st.get("engine_pin") or st.get("pipeline_version") or "0"))
    jp = st.get("journal_gate_pin") or {}
    if stage in (jp.get("stages") or []):
        pin = max(pin, version_tuple(str(jp.get("version", "0"))))
    return pin >= V


def since_1190(ctx) -> bool:
    from .state import pin_for, version_tuple
    try:
        return version_tuple(pin_for(ctx.state, getattr(ctx.stage, "id", None))) >= V
    except Exception:  # noqa: BLE001
        return True


def _block(target: dict, key: str) -> dict:
    v = target.get(key) if isinstance(target, dict) else None
    return v if isinstance(v, dict) else {}


def explicit(target: dict, which: str) -> str | None:
    """The typed value the journal copy sets, or None (absent or not a valid value)."""
    if which == "supplementary":
        raw = str(target.get("supplementary_file_pattern") or "").strip()
        return raw or None
    if which == "abbreviations":
        raw = str(target.get("abbreviation_list") or "").strip().casefold()
        return raw if raw in ("none", "after_keywords") else None
    key, allowed = {"title_page": ("title_page", TITLE_PAGE), "figures": ("figures", FIGURES),
                    "tables": ("tables", TABLES)}[which]
    raw = str(_block(target, key).get("placement") or "").strip().casefold()
    return raw if raw in allowed else None


def _required_roles(target: dict) -> set[str]:
    from . import journalfields
    pairs, _ = journalfields.required_upload_roles(target)
    return {role for _item, role in pairs}


def default_title_page(target: dict) -> str:
    return "both" if "title_page" in _required_roles(target) else "in_manuscript"


def title_page_placement(target: dict, project: Path | None = None) -> str:
    from . import journalspec
    if journalspec.blinded(target):
        return "separate"
    v = explicit(target, "title_page")
    if v:
        return v
    return default_title_page(target) if since_1190_project(project) else "separate"


def title_page_in_manuscript(target: dict, project: Path | None = None) -> bool:
    return title_page_placement(target, project) in ("in_manuscript", "both")


def legacy_embed(target: dict) -> bool:
    """embed_figures (pre-1.19 field) without figures.placement: the old interleaved layout."""
    return (explicit(target, "figures") is None and target.get("embed_figures") is True
            and not target.get("figures_at_end"))


def figure_placement(target: dict, project: Path | None = None) -> str:
    v = explicit(target, "figures")
    if v:
        return v
    return "end_of_manuscript" if legacy_embed(target) else "separate_files"


def figures_embedded(target: dict, project: Path | None = None) -> bool:
    return figure_placement(target, project) in ("in_text", "end_of_manuscript")


def figures_separate(target: dict, project: Path | None = None) -> bool:
    """Separate figure files are wanted (journalspec.separate_display_files still decides
    whether the journal allows them). With an explicit embedded placement: only when the guide
    asks for both (figures.also_separate, or figures in required_uploads)."""
    v = explicit(target, "figures")
    if v is None or v == "separate_files":
        return True
    return _block(target, "figures").get("also_separate") is True or \
        "figures" in _required_roles(target)


def table_placement(target: dict, project: Path | None = None) -> str:
    """end_of_manuscript | in_text | none (legacy: word_tables false - tables only as files)."""
    v = explicit(target, "tables")
    if v:
        return v
    if "word_tables" in target:
        return "end_of_manuscript" if target.get("word_tables") is True else "none"
    return "end_of_manuscript" if since_1190_project(project) else "none"


def tables_in_manuscript(target: dict, project: Path | None = None) -> bool:
    return table_placement(target, project) != "none"


# ------------------------------------------------------------------ supplementary file names
def supplementary_pattern(target: dict, project: Path | None = None) -> str | None:
    """The naming pattern in force, or None (a pinned paper keeps the names it chose)."""
    v = explicit(target, "supplementary")
    if v:
        return v
    return DEFAULT_SUPP_PATTERN if since_1190_project(project) else None


def title_slug(title: str, limit: int = 50) -> str:
    """'Supplementary methods' -> 'Supplementary_Methods' (ASCII, words capitalised)."""
    s = unicodedata.normalize("NFKD", str(title or "")).encode("ascii", "ignore").decode()
    out = ""
    for w in re.findall(r"[A-Za-z0-9]+", s):
        w = w[:1].upper() + w[1:]
        cand = f"{out}_{w}" if out else w
        if len(cand) > limit:
            break
        out = cand
    return out or "Supplementary_Material"


def supplementary_stem(pattern: str, n: int, title: str) -> str:
    slug = title_slug(title)
    stem = str(pattern).replace("{n}", str(n)).replace("{Title}", slug).replace("{title}", slug)
    return re.sub(r"\.[A-Za-z0-9]{2,4}$", "", stem)


DEFAULT_TITLES = {"esm_figures": "Supplementary Figures", "esm_xlsx": "Supplementary Tables",
                  "supplementary": "Supplementary Methods", "checklist_form": "Reporting Checklist"}


def default_title(kind: str, source: Path | None = None) -> str:
    """The descriptive title: the source's first heading, else the kind's default."""
    if source is not None and Path(source).suffix.casefold() == ".md" and Path(source).is_file():
        m = re.search(r"(?m)^#{1,2}\s+(.+?)\s*$", Path(source).read_text(encoding="utf-8",
                                                                         errors="replace"))
        if m:
            head = re.sub(r"[*_`]", "", m.group(1)).strip()
            if head and not re.match(r"(?i)^(online resource|esm|supplementary information)\s*\d*$", head):
                return head
    return DEFAULT_TITLES.get(kind, "Supplementary Material")


def named_output(project: Path, output: Path, number: int | None, title: str,
                 suffix: str) -> Path:
    """The upload path under the naming pattern; `output` may be the bundle directory. A
    given file name is kept when no pattern is in force (pinned paper) or no number is given."""
    output = Path(output)
    pattern = supplementary_pattern(_target(project), project)
    is_dir = output.is_dir() or not output.suffix
    if not number or not pattern:
        return output / f"Supplementary_{title_slug(title)}{suffix}" if is_dir else output
    return (output if is_dir else output.parent) / (supplementary_stem(pattern, number, title) + suffix)


def header(target: dict, number: int | None, title: str | None, project: Path | None) -> str:
    """'Online Resource 2: Supplementary Tables' (1.19.0) / 'Online Resource 2' (pinned)."""
    from . import journalspec
    if not number:
        return "Supplementary information"
    head = f"{journalspec.esm_label(target)} {number}"
    if title and supplementary_pattern(target, project):
        head += f": {title}"
    return head


def rename_supplementary(project: Path, dry: bool = False) -> list[str]:
    """`wf rebuild`: give every numbered supplementary upload its pattern name (output, PDF
    twin, receipt and manifest entries move together). Returns 'old -> new' lines."""
    from . import rebuild
    from .packagecontent import build_receipt_path
    project = Path(project)
    target = _target(project)
    pattern = supplementary_pattern(target, project)
    if not pattern:
        return []
    moves: list[tuple[Path, Path]] = []
    done: list[str] = []
    for rec in rebuild.receipts(project):
        if rec.get("kind") not in SUPP_KINDS:
            continue
        args = rec.get("args") or {}
        n = args.get("esm_number") or args.get("number")
        if not isinstance(n, int) or n <= 0:
            continue
        old = project / rec["output"]
        src = next((project / s["path"] for s in rec.get("sources", []) if s.get("path")), None)
        title = args.get("title") or default_title(rec["kind"], src if rec["kind"] in (
            "supplementary", "checklist_form") else None)
        new = old.with_name(supplementary_stem(pattern, n, title) + old.suffix)
        if new == old:
            continue
        done.append(f"{rec['output']} -> {new.relative_to(project).as_posix()}")
        if dry:
            continue
        pairs = [(old, new)]
        if rec.get("pdf_output"):
            pairs.append((project / rec["pdf_output"], new.with_suffix(".pdf")))
        for a, b in pairs:
            if a.is_file():
                b.parent.mkdir(parents=True, exist_ok=True)
                a.replace(b)
            moves.append((a, b))
        rec_path = Path(rec.pop("_receipt"))
        rec["output"] = new.relative_to(project).as_posix()
        if rec.get("pdf_output"):
            rec["pdf_output"] = new.with_suffix(".pdf").relative_to(project).as_posix()
        rec["args"] = {**args, "title": title}
        new_rec = build_receipt_path(project, new)
        new_rec.parent.mkdir(parents=True, exist_ok=True)
        new_rec.write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        if new_rec != rec_path:
            rec_path.unlink(missing_ok=True)
    if moves and (project / MANIFEST).is_file():
        man = _json(project / MANIFEST) or {}
        rel = {a.relative_to(project).as_posix(): b.relative_to(project).as_posix() for a, b in moves}
        for item in man.get("items", []) if isinstance(man, dict) else []:
            if item.get("file") in rel:
                item["file"] = rel[item["file"]]
        (project / MANIFEST).write_text(json.dumps(man, indent=2, ensure_ascii=False) + "\n",
                                        encoding="utf-8")
    if moves:
        from .revision import record_derived
        record_derived(project, [b for _a, b in moves if b.is_file()] +
                       ([project / MANIFEST] if (project / MANIFEST).is_file() else []))
    return done


# ------------------------------------------------------------------ basis and problems
def basis(project: Path, which: str) -> dict | None:
    """The guideline requirement that sources this layout field: {id, lines, quote, field}."""
    from . import requirements as rq
    fields, cats = SOURCES[which]
    for r in rq.load(project).get("requirements") or []:
        if not isinstance(r, dict):
            continue
        rule = r.get("rule") if isinstance(r.get("rule"), dict) else {}
        if str(rule.get("field", "")).strip() in fields and r.get("category") in cats \
                and r.get("enforcement") != "n.a.":
            return {"id": str(r.get("id")), "lines": rq._ranges(rq.line_numbers(r.get("lines"))),
                    "quote": rq.norm(r.get("quote", "")), "field": rule.get("field")}
    return None


ZH = {
    "title_page": {"in_manuscript": "题名页放在正文首页（作者、单位、通讯作者等），之后分页接摘要；不单独上传题名页",
                   "separate": "题名页单独成文件上传，正文不含作者信息",
                   "both": "题名页放在正文首页，同时另外上传单独的题名页文件"},
    "figures": {"separate_files": "图片作为单独文件上传；正文末尾只放图注（另起一页），正文不嵌入图片",
                "in_text": "图片嵌入正文，紧接首次引用处并附图注",
                "end_of_manuscript": "图注列表之后，每张图单独一页并附图注"},
    "tables": {"end_of_manuscript": "表格放在参考文献之后，每表单独一页",
               "in_text": "表格放在正文首次引用处附近",
               "none": "表格只作为单独文件上传（word_tables=false）"},
    "abbreviations": {"after_keywords": "缩略语表放在关键词之后", "none": "不设缩略语表",
                      "keep": "缩略语表保持原位置（旧版设置）"},
}
LABEL_ZH = {"title_page": "题名页位置", "figures": "图片位置", "tables": "表格位置",
            "supplementary": "补充文件命名", "abbreviations": "缩略语表位置"}


def decisions(project: Path) -> list[dict]:
    """[{item, value, text_zh, basis_zh}] for the five layout decisions (S24 summary)."""
    from . import journalspec
    project = Path(project)
    target = _target(project)
    rows = []
    from . import portal  # 1.21.0 (B5): the submission system's own upload slots
    portal_rec = portal.current(project)
    vals = {"title_page": title_page_placement(target, project),
            "figures": figure_placement(target, project),
            "tables": table_placement(target, project),
            "supplementary": supplementary_pattern(target, project) or "",
            "abbreviations": journalspec.abbreviation_list(target, project)}
    for item, value in vals.items():
        b = basis(project, item)
        if item == "supplementary":
            text = (f"补充文件命名为 {value}（例如 {supplementary_stem(value, 1, 'Supplementary Methods')}.docx），"
                    f"正文仍称“{journalspec.esm_label(target)} n”" if value else
                    "补充文件沿用已有文件名（旧版论文，未迁移）")
        else:
            text = ZH[item].get(value, value)
        if item == "title_page" and journalspec.blinded(target):
            why = "盲审期刊（blinded_main_manuscript），正文保持匿名"
        elif b:
            why = f"投稿指南 {b['lines']} “{b['quote'][:80]}”"
        elif item == "title_page" and portal_rec.get("title_page_slot") is not None:
            why = ("投稿系统" + ("有" if portal_rec["title_page_slot"] else "没有") + "题名页上传项（"
                   f"portal_requirements.json，{portal_rec.get('read_at')}）")
        elif item == "title_page" and value == "both" and explicit(target, item) is None:
            why = "期刊 required_uploads 要求单独题名页（引擎默认规则）"
        elif explicit(target, item) is not None or (item == "figures" and legacy_embed(target)) \
                or (item == "tables" and "word_tables" in target and explicit(target, item) is None):
            why = "target_journal.json 显式设置（未找到指南依据）"
        else:
            why = "引擎默认（指南未规定）"
        rows.append({"item": item, "value": value, "text_zh": text, "basis_zh": why})
    return rows


def decisions_zh(project: Path) -> list[str]:
    rows = decisions(project)
    return ["版式决定（依据）："] + [f"- {LABEL_ZH[r['item']]}：{r['text_zh']}。依据：{r['basis_zh']}"
                                  for r in rows]


def _manifest(project: Path) -> list[dict]:
    man = _json(Path(project) / MANIFEST)
    return [i for i in (man.get("items") or []) if isinstance(i, dict)] if isinstance(man, dict) else []


def applies(project: Path, target: dict | None = None) -> bool:
    target = _target(project) if target is None else target
    return since_1190_project(project) or any(explicit(target, w) for w in
                                              ("title_page", "figures", "tables", "supplementary"))


def problems(project: Path) -> list[str]:
    """Blocking layout problems (gate layout_from_guideline, S23)."""
    from . import journalspec
    project = Path(project)
    target = _target(project)
    out: list[str] = []
    blinded = journalspec.blinded(target)
    need = "needs a guideline requirement in guideline_requirements.json (rule.field {f}, quote + " \
           "lines; category {c}) - the placement is never chosen by judgment; remove the field to " \
           "use the engine default"
    tp = explicit(target, "title_page")
    if blinded and tp in ("in_manuscript", "both"):
        out.append(f"title_page.placement = {tp}, but the journal is blinded: the title page is a "
                   "separate file and the manuscript stays anonymous (set it to separate)")
    elif tp and tp != default_title_page(target) and not basis(project, "title_page"):
        out.append(f"title_page.placement = {tp} " + need.format(f="title_page.placement", c="title_page"))
    fg = explicit(target, "figures")
    if fg and fg != "separate_files" and not basis(project, "figures"):
        out.append(f"figures.placement = {fg} " + need.format(f="figures.placement", c="figures"))
    if fg is None and target.get("embed_figures") is True and since_1190_project(project) \
            and not basis(project, "figures"):
        out.append("embed_figures = true puts the figure images into the manuscript; since 1.19.0 "
                   "figures are separate files unless the guide says otherwise: set "
                   "figures.placement from a guideline requirement (rule.field figures.placement, "
                   "quote + lines) or remove embed_figures")
    tb = explicit(target, "tables")
    if tb and tb != "end_of_manuscript" and not basis(project, "tables"):
        out.append(f"tables.placement = {tb} " + need.format(f="tables.placement", c="tables"))
    pat = explicit(target, "supplementary")
    if pat:
        if "{n}" not in pat:
            out.append(f"supplementary_file_pattern '{pat}' must contain {{n}} (the in-text number)")
        if not basis(project, "supplementary"):
            out.append("supplementary_file_pattern " + need.format(
                f="supplementary_file_pattern", c="supplementary") + " (an 'e.g.' example in the "
                "guide is not a mandate; 'name the files consecutively' is met by the default)")
    items = _manifest(project)
    roles = {str(i.get("role", "")).casefold() for i in items}
    place = title_page_placement(target, project)
    if place == "in_manuscript" and "title_page" in roles and applies(project, target):
        out.append("the title page is on the manuscript's first page (title_page.placement "
                   "in_manuscript); a separate title-page file is uploaded only when the guide or "
                   "required_uploads asks (placement both) - remove it from the manifest")
    if explicit(target, "figures") and figures_embedded(target, project) and \
            not figures_separate(target, project):
        extra = [i["file"] for i in items if str(i.get("role", "")).casefold() == "figures"
                 and str(i.get("file", "")).casefold().endswith((".tif", ".tiff", ".eps", ".png",
                                                                  ".jpg", ".pdf"))]
        if extra:
            out.append("figures are embedded in the manuscript and also listed as separate files ("
                       + ", ".join(Path(x).name for x in extra[:3]) + "); upload both only when "
                       "the guide asks (figures.also_separate from a requirement)")
    pattern = supplementary_pattern(target, project)
    if pattern:
        for line in rename_supplementary(project, dry=True):
            out.append(f"supplementary file name does not follow {pattern}: {line} (wf rebuild "
                       "renames it)")
    cover = project / COVER
    if cover.is_file() and items:
        names = {Path(str(i.get("file", ""))).name.casefold() for i in items}
        stale = sorted({m.group(0) for m in re.finditer(r"\b[\w-]+\.(?:docx|pdf|xlsx|tiff?|eps)\b",
                                                        cover.read_text(encoding="utf-8", errors="replace"))
                        if m.group(0).casefold() not in names})
        if stale:
            out.append("the cover letter names file(s) not in the bundle: " + ", ".join(stale[:4])
                       + " - use the current upload names (or the in-text labels)")
    return out
