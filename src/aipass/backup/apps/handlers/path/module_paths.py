# =================== AIPass ====================
# Name: module_paths.py
# Description: Safe module-file path resolution that never requires a live cwd
# Version: 1.0.0
# Created: 2026-08-31
# Modified: 2026-10-17
# =============================================

"""The branch's ONE safe path helper."""

# ntpath.realpath (under Path.resolve) reads os.getcwd always: a dead cwd crashes any import-time resolve().
# Stdlib only: importing @prax here would put its cwd-reading logger on the path this module protects.

import os
import sys
from pathlib import Path

_REPORTED_DEGRADED: set[str] = set()


def module_file(dunder_file: str) -> Path:
    """Absolute path of a module file, without requiring a readable cwd."""
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
    """Walk up from a module file to a branch-relative root."""
    return module_file(dunder_file).parents[parents]


def _report_degraded(dunder_file: str, exc: OSError) -> None:
    """Announce a degraded resolution once, on a channel that cannot be down."""
    if dunder_file in _REPORTED_DEGRADED:
        return
    _REPORTED_DEGRADED.add(dunder_file)
    try:
        sys.stderr.write(f"[backup] cwd unreadable, using raw path for {dunder_file}: {exc}\n")
    except OSError:
        # No third channel; raising would turn a degraded path into the dead import this module prevents.
        return
