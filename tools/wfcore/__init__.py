"""medpaper workflow engine. Stdlib only, no third-party imports anywhere in this package."""
import sys as _sys

# Chinese paths and --why text must survive pipes and logs on Windows, where the default
# stream encoding is the ANSI code page. Every engine entry point imports this package.
for _stream in (_sys.stdout, _sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # replaced or closed streams (tests, embedded hosts)
        pass

__all__ = ["cli", "gates", "paths", "registry", "state", "xlsxlite", "checks"]
