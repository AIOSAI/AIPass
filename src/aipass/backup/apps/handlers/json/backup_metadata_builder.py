
# ===================AIPASS====================
# META DATA HEADER
# Name: backup_metadata_builder.py - Backup metadata construction
# Date: 2025-11-18
# Version: 1.0.0
# Category: handlers
#
# CHANGELOG (Max 5 entries):
#   - v1.0.0 (2025-11-18): Extracted from backup_core.py
#     * Extracted backup_info creation logic
#     * Handles mode-specific metadata formatting
#
# CODE STANDARDS:
#   - Follow seed 3-layer architecture
#   - Handlers must be independent and transportable
#   - No cross-handler imports except within same domain
# =============================================

"""
Backup Metadata Builder - Constructs backup metadata structures

Creates mode-specific backup information structures.
"""

# =============================================
# IMPORTS
# =============================================

import datetime
from pathlib import Path

from aipass.backup.apps.handlers.models.backup_models import BackupResult

# =============================================
# METADATA CONSTRUCTION OPERATIONS
# =============================================

def create_backup_metadata(mode: str, behavior: str, backup_note: str, backup_folder_name: str,
                           backup_path: Path, source_dir: Path, result: BackupResult,
                           current_timestamps: dict, existing_backup_info: dict) -> dict:
    """Create backup metadata structure based on mode.

    Args:
        mode: Backup mode ('snapshot' or 'versioned')
        behavior: Mode behavior ('dynamic' or 'versioned')
        backup_note: User note for this backup
        backup_folder_name: Backup folder name
        backup_path: Backup destination path
        source_dir: Source directory root
        result: BackupResult with operation statistics
        current_timestamps: Dict of current file timestamps
        existing_backup_info: Existing backup info to append to

    Returns:
        Complete backup info dict ready to save
    """
    if behavior == 'versioned':
        # Versioned: add to backup list
        current_backup = {
            "backup_note": backup_note,
            "backup_name": backup_folder_name,
            "timestamp": datetime.datetime.now().isoformat(),
            "backup_path": str(backup_path),
            "source_path": str(source_dir),
            "mode": mode,
            "stats": {
                "files_checked": result.files_checked,
                "files_copied": result.files_copied,
                "files_added": result.files_added,
                "files_skipped": result.files_skipped,
                "errors": result.errors
            }
        }
        existing_backup_info["backups"].insert(0, current_backup)
        return existing_backup_info
    else:
        # Dynamic: update current state
        return {
            "backup_note": backup_note,
            "last_backup": datetime.datetime.now().isoformat(),
            "file_timestamps": current_timestamps,
            "mode": mode,
            "backup_path": str(backup_path),
            "stats": {
                "files_checked": result.files_checked,
                "files_copied": result.files_copied,
                "files_added": result.files_added,
                "files_skipped": result.files_skipped,
                "files_deleted": result.files_deleted,
                "errors": result.errors
            }
        }


# =============================================
# MODULE INITIALIZATION
# =============================================

# Pure handler - no initialization needed
