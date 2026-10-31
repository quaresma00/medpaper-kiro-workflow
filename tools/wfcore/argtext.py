"""1.12.0 (C1): the user's own words survive the PowerShell -> Python hop intact.

Chinese text passed as `--words` / `--why` reached state as mojibake ('鏃犻渶缁х画...'): the
agent's shell had already decoded the UTF-8 bytes of the command with the ANSI code page, so
Python received the wrong characters (sys.argv itself is correct wide-char data). Three
remedies, applied by every engine CLI before argparse:

  * repair(): text that is UTF-8 bytes mis-decoded as GBK/cp1252/latin-1 is decoded back
    (strict, and only when that yields fewer characters - real Chinese never round-trips);
  * `--words-file <utf8 file>` / `--why-file <utf8 file>` and `--words-b64` / `--why-b64`
    carry the text without going through the shell's code page at all;
  * verify() refuses text that still contains U+FFFD or looks mis-decoded, so a garbled
    confirmation is never written; callers read the stored value back and verify again.
"""
from __future__ import annotations

import base64
import sys
from pathlib import Path

TEXT_OPTIONS = ("--words", "--why", "--rewind-words", "--note")
_CODECS = ("gbk", "gb18030", "cp1252", "latin-1", "cp932", "cp949", "big5")


def _ansi_codec() -> str | None:
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        return f"cp{int(ctypes.windll.kernel32.GetACP())}"
    except Exception:  # noqa: BLE001
        return None


def repair(text: str) -> str:
    """UTF-8 bytes that were decoded with a legacy code page -> the original text."""
    if not text or text.isascii():
        return text
    seen = []
    for codec in filter(None, (_ansi_codec(), *_CODECS)):
        if codec in seen:
            continue
        seen.append(codec)
        try:
            fixed = text.encode(codec).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError, LookupError):
            continue
        if fixed != text and len(fixed) < len(text) and not fixed.isascii():
            return fixed
    return text


def suspicious(text: str) -> str:
    """'' when the text looks intact, else why it does not."""
    if "\ufffd" in str(text or ""):
        return "contains U+FFFD (replacement character)"
    if repair(str(text or "")) != str(text or ""):
        return "looks like UTF-8 decoded with a legacy code page (mojibake)"
    return ""


def verify(text: str, what: str = "text") -> str:
    why = suspicious(text)
    if why:
        raise ValueError(f"{what} {why}; pass it with --words-file <utf-8 file> (or --words-b64) "
                         "instead of typing it into the shell")
    return text


def _wide_argv() -> list[str] | None:
    """The process command line as the OS stores it (UTF-16), Windows only."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes
        get = ctypes.windll.kernel32.GetCommandLineW
        get.restype = wintypes.LPCWSTR
        split = ctypes.windll.shell32.CommandLineToArgvW
        split.restype = ctypes.POINTER(wintypes.LPWSTR)
        n = ctypes.c_int()
        arr = split(get(), ctypes.byref(n))
        return [arr[i] for i in range(n.value)]
    except Exception:  # noqa: BLE001
        return None


def read_text_retry(path: Path, encoding: str = "utf-8", seconds: float = 3.0) -> str:
    """1.15.0: a file the agent wrote a moment ago is sometimes not yet visible to the next
    process on Windows; wait briefly instead of failing the command."""
    import time
    deadline = time.monotonic() + seconds
    while True:
        try:
            return Path(path).read_text(encoding=encoding)
        except FileNotFoundError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.25)


def wait_visible(path: Path | None, seconds: float = 3.0) -> bool:
    import time
    if path is None:
        return False
    deadline = time.monotonic() + seconds
    while not Path(path).is_file():
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.25)
    return True


def fix_argv(argv: list[str]) -> list[str]:
    """Expand --X-file / --X-b64 into --X <text> and repair mis-decoded text arguments."""
    argv = list(argv)
    if any("\ufffd" in a for a in argv):
        wide = _wide_argv()
        if wide and len(wide) >= len(argv) and not any("\ufffd" in a for a in wide[-len(argv):]):
            argv = wide[-len(argv):]
    out: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        name, eq, inline = arg.partition("=")
        for opt in TEXT_OPTIONS:
            if name in (opt + "-file", opt + "-b64"):
                value = inline if eq else (argv[i + 1] if i + 1 < len(argv) else "")
                i += 0 if eq else 1
                if name.endswith("-file"):
                    text = read_text_retry(Path(value), "utf-8-sig").strip()
                else:
                    text = base64.b64decode(value).decode("utf-8").strip()
                out += [opt, text]
                break
        else:
            out.append(repair(arg) if i and argv[i - 1] in TEXT_OPTIONS or
                       (eq and name in TEXT_OPTIONS) else arg)
        i += 1
    return out
