# =================== AIPass ====================
# Name: append_closed_plan.py
# Description: Closed Plans Local Registry Handler
# Version: 0.1.0
# Created: 2026-03-03
# Modified: 2026-07-15
# =============================================

"""
Closed Plans Append Handler

Appends a closed plan entry to the branch's CLOSED_PLANS.local.json file.
Creates the file if it doesn't exist.
"""

# ruff: noqa: E402
import json
import os
import re
import time
from pathlib import Path

# INFRASTRUCTURE IMPORT PATTERN
from aipass.flow.apps.handlers.repo_root import module_file

_PKG_ROOT = module_file(__file__).parents[4]

# External: Prax logger
from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.flow.apps.handlers.json import json_handler

MODULE_NAME = "append_closed_plan"
CLOSED_PLANS_FILE = "CLOSED_PLANS.local.json"

_LOCK_RETRIES = 10
_LOCK_BACKOFF_BASE = 0.05


def _acquire_append_lock(lock_path: Path) -> bool:
    """Atomically acquire a lockfile via O_CREAT|O_EXCL with retry+backoff."""
    for attempt in range(_LOCK_RETRIES):
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return True
        except FileExistsError:
            logger.info("[%s] Lock contention on %s, retry %d", MODULE_NAME, lock_path, attempt + 1)
            time.sleep(_LOCK_BACKOFF_BASE * (2**attempt))
    return False


def _release_append_lock(lock_path: Path) -> None:
    """Remove lockfile, tolerating already-removed."""
    try:
        lock_path.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("[%s] Could not release lock %s: %s", MODULE_NAME, lock_path, exc)


def append_to_closed_plans(plan_key: str, plan_info: dict, plan_location: Path) -> bool:
    """
    Append a closed plan entry to the branch's CLOSED_PLANS.local.json

    Args:
        plan_key: Plan number string (e.g., "0405")
        plan_info: Plan info dict from registry (must contain 'closed', may contain 'subject', 'relative_path')
        plan_location: Path to the directory where the plan resides (branch directory)

    Returns:
        True on success, False on failure
    """
    try:
        # Extract prefix from plan_info's file_path (e.g., FPLAN, DPLAN)
        file_path = plan_info.get("file_path", "")
        filename = Path(file_path).name if file_path else ""
        prefix_match = re.match(r"^([A-Z]+PLAN)", filename)
        prefix = prefix_match.group(1) if prefix_match else "FPLAN"
        plan_id = f"{prefix}-{plan_key}"

        # Extract date (YYYY-MM-DD) from the closed ISO timestamp
        closed_raw = plan_info.get("closed", "")
        date_closed = closed_raw[:10] if closed_raw else ""

        # Build the entry
        entry = {
            "plan_id": plan_id,
            "type": prefix,
            "subject": plan_info.get("subject", ""),
            "date_closed": date_closed,
            "location": plan_info.get("relative_path", ""),
        }

        # Locked read-modify-write to prevent lost updates under concurrent close
        closed_plans_path = plan_location / CLOSED_PLANS_FILE
        lock_path = closed_plans_path.with_suffix(".lock")

        if not _acquire_append_lock(lock_path):
            logger.error(
                f"[{MODULE_NAME}] Could not acquire lock for {closed_plans_path} after {_LOCK_RETRIES} retries"
            )
            return False

        try:
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
        finally:
            _release_append_lock(lock_path)

        logger.info(f"[{MODULE_NAME}] Appended {plan_id} to {closed_plans_path}")
        json_handler.log_operation(
            "closed_plan_appended", {"plan_id": plan_id, "path": str(closed_plans_path), "success": True}
        )
        return True

    except Exception as e:
        logger.warning(f"[{MODULE_NAME}] Failed to append closed plan: {e}")
        return False
