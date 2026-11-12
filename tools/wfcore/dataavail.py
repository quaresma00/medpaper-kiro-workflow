"""1.23.0 (S6): data availability from verified public facts, not from memory or the user.

    wf data licence NAME --licence "CC BY 4.0" --access open|registration|credentialed|application|published \
        --url URL [--doi DOI] --source URL [--checked YYYY-MM-DD]
    wf data availability          the generated statement (paste it into statements.md)

Per data source: licence, access mode, URL/DOI, date checked and the public page the facts come
from (dataset descriptor paper, data portal or licence page). The S21 gate
data_availability_verified: every data source of the paper has such a record, and the Data
availability statement names each source (name, URL or DOI) with its access mode and cites the
dataset DOI when one exists - so "both datasets need credentialed access" cannot stand when one
of them is CC BY 4.0 open access.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from pathlib import Path

REL = ".wf/data_availability.json"
ACCESS = ("open", "registration", "credentialed", "application", "published")
ACCESS_WORDS = {"open": r"open(?:ly)?[- ]access|openly available|publicly available|freely available|open[- ]licen[cs]e|CC[- ]BY",
                "registration": r"registration|register",
                "credentialed": r"credential",
                "application": r"application|on request|upon request|request",
                "published": r"published|included (?:articles|studies)|supplementary"}
SENTENCE = {
    "open": "{name} data are openly available at {where} under the {licence} licence.",
    "registration": "{name} data are available at {where} after free registration ({licence}).",
    "credentialed": "{name} data are available at {where} to credentialed users who complete the required training and sign the data use agreement ({licence}).",
    "application": "{name} data are available at {where} on application to the data custodian ({licence}).",
    "published": "{name}: all data are in the published articles cited in the references ({licence}).",
}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load(project: Path) -> dict:
    try:
        data = json.loads((Path(project) / REL).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("schema", 1)
    data.setdefault("sources", {})
    return data


def record(project: Path, name: str, licence: str, access: str, url: str, source: str,
           doi: str = "", checked: str = "", label: str = "") -> dict:
    if access not in ACCESS:
        raise ValueError(f"access must be one of {', '.join(ACCESS)}")
    if not str(licence).strip():
        raise ValueError("--licence: the licence or terms as the source states them (e.g. CC BY 4.0)")
    if not re.match(r"^https?://", str(url or "")) and not doi:
        raise ValueError("--url (the data portal) or --doi is required")
    if not re.match(r"^https?://", str(source or "")):
        raise ValueError("--source: the public page the facts come from (portal, licence page, "
                         "dataset descriptor paper)")
    checked = checked or date.today().isoformat()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", checked):
        raise ValueError("--checked must be YYYY-MM-DD")
    data = load(project)
    data["sources"][name] = {"label": label or name, "licence": licence.strip(), "access": access,
                             "url": url or "", "doi": doi.strip(), "checked": checked,
                             "source": source, "recorded_at": _now()}
    p = Path(project) / REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return data["sources"][name]


def paper_sources(project: Path) -> list[str]:
    """Data sources the paper uses: declared datasets (`wf data add`), web captures and the
    sources named in the acquisition manifest."""
    from . import datasources
    names = [str(d.get("name")) for d in datasources.load(project) if d.get("name")]
    web = Path(project) / "02_data/raw/web"
    if web.is_dir():
        names += [f"web:{d.name}" for d in sorted(web.iterdir()) if d.is_dir()]
    try:
        man = json.loads((Path(project) / "02_data/acquisition_manifest.json").read_text(encoding="utf-8"))
        for s in man.get("sources", []) if isinstance(man, dict) else []:
            if isinstance(s, dict) and (s.get("name") or s.get("id")):
                names.append(str(s.get("name") or s.get("id")))
    except (OSError, ValueError):
        pass
    return list(dict.fromkeys(names))


def statement(project: Path) -> str:
    out = []
    for name, r in sorted(load(project)["sources"].items()):
        where = (f"https://doi.org/{r['doi']}" if r.get("doi") else r.get("url")) or r.get("url")
        if r.get("doi") and r.get("url"):
            where = f"{r['url']} (https://doi.org/{r['doi']})"
        out.append(SENTENCE[r["access"]].format(name=r.get("label") or name, where=where,
                                                licence=r["licence"]))
    return " ".join(out)


def _da_section(text: str) -> str:
    m = re.search(r"(?ims)^#{1,6}\s*Data (?:availability|sharing)[^\n]*\n(.*?)(?=^#{1,6}\s|\Z)", text)
    return m.group(1) if m else ""


def problems(project: Path) -> list[str]:
    project = Path(project)
    recs = load(project)["sources"]
    out = []
    names = paper_sources(project)
    if not names and not recs:
        return ["no data source recorded: `wf data licence NAME --licence ... --access ... --url ... "
                "--source ...` from the public portal or licence page"]
    for n in names:
        if n not in recs:
            out.append(f"data source '{n}': licence and access mode not verified (wf data licence "
                       f"{n} ... --source <public page>)")
    for n, r in recs.items():
        for k in ("licence", "access", "checked", "source"):
            if not r.get(k):
                out.append(f"data source '{n}': '{k}' missing")
    rel = next((r for r in ("08_submission/manuscript/statements.md", "07_manuscript/statements.md")
                if (project / r).is_file()), None)
    text = (project / rel).read_text(encoding="utf-8") if rel else ""
    sec = _da_section(text)
    if not sec.strip():
        out.append("no 'Data availability' section in statements.md (paste `wf data availability`)")
        return out
    bib = ""
    try:
        bib = (project / "06_refs/refs.bib").read_text(encoding="utf-8").casefold()
    except OSError:
        pass
    sentences = re.split(r"(?<=[.;])\s+", sec)
    for n, r in recs.items():
        keys = [x for x in (r.get("label"), n, r.get("url"), r.get("doi")) if x]
        hit = [s for s in sentences if any(k.casefold() in s.casefold() for k in keys)]
        if not hit:
            out.append(f"the Data availability statement does not name '{r.get('label') or n}'")
            continue
        if not any(re.search(ACCESS_WORDS[r["access"]], s, re.I) for s in hit):
            out.append(f"the statement does not say that '{r.get('label') or n}' is "
                       f"{r['access']} ({r['licence']}; checked {r['checked']} at {r['source']})")
        if r.get("doi") and r["doi"].casefold() not in sec.casefold() and r["doi"].casefold() not in bib:
            out.append(f"dataset '{r.get('label') or n}' has DOI {r['doi']}: cite it by DOI")
    return out
