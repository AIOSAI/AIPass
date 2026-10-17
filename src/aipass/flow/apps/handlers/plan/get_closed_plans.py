# =================== AIPass ====================
# Name: get_closed_plans.py
# Description: Get Closed Plans Handler
# Version: 1.0.0
# Created: 2025-11-21
# Modified: 2026-10-17
# =============================================

"""Get Closed Plans Handler"""

from typing import List, Tuple, Dict, Any

from aipass.prax.apps.modules.logger import system_logger as logger

from aipass.flow.apps.handlers.repo_root import module_file

_PKG_ROOT = module_file(__file__).parents[4]

from aipass.flow.apps.handlers.registry.load_registry import load_registry
from aipass.flow.apps.handlers.json import json_handler

MODULE_NAME = "get_closed_plans"


def _get_all_registry_files() -> List[str]:
    """Return per-type registry filenames via plan-type discovery.

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


def get_closed_plans() -> List[Tuple[str, Dict[str, Any]]]:
    """Get all closed plans from ALL discovered registries

    Returns [(plan_num, plan_info), ...]; a registry that fails to load is skipped, not raised.
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
