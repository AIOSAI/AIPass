# =================== AIPass ====================
# Name: module_paths.py
# Description: Safe module-file path resolution that never requires a live cwd
# Version: 1.0.0
# Created: 2026-08-31
# Modified: 2026-08-31
# =============================================

"""The branch's ONE safe path helper.

``ntpath.realpath`` reads ``os.getcwd()`` unconditionally -- posixpath only does
so for relative paths -- and ``Path.resolve()`` routes through it. So on Windows
every ``resolve()`` reached at import time is an import-time crash for a process
whose cwd was deleted: the module cannot be imported at all.

Every module-level path in this branch goes through :func:`module_file` or
:func:`branch_root`, so that world degrades to the raw absolute spelling instead
of killing the import.

Stdlib only, deliberately: this is imported by the handlers package guard before
anything else exists, and importing @prax here would put the logger's own
cwd-reading construction on the path this module exists to protect.
"""

import os
import sys
from pathlib import Path

#: Paths already reported as degraded. A dead cwd makes EVERY resolve fail, and
#: one line per call would bury the real traceback under its own noise.
_REPORTED_DEGRADED: set[str] = set()


def module_file(dunder_file: str) -> Path:
    """Absolute path of a module file, without requiring a readable cwd.

    ``Path.resolve()`` is tried first so symlinks still collapse normally. When
    the cwd is gone the fallback is ``os.path.abspath`` on a path that is
    already absolute -- which is the identity, and needs no cwd.

    Args:
        dunder_file: A module's ``__file__``.

    Returns:
        Absolute Path. Symlinks are resolved when the world allows it.
    """
    raw = Path(dunder_file)
    try:
        return raw.resolve()
    except OSError as exc:
        _report_degraded(dunder_file, exc)
        try:
            return Path(os.path.abspath(dunder_file))
        except OSError as abspath_exc:
            _report_degraded(f"{dunder_file} (abspath)", abspath_exc)
            return raw


def branch_root(dunder_file: str, parents: int) -> Path:
    """Walk up from a module file to a branch-relative root.

    Args:
        dunder_file: A module's ``__file__``.
        parents: How many levels up from the file to climb.

    Returns:
        Absolute Path to the ancestor directory.
    """
    return module_file(dunder_file).parents[parents]


def _report_degraded(dunder_file: str, exc: OSError) -> None:
    """Announce a degraded resolution once, on a channel that cannot be down.

    The diagnostics live INSIDE their own protection: the world that reaches
    this fallback may have taken the logger with it, because @prax builds its
    logger by reading the cwd. A stream report is the accepted last resort.
    """
    if dunder_file in _REPORTED_DEGRADED:
        return
    _REPORTED_DEGRADED.add(dunder_file)
    try:
        sys.stderr.write(f"[backup] cwd unreadable, using raw path for {dunder_file}: {exc}\n")
    except OSError:
        # stderr itself is gone. There is no third channel to report on, and
        # raising here would replace a degraded path with a dead import --
        # exactly the failure this module exists to prevent.
        return
