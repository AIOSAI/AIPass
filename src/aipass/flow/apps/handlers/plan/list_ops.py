# =================== AIPass ====================
# Name: list_ops.py
# Description: Plan Listing Implementation Handler
# Version: 2.1.0
# Created: 2026-03-08
# Modified: 2026-10-26
# =============================================

"""
Plan Listing Operations Handler
"""

from pathlib import Path
from typing import Dict, Any, Tuple

from aipass.prax import logger
from aipass.flow.apps.handlers.json import json_handler
from aipass.flow.apps.handlers.plan.project_scope import caller_project_root, describe_project, find_project_root
from aipass.flow.apps.handlers.repo_root import find_repo_root

MODULE_NAME = "list_plans"

# "Not injected" (resolve it) vs None, "stands in no project" (refuse the listing).
_UNSET = object()


def _get_all_registry_info() -> Tuple[list[str], Dict[str, str]]:
    """Return per-type registry filenames and a registry_file -> prefix map.

    An empty file list means the caller must fall back to the default registry.
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


def list_plans_impl(
    filter_type: str = "open",
    load_registry: Any = None,
    get_registry_statistics: Any = None,
    format_plans_list: Any = None,
    format_statistics_summary: Any = None,
    caller_project: Any = _UNSET,
    host_project: Any = _UNSET,
) -> Dict[str, Any]:
    """
    Implement plan listing workflow across all plan-type registries.

    The callables are injected by the list_plans module; filter_type is "open", "closed" or "all".
    Rows are the caller's project's; only "all" from the host project's seat lists every project.
    """
    try:
        if caller_project is _UNSET:
            caller_project = caller_project_root()
        if host_project is _UNSET:
            host_project = find_repo_root(caller=MODULE_NAME)
        if caller_project is None:
            return {
                "success": False,
                "error": "you stand in no project (no project register above your directory); nothing listed",
                "formatted_list": "",
                "formatted_stats": "",
                "empty": True,
                "filter_type": filter_type,
            }
        whole_fleet = filter_type == "all" and caller_project == host_project

        merged_plans: Dict[str, Any] = {}
        reg_files, reg_prefix_map = _get_all_registry_info()

        if reg_files:
            for reg_file in reg_files:
                try:
                    registry = load_registry(registry_file=reg_file)
                    source_prefix = reg_prefix_map.get(reg_file, "FPLAN")
                    for plan_num, plan_info in registry.get("plans", {}).items():
                        plan_info["_source_prefix"] = source_prefix
                        plan_info["_plan_num"] = plan_num
                        # Plan numbers repeat across registries; the prefix keeps keys unique.
                        merge_key = f"{source_prefix}-{plan_num}"
                        merged_plans[merge_key] = plan_info
                except Exception as e:
                    logger.warning(f"[{MODULE_NAME}] Failed to load registry '{reg_file}' for plan listing: {e}")
                    continue
        else:
            registry = load_registry()
            merged_plans = registry.get("plans", {})

        if not whole_fleet:
            cache: Dict[Path, Any] = {}
            merged_plans = {
                key: info
                for key, info in merged_plans.items()
                if info.get("location") and find_project_root(Path(info["location"]), cache) == caller_project
            }

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

        if filter_type == "all":
            filter_status = None
        else:
            filter_status = filter_type  # "open" or "closed"

        scope = "fleet" if whole_fleet else describe_project(caller_project)
        formatted_list = format_plans_list(merged_plans, filter_status, scope=scope)

        stats = get_registry_statistics(merged_registry)
        formatted_stats = format_statistics_summary(stats)

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
