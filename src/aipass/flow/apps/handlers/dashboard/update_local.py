# =================== AIPass ====================
# Name: update_local.py
# Description: Update Dashboard Local Handler
# Version: 1.0.0
# Created: 2025-11-21
# Modified: 2025-11-21
# =============================================

"""
Update Dashboard Local Handler

Updates Flow's DASHBOARD.local.json file with plan summaries from fplan_registry.json.

This handler follows the 3-tier logging standard:
- NO Prax imports
- NO logging calls
- Pure handler - just read, process, write
- Returns boolean for success/failure

Flow's Dual Role:
- Flow is both a working branch (has its own plans) AND a service provider
- This handler manages Flow's OWN plans in DASHBOARD.local.json
- Flow's section is 'flow_plans', other branches manage their own sections
- Key principle: Each branch touches ONLY its own section, respects others

Data Flow:
1. Read fplan_registry.json (source of truth)
2. Extract Flow's plans only (location='flow')
3. Partition into active (status='open') and recently_closed (status='closed', last 5)
4. Calculate statistics (active_count, total_closed, next_number)
5. Read existing DASHBOARD.local.json if exists
6. Update ONLY the 'flow_plans' section
7. Preserve ALL other sections (other branches manage their own)
8. Write back to DASHBOARD.local.json

Structure:
{
  "branch": "FLOW",
  "last_updated": "ISO timestamp",
  "flow_plans": {
    "active": [
      {
        "plan_id": "FPLAN-0021",
        "subject": "...",
        "status": "open",
        "created": "ISO timestamp",
        "file_path": "...",
        "location": "flow"
      }
    ],
    "recently_closed": [ /* last 5 closed plans */ ],
    "statistics": {
      "active_count": 3,
      "total_closed": 6,
      "next_number": 24
    }
  }
  // Other sections preserved here
}

Usage:
    from aipass.flow.apps.handlers.dashboard.update_local import update_dashboard_local

    success = update_dashboard_local()
    # Returns True on success, False on failure
"""

import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from aipass.flow.apps.handlers.json import json_handler
from aipass.prax.apps.modules.logger import system_logger as logger

# INFRASTRUCTURE IMPORT PATTERN
_PKG_ROOT = Path(__file__).resolve().parents[4]
FLOW_ROOT = _PKG_ROOT / "flow"

# =============================================
# CONFIGURATION
# =============================================

REGISTRY_FILE = FLOW_ROOT / "flow_json" / "fplan_registry.json"
DASHBOARD_FILE = FLOW_ROOT / "DASHBOARD.local.json"

# =============================================
# HELPER FUNCTIONS
# =============================================

def _read_registry() -> Optional[Dict[str, Any]]:
    """
    Read fplan_registry.json.

    Returns:
        Registry dict or None if error
    """
    try:
        if not REGISTRY_FILE.exists():
            return None
        with open(REGISTRY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as exc:
        logger.warning("Failed to read fplan registry '%s': %s", REGISTRY_FILE, exc)
        return None


def _extract_flow_plans(registry: Dict[str, Any]) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Extract Flow's plans from registry and partition into active and closed.

    Args:
        registry: Registry data

    Returns:
        Tuple of (active_plans, closed_plans)
    """
    plans = registry.get("plans", {})
    active = []
    closed = []

    for plan_num, plan_data in plans.items():
        # Only include Flow's own plans (location contains 'flow')
        location = plan_data.get("location", "")
        if "flow" not in location.lower():
            continue

        # Build plan entry
        plan_id = f"FPLAN-{plan_num}"
        entry = {
            "plan_id": plan_id,
            "subject": plan_data.get("subject", ""),
            "status": plan_data.get("status", "unknown"),
            "file_path": plan_data.get("file_path", ""),
            "location": location
        }

        # Add timestamps
        if "created" in plan_data:
            entry["created"] = plan_data["created"]
        if "closed" in plan_data:
            entry["closed"] = plan_data["closed"]
            entry["closed_reason"] = plan_data.get("closed_reason", "")

        # Partition by status
        if plan_data.get("status") == "closed":
            closed.append(entry)
        else:
            active.append(entry)

    # Sort by plan_id for consistency
    active.sort(key=lambda x: x["plan_id"])
    closed.sort(key=lambda x: x["plan_id"])

    return active, closed


def _calculate_statistics(active: List[Dict[str, Any]], closed: List[Dict[str, Any]],
                          registry: Dict[str, Any]) -> Dict[str, int]:
    """
    Calculate statistics for Flow's plans.

    Args:
        active: List of active plans
        closed: List of closed plans
        registry: Registry data (for next_number)

    Returns:
        Statistics dict
    """
    return {
        "active_count": len(active),
        "total_closed": len(closed),
        "next_number": registry.get("next_number", 1)
    }


def _read_existing_dashboard() -> Dict[str, Any]:
    """
    Read existing DASHBOARD.local.json if it exists.

    Returns:
        Existing dashboard data or empty dict
    """
    try:
        if not DASHBOARD_FILE.exists():
            return {}
        with open(DASHBOARD_FILE, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            # Handle old markdown format gracefully
            if not content or content.startswith("⚠️"):
                return {}
            # Parse the JSON content we just read
            return json.loads(content)
    except Exception as exc:
        logger.warning("Failed to read existing dashboard '%s': %s", DASHBOARD_FILE, exc)
        return {}


def _build_dashboard_data(active: List[Dict[str, Any]], closed: List[Dict[str, Any]],
                          statistics: Dict[str, int],
                          existing: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build updated dashboard data with Flow's section.

    Args:
        active: Active plans
        closed: Closed plans
        statistics: Statistics dict
        existing: Existing dashboard data

    Returns:
        Updated dashboard data
    """
    # Start with existing data to preserve other sections
    dashboard = existing.copy()

    # Update Flow's section
    dashboard["branch"] = "FLOW"
    dashboard["last_updated"] = datetime.now(timezone.utc).isoformat()
    dashboard["flow_plans"] = {
        "active": active,
        "recently_closed": closed[-5:] if len(closed) > 0 else [],  # Last 5
        "statistics": statistics
    }

    return dashboard


def _write_dashboard(dashboard: Dict[str, Any]) -> bool:
    """
    Write dashboard data to DASHBOARD.local.json.

    Args:
        dashboard: Dashboard data

    Returns:
        True if successful, False otherwise
    """
    try:
        DASHBOARD_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(DASHBOARD_FILE, 'w', encoding='utf-8') as f:
            json.dump(dashboard, f, indent=2, ensure_ascii=False)
        return True
    except Exception as exc:
        logger.error("Failed to write dashboard '%s': %s", DASHBOARD_FILE, exc)
        return False


# =============================================
# HANDLER FUNCTION
# =============================================

def update_dashboard_local() -> bool:
    """
    Update DASHBOARD.local.json with Flow's plan summaries from registry.

    This is the main handler function that:
    1. Reads fplan_registry.json
    2. Extracts Flow's plans (location='flow')
    3. Partitions into active and closed
    4. Updates ONLY the 'flow_plans' section of DASHBOARD.local.json
    5. Preserves all other sections (other branches manage their own)

    Returns:
        True if successful, False on any error

    Example:
        >>> from aipass.flow.apps.handlers.dashboard.update_local import update_dashboard_local
        >>> success = update_dashboard_local()
        >>> print(f"Dashboard update: {success}")
    """
    # Read registry
    registry = _read_registry()
    if registry is None:
        return False

    # Extract Flow's plans
    active, closed = _extract_flow_plans(registry)

    # Calculate statistics
    statistics = _calculate_statistics(active, closed, registry)

    # Read existing dashboard (to preserve other sections)
    existing = _read_existing_dashboard()

    # Build updated dashboard
    dashboard = _build_dashboard_data(active, closed, statistics, existing)

    # Write dashboard
    result = _write_dashboard(dashboard)

    if result:
        json_handler.log_operation("dashboard_local_updated", {
            "active_count": statistics["active_count"],
            "total_closed": statistics["total_closed"],
            "success": True,
        })

    return result
