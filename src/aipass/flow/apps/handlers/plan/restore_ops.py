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
from aipass.flow.apps.handlers.plan.registry_routing import (
    _extract_prefix,
    _resolve_registry_file,
    _find_plan_across_registries,
)

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


def recover_plan_from_backup(
    plan_key: str, plan_num_raw: str | None = None, load_registry: Any = None, save_registry: Any = None
) -> tuple[bool, str]:
    """
    Attempt to recover a plan from processed_plans backup.

    When ``plan_num_raw`` carries an explicit type prefix (e.g. "PPLAN-0011"),
    recovery is restricted to that type -- it will not silently recover a
    same-numbered backup from a different plan type (e.g. FPLAN-0011).
    Falls back to a plan-type-agnostic search (any prefix matching the plan
    key) only when no prefix was given.

    Args:
        plan_key: Normalized plan number (e.g., "0165")
        plan_num_raw: Original plan number as given by the caller, prefix
            intact (e.g. "PPLAN-0165"). Used to scope the backup search.
        load_registry: Registry loader function (injected from module)
        save_registry: Registry saver function (injected from module)

    Returns:
        (success, message)
    """
    # Check backup processed_plans directory
    processed_plans = PROCESSED_PLANS_DIR

    # If caller gave an explicit type prefix, restrict the search to it.
    # Otherwise fall back to matching any prefix against the plan key.
    requested_prefix = _extract_prefix(plan_num_raw) if plan_num_raw else None
    glob_pattern = f"{requested_prefix}-{plan_key}*.md" if requested_prefix else f"*-{plan_key}*.md"
    variants = list(processed_plans.glob(glob_pattern)) if processed_plans.exists() else []
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

    # Write into the registry matching the RECOVERED file's actual type
    # (not the caller-requested prefix or the default fplan registry) --
    # a same-numbered plan of another type must never collide with this entry.
    actual_prefix = _extract_prefix(plan_label)
    reg_file = f"{actual_prefix.lower()}_registry.json" if actual_prefix else None

    registry = load_registry(registry_file=reg_file) if reg_file else load_registry()
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
    if reg_file:
        save_registry(registry, registry_file=reg_file)
    else:
        save_registry(registry)

    return True, f"Recovered {plan_label} from {plan_file.name} to {original_location}"


def find_backup_copy(plan_info: Dict[str, Any], plan_key: str, backup_dir: Path | None = None) -> Path | None:
    """Locate the archived copy of an ALREADY-REGISTERED closed plan.

    Close archives the plan file out of the tree and leaves the registry row's
    ``file_path`` pointing at where the file used to be. Measured on this
    machine: 0 of 719 closed rows have a file at their registered path, while
    412 have an intact copy sitting in the archive. The net exists; nothing
    reached for it.

    Matching is by the row's OWN filename first, because that name carries the
    slug and the date. A bare ``PREFIX-NNNN.md`` husk is not a restore -- see
    the auto-renumber that erased exactly that and left an orphaned row.

    The glob fallback is TYPE-SCOPED. Every registry numbers from 0001, so
    ``*-0011*.md`` would happily hand back a DPLAN when an FPLAN was asked for.

    Args:
        plan_info: The registry row (its file_path supplies the wanted name)
        plan_key: Normalised plan number, e.g. "0011"
        backup_dir: Archive directory; defaults to the live processed_plans

    Returns:
        Path to the archived file, or None when nothing credible was found.
    """
    archive = backup_dir if backup_dir is not None else PROCESSED_PLANS_DIR
    if not archive.is_dir():
        logger.warning(f"[{MODULE_NAME}] Backup directory not present: {archive}")
        return None

    wanted = Path(plan_info.get("file_path", "") or "").name
    if wanted:
        exact = archive / wanted
        if exact.is_file():
            return exact

    prefix = _extract_prefix(Path(wanted).stem) if wanted else None
    if not prefix:
        # No type evidence on the row -- refuse rather than glob every type.
        logger.warning(f"[{MODULE_NAME}] Row {plan_key} carries no typed file_path; not searching backups")
        return None

    variants = sorted(archive.glob(f"{prefix}-{plan_key}*.md"), key=lambda f: f.stat().st_mtime, reverse=True)
    return variants[0] if variants else None


def restore_file_from_backup(plan_info: Dict[str, Any], plan_key: str, backup_dir: Path | None = None):
    """Copy a closed plan's archived file back to its registered location.

    Deliberately narrow, and NOT recover_plan_from_backup: that function
    rewrites the registry row with a synthetic one whose subject reads
    "Recovered from backup" and whose created date is now. Calling it on a row
    that already exists would destroy the real subject, the real creation date
    and the real location in the act of "recovering" them.

    COPY, never move. The archive stays intact, so a restore is repeatable and
    a failed restore has not consumed the only copy.

    Returns:
        (restored_path, message). restored_path is None on failure.
    """
    source = find_backup_copy(plan_info, plan_key, backup_dir=backup_dir)
    if source is None:
        return None, "no archived copy found"

    target = Path(plan_info.get("file_path", "") or "")
    if not target.name:
        return None, "registry row has no file_path to restore to"

    if not target.parent.is_dir():
        # The original directory is gone. Recreating it would invent a location
        # for a plan whose home no longer exists; naming it is more useful.
        return None, f"original location no longer exists: {target.parent}"

    try:
        copy2(source, target)
    except OSError as e:
        logger.error(f"[{MODULE_NAME}] Failed to copy {source} -> {target}: {e}")
        return None, f"copy failed: {e}"

    logger.info(f"[{MODULE_NAME}] Restored {target.name} from archive")
    json_handler.log_operation(
        "plan_file_restored_from_backup",
        {"plan_key": plan_key, "source": str(source), "target": str(target)},
    )
    return target, f"restored {target.name} from archive"


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
    restore_file_from_backup_fn: Any = restore_file_from_backup,
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
        requested_prefix = _extract_prefix(plan_num)

        # 2. LOAD DATA: Detect correct registry from prefix, then load
        # (mirrors close_ops -- a bare load_registry() always defaults to
        # fplan_registry.json and would silently resolve the wrong plan
        # whenever another type shares this number, e.g. PPLAN-0011 vs FPLAN-0011)
        reg_file = _resolve_registry_file(plan_num)
        if reg_file:
            registry = load_registry(registry_file=reg_file)
        else:
            # No prefix -- try default registry first
            registry = load_registry()
            exists_default, _ = validate_plan_exists(plan_key, registry)
            if not exists_default:
                # Search other registries
                found_reg = _find_plan_across_registries(plan_key, load_registry)
                if found_reg:
                    reg_file = found_reg
                    registry = load_registry(registry_file=reg_file)

        # 3. VALIDATE: Check plan exists (handler)
        exists, error_msg = validate_plan_exists(plan_key, registry)
        if not exists:
            # AUTO-RECOVERY: Try to recover from processed_plans
            messages.append({"type": "warning", "text": f"PLAN-{plan_key} not in registry - attempting recovery..."})
            recovered, recovery_msg = recover_plan_from_backup_fn(plan_key, plan_num)

            if recovered:
                messages.append({"type": "success", "text": recovery_msg})
                # Recovery writes into the registry matching the recovered
                # file's actual type -- find it if we didn't already know it
                if not reg_file:
                    reg_file = _find_plan_across_registries(plan_key, load_registry)
                registry = load_registry(registry_file=reg_file) if reg_file else load_registry()
                plan_info = registry["plans"][plan_key]
                plan_file = Path(plan_info.get("file_path", ""))
            else:
                logger.warning(f"[{MODULE_NAME}] {error_msg} - Recovery failed: {recovery_msg}")
                messages.append(
                    {
                        "type": "error",
                        "error_type": "not_found",
                        "plan_key": plan_key,
                        "prefix": requested_prefix or "FPLAN",
                    }
                )
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

        # Derive the plan's actual type prefix for display (from the resolved
        # file/registry, falling back to what the caller requested)
        plan_label = plan_file.stem if plan_file.name else f"PLAN-{plan_key}"
        plan_prefix = _extract_prefix(plan_label) or requested_prefix or "FPLAN"

        # 4. VALIDATE: Check plan is closed
        if plan_info.get("status") != "closed":
            logger.warning(f"[{MODULE_NAME}] Plan {plan_key} is already open")
            messages.append(
                {"type": "error", "error_type": "already_open", "plan_key": plan_key, "prefix": plan_prefix}
            )
            return {
                "success": False,
                "messages": messages,
                "plan_key": plan_key,
                "restored_location": "",
            }

        # 5. RECOVER OR REFUSE: the file is not where the registry says it is.
        # For a normally-closed plan it never is -- close archives it out of
        # the tree. This branch used to be a hard failure, which made restore
        # fail for 719 of 719 closed plans while 412 intact copies sat in the
        # archive it never looked in.
        if not plan_file.exists():
            recovered_path, recovery_msg = restore_file_from_backup_fn(plan_info, plan_key)
            if recovered_path is None:
                logger.warning(f"[{MODULE_NAME}] File not found at {plan_file} and {recovery_msg}")
                messages.append(
                    {"type": "error", "error_type": "file_missing", "plan_key": plan_key, "prefix": plan_prefix}
                )
                messages.append({"type": "dim", "text": f"  Archive lookup: {recovery_msg}"})
                return {
                    "success": False,
                    "messages": messages,
                    "plan_key": plan_key,
                    "restored_location": "",
                }
            plan_file = recovered_path
            messages.append({"type": "success", "text": f"  {recovery_msg}"})

        # 6. DISPLAY: Plan info header data
        messages.append({"type": "restore_header", "plan_key": plan_key, "plan_info": plan_info, "prefix": plan_prefix})

        # 7. UPDATE REGISTRY: Restore to open status
        plan_info["status"] = "open"

        # Remove all close-related metadata
        plan_info.pop("closed", None)
        plan_info.pop("closed_reason", None)
        plan_info.pop("memory_created", None)
        plan_info.pop("memory_created_date", None)
        plan_info.pop("memory_file", None)

        if reg_file:
            save_registry(registry, registry_file=reg_file)
        else:
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
        messages.append(
            {"type": "restore_success", "plan_key": plan_key, "location": restored_location, "prefix": plan_prefix}
        )

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
