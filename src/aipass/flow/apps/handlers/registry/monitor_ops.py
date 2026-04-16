# =================== AIPass ====================
# Name: monitor_ops.py
# Description: Registry Monitor Implementation Handler
# Version: 1.1.0
# Created: 2026-03-08
# Modified: 2026-03-08
# =============================================

"""
Registry Monitor Operations Handler

Implements filesystem scanning, plan file watching, and registry healing logic.
Extracted from registry_monitor module.

Usage:
    from aipass.flow.apps.handlers.registry.monitor_ops import (
        scan_plan_files_impl, PlanFileWatcher,
        start_monitoring_impl, stop_monitoring_impl, get_status_impl
    )
"""

import os
import re
import time
import threading
from pathlib import Path
from typing import Callable, Dict, Any, List, Tuple, Optional
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from aipass.prax import logger
# logger imported from aipass.prax

from aipass.flow.apps.handlers.json import json_handler

# =============================================
# CONFIGURATION
# =============================================

MODULE_NAME = "registry_monitor"

# PLAN file pattern — matches any plan prefix (FPLAN, DPLAN, APLAN, RPLAN, TDPLAN, etc.)
PLAN_PATTERN = re.compile(r"^[A-Z]+PLAN-\d{4}\.md$")

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

# Global observer instance
_observer: Any = None
_observer_lock = threading.Lock()

# Event deduplication
_recent_events: List[Tuple[str, str, float]] = []  # [(event_type, plan_num, timestamp)]
DEDUPE_WINDOW = 2.0  # seconds


# =============================================
# FILE WATCHER CLASS
# =============================================


class PlanFileWatcher(FileSystemEventHandler):
    """Monitors PLAN file changes and fires trigger events"""

    def on_created(self, event):
        """Handle file creation events - fires trigger event"""
        if not event.is_directory and self._is_plan_file(str(event.src_path)):
            file_path = Path(str(event.src_path))
            plan_num = self._get_plan_number(file_path)

            if plan_num and not self._is_duplicate_event("created", plan_num):
                logger.info(f"[{MODULE_NAME}] New PLAN file detected: {file_path.name}")
                self._schedule_fire_created(file_path)

    def on_deleted(self, event):
        """Handle file deletion events - fires trigger event"""
        if not event.is_directory and self._is_plan_file(str(event.src_path)):
            file_path = Path(str(event.src_path))
            plan_num = self._get_plan_number(file_path)

            if plan_num and not self._is_duplicate_event("deleted", plan_num):
                logger.info(f"[{MODULE_NAME}] PLAN file deleted: {file_path.name}")
                self._schedule_fire_deleted(file_path)

    def on_moved(self, event):
        """Handle file move/rename events - fires trigger event"""
        if not event.is_directory and self._is_plan_file(str(event.dest_path)):
            src_path = Path(str(event.src_path))
            dest_path = Path(str(event.dest_path))
            plan_num = self._get_plan_number(dest_path)

            if plan_num and not self._is_duplicate_event("moved", plan_num):
                logger.info(f"[{MODULE_NAME}] PLAN file moved: {src_path.name} -> {dest_path}")
                self._schedule_fire_moved(src_path, dest_path)

    def _is_plan_file(self, file_path: str) -> bool:
        """Check if file is a PLAN file"""
        return PLAN_PATTERN.match(Path(file_path).name) is not None

    def _get_plan_number(self, file_path: Path) -> Optional[str]:
        """Extract plan number from filename (e.g., FPLAN-0001.md -> 0001, DPLAN-0005.md -> 0005)"""
        match = re.search(r"[A-Z]+PLAN-(\d{4})\.md$", file_path.name)
        return match.group(1) if match else None

    def _is_duplicate_event(self, event_type: str, plan_num: str) -> bool:
        """Check if this is a duplicate recent event"""
        global _recent_events
        now = time.time()

        # Clean old events
        _recent_events = [(et, pn, ts) for et, pn, ts in _recent_events if now - ts < DEDUPE_WINDOW]

        # Check for duplicates
        for et, pn, ts in _recent_events:
            if et == event_type and pn == plan_num:
                return True

        # Add to recent events
        _recent_events.append((event_type, plan_num, now))
        return False

    def _schedule_fire_created(self, file_path: Path):
        """Schedule trigger event with delay to avoid duplicate events"""
        timer = threading.Timer(0.5, self._fire_plan_file_created, args=(file_path,))
        timer.start()

    def _schedule_fire_deleted(self, file_path: Path):
        """Schedule trigger event with delay to avoid duplicate events"""
        timer = threading.Timer(0.5, self._fire_plan_file_deleted, args=(file_path,))
        timer.start()

    def _schedule_fire_moved(self, src_path: Path, dest_path: Path):
        """Schedule trigger event with delay to avoid duplicate events"""
        timer = threading.Timer(0.5, self._fire_plan_file_moved, args=(src_path, dest_path))
        timer.start()

    def _fire_plan_file_created(self, file_path: Path):
        """Fire plan_file_created event - Trigger handles registry update"""
        try:
            from aipass.trigger.apps.modules.core import trigger

            trigger.fire("plan_file_created", path=str(file_path))
        except ImportError:
            logger.warning(
                f"[{MODULE_NAME}] Trigger not available - plan_file_created event not fired for {file_path.name}"
            )

    def _fire_plan_file_deleted(self, file_path: Path):
        """Fire plan_file_deleted event - Trigger handles registry update"""
        try:
            from aipass.trigger.apps.modules.core import trigger

            trigger.fire("plan_file_deleted", path=str(file_path))
        except ImportError:
            logger.warning(
                f"[{MODULE_NAME}] Trigger not available - plan_file_deleted event not fired for {file_path.name}"
            )

    def _fire_plan_file_moved(self, src_path: Path, dest_path: Path):
        """Fire plan_file_moved event - Trigger handles registry update"""
        try:
            from aipass.trigger.apps.modules.core import trigger

            trigger.fire("plan_file_moved", src_path=str(src_path), dest_path=str(dest_path))
        except ImportError:
            logger.warning(
                f"[{MODULE_NAME}] Trigger not available - plan_file_moved event not fired for {dest_path.name}"
            )


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
        # Skip ignored directories (modify dirs in-place to prevent descent)
        dirs[:] = [d for d in dirs if not any(ignored in d for ignored in IGNORE_FOLDERS)]

        # Check for PLAN files in this directory
        for filename in files:
            if PLAN_PATTERN.match(filename):
                file_path = Path(root) / filename
                match = re.search(r"[A-Z]+PLAN-(\d{4})\.md$", filename)
                if match:
                    plan_number = match.group(1)

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

    # Fire events for orphaned registry entries (in registry but file doesn't exist)
    for plan_number in list(plans.keys()):
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
            f"[{MODULE_NAME}] Events fired - Created: {len(added)}, Moved: {len(updated)}, Deleted: {len(removed)}, Renumbered: {len(renumbered)}"
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
# MONITOR CONTROL IMPLEMENTATIONS
# =============================================


def start_monitoring_impl(ecosystem_root: Path) -> Dict[str, Any]:
    """Start PLAN file monitoring with watchdog

    Args:
        ecosystem_root: Root directory to watch

    Returns:
        Dict with keys: success (bool), message (str), status (str)
    """
    global _observer

    with _observer_lock:
        if _observer and _observer.is_alive():
            logger.info(f"[{MODULE_NAME}] Monitor already running")
            return {"success": False, "message": "Monitor is already running", "status": "already_running"}

        try:
            observer = Observer()
            observer.schedule(PlanFileWatcher(), str(ecosystem_root), recursive=True)
            observer.start()
            _observer = observer
            logger.info(f"[{MODULE_NAME}] PLAN file monitor started - watching {ecosystem_root}")
            return {"success": True, "message": f"Monitor started - watching {ecosystem_root}", "status": "started"}

        except Exception as e:
            logger.error(f"[{MODULE_NAME}] Error starting monitor: {e}")
            return {"success": False, "message": f"Error starting monitor: {e}", "status": "error"}


def stop_monitoring_impl() -> Dict[str, Any]:
    """Stop PLAN file monitoring

    Returns:
        Dict with keys: success (bool), message (str), status (str)
    """
    global _observer

    with _observer_lock:
        if _observer and _observer.is_alive():
            _observer.stop()
            _observer.join()
            _observer = None
            logger.info(f"[{MODULE_NAME}] PLAN file monitor stopped")
            return {"success": True, "message": "Monitor stopped", "status": "stopped"}
        else:
            logger.info(f"[{MODULE_NAME}] Monitor is not running")
            return {"success": False, "message": "Monitor is not running", "status": "not_running"}


def get_status_impl(
    ecosystem_root: Path, load_registry: Callable[[], Dict[str, Any]] = lambda: {"plans": {}}
) -> Dict[str, Any]:
    """Get monitoring status

    Args:
        ecosystem_root: Root directory being watched
        load_registry: Registry loader function (injected from module)

    Returns:
        Dict with monitoring status information
    """
    global _observer

    registry = load_registry()
    total_plans = len(registry.get("plans", {}))
    open_plans = sum(1 for p in registry.get("plans", {}).values() if p.get("status") == "open")

    with _observer_lock:
        is_running = _observer and _observer.is_alive()

    return {
        "module": MODULE_NAME,
        "version": "2.0.0",
        "monitoring_active": is_running,
        "watch_location": str(ecosystem_root),
        "total_plans": total_plans,
        "open_plans": open_plans,
        "ignore_folders": len(IGNORE_FOLDERS),
    }
