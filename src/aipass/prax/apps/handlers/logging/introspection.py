# =================== AIPass ====================
# Name: introspection.py
# Description: Stack Introspection
# Version: 1.7.0
# Created: 2025-11-10
# Modified: 2026-11-18
# =============================================

"""PRAX Logging Introspection"""

import functools
from pathlib import Path
from typing import Optional

import aipass
from aipass.prax.apps.handlers.logging.trail import PraxTrail

logger = PraxTrail("introspection")

_PRAX_INTERNAL_MARKERS = (
    "/prax/apps/modules/logger.py",
    "/prax/apps/handlers/",
    "prax_logger.py",
    "prax_handlers.py",
)


def _is_prax_internal(module_path: str) -> bool:
    """Check if a module path belongs to prax internals."""
    return any(marker in module_path for marker in _PRAX_INTERNAL_MARKERS)


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
    AIPASS_LOG_NAME overrides the name.
    """
    import os

    caller_path = _find_external_caller_path()
    branch = detect_branch_from_path(caller_path) if caller_path else None

    log_name = os.environ.get("AIPASS_LOG_NAME")
    if log_name:
        return (log_name, caller_path, branch)

    if not caller_path:
        return ("unknown_module", None, None)
    module_name = Path(caller_path).stem
    return (module_name, caller_path, branch)


_AIPASS_PKG_ROOT = Path(aipass.__file__).resolve().parent
_SRC_ROOT = _AIPASS_PKG_ROOT.parent  # aipass/ → src/ (contains branches outside aipass namespace)
_REPO_ROOT = _SRC_ROOT.parent  # src/ → AIPass repo root


def _resolve_caller_path(module_path: str) -> Optional[Path]:
    """Resolve a caller's path without ever requiring a working directory.

    ``<stdin>`` or a relative ``__file__`` would make resolve() read a dead cwd; None is an answer, never a raise.
    """
    # is_absolute() alone also refuses a "<" pseudo-filename; a second guard would be dead.
    candidate = Path(module_path) if module_path else None
    if candidate is None or not candidate.is_absolute():
        return None
    try:
        return candidate.resolve()
    except OSError as exc:
        logger.info("Caller path could not be resolved", path=module_path, error=str(exc))
        return None


# Runs on every log line; resolve() is the cost and a module file does not move mid-process.
@functools.lru_cache(maxsize=1024)
def detect_branch_from_path(module_path: str) -> Optional[str]:
    """Branch dir of a module: src/aipass/{b}/, src/{b}/, else the nearest ancestor with a passport."""
    path = _resolve_caller_path(module_path)
    if path is None:
        return None

    # No record of any kind on this path: it runs on every log line, and its misses are answers.
    if path.is_relative_to(_AIPASS_PKG_ROOT):
        relative = path.relative_to(_AIPASS_PKG_ROOT)
        if len(relative.parts) >= 2:
            return str(_AIPASS_PKG_ROOT / relative.parts[0])

    if path.is_relative_to(_SRC_ROOT):
        relative = path.relative_to(_SRC_ROOT)
        if len(relative.parts) >= 2 and relative.parts[0] != "aipass":
            return str(_SRC_ROOT / relative.parts[0])

    return next((str(p) for p in path.parents if (p / ".trinity" / "passport.json").is_file()), None)


def detect_external_project(module_path: str) -> Optional[tuple]:
    """Detect if a module path belongs to an external project (outside AIPass repo).

    Returns (project_name, project_root) from the nearest .git or pyproject.toml, else None."""
    path = _resolve_caller_path(module_path)
    if path is None:
        return None

    if path.is_relative_to(_REPO_ROOT):
        return None

    import os

    caller_cwd = os.environ.get("AIPASS_CALLER_CWD")
    search_path = path if path.exists() else (Path(caller_cwd) if caller_cwd else None)

    if not search_path:
        return None

    for candidate in [search_path] + list(search_path.parents):
        if (
            (m := candidate / ".git").is_file()
            or (m.is_dir() and any(m.iterdir()))
            or (candidate / "pyproject.toml").exists()
        ):
            project_name = candidate.name.lower().replace(" ", "_").replace("-", "_")
            return (project_name, candidate)

    return None
