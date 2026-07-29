# =================== AIPass ====================
# Name: monitor_ops.py
# Description: Registry Monitor Implementation Handler
# Version: 2.0.1
# Created: 2026-03-08
# Modified: 2026-07-27
# =============================================

"""
Registry Monitor Operations Handler

Implements filesystem scanning and registry healing logic.

Usage:
    from aipass.flow.apps.handlers.registry.monitor_ops import (
        scan_plan_files_impl, get_status_impl
    )
"""

import os
import re
from pathlib import Path
from typing import Callable, Dict, Any, List

from aipass.prax import logger

from aipass.flow.apps.handlers.json import json_handler

# =============================================
# CONFIGURATION
# =============================================

MODULE_NAME = "registry_monitor"

# PLAN file pattern — matches any plan prefix (FPLAN, DPLAN, APLAN, RPLAN, TDPLAN, etc.)
# Real plan files carry a subject slug + date suffix: PREFIX-NNNN_slug_YYYY-MM-DD.md
# The slug is optional so bare PREFIX-NNNN.md (e.g. test fixtures) still matches.
PLAN_PATTERN = re.compile(r"^([A-Z]+PLAN)-(\d{4})(?:_.*)?\.md$")

# Directories to ignore during monitoring
IGNORE_FOLDERS = {
    # Development and version control
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
    # Backup and archive
    "backup",
    "backups",
    ".backup",
    "archive",
    ".archive",
    "backup",
    "archive_temp",
    "processed_plans",
    # Memory and admin
    "memory",
    "admin",
    "aipass-help",
    # User directories
    ".local",
    "Downloads",
    "downloads",
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


# =============================================
# HELPER
# =============================================


def _fire_event(event_name: str, **kwargs) -> bool:
    """
    Fire a trigger event (internal helper)

    Args:
        event_name: Name of the event to fire
        **kwargs: Event data

    Returns:
        True if event fired successfully, False otherwise
    """
    try:
        from aipass.trigger.apps.modules.core import trigger

        trigger.fire(event_name, **kwargs)
        return True
    except ImportError:
        logger.warning(f"[{MODULE_NAME}] Trigger not available - {event_name} event not fired")
        return False


# =============================================
# SCAN AND HEAL IMPLEMENTATION
# =============================================


def scan_plan_files_impl(
    ecosystem_root: Path, load_registry: Callable[[], Dict[str, Any]] = lambda: {"plans": {}}
) -> Dict[str, Any]:
    """
    Scan ecosystem for PLAN files and fire events to heal registry

    Fires events for:
    - Missing registry entries (plan_file_created)
    - Orphaned entries (plan_file_deleted)
    - Location mismatches (plan_file_moved)
    - Duplicate plan numbers are auto-renumbered on filesystem, then fire plan_file_created

    Architecture (v2.0):
    - This function DETECTS changes and FIRES events
    - Trigger handlers in plan_file.py HANDLE the registry updates
    - Flow never touches registry directly during scan

    Args:
        ecosystem_root: Root directory to scan from
        load_registry: Registry loader function (injected from module)

    Returns:
        Dict with scan results and event stats
    """
    logger.info(f"[{MODULE_NAME}] Starting PLAN file scan from: {ecosystem_root}")

    # Find all PLAN files (detect duplicates)
    plan_files: Dict[str, Path] = {}
    duplicates: Dict[str, List[Path]] = {}

    def handle_walk_error(error):
        """Handle permission errors during os.walk"""
        if not isinstance(error, PermissionError):
            logger.warning(f"[{MODULE_NAME}] Error during scan: {error}")

    # Use os.walk() with error handling
    for root, dirs, files in os.walk(str(ecosystem_root), topdown=True, onerror=handle_walk_error):
        # Skip ignored directories (modify dirs in-place to prevent descent).
        # Exact-name match — substring match ("dev" in "devpulse", "sys" in "system_logs")
        # silently skipped whole project trees, causing their open plans to read as orphaned.
        dirs[:] = [d for d in dirs if d not in IGNORE_FOLDERS]

        # Check for PLAN files in this directory
        for filename in files:
            match = PLAN_PATTERN.match(filename)
            if match:
                file_path = Path(root) / filename
                plan_number = match.group(2)

                # Duplicate detection
                if plan_number in plan_files:
                    if plan_number not in duplicates:
                        duplicates[plan_number] = [plan_files[plan_number]]
                    duplicates[plan_number].append(file_path)
                    logger.warning(f"[{MODULE_NAME}] Duplicate plan {filename} found: {file_path}")
                else:
                    plan_files[plan_number] = file_path

    # Auto-renumber duplicates (keep first, renumber rest)
    renumbered: List[Dict[str, str]] = []
    if duplicates:
        logger.warning(f"[{MODULE_NAME}] Found {len(duplicates)} duplicate PLAN files")

        # Get next available plan number
        current_max = max(int(num) for num in plan_files.keys()) if plan_files else 0
        next_available = current_max + 1

        for plan_num, paths in duplicates.items():
            # Keep first occurrence, renumber the rest
            for dup_path in paths[1:]:  # Skip first path (already in plan_files)
                old_name = dup_path.name
                # Preserve original plan prefix (FPLAN, DPLAN, TDPLAN, etc.)
                prefix_match = re.match(r"^([A-Z]+PLAN)", old_name)
                dup_prefix = prefix_match.group(1) if prefix_match else "FPLAN"
                new_num = f"{next_available:04d}"
                new_name = f"{dup_prefix}-{new_num}.md"
                new_path = dup_path.parent / new_name

                try:
                    # Rename file on filesystem
                    dup_path.rename(new_path)
                    logger.info(f"[{MODULE_NAME}] Auto-renumbered: {old_name} -> {new_name} at {dup_path.parent}")

                    # Add to plan_files with new number
                    plan_files[new_num] = new_path
                    renumbered.append({"old_number": plan_num, "new_number": new_num, "path": str(new_path)})

                    next_available += 1
                except Exception as e:
                    logger.error(f"[{MODULE_NAME}] Failed to renumber {old_name}: {e}")

    # Load current registry to compare (read-only - we don't modify it here)
    registry = load_registry()
    plans = registry.get("plans", {})

    # Track events fired
    added: List[str] = []
    updated: List[str] = []
    removed: List[str] = []

    # Fire events for missing files (not in registry)
    for plan_number, file_path in plan_files.items():
        if plan_number not in plans:
            # File exists but not in registry - fire created event
            if _fire_event("plan_file_created", path=str(file_path)):
                added.append(plan_number)
                logger.info(f"[{MODULE_NAME}] Fired plan_file_created for {file_path.name}")
        else:
            # Check if location changed (file moved)
            current_path = plans[plan_number].get("file_path", "")
            if current_path != str(file_path):
                # Fire moved event
                if _fire_event("plan_file_moved", src_path=current_path, dest_path=str(file_path)):
                    updated.append(plan_number)
                    logger.info(f"[{MODULE_NAME}] Fired plan_file_moved for {file_path.name}")

    # Fire events for orphaned registry entries (in registry but file doesn't exist).
    # Closed plans are expected to be archived out of the scanned tree (see IGNORE_FOLDERS) —
    # treating that as "deleted" every scan is what caused the runaway log (305 closed plans
    # logged as orphaned on every single run). Only open plans can be genuinely orphaned.
    for plan_number in list(plans.keys()):
        if plans[plan_number].get("status") == "closed":
            continue
        if plan_number not in plan_files:
            # Registry entry but no file - fire deleted event
            orphan_path = plans[plan_number].get("file_path", "")
            orphan_name = Path(orphan_path).name if orphan_path else f"PLAN-{plan_number}.md"
            if _fire_event("plan_file_deleted", path=orphan_path or f"PLAN-{plan_number}.md"):
                removed.append(plan_number)
                logger.info(f"[{MODULE_NAME}] Fired plan_file_deleted for {orphan_name}")

    # Log event results
    if added or updated or removed or renumbered:
        logger.info(
            "[%s] Events fired - Created: %d, Moved: %d, Deleted: %d, Renumbered: %d",
            MODULE_NAME,
            len(added),
            len(updated),
            len(removed),
            len(renumbered),
        )

    # Reload registry to get updated count (after handlers processed events)
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
            "renumbered": len(renumbered),
            "success": True,
        },
    )

    return {
        "total_plans": total_plans,
        "added": added,
        "updated": updated,
        "removed": removed,
        "renumbered": renumbered,
        "healing_performed": len(added) + len(updated) + len(removed) + len(renumbered) > 0,
    }


# =============================================
# STATUS IMPLEMENTATION
# =============================================


def get_status_impl(
    ecosystem_root: Path, load_registry: Callable[[], Dict[str, Any]] = lambda: {"plans": {}}
) -> Dict[str, Any]:
    """Get registry status

    Args:
        ecosystem_root: Root directory being watched
        load_registry: Registry loader function (injected from module)

    Returns:
        Dict with registry status information
    """
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
