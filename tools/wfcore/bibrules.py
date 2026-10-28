"""1.12.0 (A7): ONE title-protection rule shared by the bib exporter and bib_format_clean.

tools/pubmed/build_library.py braces proper nouns and acronyms with `protect_title`; the
S13 gate asks `unprotected_words` which words a sentence-case CSL could still lowercase. Both
walk the same tokens with the same exceptions (an ordinary word after a colon stays unbraced),
so a freshly exported refs.bib always passes the gate.
"""
from __future__ import annotations

import re

COLON_COMMON = {
    "a", "an", "the", "results", "findings", "evidence", "lessons", "insights", "implications",
    "analysis", "study", "review", "protocol", "rationale", "design", "update", "report",
    "experience", "outcomes", "comparison", "assessment", "evaluation", "association", "role",
    "impact", "effect", "effects", "risk", "trends", "challenges", "current", "new", "is", "does",
    "do", "are", "can", "should", "what", "when", "how", "why", "who", "where", "from", "toward",
    "towards", "beyond", "time", "more", "less", "no", "not", "one", "two", "three",
}
_STRIP = "()[]:;,.\"'"


def _walk(title: str):
    """Yield (token, core, needs_brace) for every token of a title."""
    after_colon = False
    for i, tok in enumerate(re.split(r"(\s+)", title)):
        core = tok.strip(_STRIP)
        if tok.isspace() or not core or "{" in tok:
            if "{" in tok:
                # 1.13.0: an already-braced word can end a clause ("{Toxicity}:"); keep the
                # colon state so the gate walks an exported title exactly like the exporter.
                after_colon = tok.rstrip().endswith(":")
            yield tok, core, False
            continue
        upper_inside = any(ch.isupper() for ch in core[1:])
        colon_word = after_colon and core.casefold() in COLON_COMMON
        after_colon = tok.rstrip().endswith(":")
        if colon_word and not upper_inside:
            yield tok, core, False
        else:
            yield tok, core, bool((i > 0 and core[:1].isupper()) or upper_inside)


def protect_title(title: str) -> str:
    out = []
    for tok, core, brace in _walk(title):
        if brace:
            start = tok.find(core)
            out.append(tok[:start] + "{" + core + "}" + tok[start + len(core):])
        else:
            out.append(tok)
    return "".join(out)


def unprotected_words(title: str) -> list[str]:
    return [core for _, core, brace in _walk(title) if brace]
