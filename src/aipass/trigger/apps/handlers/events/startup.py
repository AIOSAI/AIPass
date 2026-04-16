# =================== AIPass ====================
# Name: startup.py
# Description: Startup event handler with error catch-up scanning
# Version: 1.0.0
# Created: 2025-12-04
# Modified: 2026-02-26
# =============================================

"""Startup Event Handler - Run startup checks

Replaces Prax logger's hardcoded calls with event-based approach.
Includes error catch-up: scans system logs for unprocessed errors on each startup.

DPLAN-037 hardening (2026-02-26):
    - MAX_ERRORS_PER_SCAN: Stop scanning after this many new errors (prevents 100K+ event storms)
    - MAX_FILE_SIZE_BYTES: Skip log files larger than this threshold (prevents scanning 6MB files)
    - SCAN_TIME_BUDGET_SECONDS: Abort scan if it exceeds this duration
"""

import json
import hashlib
import time
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Set
from aipass.trigger.apps.config import TRIGGER_ROOT, atomic_write_json
from aipass.trigger.apps.handlers.json import json_handler

SYSTEM_LOGS_DIR = TRIGGER_ROOT.parent.parent.parent / "system_logs"
TRIGGER_DATA_FILE = TRIGGER_ROOT / "trigger_json" / "trigger_data.json"
SUPPRESSED_LOG = TRIGGER_ROOT / "logs" / "medic_suppressed.log"

MAX_HASHES = 500
MAX_LOOKBACK_HOURS = 24

# DPLAN-037: Safeguards to prevent unbounded scanning
MAX_ERRORS_PER_SCAN = 50  # Stop after this many new errors found
MAX_FILE_SIZE_BYTES = 512_000  # Skip files larger than 500KB
SCAN_TIME_BUDGET_SECONDS = 5.0  # Abort entire scan after this many seconds

_HANDLER_LOG = TRIGGER_ROOT / "logs" / "startup_handler.log"


def _log_warning(message: str) -> None:
    """Log warning to file (event handlers cannot import Prax logger - causes recursion)."""
    try:
        _HANDLER_LOG.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        with open(_HANDLER_LOG, "a", encoding="utf-8") as f:
            f.write(f"{ts} | WARNING | {message}\n")
    except Exception:
        pass


def _load_trigger_data() -> Dict[str, Any]:
    """Load trigger_data.json with error_catchup section."""
    try:
        if TRIGGER_DATA_FILE.exists():
            with open(TRIGGER_DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if "error_catchup" not in data:
                data["error_catchup"] = {
                    "last_scan_timestamp": None,
                    "processed_hashes": [],
                    "max_hashes": MAX_HASHES,
                    "max_lookback_hours": MAX_LOOKBACK_HOURS,
                }
            return data
    except Exception as exc:
        _log_warning(f"load trigger data failed: {exc}")
        return {
            "error_catchup": {
                "last_scan_timestamp": None,
                "processed_hashes": [],
                "max_hashes": MAX_HASHES,
                "max_lookback_hours": MAX_LOOKBACK_HOURS,
            }
        }
    return {
        "error_catchup": {
            "last_scan_timestamp": None,
            "processed_hashes": [],
            "max_hashes": MAX_HASHES,
            "max_lookback_hours": MAX_LOOKBACK_HOURS,
        }
    }


def _save_trigger_data(data: Dict[str, Any]) -> None:
    """Save trigger_data.json."""
    try:
        atomic_write_json(TRIGGER_DATA_FILE, data)
    except Exception as exc:
        _log_warning(f"save trigger data failed: {exc}")
        return


def _log_suppression(reason: str) -> None:
    """Log a catchup suppression event to medic_suppressed.log.

    Args:
        reason: Description of why scanning was capped or skipped
    """
    try:
        SUPPRESSED_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(SUPPRESSED_LOG, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat()} | error_catchup: {reason}\n")
    except Exception as exc:
        _log_warning(f"log suppression write failed: {exc}")
        return


def _generate_error_hash(source_module: str, message: str) -> str:
    """Generate 8-char hash for error deduplication."""
    content = f"{source_module}:{message}"
    return hashlib.md5(content.encode()).hexdigest()[:8]


def _parse_log_line(log_line: str) -> Optional[Dict[str, str]]:
    """Parse a log line and extract fields if it's an ERROR.

    Uses positional parsing (like log_watcher.py) instead of content-matching
    to avoid false positives from lines that mention 'ERROR' in their message text.

    Args:
        log_line: Raw log line

    Returns:
        Dict with timestamp, module, level, message if ERROR/CRITICAL.
        None otherwise.
    """
    try:
        # Prax format: timestamp | module | LEVEL | message
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

        # Python logging format: timestamp - module - LEVEL - message
        if " - " in log_line:
            parts = log_line.split(" - ", 3)
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
    except Exception as exc:
        _log_warning(f"parse log line failed: {exc}")
        return None


def _extract_timestamp(timestamp_str: str) -> Optional[datetime]:
    """Parse timestamp string into datetime.

    Args:
        timestamp_str: Timestamp from log line

    Returns:
        datetime object, or None if unparseable
    """
    formats = [
        "%Y-%m-%d %H:%M:%S,%f",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(timestamp_str.strip(), fmt)
        except ValueError:
            continue
    return None


def _detect_branch_from_log(log_file: str) -> str:
    """Detect branch from log filename (e.g., drone_ops.log -> DRONE)."""
    try:
        name = Path(log_file).stem
        if "_" in name:
            return name.split("_")[0].upper()
        return name.upper()
    except Exception as exc:
        _log_warning(f"detect branch from log failed: {exc}")
        return "UNKNOWN"


def _scan_single_log_file(
    log_file: Path,
    cutoff: datetime,
    processed_hashes: Set[str],
    errors: List[Dict[str, Any]],
    scan_start: float,
) -> bool:
    """Scan a single log file for ERROR entries.

    Returns:
        True if scanning should continue, False if a limit was hit.
    """
    with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if len(errors) >= MAX_ERRORS_PER_SCAN:
                _log_suppression(
                    f"MAX_ERRORS_PER_SCAN ({MAX_ERRORS_PER_SCAN}) reached. Stopping scan to prevent event storm."
                )
                return False

            elapsed = time.monotonic() - scan_start
            if elapsed >= SCAN_TIME_BUDGET_SECONDS:
                return False

            line = line.strip()
            if not line:
                continue

            parsed = _parse_log_line(line)
            if not parsed:
                continue

            line_ts = _extract_timestamp(parsed["timestamp"])
            if line_ts and line_ts < cutoff:
                continue

            module = parsed["module"]
            message = parsed["message"]
            error_hash = _generate_error_hash(module, message)

            if error_hash in processed_hashes:
                continue

            branch = _detect_branch_from_log(str(log_file))
            errors.append(
                {
                    "branch": branch,
                    "module": module,
                    "message": message,
                    "log_file": str(log_file),
                    "error_hash": error_hash,
                    "timestamp": line_ts.isoformat() if line_ts else datetime.now().isoformat(),
                    "level": parsed["level"].lower(),
                }
            )
            processed_hashes.add(error_hash)

    return True


def _scan_system_logs_for_errors(
    since_timestamp: Optional[datetime], processed_hashes: Set[str]
) -> List[Dict[str, Any]]:
    """Scan system logs for ERROR entries since timestamp.

    DPLAN-037 safeguards:
        - Skips files larger than MAX_FILE_SIZE_BYTES
        - Stops after MAX_ERRORS_PER_SCAN new errors found
        - Aborts if total scan time exceeds SCAN_TIME_BUDGET_SECONDS

    Returns:
        List of error dicts with: branch, module, message, log_file, error_hash, timestamp
    """
    errors: List[Dict[str, Any]] = []
    scan_start = time.monotonic()

    if not SYSTEM_LOGS_DIR.exists():
        return errors

    cutoff = since_timestamp
    if cutoff is None:
        cutoff = datetime.now() - timedelta(hours=MAX_LOOKBACK_HOURS)

    files_skipped_size = 0

    for log_file in SYSTEM_LOGS_DIR.glob("*.log"):
        elapsed = time.monotonic() - scan_start
        if elapsed >= SCAN_TIME_BUDGET_SECONDS:
            _log_suppression(
                f"Time budget exceeded ({elapsed:.1f}s >= {SCAN_TIME_BUDGET_SECONDS}s). "
                f"Found {len(errors)} errors so far, aborting scan."
            )
            break

        try:
            file_size = log_file.stat().st_size
            if file_size > MAX_FILE_SIZE_BYTES:
                files_skipped_size += 1
                continue
        except Exception as exc:
            _log_warning(f"stat log file {log_file}: {exc}")
            continue

        try:
            should_continue = _scan_single_log_file(log_file, cutoff, processed_hashes, errors, scan_start)
            if not should_continue:
                break
        except Exception as exc:
            _log_warning(f"scan log file {log_file}: {exc}")
            continue

    if files_skipped_size > 0:
        _log_suppression(f"Skipped {files_skipped_size} file(s) exceeding MAX_FILE_SIZE_BYTES ({MAX_FILE_SIZE_BYTES})")

    return errors


def _run_error_catchup(fire_event: Optional[Callable[..., None]] = None) -> None:
    """Catch-up on errors missed while Trigger wasn't running.

    Loads last_scan_timestamp from trigger_data.json, scans system logs for
    ERROR entries since that time, fires error_logged events for new errors,
    and updates state with new timestamp and processed hashes.

    DPLAN-037 safeguards applied via _scan_system_logs_for_errors().

    Args:
        fire_event: Callback to fire events (passed from module via kwargs)
    """
    try:
        data = _load_trigger_data()
        catchup = data.get("error_catchup", {})

        last_scan = catchup.get("last_scan_timestamp")
        since_ts = None
        if last_scan:
            try:
                since_ts = datetime.fromisoformat(last_scan)
            except Exception as exc:
                _log_warning(f"parse last_scan_timestamp '{last_scan}': {exc}")

        processed_hashes = set(catchup.get("processed_hashes", []))

        errors = _scan_system_logs_for_errors(since_ts, processed_hashes)

        if errors and fire_event is not None:
            for error in errors:
                fire_event("error_detected", **error)

        hash_list = list(processed_hashes)
        max_h = catchup.get("max_hashes", MAX_HASHES)
        if len(hash_list) > max_h:
            hash_list = hash_list[-max_h:]

        catchup["last_scan_timestamp"] = datetime.now().isoformat()
        catchup["processed_hashes"] = hash_list
        data["error_catchup"] = catchup

        _save_trigger_data(data)

        json_handler.log_operation("startup_catchup", {"errors_found": len(errors)})

    except Exception as exc:
        _log_warning(f"error catchup scan failed: {exc}")
        return


def _run_memory_check() -> None:
    """Run memory rollover check if available.

    Uses memory's public modules API to avoid cross-branch handler guard.
    Silent failure - handlers cannot use logger or print.
    """
    try:
        from aipass.memory.apps.modules.rollover import check_and_rollover

        check_and_rollover()
    except ImportError:
        return  # Memory not available
    except Exception as exc:
        _log_warning(f"memory check failed: {exc}")
        return


def handle_startup(**kwargs: Any) -> None:
    """Run startup checks - replaces Prax logger's hardcoded calls.

    Args:
        **kwargs: Event data, may include 'fire_event' callback
    """
    # Error catch-up (scan for missed errors)
    fire_event = kwargs.get("fire_event")
    _run_error_catchup(fire_event)

    # Memory rollover check
    _run_memory_check()
