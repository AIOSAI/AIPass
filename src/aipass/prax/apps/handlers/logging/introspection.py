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

from pathlib import Path
from typing import Optional

from aipass.prax.apps.handlers.json import json_handler

def get_calling_module() -> str:
    """Detect calling module from stack trace

    Returns:
        Module name (e.g., 'drone', 'flow', 'cortex') or 'unknown_module'
    """
    import inspect

    frame = inspect.currentframe()
    try:
        # Walk up the stack to find the calling module
        current_frame = frame
        frame_count = 0
        while current_frame and frame_count < 10:  # Limit to prevent infinite loop
            current_frame = current_frame.f_back
            frame_count += 1
            if current_frame:
                module_path = current_frame.f_globals.get('__file__', '')
                if module_path and module_path != __file__:
                    # Skip any frame that's from prax internal files
                    if ('/prax/apps/modules/logger.py' not in module_path and
                        '/prax/apps/handlers/' not in module_path and
                        'prax_logger.py' not in module_path and
                        'prax_handlers.py' not in module_path):
                        module_name = Path(module_path).stem
                        return module_name
        return 'unknown_module'
    finally:
        del frame

def get_calling_module_path() -> Optional[str]:
    """Detect calling module path from stack trace

    Returns:
        Full path to calling module file or None
    """
    import inspect

    frame = inspect.currentframe()
    try:
        # Walk up the stack to find the calling module
        current_frame = frame
        frame_count = 0
        while current_frame and frame_count < 10:
            current_frame = current_frame.f_back
            frame_count += 1
            if current_frame:
                module_path = current_frame.f_globals.get('__file__', '')
                if module_path and module_path != __file__:
                    # Skip any frame that's from prax internal files
                    if ('/prax/apps/modules/logger.py' not in module_path and
                        '/prax/apps/handlers/' not in module_path and
                        'prax_logger.py' not in module_path and
                        'prax_handlers.py' not in module_path):
                        return module_path
        return None
    finally:
        del frame

_AIPASS_PKG_ROOT = Path(__file__).resolve().parents[4]  # logging/ → handlers/ → apps/ → prax/ → aipass/

def detect_branch_from_path(module_path: str) -> Optional[str]:
    """Detect branch name from module file path

    The package structure is: .../src/aipass/{module}/apps/...
    Resolves relative to the aipass package root found via __file__.

    Examples:
        .../src/aipass/flow/apps/module.py → "flow"
        .../src/aipass/prax/apps/module.py → "prax"
        .../src/aipass/drone/apps/branch.py → "drone"

    Returns:
        Module/branch name (e.g., "flow") or None
    """
    if not module_path:
        return None

    try:
        path = Path(module_path).resolve()
        relative = path.relative_to(_AIPASS_PKG_ROOT)
        # relative is like: flow/apps/module.py → parts[0] = "flow"
        if len(relative.parts) >= 2:
            branch = relative.parts[0]
            json_handler.log_operation("introspection_resolved", {"module_path": module_path, "branch": branch})
            return branch
    except ValueError:
        pass

    return None
