# =================== AIPass ====================
# Name: file_watcher_integration.py
# Description: File Watcher Integration
# Version: 0.1.0
# Created: 2025-11-23
# Modified: 2026-03-09
# =============================================

"""
File Watcher Integration Handler

Connects the file watcher (apps/handlers/watcher/monitor.py) to the
monitoring event queue (event_queue.py).

Flow:
1. Load branches from AIPASS_REGISTRY.json
2. Set up BranchFileHandler for each branch
3. Start watchdog observers
4. File events -> MonitoringEvent -> MonitoringQueue
5. Include branch attribution in all events

Thread Safety:
- Designed to run in monitor.py's file watcher thread
- Uses MonitoringQueue's thread-safe enqueue
- Watchdog observers run in their own threads

Linux Limitations:
- inotify has limits on watched files/directories
- Watching 18+ branches recursively may exceed system limits
- To increase: sudo sysctl fs.inotify.max_user_watches=524288
- Or filter branches to watch only active ones
"""

import json
import logging
from pathlib import Path
from typing import List, Tuple, Optional, Any
from datetime import datetime

from aipass.prax.apps.modules.logger import get_direct_logger

logger = get_direct_logger()

# =============================================================================
# IMPORTS - File watcher and event queue
# =============================================================================

try:
    # Import file watcher handler
    from aipass.prax.apps.handlers.watcher.monitor import (
        start_monitoring,
        stop_monitoring,
        WATCHDOG_AVAILABLE,
    )

    from aipass.prax.apps.handlers.monitoring.event_queue import MonitoringEvent, global_queue

except ImportError as e:
    logger.error(f"Import error in file_watcher_integration: {e}")
    WATCHDOG_AVAILABLE = False
    start_monitoring = None  # type: ignore[assignment]
    stop_monitoring = None  # type: ignore[assignment]
    MonitoringEvent = None  # type: ignore[assignment, misc]
    global_queue = None  # type: ignore[assignment]

from aipass.prax.apps.handlers.json import json_handler


# =============================================================================
# AIPASS REGISTRY LOADER
# =============================================================================


def load_branch_paths(branch_filter: Optional[List[str]] = None) -> List[Tuple[str, Path]]:
    """
    Load branch paths from AIPASS_REGISTRY.json

    Args:
        branch_filter: Optional list of branch names to watch (e.g., ['PRAX', 'CLI'])
                      If None, loads all branches from registry

    Returns:
        List of (branch_name, path) tuples
        Empty list if registry not found or error
    """
    try:
        from aipass.prax.apps.handlers.config.load import _find_repo_root

        registry_path = _find_repo_root() / "AIPASS_REGISTRY.json"

        if not registry_path.exists():
            logger.warning(f"AIPASS_REGISTRY.json not found at {registry_path}")
            return []

        with open(registry_path, encoding="utf-8") as f:
            data = json.load(f)

        branches = data.get("branches", [])
        if not branches:
            logger.warning("No branches found in AIPASS_REGISTRY.json")
            return []

        # Normalize filter to uppercase
        if branch_filter:
            branch_filter = [b.upper() for b in branch_filter]

        # Extract (name, path) tuples
        branch_paths = []
        for branch in branches:
            name = branch.get("name", "").upper()
            path_str = branch.get("path", "")

            if not name or not path_str:
                logger.warning(f"Skipping invalid branch entry: {branch}")
                continue

            # Apply filter if provided
            if branch_filter and name not in branch_filter:
                continue

            path = Path(path_str)
            if not path.exists():
                logger.warning(f"Branch path does not exist: {name} -> {path}")
                continue

            branch_paths.append((name, path))

        logger.info(f"Loaded {len(branch_paths)} branch paths from registry")
        return branch_paths

    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in AIPASS_REGISTRY.json: {e}")
        return []
    except Exception as e:
        logger.error(f"Error loading AIPASS_REGISTRY.json: {e}")
        return []


# =============================================================================
# EVENT CALLBACK - File events to MonitoringQueue
# =============================================================================


def file_event_callback(branch_name: str, event_type: str, file_path: str):
    """
    Callback for file system events from BranchFileHandler

    Converts file events to MonitoringEvent and enqueues to global queue.

    Args:
        branch_name: Name of branch where event occurred
        event_type: Event type ('CREATED', 'MODIFIED', 'DELETED', 'MOVED')
        file_path: Path to file (or "src -> dest" for MOVED)
    """
    try:
        # Map event type to action
        action_map = {"CREATED": "created", "MODIFIED": "modified", "DELETED": "deleted", "MOVED": "moved"}
        action = action_map.get(event_type, event_type.lower())

        # Determine priority based on event type
        # Deleted/Created are higher priority than modified
        priority_map = {"deleted": 2, "created": 2, "moved": 2, "modified": 3}
        priority = priority_map.get(action, 3)

        # Create monitoring event
        event = MonitoringEvent(  # type: ignore[misc]
            priority=priority,
            timestamp=datetime.now(),
            event_type="file",
            branch=branch_name,
            action=action,
            message=file_path,
            level="info",
        )

        # Enqueue to global queue (thread-safe)
        success = global_queue.enqueue(event)  # type: ignore[union-attr]

        if not success:
            logger.info(f"Failed to enqueue file event: {branch_name} {action} {file_path}")

    except Exception as e:
        logger.error(f"Error in file_event_callback: {e}")


# =============================================================================
# FILE WATCHER MANAGER
# =============================================================================


class FileWatcherManager:
    """
    Manages file watcher lifecycle and observer threads

    Responsibilities:
    - Load branches from registry
    - Start/stop watchdog observers
    - Connect file events to monitoring queue
    """

    def __init__(self, queue: Any = None, branch_filter: List[str] | None = None):
        """
        Initialize file watcher manager

        Args:
            queue: MonitoringQueue to use (defaults to global_queue)
            branch_filter: Optional list of branch names to watch (e.g., ['PRAX', 'CLI'])
        """
        self.queue = queue or global_queue
        self.observer: Any = None
        self.branch_paths: List[Tuple[str, Path]] = []
        self.branch_filter = branch_filter
        self.running = False

    def start(self) -> bool:
        """
        Start file watching for all branches (or filtered branches)

        Returns:
            True if started successfully, False otherwise
        """
        if not WATCHDOG_AVAILABLE:
            logger.error("Cannot start file watcher - watchdog not installed")
            return False

        if self.running:
            logger.warning("File watcher already running")
            return True

        # Load branch paths from registry
        self.branch_paths = load_branch_paths(self.branch_filter)

        if not self.branch_paths:
            logger.error("No valid branches found - cannot start file watcher")
            return False

        # Start monitoring with callback
        logger.info(f"Starting file watcher for {len(self.branch_paths)} branches")
        self.observer = start_monitoring(self.branch_paths, file_event_callback)  # type: ignore[misc]

        if self.observer:
            self.running = True
            json_handler.log_operation("file_watcher_started", {"branches": len(self.branch_paths)})
            logger.info("File watcher started successfully")
            return True
        else:
            logger.error("Failed to start file watcher")
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


# =============================================================================
# MODULE-LEVEL API
# =============================================================================

# Global file watcher instance
_file_watcher: Optional[FileWatcherManager] = None


def get_file_watcher() -> FileWatcherManager:
    """
    Get singleton file watcher instance

    Returns:
        FileWatcherManager instance
    """
    global _file_watcher
    if _file_watcher is None:
        _file_watcher = FileWatcherManager()
    return _file_watcher


def start_file_watcher() -> bool:
    """
    Start file watching

    Returns:
        True if started successfully
    """
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


# =============================================================================
# STANDALONE TEST
# =============================================================================

if __name__ == "__main__":
    import time

    # Set up basic logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    print("File Watcher Integration Test")
    print("=" * 60)
    print()

    # Test 1: Load branch paths
    print("Test 1: Loading branch paths from registry")
    paths = load_branch_paths()
    print(f"Found {len(paths)} branches:")
    for name, path in paths[:5]:  # Show first 5
        print(f"  - {name}: {path}")
    if len(paths) > 5:
        print(f"  ... and {len(paths) - 5} more")
    print()

    # Test 2: Start file watcher (LIMITED to PRAX only to avoid inotify limits)
    print("Test 2: Starting file watcher (PRAX branch only)")
    watcher = FileWatcherManager(branch_filter=["PRAX"])

    if watcher.start():
        print("File watcher started successfully")
        print()

        # Show stats
        stats = watcher.get_stats()
        print("Watcher stats:")
        for key, value in stats.items():
            print(f"  {key}: {value}")
        print()

        # Monitor for a bit
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

        # Stop watcher
        print("Test 3: Stopping file watcher")
        watcher.stop()
        print("File watcher stopped")

    else:
        print("Failed to start file watcher")

    print()
    print("Test complete")
