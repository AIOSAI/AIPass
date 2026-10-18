# =================== AIPass ====================
# Name: module_paths.py
# Description: Dead-cwd-safe module location for skills
# Version: 1.0.0
# Created: 2026-08-31
# Modified: 2026-10-17
# =============================================

"""
Module location that survives an unreadable current directory.

Reference: docs/dead_cwd.md
"""

# Stdlib only: importing prax puts the logger's cwd-reading construction on the path this guards.
import os
import sys
from pathlib import Path

__all__ = ["module_file"]

# A dead cwd belongs to the process, so report once per path or every module in the fan writes a line.
_REPORTED: set = set()


def _report(raw: str, error: OSError) -> None:
    """Announce a degraded resolve once per path, never raising."""
    try:
        if raw in _REPORTED:
            return
        _REPORTED.add(raw)
        sys.stderr.write(
            "[skills] resolve() unavailable for %s (%s); using the unresolved absolute spelling\n" % (raw, error)
        )
    except Exception:  # a broken stderr must not break an import
        pass


def module_file(dunder_file: str) -> Path:
    """Return a module's own path without requiring a readable cwd."""
    raw = str(dunder_file)
    try:
        return Path(raw).resolve()
    except OSError as exc:
        _report(raw, exc)
        # abspath is not a second cwd read for an absolute input: posixpath reads it only for
        # relative paths, and ntpath's _getfullpathname answers an absolute path without one.
        try:
            return Path(os.path.abspath(raw))
        except OSError as abspath_exc:
            _report(raw, abspath_exc)
            return Path(raw)
