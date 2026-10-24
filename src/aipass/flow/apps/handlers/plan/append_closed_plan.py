# =================== AIPass ====================
# Name: append_closed_plan.py
# Description: Closed Plans Local Registry Handler
# Version: 0.5.0
# Created: 2026-03-03
# Modified: 2026-10-24
# =============================================

"""Closed Plans Append Handler"""

import json
import re
from pathlib import Path

from aipass.flow.apps.handlers.repo_root import module_file

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.flow.apps.handlers.json import json_handler
from aipass.flow.apps.handlers.registry.save_registry import registry_lock

_PKG_ROOT = module_file(__file__).parents[4]

MODULE_NAME = "append_closed_plan"
CLOSED_PLANS_FILE = "CLOSED_PLANS.local.json"


def append_to_closed_plans(plan_key: str, plan_info: dict, plan_location: Path) -> bool:
    """Append a closed plan entry to the branch's CLOSED_PLANS.local.json
    Returns True on success or when already present, False when the lock stayed held past its budget.
    Raises on any other failure, so a held lock is distinguishable from a broken write.
    """
    try:
        file_path = plan_info.get("file_path", "")
        filename = Path(file_path).name if file_path else ""
        prefix_match = re.match(r"^([A-Z]+PLAN)", filename)
        prefix = prefix_match.group(1) if prefix_match else "FPLAN"
        plan_id = f"{prefix}-{plan_key}"

        closed_raw = plan_info.get("closed", "")
        date_closed = closed_raw[:10] if closed_raw else ""

        entry = {
            "plan_id": plan_id,
            "type": prefix,
            "subject": plan_info.get("subject", ""),
            "date_closed": date_closed,
            "location": plan_info.get("relative_path", ""),
        }

        closed_plans_path = plan_location / CLOSED_PLANS_FILE
        # Locked read-modify-write: concurrent closes would otherwise lose entries.
        with registry_lock():
            if closed_plans_path.exists():
                with open(closed_plans_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            else:
                data = {"closed_plans": []}

            existing_ids = {p.get("plan_id") for p in data.get("closed_plans", [])}
            if plan_id in existing_ids:
                logger.info(f"[{MODULE_NAME}] {plan_id} already in {CLOSED_PLANS_FILE} at {plan_location}, skipping")
                return True

            data["closed_plans"].append(entry)

            with open(closed_plans_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.write("\n")

        logger.info(f"[{MODULE_NAME}] Appended {plan_id} to {closed_plans_path}")
        json_handler.log_operation(
            "closed_plan_appended", {"plan_id": plan_id, "path": str(closed_plans_path), "success": True}
        )
        return True

    except TimeoutError as e:
        logger.error(f"[{MODULE_NAME}] Could not take the write lock for {CLOSED_PLANS_FILE}: {e}")
        return False
    except Exception as e:
        logger.warning(f"[{MODULE_NAME}] Failed to append closed plan: {e}")
        raise
