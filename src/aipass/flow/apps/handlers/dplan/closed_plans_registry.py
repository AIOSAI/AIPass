# =================== AIPass ====================
# Name: closed_plans_registry.py
# Description: CLOSED_PLANS.local.json file operations
# Version: 1.0.0
# Created: 2026-03-08
# Modified: 2026-03-08
# =============================================

"""
Closed Plans Registry Handler

Manages appending closed DPLAN entries to CLOSED_PLANS.local.json.
Extracted from dplan_flow.py to comply with 3-tier architecture:
modules orchestrate, handlers implement file I/O.

Usage:
    from aipass.flow.apps.handlers.dplan.closed_plans_registry import append_closed_dplan
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any


# =============================================================================
# CONFIGURATION
# =============================================================================

# closed_plans_registry.py → dplan/ → handlers/ → apps/ → flow/
FLOW_ROOT = Path(__file__).resolve().parents[3]
CLOSED_PLANS_PATH = FLOW_ROOT / "CLOSED_PLANS.local.json"


# =============================================================================
# OPERATIONS
# =============================================================================

def append_closed_dplan(plan_num: int, topic: str, location: str = "dev_central") -> Dict[str, Any]:
    """
    Append a closed DPLAN entry to CLOSED_PLANS.local.json.

    Duplicate-safe: skips if plan_id already exists.

    Args:
        plan_num: Plan number (integer)
        topic: Plan topic/subject string
        location: Location identifier (default: "dev_central")

    Returns:
        Dict with keys:
            success (bool): Whether the operation succeeded
            action (str): "appended", "duplicate_skipped", or "error"
            plan_id (str): The DPLAN-XXX identifier
            error (str): Error message if failed, empty string on success
    """
    plan_id = f"DPLAN-{plan_num:03d}"
    entry = {
        "plan_id": plan_id,
        "type": "DPLAN",
        "subject": topic,
        "date_closed": datetime.now().strftime("%Y-%m-%d"),
        "location": location,
    }

    try:
        if CLOSED_PLANS_PATH.exists():
            data = json.loads(CLOSED_PLANS_PATH.read_text(encoding="utf-8"))
        else:
            data = {"closed_plans": []}

        # Duplicate check
        if any(p.get("plan_id") == plan_id for p in data.get("closed_plans", [])):
            return {
                "success": True,
                "action": "duplicate_skipped",
                "plan_id": plan_id,
                "error": "",
            }

        data["closed_plans"].insert(0, entry)
        CLOSED_PLANS_PATH.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        return {
            "success": True,
            "action": "appended",
            "plan_id": plan_id,
            "error": "",
        }

    except Exception as e:
        return {
            "success": False,
            "action": "error",
            "plan_id": plan_id,
            "error": str(e),
        }
