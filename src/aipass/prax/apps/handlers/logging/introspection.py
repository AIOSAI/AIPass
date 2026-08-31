# =================== AIPass ====================
# Name: introspection.py
# Description: Stack Introspection
# Version: 1.1.0
# Created: 2025-11-10
# Modified: 2026-08-31
# =============================================

"""
PRAX Logging Introspection

Stack introspection for detecting calling modules and branch paths.
Used by logger_setup.py to route logs to correct files.
"""

import logging
from pathlib import Path
from typing import Optional

from aipass.prax.apps.handlers.json import json_handler

logger = logging.getLogger(__name__)

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


def get_calling_module() -> str:
    """Detect calling module from stack trace

    Returns:
        Module name (e.g., 'drone', 'flow', 'spawn') or 'unknown_module'
    """
    caller_path = _find_external_caller_path()
    if caller_path:
        return Path(caller_path).stem
    return "unknown_module"


def get_calling_module_path() -> Optional[str]:
    """Detect calling module path from stack trace

    Returns:
        Full path to calling module file or None
    """
    return _find_external_caller_path()


def get_caller_info() -> tuple:
    """Detect calling module name, path, and branch from a single stack walk.

    Avoids the double-walk problem where get_calling_module() and
    get_calling_module_path() are called separately from different
    stack depths, potentially finding different external callers.

    Env var overrides (checked in order):
        AIPASS_LOG_NAME  — explicit module name override for any process
        AIPASS_BOT_ID    — set by telegram-bot@.service, mapped to bot_{id}

    Returns:
        (module_name, module_path, branch_name) — branch_name may be None
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


_AIPASS_PKG_ROOT = Path(__file__).resolve().parents[4]  # logging/ → handlers/ → apps/ → prax/ → aipass/
_SRC_ROOT = _AIPASS_PKG_ROOT.parent  # aipass/ → src/ (contains branches outside aipass namespace)
_REPO_ROOT = _SRC_ROOT.parent  # src/ → AIPass repo root


def _resolve_caller_path(module_path: str) -> Optional[Path]:
    """Resolve a caller's path without ever requiring a working directory.

    The stack hands back whatever ``__file__`` says, and that is not always an
    absolute path to a real file: a heredoc or an embedded interpreter reports
    ``<stdin>``, and a module imported via a relative entry reports a relative
    name. ``Path.resolve()`` on either of those reads the process working
    directory — so in a process whose cwd has been deleted this raised
    FileNotFoundError while prax was building the logger, one frame EARLIER than
    the config/load.py crash @memory reported on 2026-08-31 (their caller was a
    real absolute file, so their traceback walked past this line).

    Returns:
        The resolved path, or None when the caller cannot be located — which is
        an answer, not a failure. Branch detection is a routing hint; not knowing
        where the caller lives must never take down the caller's import.
    """
    # ONE guard, not two. An explicit ``startswith("<")`` check was written here
    # first and then removed: a pseudo-filename is not absolute, so is_absolute()
    # already refuses it, and a mutation dropping the "<" check killed no test —
    # correctly, because it could not. Two guards where one decides is a reader
    # believing both are load-bearing.
    candidate = Path(module_path) if module_path else None
    if candidate is None or not candidate.is_absolute():
        return None
    try:
        return candidate.resolve()
    except OSError as exc:
        logger.info("Caller path %s could not be resolved: %s", module_path, exc)
        return None


def detect_branch_from_path(module_path: str) -> Optional[str]:
    """Detect branch name from module file path

    The package structure is: .../src/aipass/{module}/apps/...
    Resolves relative to the aipass package root found via __file__.
    Also handles branches outside src/aipass/ (e.g., src/commons/).

    Examples:
        .../src/aipass/flow/apps/module.py → "flow"
        .../src/aipass/prax/apps/module.py → "prax"
        .../src/aipass/drone/apps/branch.py → "drone"
        .../src/commons/apps/module.py → "commons"

    Returns:
        Module/branch name (e.g., "flow") or None
    """
    path = _resolve_caller_path(module_path)
    if path is None:
        return None

    # Primary: src/aipass/{branch}/...
    try:
        relative = path.relative_to(_AIPASS_PKG_ROOT)
        # relative is like: flow/apps/module.py → parts[0] = "flow"
        if len(relative.parts) >= 2:
            branch = relative.parts[0]
            json_handler.log_operation(
                "introspection_resolved",
                {"module_path": module_path, "branch": branch},
                module_name="prax_introspection",
            )
            return branch
    except ValueError:
        logger.info("Path %s is not relative to aipass package root", module_path)

    # Fallback: src/{branch}/... for branches outside src/aipass/ (e.g., commons)
    try:
        relative = path.relative_to(_SRC_ROOT)
        if len(relative.parts) >= 2 and relative.parts[0] != "aipass":
            branch = relative.parts[0]
            json_handler.log_operation(
                "introspection_resolved",
                {"module_path": module_path, "branch": branch, "outside_aipass": True},
                module_name="prax_introspection",
            )
            return branch
    except ValueError:
        logger.info("Path %s is not relative to src root", module_path)

    return None


def detect_external_project(module_path: str) -> Optional[tuple]:
    """Detect if a module path belongs to an external project (outside AIPass repo).

    Walks up from the module path looking for a project root (.git or pyproject.toml).
    Returns the project name and root path if found and the path is outside the AIPass repo.

    Returns:
        (project_name, project_root) or None if path is inside AIPass or unresolvable
    """
    path = _resolve_caller_path(module_path)
    if path is None:
        return None

    # If the path is inside the AIPass repo, it's not external
    try:
        path.relative_to(_REPO_ROOT)
        return None
    except ValueError:
        logger.info("Path %s is external to AIPass repo", module_path)

    # Also check AIPASS_CALLER_CWD for cross-project dispatch
    import os

    caller_cwd = os.environ.get("AIPASS_CALLER_CWD")
    search_path = path if path.exists() else (Path(caller_cwd) if caller_cwd else None)

    if not search_path:
        return None

    # Walk up to find project root
    for candidate in [search_path] + list(search_path.parents):
        if (candidate / ".git").exists() or (candidate / "pyproject.toml").exists():
            project_name = candidate.name.lower().replace(" ", "_").replace("-", "_")
            return (project_name, candidate)

    return None
