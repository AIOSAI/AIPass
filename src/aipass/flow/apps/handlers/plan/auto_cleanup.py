# =================== AIPass ====================
# Name: auto_cleanup.py
# Description: Plan Auto-Cleanup Handler
# Version: 0.2.0
# Created: 2025-11-15
# Modified: 2025-11-15
# =============================================

"""
Plan Auto-Cleanup Handler

Auto-closes open plans whose files no longer exist on disk.
Scans registry for orphaned plans and updates their status.
"""

from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, Tuple

from aipass.flow.apps.handlers.json import json_handler

# Infrastructure
from aipass.flow.apps.handlers.repo_root import module_file

_PKG_ROOT = module_file(__file__).parents[4]


def auto_close_orphaned_plans(registry: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
    """
    Auto-close open plans whose files no longer exist

    Scans all plans with status="open", checks if file_path exists on disk,
    and auto-closes any plans with missing files. Updates registry entries
    with closed status, timestamp, and reason.

    Args:
        registry: Flow registry dictionary with 'plans' section

    Returns:
        Tuple of (modified_registry, count_of_closed_plans)

    Side effects:
        Modifies registry["plans"][num] entries in-place

    Example:
        >>> registry = load_registry()
        >>> registry, count = auto_close_orphaned_plans(registry)
        >>> if count > 0:
        ...     save_registry(registry)
    """
    auto_closed_count = 0

    for num, info in registry.get("plans", {}).items():
        if info.get("status") == "open":
            plan_file = Path(info.get("file_path", ""))

            if plan_file and not plan_file.exists():
                # Auto-close missing plan
                info["status"] = "closed"
                info["closed"] = datetime.now(timezone.utc).isoformat()
                info["closed_reason"] = "auto_closed_missing_file"
                auto_closed_count += 1

    if auto_closed_count > 0:
        json_handler.log_operation("orphaned_plans_auto_closed", {"count": auto_closed_count, "success": True})
    return registry, auto_closed_count
