# =================== AIPass ====================
# Name: statistics.py
# Description: Registry Statistics Handler
# Version: 1.0.0
# Created: 2025-11-07
# Modified: 2025-11-07
# =============================================

"""
Registry Statistics Handler

Calculates statistics from the Flow PLAN registry.

Features:
- Counts total plans
- Counts plans by status (open, closed, etc.)
- Provides timestamp metadata
- Reusable across Flow modules

Usage:
    from aipass.flow.apps.handlers.registry.statistics import get_registry_statistics
    from aipass.flow.apps.handlers.registry.load_registry import load_registry

    registry = load_registry()
    stats = get_registry_statistics(registry)
    # stats contains: total_plans, open_plans, closed_plans, etc.
"""

from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any

from aipass.flow.apps.handlers.json import json_handler

# INFRASTRUCTURE IMPORT PATTERN
_PKG_ROOT = Path(__file__).resolve().parents[4]

# =============================================
# HANDLER FUNCTION
# =============================================

def get_registry_statistics(registry: Dict[str, Any]) -> Dict[str, Any]:
    """Calculate statistics from registry

    Args:
        registry: Registry dictionary containing plans data

    Returns:
        Dict containing:
        - total_plans: Total number of plans in registry
        - open_plans: Number of plans with status="open"
        - closed_plans: Number of plans with status="closed"
        - other_plans: Number of plans with other statuses
        - timestamp: ISO timestamp when statistics were calculated
    """
    plans = registry.get("plans", {})

    # Count plans by status
    open_count = sum(1 for plan in plans.values() if plan.get("status") == "open")
    closed_count = sum(1 for plan in plans.values() if plan.get("status") == "closed")
    other_count = len(plans) - open_count - closed_count

    result = {
        "total_plans": len(plans),
        "open_plans": open_count,
        "closed_plans": closed_count,
        "other_plans": other_count,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

    json_handler.log_operation("registry_statistics_calculated", {
        "total_plans": len(plans),
        "open_plans": open_count,
        "closed_plans": closed_count,
        "success": True,
    })

    return result
