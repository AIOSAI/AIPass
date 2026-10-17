# =================== AIPass ====================
# Name: repo_root.py
# Description: One guarded answer to "where is my file" and "where is the repo root" — never the process cwd
# Version: 1.1.0
# Created: 2026-08-31
# Modified: 2026-10-17
# =============================================

"""Module-file and repo-root resolution, defined once for trigger.

Never the cwd, never resolve() at import (Windows reads os.getcwd()); no prax (watched path, circular)."""

import os
from collections.abc import Callable
from pathlib import Path

from aipass.trigger.apps.config import TRIGGER_ROOT, module_file, trail_logger

MODULE_NAME = "repo_root"

# Tests redirect the trail to a temp dir, or their pins write into the live tree.
_test_log_dir = os.environ.get("AIPASS_TEST_LOG_DIR")
if _test_log_dir:
    _LOG_FILE = Path(_test_log_dir) / "trigger" / "repo_root.jsonl"
else:
    _LOG_FILE = TRIGGER_ROOT / "logs" / "repo_root.jsonl"

logger = trail_logger(_LOG_FILE)

# Filled when the fallback logger itself fails; see _record_fallback.
RECORD_FAILURES: list[str] = []

CORE_REGISTRY = "AIPASS_REGISTRY.json"


_THIS_FILE = module_file(__file__)

# Last resort is the filesystem root: never raises, and fails loudly downstream instead of quietly.
SOURCE_ROOT = next(
    (parent.parent for parent in _THIS_FILE.parents if parent.name == "src"),
    _THIS_FILE.parents[-1],
)


def exists_exactly(path: Path, exists_fn: Callable[[Path], bool] | None = None) -> bool:
    """True when *path* exists AND is spelled on disk exactly as asked.

    Lists the parent (exists() case-folds, resolve() follows symlinks); an unlistable parent returns True."""
    candidate = Path(path)
    exists = candidate.exists() if exists_fn is None else exists_fn(candidate)
    if not exists:
        return False
    try:
        with os.scandir(candidate.parent) as entries:
            return any(entry.name == candidate.name for entry in entries)
    except OSError:
        return True


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
