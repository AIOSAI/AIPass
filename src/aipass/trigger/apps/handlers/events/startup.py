# =================== AIPass ====================
# Name: startup.py
# Description: Startup event handler with error catch-up scanning
# Version: 1.3.0
# Created: 2025-12-04
# Modified: 2026-09-12
# =============================================

"""Startup Event Handler - Run startup checks

Replaces Prax logger's hardcoded calls with event-based approach.
Includes error catch-up: scans system logs for unprocessed errors on each startup.

DPLAN-037 hardening (2026-02-26):
    - MAX_ERRORS_PER_SCAN: Stop scanning after this many new errors (prevents 100K+ event storms)
    - MAX_FILE_SIZE_BYTES: Skip log files larger than this threshold (prevents scanning 6MB files)
    - SCAN_TIME_BUDGET_SECONDS: Abort scan if it exceeds this duration

Catch-up state lives in trigger_json/error_catchup.json. It used to live in
trigger_json/trigger_data.json — a name json_handler's trio machinery owns for
module "trigger", which validates such a file against a data template and
overwrites it when the shape does not match. This file has never carried the
template's created/last_updated keys, so a single trio call resolving to caller
module "trigger" would have blanked the processed-hash set and re-dispatched
every already-handled error. Same defect as the medic state move; see
medic_state.py. _load_trigger_data() migrates on first read.

last_scan_timestamp advances ONLY after a scan that covered every candidate
file (DPLAN-0339 step 2, row 12). It used to advance unconditionally, so any
of the DPLAN-037 limits above silently discarded the window they aborted in:
the files the scan never reached fell behind the new cutoff and their errors
were never recoverable. See ScanOutcome and _run_error_catchup.
"""

import json
import hashlib
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Set
from aipass.trigger.apps.config import (
    TRIGGER_JSON_DIR,
    TRIGGER_ROOT,
    append_trail,
    atomic_write_json,
    migrate_json_file,
    trail_logger,
)
from aipass.trigger.apps.handlers.json import json_handler

SYSTEM_LOGS_DIR = TRIGGER_ROOT.parent.parent.parent / "system_logs"
CATCHUP_STATE_FILE = TRIGGER_JSON_DIR / "error_catchup.json"
LEGACY_CATCHUP_STATE_FILE = TRIGGER_JSON_DIR / "trigger_data.json"
SUPPRESSED_LOG = TRIGGER_ROOT / "logs" / "medic_suppressed.jsonl"

MAX_HASHES = 500
MAX_LOOKBACK_HOURS = 24

# DPLAN-037: Safeguards to prevent unbounded scanning
MAX_ERRORS_PER_SCAN = 50  # Stop after this many new errors found
MAX_FILE_SIZE_BYTES = 512_000  # Skip files larger than 500KB
SCAN_TIME_BUDGET_SECONDS = 5.0  # Abort entire scan after this many seconds

# Deliberately NOT prax: this handler runs on the event path the log watchers
# read, so a line through prax would be detected and fired straight back at it.
# The sidecar is `.jsonl`, which the watchers skip — they read only `*.log`.
logger = trail_logger(TRIGGER_ROOT / "logs" / "startup_handler.jsonl")


def _load_trigger_data() -> Dict[str, Any]:
    """Load error_catchup.json, migrating off the legacy path on first read."""
    try:
        migrate_json_file(LEGACY_CATCHUP_STATE_FILE, CATCHUP_STATE_FILE)
        if CATCHUP_STATE_FILE.exists():
            with open(CATCHUP_STATE_FILE, "r", encoding="utf-8") as f:
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
        logger.warning(f"load trigger data failed: {exc}")
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
    """Save error_catchup.json."""
    try:
        atomic_write_json(CATCHUP_STATE_FILE, data)
    except Exception as exc:
        logger.warning(f"save trigger data failed: {exc}")
        return


def _log_suppression(reason: str) -> None:
    """Log a catchup suppression event to medic_suppressed.jsonl."""
    entry = {"ts": datetime.now().isoformat(), "source": "error_catchup", "reason": reason}
    if not append_trail(SUPPRESSED_LOG, entry):
        logger.warning("log suppression write failed")


class ScanOutcome(NamedTuple):
    """What one catch-up scan found, and whether it got through the whole tree.

    `completed` is the row-12 gate: it is True only when the scan read every
    candidate file to its end. Anything that cut the walk short — a DPLAN-037
    limit, or a file skipped for size — makes it False, and the caller then
    leaves last_scan_timestamp where it was so the next run covers the same
    window again. `reason` names what stopped it, for the log line; it is ""
    exactly when `completed` is True.

    Holding the timestamp back cannot re-dispatch what was already found:
    processed_hashes is persisted on every run, aborted or not, and the
    fingerprint gate drops a hash it has seen. What it re-covers is only the
    part of the window the scan never read.

    The cost of holding it back is bounded by MAX_LOOKBACK_HOURS, so the worst
    case is a 24-hour window instead of a one-minute one. Measured on this tree
    2026-09-11, 363 files: 181 ms cold (full 24 h) against 161 ms warm — 20 ms.
    That bound is what makes it safe to treat a permanently oversized file as
    "not completed" rather than inventing a second, softer verdict for it.
    """

    errors: List[Dict[str, Any]]
    completed: bool
    reason: str


def _generate_error_hash(source_module: str, message: str) -> str:
    """Generate 8-char hash for error deduplication.

    Deliberately timestamp-free: the key answers "is this the same error?",
    not "is this the same line". One event per distinct error is the point —
    37 identical lines must not become 37 dispatches.

    What the key must NOT do is throw the repeats away. It did until
    2026-09-07: every line after the first was dropped, so a burst and a
    single line were indistinguishable and the payload said `count=1`. Gate 3
    in error_detected needs `count >= 2` before it dispatches, so the loudest
    errors in the log were the ones held back as "could be transient".
    _scan_single_log_file now counts every matching line against this key
    (FPLAN-0492 wave 5, shape ruled by @devpulse).
    """
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
        logger.warning(f"parse log line failed: {exc}")
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
        logger.warning(f"detect branch from log failed: {exc}")
        return "UNKNOWN"


def _count_repeat(entry: Optional[Dict[str, Any]], line_iso: str) -> None:
    """Fold one more sighting into an entry already collected this scan.

    `entry` is None when the hash came from a previous run's persisted state —
    there is no entry here to count against, so the line stays dropped.
    """
    if entry is None:
        return
    entry["count"] += 1
    if line_iso > entry["last_seen"]:
        entry["last_seen"] = line_iso
    if line_iso < entry["first_seen"]:
        entry["first_seen"] = line_iso


def _scan_single_log_file(
    log_file: Path,
    cutoff: datetime,
    processed_hashes: Set[str],
    errors: List[Dict[str, Any]],
    scan_start: float,
    by_hash: Dict[str, Dict[str, Any]],
) -> Optional[str]:
    """Scan a single log file for ERROR entries.

    Args:
        by_hash: Entries collected so far this scan, keyed by error hash, so a
            repeat line can be counted instead of dropped. Shared across files
            — the same error in two logs is one error.

    Returns:
        None when the whole file was read and scanning should continue, or the
        reason string naming the limit that stopped it. A reason means files
        after this one were never read, which is what row 12 has to know: it
        travels up to ScanOutcome rather than being flattened back to a bool.
    """
    with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if len(errors) >= MAX_ERRORS_PER_SCAN:
                _log_suppression(
                    f"MAX_ERRORS_PER_SCAN ({MAX_ERRORS_PER_SCAN}) reached. Stopping scan to prevent event storm."
                )
                return f"MAX_ERRORS_PER_SCAN ({MAX_ERRORS_PER_SCAN}) reached"

            elapsed = time.monotonic() - scan_start
            if elapsed >= SCAN_TIME_BUDGET_SECONDS:
                return f"time budget exceeded mid-file ({elapsed:.1f}s >= {SCAN_TIME_BUDGET_SECONDS}s)"

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
            line_iso = line_ts.isoformat() if line_ts else datetime.now().isoformat()

            if error_hash in processed_hashes:
                _count_repeat(by_hash.get(error_hash), line_iso)
                continue

            branch = _detect_branch_from_log(str(log_file))
            entry = {
                "branch": branch,
                "module": module,
                "message": message,
                "log_file": str(log_file),
                "error_hash": error_hash,
                "timestamp": line_iso,
                "level": parsed["level"].lower(),
                # Occurrence facts. `count` is what gate 3 reads; first/last_seen
                # are what the notification prints. No severity is derived from
                # any of them — catch-up has never set severity and still does
                # not, so the registry default stands (@devpulse's ruling).
                "count": 1,
                "first_seen": line_iso,
                "last_seen": line_iso,
            }
            errors.append(entry)
            by_hash[error_hash] = entry
            processed_hashes.add(error_hash)

    return None


def _scan_system_logs_for_errors(since_timestamp: Optional[datetime], processed_hashes: Set[str]) -> ScanOutcome:
    """Scan system logs for ERROR entries since timestamp.

    DPLAN-037 safeguards, every one of which can cut the walk short:
        - Skips files larger than MAX_FILE_SIZE_BYTES
        - Stops after MAX_ERRORS_PER_SCAN new errors found
        - Aborts if total scan time exceeds SCAN_TIME_BUDGET_SECONDS

    Returns:
        ScanOutcome. `errors` holds one dict per distinct error — branch,
        module, message, log_file, error_hash, timestamp, level, and the
        occurrence facts count / first_seen / last_seen, with `count` holding
        how many lines produced it. `completed` and `reason` report whether
        every candidate file was read; see ScanOutcome for why the caller needs
        that and not just the list.
    """
    errors: List[Dict[str, Any]] = []
    # Same list, keyed for O(1) repeat lookup. MAX_ERRORS_PER_SCAN still measures
    # len(errors), so counting repeats cannot widen the storm guard.
    by_hash: Dict[str, Dict[str, Any]] = {}
    scan_start = time.monotonic()

    if not SYSTEM_LOGS_DIR.exists():
        # Nothing to read is not a failure to read: there is no unscanned
        # window being left behind, so the timestamp may advance.
        return ScanOutcome(errors, True, "")

    cutoff = since_timestamp
    if cutoff is None:
        cutoff = datetime.now() - timedelta(hours=MAX_LOOKBACK_HOURS)

    files_skipped_size = 0

    abort_reason = ""

    for log_file in SYSTEM_LOGS_DIR.glob("*.log"):
        elapsed = time.monotonic() - scan_start
        if elapsed >= SCAN_TIME_BUDGET_SECONDS:
            abort_reason = f"time budget exceeded between files ({elapsed:.1f}s >= {SCAN_TIME_BUDGET_SECONDS}s)"
            _log_suppression(f"{abort_reason}. Found {len(errors)} errors so far, aborting scan.")
            break

        try:
            file_size = log_file.stat().st_size
            if file_size > MAX_FILE_SIZE_BYTES:
                files_skipped_size += 1
                continue
        except Exception as exc:
            logger.warning(f"stat log file {log_file}: {exc}")
            continue

        try:
            abort_reason = _scan_single_log_file(log_file, cutoff, processed_hashes, errors, scan_start, by_hash) or ""
            if abort_reason:
                break
        except Exception as exc:
            logger.warning(f"scan log file {log_file}: {exc}")
            continue

    if files_skipped_size > 0:
        skipped = f"skipped {files_skipped_size} file(s) exceeding MAX_FILE_SIZE_BYTES ({MAX_FILE_SIZE_BYTES})"
        _log_suppression(skipped.capitalize())
        # A file too large to read is a hole in the window whether or not the
        # walk finished, so it blocks the timestamp too — @devpulse's wording
        # for row 12 is "aborted OR skipped files". An abort already found is
        # the more specific answer, so it is the one reported.
        abort_reason = abort_reason or skipped

    return ScanOutcome(errors, not abort_reason, abort_reason)


def _run_error_catchup(fire_event: Optional[Callable[..., object]] = None) -> None:
    """Catch-up on errors missed while Trigger wasn't running.

    Loads last_scan_timestamp from error_catchup.json, scans system logs for
    ERROR entries since that time, fires error_detected events for new errors,
    and persists the processed hashes.

    The timestamp is the one thing here that is conditional. It advances only
    on a completed scan (row 12, DPLAN-0339 step 2); an aborted or
    file-skipping scan leaves it alone so the next run re-covers the window it
    did not read. Processed hashes are persisted either way — they are what
    stops the re-covered window from re-dispatching what was already handled.

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
                logger.warning(f"parse last_scan_timestamp '{last_scan}': {exc}")

        processed_hashes = set(catchup.get("processed_hashes", []))

        outcome = _scan_system_logs_for_errors(since_ts, processed_hashes)

        if outcome.errors and fire_event is not None:
            for error in outcome.errors:
                fire_event("error_detected", **error)

        hash_list = list(processed_hashes)
        max_h = catchup.get("max_hashes", MAX_HASHES)
        if len(hash_list) > max_h:
            hash_list = hash_list[-max_h:]

        if outcome.completed:
            catchup["last_scan_timestamp"] = datetime.now().isoformat()
        else:
            _log_suppression(
                f"last_scan_timestamp HELD at {last_scan} — scan did not cover every file: {outcome.reason}"
            )
        catchup["processed_hashes"] = hash_list
        data["error_catchup"] = catchup

        _save_trigger_data(data)

        json_handler.log_operation(
            "startup_catchup",
            {"errors_found": len(outcome.errors), "completed": outcome.completed, "reason": outcome.reason},
        )

    except Exception as exc:
        logger.warning(f"error catchup scan failed: {exc}")
        return


def run_startup_catchup(fire_event: Optional[Callable[..., object]] = None) -> None:
    """Run the error catch-up explicitly, without going through the event bus.

    The door for a process that owns recovery and should not have to wait for
    somebody else to fire an event at it. log_watcher_service.main() calls this
    once its watchers are up, so the service recovers errors missed while it
    was down whether or not anything fires `startup` (DPLAN-0339 step 2, the
    prerequisite for prax dropping the per-process fire at logger.py:132).

    Safe to run alongside that fire while it still exists: the scan dedupes on
    persisted processed_hashes, so a second run moments later finds nothing new
    and dispatches nothing twice.

    Args:
        fire_event: Callback used to fire error_detected for each error found.
            None scans and records without dispatching.
    """
    _run_error_catchup(fire_event)


def handle_startup(**kwargs: Any) -> None:
    """Run startup checks - replaces Prax logger's hardcoded calls.

    Args:
        **kwargs: Event data, may include 'fire_event' callback
    """
    # Error catch-up (scan for missed errors)
    fire_event = kwargs.get("fire_event")
    _run_error_catchup(fire_event)
