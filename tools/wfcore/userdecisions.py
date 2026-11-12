"""1.22.0 (U1): persistent user decisions - recorded once, never asked again.

Real runs re-asked what the user had long decided: a named target journal got a shortlist at
S20, author information, spelling, the AI-use answer and the APC policy were asked again at
later stages. `.wf/user_decisions.json` now holds every such decision, dated, with the user's
words and the source:

    wf decisions show
    wf decisions set <key> <value> --words "<the user's words>"

It is seeded automatically from the paper's existing state (one event on the first 1.22.0
command), every card says to read it (and `wf handoff`) before asking the user anything, and
journal-independent keys survive a journal switch (journal-dependent keys are archived with
the old epoch).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

REL = ".wf/user_decisions.json"
KEYS = {  # key -> (Chinese label, journal-dependent)
    "target_journal": ("目标期刊", True),
    "authors": ("作者与单位信息", False),
    "author_info_placement": ("作者信息位置（题名页/正文）", False),
    "spelling": ("拼写规范", False),
    "ai_use": ("AI 使用答复", False),
    "apc_policy": ("版面费（APC）政策", False),
    "layout_preferences": ("版面偏好", False),
    "review_mode": ("审阅模式（standard/fast）", False),
    "portal_check": ("是否由代理读取投稿系统", True),
}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _json(path: Path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def load(project: Path) -> dict:
    data = _json(Path(project) / REL)
    if not isinstance(data, dict):
        data = {}
    data.setdefault("schema", 1)
    if not isinstance(data.get("decisions"), dict):
        data["decisions"] = {}
    return data


def _save(project: Path, data: dict) -> None:
    path = Path(project) / REL
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def get(project: Path, key: str) -> dict | None:
    rec = load(project)["decisions"].get(key)
    return rec if isinstance(rec, dict) else None


def user_named_journal(project: Path) -> bool:
    """The user named the target journal (decision with the user's words, current epoch)."""
    from . import journalepoch
    rec = get(project, "target_journal")
    if not rec or rec.get("source") not in ("user", "seed:user"):
        return False
    return int(rec.get("epoch") or 1) == journalepoch.number(project)


def put(project: Path, key: str, value, words: str, source: str = "user") -> dict:
    from . import journalepoch
    if key not in KEYS:
        raise ValueError(f"unknown decision key {key}; known: {', '.join(KEYS)}")
    words = str(words or "").strip()
    if source == "user" and len(words) < 2:
        raise ValueError("--words 写用户的原话")
    data = load(project)
    rec = {"value": value, "words": words, "at": _now(), "source": source,
           "journal_dependent": KEYS[key][1]}
    if KEYS[key][1]:
        rec["epoch"] = journalepoch.number(project)
    old = data["decisions"].get(key)
    if isinstance(old, dict) and old.get("value") != value:
        data.setdefault("history", []).append({"key": key, **old, "replaced_at": rec["at"]})
    data["decisions"][key] = rec
    _save(project, data)
    return rec


def seed(project: Path, state=None) -> list[str]:
    """Fill missing keys from what the paper already records; returns the keys seeded."""
    project = Path(project)
    data = load(project)
    dec = data["decisions"]
    done = []

    def add(key, value, words, source):
        if key in dec or value in (None, "", [], {}):
            return
        from . import journalepoch
        rec = {"value": value, "words": words, "at": _now(), "source": source,
               "journal_dependent": KEYS[key][1]}
        if KEYS[key][1]:
            rec["epoch"] = journalepoch.number(project)
        dec[key] = rec
        done.append(key)
    tj = _json(project / "08_submission/target_journal.json") or {}
    if isinstance(tj, dict) and tj.get("journal") and tj.get("chosen_by_user"):
        add("target_journal", tj["journal"], "target_journal.json chosen_by_user", "seed:user")
    idea = _json(project / "01_protocol/idea.json") or {}
    named = (idea.get("target_journal") or idea.get("journal")) if isinstance(idea, dict) else None
    if named:
        add("target_journal", named, "01_protocol/idea.json (the user's research idea)", "seed:user")
    ai = _json(project / "00_input/author_info.json") or {}
    if isinstance(ai, dict) and ai.get("authors"):
        add("authors", f"{len(ai['authors'])} author(s) in 00_input/author_info.json",
            "00_input/author_info.json", "seed:file")
    cfg = state.config().get("targets", {}) if state is not None else {}
    if cfg.get("spelling"):
        add("spelling", cfg["spelling"], ".wf/config.toml", "seed:config")
    if cfg.get("review_mode"):
        add("review_mode", cfg["review_mode"], ".wf/config.toml", "seed:config")
    try:
        from .declarations import ai_fact
        fact = ai_fact(project)
    except Exception:  # noqa: BLE001
        fact = None
    if fact:
        add("ai_use", "used: " + str(fact.get("tool")) if fact.get("used") else "not used",
            str(fact.get("author_words") or fact.get("statement") or "declarations_assessment.json"),
            "seed:declarations")
    if isinstance(tj, dict) and (tj.get("apc_policy") or tj.get("apc_user_policy")):
        add("apc_policy", tj.get("apc_policy") or tj.get("apc_user_policy"),
            "target_journal.json", "seed:file")
    if done:
        _save(project, data)
    return done


def carry_over_switch(project: Path, old_epoch: int) -> list[str]:
    """`wf journal switch`: journal-dependent keys move to history; the others stay."""
    data = load(project)
    moved = []
    for key, rec in list(data["decisions"].items()):
        if isinstance(rec, dict) and rec.get("journal_dependent"):
            data.setdefault("history", []).append({"key": key, **rec, "archived_epoch": old_epoch})
            del data["decisions"][key]
            moved.append(key)
    if moved or data["decisions"]:
        _save(project, data)
    return moved


def verify(project: Path, key: str, text: str, sources: list[str], fact: str) -> dict:
    """1.23.0 (S6): a declaration, dataset access mode or journal-specific statement the agent
    established from public sources (descriptor paper, data portal / licence page, journal
    policy page, comparable papers) - recorded with the URLs, never asked of the user."""
    import re
    key = str(key or "").strip()
    if not re.match(r"^[a-z][a-z0-9_.-]{1,60}$", key):
        raise ValueError("key: lower-case words, e.g. data_access_mimic or transplant_statement")
    urls = [s.strip() for s in sources or [] if s and s.strip()]
    if not urls or not all(re.match(r"^https?://", u) for u in urls):
        raise ValueError("--source: at least one public http(s) URL")
    if len(str(text).strip()) < 10 or len(str(fact).strip()) < 10:
        raise ValueError("--text (the drafted statement) and --fact (what the source says) are "
                         "required")
    data = load(project)
    rec = {"text": text.strip(), "fact": fact.strip(), "sources": urls, "checked": _now(),
           "source": "self-verified"}
    old = data.setdefault("verified", {}).get(key)
    if old:
        data.setdefault("history", []).append({"key": key, **old, "replaced_at": rec["checked"]})
    data["verified"][key] = rec
    _save(project, data)
    return rec


def show_lines(project: Path) -> list[str]:
    data = load(project)
    out = ["用户既定决定（.wf/user_decisions.json；已记录的不再重复询问，除非事实变化）："]
    for key, rec in sorted((data.get("verified") or {}).items()):
        out.append(f"  - {key}（自行查证）= {str(rec.get('text'))[:80]}  [来源 "
                   + ", ".join(rec.get("sources", [])[:2]) + "]")
    if not data["decisions"]:
        out.append("  （暂无）")
    for key, rec in sorted(data["decisions"].items()):
        label = KEYS.get(key, (key, False))[0]
        out.append(f"  - {key}（{label}）= {rec.get('value')}  [{rec.get('at', '')[:10]}，来源 "
                   f"{rec.get('source')}" + (f"，原话：“{str(rec.get('words'))[:80]}”" if rec.get("words") else "")
                   + "]")
    return out
