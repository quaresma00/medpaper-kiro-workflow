"""1.10.0: ethics, consent and data-availability statements judged by the workflow.

The study design and data source are captured as structured fields at S01/S03
(`01_protocol/idea.json`: `study_design`, `data_source`). From them the workflow writes a
conclusion and its basis for ethics approval, consent and data availability, and asks the author
only for the specific facts it cannot determine (for example the approval number of an own-centre
retrospective study). Stored in 08_submission/declarations_assessment.json; the author's answers
are kept across re-assessments by question id.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

IDEA = "01_protocol/idea.json"
REL = "08_submission/declarations_assessment.json"
DESIGNS = (
    "cross_sectional", "cohort_retrospective", "cohort_prospective", "case_control", "rct",
    "diagnostic_accuracy", "prognostic_model", "mendelian_randomization", "meta_analysis",
    "systematic_review", "secondary_analysis", "qualitative", "case_report", "other",
)
SOURCE_TYPES = (
    "public_database", "own_centre_retrospective", "prospective_collection", "biospecimens",
    "third_party_registry", "published_studies",
)
# Ethics oversight that well-known public databases document themselves (cite their own approval).
KNOWN_DATABASES = {
    "nhanes": "the NCHS Research Ethics Review Board approved the NHANES protocols and "
              "participants gave written informed consent",
    "mimic": "the institutional review boards of Beth Israel Deaconess Medical Center and the "
             "Massachusetts Institute of Technology approved the MIMIC database with a waiver of "
             "informed consent",
    "uk biobank": "UK Biobank has approval from the North West Multi-centre Research Ethics "
                  "Committee and all participants gave written informed consent",
    "charls": "the Biomedical Ethics Review Committee of Peking University approved CHARLS and "
              "participants gave informed consent",
}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def basis_problems(idea: dict) -> list[str]:
    """Why the structured study basis is incomplete (empty = usable)."""
    out = []
    design = idea.get("study_design")
    if design not in DESIGNS:
        out.append(f"study_design must be one of {', '.join(DESIGNS)} (got {design!r})")
    elif design == "other" and len(str(idea.get("study_design_detail", "")).strip()) < 10:
        out.append("study_design 'other' needs study_design_detail")
    src = idea.get("data_source")
    if not isinstance(src, dict):
        return out + ["data_source must be an object {type, name, third_party, redistributable, "
                      "deidentified, vulnerable_populations}"]
    types = src.get("type")
    types = types if isinstance(types, list) else [types]
    bad = [t for t in types if t not in SOURCE_TYPES]
    if not types or bad:
        out.append(f"data_source.type must be one or more of {', '.join(SOURCE_TYPES)} "
                   f"(got {src.get('type')!r})")
    if len(str(src.get("name", "")).strip()) < 2:
        out.append("data_source.name is empty")
    for key in ("third_party", "redistributable", "deidentified"):
        if src.get(key) not in (True, False, "unknown"):
            out.append(f"data_source.{key} must be true, false or \"unknown\"")
    if not isinstance(src.get("vulnerable_populations"), list):
        out.append("data_source.vulnerable_populations must be a list ([] when none)")
    return out


def _types(src: dict) -> list[str]:
    t = src.get("type")
    return t if isinstance(t, list) else [t]


def needs_human_coding(idea: dict) -> bool | None:
    """1.13.0 (#7): does the study basis declare manual abstraction, coding or reading?

    Only then do coder qualifications, double data entry, adjudication or inter-rater
    agreement come up. `data_source.manual_abstraction` (true/false) decides; without it a
    meta-analysis / systematic review counts as manual extraction, public databases and
    registry files as automated, anything else as undeclared (None = ask once at S01)."""
    src = idea.get("data_source") if isinstance(idea.get("data_source"), dict) else {}
    flag = src.get("manual_abstraction", idea.get("manual_abstraction"))
    if isinstance(flag, bool):
        return flag
    if idea.get("study_design") in ("meta_analysis", "systematic_review"):
        return True
    types = {t for t in _types(src) if t}
    if types and types <= {"public_database", "third_party_registry"}:
        return False
    return None


def review_rules(project: Path) -> list[str]:
    """Study-specific lines for the reviewer brief (multi-person checks, protocol talk)."""
    from .checks.text import deviation_reporting_allowed
    try:
        idea = json.loads((Path(project) / IDEA).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        idea = {}
    idea = idea if isinstance(idea, dict) else {}
    out = []
    if needs_human_coding(idea) is not True:
        name = str((idea.get("data_source") or {}).get("name", "")).strip() \
            if isinstance(idea.get("data_source"), dict) else ""
        out.append("Study basis: data are extracted by code" + (f" from {name}" if name else "")
                   + " (no manual abstraction or coding). Do not request double data entry, "
                   "multiple coders, adjudicators or inter-rater agreement; judge the "
                   "documented extraction rules instead.")
    if not deviation_reporting_allowed(project):
        out.append("The protocol is internal (not a registered meta-analysis): do not ask for "
                   "registration, protocol deviations or an initial-versus-final plan; judge the "
                   "analysis as described.")
    return out


def assess(idea: dict) -> dict:
    """Conclusion + basis for ethics, consent and data availability; open author questions."""
    design = idea.get("study_design")
    src = idea.get("data_source") or {}
    name = str(src.get("name", "")).strip()
    types = _types(src)
    vulnerable = [str(v) for v in src.get("vulnerable_populations") or []]
    questions: list[dict] = []
    ethics, consent = [], []
    basis = [f"study_design={design}", f"data_source.type={'+'.join(map(str, types))}",
             f"deidentified={src.get('deidentified')}", f"third_party={src.get('third_party')}",
             f"redistributable={src.get('redistributable')}",
             "vulnerable_populations=" + (", ".join(vulnerable) or "none")]

    def ask(qid: str, text: str) -> None:
        questions.append({"id": qid, "ask": text})

    if design in ("meta_analysis", "systematic_review") or types == ["published_studies"]:
        ethics.append("Ethics approval was not required because only published, aggregate data "
                      "were analysed.")
        consent.append("Not applicable (no individual participants were enrolled).")
    for t in types:
        if t == "public_database":
            known = next((v for k, v in KNOWN_DATABASES.items() if k in name.casefold()), None)
            if src.get("deidentified") is not True:
                ask("public_deidentified", f"Is the {name} release you analysed de-identified "
                    "(yes/no)?")
            ethics.append(f"This secondary analysis of de-identified public data from {name} "
                          "typically does not require additional institutional review"
                          + (f"; {known}." if known else "."))
            consent.append("Additional consent was not required for this secondary analysis"
                           + (" (original consent obtained by the database)." if known else "."))
            if not known and not str(src.get("source_ethics", "")).strip():
                ask("source_ethics", f"Which committee approved {name} itself (name, or the "
                    "database documentation URL that states it)?")
        elif t == "own_centre_retrospective":
            ethics.append(f"Retrospective use of records from {name} requires approval by the "
                          "institutional ethics committee.")
            consent.append("Informed consent is usually waived by the committee for retrospective "
                           "record review.")
            ask("ethics_committee_and_number", f"Ethics committee name and approval number for "
                "the {name} records?")
            ask("consent_waiver", "Did that committee waive informed consent (yes/no)?")
        elif t == "prospective_collection":
            ethics.append("Prospective data collection requires ethics committee approval before "
                          "enrolment.")
            consent.append("Written informed consent from every participant is required.")
            ask("ethics_committee_and_number", "Ethics committee name and approval number?")
            ask("consent_obtained", "Confirm written informed consent was obtained (yes/no).")
        elif t == "biospecimens":
            ethics.append("Use of human biospecimens requires ethics committee approval.")
            consent.append("Consent covering research use of the specimens is required (study "
                           "consent or biobank broad consent).")
            ask("ethics_committee_and_number", "Ethics committee name and approval number for "
                "the specimen use?")
            ask("specimen_consent", "Which consent covers the specimens (study consent / biobank "
                "broad consent / waiver)?")
        elif t == "third_party_registry":
            ethics.append(f"Licensed third-party data from {name}: approval or exemption follows "
                          "the data provider's and the institution's rules.")
            consent.append("Consent is normally covered or waived under the provider's governance.")
            ask("registry_approval", f"Ethics approval number or formal exemption for the {name} "
                "analysis?")
    if vulnerable:
        consent.append("Vulnerable groups (" + ", ".join(vulnerable) + ") need guardian consent "
                       "or assent where they were enrolled directly.")
        if any(t in ("prospective_collection", "biospecimens") for t in types):
            ask("vulnerable_consent", "How was consent obtained for " + ", ".join(vulnerable)
                + " (guardian consent / assent / waiver)?")
    if src.get("redistributable") is True:
        availability = f"The data analysed are publicly available from {name}."
    elif src.get("third_party") is True or "public_database" in types:
        availability = (f"The data are available from {name} under its data use terms; the "
                        "authors are not permitted to redistribute them.")
    elif design in ("meta_analysis", "systematic_review"):
        availability = ("All data were extracted from the published studies cited; the "
                        "extraction sheet is provided in the Supplementary Material.")
    else:
        availability = ("The data are not publicly available because they contain patient "
                        "information; de-identified data are available from the corresponding "
                        "author on reasonable request with institutional approval.")
    if src.get("redistributable") == "unknown" or src.get("third_party") == "unknown":
        ask("redistribution", f"May the {name} data be shared by the authors (yes/no)?")
    seen, unique = set(), []
    for q in questions:
        if q["id"] not in seen:
            seen.add(q["id"])
            unique.append(q)
    return {"ethics": {"conclusion": " ".join(dict.fromkeys(ethics)) or "Not determinable.",
                       "basis": basis},
            "consent": {"conclusion": " ".join(dict.fromkeys(consent)) or "Not determinable.",
                        "basis": basis},
            "data_availability": {"text": availability, "basis": basis},
            "questions": unique}


def idea_sha256(project: Path) -> str:
    return hashlib.sha256((Path(project) / IDEA).read_bytes()).hexdigest()


def load(project: Path) -> dict:
    try:
        data = json.loads((Path(project) / REL).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write(project: Path) -> dict:
    """(Re)assess from idea.json, keeping the author's answers to questions still asked."""
    idea = json.loads((Path(project) / IDEA).read_text(encoding="utf-8"))
    problems = basis_problems(idea)
    if problems:
        raise ValueError("idea.json study basis incomplete: " + "; ".join(problems))
    old = load(project).get("answers", {})
    out = assess(idea)
    out["answers"] = {q["id"]: old[q["id"]] for q in out["questions"] if q["id"] in old}
    out.update(idea_sha256=idea_sha256(project), assessed_at=_now())
    path = Path(project) / REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


def answer(project: Path, qid: str, value: str) -> dict:
    data = load(project)
    if not data:
        raise ValueError(f"{REL} missing: run tools/declarations.py assess first")
    if qid not in {q["id"] for q in data.get("questions", [])}:
        raise ValueError(f"no open question {qid!r}; the workflow did not ask it")
    if len(value.strip()) < 2:
        raise ValueError("record the author's answer")
    data.setdefault("answers", {})[qid] = {"value": value.strip(), "at": _now()}
    (Path(project) / REL).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                                     encoding="utf-8")
    return data


def pending(data: dict) -> list[dict]:
    answers = data.get("answers", {})
    return [q for q in data.get("questions", []) if q["id"] not in answers]


# --------------------------------------------------------------------------- 1.15.0 (E10)
AI_RULE_RE = (r"(?i)(large language model|\bLLMs?\b|generative (?:AI|artificial)|"
              r"artificial intelligence|\bAI\b[- ](?:assisted|generated|tools?|use)|ChatGPT|"
              r"chatbot)")


def ai_requirement(project: Path) -> str:
    """The journal's AI/LLM-use rule, verbatim from the guideline snapshot ('' = silent)."""
    from .guidelines import section
    return section(project, AI_RULE_RE)


def ai_statement(fact: dict) -> str:
    if not fact.get("used"):
        return ("No generative artificial intelligence (AI) or large language model tools were "
                "used to write this manuscript or to analyse its data.")
    return (f"During the preparation of this work the authors used {fact['tool']} for "
            f"{fact['purpose']}. The authors reviewed and edited the output and take full "
            "responsibility for the content of the publication.")


def record_ai(project: Path, used: bool, tool: str, purpose: str, words: str) -> dict:
    """The author's FACTUAL answer on AI/LLM use (used or not, tool, purpose), in their words."""
    if len(words.strip()) < 2:
        raise ValueError("record the author's own answer (--words)")
    if used and (len(tool.strip()) < 2 or len(purpose.strip()) < 5):
        raise ValueError("when AI/LLM tools were used, record the tool and the purpose")
    data = load(project)
    if not data:
        raise ValueError(f"{REL} missing: run tools/declarations.py assess first")
    fact = {"used": bool(used), "tool": tool.strip() if used else "",
            "purpose": purpose.strip() if used else "", "author_words": words.strip(),
            "at": _now()}
    fact["statement"] = ai_statement(fact)
    rule = ai_requirement(project)
    fact["journal_rule"] = rule[:1500]
    data["ai_use"] = fact
    (Path(project) / REL).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                                     encoding="utf-8")
    return fact


def ai_fact(project: Path) -> dict | None:
    fact = load(project).get("ai_use")
    return fact if isinstance(fact, dict) and "used" in fact else None
