"""Short-lived reuse of pure local checks with explicit content-hashed dependencies.

`wf check` followed by `wf advance` used to run every gate twice within a minute, including
the heavy local ones (DOCX audit, number provenance). A receipt written by `wf check` lets the
immediately following `wf advance` reuse a PASS - but only for checks on the whitelist below,
only within TTL_SECONDS, and only when the identity is byte-for-byte the same:

    stage + resolved gate spec (after the journal-variant path rewrite)
    + SHA-256 of every declared input file (plus every path the spec names)
    + SHA-256 of every engine source file (tools/, pipeline/, reference/)
    + pipeline targets + the paper's .wf/config.toml + recorded decisions
    + the paper's .wf/overrides.toml and this stage's override fingerprint

Anything not on the whitelist always executes: live PubMed, data/reference integrity,
approvals, decisions, freezes, reproducibility, package/baseline checks and every unknown
check. A failure is never cached. This is an execution optimisation, not a trust boundary
against a hostile local user. Receipts live in the paper's `.wf/`, never in the engine.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict
from pathlib import Path

from . import paths, scifreeze
from .packagefreeze import _safe_path, _sha256

REL = "check_receipts.json"
TTL_SECONDS = 120

# Inputs every identity carries: whether a journal variant exists changes which copy a gate
# reads, and the freeze record changes what "authoritative" means.
_COMMON = ("07_manuscript/scientific_freeze.json", "08_submission/manuscript/full_manuscript.md",
           "08_submission/manuscript/variant.json")

# Pure, local, deterministic checks and the files they read (beyond the paths named in spec).
INPUTS: dict[str, tuple[str, ...]] = {
    "md_sections": (),
    "md_wordcount": (),
    "no_ai_boilerplate": (),
    "supplementary_methods_clean": ("07_manuscript/supplementary_methods.md",
                                    "08_submission/manuscript/supplementary_methods.md"),
    "numbers_have_provenance": ("03_analysis/results/*", "04_tables/**/*.xlsx"),
    "manuscript_structure": ("01_protocol/artifact_plan.json", "07_manuscript/title.md",
                             "07_manuscript/full_manuscript.md", "05_figures/legends.md",
                             "04_tables/table_captions.md"),
    "docx_bundle_ready": ("08_submission/bundle/**/*", "08_submission/docx_style.json",
                          "08_submission/target_journal.json",
                          "08_submission/submission_requirements.json",
                          "08_submission/manuscript/**/*", "07_manuscript/supplementary_methods.md",
                          "01_protocol/artifact_plan.json"),
}


def _engine_hashes() -> dict[str, str]:
    root = paths.repo_root()
    out: dict[str, str] = {}
    for folder in ("tools", "pipeline", "reference"):
        base = root / folder
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            if (p.is_file() and p.suffix.lower() in {".py", ".r", ".toml", ".md", ".json"}
                    and "__pycache__" not in p.parts):
                out[p.relative_to(root).as_posix()] = _sha256(p)
    return out


class Receipts:
    def __init__(self, project: Path, pipeline, state):
        self.project, self.pipeline, self.state = project, pipeline, state
        self.path = state.dir / REL
        try:
            self.old = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(self.old, dict):
                self.old = {}
        except (OSError, ValueError):
            self.old = {}
        self.new: dict = {}
        self.reused = 0
        self._engine: dict | None = None
        overrides = state.dir / "overrides.toml"
        self.overrides = _sha256(overrides) if overrides.is_file() else ""

    @property
    def engine(self) -> dict:
        # Once per invocation; any implementation change invalidates every old receipt.
        if self._engine is None:
            self._engine = _engine_hashes()
        return self._engine

    def identity(self, stage, spec: dict) -> str | None:
        name = spec.get("check")
        if name not in INPUTS:
            return None
        patterns = list(_COMMON) + list(INPUTS[name])
        # Every path the spec names, not only the default locations.
        for key, value in spec.items():
            if isinstance(value, str) and (key == "path" or key.endswith("_path")
                                           or key in {"manifest", "style", "title_page",
                                                      "manuscript"}):
                patterns.append(value)
            elif key == "paths" and isinstance(value, list):
                patterns.extend(v for v in value if isinstance(v, str))
        if name == "docx_bundle_ready":
            manifest = self.project / "08_submission/bundle/manifest.json"
            if manifest.is_file():
                try:
                    items = json.loads(manifest.read_text(encoding="utf-8")).get("items", [])
                except (OSError, ValueError):
                    return None
                patterns.extend(str(row.get("file", "")) for row in items if row.get("file"))
        files: dict[str, dict] = {}
        for pattern in patterns:
            try:
                _safe_path(self.project, pattern)  # reject traversal before globbing
            except ValueError:
                return None
            found = [p for p in self.project.glob(pattern) if p.is_file()]
            files[pattern] = {p.relative_to(self.project).as_posix(): _sha256(p)
                              for p in sorted(found)}
        payload = {
            "stage": stage.id, "spec": spec, "files": files, "engine": self.engine,
            "targets": getattr(self.pipeline, "targets", {}), "config": self.state.config(),
            "decisions": self.state.data.get("decisions", {}),
            "overrides": self.overrides,
            "override_fingerprint": getattr(stage, "override_fingerprint", "") or "",
            "variant": scifreeze.variant_exists(self.project),
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()

    def get(self, identity: str | None):
        from .checks import Result
        if not identity:
            return None
        row = self.old.get(identity, {})
        try:
            if not 0 <= time.time() - float(row.get("at", 0)) < TTL_SECONDS:
                return None
            result = Result(**row["result"])
            if not result.ok:
                return None
        except (KeyError, TypeError, ValueError):
            return None
        self.new[identity] = row  # a hit never extends the freshness window
        self.reused += 1
        return result

    def put(self, identity: str | None, result) -> None:
        if identity and result.ok:
            self.new[identity] = {"at": time.time(), "result": asdict(result)}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.new, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(self.path)
