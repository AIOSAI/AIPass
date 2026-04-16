# =================== AIPass ====================
# Name: introspection.py
# Description: Stack Introspection
# Version: 1.0.0
# Created: 2025-11-10
# Modified: 2026-03-09
# =============================================

"""
PRAX Logging Introspection

Stack introspection for detecting calling modules and branch paths.
Used by logger_setup.py to route logs to correct files.
"""

import logging

logger = logging.getLogger(__name__)
from pathlib import Path
from typing import Optional

from aipass.prax.apps.handlers.json import json_handler

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

    Returns:
        (module_name, module_path, branch_name) — branch_name may be None
    """
    caller_path = _find_external_caller_path()
    if not caller_path:
        return ("unknown_module", None, None)
    module_name = Path(caller_path).stem
    branch = detect_branch_from_path(caller_path)
    return (module_name, caller_path, branch)


_AIPASS_PKG_ROOT = Path(__file__).resolve().parents[4]  # logging/ → handlers/ → apps/ → prax/ → aipass/
_SRC_ROOT = _AIPASS_PKG_ROOT.parent  # aipass/ → src/ (contains branches outside aipass namespace)


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
    if not module_path:
        return None

    path = Path(module_path).resolve()

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
