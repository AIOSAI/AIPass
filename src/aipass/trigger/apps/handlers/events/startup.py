# =================== AIPass ====================
# Name: startup.py
# Description: Startup event handler with error catch-up scanning
# Version: 1.5.0
# Created: 2025-12-04
# Modified: 2026-10-17
# =============================================

"""Startup Event Handler - Run startup checks

Never store state in trigger_data.json: json_handler's trio owns that name and would blank the processed hashes.
last_scan_timestamp advances only after a scan covered every file, or the unread window is lost for good.
"""

import json
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

MAX_ERRORS_PER_SCAN = 50  # Stop after this many new errors found
MAX_FILE_SIZE_BYTES = 512_000  # Skip files larger than 500KB
SCAN_TIME_BUDGET_SECONDS = 5.0  # Abort entire scan after this many seconds

# Not prax: the watchers would read its line and fire it back; they skip `.jsonl`.
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

    `completed` is False on any limit or size skip; `reason` is "" exactly when it is True.
    """

    errors: List[Dict[str, Any]]
    completed: bool
    reason: str


def _parse_log_line(log_line: str) -> Optional[Dict[str, str]]:
    """Parse a log line and extract fields if it's an ERROR.

    Positional, not content-matching: a message that mentions 'ERROR' is not an error line.
    """
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


def _extract_timestamp(timestamp_str: str) -> Optional[datetime]:
    """Parse timestamp string into datetime."""
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


def _registry_fingerprint(level: str, message: str, component: str) -> str:
    """The fingerprint the registry would store for this line, computed, not minted.

    Keep the level as logged ("ERROR"): lower-casing it computes a twin of an existing row.
    """
    try:
        from aipass.trigger.apps.handlers.error_registry import compute_fingerprint, normalize_message

        return compute_fingerprint(level, normalize_message(message), component)
    except Exception as exc:
        logger.warning(f"registry fingerprint failed: {exc}")
        return ""


def _registry_get_entry(fingerprint: str) -> Optional[Dict[str, Any]]:
    """The registry row for a fingerprint, or None. An unreadable registry is not fatal."""
    try:
        from aipass.trigger.apps.handlers.error_registry import get_entry

        return get_entry(fingerprint)
    except Exception as exc:
        logger.warning(f"registry get_entry failed: {exc}")
        return None


def _registry_report(**kwargs: Any) -> Dict[str, Any]:
    """Register an error the watcher never saw, so the dispatch has a row to close."""
    try:
        from aipass.trigger.apps.handlers.error_registry import report

        return report(**kwargs)
    except Exception as exc:
        logger.warning(f"registry report failed: {exc}")
        return {}


def _registry_identity(level: str, message: str, branch: str, log_path: str, line_iso: str) -> Optional[Dict[str, str]]:
    """{fingerprint, registry_id} for a scanned line, or None when it is a replay.

    Never report a known row (it would move last_seen to now); a line no newer than last_seen is a replay.
    """
    fingerprint = _registry_fingerprint(level, message, branch)
    known = _registry_get_entry(fingerprint) if fingerprint else None
    if known:
        last_seen = known.get("last_seen", "")
        if last_seen and line_iso <= last_seen:
            return None
        return {"fingerprint": fingerprint, "registry_id": known.get("id", "")}
    row = _registry_report(error_type=level, message=message, component=branch, log_path=log_path)
    return {"fingerprint": row.get("fingerprint", fingerprint), "registry_id": row.get("id", "")}


def _count_repeat(entry: Optional[Dict[str, Any]], line_iso: str) -> None:
    """Fold one more sighting into an entry already collected this scan; None (a past run's hash) stays dropped."""
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
    """Scan a single log file for ERROR entries; returns None when fully read, else the limit's reason."""
    # Function-local: medic imports this module, and log_watcher pulls watchdog and prax in at import.
    from aipass.trigger.apps.handlers.watchers.log_watcher import detect_branch_from_log, generate_error_hash

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
            # Timestamp-free on purpose: identical lines are one error counted N times (gate 3 needs count >= 2).
            error_hash = generate_error_hash(module, message)
            line_iso = line_ts.isoformat() if line_ts else datetime.now().isoformat()

            if error_hash in processed_hashes:
                _count_repeat(by_hash.get(error_hash), line_iso)
                continue

            branch = detect_branch_from_log(str(log_file))
            identity = _registry_identity(parsed["level"], message, branch, str(log_file), line_iso)
            if identity is None:
                # Not added to processed_hashes: a newer line of the same error must still fire.
                continue
            entry = {
                "branch": branch,
                "module": module,
                "message": message,
                # log_path, not log_file: it is the key handle_error_detected reads.
                "log_path": str(log_file),
                "error_hash": error_hash,
                "fingerprint": identity["fingerprint"],
                "registry_id": identity["registry_id"],
                "timestamp": line_iso,
                "level": parsed["level"].lower(),
                # No severity derived from these: catch-up leaves the registry default.
                "count": 1,
                "first_seen": line_iso,
                "last_seen": line_iso,
            }
            errors.append(entry)
            by_hash[error_hash] = entry
            processed_hashes.add(error_hash)

    return None


def _scan_system_logs_for_errors(since_timestamp: Optional[datetime], processed_hashes: Set[str]) -> ScanOutcome:
    """Scan system logs for ERROR entries since timestamp."""
    errors: List[Dict[str, Any]] = []
    by_hash: Dict[str, Dict[str, Any]] = {}
    scan_start = time.monotonic()

    if not SYSTEM_LOGS_DIR.exists():
        # No directory leaves no unread window, so the timestamp may advance.
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
        # A skipped file is a hole in the window, so it holds the timestamp too.
        abort_reason = abort_reason or skipped

    return ScanOutcome(errors, not abort_reason, abort_reason)


def _run_error_catchup(fire_event: Optional[Callable[..., object]] = None) -> None:
    """Catch-up on errors missed while Trigger wasn't running.

    Hashes persist on every run; they keep a re-covered window from re-dispatching.
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

    fire_event=None scans and records without dispatching.
    """
    _run_error_catchup(fire_event)


def handle_startup(**kwargs: Any) -> None:
    """Run startup checks - replaces Prax logger's hardcoded calls."""
    fire_event = kwargs.get("fire_event")
    _run_error_catchup(fire_event)
