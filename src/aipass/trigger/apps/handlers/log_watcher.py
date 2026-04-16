# =================== AIPass ====================
# Name: log_watcher.py
# Description: Branch log watcher event producer for error detection
# Version: 2.3.0
# Created: 2026-02-02
# Modified: 2026-02-27
# =============================================

"""
Branch Log Watcher Event Producer

Watches */logs/*.log across all branches for ERROR entries.
Also watches ~/system_logs/ for system-level services.
Fires error_detected events for the Trigger event system.

Architecture:
    - Watches: src/aipass/*/logs/*.log (branch log directories)
    - Watches: system_logs/*.log (mapped to owning branch)
    - Parses: Prax format (timestamp | module | LEVEL | message)
    - Fires: error_detected event (via callback, branch=..., module=..., message=..., log_path=...)
    - Primary dedup: error_registry.report() with SHA1 fingerprinting (Medic v2)
    - Fallback dedup: MD5 hash of (module + message) if registry unavailable (Medic v1)
"""

import json
import re
import sys
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Set, Optional, Callable
from aipass.trigger.apps.config import TRIGGER_ROOT, AIPASS_PKG_ROOT, atomic_write_json, json_file_lock
from aipass.trigger.apps.handlers.json import json_handler

from aipass.prax.apps.modules.logger import get_direct_logger

logger = get_direct_logger()

# Persistent hash storage
TRIGGER_DATA_FILE = TRIGGER_ROOT / "trigger_data.json"

# Max age for log entries to be considered fresh (seconds)
STALE_ENTRY_THRESHOLD_SECONDS = 300  # 5 minutes

# Log filenames to exclude from watching (self-referential / dispatch feedback)
# Compared case-insensitively against Path.name (see on_modified)
EXCLUDED_LOG_FILES: Set[str] = {
    "dispatch.log",
    "medic_suppressed.log",
    "rate_limited.log",
    "error_monitor.log",
    "log_watcher.log",
    "log_watcher.log.1",
    # DirectLogger output files for handlers that watch logs (self-referential)
    "trigger_log_watcher.log",
    "trigger_error_registry.log",
}

# Pre-compute lowercase set for case-insensitive matching
_EXCLUDED_LOG_FILES_LOWER: Set[str] = {f.lower() for f in EXCLUDED_LOG_FILES}

# Patterns in error *messages* that indicate the line is ABOUT an error
# (e.g. a handler logging that it processed an error) rather than being
# a new error itself.  Lines matching any of these are skipped.
_SEMANTIC_EXCLUSION_PATTERNS: re.Pattern = re.compile(
    r"error_hash|fingerprint|registry_id|Error ID:|"
    r"\[ERROR\]|Processed error|Processing error|"
    r"dispatch.*error|error.*dispatch|"
    r"suppress.*error|error.*suppress",
    re.IGNORECASE,
)

# Try to import error_registry for Medic v2 registry-based dedup
try:
    from aipass.trigger.apps.handlers.error_registry import report as registry_report

    _REGISTRY_AVAILABLE = True
except ImportError:
    logger.info("error_registry not available, using MD5 fallback dedup")
    _REGISTRY_AVAILABLE = False

    def registry_report(
        error_type: str, message: str, component: str, log_path: str = "", severity: str = "medium"
    ) -> dict:
        """Fallback no-op error registry report when error_registry is unavailable."""
        return {"is_new": False, "count": 0}


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

# Global state
_branch_log_observer: Any = None
_active_watcher: Any = None  # Reference to BranchLogWatcher for position persistence
_seen_error_hashes: Set[str] = set()
_fallback_error_counts: Dict[str, int] = {}  # Local count per hash when registry unavailable
MAX_SEEN_HASHES = 2000  # Limit memory usage

# Explicit mapping of system_logs filenames to their owning branch.
# Used for files that don't follow the <branch>_<module>.log naming convention.
SYSTEM_LOGS_BRANCH_MAP: Dict[str, str] = {
    "telegram_bridge.log": "API",
    "telegram_chats.log": "API",
}

SYSTEM_LOGS_DIR = AIPASS_PKG_ROOT.parent.parent / "system_logs"

# Known branch prefixes that appear in system_logs filenames (<prefix>_<module>.log).
# Sorted longest-first so longer prefixes match before shorter ones.
_SYSTEM_LOGS_BRANCH_PREFIXES: list = sorted(
    [
        "ai_mail",
        "api",
        "cli",
        "drone",
        "flow",
        "prax",
        "trigger",
        "seedgo",
        "memory",
        "spawn",
        "devpulse",
    ],
    key=len,
    reverse=True,
)

# Event fire callback (set by module, avoids handler importing from modules)
_fire_event: Optional[Callable[..., None]] = None


def _load_seen_hashes() -> None:
    """
    Load persisted dedup hashes from trigger_data.json on startup.

    Populates _seen_error_hashes from disk so deduplication
    survives restarts.
    """
    global _seen_error_hashes
    try:
        if TRIGGER_DATA_FILE.exists():
            data = json.loads(TRIGGER_DATA_FILE.read_text(encoding="utf-8"))
            stored = data.get("seen_error_hashes", [])
            _seen_error_hashes = set(stored)
    except Exception as exc:
        logger.warning("Failed to load seen hashes: %s", exc)
        _seen_error_hashes = set()  # Start fresh on read failure


def _save_seen_hashes() -> None:
    """
    Persist dedup hashes to trigger_data.json.

    Writes current _seen_error_hashes to disk so they survive restarts.
    Merges with existing trigger_data.json content to preserve other keys.
    """
    try:
        with json_file_lock(TRIGGER_DATA_FILE):
            data: Dict[str, Any] = {}
            if TRIGGER_DATA_FILE.exists():
                data = json.loads(TRIGGER_DATA_FILE.read_text(encoding="utf-8"))
            data["seen_error_hashes"] = list(_seen_error_hashes)
            atomic_write_json(TRIGGER_DATA_FILE, data)
    except Exception as exc:
        logger.warning("Failed to save seen hashes: %s", exc)
        return  # Write failure - hashes remain in memory only


def _load_log_positions() -> Dict[str, int]:
    """
    Load persisted log positions from trigger_data.json.

    Returns byte offsets for each log file so the watcher resumes
    from last-processed position across restarts.

    Returns:
        Dict mapping file paths to byte offsets
    """
    try:
        if TRIGGER_DATA_FILE.exists():
            data = json.loads(TRIGGER_DATA_FILE.read_text(encoding="utf-8"))
            stored = data.get("log_positions", {})
            if isinstance(stored, dict):
                return {k: int(v) for k, v in stored.items()}
    except Exception as e:
        logger.warning("Failed to load log positions: %s", e)
    return {}


def _save_log_positions(positions: Dict[str, int]) -> None:
    """
    Persist log positions to trigger_data.json.

    Saves byte offsets for each log file so they survive restarts.
    Merges with existing trigger_data.json content to preserve other keys.

    Args:
        positions: Dict mapping file paths to byte offsets
    """
    try:
        with json_file_lock(TRIGGER_DATA_FILE):
            data: Dict[str, Any] = {}
            if TRIGGER_DATA_FILE.exists():
                data = json.loads(TRIGGER_DATA_FILE.read_text(encoding="utf-8"))
            data["log_positions"] = positions
            atomic_write_json(TRIGGER_DATA_FILE, data)
    except Exception as exc:
        logger.warning("Failed to save log positions: %s", exc)
        return  # Write failure - positions remain in memory only


def _is_stale_entry(timestamp_str: str) -> bool:
    """
    Check if a log entry timestamp is older than the freshness threshold.

    Parses common timestamp formats and returns True if the entry
    is too old to process (prevents re-flagging old entries).

    Args:
        timestamp_str: Timestamp string from log line

    Returns:
        True if the entry is stale (older than STALE_ENTRY_THRESHOLD_SECONDS)
    """
    now = datetime.now()
    cutoff = now - timedelta(seconds=STALE_ENTRY_THRESHOLD_SECONDS)

    formats = [
        "%Y-%m-%d %H:%M:%S,%f",  # Python logging: 2026-02-13 22:51:25,565
        "%Y-%m-%d %H:%M:%S.%f",  # Prax: 2026-02-13 22:51:25.565
        "%Y-%m-%d %H:%M:%S",  # Simple: 2026-02-13 22:51:25
        "%Y-%m-%dT%H:%M:%S.%f",  # ISO: 2026-02-13T22:51:25.565
        "%Y-%m-%dT%H:%M:%S",  # ISO simple: 2026-02-13T22:51:25
    ]

    stripped = timestamp_str.strip()
    for fmt in formats:
        try:
            entry_time = datetime.strptime(stripped, fmt)
            return entry_time < cutoff
        except ValueError:
            continue

    # All formats failed — log once and treat as stale
    logger.warning("Failed to parse timestamp '%s' (no matching format)", stripped)
    return True


def _generate_error_hash(source_module: str, message: str) -> str:
    """
    Generate hash for error deduplication.

    BACKWARD COMPAT: Kept for fallback when error_registry is unavailable.
    Primary dedup path is now error_registry.report() (Medic v2).

    Args:
        source_module: Module that generated the error
        message: Error message content

    Returns:
        8-character hash string
    """
    content = f"{source_module}:{message}"
    return hashlib.md5(content.encode()).hexdigest()[:8]


def _detect_branch_from_path(log_path: str) -> str:
    """
    Detect branch name from log file path.

    Handles two path patterns:
        - src/aipass/<branch>/logs/<file>.log
        - system_logs/<file>.log (mapped via SYSTEM_LOGS_BRANCH_MAP,
          falls back to branch prefix in filename like "api_api.log" -> API)

    Args:
        log_path: Full path to log file

    Returns:
        Branch name in uppercase (e.g., 'FLOW', 'PRAX')
    """
    try:
        path = Path(log_path)

        # Check system_logs/ files first
        if path.parent == SYSTEM_LOGS_DIR:
            filename = path.name
            # Explicit mapping for known services
            if filename in SYSTEM_LOGS_BRANCH_MAP:
                return SYSTEM_LOGS_BRANCH_MAP[filename]
            # Match filename prefix against known branch names (longest-first)
            name_stem = path.stem  # e.g. "memory_rollover" from "memory_rollover.log"
            for prefix in _SYSTEM_LOGS_BRANCH_PREFIXES:
                if name_stem.startswith(prefix + "_") or name_stem == prefix:
                    return prefix.upper()
            return "UNKNOWN"

        # Standard src/aipass/<branch>/logs/ pattern
        parts = path.parts
        for i, part in enumerate(parts):
            if part == "aipass" and i + 1 < len(parts) and parts[i + 1] != "__pycache__":
                # Check if this looks like a branch dir (has logs/ subdir)
                if i + 2 < len(parts) and parts[i + 2] == "logs":
                    return parts[i + 1].upper()
        return "UNKNOWN"
    except Exception as exc:
        logger.warning("Failed to detect branch from path '%s': %s", log_path, exc)
        return "UNKNOWN"


def _parse_prax_log_line(log_line: str) -> Optional[Dict[str, str]]:
    """
    Parse a log line in Prax format or Python logging format.

    Formats supported:
        - Prax:   timestamp | module | LEVEL | message
        - Python: timestamp - module - LEVEL - message

    Args:
        log_line: Raw log line

    Returns:
        Dict with keys: timestamp, module, level, message
        None if parsing fails or line is not ERROR level
    """
    try:
        # Try Prax format first (pipe-separated)
        if " | " in log_line:
            parts = log_line.split(" | ", 3)
            if len(parts) >= 4:
                level = parts[2].strip().upper()
                if level in ("ERROR", "CRITICAL"):
                    return {
                        "timestamp": parts[0].strip(),
                        "module": parts[1].strip(),
                        "level": level,
                        "message": parts[3].strip(),
                    }
                return None

        # Fallback: Python logging format (dash-separated)
        # Format: 2026-02-10 15:12:29,460 - telegram_bridge - ERROR - message
        # NOTE: We do NOT pre-check ' - ERROR - ' in log_line because that
        # matches ERROR appearing anywhere in the text (false positive).
        # Instead, we split positionally and validate parts[2] is a
        # standalone level word.
        if " - " in log_line:
            parts = log_line.split(" - ", 3)
            if len(parts) >= 4:
                level = parts[2].strip().upper()
                # Strict check: level field must be EXACTLY a known level,
                # not a longer string that happens to contain one.
                if level in ("ERROR", "CRITICAL"):
                    return {
                        "timestamp": parts[0].strip(),
                        "module": parts[1].strip(),
                        "level": level,
                        "message": parts[3].strip(),
                    }

        return None
    except Exception as exc:
        logger.warning("Failed to parse log line: %s", exc)
        return None


def _is_duplicate_error(error_hash: str) -> bool:
    """
    Check if error has been seen before (deduplication).

    BACKWARD COMPAT: Kept for fallback when error_registry is unavailable.
    Primary dedup path is now error_registry.report() (Medic v2).

    Args:
        error_hash: Hash of module + message

    Returns:
        True if this error has been seen before
    """
    global _seen_error_hashes

    if error_hash in _seen_error_hashes:
        return True

    # Add to seen set with size limit
    _seen_error_hashes.add(error_hash)
    if len(_seen_error_hashes) > MAX_SEEN_HASHES:
        # Remove oldest entries (convert to list, slice, back to set)
        _seen_error_hashes = set(list(_seen_error_hashes)[MAX_SEEN_HASHES // 2 :])

    # Persist to disk after each new hash
    _save_seen_hashes()

    return False


def set_event_callback(callback: Callable[..., None]) -> None:
    """
    Set the callback function for firing events.

    Must be called by the module before starting the watcher.
    This avoids handler importing from modules (maintains independence).

    Args:
        callback: Function to call with (event_name, **data)
    """
    global _fire_event
    _fire_event = callback


class BranchLogWatcher(WatchdogFileSystemEventHandler if WATCHDOG_AVAILABLE else object):  # type: ignore[misc]
    """
    Watch branch log files and fire error_detected events.

    Monitors src/aipass/*/logs/*.log for ERROR entries.
    Persists file positions to disk so restarts resume from last-processed offset.
    """

    def __init__(self):
        """Initialize log watcher with position tracking."""
        super().__init__()
        self.log_positions: Dict[str, int] = {}
        self._position_save_counter: int = 0
        self._POSITION_SAVE_INTERVAL: int = 10  # Save positions every N file events

    def _should_process(self, file_path: str) -> bool:
        """Check if a log file should be processed."""
        if not file_path.endswith(".log"):
            return False
        filename = Path(file_path).name
        if filename.lower() in _EXCLUDED_LOG_FILES_LOWER:
            return False
        is_branch_log = "/aipass/" in file_path and "/logs/" in file_path
        is_system_log = "/system_logs/" in file_path
        return is_branch_log or is_system_log

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
                for line in new_lines.strip().split("\n"):
                    if line.strip():
                        self._process_log_line(line, file_path)
            self.log_positions[file_path] = f.tell()

        self._position_save_counter += 1
        if self._position_save_counter >= self._POSITION_SAVE_INTERVAL:
            _save_log_positions(self.log_positions)
            self._position_save_counter = 0

    def on_modified(self, event) -> None:
        """
        Handle log file modification events.

        Reads new content and fires error_detected for ERROR entries.
        Skips excluded files (dispatch logs, medic logs) to prevent feedback loops.
        """
        if event.is_directory:
            return

        file_path = str(event.src_path)
        if not self._should_process(file_path):
            return

        try:
            self._read_new_lines(file_path)
        except Exception as exc:
            logger.warning("Failed to read log file '%s': %s", file_path, exc)
            return  # Read failure on this event - skip without raising

    def _process_log_line(self, log_line: str, log_path: str) -> None:
        """
        Process a log line and fire error_detected if ERROR found.

        Primary path (Medic v2): Uses error_registry.report() for structured
        dedup with SHA1 fingerprinting. Fires event on first occurrence (count==1)
        and second occurrence (count==2) so the handler can apply the dispatch
        threshold. Subsequent occurrences are silent until backoff allows.

        Fallback path (Medic v1): Uses MD5 hash dedup if error_registry is
        unavailable (import failed).

        Args:
            log_line: Raw log line
            log_path: Path to log file
        """
        try:
            parsed = _parse_prax_log_line(log_line)
            if not parsed:
                return

            # Skip lines that reference error artifacts (IDs, fingerprints,
            # registry entries).  These are logs ABOUT errors, not new errors.
            if _SEMANTIC_EXCLUSION_PATTERNS.search(parsed["message"]):
                return

            # Skip stale entries — prevents re-flagging old log lines
            if _is_stale_entry(parsed["timestamp"]):
                return

            branch = _detect_branch_from_path(log_path)
            module = parsed["module"]
            message = parsed["message"]

            # Primary path: Medic v2 registry-based dedup
            if _REGISTRY_AVAILABLE:
                try:
                    result = registry_report(
                        error_type=parsed["level"],
                        message=message,
                        component=branch,
                        log_path=log_path,
                        severity="medium",
                    )

                    # Fire event on every occurrence — let the error_detected
                    # handler decide via circuit breaker, backoff, and rate limiting.
                    error_count = result.get("count", 1)

                    # Fire error_detected event with registry data
                    if _fire_event is not None:
                        _fire_event(
                            "error_detected",
                            branch=branch,
                            module=module,
                            message=message,
                            log_path=log_path,
                            error_hash=result.get("id", ""),
                            timestamp=parsed["timestamp"],
                            fingerprint=result.get("fingerprint", ""),
                            registry_id=result.get("id", ""),
                            first_seen=result.get("first_seen", ""),
                            last_seen=result.get("last_seen", ""),
                            count=error_count,
                        )
                        json_handler.log_operation("error_detected_in_log", {"branch": branch, "log_path": log_path})
                    else:
                        logger.warning(
                            "Cannot fire error_detected event: _fire_event callback not set (branch=%s, module=%s)",
                            branch,
                            module,
                        )
                    return

                except Exception as e:
                    # Registry unavailable — fall through to legacy MD5 dedup
                    logger.warning("Registry report failed for %s:%s — using MD5 fallback: %s", branch, module, e)

            # Fallback path: retry lazy import of registry, else track count locally
            error_hash = _generate_error_hash(module, message)

            # Retry registry import — may have failed at module load but be available now
            try:
                from aipass.trigger.apps.handlers.error_registry import report as _lazy_report

                result = _lazy_report(
                    error_type=parsed["level"], message=message, component=branch, log_path=log_path, severity="medium"
                )
                error_count = result.get("count", 1)
                if not result.get("is_new", False) and error_count != 2:
                    return
                if _fire_event is not None:
                    _fire_event(
                        "error_detected",
                        branch=branch,
                        module=module,
                        message=message,
                        log_path=log_path,
                        error_hash=result.get("id", error_hash),
                        timestamp=parsed["timestamp"],
                        fingerprint=result.get("fingerprint", ""),
                        registry_id=result.get("id", ""),
                        first_seen=result.get("first_seen", ""),
                        last_seen=result.get("last_seen", ""),
                        count=error_count,
                    )
                    json_handler.log_operation("error_detected_in_log", {"branch": branch, "log_path": log_path})
                return
            except Exception as exc:
                logger.warning("Lazy registry import failed in fallback path: %s", exc)

            # Registry truly unavailable — track count locally, fire with count
            _fallback_error_counts[error_hash] = _fallback_error_counts.get(error_hash, 0) + 1
            local_count = _fallback_error_counts[error_hash]

            if _fire_event is not None:
                _fire_event(
                    "error_detected",
                    branch=branch,
                    module=module,
                    message=message,
                    log_path=log_path,
                    error_hash=error_hash,
                    timestamp=parsed["timestamp"],
                    count=local_count,
                )
                json_handler.log_operation("error_detected_in_log", {"branch": branch, "log_path": log_path})
            else:
                logger.warning(
                    "Cannot fire error_detected event: _fire_event callback not set (branch=%s, module=%s)",
                    branch,
                    module,
                )

        except Exception as exc:
            logger.warning("Failed to process log line from '%s': %s", log_path, exc)
            return  # Parse/fire failure on this line - skip without raising

    def initialize_positions(self) -> None:
        """
        Initialize log positions from persisted state, falling back to END of file.

        Loads saved positions from trigger_data.json first (survives restarts).
        For files not in persisted state, snaps to current EOF.
        Validates persisted positions against actual file sizes (handles rotation).
        Covers both aipass/*/logs/ and system_logs/.
        """
        # Load persisted positions from disk first
        persisted = _load_log_positions()

        # Branch logs under aipass/*/logs/
        for branch_dir in AIPASS_PKG_ROOT.iterdir():
            if not branch_dir.is_dir():
                continue
            logs_dir = branch_dir / "logs"
            if not logs_dir.exists():
                continue
            for log_file in logs_dir.glob("*.log"):
                try:
                    file_path = str(log_file)
                    current_size = log_file.stat().st_size
                    saved_pos = persisted.get(file_path, -1)
                    # Use persisted position if valid (not beyond current file size)
                    if 0 <= saved_pos <= current_size:
                        self.log_positions[file_path] = saved_pos
                    else:
                        self.log_positions[file_path] = current_size
                except Exception as exc:
                    logger.warning("Failed to initialize position for branch log '%s': %s", log_file, exc)
                    continue  # Skip unreadable log file

        # System-level logs under ~/system_logs/
        if SYSTEM_LOGS_DIR.exists():
            for log_file in SYSTEM_LOGS_DIR.glob("*.log"):
                try:
                    file_path = str(log_file)
                    current_size = log_file.stat().st_size
                    saved_pos = persisted.get(file_path, -1)
                    if 0 <= saved_pos <= current_size:
                        self.log_positions[file_path] = saved_pos
                    else:
                        self.log_positions[file_path] = current_size
                except Exception as exc:
                    logger.warning("Failed to initialize position for system log '%s': %s", log_file, exc)
                    continue  # Skip unreadable log file


def start_branch_log_watcher() -> Any:
    """
    Start the branch log watcher.

    Watches src/aipass/*/logs/*.log for ERROR entries.
    Loads persisted positions from disk so restarts resume correctly.

    Returns:
        Observer instance (caller must keep reference to keep alive)
        None if watchdog not available or error
    """
    global _branch_log_observer, _active_watcher

    if not WATCHDOG_AVAILABLE:
        return None

    # Stop existing watcher if running
    if _branch_log_observer and _branch_log_observer.is_alive():
        stop_branch_log_watcher()

    if not AIPASS_PKG_ROOT.exists():
        return None

    if WatchdogObserver is None:
        return None

    # Load persisted dedup hashes from disk
    _load_seen_hashes()

    watcher = BranchLogWatcher()
    watcher.initialize_positions()
    _active_watcher = watcher
    _callback = watcher.on_modified  # watchdog dispatches FileSystemEvents here
    observer = WatchdogObserver()

    # Schedule watcher for each branch's logs directory
    for branch_dir in AIPASS_PKG_ROOT.iterdir():
        if not branch_dir.is_dir():
            continue
        logs_dir = branch_dir / "logs"
        if logs_dir.exists():
            observer.schedule(watcher, str(logs_dir), recursive=False)

    # Also watch system_logs/ for system-level log files
    if SYSTEM_LOGS_DIR.exists():
        observer.schedule(watcher, str(SYSTEM_LOGS_DIR), recursive=False)

    observer.start()
    _branch_log_observer = observer

    return observer


def stop_branch_log_watcher() -> None:
    """Stop the branch log watcher and persist positions to disk."""
    global _branch_log_observer, _active_watcher

    # Persist positions before stopping
    if _active_watcher is not None:
        _save_log_positions(_active_watcher.log_positions)
        _active_watcher = None

    if _branch_log_observer and _branch_log_observer.is_alive():
        _branch_log_observer.stop()
        _branch_log_observer.join(timeout=5.0)
        _branch_log_observer = None


def is_branch_log_watcher_active() -> bool:
    """
    Check if branch log watcher is running.

    Returns:
        True if watcher is active
    """
    return _branch_log_observer is not None and _branch_log_observer.is_alive()


def clear_seen_hashes() -> None:
    """
    Clear the deduplication hash set (memory and disk).

    Useful for testing or after extended runtime.
    """
    global _seen_error_hashes
    _seen_error_hashes.clear()
    _save_seen_hashes()


def get_watcher_status() -> Dict[str, Any]:
    """
    Get current watcher status.

    Returns:
        Dict with status information
    """
    tracked_files = 0
    if _active_watcher is not None:
        tracked_files = len(_active_watcher.log_positions)
    return {
        "active": is_branch_log_watcher_active(),
        "watchdog_available": WATCHDOG_AVAILABLE,
        "seen_hashes_count": len(_seen_error_hashes),
        "tracked_log_files": tracked_files,
        "excluded_files": list(EXCLUDED_LOG_FILES),
        "stale_threshold_seconds": STALE_ENTRY_THRESHOLD_SECONDS,
        "aipass_root": str(AIPASS_PKG_ROOT),
    }


if __name__ == "__main__":
    """Standalone test for branch log watcher."""
    import time

    def test_fire_event(event_name: str, **data: Any) -> None:
        """Test callback that prints events."""
        print(f"[EVENT] {event_name}: {data}")

    # Set callback for standalone testing
    set_event_callback(test_fire_event)

    print("Branch Log Watcher Test")
    print(f"Monitoring: {AIPASS_PKG_ROOT}/*/logs/*.log")
    print(f"Monitoring: {SYSTEM_LOGS_DIR}/*.log")
    print("Press Ctrl+C to stop")
    print()

    observer = start_branch_log_watcher()

    if not observer:
        print("Failed to start branch log watcher")
        if not WATCHDOG_AVAILABLE:
            print("  - watchdog package not installed")
        sys.exit(1)

    print(f"Status: {get_watcher_status()}")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Branch log watcher stopped by user")
        print("\nStopping...")
        stop_branch_log_watcher()
        print("Stopped")
