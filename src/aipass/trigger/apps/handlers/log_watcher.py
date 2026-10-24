# =================== AIPass ====================
# Name: log_watcher.py
# Description: Branch log watcher event producer for error detection
# Version: 2.9.0
# Created: 2026-02-02
# Modified: 2026-10-24
# =============================================

"""
Branch Log Watcher Event Producer
"""

import json
import re
import sys
import hashlib
import time
import threading
from datetime import datetime, timedelta
from pathlib import Path, PurePath
from typing import Any, Dict, Set, Optional, Callable
from aipass.trigger.apps.config import TRIGGER_ROOT, AIPASS_PKG_ROOT, atomic_write_json, json_file_lock
from aipass.trigger.apps.handlers.json import json_handler
from aipass.trigger.apps.handlers.error_registry import report as registry_report

from aipass.prax.apps.modules.logger import get_direct_logger

logger = get_direct_logger()

TRIGGER_DATA_FILE = TRIGGER_ROOT / "trigger_data.json"

STALE_ENTRY_THRESHOLD_SECONDS = 300

# Warnings feed only the escalation digest lane, never medic dispatch.
ERROR_LEVELS = ("ERROR", "CRITICAL")
WARNING_LEVELS = ("WARNING", "WARN")

# Must match prax RotatingFileHandler backup_count.
MAX_BACKUP_CHAIN_DEPTH = 3

# Self-referential / dispatch logs: watching them would feed the watcher its own output.
EXCLUDED_LOG_FILES: Set[str] = {
    "dispatch.log",
    "medic_suppressed.jsonl",
    "rate_limited.jsonl",
    "error_monitor.log",
    "log_watcher.log",
    "log_watcher.log.1",
    "trigger_log_watcher.log",
    "trigger_error_registry.log",
}

_EXCLUDED_LOG_FILES_LOWER: Set[str] = {f.lower() for f in EXCLUDED_LOG_FILES}

# A line ABOUT an error (a handler reporting one it processed) is not a new error.
_SEMANTIC_EXCLUSION_PATTERNS: re.Pattern = re.compile(
    r"error_hash|fingerprint|registry_id|Error ID:|"
    r"\[ERROR\]|Processed error|Processing error|"
    r"dispatch.*error|error.*dispatch|"
    r"suppress.*error|error.*suppress",
    re.IGNORECASE,
)

try:
    from watchdog.observers import Observer as WatchdogObserver
    from watchdog.events import FileSystemEventHandler as WatchdogFileSystemEventHandler

    WATCHDOG_AVAILABLE = True
except ImportError:
    logger.info("watchdog not available, log watcher disabled")
    WATCHDOG_AVAILABLE = False
    WatchdogObserver = None  # type: ignore
    WatchdogFileSystemEventHandler = object  # type: ignore

_branch_log_observer: Any = None
_active_watcher: Any = None
_seen_error_hashes: Set[str] = set()
MAX_SEEN_HASHES = 2000

# Debounced: positions + hashes coalesce into one write per interval, not one per event.
_FLUSH_INTERVAL = 5.0
_data_dirty: bool = False
_last_flush_time: float = 0.0
_flush_lock = threading.Lock()

# For system_logs files outside the <branch>_<module>.log convention.
SYSTEM_LOGS_BRANCH_MAP: Dict[str, str] = {
    "telegram_bridge.log": "API",
    "telegram_chats.log": "API",
}

SYSTEM_LOGS_DIR = AIPASS_PKG_ROOT.parent.parent / "system_logs"

# A FLOOR for when the tree cannot be read; real names come from _known_branch_names,
# since a hardcoded roster silently attributes every newer branch as UNKNOWN.
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

# TTL: a new branch is attributed within the minute without a listdir per log line.
_BRANCH_NAMES_TTL_SECONDS = 60.0
_branch_names_cache: tuple = (0.0, ())

# `object`, not None: Trigger.fire returns a summary, and -> None would reject the real bus.
_fire_event: Optional[Callable[..., object]] = None

# Checked per log line: the TTL applies a config edit within a minute without a read per line.
_WARNING_CAPTURE_TTL_SECONDS = 60.0
_warning_capture_cache: tuple = (0.0, True)


def _warning_capture_enabled() -> bool:
    """Check whether branch-log WARNING lines feed the escalation lane."""
    # Fails OPEN: losing the count silently is the failure this lane exists to stop.
    global _warning_capture_cache
    checked_at, cached = _warning_capture_cache
    now = time.time()
    if now - checked_at < _WARNING_CAPTURE_TTL_SECONDS:
        return cached
    value = True
    try:
        from aipass.trigger.apps.handlers.json import config_loader

        value = bool(config_loader.section("escalation").get("watch_branch_log_warnings", True))
    except Exception as exc:
        logger.warning("Escalation config unreadable, keeping warning capture on: %s", exc)
    _warning_capture_cache = (now, value)
    return value


def _load_seen_hashes() -> None:
    """Load persisted dedup hashes from trigger_data.json on startup."""
    global _seen_error_hashes
    try:
        if TRIGGER_DATA_FILE.exists():
            data = json.loads(TRIGGER_DATA_FILE.read_text(encoding="utf-8"))
            stored = data.get("seen_error_hashes", [])
            _seen_error_hashes = set(stored)
    except Exception as exc:
        logger.warning("Failed to load seen hashes: %s", exc)
        _seen_error_hashes = set()


def _load_log_positions() -> Dict[str, int]:
    """Load persisted log positions from trigger_data.json."""
    try:
        if TRIGGER_DATA_FILE.exists():
            data = json.loads(TRIGGER_DATA_FILE.read_text(encoding="utf-8"))
            stored = data.get("log_positions", {})
            if isinstance(stored, dict):
                return {k: int(v) for k, v in stored.items()}
    except Exception as e:
        logger.warning("Failed to load log positions: %s", e)
    return {}


def _load_log_inodes() -> Dict[str, int]:
    """Load persisted log inodes from trigger_data.json."""
    # A separate key so the on-disk log_positions shape never changes.
    try:
        if TRIGGER_DATA_FILE.exists():
            data = json.loads(TRIGGER_DATA_FILE.read_text(encoding="utf-8"))
            stored = data.get("log_inodes", {})
            if isinstance(stored, dict):
                return {k: int(v) for k, v in stored.items()}
    except Exception as e:
        logger.warning("Failed to load log inodes: %s", e)
    return {}


def _mark_data_dirty() -> None:
    """Mark trigger_data.json as needing a flush; flush if interval elapsed."""
    global _data_dirty
    _data_dirty = True
    if time.monotonic() - _last_flush_time >= _FLUSH_INTERVAL:
        _flush_trigger_data()


def _flush_trigger_data(force: bool = False) -> None:
    """Write both positions and hashes to trigger_data.json in one atomic write."""
    global _data_dirty, _last_flush_time
    if not force and not _data_dirty:
        return
    with _flush_lock:
        if not force and not _data_dirty:
            return
        try:
            with json_file_lock(TRIGGER_DATA_FILE):
                data: Dict[str, Any] = {}
                if TRIGGER_DATA_FILE.exists():
                    data = json.loads(TRIGGER_DATA_FILE.read_text(encoding="utf-8"))
                if _active_watcher is not None:
                    data["log_positions"] = _active_watcher.log_positions
                    data["log_inodes"] = _active_watcher.log_inodes
                data["seen_error_hashes"] = list(_seen_error_hashes)
                atomic_write_json(TRIGGER_DATA_FILE, data)
            _data_dirty = False
            _last_flush_time = time.monotonic()
        except Exception as exc:
            logger.warning("Failed to flush trigger_data.json: %s", exc)


def is_stale_entry(timestamp_str: str) -> bool:
    """Check if a log entry timestamp is older than the freshness threshold."""
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

    logger.warning("Failed to parse timestamp '%s' (no matching format)", stripped)
    return True


def generate_error_hash(source_module: str, message: str) -> str:
    """Generate hash for error deduplication."""
    content = f"{source_module}:{message}"
    return hashlib.md5(content.encode()).hexdigest()[:8]


def _known_branch_names() -> tuple:
    """Branch names taken from the live tree, longest first."""
    # Longest-first: "ai_mail_delivery" must resolve to ai_mail, never a shorter shared prefix.
    global _branch_names_cache
    cached_at, names = _branch_names_cache
    now = time.monotonic()
    if names and (now - cached_at) < _BRANCH_NAMES_TTL_SECONDS:
        return names

    found = set(_SYSTEM_LOGS_BRANCH_PREFIXES)
    try:
        for entry in AIPASS_PKG_ROOT.iterdir():
            if entry.is_dir() and not entry.name.startswith((".", "_")):
                found.add(entry.name)
    except OSError as exc:
        logger.warning("Failed to list branch directories under '%s': %s", AIPASS_PKG_ROOT, exc)

    resolved = tuple(sorted(found, key=len, reverse=True))
    _branch_names_cache = (now, resolved)
    return resolved


def classify_log_path(path: PurePath) -> str:
    """Say which tree a log file belongs to, from its path components."""
    # Components, never separators: a "/logs/" substring test drops every Windows path.
    parts = path.parts
    if "aipass" in parts and "logs" in parts:
        return "branch"
    if "system_logs" in parts:
        return "system"
    return "foreign"


def _system_log_branch_twin(log_path: str) -> Optional[Path]:
    """Find the branch log holding the same lines as this system_logs file."""
    stem = Path(log_path).stem
    for branch in _known_branch_names():
        if stem == branch:
            module = branch
        elif stem.startswith(branch + "_"):
            module = stem[len(branch) + 1 :]
        else:
            continue
        twin = AIPASS_PKG_ROOT / branch / "logs" / f"{module}.log"
        try:
            if twin.exists():
                return twin
        except OSError as exc:
            logger.warning("Failed to check twin log '%s': %s", twin, exc)
    return None


def detect_branch_from_path(log_path: str) -> str:
    """Detect branch name from log file path."""
    # UNKNOWN is an answer, never a failure: an unreadable path raises, and both callers contain it.
    path = Path(log_path)

    if path.parent == SYSTEM_LOGS_DIR:
        filename = path.name
        if filename in SYSTEM_LOGS_BRANCH_MAP:
            return SYSTEM_LOGS_BRANCH_MAP[filename]
        name_stem = path.stem
        for prefix in _known_branch_names():
            if name_stem.startswith(prefix + "_") or name_stem == prefix:
                return prefix.upper()
        return "UNKNOWN"

    parts = path.parts
    for i, part in enumerate(parts):
        if part == "aipass" and i + 1 < len(parts) and parts[i + 1] != "__pycache__":
            if i + 2 < len(parts) and parts[i + 2] == "logs":
                return parts[i + 1].upper()
    return "UNKNOWN"


def parse_prax_log_line(log_line: str, levels: tuple = ERROR_LEVELS) -> Optional[Dict[str, str]]:
    """Parse a log line in Prax format or Python logging format."""
    # None means "not a line for this lane", never a failure: an unreadable line raises.
    if " | " in log_line:
        parts = log_line.split(" | ", 3)
        if len(parts) >= 4:
            level = parts[2].strip().upper()
            if level in levels:
                return {
                    "timestamp": parts[0].strip(),
                    "module": parts[1].strip(),
                    "level": level,
                    "message": parts[3].strip(),
                }
            return None

    # Split positionally, never pre-check ' - ERROR - ': that matches ERROR anywhere in the text.
    if " - " in log_line:
        parts = log_line.split(" - ", 3)
        if len(parts) >= 4:
            level = parts[2].strip().upper()
            if level in levels:
                return {
                    "timestamp": parts[0].strip(),
                    "module": parts[1].strip(),
                    "level": level,
                    "message": parts[3].strip(),
                }

    return None


def set_event_callback(callback: Callable[..., object]) -> None:
    """Set the callback function for firing events."""
    global _fire_event
    _fire_event = callback


class BranchLogWatcher(WatchdogFileSystemEventHandler if WATCHDOG_AVAILABLE else object):  # type: ignore[misc]
    """Watch branch log files and fire error_detected events."""

    def __init__(self):
        """Initialize log watcher with position tracking."""
        super().__init__()
        self.log_positions: Dict[str, int] = {}
        self.log_inodes: Dict[str, int] = {}
        self.watched_dirs: Set[Path] = set()

    def _record_position(self, file_path: str, position: int) -> None:
        """Record byte position and inode identity for a watched file."""
        self.log_positions[file_path] = position
        try:
            self.log_inodes[file_path] = Path(file_path).stat().st_ino
        except OSError as exc:
            logger.warning("Failed to record inode for '%s': %s", file_path, exc)
            self.log_inodes.pop(file_path, None)

    def _drain_rotated_tail(self, file_path: str, last_pos: int) -> None:
        """Process the unread tail of a log file that was just rotated away."""
        # Only the backup whose inode matches the recorded one is drained; anything else skips rather
        # than re-fire old errors. Backups rotated past unseen are warned about, never replayed (a flood).
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

        for line in tail.strip().split("\n"):
            if line.strip():
                self._process_log_line(line, file_path)

    def _should_process(self, file_path: str) -> bool:
        """Check if a log file should be processed."""
        if not file_path.endswith(".log"):
            return False
        filename = Path(file_path).name
        if filename.lower() in _EXCLUDED_LOG_FILES_LOWER:
            return False
        kind = classify_log_path(Path(file_path))
        if kind == "branch":
            return True
        if kind != "system":
            return False
        # Prax dual-writes; drop the system copy only while its twin is read, else it is the only copy.
        twin = _system_log_branch_twin(file_path)
        return twin is None or twin.parent not in self.watched_dirs

    def _read_new_lines(self, file_path: str) -> None:
        """Read new content from a log file and process lines."""
        # Rotation by INODE, not size: a fresh log may already exceed the old offset. Inode 0 is unknown.
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
            # Record now so a second event cannot drain the same tail twice.
            self._record_position(file_path, 0)
        elif current_size < last_pos:
            last_pos = 0
            self._record_position(file_path, 0)
        if current_size <= last_pos:
            return

        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            f.seek(last_pos)
            new_lines = f.read()
            if new_lines.strip():
                for line in new_lines.strip().split("\n"):
                    if line.strip():
                        self._process_log_line(line, file_path)
            self._record_position(file_path, f.tell())

        _mark_data_dirty()

    def on_modified(self, event) -> None:
        """Handle log file modification events."""
        if event.is_directory:
            return

        file_path = str(event.src_path)
        if not self._should_process(file_path):
            return

        try:
            self._read_new_lines(file_path)
        except Exception as exc:
            logger.warning("Failed to read log file '%s': %s", file_path, exc)
            return

    def _process_warning_line(self, log_line: str, log_path: str) -> None:
        """Fire warning_logged for a WARNING line so repeats can escalate."""
        try:
            if not _warning_capture_enabled():
                return

            parsed = parse_prax_log_line(log_line, levels=WARNING_LEVELS)
            if not parsed:
                return

            if _SEMANTIC_EXCLUSION_PATTERNS.search(parsed["message"]):
                return
            if is_stale_entry(parsed["timestamp"]):
                return

            if _fire_event is None:
                return

            _fire_event(
                "warning_logged",
                branch=detect_branch_from_path(log_path),
                message=parsed["message"],
                error_hash=generate_error_hash(parsed["module"], parsed["message"]),
                timestamp=parsed["timestamp"],
                log_file=log_path,
                module_name=parsed["module"],
                level=parsed["level"],
                raw_line=log_line,
            )
        except Exception as exc:
            logger.warning("Failed to process warning line from '%s': %s", log_path, exc)

    def _process_log_line(self, log_line: str, log_path: str) -> None:
        """Process a log line and fire error_detected if ERROR found."""
        try:
            parsed = parse_prax_log_line(log_line)
            if not parsed:
                self._process_warning_line(log_line, log_path)
                return

            if _SEMANTIC_EXCLUSION_PATTERNS.search(parsed["message"]):
                return

            if is_stale_entry(parsed["timestamp"]):
                return

            branch = detect_branch_from_path(log_path)
            module = parsed["module"]
            message = parsed["message"]

            result = registry_report(
                error_type=parsed["level"],
                message=message,
                component=branch,
                log_path=log_path,
                severity="medium",
            )

            if _fire_event is None:
                logger.warning(
                    "Cannot fire error_detected event: _fire_event callback not set (branch=%s, module=%s)",
                    branch,
                    module,
                )
                return

            # Fire on every occurrence; the handler owns breaker, backoff and threshold.
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
                count=result.get("count", 1),
            )
            json_handler.log_operation("error_detected_in_log", {"branch": branch, "log_path": log_path})

        except Exception as exc:
            logger.warning("Failed to process log line from '%s': %s", log_path, exc)
            return

    def initialize_positions(self) -> None:
        """Initialize log positions from persisted state, falling back to END of file."""
        persisted = _load_log_positions()
        # Seeded from disk; the live stat below wins for files that exist.
        self.log_inodes.update(_load_log_inodes())

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
                    # A saved position past EOF means the file rotated; snap to EOF.
                    if 0 <= saved_pos <= current_size:
                        self._record_position(file_path, saved_pos)
                    else:
                        self._record_position(file_path, current_size)
                except Exception as exc:
                    logger.warning("Failed to initialize position for branch log '%s': %s", log_file, exc)
                    continue

        if SYSTEM_LOGS_DIR.exists():
            for log_file in SYSTEM_LOGS_DIR.glob("*.log"):
                try:
                    file_path = str(log_file)
                    current_size = log_file.stat().st_size
                    saved_pos = persisted.get(file_path, -1)
                    if 0 <= saved_pos <= current_size:
                        self._record_position(file_path, saved_pos)
                    else:
                        self._record_position(file_path, current_size)
                except Exception as exc:
                    logger.warning("Failed to initialize position for system log '%s': %s", log_file, exc)
                    continue


def start_branch_log_watcher() -> Any:
    """Start the branch log watcher."""
    # The caller must keep a reference to the returned observer to keep it alive.
    global _branch_log_observer, _active_watcher

    if not WATCHDOG_AVAILABLE:
        return None

    if _branch_log_observer and _branch_log_observer.is_alive():
        stop_branch_log_watcher()

    if not AIPASS_PKG_ROOT.exists():
        return None

    if WatchdogObserver is None:
        return None

    _load_seen_hashes()

    watcher = BranchLogWatcher()
    watcher.initialize_positions()
    _active_watcher = watcher
    _callback = watcher.on_modified
    observer = WatchdogObserver()

    for branch_dir in AIPASS_PKG_ROOT.iterdir():
        if not branch_dir.is_dir():
            continue
        logs_dir = branch_dir / "logs"
        if logs_dir.exists():
            observer.schedule(watcher, str(logs_dir), recursive=False)
            watcher.watched_dirs.add(logs_dir)

    if SYSTEM_LOGS_DIR.exists():
        observer.schedule(watcher, str(SYSTEM_LOGS_DIR), recursive=False)

    observer.start()
    _branch_log_observer = observer

    return observer


def stop_branch_log_watcher() -> None:
    """Stop the branch log watcher and persist positions to disk."""
    global _branch_log_observer, _active_watcher

    if _active_watcher is not None:
        _flush_trigger_data(force=True)
        _active_watcher = None

    if _branch_log_observer and _branch_log_observer.is_alive():
        _branch_log_observer.stop()
        _branch_log_observer.join(timeout=5.0)
        _branch_log_observer = None


def is_branch_log_watcher_active() -> bool:
    """Check if branch log watcher is running."""
    return _branch_log_observer is not None and _branch_log_observer.is_alive()


def clear_seen_hashes() -> None:
    """Clear the deduplication hash set (memory and disk)."""
    global _seen_error_hashes
    _seen_error_hashes.clear()
    _flush_trigger_data(force=True)


def get_watcher_status() -> Dict[str, Any]:
    """Get current watcher status."""
    # pending_flush shows state a crash now would lose.
    tracked_files = 0
    if _active_watcher is not None:
        tracked_files = len(_active_watcher.log_positions)
    return {
        "active": is_branch_log_watcher_active(),
        "watchdog_available": WATCHDOG_AVAILABLE,
        "seen_hashes_count": len(_seen_error_hashes),
        "tracked_log_files": tracked_files,
        "pending_flush": _data_dirty,
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
