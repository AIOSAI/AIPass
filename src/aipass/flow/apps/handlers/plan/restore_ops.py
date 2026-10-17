# =================== AIPass ====================
# Name: restore_ops.py
# Description: Plan Restore Implementation Handler
# Version: 1.4.0
# Created: 2026-03-08
# Modified: 2026-10-17
# =============================================

"""Plan Restore Operations Handler

Returns data dicts - module handles all display.
"""

from pathlib import Path, PurePosixPath, PureWindowsPath
from shutil import copy2
from datetime import datetime, timezone
from typing import Dict, Any, List

from aipass.prax import logger

from aipass.flow.apps.handlers.json import json_handler
from aipass.flow.apps.handlers.plan.registry_routing import (
    _extract_prefix,
    _resolve_registry_file,
    _find_plan_across_registries,
)


from aipass.flow.apps.handlers.repo_root import find_repo_root, module_file

_PKG_ROOT = module_file(__file__).parents[4]  # handlers/plan/ -> handlers/ -> apps/ -> flow/ -> aipass/
FLOW_ROOT = _PKG_ROOT / "flow"


def _find_repo_root() -> Path:
    """Walk up to the repo root (the directory holding AIPASS_REGISTRY.json)."""
    return find_repo_root(caller="restore_ops")


PROCESSED_PLANS_DIR = _find_repo_root() / ".backup" / "processed_plans"

MODULE_NAME = "restore_plan"


def _recorded_is_absolute(recorded: str) -> bool:
    """Is a path RECORDED IN THE REGISTRY absolute — in either dialect?
    Registries are shared across hosts, and Path.is_absolute() answers only for this one. Both checks
    are needed: PureWindowsPath calls ``/srv`` relative, PurePosixPath refuses a drive letter.
    """
    return PurePosixPath(recorded).is_absolute() or PureWindowsPath(recorded).is_absolute()


def recover_plan_from_backup(
    plan_key: str, plan_num_raw: str | None = None, load_registry: Any = None, save_registry: Any = None
) -> tuple[bool, str]:
    """Attempt to recover a plan from processed_plans backup.
    An explicit prefix in plan_num_raw restricts recovery to that type; never a same-numbered other type.
    Returns (success, message).
    """
    processed_plans = PROCESSED_PLANS_DIR

    requested_prefix = _extract_prefix(plan_num_raw) if plan_num_raw else None
    glob_pattern = f"{requested_prefix}-{plan_key}*.md" if requested_prefix else f"*-{plan_key}*.md"
    variants = list(processed_plans.glob(glob_pattern)) if processed_plans.exists() else []
    plan_file = None  # No default -- use variant search
    if variants:
        variants.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        plan_file = variants[0]  # Use most recent backup
    if plan_file is None or not plan_file.exists():
        return False, f"Plan {plan_key} not found in backups"

    try:
        with open(plan_file, "r", encoding="utf-8") as f:
            content = f.read()

        original_location = None
        for line in content.split("\n")[:20]:  # Check first 20 lines
            if line.startswith("**Location**:"):
                original_location = line.split("**Location**:")[1].strip()
                break

        if not original_location:
            original_location = str(FLOW_ROOT)

        if _recorded_is_absolute(original_location):
            # Re-homing a vanished absolute location would file the plan where its header never said.
            if not Path(original_location).is_dir():
                return False, (
                    f"Recorded location '{original_location}' for {plan_file.stem} no longer exists — "
                    f"refusing to restore somewhere else; recreate the directory or edit the plan header"
                )
        else:
            if original_location == "flow":
                original_location = str(FLOW_ROOT)
            else:
                potential_path = _PKG_ROOT / original_location
                if potential_path.exists():
                    original_location = str(potential_path)
                else:
                    original_location = str(FLOW_ROOT)

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

    plan_label = plan_file.stem  # e.g. "FPLAN-0165" or "DPLAN-0004"

    # The RECOVERED file's type picks the registry, so a same-numbered plan of another type never collides.
    actual_prefix = _extract_prefix(plan_label)
    reg_file = f"{actual_prefix.lower()}_registry.json" if actual_prefix else None

    # Load BEFORE the copy: a raise after it would leave a plan file no registry names.
    registry = load_registry(registry_file=reg_file) if reg_file else load_registry()

    target = Path(original_location) / plan_file.name
    copy2(plan_file, target)

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
    # An unsaved row means no recovery, even though the file was copied.
    if reg_file:
        saved = save_registry(registry, registry_file=reg_file)
    else:
        saved = save_registry(registry)
    if not saved:
        return False, (
            f"Copied {plan_file.name} to {target}, but could not save the registry, "
            f"so no row names it: {plan_label} was not recovered"
        )

    return True, f"Recovered {plan_label} from {plan_file.name} to {original_location}"


def find_backup_copy(plan_info: Dict[str, Any], plan_key: str, backup_dir: Path | None = None) -> Path | None:
    """Locate the archived copy of an ALREADY-REGISTERED closed plan.
    Close archives the file and leaves file_path pointing at the old spot. Match the row's own filename
    first (it carries slug and date); the glob fallback is type-scoped because every registry numbers from 0001.
    Returns None when nothing credible was found.
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
    Not recover_plan_from_backup: that rewrites the row with a synthetic one, destroying the real subject,
    date and location. Copy, never move, so a failed restore has not consumed the only copy.
    Returns (restored_path, message); restored_path is None on failure.
    """
    source = find_backup_copy(plan_info, plan_key, backup_dir=backup_dir)
    if source is None:
        return None, "no archived copy found"

    target = Path(plan_info.get("file_path", "") or "")
    if not target.name:
        return None, "registry row has no file_path to restore to"

    if not target.parent.is_dir():
        # Recreating a vanished directory would invent a home for the plan.
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


def restore_plan_impl(
    plan_num: str | None = None,
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
    """Implement plan restore workflow
    Returns a dict with keys success, messages, plan_key, restored_location.
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
        scan_plan_files()
        logger.info(f"[{MODULE_NAME}] Auto-heal scan completed")

        plan_key = normalize_plan_number(plan_num)
        requested_prefix = _extract_prefix(plan_num)

        # A bare load_registry() defaults to fplan and resolves the wrong plan when types share a number.
        reg_file = _resolve_registry_file(plan_num)
        if reg_file:
            registry = load_registry(registry_file=reg_file)
        else:
            registry = load_registry()
            exists_default, _ = validate_plan_exists(plan_key, registry)
            if not exists_default:
                found_reg = _find_plan_across_registries(plan_key, load_registry)
                if found_reg:
                    reg_file = found_reg
                    registry = load_registry(registry_file=reg_file)

        exists, error_msg = validate_plan_exists(plan_key, registry)
        if not exists:
            messages.append({"type": "warning", "text": f"PLAN-{plan_key} not in registry - attempting recovery..."})
            recovered, recovery_msg = recover_plan_from_backup_fn(plan_key, plan_num)

            if recovered:
                messages.append({"type": "success", "text": recovery_msg})
                # Recovery wrote to the recovered file's own type registry.
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

        plan_label = plan_file.stem if plan_file.name else f"PLAN-{plan_key}"
        plan_prefix = _extract_prefix(plan_label) or requested_prefix or "FPLAN"

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

        # A normally-closed plan's file is never at its registered path: close archives it.
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

        messages.append({"type": "restore_header", "plan_key": plan_key, "plan_info": plan_info, "prefix": plan_prefix})

        plan_info["status"] = "open"

        plan_info.pop("closed", None)
        plan_info.pop("closed_reason", None)
        plan_info.pop("memory_created", None)
        plan_info.pop("memory_created_date", None)
        plan_info.pop("memory_file", None)

        if reg_file:
            saved = save_registry(registry, registry_file=reg_file)
        else:
            saved = save_registry(registry)
        if not saved:
            logger.error(f"[{MODULE_NAME}] Could not save the registry: {plan_key} is still closed")
            messages.append(
                {
                    "type": "error",
                    "error_type": "general",
                    "plan_key": plan_key,
                    "details": "could not save the registry, so the plan is still closed. Run restore again.",
                    "prefix": plan_prefix,
                }
            )
            return {
                "success": False,
                "messages": messages,
                "plan_key": plan_key,
                "restored_location": "",
            }
        logger.info(f"[{MODULE_NAME}] Restored plan {plan_key} to open status")

        dashboard_success = update_dashboard_local()
        central_success = push_to_plans_central()

        # None is "flow has no dashboard", not a failure.
        if dashboard_success is False:
            logger.warning(f"[{MODULE_NAME}] Failed to update DASHBOARD.local.json")
        if not central_success:
            logger.warning(f"[{MODULE_NAME}] Failed to update PLANS.central.json")

        restored_location = plan_info.get("location", "unknown")
        messages.append(
            {"type": "restore_success", "plan_key": plan_key, "location": restored_location, "prefix": plan_prefix}
        )

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
