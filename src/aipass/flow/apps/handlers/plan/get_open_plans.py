# =================== AIPass ====================
# Name: get_open_plans.py
# Description: Get Open Plans Handler
# Version: 1.0.0
# Created: 2025-11-21
# Modified: 2026-11-15
# =============================================

"""
Get Open Plans Handler
"""

from typing import List, Tuple, Dict, Any
from pathlib import Path

_PKG_ROOT = Path(__file__).resolve().parents[4]

MODULE_NAME = "get_open_plans"

from aipass.flow.apps.handlers.registry.load_registry import load_registry
from aipass.flow.apps.handlers.json import json_handler


def _get_all_registry_files() -> List[str]:
    """Return per-type registry filenames via plan-type discovery; raises when it finds none."""
    from aipass.flow.apps.handlers.template.plan_type_loader import discover_plan_types  # type: ignore[import-not-found]

    files: List[str] = []
    for _key, config in discover_plan_types().items():
        rf = config.get("registry_file")
        if rf and rf not in files:
            files.append(rf)
    if not files:
        raise RuntimeError(f"[{MODULE_NAME}] plan-type discovery found no registry files")
    return files


def get_open_plans() -> List[Tuple[str, Dict[str, Any]]]:
    """Open plans from every per-type registry; an unreadable registry raises."""
    open_plans: List[Tuple[str, Dict[str, Any]]] = []
    for reg_file in _get_all_registry_files():
        registry = load_registry(registry_file=reg_file)
        open_plans.extend(
            (plan_num, plan_info)
            for plan_num, plan_info in registry.get("plans", {}).items()
            if plan_info.get("status") == "open"
        )

    json_handler.log_operation("open_plans_retrieved", {"count": len(open_plans)})
    return open_plans
