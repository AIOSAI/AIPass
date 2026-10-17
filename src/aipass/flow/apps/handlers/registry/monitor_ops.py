# =================== AIPass ====================
# Name: monitor_ops.py
# Description: Registry Monitor Implementation Handler
# Version: 2.1.0
# Created: 2026-03-08
# Modified: 2026-10-17
# =============================================

"""Registry Monitor Operations Handler"""

import os
import re
from pathlib import Path
from typing import Callable, Dict, Any, List, Optional, Tuple

from aipass.prax import logger

from aipass.flow.apps.handlers.json import json_handler


MODULE_NAME = "registry_monitor"

# The slug is optional so a bare PREFIX-NNNN.md still matches.
PLAN_PATTERN = re.compile(r"^([A-Z]+PLAN)-(\d{4})(?:_.*)?\.md$")

IGNORE_FOLDERS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    ".pytest_cache",
    "dist",
    "build",
    ".idea",
    ".vscode",
    "backup",
    "backups",
    ".backup",
    "archive",
    ".archive",
    "backup",
    "archive_temp",
    "processed_plans",
    "memory",
    "admin",
    "aipass-help",
    ".local",
    "Downloads",
    "downloads",
    "dropbox",
    # System directories (permission issues)
    "proc",
    "sys",
    "dev",
    "run",
    "boot",
    "lost+found",
    "timeshift",
    "snapshots",
    ".snapshots",
}


def is_plan_file(path: Path) -> Optional[bool]:
    """True if ``path`` is a plan, not only a file named like one.
    A plan opens with ``# {PREFIX}-{NNNN}: `` (older templates: `` - ``) matching its filename; a report
    named after a plan matches PLAN_PATTERN and nothing else.
    Returns None when the file cannot be read; every caller treats None as "never rename, register or close".
    """
    match = PLAN_PATTERN.match(path.name)
    if not match:
        return False
    try:
        with open(path, "r", encoding="utf-8") as fh:
            first_line = fh.readline()
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning(f"[{MODULE_NAME}] Cannot read {path} to tell a plan from a look-alike, leaving it: {exc}")
        return None
    plan_id = f"# {match.group(1)}-{match.group(2)}"
    return first_line.startswith((f"{plan_id}:", f"{plan_id} - "))


def _fire_event(event_name: str, **kwargs) -> bool:
    """Fire a trigger event (internal helper)"""
    try:
        from aipass.trigger.apps.modules.core import trigger

        trigger.fire(event_name, **kwargs)
        return True
    except ImportError:
        logger.warning(f"[{MODULE_NAME}] Trigger not available - {event_name} event not fired")
        return False


def scan_plan_files_impl(
    ecosystem_root: Path, load_registry: Callable[[], Dict[str, Any]] = lambda: {"plans": {}}
) -> Dict[str, Any]:
    """Scan ecosystem for PLAN files and fire events to heal registry
    Detects and fires events only; trigger handlers in plan_file.py update the registry. Duplicate
    plan numbers are reported in "duplicates", never renamed.
    """
    logger.info(f"[{MODULE_NAME}] Starting PLAN file scan from: {ecosystem_root}")

    plan_files: Dict[Tuple[str, str], Path] = {}
    duplicates: Dict[Tuple[str, str], List[Path]] = {}

    def handle_walk_error(error):
        """Handle permission errors during os.walk"""
        if not isinstance(error, PermissionError):
            logger.warning(f"[{MODULE_NAME}] Error during scan: {error}")

    found: List[Tuple[Tuple[str, str], Path]] = []
    for root, dirs, files in os.walk(str(ecosystem_root), topdown=True, onerror=handle_walk_error):
        # Exact-name match: a substring match ("dev" in "devpulse") skips whole project trees.
        dirs[:] = [d for d in dirs if d not in IGNORE_FOLDERS]

        for filename in files:
            match = PLAN_PATTERN.match(filename)
            if match and is_plan_file(Path(root) / filename):
                # Keyed by (prefix, number): every type numbers from 0001, so APLAN-0007 is not FPLAN-0007.
                found.append(((match.group(1), match.group(2)), Path(root) / filename))

    # os.walk order is OS order; sorting makes "first occurrence" the same file every run.
    found.sort(key=lambda entry: str(entry[1]))

    for plan_key, file_path in found:
        if plan_key in plan_files:
            if plan_key not in duplicates:
                duplicates[plan_key] = [plan_files[plan_key]]
            duplicates[plan_key].append(file_path)
            logger.warning(f"[{MODULE_NAME}] Duplicate plan {file_path.name} found: {file_path}")
        else:
            plan_files[plan_key] = file_path

    # Which of two real plans keeps a number is a human's call, so duplicates are only reported.
    duplicate_report: List[Dict[str, Any]] = [
        {"prefix": dup_prefix, "number": plan_num, "paths": [str(p) for p in paths]}
        for (dup_prefix, plan_num), paths in duplicates.items()
    ]
    if duplicate_report:
        logger.warning(f"[{MODULE_NAME}] Found {len(duplicate_report)} duplicate plan number(s), none renamed")

    registry = load_registry()
    plans = registry.get("plans", {})

    added: List[str] = []
    updated: List[str] = []
    removed: List[str] = []

    # `plans` is one registry type (FPLAN by default): other types' files re-fire plan_file_created every scan.
    for (_plan_prefix, plan_number), file_path in plan_files.items():
        if plan_number not in plans:
            if _fire_event("plan_file_created", path=str(file_path)):
                added.append(plan_number)
                logger.info(f"[{MODULE_NAME}] Fired plan_file_created for {file_path.name}")
        else:
            current_path = plans[plan_number].get("file_path", "")
            if current_path != str(file_path):
                if _fire_event("plan_file_moved", src_path=current_path, dest_path=str(file_path)):
                    updated.append(plan_number)
                    logger.info(f"[{MODULE_NAME}] Fired plan_file_moved for {file_path.name}")

    # Closed plans are archived out of the scanned tree, so only open plans can be orphaned.
    # Bare numbers here: the single-type `plans` registry is keyed that way.
    disk_numbers = {num for _pfx, num in plan_files}
    for plan_number in list(plans.keys()):
        if plans[plan_number].get("status") == "closed":
            continue
        if plan_number not in disk_numbers:
            orphan_path = plans[plan_number].get("file_path", "")
            orphan_name = Path(orphan_path).name if orphan_path else f"PLAN-{plan_number}.md"
            if _fire_event("plan_file_deleted", path=orphan_path or f"PLAN-{plan_number}.md"):
                removed.append(plan_number)
                logger.info(f"[{MODULE_NAME}] Fired plan_file_deleted for {orphan_name}")

    if added or updated or removed or duplicate_report:
        logger.info(
            "[%s] Events fired - Created: %d, Moved: %d, Deleted: %d, Duplicates reported: %d",
            MODULE_NAME,
            len(added),
            len(updated),
            len(removed),
            len(duplicate_report),
        )

    # Reload: the trigger handlers have updated the registry since the first load.
    registry = load_registry()
    total_plans = len(registry.get("plans", {}))

    logger.info(f"[{MODULE_NAME}] Scan complete - {total_plans} PLAN files in registry")

    json_handler.log_operation(
        "plan_files_scanned",
        {
            "total_plans": total_plans,
            "added": len(added),
            "updated": len(updated),
            "removed": len(removed),
            "duplicates": len(duplicate_report),
            "success": True,
        },
    )

    return {
        "total_plans": total_plans,
        "added": added,
        "updated": updated,
        "removed": removed,
        "duplicates": duplicate_report,
        "healing_performed": len(added) + len(updated) + len(removed) > 0,
    }


def get_status_impl(
    ecosystem_root: Path, load_registry: Callable[[], Dict[str, Any]] = lambda: {"plans": {}}
) -> Dict[str, Any]:
    """Get registry status"""
    registry = load_registry()
    total_plans = len(registry.get("plans", {}))
    open_plans = sum(1 for p in registry.get("plans", {}).values() if p.get("status") == "open")

    return {
        "module": MODULE_NAME,
        "version": "2.0.0",
        "monitoring_active": False,
        "watch_location": str(ecosystem_root),
        "total_plans": total_plans,
        "open_plans": open_plans,
        "ignore_folders": len(IGNORE_FOLDERS),
    }
