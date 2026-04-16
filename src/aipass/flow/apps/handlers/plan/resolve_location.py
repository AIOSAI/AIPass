# =================== AIPass ====================
# Name: resolve_location.py
# Description: Plan Location Resolution Handler
# Version: 2.0.0
# Created: 2025-11-29
# Modified: 2026-03-17
# =============================================

"""
Plan Location Resolution Handler

Resolves plan locations using the CALLER's working directory, not flow's.
Drone sets AIPASS_CALLER_CWD env var before invoking flow, so relative
paths (like ".") resolve to where the user actually is.

@ symbols are pre-resolved by Drone before Flow receives args.
"""

import os
from pathlib import Path
from typing import Tuple

from aipass.flow.apps.handlers.json import json_handler


def _get_caller_cwd() -> Path:
    """Return the caller's working directory.

    Drone passes this via AIPASS_CALLER_CWD env var. Falls back to
    Path.cwd() for direct invocation (testing, standalone).
    """
    caller_cwd = os.environ.get("AIPASS_CALLER_CWD")
    if caller_cwd:
        return Path(caller_cwd)
    return Path.cwd()


def resolve_plan_location(location: str | None, ecosystem_root: Path) -> Tuple[bool, Path, str]:
    """
    Resolve plan location relative to the CALLER's directory.

    Plans are created where the caller is, not where flow lives.
    Drone passes AIPASS_CALLER_CWD so "." resolves to the caller's CWD.

    Args:
        location: Target location (absolute/relative path, ".", or None)
        ecosystem_root: Root directory (kept for API compatibility)

    Returns:
        Tuple of (success, resolved_path, error_message)
    """
    caller_cwd = _get_caller_cwd()

    if location:
        loc_path = Path(location)
        if loc_path.is_absolute():
            target_dir = loc_path.resolve()
        else:
            # Resolve relative paths against CALLER's CWD, not flow's
            target_dir = (caller_cwd / loc_path).resolve()
    else:
        # No location provided — use caller's CWD
        target_dir = caller_cwd

    # Validate directory exists
    if not target_dir.exists():
        return False, caller_cwd, f"Directory {target_dir} does not exist"

    json_handler.log_operation("location_resolved", {"input": location, "resolved": str(target_dir), "success": True})
    return True, target_dir, ""
