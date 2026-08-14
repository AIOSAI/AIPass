# =================== AIPass ====================
# Name: log_watcher.py
# Description: Branch log watcher event producer for error detection
# Version: 2.6.0
# Created: 2026-02-02
# Modified: 2026-08-04
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
import time
import threading
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

# Log levels this watcher acts on. Errors drive the medic dispatch pipeline;
# warnings drive nothing but the escalation digest lane — they are counted by
# signature and only surface when one keeps repeating (DPLAN-0283).
ERROR_LEVELS = ("ERROR", "CRITICAL")
WARNING_LEVELS = ("WARNING", "WARN")

# How far down the rotation chain ('<name>.log.1' .. '.N') to look for a
# rotated-out file. Matches prax RotatingFileHandler backup_count.
MAX_BACKUP_CHAIN_DEPTH = 3

# Log filenames to exclude from watching (self-referential / dispatch feedback)
# Compared case-insensitively against Path.name (see on_modified)
EXCLUDED_LOG_FILES: Set[str] = {
    "dispatch.log",
    "medic_suppressed.jsonl",
    "rate_limited.jsonl",
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

# Debounced trigger_data.json writer — coalesces positions + hashes into one
# write per flush interval instead of per-event.
_FLUSH_INTERVAL = 5.0
_data_dirty: bool = False
_last_flush_time: float = 0.0
_flush_lock = threading.Lock()

# Explicit mapping of system_logs filenames to their owning branch.
# Used for files that don't follow the <branch>_<module>.log naming convention.
SYSTEM_LOGS_BRANCH_MAP: Dict[str, str] = {
    "telegram_bridge.log": "API",
    "telegram_chats.log": "API",
}

SYSTEM_LOGS_DIR = AIPASS_PKG_ROOT.parent.parent / "system_logs"

# Branch prefixes that appear in system_logs filenames (<prefix>_<module>.log).
# This list is a FLOOR, not the answer: the real names come from the live tree
# (_known_branch_names) because a hardcoded roster silently mints UNKNOWN for
# every citizen born after it was written. On 2026-08-14 it held 11 names
# against 17 branches, so @hooks, @backup, @commons, @daemon, @skills and
# @aipass lost their attribution in system_logs. The list survives only to
# answer when the tree cannot be read.
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

# Branch directory names read from disk, refreshed on a TTL so a newly spawned
# citizen is attributed within the minute without a listdir per log line.
_BRANCH_NAMES_TTL_SECONDS = 60.0
_branch_names_cache: tuple = (0.0, ())

# Event fire callback (set by module, avoids handler importing from modules)
# Return type is deliberately `object`, not None: Trigger.fire returns an
# execution summary (APLAN-0008) and the watcher ignores it. Pinning the
# callback to -> None would reject the real bus as an invalid callback.
_fire_event: Optional[Callable[..., object]] = None

# Cached answer to "should I read WARNING lines at all?".  This runs per log
# line, so it must not hit the config file every time; the TTL keeps an
# operator's edit taking effect within a minute without a read per line.
_WARNING_CAPTURE_TTL_SECONDS = 60.0
_warning_capture_cache: tuple = (0.0, True)


def _warning_capture_enabled() -> bool:
    """Check whether branch-log WARNING lines feed the escalation lane.

    Fails OPEN: if the config cannot be read, warnings keep being collected.
    Losing the count silently is the failure this whole lane exists to stop.

    Returns:
        True when WARNING lines should be parsed and fired
    """
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


def _load_log_inodes() -> Dict[str, int]:
    """
    Load persisted log inodes from trigger_data.json.

    Parallel key to 'log_positions' (kept separate so the on-disk
    Dict[str, int] position shape never changes). Absence means
    "no inode known", which simply disables the rotation drain until
    positions are recorded again.

    Returns:
        Dict mapping file paths to inode numbers
    """
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


def _known_branch_names() -> tuple:
    """
    Branch names taken from the live tree, longest first.

    Longest-first matters: "ai_mail_delivery" must resolve to ai_mail, never
    to a shorter branch that happens to share its opening characters.

    Returns:
        Tuple of branch directory names, plus the static floor list.
    """
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
        # Unreadable tree — answer from the floor list rather than going blind.
        logger.warning("Failed to list branch directories under '%s': %s", AIPASS_PKG_ROOT, exc)

    resolved = tuple(sorted(found, key=len, reverse=True))
    _branch_names_cache = (now, resolved)
    return resolved


def _system_log_branch_twin(log_path: str) -> Optional[Path]:
    """
    Find the branch log holding the same lines as this system_logs file.

    Prax dual-writes: one call lands in src/aipass/<branch>/logs/<module>.log
    AND in system_logs/<branch>_<module>.log. Measured 2026-08-14 across the
    whole tree — 230 of 243 system_logs files had a twin, and 229 of those
    twins were written within one second of their system copy.

    Args:
        log_path: Full path to a system_logs file

    Returns:
        Path to the twin branch log, or None when nothing else covers it.
    """
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
            # Match filename prefix against live branch names (longest-first)
            name_stem = path.stem  # e.g. "memory_rollover" from "memory_rollover.log"
            for prefix in _known_branch_names():
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


def _parse_prax_log_line(log_line: str, levels: tuple = ERROR_LEVELS) -> Optional[Dict[str, str]]:
    """
    Parse a log line in Prax format or Python logging format.

    Formats supported:
        - Prax:   timestamp | module | LEVEL | message
        - Python: timestamp - module - LEVEL - message

    Args:
        log_line: Raw log line
        levels: Levels to accept — defaults to ERROR/CRITICAL. The escalation
            lane passes WARNING_LEVELS to collect repeat-warning signatures.

    Returns:
        Dict with keys: timestamp, module, level, message
        None if parsing fails or the line's level is not in *levels*
    """
    try:
        # Try Prax format first (pipe-separated)
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
                if level in levels:
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


def set_event_callback(callback: Callable[..., object]) -> None:
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
        self.log_inodes: Dict[str, int] = {}

    def _record_position(self, file_path: str, position: int) -> None:
        """
        Record byte position and inode identity for a watched file.

        The inode is what later proves a shrunken file was rotated away
        (renamed to '<name>.log.1') rather than truncated in place.

        Args:
            file_path: Path to log file
            position: Byte offset already processed
        """
        self.log_positions[file_path] = position
        try:
            self.log_inodes[file_path] = Path(file_path).stat().st_ino
        except OSError as exc:
            logger.warning("Failed to record inode for '%s': %s", file_path, exc)
            self.log_inodes.pop(file_path, None)

    def _drain_rotated_tail(self, file_path: str, last_pos: int) -> None:
        """
        Process the unread tail of a log file that was just rotated away.

        The rotated file is located BY INODE across the backup chain
        ('<file_path>.1' .. '.MAX_BACKUP_CHAIN_DEPTH', stopping at the first
        gap): the only file drained is the one whose CURRENT inode matches the
        inode recorded for the live path - proof it is literally the file we
        were reading, now renamed. No match anywhere in the chain, a backup
        shorter than the recorded position, or an unknown inode all skip
        silently rather than re-fire old errors.

        DELIBERATE SCOPE LIMIT: when the match is found at '.2' or later, at
        least one whole backup rotated past unseen. Those skipped backups are
        NOT replayed - re-reading a full backup would fire a flood of events
        for already-historical lines, which is worse than the gap. Only the
        matched file's own tail is drained, and one warning names the file and
        the number of skipped backups so the loss is visible in the log
        instead of silent.

        Args:
            file_path: Path to the live log file
            last_pos: Byte offset processed before the rotation
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
        if "/aipass/" in file_path and "/logs/" in file_path:
            return True
        if "/system_logs/" not in file_path:
            return False
        # Prax writes the same line to the branch's own logs/ dir and to
        # system_logs/. Reading both counts one event twice, and the copy to
        # drop is this one: its branch is guessed from the filename, while the
        # branch copy is attributed by the directory it sits in.
        return _system_log_branch_twin(file_path) is None

    def _read_new_lines(self, file_path: str) -> None:
        """
        Read new content from a log file and process lines.

        Rotation is detected by INODE, not by size: a fresh log can already
        have grown past the recorded offset by the time the event arrives, and
        a size-only check would then seek into the middle of a brand new file.
        An inode of 0 (possible on some Windows filesystems) means "unknown"
        and falls back to the size-based check.

        Args:
            file_path: Path to log file
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
                for line in new_lines.strip().split("\n"):
                    if line.strip():
                        self._process_log_line(line, file_path)
            self._record_position(file_path, f.tell())

        _mark_data_dirty()

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

    def _process_warning_line(self, log_line: str, log_path: str) -> None:
        """
        Fire warning_logged for a WARNING line so repeats can escalate.

        Warnings never enter the error registry and never dispatch anyone —
        this path exists purely to feed the escalation digest lane, which
        counts by signature and mails the operator only when one repeats past
        its threshold. Before this, branch-log warnings were seen by nothing
        at all: the parser dropped every non-ERROR line, so tier 1 of the
        digest would have covered system_logs/ only.

        Off by config (escalation.watch_branch_log_warnings) for operators who
        want the extra lines left unread.

        Args:
            log_line: Raw log line
            log_path: Path to log file
        """
        try:
            if not _warning_capture_enabled():
                return

            parsed = _parse_prax_log_line(log_line, levels=WARNING_LEVELS)
            if not parsed:
                return

            # Same guards the error path uses: lines ABOUT an error, and old
            # lines replayed from a rotation, are not new signal.
            if _SEMANTIC_EXCLUSION_PATTERNS.search(parsed["message"]):
                return
            if _is_stale_entry(parsed["timestamp"]):
                return

            if _fire_event is None:
                return

            _fire_event(
                "warning_logged",
                branch=_detect_branch_from_path(log_path),
                message=parsed["message"],
                error_hash=_generate_error_hash(parsed["module"], parsed["message"]),
                timestamp=parsed["timestamp"],
                log_file=log_path,
                module_name=parsed["module"],
                level=parsed["level"],
                raw_line=log_line,
            )
        except Exception as exc:
            logger.warning("Failed to process warning line from '%s': %s", log_path, exc)

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
                self._process_warning_line(log_line, log_path)
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
        # Seed inodes from disk; the live stat below wins for files that exist
        self.log_inodes.update(_load_log_inodes())

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
                        self._record_position(file_path, saved_pos)
                    else:
                        self._record_position(file_path, current_size)
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
                        self._record_position(file_path, saved_pos)
                    else:
                        self._record_position(file_path, current_size)
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

    # Flush positions + hashes before stopping
    if _active_watcher is not None:
        _flush_trigger_data(force=True)
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
    _flush_trigger_data(force=True)


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
