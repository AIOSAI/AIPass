# =================== AIPass ====================
# Name: backup_info_handler.py
# Description: Backup state and statistics
# Version: 1.0.0
# Created: 2025-11-16
# Modified: 2026-03-09
# =============================================

"""
Backup Info Handler

Manages backup state and statistics persistence.
Handles mode-specific formats (dynamic vs versioned).

Functions:
    load_backup_info: Load mode-specific backup state
    save_backup_info: Persist backup state to JSON
"""

# =============================================
# IMPORTS
# =============================================

import json
import os
import datetime
import tempfile
from pathlib import Path
from typing import Dict

from aipass.prax import logger


def _atomic_write(file_path: Path, data: dict) -> None:
    """Write JSON atomically via temp file + rename."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(suffix='.tmp', dir=str(file_path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, str(file_path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError as cleanup_err:
            logger.warning(f"[backup_info_handler] Failed to clean temp file: {cleanup_err}")
        raise


# =============================================
# BACKUP INFO OPERATIONS
# =============================================

def load_backup_info(backup_info_file: Path, mode_behavior: str) -> Dict:
    """Load backup information from JSON file.

    Args:
        backup_info_file: Path to backup_info JSON file
        mode_behavior: 'dynamic' or 'versioned'

    Returns:
        Dictionary with backup information (mode-specific format)
    """
    if backup_info_file.exists():
        try:
            with open(backup_info_file, 'r', encoding='utf-8', errors='replace') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"[backup_info_handler] Failed to load backup info from {backup_info_file}: {e}")

    # Return mode-specific default structure
    if mode_behavior == 'versioned':
        return {"backups": []}
    else:  # dynamic
        return {"last_backup": None, "file_timestamps": {}}


def save_backup_info(backup_info_file: Path, backup_info: Dict) -> bool:
    """Save backup information to JSON file.

    Args:
        backup_info_file: Path to backup_info JSON file
        backup_info: Dictionary containing backup information

    Returns:
        True if save succeeded, False otherwise
    """
    try:
        _atomic_write(backup_info_file, backup_info)
        return True
    except Exception as e:
        logger.warning(f"[backup_info_handler] Failed to save backup info to {backup_info_file}: {e}")
        return False


# =============================================
# MODULE INITIALIZATION
# =============================================

# No initialization needed - pure utility functions
