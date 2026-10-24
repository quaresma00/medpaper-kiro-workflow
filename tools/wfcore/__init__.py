"""medpaper workflow engine. Stdlib only, no third-party imports anywhere in this package."""
import os as _os
import sys as _sys


def _console_cp():
    """The attached Windows console's output code page (what PowerShell decodes with)."""
    if _sys.platform != "win32":
        return None
    try:
        import ctypes
        return int(ctypes.windll.kernel32.GetConsoleOutputCP()) or None
    except Exception:  # noqa: BLE001 - no console / no ctypes
        return None


def stream_encoding(isatty: bool, env: dict, console_cp) -> str:
    """1.11.0 (#3e): bytes the READER decodes correctly.

    Chinese text (stage-card questions, --why) used to reach the agent as mojibake: the engine
    wrote UTF-8 into a pipe that PowerShell decodes with the console code page (936). Now:
    an explicit MEDPAPER_STDOUT_ENCODING or PYTHONIOENCODING wins; a console (tty) or a
    UTF-8 console (65001) gets UTF-8; a pipe under a non-UTF-8 console gets that code page.
    Log files are always written as UTF-8 regardless.
    """
    explicit = env.get("MEDPAPER_STDOUT_ENCODING") or env.get("PYTHONIOENCODING")
    if explicit:
        return explicit.split(":")[0].strip() or "utf-8"
    if isatty or not console_cp or console_cp == 65001:
        return "utf-8"
    return f"cp{console_cp}"


for _stream in (_sys.stdout, _sys.stderr):
    try:
        _tty = bool(_stream.isatty())
        _stream.reconfigure(encoding=stream_encoding(_tty, _os.environ, None if _tty else _console_cp()),
                            errors="replace")
    except (AttributeError, ValueError, LookupError, OSError):  # replaced/closed streams
        pass

__all__ = ["cli", "gates", "paths", "registry", "state", "xlsxlite", "checks"]
