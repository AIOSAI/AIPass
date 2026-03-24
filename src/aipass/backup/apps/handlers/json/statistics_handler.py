# =================== AIPass ====================
# Name: statistics_handler.py
# Description: Backup statistics tracking
# Version: 1.0.0
# Created: 2025-11-18
# Modified: 2026-03-09
# =============================================

"""
Statistics Handler - Backup statistics and runtime state tracking

Manages backup operation statistics and runtime state persistence.
"""

# =============================================
# IMPORTS
# =============================================

import datetime
from pathlib import Path

from aipass.prax import logger
from aipass.backup.apps.handlers.json.json_handler import load_json, save_json
from aipass.backup.apps.handlers.models.backup_models import BackupResult
from aipass.backup.apps.handlers.utils.system_utils import safe_print

# =============================================
# STATISTICS OPERATIONS
# =============================================

def update_data_file(backup_result: BackupResult):
    """Update data file with backup statistics.

    Args:
        backup_result: BackupResult instance with operation statistics
    """
    try:
        # Load current data
        data = load_json("backup_core", "data")
        if not data:
            data = {
                "last_updated": datetime.datetime.now().isoformat(),
                "runtime_state": {},
                "statistics": {},
                "recent_backups": []
            }

        # Update runtime state
        data["last_updated"] = datetime.datetime.now().isoformat()
        if "runtime_state" not in data:
            data["runtime_state"] = {}
        data["runtime_state"]["current_status"] = "completed" if backup_result.success else "failed"
        data["runtime_state"]["last_backup"] = datetime.datetime.now().isoformat()
        data["runtime_state"]["active_mode"] = backup_result.mode
        data["runtime_state"]["total_files_backed_up"] = backup_result.files_copied
        data["runtime_state"]["backup_in_progress"] = False

        # Update statistics
        if "statistics" not in data:
            data["statistics"] = {
                "total_backups": 0,
                "successful_backups": 0,
                "failed_backups": 0,
                "snapshot_backups": 0,
                "versioned_backups": 0,
                "total_files_processed": 0
            }

        data["statistics"]["total_backups"] += 1
        if backup_result.success:
            data["statistics"]["successful_backups"] += 1
        else:
            data["statistics"]["failed_backups"] += 1

        # Mode-specific counters
        if backup_result.mode == "snapshot":
            data["statistics"]["snapshot_backups"] += 1
        elif backup_result.mode == "versioned":
            data["statistics"]["versioned_backups"] += 1

        data["statistics"]["total_files_processed"] += backup_result.files_checked

        # Add to recent backups (keep last 10)
        if "recent_backups" not in data:
            data["recent_backups"] = []
        data["recent_backups"].append({
            "timestamp": datetime.datetime.now().isoformat(),
            "mode": backup_result.mode,
            "success": backup_result.success,
            "files_copied": backup_result.files_copied,
            "errors": backup_result.errors
        })
        data["recent_backups"] = data["recent_backups"][-10:]  # Keep last 10

        save_json("backup_core", "data", data)
    except Exception as e:
        safe_print(f"Failed to update data file: {e}")
        logger.error(f"[statistics_handler] Failed to update data file: {e}")


# =============================================
# MODULE INITIALIZATION
# =============================================

# No module-level initialization needed
