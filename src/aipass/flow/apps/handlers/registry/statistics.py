# =================== AIPass ====================
# Name: statistics.py
# Description: Registry Statistics Handler
# Version: 1.0.0
# Created: 2025-11-07
# Modified: 2026-10-17
# =============================================

"""
Registry Statistics Handler
"""

from datetime import datetime, timezone
from typing import Dict, Any

from aipass.flow.apps.handlers.json import json_handler

from aipass.flow.apps.handlers.repo_root import module_file

_PKG_ROOT = module_file(__file__).parents[4]


def get_registry_statistics(registry: Dict[str, Any]) -> Dict[str, Any]:
    """Calculate statistics from registry"""
    plans = registry.get("plans", {})

    open_count = sum(1 for plan in plans.values() if plan.get("status") == "open")
    closed_count = sum(1 for plan in plans.values() if plan.get("status") == "closed")
    other_count = len(plans) - open_count - closed_count

    result = {
        "total_plans": len(plans),
        "open_plans": open_count,
        "closed_plans": closed_count,
        "other_plans": other_count,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    json_handler.log_operation(
        "registry_statistics_calculated",
        {
            "total_plans": len(plans),
            "open_plans": open_count,
            "closed_plans": closed_count,
            "success": True,
        },
    )

    return result
