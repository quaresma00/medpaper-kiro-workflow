"""Comment/string-aware scanners for paper scripts. Stdlib only.

Both return (code, strings): `code` is the source with comments removed and string contents
blanked (offsets and newlines preserved, so regexes over code never see text inside strings),
`strings` the decoded string literals. Used by `no_plot_calls` and `paper_scripts_scoped`.
"""
from __future__ import annotations

import io
import re
import tokenize


def _blank(chars: list[str], start: int, end: int) -> None:
    for i in range(start, end):
        if chars[i] != "\n":
            chars[i] = " "


def scan_py(text: str) -> tuple[str, list[str]]:
    lines = text.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))

    def pos(rc):
        r, c = rc
        return offsets[r - 1] + c if r - 1 < len(offsets) else len(text)

    chars = list(text)
    strings: list[str] = []
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        code = re.sub(r"(?m)#.*$", "", text)
        found = re.findall(r"'([^'\n]*)'|\"([^\"\n]*)\"", code)
        code = re.sub(r"'[^'\n]*'|\"[^\"\n]*\"", lambda m: " " * len(m.group(0)), code)
        return code, [a or b for a, b in found]
    fstart = getattr(tokenize, "FSTRING_START", None)
    fmiddle = getattr(tokenize, "FSTRING_MIDDLE", None)
    fend = getattr(tokenize, "FSTRING_END", None)
    depth = 0
    f_begin = None
    f_text: list[str] = []
    for tok in toks:
        if fstart is not None and tok.type == fstart:
            if depth == 0:
                f_begin = pos(tok.start)
                f_text = []
            depth += 1
            continue
        if depth:
            if tok.type == fmiddle:
                f_text.append(tok.string)
            elif tok.type == fend:
                depth -= 1
                if depth == 0 and f_begin is not None:
                    _blank(chars, f_begin, pos(tok.end))
                    strings.append("".join(f_text))
            continue
        if tok.type == tokenize.COMMENT:
            _blank(chars, pos(tok.start), pos(tok.end))
        elif tok.type == tokenize.STRING:
            _blank(chars, pos(tok.start), pos(tok.end))
            s = tok.string
            m = re.match(r"(?is)^([rbuf]*)('''|\"\"\"|'|\")", s)
            if m:
                q = m.group(2)
                strings.append(s[len(m.group(0)):len(s) - len(q)])
            else:
                strings.append(s)
    return "".join(chars), strings


def scan_r(text: str) -> tuple[str, list[str]]:
    """State machine over R source: comments, "..."/'...' (escapes), `names`, raw strings."""
    chars = list(text)
    strings: list[str] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "#":
            j = text.find("\n", i)
            j = n if j == -1 else j
            _blank(chars, i, j)
            i = j
            continue
        raw = re.match(r"[rR]([\"'])(-*)([(\[{])", text[i:i + 40])
        if raw and (i == 0 or not (text[i - 1].isalnum() or text[i - 1] in "._")):
            quote, dashes, opener = raw.group(1), raw.group(2), raw.group(3)
            closer = {"(": ")", "[": "]", "{": "}"}[opener] + dashes + quote
            body_start = i + len(raw.group(0))
            j = text.find(closer, body_start)
            j = n if j == -1 else j
            strings.append(text[body_start:j])
            end = min(n, j + len(closer))
            _blank(chars, i, end)
            i = end
            continue
        if c in "\"'`":
            j = i + 1
            buf = []
            while j < n and text[j] != c:
                if text[j] == "\\" and j + 1 < n:
                    buf.append(text[j:j + 2])
                    j += 2
                    continue
                buf.append(text[j])
                j += 1
            end = min(n, j + 1)
            if c != "`":
                strings.append(re.sub(r"\\(.)", r"\1", "".join(buf)))
            _blank(chars, i + 1, end - 1 if end - 1 > i else end)
            i = end
            continue
        i += 1
    return "".join(chars), strings
