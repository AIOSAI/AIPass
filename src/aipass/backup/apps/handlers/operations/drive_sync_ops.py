# =================== AIPass ====================
# Name: drive_sync_ops.py
# Description: Google Drive Sync Business Operations Handler
# Version: 1.0.0
# Created: 2026-02-20
# Modified: 2026-03-09
# =============================================

"""
Google Drive Sync Business Operations Handler

Implements status, tracker management, and test operations for the
google_drive_sync module. Called by the module orchestrator.
"""

from pathlib import Path
from typing import Any, Dict

from aipass.prax import logger

from aipass.backup.apps.handlers.json.drive_sync_json import (
    load_data,
    save_data,
    log_operation,
)
from aipass.backup.apps.handlers.json import json_handler

# JSON file paths (resolved relative to backup root)
_BACKUP_ROOT = Path(__file__).resolve().parents[3]  # src/aipass/backup/
_JSON_DIR = _BACKUP_ROOT / "backup_json"
_MODULE_NAME = "google_drive_sync"
_DATA_FILE = _JSON_DIR / f"{_MODULE_NAME}_data.json"
_LOG_FILE = _JSON_DIR / f"{_MODULE_NAME}_log.json"


def clear_file_tracker() -> bool:
    """Clear the file tracker cache for a fresh sync.

    Returns:
        bool: True if cleared successfully, False on error
    """
    json_handler.log_operation("drive_sync_clear_tracker")
    try:
        data = load_data(_DATA_FILE)
        if "runtime_state" in data and "file_tracker" in data["runtime_state"]:
            data["runtime_state"]["file_tracker"] = {}
            save_data(_DATA_FILE, data)
        return True
    except Exception as e:
        logger.warning(f"[drive_sync_ops] Failed to clear file tracker: {e}")
        return False


def get_file_tracker_stats() -> Dict[str, Any]:
    """Get statistics about the file tracker.

    Returns:
        Dict with tracker count and sample entries
    """
    try:
        data = load_data(_DATA_FILE)
        tracker = data.get("runtime_state", {}).get("file_tracker", {})

        sample = []
        for i, (file_key, info) in enumerate(list(tracker.items())[:5]):
            last_sync = info.get("last_sync", "unknown")[:19] if info.get("last_sync") else "unknown"
            sample.append({"file": file_key, "last_sync": last_sync})

        return {
            "total": len(tracker),
            "sample": sample,
            "truncated": len(tracker) > 5
        }
    except Exception as e:
        logger.warning(f"[drive_sync_ops] Failed to get file tracker stats: {e}")
        return {"total": 0, "sample": [], "truncated": False}


def test_drive_connection(sync_instance: Any) -> bool:
    """Test Google Drive connectivity using an authenticated sync instance.

    Args:
        sync_instance: An authenticated GoogleDriveSync instance

    Returns:
        bool: True if connection test succeeded, False otherwise
    """
    try:
        folder_id = sync_instance.get_or_create_backup_folder()
        if folder_id:
            log_operation(
                _LOG_FILE,
                "test_sync",
                {"message": "Drive sync test successful", "folder_id": folder_id},
                success=True
            )
            return True
        else:
            log_operation(
                _LOG_FILE,
                "test_sync",
                {"message": "Failed to create backup folder"},
                success=False
            )
            return False
    except Exception as e:
        logger.warning(f"[drive_sync_ops] Drive connection test failed: {e}")
        log_operation(
            _LOG_FILE,
            "test_sync",
            {
                "message": f"Test failed: {e}",
                "error_details": {"exception_type": type(e).__name__, "stack_trace": str(e)}
            },
            success=False
        )
        return False
