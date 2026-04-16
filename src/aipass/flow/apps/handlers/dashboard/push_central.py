# =================== AIPass ====================
# Name: push_central.py
# Description: Push to Plans Central Handler
# Version: 1.1.0
# Created: 2025-11-21
# Modified: 2025-11-21
# =============================================

"""
Push to Plans Central Handler

Pushes Flow's plan data to the central PLANS.central.json file at .ai_central.
This handler follows the 3-tier logging standard (no Prax imports, no logging).

Features:
- Reads fplan_registry.json to get Flow's plans
- Extracts only plans where location='flow' (Flow's own plans)
- Updates branches.flow section in PLANS.central.json
- Preserves all other branch sections
- Calls aggregate_central_impl to rebuild top-level active_plans
- Calculates global statistics across all branches
- Pure handler - returns boolean for success/failure

Usage:
    from aipass.flow.apps.handlers.dashboard.push_central import push_to_plans_central
    success = push_to_plans_central()
"""

import json
import re
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, List

from aipass.flow.apps.handlers.json import json_handler
from aipass.prax.apps.modules.logger import system_logger as logger

# INFRASTRUCTURE IMPORT PATTERN
_PKG_ROOT = Path(__file__).resolve().parents[4]
FLOW_ROOT = _PKG_ROOT / "flow"

# Handler imports (aggregate_ops is a sibling handler — avoids handler→module layer violation)
from aipass.flow.apps.handlers.plan.aggregate_ops import aggregate_central_impl

# =============================================
# CONFIGURATION
# =============================================

MODULE_NAME = "push_central"
FLOW_JSON_DIR = FLOW_ROOT / "flow_json"
REGISTRY_FILE = FLOW_JSON_DIR / "fplan_registry.json"


def _find_repo_root() -> Path:
    """Walk up from this file to find the repo root (contains AIPASS_REGISTRY.json)."""
    current = Path(__file__).resolve().parent
    for parent in [current] + list(current.parents):
        if (parent / "AIPASS_REGISTRY.json").exists():
            return parent
    return Path.cwd()


_REPO_ROOT = _find_repo_root()
AI_CENTRAL_DIR = _REPO_ROOT / ".ai_central"
CENTRAL_FILE = AI_CENTRAL_DIR / "PLANS.central.json"

# =============================================
# PLAN TYPE HELPERS
# =============================================


def _get_all_registry_files() -> List[str]:
    """Return per-type registry filenames via plan-type discovery."""
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
        logger.warning("[push_central] Failed to discover plan types, falling back to default registry: %s", exc)
    return [REGISTRY_FILE.name]


# =============================================
# HELPER FUNCTIONS
# =============================================


def _load_registry() -> Dict[str, Any]:
    """Load all per-type plan registries and merge into a single dict.

    Returns:
        Merged registry dict or empty structure if no files found
    """
    merged: Dict[str, Any] = {"plans": {}, "next_number": 1}
    for registry_file in _get_all_registry_files():
        target = FLOW_JSON_DIR / registry_file
        try:
            if not target.exists():
                continue
            with open(target, "r", encoding="utf-8") as f:
                data = json.load(f)
            for plan_num, plan_data in data.get("plans", {}).items():
                merged["plans"][plan_num] = plan_data
            nn = data.get("next_number", 1)
            if nn > merged["next_number"]:
                merged["next_number"] = nn
        except Exception as exc:
            logger.warning("Failed to load registry '%s': %s", target, exc)
    return merged


def _extract_flow_plans(registry: Dict[str, Any]) -> tuple[List[Dict], List[Dict]]:
    """Extract Flow's own plans from registry

    Args:
        registry: The fplan_registry.json data

    Returns:
        Tuple of (active_plans, recently_closed_plans)
    """
    plans = registry.get("plans", {})
    active = []
    closed = []

    for plan_num, plan_data in plans.items():
        # Only include plans where location is 'flow' (Flow's own plans)
        location = plan_data.get("location", "")
        if location != str(FLOW_ROOT):
            continue

        # Extract plan prefix from file_path (e.g., DPLAN, FPLAN, TDPLAN)
        file_path_str = plan_data.get("file_path", "")
        filename = Path(file_path_str).name if file_path_str else ""
        prefix_match = re.match(r"^([A-Z]+PLAN)", filename)
        prefix = prefix_match.group(1) if prefix_match else "FPLAN"

        # Build plan entry
        plan_entry = {
            "plan_id": f"{prefix}-{plan_num.zfill(4)}",
            "subject": plan_data.get("subject", ""),
            "status": plan_data.get("status", "open"),
            "created": plan_data.get("created", ""),
            "file_path": plan_data.get("file_path", ""),
            "relative_path": plan_data.get("relative_path", ""),
        }

        if plan_data.get("status") == "open":
            active.append(plan_entry)
        else:
            # Add closed metadata
            plan_entry["closed"] = plan_data.get("closed", "")
            plan_entry["closed_reason"] = plan_data.get("closed_reason", "")
            closed.append(plan_entry)

    # Sort active by created date (newest first)
    active.sort(key=lambda x: x.get("created", ""), reverse=True)

    # Sort closed by closed date (newest first) and limit to last 5
    closed.sort(key=lambda x: x.get("closed", ""), reverse=True)
    recently_closed = closed[:5]

    return active, recently_closed


def _load_central() -> Dict[str, Any]:
    """Load existing PLANS.central.json

    Returns:
        Central file data or empty structure if file doesn't exist
    """
    if not CENTRAL_FILE.exists():
        return {
            "generated_at": "",
            "branches": {},
            "global_statistics": {"total_active": 0, "total_closed": 0, "branches_reporting": 0},
        }

    try:
        with open(CENTRAL_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logger.warning("Failed to load PLANS.central.json '%s': %s", CENTRAL_FILE, exc)
        return {
            "generated_at": "",
            "branches": {},
            "global_statistics": {"total_active": 0, "total_closed": 0, "branches_reporting": 0},
        }


def _calculate_global_statistics(central_data: Dict[str, Any]) -> Dict[str, int]:
    """Calculate global statistics by summing all branches

    Args:
        central_data: The full central file data

    Returns:
        Dict with total_active, total_closed, branches_reporting
    """
    branches = central_data.get("branches", {})
    total_active = 0
    total_closed = 0

    for branch_data in branches.values():
        stats = branch_data.get("statistics", {})
        total_active += stats.get("active_count", 0)
        total_closed += stats.get("total_closed", 0)

    return {"total_active": total_active, "total_closed": total_closed, "branches_reporting": len(branches)}


# =============================================
# MAIN HANDLER FUNCTION
# =============================================


def push_to_plans_central() -> bool:
    """Push Flow's plan data to .ai_central/PLANS.central.json

    Algorithm:
    1. Read fplan_registry.json
    2. Extract only plans where location='flow' (Flow's own plans)
    3. Format for central structure with branch metadata
    4. Read existing PLANS.central.json if exists
    5. Update ONLY branches.flow section
    6. Update global_statistics (total counts across all branches)
    7. Preserve ALL other branch sections
    8. Write back to PLANS.central.json
    9. Call aggregate_central_impl to rebuild top-level active_plans with validation

    Returns:
        True on success, False on failure
    """
    try:
        # Ensure .ai_central directory exists
        AI_CENTRAL_DIR.mkdir(parents=True, exist_ok=True)

        # Load registry
        registry = _load_registry()

        # Extract Flow's plans
        active_plans, recently_closed = _extract_flow_plans(registry)

        # Build Flow's branch section
        now = datetime.now(timezone.utc).isoformat()
        flow_section = {
            "branch_name": "FLOW",
            "branch_path": str(FLOW_ROOT),
            "last_updated": now,
            "active_plans": active_plans,
            "recently_closed": recently_closed,
            "statistics": {
                "active_count": len(active_plans),
                "total_closed": len(
                    [
                        p
                        for p in registry.get("plans", {}).values()
                        if p.get("location") == str(FLOW_ROOT) and p.get("status") == "closed"
                    ]
                ),
            },
        }

        # Load existing central file
        central_data = _load_central()

        # Update Flow's section
        if "branches" not in central_data:
            central_data["branches"] = {}
        central_data["branches"]["flow"] = flow_section

        # Update global statistics
        central_data["global_statistics"] = _calculate_global_statistics(central_data)

        # Update generated_at timestamp
        central_data["generated_at"] = now

        # Write back to central file
        with open(CENTRAL_FILE, "w", encoding="utf-8") as f:
            json.dump(central_data, f, indent=2, ensure_ascii=False)

        # Call aggregate_central_impl to rebuild top-level arrays with validation
        # This ensures active_plans is built from all branches and validates files exist
        aggregate_central_impl(heal=True, central_file=CENTRAL_FILE, central_dir=AI_CENTRAL_DIR)

        json_handler.log_operation(
            "plans_central_pushed",
            {
                "active_plans": len(active_plans),
                "recently_closed": len(recently_closed),
                "branches_reporting": central_data["global_statistics"].get("branches_reporting", 0),
                "success": True,
            },
        )

        return True

    except Exception as exc:
        logger.error("Failed to push plans to central '%s': %s", CENTRAL_FILE, exc)
        return False
