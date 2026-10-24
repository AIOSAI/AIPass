# =================== AIPass ====================
# Name: introspection.py
# Description: Stack Introspection
# Version: 1.2.0
# Created: 2025-11-10
# Modified: 2026-10-23
# =============================================

"""PRAX Logging Introspection"""

import functools
import logging
from pathlib import Path
from typing import Optional

from aipass.prax.apps.handlers.json import json_handler
from aipass.prax.apps.handlers.repo_root import resolved_file

logger = logging.getLogger(__name__)

_PRAX_INTERNAL_MARKERS = (
    "/prax/apps/modules/logger.py",
    "/prax/apps/handlers/",
    "prax_logger.py",
    "prax_handlers.py",
)


def _is_prax_internal(module_path: str) -> bool:
    """Check if a module path belongs to prax internals."""
    norm = module_path.replace("\\", "/")
    return any(marker in norm for marker in _PRAX_INTERNAL_MARKERS)


def _find_external_caller_path() -> Optional[str]:
    """Walk the stack and return the first non-prax module path, or None."""
    import inspect

    frame = inspect.currentframe()
    try:
        current_frame = frame
        frame_count = 0
        while current_frame and frame_count < 10:
            current_frame = current_frame.f_back
            frame_count += 1
            if not current_frame:
                break
            module_path = current_frame.f_globals.get("__file__", "")
            if not module_path or module_path == __file__:
                continue
            if not _is_prax_internal(module_path):
                return module_path
        return None
    finally:
        del frame


def get_calling_module_path() -> Optional[str]:
    """Detect calling module path from stack trace"""
    return _find_external_caller_path()


def get_caller_info() -> tuple:
    """Detect calling module name, path, and branch from a single stack walk.

    One walk, so name and path never come from different callers.
    AIPASS_LOG_NAME, then AIPASS_BOT_ID (telegram-bot@.service), override the name.
    """
    import os

    caller_path = _find_external_caller_path()
    branch = detect_branch_from_path(caller_path) if caller_path else None

    log_name = os.environ.get("AIPASS_LOG_NAME")
    if log_name:
        return (log_name, caller_path, branch)

    bot_id = os.environ.get("AIPASS_BOT_ID")
    if bot_id:
        return (f"bot_{bot_id}", caller_path, branch)

    if not caller_path:
        return ("unknown_module", None, None)
    module_name = Path(caller_path).stem
    return (module_name, caller_path, branch)


_AIPASS_PKG_ROOT = resolved_file(Path(__file__)).parents[4]  # logging/ → handlers/ → apps/ → prax/ → aipass/
_SRC_ROOT = _AIPASS_PKG_ROOT.parent  # aipass/ → src/ (contains branches outside aipass namespace)
_REPO_ROOT = _SRC_ROOT.parent  # src/ → AIPass repo root


def _resolve_caller_path(module_path: str) -> Optional[Path]:
    """Resolve a caller's path without ever requiring a working directory.

    ``<stdin>`` or a relative ``__file__`` would make resolve() read a possibly deleted cwd.
    None is an answer: not knowing the caller must never take down the caller's import.
    """
    # is_absolute() alone also refuses a "<" pseudo-filename; a second guard would be dead.
    candidate = Path(module_path) if module_path else None
    if candidate is None or not candidate.is_absolute():
        return None
    try:
        return candidate.resolve()
    except OSError as exc:
        logger.info("Caller path %s could not be resolved: %s", module_path, exc)
        return None


# Runs on every log line; resolve() is the cost and a module file does not move mid-process.
@functools.lru_cache(maxsize=1024)
def detect_branch_from_path(module_path: str) -> Optional[str]:
    """Detect branch name from module file path: src/aipass/{branch}/... or src/{branch}/..."""
    path = _resolve_caller_path(module_path)
    if path is None:
        return None

    try:
        relative = path.relative_to(_AIPASS_PKG_ROOT)
        if len(relative.parts) >= 2:
            # No json operation here: every module-level get_direct_logger() resolves through this.
            return relative.parts[0]
    except ValueError:
        logger.info("Path %s is not relative to aipass package root", module_path)

    try:
        relative = path.relative_to(_SRC_ROOT)
        if len(relative.parts) >= 2 and relative.parts[0] != "aipass":
            return relative.parts[0]
    except ValueError:
        logger.info("Path %s is not relative to src root", module_path)

    return None


def detect_external_project(module_path: str) -> Optional[tuple]:
    """Detect if a module path belongs to an external project (outside AIPass repo).

    Returns (project_name, project_root) from the nearest .git or pyproject.toml, else None."""
    path = _resolve_caller_path(module_path)
    if path is None:
        return None

    try:
        path.relative_to(_REPO_ROOT)
        return None
    except ValueError:
        logger.info("Path %s is external to AIPass repo", module_path)

    import os

    caller_cwd = os.environ.get("AIPASS_CALLER_CWD")
    search_path = path if path.exists() else (Path(caller_cwd) if caller_cwd else None)

    if not search_path:
        return None

    for candidate in [search_path] + list(search_path.parents):
        if (candidate / ".git").exists() or (candidate / "pyproject.toml").exists():
            project_name = candidate.name.lower().replace(" ", "_").replace("-", "_")
            # Logged outside AIPass only, never on a fleet module's import.
            json_handler.log_operation(
                "introspection_external_project",
                {"module_path": module_path, "project": project_name},
                module_name="prax_introspection",
            )
            return (project_name, candidate)

    return None
