# =================== AIPass ====================
# Name: resolve_location.py
# Description: Plan Location Resolution Handler
# Version: 2.0.0
# Created: 2025-11-29
# Modified: 2026-10-17
# =============================================

"""Plan Location Resolution Handler"""

import os
from pathlib import Path
from typing import Tuple

from aipass.flow.apps.handlers.json import json_handler


def _get_caller_cwd() -> Path:
    """Return the caller's working directory.

    Drone sets AIPASS_CALLER_CWD so paths resolve where the user is, not in flow; Path.cwd() without drone.
    """
    caller_cwd = os.environ.get("AIPASS_CALLER_CWD")
    if caller_cwd:
        return Path(caller_cwd)
    return Path.cwd()


def resolve_plan_location(location: str | None, ecosystem_root: Path) -> Tuple[bool, Path, str]:
    """Resolve plan location relative to the CALLER's directory.

    ecosystem_root is unused, kept for API compatibility.
    """
    caller_cwd = _get_caller_cwd()

    if location:
        loc_path = Path(location)
        if loc_path.is_absolute():
            target_dir = loc_path.resolve()
        else:
            target_dir = (caller_cwd / loc_path).resolve()
    else:
        target_dir = caller_cwd

    if not target_dir.exists():
        return False, caller_cwd, f"Directory {target_dir} does not exist"

    json_handler.log_operation("location_resolved", {"input": location, "resolved": str(target_dir), "success": True})
    return True, target_dir, ""
