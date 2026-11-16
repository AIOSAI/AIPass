# =================== AIPass ====================
# Name: repo_root.py
# Description: One guarded answer to "where is my file" and "where is the repo root" — never the process cwd
# Version: 1.2.0
# Created: 2026-08-31
# Modified: 2026-11-16
# =============================================

"""Module-file and repo-root resolution, defined once for trigger.

Never the cwd."""

import os
from collections.abc import Callable
from pathlib import Path

from aipass.prax import logger

MODULE_NAME = "repo_root"

# Filled when the fallback logger itself fails; see _record_fallback.
RECORD_FAILURES: list[str] = []

CORE_REGISTRY = "AIPASS_REGISTRY.json"


_THIS_FILE = Path(__file__).resolve()

# Last resort is the filesystem root: never raises, and fails loudly downstream instead of quietly.
SOURCE_ROOT = next(
    (parent.parent for parent in _THIS_FILE.parents if parent.name == "src"),
    _THIS_FILE.parents[-1],
)


def exists_exactly(path: Path, exists_fn: Callable[[Path], bool] | None = None) -> bool:
    """True when *path* exists AND is spelled on disk exactly as asked; an unlistable parent raises.

    Lists the parent: exists() case-folds on a WSL2 /mnt/c drvfs mount, resolve() follows symlinks."""
    candidate = Path(path)
    exists = candidate.exists() if exists_fn is None else exists_fn(candidate)
    if not exists:
        return False
    with os.scandir(candidate.parent) as entries:
        return any(entry.name == candidate.name for entry in entries)


def _record_fallback(caller: str, marker: str, current: Path) -> None:
    """Record the fallback without ever raising: callers reach it at import time."""
    try:
        logger.warning(
            f"[{caller}] No {marker} above {current} — "
            f"resolving to the source tree at {SOURCE_ROOT}, never the process directory"
        )
        # Function-local: a module-level import closes a cycle through config.
        from aipass.trigger.apps.handlers.json import json_handler

        json_handler.log_operation(
            "repo_root_fallback",
            {"caller": caller, "marker": marker, "searched_from": str(current), "resolved": str(SOURCE_ROOT)},
            module_name=MODULE_NAME,
        )
    except Exception as exc:  # an audit line must never take an import down
        RECORD_FAILURES.append(f"{caller}/{marker}: {type(exc).__name__}: {exc}")


def find_repo_root(
    start: Path | None = None,
    *,
    marker: str = CORE_REGISTRY,
    caller: str = MODULE_NAME,
    exists_fn: Callable[[Path], bool] | None = None,
) -> Path:
    """Walk up from *start* to the directory holding *marker*; falls back to SOURCE_ROOT, never the cwd."""
    current = Path(start) if start is not None else _THIS_FILE.parent
    for parent in [current] + list(current.parents):
        if exists_exactly(parent / marker, exists_fn):
            return parent
    _record_fallback(caller, marker, current)
    return SOURCE_ROOT
