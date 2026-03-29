# =================== AIPass ====================
# Name: drive_sync_json.py
# Description: Google Drive Sync JSON Operations Handler
# Version: 1.0.0
# Created: 2026-02-20
# Modified: 2026-03-09
# =============================================

"""
Google Drive Sync JSON Operations Handler

Handles all JSON file read/write operations for the google_drive_sync module.
Provides load/save functions for config, data, and log files.
"""

import copy
import fcntl
import json
import os
import tempfile
import time
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from aipass.prax import logger

# Module JSON file paths (resolved by caller)
_log_lock = threading.Lock()


def atomic_json_write(file_path: Path, data: Any) -> None:
    """Write JSON atomically via temp file + rename to prevent corruption.

    Args:
        file_path: Target JSON file path
        data: Data to serialize as JSON

    Raises:
        Exception: If write fails after cleanup attempt
    """
    fd, tmp_path = tempfile.mkstemp(suffix='.tmp', dir=str(file_path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, str(file_path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError as e:
            logger.warning(f"[drive_sync_json] Failed to clean up temp file: {e}")
        raise


def load_config(config_file: Path) -> Dict[str, Any]:
    """Load module configuration from JSON file.

    Args:
        config_file: Path to the config JSON file

    Returns:
        Dict with config data, or empty dict on error
    """
    try:
        if config_file.exists():
            with open(config_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}
    except Exception as e:
        logger.warning(f"[drive_sync_json] Failed to load config from {config_file}: {e}")
        return {}


def save_config(config_file: Path, config: Dict[str, Any]) -> None:
    """Save module configuration to JSON file.

    Args:
        config_file: Path to the config JSON file
        config: Config data to save

    Raises:
        Exception: If save fails
    """
    config_file.parent.mkdir(parents=True, exist_ok=True)
    atomic_json_write(config_file, config)


def load_data(data_file: Path) -> Dict[str, Any]:
    """Load runtime data from JSON file.

    Args:
        data_file: Path to the data JSON file

    Returns:
        Dict with runtime data, or empty dict on error
    """
    try:
        if data_file.exists():
            with open(data_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}
    except Exception as e:
        logger.warning(f"[drive_sync_json] Failed to load data from {data_file}: {e}")
        return {}


def save_data(data_file: Path, data: Dict[str, Any]) -> None:
    """Save runtime data to JSON file with deepcopy protection.

    Args:
        data_file: Path to the data JSON file
        data: Runtime data to save

    Raises:
        RuntimeError: If deepcopy fails after 3 retries
    """
    data_file.parent.mkdir(parents=True, exist_ok=True)
    snapshot: Dict[str, Any] = {}
    for attempt in range(3):
        try:
            snapshot = copy.deepcopy(data)
            break
        except RuntimeError as e:
            if attempt < 2:
                logger.info(f"[drive_sync_json] Deepcopy retry {attempt + 1}/3: {e}")
                time.sleep(0.05 * (attempt + 1))
            else:
                raise
    snapshot["last_updated"] = datetime.now().isoformat()
    atomic_json_write(data_file, snapshot)


def _read_json_locked(file_path: Path) -> Any:
    """Read and parse JSON from a file with shared lock."""
    with open(file_path, 'r', encoding='utf-8') as f:
        fcntl.flock(f, fcntl.LOCK_SH)
        try:
            return json.load(f)
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def load_log(log_file: Path, max_retries: int = 3) -> Dict[str, Any]:
    """Load operation log from JSON file with cross-process locking and retry.

    Args:
        log_file: Path to the log JSON file
        max_retries: Number of retry attempts on decode error

    Returns:
        Dict with log data and summary
    """
    default_log: Dict[str, Any] = {
        "entries": [],
        "summary": {"total_entries": 0, "last_entry": None, "next_id": 1}
    }
    for attempt in range(max_retries):
        try:
            if log_file.exists() and log_file.stat().st_size > 0:
                raw = _read_json_locked(log_file)
                # Validate structure — legacy files may be a bare list
                if isinstance(raw, dict) and "entries" in raw and "summary" in raw:
                    return raw
                # Migrate legacy list format to new structure
                if isinstance(raw, list):
                    logger.info(f"[drive_sync_json] Migrating legacy log format for {log_file}")
                    migrated = dict(default_log)
                    migrated["entries"] = raw[:100]
                    migrated["summary"]["total_entries"] = len(raw)
                    migrated["summary"]["next_id"] = len(raw) + 1
                    save_log(log_file, migrated)
                    return migrated
                # Unknown structure — reset
                logger.warning(f"[drive_sync_json] Unexpected log structure in {log_file}, resetting")
                save_log(log_file, default_log)
                return default_log
            else:
                save_log(log_file, default_log)
                return default_log
        except json.JSONDecodeError as e:
            if attempt < max_retries - 1:
                time.sleep(0.1 * (attempt + 1))
            else:
                logger.warning(f"[drive_sync_json] JSON decode failed after {max_retries} retries for {log_file}: {e}")
                return default_log
        except Exception as e:
            logger.warning(f"[drive_sync_json] Failed to load log from {log_file}: {e}")
            return default_log
    return default_log


def save_log(log_file: Path, log: Dict[str, Any]) -> None:
    """Save operation log to JSON file with cross-process locking.

    Args:
        log_file: Path to the log JSON file
        log: Log data to save

    Raises:
        Exception: If save fails
    """
    log_file.parent.mkdir(parents=True, exist_ok=True)
    lock_path = log_file.with_suffix('.lock')
    with open(lock_path, 'w', encoding='utf-8') as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            atomic_json_write(log_file, log)
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)


def log_operation(
    log_file: Path,
    operation: str,
    details: Dict[str, Any],
    success: bool = True,
    correlation_id: Optional[str] = None
) -> None:
    """Log a business operation to the module's JSON log file.

    Args:
        log_file: Path to the log JSON file
        operation: Operation name/identifier
        details: Dict with 'message', optional 'execution_time_ms', 'error_details'
        success: True if operation succeeded
        correlation_id: Optional correlation ID for tracing
    """
    with _log_lock:
        log = load_log(log_file)

        log_entry = {
            "id": log["summary"].get("next_id", 1),
            "timestamp": datetime.now().isoformat(),
            "level": "INFO" if success else "ERROR",
            "operation": operation,
            "message": details.get("message", ""),
            "success": success,
            "execution_time_ms": details.get("execution_time_ms", 0),
            "correlation_id": correlation_id
        }

        if not success:
            log_entry["error_details"] = details.get("error_details", {})

        log["entries"].insert(0, log_entry)
        log["entries"] = log["entries"][:100]

        log["summary"]["total_entries"] += 1
        log["summary"]["last_entry"] = log_entry["timestamp"]
        log["summary"]["next_id"] = log_entry["id"] + 1

        save_log(log_file, log)
