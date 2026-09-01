# =================== AIPass ====================
# Name: module_paths.py
# Description: Dead-cwd-safe module location for skills
# Version: 1.0.0
# Created: 2026-08-31
# Modified: 2026-08-31
# =============================================

"""
Module location that survives an unreadable current directory.

WHY THIS EXISTS. ``Path.resolve()`` routes through ``os.path.realpath``, and
``ntpath.realpath`` calls ``os.getcwd()`` on its first lines UNCONDITIONALLY —
before it checks whether the path is even relative. ``posixpath.realpath``
reads the cwd only for relative paths, which is why this was invisible on
Linux. A process whose working directory has been deleted, or which sits on a
disconnected network share, therefore cannot IMPORT a module that calls
``Path(__file__).resolve()`` at module scope. Not "misbehaves" — cannot import.

Skill units run in host processes nobody here chose: the telegram relay, a
cron-fired lane, a hook subprocess. Those are exactly the processes most likely
to hold a dead or foreign cwd, so every module-level location in this branch
goes through here.

STDLIB ONLY, DELIBERATELY. Importing prax would put the logger's own
construction — which reads the cwd — onto the very path this helper protects.
The fallback reports through ``sys.stderr`` instead, which is the accepted last
resort for a diagnostic that cannot afford a logger (seedgo's silent_catch
accepts a stream report). The report is deduped per path so a dead world writes
one line per module rather than burying the real traceback.
"""

import os
import sys
from pathlib import Path

__all__ = ["module_file"]

# Paths already reported this process. A dead cwd is a property of the process,
# not of one import, so without this every module in the fan writes its own line.
_REPORTED: set = set()


def _report(raw: str, error: OSError) -> None:
    """Announce a degraded resolve once per path, never raising.

    Args:
        raw: The spelling being returned instead of the resolved one.
        error: What resolve() raised.
    """
    # The diagnostic lives inside its own protection: a world that broke
    # resolve() can just as easily have closed stderr, and a fallback that
    # dies while explaining itself is worse than one that stays quiet.
    try:
        if raw in _REPORTED:
            return
        _REPORTED.add(raw)
        sys.stderr.write(
            "[skills] resolve() unavailable for %s (%s); using the unresolved absolute spelling\n" % (raw, error)
        )
    except Exception:  # noqa: BLE001 - a broken stderr must not break an import
        pass


def module_file(dunder_file: str) -> Path:
    """Return a module's own path without requiring a readable cwd.

    Args:
        dunder_file: The calling module's ``__file__``.

    Returns:
        Path: The resolved path, or the unresolved absolute spelling when the
        working directory is unreadable. Never raises OSError.

    Note:
        ``__file__`` has been absolute for imported modules since Python 3.9,
        so the fallback loses symlink normalisation and nothing else. That is
        the whole trade: a normalised path that cannot be computed is worth
        less than an un-normalised one that can.
    """
    raw = str(dunder_file)
    try:
        return Path(raw).resolve()
    except OSError as exc:
        _report(raw, exc)
        # abspath is NOT a second cwd read for an absolute input: posixpath
        # reads the cwd only when the path is relative, and ntpath's
        # _getfullpathname answers an absolute path without one. Measured
        # green under the getcwd-denied world on 2026-08-31.
        try:
            return Path(os.path.abspath(raw))
        except OSError as abspath_exc:
            # abspath was measured green under the getcwd-denied world, so
            # reaching here means a world nobody has named yet. Say so — a
            # second swallow would leave the caller holding a path with no
            # record of how degraded it is.
            _report(raw, abspath_exc)
            return Path(raw)
