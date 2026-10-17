# =================== AIPass ====================
# Name: repo_root.py
# Description: The one guarded answer to "where is my file" and "which repo root is this"
# Version: 1.0.0
# Created: 2026-08-31
# Modified: 2026-10-17
# =============================================

"""Location discovery for flow, defined once and guarded.

On Windows ``Path.resolve()`` reads the cwd, so a module-level resolve dies when the cwd is gone.
The repo-root fallback is this file's tree, never cwd: writers on a guessed root write anywhere.
"""

import os
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger

MODULE_NAME = "repo_root"

CORE_REGISTRY = "AIPASS_REGISTRY.json"


def module_file(file: str) -> Path:
    """A module's own path, absolute, resolved when the filesystem allows."""
    path = Path(file)
    try:
        return path.resolve()
    except OSError as exc:
        # debug, not warning: every module import takes this path in that world.
        logger.debug(f"[{MODULE_NAME}] Cannot resolve {path} ({type(exc).__name__}) — using its absolute spelling")
        return path


# Last resort is the filesystem root: never raises, and fails loudly downstream.
_THIS_FILE = module_file(__file__)
SOURCE_ROOT = next(
    (parent.parent for parent in _THIS_FILE.parents if parent.name == "src"),
    _THIS_FILE.parents[-1],
)


def exists_exactly(path: Path) -> bool:
    """True when *path* exists AND is spelled on disk exactly as asked.

    Lists the parent because resolve() follows symlinks; an unlistable parent returns True.
    """
    candidate = Path(path)
    if not candidate.exists():
        return False
    try:
        with os.scandir(candidate.parent) as entries:
            return any(entry.name == candidate.name for entry in entries)
    except OSError as exc:
        logger.debug(
            f"[{MODULE_NAME}] Cannot enumerate {candidate.parent} ({exc}) — trusting exists() for {candidate.name}"
        )
        return True


def exactly_named(candidates: list[Path], suffix: str) -> list[Path]:
    """Keep only the candidates whose filename ends with *suffix* in EXACT case.

    Never reorders: callers sort first, and order decides which is read first.
    """
    return [path for path in candidates if path.name.endswith(suffix)]


def _record_fallback(caller: str, marker: str, current: Path) -> None:
    """Log the fallback loudly, and record it without ever raising."""
    logger.warning(
        f"[{caller}] No {marker} above {current} — "
        f"resolving to the source tree at {SOURCE_ROOT}, never the process directory"
    )
    try:
        from aipass.flow.apps.handlers.json import json_handler

        json_handler.log_operation(
            "repo_root_fallback",
            {"caller": caller, "marker": marker, "searched_from": str(current), "resolved": str(SOURCE_ROOT)},
            module_name=MODULE_NAME,
        )
    except Exception as exc:  # an audit line must never take an import down
        logger.debug(f"[{caller}] repo_root fallback not recorded: {type(exc).__name__}: {exc}")


def find_repo_root(start: Path | None = None, *, marker: str = CORE_REGISTRY, caller: str = MODULE_NAME) -> Path:
    """Walk up from *start* to the directory holding *marker*."""
    current = Path(start) if start is not None else module_file(__file__).parent
    for parent in [current] + list(current.parents):
        if exists_exactly(parent / marker):
            return parent
    _record_fallback(caller, marker, current)
    return SOURCE_ROOT
