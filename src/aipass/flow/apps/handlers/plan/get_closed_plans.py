# =================== AIPass ====================
# Name: get_closed_plans.py
# Description: Get Closed Plans Handler
# Version: 1.0.0
# Created: 2025-11-21
# Modified: 2025-11-21
# =============================================

"""
Get Closed Plans Handler

Returns list of closed plans from registry.

Usage:
    from aipass.flow.apps.handlers.plan.get_closed_plans import get_closed_plans
    closed_plans = get_closed_plans()
"""

from pathlib import Path
from typing import List, Tuple, Dict, Any

from aipass.prax.apps.modules.logger import system_logger as logger

# INFRASTRUCTURE IMPORT PATTERN
_PKG_ROOT = Path(__file__).resolve().parents[4]

# Internal: Registry handler
from aipass.flow.apps.handlers.registry.load_registry import load_registry
from aipass.flow.apps.handlers.json import json_handler

# =============================================
# MULTI-REGISTRY DISCOVERY
# =============================================

MODULE_NAME = "get_closed_plans"


def _get_all_registry_files() -> List[str]:
    """Return per-type registry filenames via plan-type discovery.

    Uses the same pattern as mbank/process.py to discover all plan-type
    registries (e.g. fplan_registry.json, dplan_registry.json).
    Falls back to the default fplan_registry.json if discovery fails.
    """
    try:
        from aipass.flow.apps.handlers.template.plan_type_loader import discover_plan_types

        files: List[str] = []
        for _key, config in discover_plan_types().items():
            rf = config.get("registry_file")
            if rf and rf not in files:
                files.append(rf)
        if files:
            return files
    except Exception as exc:
        logger.warning("[%s] Failed to discover plan types, falling back to default registry: %s", MODULE_NAME, exc)
    return ["fplan_registry.json"]


# =============================================
# HANDLER FUNCTION
# =============================================


def get_closed_plans() -> List[Tuple[str, Dict[str, Any]]]:
    """
    Get all closed plans from ALL discovered registries

    Returns:
        List of tuples: [(plan_num, plan_info), ...]
        Empty list if no closed plans found

    Example:
        >>> plans = get_closed_plans()
        >>> for plan_num, plan_info in plans:
        ...     print(f"PLAN{plan_num}: {plan_info['subject']}")
    """
    closed_plans: List[Tuple[str, Dict[str, Any]]] = []

    for reg_file in _get_all_registry_files():
        try:
            registry = load_registry(registry_file=reg_file)
        except Exception as exc:
            logger.warning("[%s] Failed to load registry '%s': %s", MODULE_NAME, reg_file, exc)
            continue

        for plan_num, plan_info in registry.get("plans", {}).items():
            if plan_info.get("status") == "closed":
                closed_plans.append((plan_num, plan_info))

    json_handler.log_operation("closed_plans_retrieved", {"count": len(closed_plans)})
    return closed_plans
