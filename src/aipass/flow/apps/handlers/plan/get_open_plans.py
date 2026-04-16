# =================== AIPass ====================
# Name: get_open_plans.py
# Description: Get Open Plans Handler
# Version: 1.0.0
# Created: 2025-11-21
# Modified: 2025-11-21
# =============================================

"""
Get Open Plans Handler

Returns list of open plans from registry.

Usage:
    from aipass.flow.apps.handlers.plan.get_open_plans import get_open_plans
    open_plans = get_open_plans()
"""

from pathlib import Path
from typing import List, Tuple, Dict, Any

from aipass.prax import logger

# INFRASTRUCTURE IMPORT PATTERN
_PKG_ROOT = Path(__file__).resolve().parents[4]

MODULE_NAME = "get_open_plans"

# Internal: Registry handler
from aipass.flow.apps.handlers.registry.load_registry import load_registry
from aipass.flow.apps.handlers.json import json_handler

# =============================================
# HANDLER FUNCTION
# =============================================


def _get_all_registry_files() -> List[str]:
    """Return per-type registry filenames via plan-type discovery."""
    try:
        from aipass.flow.apps.handlers.template.plan_type_loader import discover_plan_types  # type: ignore[import-not-found]

        files: List[str] = []
        for _key, config in discover_plan_types().items():
            rf = config.get("registry_file")
            if rf and rf not in files:
                files.append(rf)
        if files:
            return files
    except Exception as e:
        logger.warning(f"[{MODULE_NAME}] Failed to discover plan types for registry files: {e}")
    return []


def get_open_plans() -> List[Tuple[str, Dict[str, Any]]]:
    """
    Get all open plans from ALL per-type registries.

    Returns:
        List of tuples: [(plan_num, plan_info), ...]
        Empty list if no open plans found
    """
    open_plans: List[Tuple[str, Dict[str, Any]]] = []
    reg_files = _get_all_registry_files()

    if reg_files:
        for reg_file in reg_files:
            try:
                registry = load_registry(registry_file=reg_file)
                open_plans.extend(
                    (plan_num, plan_info)
                    for plan_num, plan_info in registry.get("plans", {}).items()
                    if plan_info.get("status") == "open"
                )
            except Exception as e:
                logger.warning(f"[{MODULE_NAME}] Failed to load registry '{reg_file}' for open plan scan: {e}")
                continue
    else:
        # Fallback: load default registry
        registry = load_registry()
        open_plans = [
            (plan_num, plan_info)
            for plan_num, plan_info in registry.get("plans", {}).items()
            if plan_info.get("status") == "open"
        ]

    json_handler.log_operation("open_plans_retrieved", {"count": len(open_plans)})
    return open_plans
