# =================== AIPass ====================
# Name: aggregate_ops.py
# Description: Central Plans Aggregation Implementation Handler
# Version: 1.0.0
# Created: 2026-03-08
# Modified: 2026-03-08
# =============================================

"""
Central Plans Aggregation Operations Handler

Implements aggregation and self-healing logic for PLANS.central.json.
Validates file existence, rebuilds active_plans, and auto-closes missing plans.

Usage:
    from aipass.flow.apps.handlers.plan.aggregate_ops import aggregate_central_impl
"""

import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, List, Tuple, Optional

from aipass.prax import logger

# logger imported from aipass.prax
from aipass.flow.apps.handlers.json import json_handler

# =============================================
# CONFIGURATION
# =============================================

MODULE_NAME = "aggregate_central"


# =============================================
# HELPER FUNCTIONS
# =============================================


def find_branch_registry(branch_path: Path, branch_name: str) -> Optional[Path]:
    """Find the registry file for a branch

    Args:
        branch_path: Path to the branch directory
        branch_name: Name of the branch

    Returns:
        Path to registry file if found, None otherwise

    Checks common patterns:
    - {branch_path}/flow_json/{branch}_registry.json
    - {branch_path}/{branch}_json/{branch}_registry.json
    - {branch_path}/registry.json
    """
    if not branch_path.exists():
        return None

    # Pattern 1: flow_json/{branch}_registry.json
    candidate = branch_path / "flow_json" / f"{branch_name}_registry.json"
    if candidate.exists():
        return candidate

    # Pattern 2: branch_json/branch_registry.json
    candidate = branch_path / f"{branch_name}_json" / f"{branch_name}_registry.json"
    if candidate.exists():
        return candidate

    # Pattern 3: registry.json
    candidate = branch_path / "registry.json"
    if candidate.exists():
        return candidate

    return None


def load_branch_registry(registry_path: Path) -> Dict[str, Any]:
    """Load a branch registry file

    Args:
        registry_path: Path to the registry file

    Returns:
        Registry dict or empty structure on error
    """
    try:
        with open(registry_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"[{MODULE_NAME}] Failed to load registry {registry_path}: {e}")
        return {"plans": {}, "next_number": 1}


def save_branch_registry(registry_path: Path, registry: Dict[str, Any]) -> bool:
    """Save a branch registry file

    Args:
        registry_path: Path to the registry file
        registry: Registry data to save

    Returns:
        True on success, False on failure
    """
    try:
        registry["last_updated"] = datetime.now(timezone.utc).isoformat()
        with open(registry_path, "w", encoding="utf-8") as f:
            json.dump(registry, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"[{MODULE_NAME}] Failed to save registry {registry_path}: {e}")
        return False


def extract_plan_number(plan_id: str) -> Optional[str]:
    """Extract plan number from plan_id (e.g., 'FPLAN-0148' -> '0148', 'DPLAN-0004' -> '0004')

    Args:
        plan_id: Plan ID string with any prefix (e.g., 'FPLAN-0148', 'DPLAN-0004')

    Returns:
        Plan number string or None if invalid format
    """
    if not plan_id or "-" not in plan_id:
        return None
    return plan_id.split("-", 1)[1]


def auto_close_plan(registry_path: Path, plan_id: str, branch_name: str) -> bool:
    """Auto-close a plan in its branch registry

    Args:
        registry_path: Path to the branch registry
        plan_id: Plan ID (e.g., 'PLAN0148')
        branch_name: Name of the branch for logging

    Returns:
        True if plan was closed, False otherwise
    """
    plan_num = extract_plan_number(plan_id)
    if not plan_num:
        logger.warning(f"[{MODULE_NAME}] Invalid plan_id format: {plan_id}")
        return False

    # Load registry
    registry = load_branch_registry(registry_path)
    plans = registry.get("plans", {})

    # Check if plan exists in registry
    if plan_num not in plans:
        logger.warning(f"[{MODULE_NAME}] {plan_id} not found in registry {registry_path}")
        return False

    plan_info = plans[plan_num]

    # Skip if already closed
    if plan_info.get("status") == "closed":
        logger.info(f"[{MODULE_NAME}] {plan_id} already closed in {branch_name}")
        return False

    # Close the plan
    plan_info["status"] = "closed"
    plan_info["closed"] = datetime.now(timezone.utc).isoformat()
    plan_info["closed_reason"] = "auto_closed_missing_file"

    # Save registry
    if save_branch_registry(registry_path, registry):
        logger.info(f"[{MODULE_NAME}] SUCCESS: Auto-closed {plan_id} in {branch_name} - file not found")
        return True
    else:
        logger.error(f"[{MODULE_NAME}] Failed to save registry after closing {plan_id}")
        return False


def validate_and_heal_branch(
    branch_name: str, branch_data: Dict[str, Any], heal: bool = True
) -> Tuple[List[Dict], List[Dict]]:
    """Validate plans in a branch and heal missing files

    Args:
        branch_name: Name of the branch
        branch_data: Branch data from PLANS.central.json
        heal: If True, auto-close plans with missing files

    Returns:
        Tuple of (valid_active_plans, all_closed_plans)
    """
    branch_path = Path(branch_data.get("branch_path", ""))
    active_plans = branch_data.get("active_plans", [])
    recently_closed = branch_data.get("recently_closed", [])

    valid_active = []
    healed_plans = []

    # Find branch registry for healing
    registry_path = None
    if heal and branch_path.exists():
        registry_path = find_branch_registry(branch_path, branch_name)

    # Validate active plans
    for plan in active_plans:
        file_path = Path(plan.get("file_path", ""))
        plan_id = plan.get("plan_id", plan.get("plan", ""))

        if file_path.exists():
            valid_active.append(plan)
        else:
            logger.info(f"[{MODULE_NAME}] Missing file for {plan_id} in {branch_name}: {file_path}")

            # Attempt to heal
            if heal and registry_path:
                if auto_close_plan(registry_path, plan_id, branch_name):
                    # Add to healed plans for recently_closed
                    healed_plan = plan.copy()
                    healed_plan["status"] = "closed"
                    healed_plan["closed"] = datetime.now(timezone.utc).isoformat()
                    healed_plan["closed_reason"] = "auto_closed_missing_file"
                    healed_plans.append(healed_plan)
            else:
                if heal:
                    logger.warning(f"[{MODULE_NAME}] Cannot heal {plan_id} - registry not found for {branch_name}")

    # Combine recently_closed with healed plans
    all_closed = recently_closed + healed_plans

    return valid_active, all_closed


def load_central(central_file: Path) -> Dict[str, Any]:
    """Load PLANS.central.json

    Args:
        central_file: Path to the central file

    Returns:
        Central data or empty structure if file doesn't exist
    """
    empty_structure = {
        "generated_at": "",
        "active_plans": [],
        "recently_closed": [],
        "statistics": {"active_count": 0, "total_closed": 0, "recently_closed_included": 0},
        "branches": {},
        "global_statistics": {"total_active": 0, "total_closed": 0, "branches_reporting": 0},
    }

    if not central_file.exists():
        return empty_structure

    try:
        with open(central_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"[{MODULE_NAME}] Failed to load {central_file}: {e}")
        return empty_structure


def save_central(central_file: Path, central_dir: Path, central_data: Dict[str, Any]) -> bool:
    """Save PLANS.central.json

    Args:
        central_file: Path to the central file
        central_dir: Path to the .ai_central/ directory
        central_data: Central data to save

    Returns:
        True on success, False on failure
    """
    try:
        central_dir.mkdir(parents=True, exist_ok=True)
        with open(central_file, "w", encoding="utf-8") as f:
            json.dump(central_data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"[{MODULE_NAME}] Failed to save {central_file}: {e}")
        return False


# =============================================
# MAIN AGGREGATION IMPLEMENTATION
# =============================================


def aggregate_central_impl(
    heal: bool = True, central_file: Path | None = None, central_dir: Path | None = None
) -> bool:
    """Aggregate and validate central plans

    Algorithm:
    1. Load PLANS.central.json
    2. For each branch in branches.*:
       - Validate all active_plans have files on disk
       - If heal=True and file missing: auto-close in branch registry
       - Collect valid active plans and all closed plans
    3. Rebuild top-level active_plans (sorted by created, newest first)
    4. Rebuild top-level recently_closed (last 5, sorted by closed, newest first)
    5. Update statistics
    6. Save PLANS.central.json

    Args:
        heal: If True, auto-close plans with missing files in their registries
        central_file: Path to PLANS.central.json
        central_dir: Path to .ai_central directory

    Returns:
        True on success, False on failure
    """
    try:
        logger.info(f"[{MODULE_NAME}] Starting central aggregation")

        # Apply defaults when caller passes None
        if central_file is None or central_dir is None:
            logger.error(f"[{MODULE_NAME}] central_file and central_dir are required")
            return False

        assert central_file is not None  # narrowing for type checker
        assert central_dir is not None

        # Load central file
        central_data = load_central(central_file)
        branches = central_data.get("branches", {})

        if not branches:
            logger.info(f"[{MODULE_NAME}] No branches found in PLANS.central.json")
            return True

        # Track all active and closed plans across branches
        all_active = []
        all_closed = []

        # Process each branch
        for branch_name, branch_data in branches.items():
            logger.info(f"[{MODULE_NAME}] Processing branch: {branch_name}")

            # Validate and heal
            valid_active, closed_plans = validate_and_heal_branch(branch_name, branch_data, heal)

            # Update branch-level active_plans with validated list
            branch_data["active_plans"] = valid_active

            # Update branch-level recently_closed (sorted, newest first)
            branch_recently_closed = sorted(closed_plans, key=lambda x: x.get("closed", ""), reverse=True)[:5]
            branch_data["recently_closed"] = branch_recently_closed

            # Update branch-level statistics to match validated arrays
            branch_data["statistics"] = {
                "active_count": len(valid_active),
                "total_closed": len(closed_plans),
                "recently_closed_included": len(branch_recently_closed),
            }

            # Add branch name to each plan for identification
            for plan in valid_active:
                if "branch" not in plan:
                    plan["branch"] = branch_name
                all_active.append(plan)

            for plan in closed_plans:
                if "branch" not in plan:
                    plan["branch"] = branch_name
                all_closed.append(plan)

        # Sort active by created date (newest first)
        all_active.sort(key=lambda x: x.get("created", ""), reverse=True)

        # Sort closed by closed date (newest first) and limit to last 5
        all_closed.sort(key=lambda x: x.get("closed", ""), reverse=True)
        recently_closed = all_closed[:5]

        # Update top-level arrays
        central_data["active_plans"] = all_active
        central_data["recently_closed"] = recently_closed

        # Update top-level statistics
        central_data["statistics"] = {
            "active_count": len(all_active),
            "total_closed": len(all_closed),
            "recently_closed_included": len(recently_closed),
        }

        # Update global_statistics (aggregated from all branches)
        central_data["global_statistics"] = {
            "total_active": len(all_active),
            "total_closed": len(all_closed),
            "branches_reporting": len(
                [b for b in branches.values() if b.get("active_plans") or b.get("recently_closed")]
            ),
        }

        # Update generated_at timestamp
        central_data["generated_at"] = datetime.now(timezone.utc).isoformat()

        # Save central file
        if save_central(central_file, central_dir, central_data):
            logger.info(
                f"[{MODULE_NAME}] SUCCESS: Aggregation complete: {len(all_active)} active, {len(recently_closed)} recently closed"
            )

            # Fire trigger event
            try:
                from aipass.trigger.apps.modules.core import trigger

                trigger.fire(
                    "central_aggregated",
                    active_count=len(all_active),
                    closed_count=len(recently_closed),
                    branches_count=len(branches),
                )
            except ImportError as e:
                logger.warning(f"[{MODULE_NAME}] Trigger module not available, skipping central_aggregated event: {e}")

            json_handler.log_operation(
                "central_aggregated",
                {"active_count": len(all_active), "closed_count": len(recently_closed), "success": True},
            )
            return True
        else:
            logger.error(f"[{MODULE_NAME}] Failed to save central file")
            return False

    except Exception as e:
        logger.error(f"[{MODULE_NAME}] Aggregation failed: {e}")
        return False
