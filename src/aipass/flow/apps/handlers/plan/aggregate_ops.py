# =================== AIPass ====================
# Name: aggregate_ops.py
# Description: Central Plans Aggregation Implementation Handler
# Version: 1.5.0
# Created: 2026-03-08
# Modified: 2026-10-24
# =============================================

"""
Central Plans Aggregation Operations Handler
"""

import json
import os
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, List, Tuple, Optional

from aipass.prax import logger

from aipass.flow.apps.handlers.json import json_handler
from aipass.flow.apps.handlers.registry.save_registry import registry_lock

MODULE_NAME = "aggregate_central"


def find_branch_registry(branch_path: Path, branch_name: str) -> Optional[Path]:
    """Find the registry file for a branch"""
    if not branch_path.exists():
        return None

    candidate = branch_path / "flow_json" / f"{branch_name}_registry.json"
    if candidate.exists():
        return candidate

    candidate = branch_path / f"{branch_name}_json" / f"{branch_name}_registry.json"
    if candidate.exists():
        return candidate

    candidate = branch_path / "registry.json"
    if candidate.exists():
        return candidate

    return None


def load_branch_registry(registry_path: Path) -> Dict[str, Any]:
    """Load a branch registry file"""
    try:
        with open(registry_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"[{MODULE_NAME}] Failed to load registry {registry_path}: {e}")
        return {"plans": {}, "next_number": 1}


def save_branch_registry(registry_path: Path, registry: Dict[str, Any]) -> bool:
    """Save a branch registry file"""
    try:
        registry_path.parent.mkdir(parents=True, exist_ok=True)

        with registry_lock():
            registry["last_updated"] = datetime.now(timezone.utc).isoformat()
            tmp_path = registry_path.with_suffix(".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(registry, f, indent=2, ensure_ascii=False)
            os.replace(str(tmp_path), str(registry_path))

        return True
    except Exception as e:
        logger.error(
            "[%s] Failed to save registry %s: %s",
            MODULE_NAME,
            registry_path,
            e,
        )
        return False


def extract_plan_number(plan_id: str) -> Optional[str]:
    """Extract plan number from plan_id (e.g., 'FPLAN-0148' -> '0148', 'DPLAN-0004' -> '0004')"""
    if not plan_id or "-" not in plan_id:
        return None
    return plan_id.split("-", 1)[1]


def auto_close_plan(registry_path: Path, plan_id: str, branch_name: str) -> bool:
    """Auto-close a plan in its branch registry"""
    plan_num = extract_plan_number(plan_id)
    if not plan_num:
        logger.warning(f"[{MODULE_NAME}] Invalid plan_id format: {plan_id}")
        return False

    registry = load_branch_registry(registry_path)
    plans = registry.get("plans", {})

    if plan_num not in plans:
        logger.warning(f"[{MODULE_NAME}] {plan_id} not found in registry {registry_path}")
        return False

    plan_info = plans[plan_num]

    # Every plan type numbers from 0001: close only a row whose file names the same prefix.
    prefix = plan_id.split("-", 1)[0]
    row_file = Path(str(plan_info.get("file_path") or "")).name
    if not row_file.startswith(f"{prefix}-"):
        logger.warning(
            "[%s] %s: the row under %s in %s is %r, not this plan; left open",
            MODULE_NAME,
            plan_id,
            plan_num,
            registry_path,
            row_file or "a row with no file",
        )
        return False

    if plan_info.get("status") == "closed":
        logger.info(f"[{MODULE_NAME}] {plan_id} already closed in {branch_name}")
        return False

    plan_info["status"] = "closed"
    plan_info["closed"] = datetime.now(timezone.utc).isoformat()
    plan_info["closed_reason"] = "auto_closed_missing_file"

    if save_branch_registry(registry_path, registry):
        logger.info(f"[{MODULE_NAME}] SUCCESS: Auto-closed {plan_id} in {branch_name} - file not found")
        return True
    else:
        logger.error(f"[{MODULE_NAME}] Failed to save registry after closing {plan_id}")
        return False


def validate_and_heal_branch(
    branch_name: str, branch_data: Dict[str, Any], heal: bool = True
) -> Tuple[List[Dict], List[Dict]]:
    """Validate plans in a branch and heal missing files"""
    branch_path = Path(branch_data.get("branch_path", ""))
    active_plans = branch_data.get("active_plans", [])
    recently_closed = branch_data.get("recently_closed", [])

    valid_active = []
    healed_plans = []

    registry_path = None
    if heal and branch_path.exists():
        registry_path = find_branch_registry(branch_path, branch_name)

    for plan in active_plans:
        file_path = Path(plan.get("file_path", ""))
        plan_id = plan.get("plan_id", plan.get("plan", ""))

        if file_path.exists():
            valid_active.append(plan)
        else:
            logger.info(f"[{MODULE_NAME}] Missing file for {plan_id} in {branch_name}: {file_path}")

            if heal and registry_path:
                if auto_close_plan(registry_path, plan_id, branch_name):
                    healed_plan = plan.copy()
                    healed_plan["status"] = "closed"
                    healed_plan["closed"] = datetime.now(timezone.utc).isoformat()
                    healed_plan["closed_reason"] = "auto_closed_missing_file"
                    healed_plans.append(healed_plan)
            else:
                if heal:
                    logger.warning(f"[{MODULE_NAME}] Cannot heal {plan_id} - registry not found for {branch_name}")

    all_closed = recently_closed + healed_plans

    return valid_active, all_closed


def _resolve_total_closed(branch_name: str, *, upstream_total: Any, healed_count: int, window_size: int) -> int:
    """Resolve how many plans a branch has really closed.

    Aggregation sees only the capped recently_closed window, so the real count is push_central's
    upstream total plus this run's heals; without it, the window size is returned as a floor.
    """
    if isinstance(upstream_total, bool) or not isinstance(upstream_total, int):
        logger.warning(
            "[%s] No upstream total_closed for '%s' — publishing the recently-closed window (%d) as a FLOOR, "
            "not a total. The real count comes from push_central; run a plan push to correct it.",
            MODULE_NAME,
            branch_name,
            window_size,
        )
        return window_size
    return upstream_total + healed_count


def load_central(central_file: Path) -> Dict[str, Any]:
    """Load PLANS.central.json"""
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
    """Save PLANS.central.json"""
    try:
        central_dir.mkdir(parents=True, exist_ok=True)

        with registry_lock():
            tmp_path = central_file.with_suffix(".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(central_data, f, indent=2, ensure_ascii=False)
            os.replace(str(tmp_path), str(central_file))

        return True
    except Exception as e:
        logger.error(f"[{MODULE_NAME}] Failed to save {central_file}: {e}")
        return False


def aggregate_central_impl(
    heal: bool = True, central_file: Path | None = None, central_dir: Path | None = None
) -> bool:
    """Aggregate and validate central plans"""
    try:
        logger.info(f"[{MODULE_NAME}] Starting central aggregation")

        if central_file is None or central_dir is None:
            logger.error(f"[{MODULE_NAME}] central_file and central_dir are required")
            return False

        assert central_file is not None  # narrowing for type checker
        assert central_dir is not None

        central_data = load_central(central_file)
        branches = central_data.get("branches", {})

        if not branches:
            logger.info(f"[{MODULE_NAME}] No branches found in PLANS.central.json")
            return True

        all_active = []
        all_closed = []

        total_closed_all_branches = 0
        for branch_name, branch_data in branches.items():
            logger.info(f"[{MODULE_NAME}] Processing branch: {branch_name}")

            # Read before validate_and_heal_branch, while push_central's statistic is still here.
            window_before = len(branch_data.get("recently_closed", []))
            upstream_total = branch_data.get("statistics", {}).get("total_closed")

            valid_active, closed_plans = validate_and_heal_branch(branch_name, branch_data, heal)

            branch_data["active_plans"] = valid_active

            branch_recently_closed = sorted(closed_plans, key=lambda x: x.get("closed", ""), reverse=True)[:5]
            branch_data["recently_closed"] = branch_recently_closed

            branch_total_closed = _resolve_total_closed(
                branch_name,
                upstream_total=upstream_total,
                healed_count=len(closed_plans) - window_before,
                window_size=len(closed_plans),
            )
            total_closed_all_branches += branch_total_closed

            branch_data["statistics"] = {
                "active_count": len(valid_active),
                "total_closed": branch_total_closed,
                "recently_closed_included": len(branch_recently_closed),
            }

            for plan in valid_active:
                if "branch" not in plan:
                    plan["branch"] = branch_name
                all_active.append(plan)

            for plan in closed_plans:
                if "branch" not in plan:
                    plan["branch"] = branch_name
                all_closed.append(plan)

        all_active.sort(key=lambda x: x.get("created", ""), reverse=True)

        all_closed.sort(key=lambda x: x.get("closed", ""), reverse=True)
        recently_closed = all_closed[:5]

        central_data["active_plans"] = all_active
        central_data["recently_closed"] = recently_closed

        # Not len(all_closed): that sums the per-branch windows, not the totals.
        central_data["statistics"] = {
            "active_count": len(all_active),
            "total_closed": total_closed_all_branches,
            "recently_closed_included": len(recently_closed),
        }

        central_data["global_statistics"] = {
            "total_active": len(all_active),
            "total_closed": total_closed_all_branches,
            "branches_reporting": len(
                [b for b in branches.values() if b.get("active_plans") or b.get("recently_closed")]
            ),
        }

        central_data["generated_at"] = datetime.now(timezone.utc).isoformat()

        if save_central(central_file, central_dir, central_data):
            logger.info(
                "[%s] SUCCESS: Aggregation complete: %d active, %d recently closed",
                MODULE_NAME,
                len(all_active),
                len(recently_closed),
            )

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
