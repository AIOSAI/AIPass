# =================== AIPass ====================
# Name: restore_ops.py
# Description: Plan Restore Implementation Handler
# Version: 1.1.0
# Created: 2026-03-08
# Modified: 2026-03-08
# =============================================

"""
Plan Restore Operations Handler

Implements plan restore/recovery business logic, extracted from restore_plan module.
Handles backup recovery and plan file restoration.

Returns data dicts - module handles all display.

Usage:
    from aipass.flow.apps.handlers.plan.restore_ops import recover_plan_from_backup, restore_plan_impl
"""

from pathlib import Path
from shutil import copy2
from datetime import datetime, timezone
from typing import Dict, Any, List

from aipass.prax import logger

# logger imported from aipass.prax
from aipass.flow.apps.handlers.json import json_handler

# =============================================
# INFRASTRUCTURE
# =============================================

_PKG_ROOT = Path(__file__).resolve().parents[4]  # handlers/plan/ -> handlers/ -> apps/ -> flow/ -> aipass/
FLOW_ROOT = _PKG_ROOT / "flow"


def _find_repo_root() -> Path:
    """Walk up to find the repo root (contains AIPASS_REGISTRY.json)."""
    current = Path(__file__).resolve().parent
    for parent in [current] + list(current.parents):
        if (parent / "AIPASS_REGISTRY.json").exists():
            return parent
    return Path.cwd()


PROCESSED_PLANS_DIR = _find_repo_root() / ".backup" / "processed_plans"

MODULE_NAME = "restore_plan"


# =============================================
# RECOVERY IMPLEMENTATION
# =============================================


def recover_plan_from_backup(plan_key: str, load_registry: Any = None, save_registry: Any = None) -> tuple[bool, str]:
    """
    Attempt to recover a plan from processed_plans backup.

    Plan-type-agnostic: searches for any prefix matching the plan key
    (e.g. FPLAN-0165, DPLAN-0165).

    Args:
        plan_key: Normalized plan number (e.g., "0165")
        load_registry: Registry loader function (injected from module)
        save_registry: Registry saver function (injected from module)

    Returns:
        (success, message)
    """
    # Check backup processed_plans directory
    processed_plans = PROCESSED_PLANS_DIR

    # Search for any prefix matching the plan key (FPLAN-, DPLAN-, etc.)
    variants = list(processed_plans.glob(f"*-{plan_key}*.md")) if processed_plans.exists() else []
    plan_file = None  # No default -- use variant search
    if variants:
        # Sort by modification time, newest first
        variants.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        plan_file = variants[0]  # Use most recent backup
    if plan_file is None or not plan_file.exists():
        return False, f"Plan {plan_key} not found in backups"

    # Read plan file to extract original location from header
    try:
        with open(plan_file, "r", encoding="utf-8") as f:
            content = f.read()

        # Parse location from header (e.g., "**Location**: /path/to/dir")
        original_location = None
        for line in content.split("\n")[:20]:  # Check first 20 lines
            if line.startswith("**Location**:"):
                original_location = line.split("**Location**:")[1].strip()
                break

        # If location not found in header, default to FLOW_ROOT
        if not original_location:
            original_location = str(FLOW_ROOT)

        # CRITICAL: Convert relative paths to absolute paths
        # If location is relative (like "flow"), resolve it
        if not original_location.startswith("/"):
            # Relative path - resolve against _PKG_ROOT
            if original_location == "flow":
                original_location = str(FLOW_ROOT)
            else:
                # Try resolving relative to _PKG_ROOT
                potential_path = _PKG_ROOT / original_location
                if potential_path.exists():
                    original_location = str(potential_path)
                else:
                    # Fallback to FLOW_ROOT
                    original_location = str(FLOW_ROOT)

        # Determine relative path
        original_path = Path(original_location)
        if original_path == FLOW_ROOT:
            relative_path = "flow"
        elif original_path == _PKG_ROOT:
            relative_path = "root"
        else:
            try:
                relative_path = str(original_path.relative_to(_PKG_ROOT))
            except ValueError as e:
                logger.warning(f"[{MODULE_NAME}] Could not compute relative path for '{original_path}': {e}")
                relative_path = str(original_path)

    except Exception as e:
        logger.warning(
            f"[{MODULE_NAME}] Failed to parse plan file '{plan_file}' for recovery, defaulting to FLOW_ROOT: {e}"
        )
        original_location = str(FLOW_ROOT)
        relative_path = "flow"

    # Copy file to ORIGINAL location (preserve backup) using the original filename
    target = Path(original_location) / plan_file.name
    copy2(plan_file, target)

    # Derive display label from the backup filename
    plan_label = plan_file.stem  # e.g. "FPLAN-0165" or "DPLAN-0004"

    # Create minimal registry entry
    registry = load_registry()
    registry["plans"][plan_key] = {
        "location": original_location,
        "relative_path": relative_path,
        "file_path": str(target),
        "status": "closed",
        "created": datetime.now(timezone.utc).isoformat(),
        "subject": "Recovered from backup",
        "closed": datetime.now(timezone.utc).isoformat(),
        "closed_reason": "recovered_from_backup",
        "template_type": "default",
    }
    save_registry(registry)

    return True, f"Recovered {plan_label} from {plan_file.name} to {original_location}"


# =============================================
# RESTORE PLAN IMPLEMENTATION
# =============================================


def restore_plan_impl(
    plan_num: str | None = None,
    # Dependencies injected from module
    normalize_plan_number: Any = None,
    load_registry: Any = None,
    save_registry: Any = None,
    validate_plan_exists: Any = None,
    recover_plan_from_backup_fn: Any = None,
    scan_plan_files: Any = None,
    update_dashboard_local: Any = None,
    push_to_plans_central: Any = None,
) -> Dict[str, Any]:
    """
    Implement plan restore workflow

    Restores a closed plan back to open status by updating registry metadata.
    Does NOT move files - file must already be at registered location.

    Args:
        plan_num: Plan number (e.g., "0001" or "1" or "42")
        (remaining args): Handler/service dependencies injected by module

    Returns:
        Dict with keys: success (bool), messages (list of dicts with type/text),
        plan_key (str), restored_location (str)
    """
    messages: List[Dict[str, Any]] = []

    if not plan_num:
        logger.warning(f"[{MODULE_NAME}] Plan number required for restore")
        return {
            "success": False,
            "messages": [{"type": "error", "error_type": "invalid_number", "plan_key": ""}],
            "plan_key": "",
            "restored_location": "",
        }

    try:
        # 0. AUTO-HEAL: Run registry scan to detect moved files (self-healing)
        scan_plan_files()
        logger.info(f"[{MODULE_NAME}] Auto-heal scan completed")

        # 1. VALIDATE: Normalize plan number (handler)
        plan_key = normalize_plan_number(plan_num)

        # 2. LOAD DATA: Get registry (service)
        registry = load_registry()

        # 3. VALIDATE: Check plan exists (handler)
        exists, error_msg = validate_plan_exists(plan_key, registry)
        if not exists:
            # AUTO-RECOVERY: Try to recover from processed_plans
            messages.append({"type": "warning", "text": f"PLAN-{plan_key} not in registry - attempting recovery..."})
            recovered, recovery_msg = recover_plan_from_backup_fn(plan_key)

            if recovered:
                messages.append({"type": "success", "text": recovery_msg})
                # Reload registry with recovered plan
                registry = load_registry()
                plan_info = registry["plans"][plan_key]
                plan_file = Path(plan_info.get("file_path", ""))
            else:
                logger.warning(f"[{MODULE_NAME}] {error_msg} - Recovery failed: {recovery_msg}")
                messages.append({"type": "error", "error_type": "not_found", "plan_key": plan_key})
                messages.append({"type": "dim", "text": f"Recovery attempt: {recovery_msg}"})
                return {
                    "success": False,
                    "messages": messages,
                    "plan_key": plan_key,
                    "restored_location": "",
                }
        else:
            plan_info = registry["plans"][plan_key]
            plan_file = Path(plan_info.get("file_path", ""))

        # 4. VALIDATE: Check plan is closed
        if plan_info.get("status") != "closed":
            logger.warning(f"[{MODULE_NAME}] Plan {plan_key} is already open")
            messages.append({"type": "error", "error_type": "already_open", "plan_key": plan_key})
            return {
                "success": False,
                "messages": messages,
                "plan_key": plan_key,
                "restored_location": "",
            }

        # 5. VALIDATE: Check file exists at registered location
        if not plan_file.exists():
            logger.warning(f"[{MODULE_NAME}] File not found at {plan_file}")
            messages.append({"type": "error", "error_type": "file_missing", "plan_key": plan_key})
            return {
                "success": False,
                "messages": messages,
                "plan_key": plan_key,
                "restored_location": "",
            }

        # 6. DISPLAY: Plan info header data
        messages.append({"type": "restore_header", "plan_key": plan_key, "plan_info": plan_info})

        # 7. UPDATE REGISTRY: Restore to open status
        plan_info["status"] = "open"

        # Remove all close-related metadata
        plan_info.pop("closed", None)
        plan_info.pop("closed_reason", None)
        plan_info.pop("memory_created", None)
        plan_info.pop("memory_created_date", None)
        plan_info.pop("memory_file", None)

        save_registry(registry)
        logger.info(f"[{MODULE_NAME}] Restored plan {plan_key} to open status")

        # 8. UPDATE DASHBOARDS: Sync dashboard files (handlers)
        dashboard_success = update_dashboard_local()
        central_success = push_to_plans_central()

        # Log dashboard update results
        if not dashboard_success:
            logger.warning(f"[{MODULE_NAME}] Failed to update DASHBOARD.local.json")
        if not central_success:
            logger.warning(f"[{MODULE_NAME}] Failed to update PLANS.central.json")

        # 9. Success message data
        restored_location = plan_info.get("location", "unknown")
        messages.append({"type": "restore_success", "plan_key": plan_key, "location": restored_location})

        # Fire trigger event for plan restore
        try:
            from aipass.trigger.apps.modules.core import trigger

            trigger.fire("plan_restored", plan_number=plan_key, location=restored_location)
        except ImportError:
            logger.info(f"[{MODULE_NAME}] Trigger module not available, skipping event fire")

        json_handler.log_operation(
            "plan_restored", {"plan_key": plan_key, "location": restored_location, "success": True}
        )
        return {
            "success": True,
            "messages": messages,
            "plan_key": plan_key,
            "restored_location": restored_location,
        }

    except ValueError:
        error_msg = f"Invalid plan number: {plan_num}"
        logger.warning(f"[{MODULE_NAME}] {error_msg}")
        return {
            "success": False,
            "messages": [{"type": "error", "error_type": "invalid_number", "plan_key": plan_num}],
            "plan_key": "",
            "restored_location": "",
        }

    except Exception as e:
        error_msg = f"Error restoring plan: {e}"
        logger.error(f"[{MODULE_NAME}] {error_msg}")
        return {
            "success": False,
            "messages": [{"type": "error", "error_type": "general", "details": str(e)}],
            "plan_key": "",
            "restored_location": "",
        }
