# =================== AIPass ====================
# Name: caller.py
# Description: Caller-CWD path resolution — relative paths resolve where the user is
# Version: 1.0.0
# Created: 2026-08-08
# Modified: 2026-10-17
# =============================================

"""Caller-CWD path resolution handler."""

# Under drone, Path.cwd() is backup's own branch dir; drone exports AIPASS_CALLER_CWD, where the user typed.

import os
from pathlib import Path

from ..audit import trail


def caller_cwd() -> Path:
    """Return the directory the user invoked the command from."""
    caller = os.environ.get("AIPASS_CALLER_CWD")
    if caller:
        return Path(caller)
    return Path.cwd()


def resolve_caller_path(target: str | Path) -> Path:
    """Resolve a user-supplied path against the CALLER's directory."""
    path = Path(target)
    if path.is_absolute():
        resolved = path.resolve()
    else:
        resolved = (caller_cwd() / path).resolve()
    trail.log_operation(
        "resolve_caller_path",
        {"given": str(target), "resolved": str(resolved)},
    )
    return resolved
