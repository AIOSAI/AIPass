# =================== AIPass ====================
# Name: log_watcher.py
# Description: Centralized log file watcher for system_logs directory
# Version: 1.3.0
# Created: 2026-01-31
# Modified: 2026-10-17
# =============================================

"""
Centralized Log Watcher - Trigger owns all log event detection

Fires error_detected and warning_logged; no `error_logged` event exists, do not advertise one.
"""

import hashlib
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from aipass.prax import logger
from aipass.trigger.apps.config import TRIGGER_ROOT
from aipass.trigger.apps.handlers.json import json_handler

SYSTEM_LOGS_DIR = TRIGGER_ROOT.parent.parent.parent / "system_logs"

# Sole owner of system_logs; see start_log_watcher() for why this module does not watch it.
SYSTEM_LOGS_OWNER = "branch_log_events"

# Must match prax RotatingFileHandler backup_count.
MAX_BACKUP_CHAIN_DEPTH = 3

try:
    from watchdog.observers import Observer as WatchdogObserver
    from watchdog.events import FileSystemEventHandler as WatchdogFileSystemEventHandler

    WATCHDOG_AVAILABLE = True
except ImportError:
    logger.info("watchdog not available, log watcher disabled")
    WATCHDOG_AVAILABLE = False
    WatchdogObserver = None  # type: ignore
    WatchdogFileSystemEventHandler = object  # type: ignore

_log_observer: Any = None


def generate_error_hash(module_name: str, message: str) -> str:
    """Generate hash for error deduplication."""
    content = f"{module_name}:{message}"
    return hashlib.md5(content.encode()).hexdigest()[:8]


def detect_branch_from_log(log_file: str) -> str:
    """Detect branch from log filename: seedgo_audit.log -> SEEDGO."""
    try:
        name = Path(log_file).stem
        if "_" in name:
            parts = name.split("_")
            return parts[0].upper()
        return name.upper()
    except Exception as exc:
        logger.warning("Failed to detect branch from log '%s': %s", log_file, exc)
        return "UNKNOWN"


def detect_log_level(log_line: str) -> str:
    """Detect log level from log line content."""
    if " - ERROR - " in log_line or " ERROR " in log_line or "[ERROR]" in log_line:
        return "error"
    if " - WARNING - " in log_line or " WARNING " in log_line or "[WARNING]" in log_line:
        return "warning"
    if " - CRITICAL - " in log_line or " CRITICAL " in log_line or "[CRITICAL]" in log_line:
        return "error"
    if " - DEBUG - " in log_line or " DEBUG " in log_line or "[DEBUG]" in log_line:
        return "debug"
    return "info"


def parse_log_message(log_line: str) -> str:
    """Extract clean message from log line: [BRANCH_NAME] TIMESTAMP | SOURCE | LEVEL | MESSAGE."""
    if " | " in log_line:
        parts = log_line.split(" | ")
        if len(parts) >= 4:
            return " | ".join(parts[3:]).strip()
        if len(parts) >= 2:
            return parts[-1].strip()
    return log_line.strip()


def extract_module_name(log_line: str) -> str:
    """Extract module name from log line."""
    if " | " in log_line:
        parts = log_line.split(" | ")
        if len(parts) >= 2:
            return parts[1].strip()
    return "unknown"


def should_skip_log(log_line: str) -> bool:
    """Filter out initialization noise."""
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
    """Watch log files and fire Trigger events."""

    def __init__(self):
        """Initialize log watcher with position tracking."""
        super().__init__()
        self.log_positions: Dict[str, int] = {}
        self.log_inodes: Dict[str, int] = {}

    def _record_position(self, file_path: str, position: int) -> None:
        """Record byte position and inode; the inode tells rotation from in-place truncation."""
        self.log_positions[file_path] = position
        try:
            self.log_inodes[file_path] = Path(file_path).stat().st_ino
        except OSError as exc:
            logger.warning("Failed to record inode for '%s': %s", file_path, exc)
            self.log_inodes.pop(file_path, None)

    def _drain_rotated_tail(self, file_path: str, last_pos: int) -> None:
        """
        Process the unread tail of a log file that was just rotated away.

        Only the backup whose inode matches the recorded one is drained; anything uncertain skips rather than re-fires.
        Backups skipped past are deliberately not replayed (a flood of historical events is worse than the gap).
        """
        known_inode = self.log_inodes.get(file_path)
        if not known_inode or last_pos <= 0:
            return

        try:
            rotated: Optional[Path] = None
            skipped = 0
            for index in range(1, MAX_BACKUP_CHAIN_DEPTH + 1):
                backup = Path(f"{file_path}.{index}")
                if not backup.exists():
                    break
                if backup.stat().st_ino == known_inode:
                    rotated = backup
                    skipped = index - 1
                    break
            if rotated is None:
                return
            if skipped:
                logger.warning(
                    "Rotated log found at '%s' - %d earlier backup(s) rotated past unread (not replayed)",
                    rotated,
                    skipped,
                )
            if rotated.stat().st_size <= last_pos:
                return
            with open(rotated, "r", encoding="utf-8", errors="ignore") as f:
                f.seek(last_pos)
                tail = f.read()
        except OSError as exc:
            logger.warning("Failed to drain rotated log for '%s': %s", file_path, exc)
            return

        if not tail.strip():
            return

        branch = detect_branch_from_log(file_path)
        for line in tail.strip().split("\n"):
            if line.strip() and not should_skip_log(line):
                self._process_log_line(branch, line, file_path)

    def _read_new_lines(self, file_path: str) -> None:
        """
        Read new content from a log file and process lines.

        Rotation is detected by inode, not size: a fresh log may already be past the old offset.
        Inode 0 (some Windows filesystems) means unknown and falls back to the size check.
        """
        stats = Path(file_path).stat()
        current_size = stats.st_size
        last_pos = self.log_positions.get(file_path, 0)
        known_inode = self.log_inodes.get(file_path)
        rotated_away = bool(known_inode) and bool(stats.st_ino) and known_inode != stats.st_ino

        if rotated_away:
            try:
                self._drain_rotated_tail(file_path, last_pos)
            except Exception as exc:
                logger.warning("Failed to drain rotated tail for '%s': %s", file_path, exc)
            last_pos = 0
            # Record immediately so a second event cannot drain the same tail twice
            self._record_position(file_path, 0)
        elif current_size < last_pos:
            # Same file, smaller: truncated in place - no rotated tail exists
            last_pos = 0
            self._record_position(file_path, 0)
        if current_size <= last_pos:
            return

        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            f.seek(last_pos)
            new_lines = f.read()
            if new_lines.strip():
                branch = detect_branch_from_log(file_path)
                for line in new_lines.strip().split("\n"):
                    if line.strip() and not should_skip_log(line):
                        self._process_log_line(branch, line, file_path)
            self._record_position(file_path, f.tell())

    def on_modified(self, event):
        """Handle log file modification events."""
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
        """Process a log line and fire appropriate events."""
        try:
            from aipass.trigger.apps.modules.core import trigger

            level = detect_log_level(log_line)
            message = parse_log_message(log_line)
            module_name = extract_module_name(log_line)
            timestamp = datetime.now().isoformat()
            error_hash = generate_error_hash(module_name, message)

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
                except Exception as exc:
                    logger.warning("Registry unavailable, falling back to error_detected: %s", exc)
                    trigger.fire(
                        "error_detected",
                        branch=branch,
                        module=module_name,
                        message=message,
                        log_path=log_file,
                        error_hash=error_hash,
                        timestamp=timestamp,
                    )
                json_handler.log_operation("system_log_event", {"level": level, "module": module_name})
            elif level == "warning":
                trigger.fire("warning_logged", **event_data)
                json_handler.log_operation("system_log_event", {"level": level, "module": module_name})

        except Exception as exc:
            logger.warning("Failed to process log line from '%s': %s", log_file, exc)

    def initialize_positions(self) -> None:
        """Initialize log positions to END of existing files."""
        if not SYSTEM_LOGS_DIR.exists():
            return

        for log_file in SYSTEM_LOGS_DIR.glob("*.log"):
            try:
                self._record_position(str(log_file), log_file.stat().st_size)
            except Exception as exc:
                logger.warning("Failed to initialize position for '%s': %s", log_file, exc)


def start_log_watcher() -> Any:
    """
    Decline to start — `branch_log_events` owns system_logs.

    A second observer mints duplicate escalation signatures. Returns None always; callers take the not-started path.
    """
    logger.info(
        "[TRIGGER] system_logs is watched by %s — centralized observer not started (the owner's ruling, 2026-08-14)",
        SYSTEM_LOGS_OWNER,
    )
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
    """Check if log watcher is running."""
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
