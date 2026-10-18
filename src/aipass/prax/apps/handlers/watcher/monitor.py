# =================== AIPass ====================
# Name: monitor.py
# Description: File System Monitor Handler
# Version: 0.1.0
# Created: 2025-11-15
# Modified: 2026-10-17
# =============================================

"""File System Monitor Handler"""

from typing import List, Callable, Any

from aipass.prax.apps.modules.logger import get_direct_logger
from aipass.prax.apps.handlers.json import json_handler

logger = get_direct_logger()

try:
    from watchdog.observers import Observer  # type: ignore
    from watchdog.events import FileSystemEventHandler  # type: ignore
    from watchdog.events import FileSystemEvent  # type: ignore

    WATCHDOG_AVAILABLE = True
except ImportError as e:
    logger.info(f"[monitor] watchdog not available, using placeholders: {e}")
    WATCHDOG_AVAILABLE = False

    class Observer:  # type: ignore
        """Placeholder when watchdog unavailable."""

        def schedule(self, *args, **kwargs):
            return None

        def start(self):
            return None

        def stop(self):
            return None

        def join(self):
            return None

    class FileSystemEventHandler:  # type: ignore
        """Placeholder when watchdog unavailable."""

    class FileSystemEvent:  # type: ignore
        """Placeholder when watchdog unavailable."""


class BranchFileHandler(FileSystemEventHandler):
    """Custom file system event handler for branch monitoring; ignores logs to prevent infinite loops."""

    def __init__(self, branch_name: str, callback: Callable):
        """Initialize handler"""
        super().__init__()
        self.branch_name = branch_name
        self.callback = callback

    def _should_ignore(self, path: str) -> bool:
        """Check if file should be ignored"""
        if path.endswith(".log"):
            return True

        if ".tmp." in path or path.endswith(".tmp"):
            return True
        if path.endswith(".backup") or path.endswith(".bak"):
            return True
        if path.endswith("~"):  # Editor backup files
            return True
        if path.endswith(".swp") or path.endswith(".swo"):  # Vim swap files
            return True

        if "/logs/" in path or "/system_logs/" in path:
            return True

        ignore_dirs = [
            "/.claude/",
            "/.local/",
            "/.cache/",
            "/.config/",
            "/.vscode/",
            "/.git/",
            "/__pycache__/",
            "/.pytest_cache/",
            "/node_modules/",
            "/.venv/",
            "/venv/",
        ]

        for ignore_dir in ignore_dirs:
            if ignore_dir in path:
                return True

        return False

    def on_created(self, event) -> None:
        """File or directory created"""
        if not event.is_directory and not self._should_ignore(event.src_path):
            self.callback(self.branch_name, "CREATED", event.src_path)

    def on_modified(self, event) -> None:
        """File or directory modified"""
        if not event.is_directory and not self._should_ignore(event.src_path):
            self.callback(self.branch_name, "MODIFIED", event.src_path)

    def on_deleted(self, event) -> None:
        """File or directory deleted"""
        if not event.is_directory and not self._should_ignore(event.src_path):
            self.callback(self.branch_name, "DELETED", event.src_path)

    def on_moved(self, event) -> None:
        """File or directory moved/renamed"""
        if not event.is_directory and not self._should_ignore(event.src_path):
            self.callback(self.branch_name, "MOVED", f"{event.src_path} → {event.dest_path}")


def start_monitoring(branch_paths: List[tuple], callback: Callable) -> Any:
    """Start monitoring (branch_name, path) tuples; None if watchdog is not available."""
    if not WATCHDOG_AVAILABLE:
        return None

    observer = Observer()

    for branch_name, path in branch_paths:
        if not path.exists():
            continue

        event_handler = BranchFileHandler(branch_name, callback)
        observer.schedule(event_handler, str(path), recursive=True)

    observer.start()

    json_handler.log_operation("watcher_monitor_event", {"branches_monitored": len(branch_paths)})

    return observer


def stop_monitoring(observer: Any) -> None:
    """Stop monitoring"""
    if observer:
        observer.stop()
        observer.join()
