"""Declarative check library.

A gate entry in pipeline.toml looks like:

    [[stage.gate]]
    check = "md_wordcount"
    path  = "07_manuscript/introduction.md"
    min_key = "intro_words_min"

`check` selects a function registered here; every other key is passed through in
`ctx.spec`. Add a check by writing a function and decorating it -- no engine edit.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

REGISTRY: dict[str, Callable[["Ctx"], "Result"]] = {}


@dataclass
class Result:
    ok: bool
    check: str
    detail: str = ""
    hints: list[str] = field(default_factory=list)
    severity: str = "fail"  # "fail" | "warn"

    @property
    def blocking(self) -> bool:
        return (not self.ok) and self.severity == "fail"

    @property
    def label(self) -> str:
        if self.ok:
            return "PASS"
        return "FAIL" if self.severity == "fail" else "WARN"


@dataclass
class Ctx:
    pipeline: object          # registry.Pipeline
    state: object            # state.State
    project: Path
    stage: object            # registry.Stage
    spec: dict

    # ---- convenience ---------------------------------------------------
    def p(self, rel: str) -> Path:
        return self.project / rel

    def exists(self, rel: str) -> bool:
        p = self.p(rel)
        return p.exists() and (p.is_dir() or p.stat().st_size > 0)

    def read(self, rel: str) -> str:
        return self.p(rel).read_text(encoding="utf-8", errors="replace")

    # ---- frozen science vs journal variant -----------------------------
    def src(self, rel: str) -> str:
        """Whichever copy of a manuscript artifact is authoritative right now.

        Once the scientific record is frozen at S19 and a journal variant is opened, the files
        a journal legitimately alters live under 08_submission/manuscript/. Before that - and
        for any project that predates the freeze - this returns `rel` unchanged, so existing
        gate specs keep working without edits.
        """
        from .. import scifreeze
        return scifreeze.resolve(self.project, rel)

    def src_all(self, rels) -> list[str]:
        return [self.src(r) for r in rels]

    def psrc(self, rel: str) -> Path:
        return self.project / self.src(rel)

    def read_json(self, rel: str):
        return json.loads(self.read(rel))

    def glob(self, pattern: str) -> list[Path]:
        return sorted(x for x in self.project.glob(pattern) if x.is_file())

    def target(self, key: str, default=None):
        return self.pipeline.targets.get(key, default)

    def spec_bound(self, which: str):
        """Resolve `min`/`max` either literally or via `min_key`/`max_key` -> targets."""
        if which in self.spec:
            return self.spec[which]
        keyname = self.spec.get(f"{which}_key")
        if keyname:
            return self.target(keyname)
        return None


def check(name: str):
    def deco(fn):
        REGISTRY[name] = fn
        fn.check_name = name
        return fn

    return deco


def get(name: str):
    return REGISTRY.get(name)


def load_all() -> None:
    """Import every check module so the registry is populated."""
    from . import (artifacts, data, display, frozen, fsx, manuscript, numbers,  # noqa: F401
                   polish, refs, reporting, repro, revisions, statecheck, text, v1100)


def known() -> list[str]:
    load_all()
    return sorted(REGISTRY)
