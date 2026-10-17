# =================== AIPass ====================
# Name: file_watcher_integration.py
# Description: File Watcher Integration
# Version: 0.1.1
# Created: 2025-11-23
# Modified: 2026-10-17
# =============================================

"""File Watcher Integration Handler

Reference: docs/monitor.md. inotify limits: sudo sysctl fs.inotify.max_user_watches=524288."""

import json
import logging
from pathlib import Path
from typing import List, Tuple, Optional, Any
from datetime import datetime

from aipass.prax.apps.modules.logger import get_direct_logger
from aipass.prax.apps.handlers.json import json_handler

logger = get_direct_logger()

try:
    from aipass.prax.apps.handlers.watcher.monitor import (
        start_monitoring,
        stop_monitoring,
        WATCHDOG_AVAILABLE,
    )

    from aipass.prax.apps.handlers.monitoring.event_queue import MonitoringEvent, global_queue

except ImportError as e:
    logger.error(
        f"[file_watcher] The live monitor's file watching is OFF — a component it needs could not "
        f"be loaded ({type(e).__name__}). File changes will not appear on screen; the log feed and "
        f"the on-disk logs are unaffected."
    )
    WATCHDOG_AVAILABLE = False
    start_monitoring = None  # type: ignore[assignment]
    stop_monitoring = None  # type: ignore[assignment]
    MonitoringEvent = None  # type: ignore[assignment, misc]
    global_queue = None  # type: ignore[assignment]


def load_branch_paths(branch_filter: Optional[List[str]] = None) -> List[Tuple[str, Path]]:
    """Load branch paths from AIPASS_REGISTRY.json; [] when absent or unreadable"""
    try:
        from aipass.prax.apps.handlers.config.load import _find_repo_root

        registry_path = _find_repo_root() / "AIPASS_REGISTRY.json"

        # Opened, not checked first: spawn replaces the registry atomically, so exists() races.
        try:
            with open(registry_path, encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            logger.warning(
                f"[file_watcher] No branch registry at {registry_path}, so the live monitor will "
                f"watch no branches for file changes. The log feed is unaffected."
            )
            return []

        branches = data.get("branches", [])
        if not branches:
            logger.warning(
                "[file_watcher] The branch registry lists no branches, so the live monitor will "
                "watch none of them for file changes. The log feed is unaffected."
            )
            return []

        if branch_filter:
            branch_filter = [b.upper() for b in branch_filter]

        branch_paths = []
        for branch in branches:
            name = branch.get("name", "").upper()
            path_str = branch.get("path", "")

            if not name or not path_str:
                logger.warning(
                    f"[file_watcher] A branch in the registry has no name or no path, so the live "
                    f"monitor will not watch it for file changes. Entry: {branch}"
                )
                continue

            if branch_filter and name not in branch_filter:
                continue

            path = Path(path_str)
            if not path.exists():
                logger.warning(
                    f"[file_watcher] Branch {name} is in the registry but its folder is missing, so "
                    f"the live monitor will not watch it for file changes. Expected at: {path}"
                )
                continue

            branch_paths.append((name, path))

        logger.info(f"Loaded {len(branch_paths)} branch paths from registry")
        return branch_paths

    except json.JSONDecodeError as e:
        logger.error(
            f"[file_watcher] The branch registry is not valid JSON (line {e.lineno}), so the live "
            f"monitor will watch no branches for file changes. The log feed is unaffected and the "
            f"registry file was not modified."
        )
        return []
    except Exception as e:
        logger.error(
            f"[file_watcher] Could not read the branch registry ({type(e).__name__}), so the live "
            f"monitor will watch no branches for file changes. The log feed is unaffected and the "
            f"registry file was not modified."
        )
        return []


def file_event_callback(branch_name: str, event_type: str, file_path: str):
    """Callback for file system events from BranchFileHandler: enqueue a MonitoringEvent"""
    try:
        action_map = {"CREATED": "created", "MODIFIED": "modified", "DELETED": "deleted", "MOVED": "moved"}
        action = action_map.get(event_type, event_type.lower())

        priority_map = {"deleted": 2, "created": 2, "moved": 2, "modified": 3}
        priority = priority_map.get(action, 3)

        event = MonitoringEvent(  # type: ignore[misc]
            priority=priority,
            timestamp=datetime.now(),
            event_type="file",
            branch=branch_name,
            action=action,
            message=file_path,
            level="info",
        )

        success = global_queue.enqueue(event)  # type: ignore[union-attr]

        if not success:
            logger.info(
                f"[file_watcher] The live monitor display queue is full, or already showed this — "
                f"file change not added to the terminal monitor view ({branch_name} {action} "
                f"{file_path}). The file itself is fine."
            )

    except Exception as e:
        # event_type, not action: action is derived inside the try and may be unbound here.
        logger.error(
            f"[file_watcher] The live monitor could not show a file change — unexpected "
            f"{type(e).__name__} ({branch_name} {event_type} {file_path}). The file itself is fine; "
            f"file watching continues."
        )


class FileWatcherManager:
    """Manages file watcher lifecycle and observer threads"""

    def __init__(self, queue: Any = None, branch_filter: List[str] | None = None):
        """Initialize file watcher manager; queue defaults to global_queue"""
        self.queue = queue or global_queue
        self.observer: Any = None
        self.branch_paths: List[Tuple[str, Path]] = []
        self.branch_filter = branch_filter
        self.running = False

    def start(self) -> bool:
        """Start file watching for all branches (or filtered branches)"""
        if not WATCHDOG_AVAILABLE:
            logger.error(
                "[file_watcher] The live monitor cannot watch files — the watchdog package is not "
                "installed. File changes will not appear on screen; the log feed is unaffected."
            )
            return False

        if self.running:
            logger.warning(
                "[file_watcher] The live monitor's file watching is already running — "
                "the start request was ignored, nothing changed."
            )
            return True

        self.branch_paths = load_branch_paths(self.branch_filter)

        if not self.branch_paths:
            logger.error(
                "[file_watcher] No watchable branches were found, so the live monitor's file "
                "watching did not start. File changes will not appear on screen; the log feed is "
                "unaffected."
            )
            return False

        logger.info(f"Starting file watcher for {len(self.branch_paths)} branches")
        self.observer = start_monitoring(self.branch_paths, file_event_callback)  # type: ignore[misc]

        if self.observer:
            self.running = True
            json_handler.log_operation("file_watcher_started", {"branches": len(self.branch_paths)})
            logger.info("File watcher started successfully")
            return True
        else:
            logger.error(
                "[file_watcher] The live monitor's file watching could not be started. File changes "
                "will not appear on screen; the log feed and the on-disk logs are unaffected."
            )
            return False

    def stop(self):
        """Stop file watching"""
        if not self.running:
            return

        if self.observer:
            logger.info("Stopping file watcher")
            stop_monitoring(self.observer)  # type: ignore[misc]
            self.observer = None

        self.running = False
        logger.info("File watcher stopped")

    def is_running(self) -> bool:
        """Check if file watcher is running"""
        return self.running

    def get_stats(self) -> dict:
        """Get file watcher statistics"""
        return {
            "running": self.running,
            "branches_watched": len(self.branch_paths),
            "branch_names": [name for name, _ in self.branch_paths],
            "watchdog_available": WATCHDOG_AVAILABLE,
        }


_file_watcher: Optional[FileWatcherManager] = None


def get_file_watcher() -> FileWatcherManager:
    """Get singleton file watcher instance"""
    global _file_watcher
    if _file_watcher is None:
        _file_watcher = FileWatcherManager()
    return _file_watcher


def start_file_watcher() -> bool:
    """Start file watching"""
    return get_file_watcher().start()


def stop_file_watcher():
    """Stop file watching"""
    get_file_watcher().stop()


def is_file_watcher_running() -> bool:
    """Check if file watcher is running"""
    return get_file_watcher().is_running()


def get_file_watcher_stats() -> dict:
    """Get file watcher statistics"""
    return get_file_watcher().get_stats()


if __name__ == "__main__":
    import time

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    print("File Watcher Integration Test")
    print("=" * 60)
    print()

    print("Test 1: Loading branch paths from registry")
    paths = load_branch_paths()
    print(f"Found {len(paths)} branches:")
    for name, path in paths[:5]:  # Show first 5
        print(f"  - {name}: {path}")
    if len(paths) > 5:
        print(f"  ... and {len(paths) - 5} more")
    print()

    print("Test 2: Starting file watcher (PRAX branch only)")
    watcher = FileWatcherManager(branch_filter=["PRAX"])

    if watcher.start():
        print("File watcher started successfully")
        print()

        stats = watcher.get_stats()
        print("Watcher stats:")
        for key, value in stats.items():
            print(f"  {key}: {value}")
        print()

        print("Monitoring for 10 seconds... (modify a file to test)")
        print("Watching queue for events...")
        print()

        start_time = time.time()
        event_count = 0

        while time.time() - start_time < 10:
            event = global_queue.dequeue(timeout=0.5)  # type: ignore[union-attr]
            if event:
                event_count += 1
                print(f"Event #{event_count}: {event.branch} - {event.action} - {event.message}")

        print()
        print(f"Captured {event_count} events in 10 seconds")
        print()

        print("Test 3: Stopping file watcher")
        watcher.stop()
        print("File watcher stopped")

    else:
        print("Failed to start file watcher")

    print()
    print("Test complete")
