# =================== AIPass ====================
# Name: log_watcher.py
# Description: Centralized log file watcher for system_logs directory
# Version: 1.0.0
# Created: 2026-01-31
# Modified: 2026-01-31
# =============================================

"""
Centralized Log Watcher - Trigger owns all log event detection

Watches system_logs/ for log file changes.
Detects ERROR/WARNING/INFO entries and fires appropriate events.

Events fired:
    - error_detected: When ERROR level log detected (Medic v2 pipeline via registry_report)
    - error_logged: Monitoring-only event (no dispatch)
    - warning_logged: When WARNING level log detected

Architecture:
    - Trigger OWNS all file watching (filesystem events)
    - Prax/AI_Mail RESPOND to events, don't watch themselves
    - Consolidated from: Prax log_watcher.py, AI_Mail error_monitor.py
"""

import hashlib
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from aipass.prax import logger
from aipass.trigger.apps.config import TRIGGER_ROOT
from aipass.trigger.apps.handlers.json import json_handler

# Logger - use prax system_logger for Error_Handling and Log_Visibility standards
# logger imported from aipass.prax

# System logs directory (package-relative via config)
SYSTEM_LOGS_DIR = TRIGGER_ROOT.parent.parent.parent / "system_logs"

# Try to import watchdog
try:
    from watchdog.observers import Observer as WatchdogObserver
    from watchdog.events import FileSystemEventHandler as WatchdogFileSystemEventHandler

    WATCHDOG_AVAILABLE = True
except ImportError:
    logger.info("watchdog not available, log watcher disabled")
    WATCHDOG_AVAILABLE = False
    WatchdogObserver = None  # type: ignore
    WatchdogFileSystemEventHandler = object  # type: ignore

# Global observer instance
_log_observer: Any = None


def _generate_error_hash(module_name: str, message: str) -> str:
    """
    Generate hash for error deduplication.

    Args:
        module_name: Module that generated the error
        message: Error message content

    Returns:
        8-character hash string
    """
    content = f"{module_name}:{message}"
    return hashlib.md5(content.encode()).hexdigest()[:8]


def _detect_branch_from_log(log_file: str) -> str:
    """
    Detect branch from log filename.

    Log files follow pattern: branch_operation.log
    Example: seedgo_audit.log -> SEEDGO

    Args:
        log_file: Log filename or path

    Returns:
        Branch name in uppercase
    """
    try:
        name = Path(log_file).stem
        if "_" in name:
            parts = name.split("_")
            return parts[0].upper()
        return name.upper()
    except Exception as exc:
        logger.warning("Failed to detect branch from log '%s': %s", log_file, exc)
        return "UNKNOWN"


def _detect_log_level(log_line: str) -> str:
    """
    Detect log level from log line content.

    Args:
        log_line: Raw log line

    Returns:
        'error', 'warning', 'info', or 'debug'
    """
    if " - ERROR - " in log_line or " ERROR " in log_line or "[ERROR]" in log_line:
        return "error"
    if " - WARNING - " in log_line or " WARNING " in log_line or "[WARNING]" in log_line:
        return "warning"
    if " - CRITICAL - " in log_line or " CRITICAL " in log_line or "[CRITICAL]" in log_line:
        return "error"
    if " - DEBUG - " in log_line or " DEBUG " in log_line or "[DEBUG]" in log_line:
        return "debug"
    return "info"


def _parse_log_message(log_line: str) -> str:
    """
    Extract clean message from log line.

    Raw format: [BRANCH_NAME] TIMESTAMP | SOURCE | LEVEL | MESSAGE

    Args:
        log_line: Raw log line

    Returns:
        Cleaned message content
    """
    if " | " in log_line:
        parts = log_line.split(" | ")
        if len(parts) >= 4:
            return " | ".join(parts[3:]).strip()
        if len(parts) >= 2:
            return parts[-1].strip()
    return log_line.strip()


def _extract_module_name(log_line: str) -> str:
    """
    Extract module name from log line.

    Args:
        log_line: Raw log line

    Returns:
        Module name or 'unknown'
    """
    if " | " in log_line:
        parts = log_line.split(" | ")
        if len(parts) >= 2:
            return parts[1].strip()
    return "unknown"


def _should_skip_log(log_line: str) -> bool:
    """
    Filter out initialization noise.

    Args:
        log_line: Raw log line

    Returns:
        True if line should be skipped
    """
    noise_patterns = [
        "Initializing ",
        "Module initialized",
        "Module initialization completed",
        "Configuration loaded",
        "Data loaded",
        "Registry loaded",
        "loaded config from",
        "Cleanup completed - Removed 0",
    ]
    for pattern in noise_patterns:
        if pattern in log_line:
            return True
    return False


class LogFileWatcher(WatchdogFileSystemEventHandler if WATCHDOG_AVAILABLE else object):  # type: ignore[misc]
    """
    Watch log files and fire Trigger events.

    Centralized watcher - all log event detection goes through here.
    """

    def __init__(self):
        """Initialize log watcher with position tracking."""
        super().__init__()
        self.log_positions: Dict[str, int] = {}

    def _read_new_lines(self, file_path: str) -> None:
        """Read new content from a log file and process lines."""
        current_size = Path(file_path).stat().st_size
        last_pos = self.log_positions.get(file_path, 0)

        if current_size < last_pos:
            last_pos = 0
        if current_size <= last_pos:
            return

        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            f.seek(last_pos)
            new_lines = f.read()
            if new_lines.strip():
                branch = _detect_branch_from_log(file_path)
                for line in new_lines.strip().split("\n"):
                    if line.strip() and not _should_skip_log(line):
                        self._process_log_line(branch, line, file_path)
            self.log_positions[file_path] = f.tell()

    def on_modified(self, event):
        """
        Handle log file modification events.

        Reads new content and fires appropriate Trigger events.
        """
        if event.is_directory:
            return

        file_path = str(event.src_path)
        if not file_path.endswith(".log") or str(SYSTEM_LOGS_DIR) not in file_path:
            return

        try:
            self._read_new_lines(file_path)
        except Exception as exc:
            logger.warning("Failed to read log file '%s': %s", file_path, exc)

    def _process_log_line(self, branch: str, log_line: str, log_file: str) -> None:
        """
        Process a log line and fire appropriate events.

        Args:
            branch: Branch name
            log_line: Raw log line
            log_file: Path to log file
        """
        try:
            from aipass.trigger.apps.modules.core import trigger

            level = _detect_log_level(log_line)
            message = _parse_log_message(log_line)
            module_name = _extract_module_name(log_line)
            timestamp = datetime.now().isoformat()
            error_hash = _generate_error_hash(module_name, message)

            event_data = {
                "branch": branch,
                "message": message,
                "level": level,
                "module_name": module_name,
                "timestamp": timestamp,
                "log_file": log_file,
                "error_hash": error_hash,
            }

            if level == "error":
                # Route through Medic v2: registry_report() for dedup/count, then error_detected
                try:
                    from aipass.trigger.apps.handlers.error_registry import report as registry_report

                    result = registry_report(
                        error_type="ERROR", message=message, component=branch, log_path=log_file, severity="medium"
                    )
                    error_count = result.get("count", 1)
                    trigger.fire(
                        "error_detected",
                        branch=branch,
                        module=module_name,
                        message=message,
                        log_path=log_file,
                        error_hash=result.get("id", error_hash),
                        timestamp=timestamp,
                        fingerprint=result.get("fingerprint", ""),
                        registry_id=result.get("id", ""),
                        first_seen=result.get("first_seen", ""),
                        last_seen=result.get("last_seen", ""),
                        count=error_count,
                    )
                except Exception:
                    # Registry unavailable — fire error_logged as monitoring-only fallback
                    trigger.fire("error_logged", **event_data)
                json_handler.log_operation("system_log_event", {"level": level, "module": module_name})
            elif level == "warning":
                trigger.fire("warning_logged", **event_data)
                json_handler.log_operation("system_log_event", {"level": level, "module": module_name})

        except Exception as exc:
            logger.warning("Failed to process log line from '%s': %s", log_file, exc)

    def initialize_positions(self) -> None:
        """
        Initialize log positions to END of existing files.

        Only show NEW entries after watcher starts.
        """
        if not SYSTEM_LOGS_DIR.exists():
            return

        for log_file in SYSTEM_LOGS_DIR.glob("*.log"):
            try:
                self.log_positions[str(log_file)] = log_file.stat().st_size
            except Exception as exc:
                logger.warning("Failed to initialize position for '%s': %s", log_file, exc)


def start_log_watcher() -> Any:
    """
    Start the centralized log watcher.

    Returns:
        Observer instance (caller must keep alive)
    """
    global _log_observer

    if not WATCHDOG_AVAILABLE:
        return None

    if _log_observer and _log_observer.is_alive():
        stop_log_watcher()

    if not SYSTEM_LOGS_DIR.exists():
        return None

    watcher = LogFileWatcher()
    watcher.initialize_positions()
    _callback = watcher.on_modified  # watchdog dispatches FileSystemEvents here
    if WatchdogObserver is None:
        return None
    observer = WatchdogObserver()
    observer.schedule(watcher, str(SYSTEM_LOGS_DIR), recursive=False)
    observer.start()

    _log_observer = observer

    return observer


def stop_log_watcher() -> None:
    """Stop the log watcher."""
    global _log_observer

    if _log_observer and _log_observer.is_alive():
        _log_observer.stop()
        _log_observer.join(timeout=5.0)
        _log_observer = None


def is_log_watcher_active() -> bool:
    """
    Check if log watcher is running.

    Returns:
        True if watcher is active
    """
    return _log_observer is not None and _log_observer.is_alive()


if __name__ == "__main__":
    """Standalone test for log watcher."""
    import time

    print("Trigger Log Watcher Test")
    print(f"Monitoring: {SYSTEM_LOGS_DIR}")
    print("Press Ctrl+C to stop")
    print()

    observer = start_log_watcher()

    if not observer:
        print("Failed to start log watcher")
        sys.exit(1)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Log watcher stopped by user")
        print("\nStopping...")
        stop_log_watcher()
        print("Stopped")
