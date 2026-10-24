"""Loads pipeline.toml (the SSOT) plus per-project config overrides.

Stdlib only: tomllib requires Python >= 3.11.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import overrides, paths


@dataclass
class Stage:
    id: str
    title: str
    card: str
    outputs: list[str] = field(default_factory=list)
    gate: list[dict] = field(default_factory=list)
    needs_user: bool = False
    loopable: bool = False
    index: int = 0
    # Set by a paper-local override in .wf/overrides.toml, never by the master pipeline.
    skipped: bool = False
    skip_reason: str = ""
    override_fingerprint: str = ""

    def card_path(self) -> Path:
        return paths.pipeline_dir() / self.card


@dataclass
class Pipeline:
    meta: dict
    layout: dict
    policy: dict
    targets: dict
    freeform: list[str]
    stages: list[Stage]
    raw: dict
    # Human-readable summary of what this paper's overrides.toml changed. Printed by `wf status`
    # on every call, so a customised workflow can never look like the standard one.
    override_notes: list[str] = field(default_factory=list)

    # ---- lookups -------------------------------------------------------
    def stage(self, sid: str) -> Stage:
        for s in self.stages:
            if s.id == sid:
                return s
        raise KeyError(f"unknown stage: {sid}")

    def resolve(self, token: str) -> Stage:
        """Accept exact id, index (1-based), or unique prefix/substring."""
        token = (token or "").strip()
        if not token:
            raise KeyError("empty stage token")
        for s in self.stages:
            if s.id == token:
                return s
        if token.isdigit():
            i = int(token)
            if 1 <= i <= len(self.stages):
                return self.stages[i - 1]
        low = token.lower()
        hits = [s for s in self.stages if s.id.lower().startswith(low)]
        if len(hits) == 1:
            return hits[0]
        hits = [s for s in self.stages if low in s.id.lower()]
        if len(hits) == 1:
            return hits[0]
        raise KeyError(f"stage token '{token}' matched {len(hits)} stages")

    def next_of(self, sid: str) -> Stage | None:
        """Immediate physical successor in the master order (including skipped stages)."""
        s = self.stage(sid)
        if s.index + 1 < len(self.stages):
            return self.stages[s.index + 1]
        return None

    def transition_after(self, sid: str) -> tuple[Stage | None, list[Stage]]:
        """Next runnable stage plus every paper-local skip crossed to reach it."""
        skipped: list[Stage] = []
        for stage in self.stages[self.stage(sid).index + 1:]:
            if stage.skipped:
                skipped.append(stage)
                continue
            return stage, skipped
        return None, skipped

    def stages_after(self, sid: str) -> list[Stage]:
        return self.stages[self.stage(sid).index + 1 :]

    def first(self) -> Stage:
        return self.stages[0]

    def target(self, key: str, default=None):
        return self.targets.get(key, default)

    def all_declared_outputs(self) -> set[str]:
        out: set[str] = set()
        for s in self.stages:
            out.update(s.outputs)
        return out


DETAILS_DIR = "reference/stage_details"
CARD_MAX_CHARS = 4000  # 1.12.0 (D1): hard limit; target 3000. Detail lives in DETAILS_DIR.


def card_details_path(card: str | Path) -> Path:
    """reference/stage_details/<card name>: the long form a slim card points to."""
    name = Path(str(card)).name
    if not name.endswith(".md"):
        name += ".md"
    return paths.repo_root() / DETAILS_DIR / name


def card_full_text(card: str | Path) -> str:
    """A stage card plus its details file (what the stage documents in full)."""
    name = Path(str(card)).name
    if not name.endswith(".md"):
        name += ".md"
    text = (paths.pipeline_dir() / "stages" / name).read_text(encoding="utf-8")
    details = card_details_path(name)
    return text + ("\n" + details.read_text(encoding="utf-8") if details.is_file() else "")


def effective_targets(project: Path | None) -> dict:
    """[targets] of pipeline.toml overlaid by [targets] of <paper>/.wf/config.toml."""
    out = dict(tomllib.loads(paths.pipeline_file().read_text(encoding="utf-8")).get("targets", {}))
    if project is not None:
        cfg = Path(project) / ".wf" / "config.toml"
        if cfg.is_file():
            try:
                out.update(tomllib.loads(cfg.read_text(encoding="utf-8")).get("targets", {}))
            except tomllib.TOMLDecodeError:
                pass
    return out


def load(config_overrides: dict | None = None,
         paper_overrides: dict | None = None) -> Pipeline:
    pf = paths.pipeline_file()
    if not pf.exists():
        raise SystemExit(f"pipeline definition missing: {pf}")
    data = tomllib.loads(pf.read_text(encoding="utf-8"))

    stages: list[Stage] = []
    for i, raw in enumerate(data.get("stage", [])):
        stages.append(
            Stage(
                id=raw["id"],
                title=raw.get("title", raw["id"]),
                card=raw.get("card", f"stages/{raw['id']}.md"),
                outputs=list(raw.get("outputs", [])),
                gate=list(raw.get("gate", [])),
                needs_user=bool(raw.get("needs_user", False)),
                loopable=bool(raw.get("loopable", False)),
                index=i,
            )
        )
    if not stages:
        raise SystemExit("pipeline.toml declares no stages")

    targets = dict(data.get("targets", {}))
    if config_overrides:
        targets.update(config_overrides.get("targets", {}))

    pipeline = Pipeline(
        meta=data.get("meta", {}),
        layout=data.get("layout", {}),
        policy=data.get("policy", {}),
        targets=targets,
        freeform=list(data.get("freeform", {}).get("globs", [])),
        stages=stages,
        raw=data,
    )

    # Paper-local shape changes are applied last, and only after validation, so an illegal
    # override cannot take effect even for the duration of one command. The master file on disk
    # is never modified - two papers can run different shapes from the same engine.
    if paper_overrides:
        problems = overrides.validate(paper_overrides, stages)
        if problems:
            raise SystemExit(
                "refusing to apply .wf/overrides.toml:\n  " + "\n  ".join(problems))
        pipeline.override_notes = overrides.apply(pipeline, paper_overrides)
    return pipeline
