"""1.25.0 regression tests: the display benchmark from the most recent comparable papers; after
assembly only cross-section consistency, journal adaptation and changed paragraphs.

A benchmark.py search / skip / exceptions / unknown counts and the S07 recency gate (mocked
E-utilities and Europe PMC), B1 the S22 card and polish_log headings, B2 editor receipts for
paragraphs changed after assembly (journal copy included), B3 the cross-section report, C cards,
SKILL, README and the release policy. Synthetic fixtures only - no real paper, dataset, network
or browser. Called from tools/selftest.py.
"""
from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from selftest_v1140 import _envset, _gate, _out, _paper, _run, _w  # noqa: E402
from selftest_v1230 import _Http  # noqa: E402

EU = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"


def run(tmp: Path, record, section, only: str = "") -> None:
    tmp.mkdir(parents=True, exist_ok=True)
    for name, fn in GROUPS:
        if not only or name in only.split():
            fn(tmp / name, record, section)


def _pin(p: Path, version: str) -> None:
    st = json.loads((p / ".wf/state.json").read_text(encoding="utf-8"))
    st["engine_pin"] = version
    (p / ".wf/state.json").write_text(json.dumps(st), encoding="utf-8")


# ------------------------------------------------------------------------------ A
def _basis(p: Path) -> None:
    _w(p, "01_protocol/idea.json", {"study_design": "secondary_analysis", "data_source": {
        "type": ["public_database"], "name": "FAERS", "third_party": True,
        "redistributable": True, "deidentified": True}})
    _w(p, "01_protocol/display_dictionary.json", {"entries": [
        {"internal": "drug_x", "label": "Semaglutide", "role": "exposure"},
        {"internal": "ali", "label": "Acute pancreatitis", "role": "outcome"},
        {"internal": "sex", "label": "Female sex"}]})


def _records(n: int, extra: bool = True) -> list[dict]:
    recs = [{"uid": str(9000 + i), "epubdate": f"2025 {['Dec', 'Nov', 'Oct', 'Sep', 'Aug', 'Jul', 'Jun', 'May', 'Apr', 'Mar'][i]} 1",
             "pubdate": "2026 Jan", "source": "Drug Saf", "title": f"Comparable paper {i}",
             "pubtype": ["Journal Article"], "lang": ["eng"]} for i in range(n)]
    if extra:
        recs += [{"uid": "8001", "pubdate": "2025 Dec", "source": "Drugs", "title": "A review",
                  "pubtype": ["Journal Article", "Review"], "lang": ["eng"]},
                 {"uid": "8002", "pubdate": "2025 Dec", "source": "BMJ", "title": "A letter",
                  "pubtype": ["Letter"], "lang": ["eng"]},
                 {"uid": "8003", "pubdate": "2025 Dec", "source": "Yakugaku", "title": "Japanese",
                  "pubtype": ["Journal Article"], "lang": ["jpn"]}]
    return recs


def _eutils(recs: list[dict], seen: list):
    def es(prm):
        seen.append(dict(prm))
        return json.dumps({"esearchresult": {"count": str(len(recs)),
                                             "idlist": [r["uid"] for r in recs]}}).encode()

    def summ(prm):
        ids = prm["id"].split(",")
        return json.dumps({"result": {"uids": ids, **{r["uid"]: r for r in recs
                                                      if r["uid"] in ids}}}).encode()

    def epmc(prm):
        pmid = prm["query"].split(":")[1].split()[0]
        return json.dumps({"resultList": {"result": [{"pmid": pmid, "title": f"Paper {pmid}",
                                                      "journalTitle": "Drug Saf", "pubYear": "2025",
                                                      "isOpenAccess": "N"}]}}).encode()
    return _Http({f"{EU}/esearch.fcgi": es, f"{EU}/esummary.fcgi": summ, EPMC: epmc})


PLAN = {"main_figures": [{"id": "Figure 1", "title": "Flow chart of case selection",
                          "archetype": "flow_diagram"},
                         {"id": "Figure 2", "title": "Forest plot of reporting odds ratios",
                          "display_type": "forest_ror"},
                         {"id": "Figure 3", "title": "Annual reports"}],
        "main_tables": [{"id": "Table 1", "title": "Characteristics of the reports"}],
        "supp_figures": [], "supp_tables": [], "supp_files": []}


def run_bench(tmp: Path, record, section) -> None:
    from wfcore import displaybench as db
    from pubmed import benchmark as bm
    section("1.25.0 A: display benchmark from the 5-10 most recent comparable papers")
    p = _paper(tmp / "p", "S07_artifacts")
    _basis(p)
    q, start, end = db.build_query(p, "disproportionality", searched=datetime(2026, 2, 1,
                                                                               tzinfo=timezone.utc))
    record("A1 the query comes from the study basis (disproportionality + FAERS family) and the "
           "exposure/outcome labels, with original-article, English and 3-year date filters",
           "disproportionality[tiab]" in q and '"FAERS"[tiab]' in q and '"Semaglutide"[tiab]' in q
           and '"Acute pancreatitis"[tiab]' in q and '"Female sex"' not in q
           and '"review"[pt]' in q and '"case reports"[pt]' in q and '"meta-analysis"[pt]' in q
           and "english[la]" in q and start == "2023-02-01" and '"2026/02/01"[dp]' in q, q)
    seen: list = []
    http = _eutils(_records(10), seen)
    old = bm.eu.http_get
    bm.eu.http_get = http
    try:
        with _envset(MEDPAPER_PROJECT=str(p), NCBI_API_KEY="test-key"):
            s = bm.search(p)
            short = _paper(tmp / "short", "S07_artifacts")
            _basis(short)
            bm.eu.http_get = _eutils(_records(3, extra=False), [])
            with _envset(MEDPAPER_PROJECT=str(short)):
                s_short = bm.search(short)
            bm.eu.http_get = http
            for c in s["candidates"][:2]:
                bm.add(p, c["pmid"], "disproportionality", figures=3, tables=1, supplementary=4,
                       types=["flow_diagram", "forest_ror"], source="manual")
            _w(p, "01_protocol/artifact_plan.json", PLAN)
            g_few = _gate(p, "display_plan_benchmarked", "S07_artifacts")
            for c in s["candidates"][3:6]:
                bm.add(p, c["pmid"], "disproportionality", figures=3, tables=1, supplementary=4,
                       types=["flow_diagram", "forest_ror"], source="manual")
            g_gap = _gate(p, "display_plan_benchmarked", "S07_artifacts")
            try:
                db.skip(p, s["candidates"][2]["pmid"], "not_comparable", "x")
                short_note = "accepted"
            except ValueError as exc:
                short_note = str(exc)
            db.skip(p, s["candidates"][2]["pmid"], "not_comparable",
                    "single-centre hospital cohort, not a FAERS analysis")
            g_ok = _gate(p, "display_plan_benchmarked", "S07_artifacts")
            bm.add(p, "7777", "disproportionality", figures=9, tables=9, supplementary=9,
                   types=["flow_diagram"], source="manual")
            g_out = _gate(p, "display_plan_benchmarked", "S07_artifacts")
            bm.add(p, "7777", "disproportionality", figures=9, tables=9, supplementary=9,
                   types=["flow_diagram"], source="manual",
                   exception="the only comparable paper in the target journal (2019)")
            bm.add(p, s["candidates"][6]["pmid"], "disproportionality", unknown_counts=True)
            g_exc = _gate(p, "display_plan_benchmarked", "S07_artifacts")
    finally:
        bm.eu.http_get = old
    cands = s["candidates"]
    record("A1 search: E-utilities sorted by pub_date with the API key, metadata only; reviews, "
           "letters and non-English excluded; most recent first (electronic date); 3-year window; "
           "the log is written", bool(seen) and seen[0].get("sort") == "pub_date"
           and seen[0].get("api_key") == "test-key" and len(cands) == 10
           and not {"8001", "8002", "8003"} & {c["pmid"] for c in cands}
           and cands[0]["date"] == "2025-12-01" and cands[-1]["date"] == "2025-03-01"
           and s["window_years"] == 3 and (p / db.SEARCH_REL).is_file(),
           json.dumps(seen[:1])[:300] + str([c["date"] for c in cands]))
    record("A2 fewer than 5 candidates in 3 years -> the window extends to 5 years by itself, recorded",
           s_short["window_years"] == 5 and "automatic" in s_short.get("extended_reason", ""),
           str({k: s_short.get(k) for k in ("window_years", "extended_reason")}))
    summ = db.summary(db.load(p))
    msg = "\n".join(db.message_zh(p))
    record("A4 gate (1.25.0): 2 papers fail (5-10 needed); a more recent candidate passed over "
           "without a reason fails; a skip needs a one-line note; with the reason it passes",
           not g_few.ok and "2 paper(s) included" in g_few.detail and not g_gap.ok
           and f"PMID {cands[2]['pmid']}" in g_gap.detail and "--note" in short_note
           and g_ok.ok and "recency" in g_ok.detail, g_few.detail[:200] + " | " + g_gap.detail[:200]
           + " | " + g_ok.detail[:200])
    record("A2/A3 a paper outside the search log fails unless it is a recorded exception; the "
           "exception and an abstract-only paper are listed but stay outside the median",
           not g_out.ok and "not a candidate" in g_out.detail and g_exc.ok and summ["n"] == 5
           and summ["median_main_items"] == 4, g_out.detail[:200] + " | " + str(summ)[:200])
    record("A4 the Chinese S07 lines name the search window and each included paper (year, "
           "journal, main figures/tables), exceptions and unknown counts, and the plan",
           "检索：" in msg and "近 3 年" in msg and "- 2025 Drug Saf：正文图 3、表 1" in msg
           and "例外：" in msg and "仅摘要，图表数未知" in msg and "本文计划：正文图 3 张" in msg,
           msg[:600])
    old_p = _paper(tmp / "old", "S07_artifacts")
    _pin(old_p, "1.24.0")
    shutil.copyfile(p / db.REL, (old_p / db.REL).parent.mkdir(parents=True, exist_ok=True)
                    or old_p / db.REL)
    data = db.load(old_p)
    data["papers"] = [x for x in data["papers"] if not x.get("exception")][:3]
    db.save(old_p, data)
    _w(old_p, "01_protocol/artifact_plan.json", PLAN)
    g_pin = _gate(old_p, "display_plan_benchmarked", "S07_artifacts")
    record("A4 a paper pinned to 1.24.0 keeps the 1.23 rule (3 papers, no search log needed)",
           g_pin.ok and "recency" not in g_pin.detail, g_pin.detail[:300])


# ------------------------------------------------------------------------------ B1
OLD_LOG = ("# AI patterns removed\n\nnone\n\n# Language changes by section\n\nnone\n\n# House "
           "style decisions\n\nUS\n\n# Cut to meet journal limits\n\nnone\n\n# Read by eye\n\nyes"
           "\n\n# Tier-B phrases kept\n\nnone\n")
NEW_LOG = ("# Cross-section consistency fixes\n\nOne population name.\n\n# Journal adaptation\n\n"
           "Structured abstract.\n\n# Re-polished paragraphs (editor receipts)\n\nResults 2.\n\n# "
           "Cut to meet journal limits\n\nnone\n\n# Tier-B phrases kept\n\nnone\n")


def run_s22(tmp: Path, record, section) -> None:
    from wfcore import registry
    section("1.25.0 B1: S22 without a second full polish")
    card = (ROOT / "pipeline/stages/S22_polish.md").read_text(encoding="utf-8")
    det = (ROOT / "reference/stage_details/S22_polish.md").read_text(encoding="utf-8")
    heads = ("Cross-section consistency fixes", "Journal adaptation",
             "Re-polished paragraphs (editor receipts)", "Cut to meet journal limits",
             "Tier-B phrases kept")
    record("B1 the S22 card and details drop 'Reread everything' and the old log headings, name "
           "the five new ones, crosscheck and --section manuscript",
           all(x not in card + det for x in ("Reread everything", "AI patterns removed",
                                              "Language changes by section",
                                              "Reread the complete manuscript"))
           and all(h in card and h in det for h in heads) and "polish.py crosscheck" in card
           and "--section manuscript" in card and "not the\n   whole manuscript" in card
           and len(card) <= registry.CARD_MAX_CHARS)
    res = {}
    for name, pin, log in (("new_old", None, OLD_LOG), ("new_new", None, NEW_LOG),
                           ("pinned_old", "1.24.0", OLD_LOG)):
        p = _paper(tmp / name, "S22_polish")
        if pin:
            _pin(p, pin)
        _w(p, "07_manuscript/polish_log.md", log)
        res[name] = _gate(p, "polish_complete", "S22_polish").detail
    record("B1 polish_complete checks the new log headings on 1.25.0 papers; a pinned paper keeps "
           "the old headings", "log:" in res["new_old"] and "Journal adaptation" in res["new_old"]
           and "log:" not in res["new_new"] and "log:" not in res["pinned_old"],
           json.dumps(res)[:500])


# ------------------------------------------------------------------------------ B2
SECS = {"abstract": "# Abstract\n\nAmong 412 patients, mortality was 12.0%.",
        "introduction": "# Introduction\n\nPancreatitis is a serious adverse event.",
        "methods": "# Methods\n\nWe analysed reports submitted between 2004 and 2023.",
        "results": "# Results\n\nWe identified 412 patients with the event.\n\nThe reporting odds "
                   "ratio was 2.51 (95% CI 1.80-3.50) in women.",
        "discussion": "# Discussion\n\nThe signal was consistent across analyses."}


def _manuscript() -> str:
    return ("# A title\n\n" + "\n\n".join(SECS[k] for k in ("abstract", "introduction",
                                                            "methods", "results", "discussion"))
            + "\n\n# References\n\n1. Smith J. Paper. 2020.\n")


def _receipts(p: Path) -> None:
    for sec, text in SECS.items():
        _w(p, f".wf/writer/{sec}/polished.md", text + "\n")


def run_changed(tmp: Path, record, section) -> None:
    from wfcore import registry, sectionpolish as sp
    section("1.25.0 B2: editor receipts for paragraphs changed after assembly")
    p = _paper(tmp / "p", "S22_polish")
    _receipts(p)
    _w(p, "07_manuscript/full_manuscript.md", _manuscript())
    g0 = _gate(p, "changed_paragraphs_polished", "S22_polish")
    trimmed = _manuscript().replace("The signal was consistent across analyses.",
                                    "The signal held in every analysis we ran.")
    _w(p, "08_submission/manuscript/full_manuscript.md", trimmed)
    g1 = _gate(p, "changed_paragraphs_polished", "S22_polish")
    ch = sp.manuscript_changed(p)
    ed = _run(p, "tools/manuscript/writer_bundle.py", "edit", "--section", "manuscript",
              "--project", p)
    cm = p / ".wf/editor_bundle/manuscript/changed.md"
    changed = cm.read_text(encoding="utf-8") if cm.is_file() else ""
    record("B2 a trim in the journal copy is one changed paragraph; the editor bundle carries only "
           "that paragraph (unchanged ones are not sent); the gate names it",
           g0.ok and sp.manuscript_rel(p) == "08_submission/manuscript/full_manuscript.md"
           and len(ch) == 1 and not g1.ok and f"paragraph {ch[0]}" in g1.detail
           and ed.returncode == 0 and "held in every analysis" in changed
           and "412 patients" not in changed and changed.count("<!-- paragraph") == 1,
           g1.detail[:200] + " | " + _out(ed)[-200:] + " | " + changed[:200])
    pol = p / ".wf/editor_bundle/manuscript/polished.md"
    _w(p, ".wf/editor_bundle/manuscript/polished.md",
       f"<!-- paragraph {ch[0]} -->\nThe signal held in all 3 analyses.\n")
    bad = _run(p, "tools/manuscript/writer_bundle.py", "polished", "--section", "manuscript",
               "--project", p)
    pol.write_text(f"<!-- paragraph {ch[0]} -->\nThe signal was consistent in every analysis.\n",
                   encoding="utf-8")
    ok = _run(p, "tools/manuscript/writer_bundle.py", "polished", "--section", "manuscript",
              "--project", p)
    after = (p / "08_submission/manuscript/full_manuscript.md").read_text(encoding="utf-8")
    g2 = _gate(p, "changed_paragraphs_polished", "S23_package")
    again = _run(p, "tools/manuscript/writer_bundle.py", "edit", "--section", "manuscript",
                 "--project", p)
    record("B2 the editor's paragraph is refused when a number appears; accepted, it is merged "
           "under its heading, the gate passes at S23 and nothing is sent again",
           bad.returncode == 2 and "numbers changed" in _out(bad) and ok.returncode == 0
           and "# Discussion\n\nThe signal was consistent in every analysis." in after
           and "412 patients with the event." in after and g2.ok
           and again.returncode == 2 and "nothing to send" in _out(again),
           _out(bad)[-200:] + " | " + _out(ok)[-200:] + " | " + g2.detail[:200])
    q = _paper(tmp / "pinned", "S22_polish")
    _pin(q, "1.24.0")
    _receipts(q)
    _w(q, "07_manuscript/full_manuscript.md", trimmed)
    g3 = _gate(q, "changed_paragraphs_polished", "S22_polish")
    pipe = registry.load()
    names = {s: [(g["check"], g.get("block"), g.get("severity")) for g in pipe.stage(s).gate]
             for s in ("S17_assemble", "S22_polish", "S23_package")}
    record("B2 a paper pinned to 1.24.0 is not judged; S22 and S23 carry the gate, S17 warns with "
           "the cross-section report and S22 blocks with it",
           g3.ok and "pinned earlier" in g3.detail
           and ("changed_paragraphs_polished", None, None) in names["S22_polish"]
           and ("changed_paragraphs_polished", None, None) in names["S23_package"]
           and ("cross_section_consistent", None, "warn") in names["S17_assemble"]
           and ("cross_section_consistent", True, None) in names["S22_polish"], str(names)[:400])


# ------------------------------------------------------------------------------ B3
BAD = """# Liver injury with drug X

# Abstract

**Background:** Drug X is widely used.

**Methods:** We analysed reports to the FDA Adverse Event Reporting System (FAERS) from 2004 to 2023.

**Results:** Among 1204 reports, the reporting odds ratio was 2.15 (95% CI 1.80-3.50).

**Conclusions:** Drug X causes liver injury and should be avoided.

Keywords: liver injury, pharmacovigilance

# Introduction

Drug-induced liver injury remains a leading cause of acute liver failure in adults worldwide today.

# Methods

We used the reporting odds ratio (ROR) to measure disproportionality. The ROR was computed with a 95% confidence interval.

# Results

We identified 1204 reports. The ROR was 2.51 (95% CI 1.80-3.50) for liver injury. The reporting odds ratio (ROR) was higher in women.

# Discussion

Drug-induced liver injury remains a leading cause of acute liver failure in adults worldwide. Among 1204 patients, the signal was consistent.

In conclusion, drug X was associated with more frequent reporting of liver injury; this signal needs confirmation in cohort studies.

# References

1. Smith J. Paper. 2020.
"""


def run_cross(tmp: Path, record, section) -> None:
    from wfcore import crosscheck, reviewrounds
    section("1.25.0 B3: deterministic cross-section report")
    p = _paper(tmp / "p", "S22_polish")
    _w(p, "07_manuscript/full_manuscript.md", BAD)
    data = crosscheck.report(p, write=False)
    kinds_b = [x["kind"] for x in data["blocking"]]
    kinds_w = [x["kind"] for x in data["warnings"]]
    det = " ".join(x["detail"] for x in data["blocking"])
    rev = data["for_reviewer"]
    record("B3 blocking: an abbreviation defined twice in the body and an abstract number that is "
           "no value of the Results text or tables (2.15 vs 2.51); years and the 95% CI are not "
           "judged", "abbrev_redefined" in kinds_b and "abstract_number_mismatch" in kinds_b
           and "2.15" in det and "2004" not in det and "95" not in det.replace("2.15", "")
           .replace("1204", ""), json.dumps(data["blocking"])[:500])
    record("B3 warnings: Introduction/Discussion near-duplicate sentence; the same count called "
           "reports and patients; the abstract's stronger conclusion goes to the reviewer list",
           "near_duplicate" in kinds_w and "unit_interchanged" in kinds_w and len(rev) == 1
           and "caus" in rev[0]["detail"] and "should be" in rev[0]["detail"]
           and "In conclusion" in rev[0]["discussion"], json.dumps(data["warnings"])[:500])
    g22 = _gate(p, "cross_section_consistent", "S22_polish", block=True)
    g17 = _gate(p, "cross_section_consistent", "S17_assemble")
    q = _paper(tmp / "pinned", "S22_polish")
    _pin(q, "1.24.0")
    _w(q, "07_manuscript/full_manuscript.md", BAD)
    gpin = _gate(q, "cross_section_consistent", "S22_polish", block=True)
    good = BAD.replace("2.15", "2.51").replace("Among 1204 patients", "Among 1204 reports") \
        .replace("Drug-induced liver injury remains a leading cause of acute liver failure in "
                 "adults worldwide. ", "") \
        .replace(" The reporting odds ratio (ROR) was higher in women.", " It was higher in women.")
    r = _paper(tmp / "good", "S22_polish")
    _w(r, "07_manuscript/full_manuscript.md", good)
    ggood = _gate(r, "cross_section_consistent", "S22_polish", block=True)
    gd = crosscheck.report(r, write=False)
    record("B3 gate: the clear errors block at S22 on 1.25.0; S17 and a pinned paper only warn; "
           "a consistent manuscript passes with the reviewer item listed",
           not g22.ok and g22.severity == "fail" and not g17.ok and g17.severity == "warn"
           and not gpin.ok and gpin.severity == "warn" and not ggood.blocking
           and not gd["blocking"] and len(gd["for_reviewer"]) == 1,
           g22.detail[:200] + " | " + ggood.detail[:200] + json.dumps(gd["warnings"])[:300])
    cli = _run(p, "tools/text/polish.py", "crosscheck")
    _w(p, "08_submission/manuscript/full_manuscript.md", good)
    cli2 = _run(p, "tools/text/polish.py", "crosscheck")
    brief = reviewrounds.brief(r, {"id": "r1", "scope": "manuscript", "mode": "full"}, "B")
    record("B3 `polish.py crosscheck` exits 2 on blocking items and writes the report next to the "
           "manuscript (the journal copy once open); the S18 brief carries the reviewer item",
           cli.returncode == 2 and "BLOCK abbrev_redefined" in _out(cli)
           and (p / "07_manuscript/crosscheck_report.json").is_file() and cli2.returncode == 0
           and (p / "08_submission/manuscript/crosscheck_report.json").is_file()
           and "Cross-section report (engine)" in brief,
           _out(cli)[-300:] + " | " + _out(cli2)[-300:])


# ------------------------------------------------------------------------------ C
def run_release(tmp: Path, record, section) -> None:
    from wfcore import registry
    from wfcore.state import State
    section("1.25.0 C: one migration event, cards, SKILL and README")
    q = tmp / "mig"
    q.mkdir(parents=True, exist_ok=True)
    st = State(q, ".wf").create("medpaper", "1.24.0", "S07_artifacts")
    before = sorted(x.name for x in q.rglob("*"))
    st.migrate_pipeline("1.25.0", [s.id for s in registry.load().stages])
    st.migrate_pipeline("1.25.0", [s.id for s in registry.load().stages])
    notes = [e for e in st.data["events"] if e["kind"] == "requirements_changed"
             and str(e.get("detail", "")).startswith("1.25.0")]
    after = sorted(x.name for x in q.rglob("*"))
    pipe = registry.load()
    record("C pipeline 1.25.0; a 1.24.0 paper gets exactly one 1.25.0 event (search, crosscheck and "
           "the S22 card now; recency, receipts and blocking items after wf migrate --yes) and "
           "stays pinned; no paper file touched",
           pipe.meta.get("version") == "1.25.0" and len(notes) == 1
           and "wf migrate --yes" in notes[0]["detail"] and "benchmark.py search" in notes[0]["detail"]
           and "crosscheck" in notes[0]["detail"] and st.engine_pin == "1.24.0" and before == after,
           str(notes)[:300])
    cards = {s.id: (ROOT / "pipeline" / s.card).read_text(encoding="utf-8") for s in pipe.stages}
    skill = (ROOT / ".kiro/skills/medpaper-pipeline/SKILL.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    record("C S07 card: the most recent 5-10 papers via benchmark.py search/skip; S17 crosscheck; "
           "SKILL one line each; README 1.25.0; every card within the limit",
           "MOST RECENT" in cards["S07_artifacts"] and "benchmark.py search" in cards["S07_artifacts"]
           and "benchmark.py skip" in cards["S07_artifacts"] and "crosscheck" in cards["S17_assemble"]
           and "--section manuscript" in cards["S19_human_review"]
           and "benchmark.py search" in skill and "--section manuscript" in skill
           and len(skill) <= 9000 and "## 1.25.0" in readme and "`1.25.0`" in readme
           and max(len(c) for c in cards.values()) <= registry.CARD_MAX_CHARS,
           str({k: len(v) for k, v in cards.items() if len(v) > 3900}) + f" skill={len(skill)}")


GROUPS = [("bench", run_bench), ("s22", run_s22), ("changed", run_changed), ("cross", run_cross),
          ("release", run_release)]
