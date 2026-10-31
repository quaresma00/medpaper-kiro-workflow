"""On-disk run state.

This file is the memory that survives context compaction. The agent never has to
remember where it is; it reads it back from here.
"""
from __future__ import annotations

import json
import tomllib
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = 1


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def version_tuple(value: str) -> tuple[int, ...]:
    """'1.8.1-wip' -> (1, 8, 1); unparseable -> (0,)."""
    out = []
    for part in str(value).split("-")[0].split(".")[:3]:
        if not part.isdigit():
            break
        out.append(int(part))
    return tuple(out) or (0,)


# 1.14.0 (E): decisions that judge the results; each stores a hash of what it judged.
SCIENTIFIC_DECISIONS = {
    "analysis_converged": ("results", "03_analysis/analysis_manifest.json"),
    "go_nogo_2": ("results", "01_protocol/protocol_final.md", "03_analysis/analysis_manifest.json"),
}


def scientific_inputs_sha256(project, name: str) -> str:
    """Hash of the results set (every 03_analysis/results/*.json without its environment
    receipt), the protocol and the analysis manifest a scientific decision judged."""
    import hashlib
    from pathlib import Path as _P
    project = _P(project)
    h = hashlib.sha256()
    for part in SCIENTIFIC_DECISIONS.get(name, ()):
        if part == "results":
            for p in sorted((project / "03_analysis/results").glob("*.json")):
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    data = None
                if isinstance(data, dict):
                    data = {k: v for k, v in data.items() if k != "environment"}
                h.update(p.name.encode() + b"\0" + json.dumps(data, sort_keys=True).encode())
        else:
            p = project / part
            blob = p.read_bytes().replace(b"\r\n", b"\n") if p.is_file() else b"<absent>"
            h.update(part.encode() + b"\0" + blob)
    return h.hexdigest()


class State:
    def __init__(self, root: Path, state_dir: str = ".wf"):
        self.project = root
        self.dir = root / state_dir
        self.file = self.dir / "state.json"
        self.handoff_file = self.dir / "handoff.md"
        self.config_file = self.dir / "config.toml"
        self.data: dict = {}

    # ---- lifecycle -----------------------------------------------------
    def exists(self) -> bool:
        return self.file.exists()

    def load(self) -> "State":
        if not self.exists():
            raise SystemExit(
                "no run state found. Initialise first:  .venv/Scripts/python.exe tools/wf.py init"
            )
        self.data = json.loads(self.file.read_text(encoding="utf-8"))
        return self

    def create(self, pipeline_name: str, pipeline_version: str, first_stage: str) -> "State":
        self.dir.mkdir(parents=True, exist_ok=True)
        self.data = {
            "schema": SCHEMA,
            "pipeline": pipeline_name,
            "pipeline_version": pipeline_version,
            "pipeline_origin_version": pipeline_version,
            # 1.9.0: completed stages keep the gate set of this version until `wf migrate`.
            "engine_pin": pipeline_version,
            "created_at": _now(),
            "current": first_stage,
            "stages": {first_stage: {"status": "active", "started_at": _now(), "loops": 0}},
            "decisions": {},
            "handoff": [],
            "events": [{"at": _now(), "kind": "init", "detail": first_stage}],
        }
        self.save()
        if not self.handoff_file.exists():
            self.handoff_file.write_text(
                "# Handoff log\n\n"
                "Append-only. One entry per stage close. Written by `wf note` / `wf advance`.\n"
                "Read this first when resuming after a context reset.\n",
                encoding="utf-8",
            )
        return self

    def save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.file.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.file)

    def migrate_pipeline(self, pipeline_version: str, valid_stage_ids: list[str],
                         stage_aliases: dict[str, str] | None = None) -> bool:
        """Migrate engine metadata and renamed active stages without touching artifacts."""
        old_version = str(self.data.get("pipeline_version", "unknown"))
        current = str(self.data.get("current", ""))
        aliases = stage_aliases or {}
        changed = old_version != pipeline_version
        if current not in valid_stage_ids:
            replacement = aliases.get(current)
            if not replacement or replacement not in valid_stage_ids:
                raise SystemExit(
                    f"run state uses stage '{current}', which pipeline {pipeline_version} cannot migrate"
                )
            self.stage_info(current)["status"] = "superseded"
            self.stage_info(replacement)["status"] = "active"
            self.stage_info(replacement).setdefault("started_at", _now())
            self.data["current"] = replacement
            changed = True
        if changed:
            self.data.setdefault("pipeline_origin_version", old_version)
            # 1.9.0: the version the paper ran under stays its pin; new gates reach completed
            # stages only through an explicit `wf migrate`.
            self.data.setdefault("engine_pin", old_version)
            self.data.setdefault("pipeline_migrations", []).append({
                "at": _now(), "from": old_version, "to": pipeline_version,
                "current_before": current, "current_after": self.data["current"],
            })
            self.data["pipeline_version"] = pipeline_version
            # 1.12.0 (C2): pipeline_version records the engine that last opened this state; the
            # paper's gate set moves only with `wf migrate --yes` (engine_pin). The event says
            # so instead of implying the paper moved.
            self.event("pipeline_migration",
                       f"engine {old_version} -> {pipeline_version} opened this paper; paper stays "
                       f"pinned to {self.data.get('engine_pin')} (`wf migrate --yes` adopts the new "
                       f"gate set); current {current} -> {self.data['current']}")
            self._note_legacy_revision()
            self._note_on_demand_checklist(old_version)
            self._note_v180(old_version)
            self._note_v181(old_version)
            self._note_v190(old_version, pipeline_version)
            self._note_v1100(old_version, pipeline_version)
            self._note_v1110(old_version, pipeline_version)
            self._note_v1120(old_version, pipeline_version)
            self._note_v1130(old_version, pipeline_version)
            self._note_v1140(old_version, pipeline_version)
            self._note_v1141(old_version, pipeline_version)
            self.save()
        return changed

    def _note_v1141(self, old_version: str, new_version: str) -> None:
        """1.14.1: patch release. Event only; no file or stage is touched."""
        if (version_tuple(old_version) >= (1, 14, 1) or version_tuple(new_version) < (1, 14, 1)
                or self.data.get("v1141_migration_noted")):
            return
        self.data["v1141_migration_noted"] = True
        self.event("requirements_changed",
                   "1.14.1: the opened folder is the paper (an older attempt in a subfolder is "
                   "left isolated; a fresh restart archives in place after confirmation); one "
                   "merged guard hook on writes and folder searches only (adapters refresh "
                   "automatically); Word files carry no keep markers unless the journal sets "
                   "keep_table_footnotes; meaning-report lines parsed one by one; the latest "
                   "receipt per file across all closed rounds, builder outputs recorded into the "
                   "open round; supplementary page reads affiliation or address; versions, URLs, "
                   "DOIs and identifiers are not numbers to trace; registration-status sentences "
                   "are allowed; polish_allowlist also from 08_submission/manuscript/; "
                   "upload:false items are evidence; per-sheet table tiles; previews of every "
                   "page. Stricter checks (zero keep markers without the switch, PDF /Lang, "
                   "document properties without local paths, receipts of every closed round) "
                   "apply to this paper only after `wf migrate --yes`. Paper files were not "
                   "modified.")

    def _note_v1140(self, old_version: str, new_version: str) -> None:
        """1.14.0: an external review of 1.13.0. Event only; no file or stage is touched."""
        if (version_tuple(old_version) >= (1, 14, 0) or version_tuple(new_version) < (1, 14, 0)
                or self.data.get("v1140_migration_noted")):
            return
        self.data["v1140_migration_noted"] = True
        self.event("requirements_changed",
                   "1.14.0: post-freeze wording changes are classified SAFE / MEANING_CHECK / "
                   "SCIENCE (a meaning check by the reviewer or the author); the writer bundle "
                   "carries every result (gaps gate); a number cited from a prior study must "
                   "appear in that source; reproduction copies within a size limit and never "
                   "links or alters data; analysis stop rule (additional analyses name the "
                   "decision they could change); stale GO decisions re-judged; gate cache "
                   "follows every file a check reads; only a release-tagged engine serves "
                   "papers; reviewers get a factual pre-specified vs post hoc record; one look "
                   "at all tables and figures before Results; Word keeps each table footnote "
                   "with its table. New gates are since=1.14.0: completed stages keep the "
                   "pinned gate set. Paper files were not modified.")

    def _note_v1130(self, old_version: str, new_version: str) -> None:
        """1.13.0: paper isolation and engine protection. Event only; no file or stage is touched."""
        if (version_tuple(old_version) >= (1, 13, 0) or version_tuple(new_version) < (1, 13, 0)
                or self.data.get("v1130_migration_noted")):
            return
        self.data["v1130_migration_noted"] = True
        self.event("requirements_changed",
                   "1.13.0: the paper is the working folder (cwd/MEDPAPER_PROJECT, no wf use); "
                   "engine integrity guard (a modified shared engine refuses paper commands; "
                   "fixes via paper overrides or `wf engine-fork`); paper guard hook "
                   "(install_adapters.py --paper); datasets registered in place (`wf data add`) "
                   "and never copied (data_not_copied); reproduction in a paper-local sandbox, "
                   "once per round, scoped re-runs, logs in .wf/logs/; traceable post-freeze "
                   "edits never rewind; multi-person checks only for manual coding; no protocol "
                   "deviations in the paper; per-section polishing; Word without keep markers. "
                   "New gates are since=1.13.0: completed stages keep the pinned gate set. Paper "
                   "files were not modified.")

    def _note_v1120(self, old_version: str, new_version: str) -> None:
        """1.12.0: a lighter engine. Event only; no file or stage is touched."""
        if (version_tuple(old_version) >= (1, 12, 0) or version_tuple(new_version) < (1, 12, 0)
                or self.data.get("v1120_migration_noted")):
            return
        self.data["v1120_migration_noted"] = True
        self.event("requirements_changed",
                   "1.12.0: fewer false positives (re-checks of finished stages, render/QC race, "
                   "locked workbooks, stacked bars, bib export rule, incremental review "
                   "coverage, WARN checklist rows); merged gate lines (pending outputs, one "
                   "polish gate, keep-with-next inside docx_bundle_ready); no section word "
                   "minimums; deferred visual looks need no DEFER decision (still owed at S23); "
                   "short stage cards with reference/stage_details/; `wf handoff`; reviewer "
                   "report written to the review bundle; medpaper-clinical-writer + "
                   "tools/manuscript/writer_bundle.py; first-reader display check (warn S10/S11, "
                   "block S12); display items need a non-redundancy line; Word line numbers "
                   "from target_journal.json line_numbers. New gates are since=1.12.0: "
                   "completed stages keep the pinned gate set. Paper files were not modified.")

    def _note_v1110(self, old_version: str, new_version: str) -> None:
        """1.11.0: the clinical presentation layer. Event only; no file or stage is touched."""
        if (version_tuple(old_version) >= (1, 11, 0) or version_tuple(new_version) < (1, 11, 0)
                or self.data.get("v1110_migration_noted")):
            return
        self.data["v1110_migration_noted"] = True
        self.event("requirements_changed",
                   "1.11.0: display dictionary (S07) and clinical labels in displays/prose; "
                   "engineering-language lint (warn in Methods, block elsewhere; paper allowlist "
                   ".wf/language_allowlist.json); each table/figure defines its abbreviations plus "
                   "a central list (a pinned paper keeps its legacy placement); flow diagrams are "
                   "schematics with analysis units; Word keeps caption/table/footnote and "
                   "legend/figure together; every numbered review finding closed (close --report); "
                   "provisional journal parameters (01_protocol/journal_profile.json) from S07; "
                   "print-size fonts >= 8 pt; no raw statuses in displays; concise footnotes; "
                   "`rework.py preview` and an explicit confirmation before any S19 rewind. New "
                   "gates are since=1.11.0: completed stages keep the pinned gate set. Paper files "
                   "were not modified.")

    def _note_v1100(self, old_version: str, new_version: str) -> None:
        """1.10.0: S09 Results now follows S10/S11. A paper whose active stage is S09 while the
        tables/figures are still pending moves to S10 (S09 waits, its draft is kept)."""
        if (version_tuple(old_version) >= (1, 10, 0) or version_tuple(new_version) < (1, 10, 0)
                or self.data.get("v1100_migration_noted")):
            return
        self.data["v1100_migration_noted"] = True
        moved = ""
        if self.data.get("current") == "S09_results" and not self.is_done("S10_tables"):
            self.stage_info("S09_results")["status"] = "pending"
            info = self.stage_info("S10_tables")
            info["status"] = "active"
            info.setdefault("started_at", _now())
            self.data["current"] = "S10_tables"
            moved = " Active S09 moved to S10 (results.md kept; finished from final displays)."
        self.event("requirements_changed",
                   "1.10.0: order S10 tables -> S11 figures -> S09 Results -> S12 cross-check; "
                   "Methods citations checked live at S08; variable crosswalk (S04) and 10-case "
                   "raw spot check (S06); structured study_design/data_source (S01/S03) drive "
                   "declarations; statistical reporting plan in the protocol; length/reference "
                   "counts are warnings until S20; review findings on numbers/grouping/conclusion "
                   "strength need a change or the author; approval is the sentence '我确认这一版'. "
                   "New gates are since=1.10.0: completed stages keep the pinned gate set." + moved
                   + " Paper files were not modified.")

    @property
    def engine_pin(self) -> str:
        return str(self.data.get("engine_pin") or self.data.get("pipeline_version") or "0")

    def pin_excludes(self, sid: str, since: str | None) -> bool:
        """A gate added after the paper's pinned engine does not re-judge a completed stage."""
        if not since or self.status_of(sid) not in ("done", "skipped"):
            return False
        return version_tuple(self.engine_pin) < version_tuple(since)

    def migrate_pin(self, engine_version: str) -> list[str]:
        """`wf migrate`: adopt the engine's full gate set; returns the recorded migration notes."""
        old = self.engine_pin
        notes = [f"{e.get('at', '')} {e.get('kind')}: {e.get('detail', '')}"
                 for e in self.data.get("events", [])
                 if e.get("kind") in ("requirements_added", "requirements_changed",
                                      "requirements_relaxed")]
        self.data["engine_pin"] = engine_version
        # 1.12.0 (C2): an explicit migration also brings the recorded engine version along, so
        # pin and pipeline_version agree after `wf migrate --yes`.
        self.data["pipeline_version"] = engine_version
        self.data.setdefault("pin_migrations", []).append(
            {"at": _now(), "from": old, "to": engine_version})
        self.event("engine_pin_migrated", f"{old} -> {engine_version}")
        self.save()
        return notes

    def _note_v190(self, old_version: str, new_version: str = "1.9.0") -> None:
        """1.9.0: record what changes for an in-flight paper; never rewrite its files."""
        if (version_tuple(old_version) >= (1, 9, 0) or version_tuple(new_version) < (1, 9, 0)
                or self.data.get("v190_migration_noted")):
            return
        self.data["v190_migration_noted"] = True
        self.event("requirements_changed",
                   "1.9.0: post-freeze revision items are classified by content (unchanged facts "
                   "= presentation delta, no S19 return or re-confirmation); kind 'journal' is now "
                   "'journal-switch' (+ 'journal-format'); package confirmation covers uploads by "
                   "visible content only; completed stages keep this paper's pinned gate set "
                   "until `wf migrate`; S25 can close with an author-edited upload copy "
                   "(tools/final_copy.py). Paper files were not modified.")

    def _note_v180(self, old_version: str) -> None:
        """1.8.0: record what an in-flight paper must add; never rewrite its files."""
        try:
            old = tuple(int(x) for x in old_version.split(".")[:3])
        except ValueError:
            old = (0,)
        if old >= (1, 8, 0) or self.data.get("v180_migration_noted"):
            return
        self.data["v180_migration_noted"] = True
        self.event("requirements_added",
                   "1.8.0: target_journal.json needs typed 'limits' (journal_limits_met no longer "
                   "parses guideline prose); rebuild DOCX for page numbers/TAB references/main-only "
                   "legends; regenerate SUBMISSION_CHECKLIST.md with tools/manuscript/submission_qc.py "
                   "write; supplementary legends move to the supplementary file; papers before S03/S06 "
                   "add 'Design precedent' lines. Paper files were not modified.")

    def _note_v181(self, old_version: str) -> None:
        """1.8.1: review rounds replace the S19 review ZIP; Word tables get three-line borders."""
        try:
            old = tuple(int(x) for x in old_version.split(".")[:3])
        except ValueError:
            old = (0,)
        if old >= (1, 8, 1) or self.data.get("v181_migration_noted"):
            return
        self.data["v181_migration_noted"] = True
        self.event("requirements_changed",
                   "1.8.1: S19/S24 review is a subagent round loop (tools/review_round.py); no "
                   "review ZIP is built. A paper already holding a review ZIP or an S24 OK keeps "
                   "passing on it; the next review starts a round. Rebuild a manuscript DOCX with "
                   "word_tables for three-line tables on their own pages. Paper files were not "
                   "modified.")

    def _note_on_demand_checklist(self, old_version: str) -> None:
        """1.7.3: no pre-emptive registration or reporting checklist. Nothing to convert - the
        checklist gate now passes as not required unless the journal (or a meta-analysis)
        demands one, and the protocol no longer needs a Reporting guideline section."""
        try:
            old = tuple(int(x) for x in old_version.split(".")[:3])
        except ValueError:
            old = (0,)
        if old >= (1, 7, 3) or self.data.get("on_demand_checklist_noted"):
            return
        self.data["on_demand_checklist_noted"] = True
        self.event("requirements_relaxed",
                   "1.7.3: registration not required (meta-analysis: PROSPERO recommended); "
                   "reporting checklist only when target_journal.json journal_requires_checklist "
                   "is set or PRISMA for a meta-analysis")

    def _note_legacy_revision(self) -> None:
        """1.7.0 rounds are scoped (schema 2). A round opened earlier keeps its rewind flow.

        Its stages were already reset when it opened, so it finishes through the normal gates
        and closes as before; nothing is converted. Recorded once so the history explains it.
        """
        rid = self.data.get("active_revision_round")
        if not rid or self.data.get("legacy_revision_round") == rid:
            return
        try:
            payload = json.loads((self.dir / "revisions" / f"{rid}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if payload.get("schema_version") == 1:
            self.data["legacy_revision_round"] = rid
            self.event("revision_legacy_round",
                       f"{rid} (schema 1) finishes through its stage gates; new rounds are scoped")

    # ---- config --------------------------------------------------------
    def config(self) -> dict:
        if not self.config_file.exists():
            return {}
        try:
            return tomllib.loads(self.config_file.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            raise SystemExit(f"malformed {self.config_file}: {exc}")

    def set_config(self, key: str, value: str) -> None:
        cfg = self.config()
        tgt = cfg.setdefault("targets", {})
        try:
            tgt[key] = int(value)
        except ValueError:
            try:
                tgt[key] = float(value)
            except ValueError:
                tgt[key] = value
        lines = ["# Per-project overrides of [targets] in pipeline/pipeline.toml", "[targets]"]
        for k, v in sorted(tgt.items()):
            lines.append(f'{k} = {json.dumps(v)}' if not isinstance(v, str) else f'{k} = "{v}"')
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        self.config_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # ---- accessors -----------------------------------------------------
    @property
    def current(self) -> str:
        return self.data["current"]

    def stage_info(self, sid: str) -> dict:
        return self.data.setdefault("stages", {}).setdefault(sid, {"status": "pending", "loops": 0})

    def status_of(self, sid: str) -> str:
        return self.stage_info(sid).get("status", "pending")

    def is_done(self, sid: str) -> bool:
        # A paper-local skip is a completed transition for dependency purposes: the stage is
        # inapplicable to this paper and the state records why. It is displayed as "-", not "x".
        return self.status_of(sid) in {"done", "skipped"}

    def was_completed(self, sid: str) -> bool:
        """True if the stage was completed or explicitly skipped for this paper.

        `wf loop` deliberately leaves downstream artifacts in place, so a checker that asks
        "does a future stage's output exist?" must distinguish an artifact produced by a stage
        that ran ahead of itself from one produced by a stage that genuinely finished and was
        then rewound past. A recorded paper-local skip is also terminal for dependency order.
        """
        info = self.stage_info(sid)
        return bool(info.get("completed_at") or info.get("skipped_at"))

    def decision(self, name: str) -> dict | None:
        return self.data.get("decisions", {}).get(name)

    # ---- mutations -----------------------------------------------------
    def event(self, kind: str, detail: str) -> None:
        self.data.setdefault("events", []).append({"at": _now(), "kind": kind, "detail": detail})

    def record_decision(self, name: str, value: str, why: str) -> None:
        self.data.setdefault("decisions", {})[name] = {
            "value": value,
            "rationale": why,
            "at": _now(),
            "stage": self.current,
        }
        if name in SCIENTIFIC_DECISIONS:
            # 1.14.0 (E): bound to the scientific inputs it judged; stale when they change.
            self.data["decisions"][name]["inputs_sha256"] = scientific_inputs_sha256(
                self.project, name)
        self.event("decision", f"{name}={value}")
        self.save()

    def add_note(self, note: str, stage: str | None = None) -> None:
        stage = stage or self.current
        entry = {"stage": stage, "at": _now(), "note": note}
        self.data.setdefault("handoff", []).append(entry)
        self.save()
        with self.handoff_file.open("a", encoding="utf-8") as fh:
            fh.write(f"\n## {stage} - {entry['at']}\n\n{note}\n")

    def notes_for(self, stage: str) -> list[dict]:
        return [h for h in self.data.get("handoff", []) if h.get("stage") == stage]

    def complete(self, sid: str, next_sid: str | None,
                 skipped: list[tuple[str, str, str]] | None = None,
                 override_fingerprint: str = "") -> None:
        """Complete `sid`, record any overridden stages crossed, then activate `next_sid`."""
        info = self.stage_info(sid)
        info["status"] = "done"
        info["completed_at"] = _now()
        if override_fingerprint:
            info["paper_override_fingerprint"] = override_fingerprint
        else:
            info.pop("paper_override_fingerprint", None)
        skipped = skipped or []
        for skipped_sid, reason, fingerprint in skipped:
            rec = self.stage_info(skipped_sid)
            rec["status"] = "skipped"
            rec["skipped_at"] = _now()
            rec["skip_reason"] = reason
            rec["paper_override_fingerprint"] = fingerprint
            self.event("paper_override_skip", f"{skipped_sid}: {reason}")
        if next_sid:
            nxt = self.stage_info(next_sid)
            if nxt.get("completed_at"):
                # 1.12.0 (C3): re-entering a stage that finished before is a revisit.
                nxt["loops"] = nxt.get("loops", 0) + 1
            nxt["status"] = "active"
            nxt.setdefault("started_at", _now())
            self.data["current"] = next_sid
        self.event("advance", f"{sid} -> {next_sid or 'END'}"
                   + (f" (skipped {', '.join(s for s, _, _ in skipped)})" if skipped else ""))
        self.save()

    def skip_current(self, sid: str, reason: str, next_sid: str | None,
                     skipped_after: list[tuple[str, str, str]] | None = None,
                     override_fingerprint: str = "") -> None:
        """Apply a paper-local skip to the active stage and any consecutive skipped stages."""
        chain = [(sid, reason, override_fingerprint), *(skipped_after or [])]
        for skipped_sid, why, fingerprint in chain:
            rec = self.stage_info(skipped_sid)
            rec["status"] = "skipped"
            rec["skipped_at"] = _now()
            rec["skip_reason"] = why
            rec["paper_override_fingerprint"] = fingerprint
            self.event("paper_override_skip", f"{skipped_sid}: {why}")
        if next_sid:
            nxt = self.stage_info(next_sid)
            nxt["status"] = "active"
            nxt.setdefault("started_at", _now())
            self.data["current"] = next_sid
        else:
            self.data["current"] = sid
        self.event("advance", f"{sid} skipped -> {next_sid or 'END'}"
                   + (f" (also skipped {', '.join(s for s, _, _ in chain[1:])})"
                      if len(chain) > 1 else ""))
        self.save()

    def rewind(self, sid: str, why: str) -> None:
        """Go back to an earlier stage; later stages return to pending."""
        order = list(self.data.get("stages", {}).keys())
        self.stage_info(sid)["status"] = "active"
        self.stage_info(sid)["loops"] = self.stage_info(sid).get("loops", 0) + 1
        self.data["current"] = sid
        self.event("loop", f"back to {sid}: {why}")
        _ = order
        self.save()

    def reset_forward(self, stage_ids: list[str]) -> None:
        for sid in stage_ids:
            if sid in self.data.get("stages", {}):
                self.data["stages"][sid]["status"] = "pending"
        self.save()

    def clear_decisions_for(self, stage_ids: list[str]) -> None:
        """Invalidate decisions made in stages that are about to be rerun."""
        affected = set(stage_ids)
        decisions = self.data.get("decisions", {})
        removed = [name for name, rec in decisions.items() if rec.get("stage") in affected]
        for name in removed:
            del decisions[name]
        if removed:
            self.event("decisions_invalidated", ", ".join(sorted(removed)))
        self.save()
