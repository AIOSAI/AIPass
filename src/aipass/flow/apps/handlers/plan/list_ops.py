# =================== AIPass ====================
# Name: list_ops.py
# Description: Plan Listing Implementation Handler
# Version: 2.0.0
# Created: 2026-03-08
# Modified: 2026-03-17
# =============================================

"""
Plan Listing Operations Handler

Implements plan listing business logic, extracted from list_plans module.
Plan-type-agnostic: loads ALL per-type registries and merges plans for display.

Usage:
    from aipass.flow.apps.handlers.plan.list_ops import list_plans_impl
"""

from typing import Dict, Any, Tuple

from aipass.prax import logger
from aipass.flow.apps.handlers.json import json_handler

# =============================================
# CONFIGURATION
# =============================================

MODULE_NAME = "list_plans"


def _get_all_registry_info() -> Tuple[list[str], Dict[str, str]]:
    """Return per-type registry filenames and a registry_file -> prefix map.

    Returns:
        (registry_files, prefix_map) where prefix_map maps e.g.
        "dplan_registry.json" -> "DPLAN".  Empty list means caller
        should fall back to the default registry.
    """
    try:
        from aipass.flow.apps.handlers.template.plan_type_loader import discover_plan_types  # type: ignore[import-not-found]

        files: list[str] = []
        prefix_map: Dict[str, str] = {}
        for _key, config in discover_plan_types().items():
            rf = config.get("registry_file")
            if rf:
                prefix_map[rf] = config.get("prefix", "FPLAN")
                if rf not in files:
                    files.append(rf)
        if files:
            return files, prefix_map
    except Exception as e:
        logger.warning(f"[{MODULE_NAME}] Failed to discover plan types for registry info: {e}")
    return [], {}  # empty means caller should fall back to default


# =============================================
# LIST PLANS IMPLEMENTATION
# =============================================


def list_plans_impl(
    filter_type: str = "open",
    # Dependencies injected from module
    load_registry: Any = None,
    get_registry_statistics: Any = None,
    format_plans_list: Any = None,
    format_statistics_summary: Any = None,
) -> Dict[str, Any]:
    """
    Implement plan listing workflow across all plan-type registries.

    Args:
        filter_type: Filter plans by status ("open", "closed", "all")
        load_registry: Registry loader function (injected from module)
        get_registry_statistics: Statistics function (injected from module)
        format_plans_list: Plan list formatter (injected from module)
        format_statistics_summary: Stats formatter (injected from module)

    Returns:
        Dict with keys: success (bool), formatted_list (str), formatted_stats (str),
        empty (bool), filter_type (str)
    """
    try:
        # STEP 1: Load ALL per-type registries and merge plans
        merged_plans: Dict[str, Any] = {}
        reg_files, reg_prefix_map = _get_all_registry_info()

        if reg_files:
            for reg_file in reg_files:
                try:
                    registry = load_registry(registry_file=reg_file)
                    source_prefix = reg_prefix_map.get(reg_file, "FPLAN")
                    for plan_num, plan_info in registry.get("plans", {}).items():
                        # Tag each plan with its source prefix and original number for display
                        plan_info["_source_prefix"] = source_prefix
                        plan_info["_plan_num"] = plan_num
                        # Use prefix-qualified key to avoid collisions across registries
                        merge_key = f"{source_prefix}-{plan_num}"
                        merged_plans[merge_key] = plan_info
                except Exception as e:
                    logger.warning(f"[{MODULE_NAME}] Failed to load registry '{reg_file}' for plan listing: {e}")
                    continue
        else:
            # Fallback: load default registry
            registry = load_registry()
            merged_plans = registry.get("plans", {})

        # Build a synthetic merged registry for statistics
        merged_registry: Dict[str, Any] = {"plans": merged_plans}

        if not merged_plans:
            logger.info(f"[{MODULE_NAME}] No plans in any registry")
            return {
                "success": True,
                "formatted_list": "",
                "formatted_stats": "",
                "empty": True,
                "filter_type": filter_type,
            }

        # STEP 2: Determine filter
        if filter_type == "all":
            filter_status = None
        else:
            filter_status = filter_type  # "open" or "closed"

        # STEP 3: Format plans list
        formatted_list = format_plans_list(merged_plans, filter_status)

        # STEP 4: Get and format statistics
        stats = get_registry_statistics(merged_registry)
        formatted_stats = format_statistics_summary(stats)

        # STEP 5: Log success
        logger.info(f"[{MODULE_NAME}] Listed plans (filter: {filter_type})")
        json_handler.log_operation(
            "plans_listed", {"filter_type": filter_type, "count": len(merged_plans), "success": True}
        )

        return {
            "success": True,
            "formatted_list": formatted_list,
            "formatted_stats": formatted_stats,
            "empty": False,
            "filter_type": filter_type,
        }

    except BrokenPipeError:
        logger.info(f"[{MODULE_NAME}] Broken pipe (stdout closed early)")
        return {
            "success": True,
            "formatted_list": "",
            "formatted_stats": "",
            "empty": True,
            "filter_type": filter_type,
        }

    except Exception as e:
        error_msg = f"Error listing plans: {e}"
        logger.error(f"[{MODULE_NAME}] {error_msg}")
        return {
            "success": False,
            "error": error_msg,
            "formatted_list": "",
            "formatted_stats": "",
            "empty": True,
            "filter_type": filter_type,
        }
