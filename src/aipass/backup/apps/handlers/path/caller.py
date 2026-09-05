# =================== AIPass ====================
# Name: caller.py
# Description: Caller-CWD path resolution — relative paths resolve where the user is
# Version: 1.0.0
# Created: 2026-08-08
# Modified: 2026-08-08
# =============================================

"""Caller-CWD path resolution handler.

Backup runs as an installed entry point, so ``Path.cwd()`` is backup's own
branch directory -- not where the user typed the command. A relative path
resolved against ``Path.cwd()`` therefore silently points into the backup
branch instead of the caller's project.

Drone exports ``AIPASS_CALLER_CWD`` before invoking a branch. Resolve every
user-supplied relative path against that, falling back to ``Path.cwd()`` for
direct invocation (tests, standalone runs). Same pattern @flow uses in
``handlers/plan/resolve_location.py``.
"""

import os
from pathlib import Path

from ..audit import trail


def caller_cwd() -> Path:
    """Return the directory the user invoked the command from.

    Drone passes it via AIPASS_CALLER_CWD. Falls back to Path.cwd() for
    direct invocation, where the process CWD *is* the caller's CWD.
    """
    caller = os.environ.get("AIPASS_CALLER_CWD")
    if caller:
        return Path(caller)
    return Path.cwd()


def resolve_caller_path(target: str | Path) -> Path:
    """Resolve a user-supplied path against the CALLER's directory.

    Absolute paths are returned resolved and otherwise untouched -- only
    relative paths are re-anchored, so absolute-path behaviour is identical
    to plain ``Path(target).resolve()``.

    Args:
        target: Path as the user typed it (absolute or relative).

    Returns:
        Absolute, resolved Path.
    """
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


# =============================================
