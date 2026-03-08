
# ===================AIPASS====================
# META DATA HEADER
# Name: backup_timestamps.py - Tracks last-run timestamps for all backup modes
# Date: 2026-02-22
# Version: 1.0.0
# Category: handlers/utils
#
# CHANGELOG (Max 5 entries):
#   - v1.0.0 (2026-02-22): Initial version - show/update backup timestamps
#
# CODE STANDARDS:
#   - Handler utility: no console output, returns data for module layer
#   - JSON file at backups/backup_timestamps.json
# =============================================

"""
Backup Timestamps - Tracks when each backup mode was last run.

Provides get/update functions for a shared timestamps file so any
backup command can display how fresh each backup type is.
"""

import json
from pathlib import Path
from datetime import datetime

_BACKUP_ROOT = Path(__file__).resolve().parents[3]  # src/aipass/backup/
TIMESTAMPS_FILE = _BACKUP_ROOT / "backup_data" / "backup_timestamps.json"

MODES = ["snapshot", "versioned", "drive_sync"]


def get_timestamps() -> dict:
    """Read all backup timestamps from disk.

    Returns:
        dict with mode keys and ISO datetime string values (or None if never run)
    """
    data = {}
    if TIMESTAMPS_FILE.exists():
        try:
            data = json.loads(TIMESTAMPS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
    return {mode: data.get(mode) for mode in MODES}


def update_timestamp(mode: str) -> None:
    """Update the timestamp for a backup mode to now.

    Args:
        mode: One of 'snapshot', 'versioned', 'drive_sync'
    """
    data = {}
    if TIMESTAMPS_FILE.exists():
        try:
            data = json.loads(TIMESTAMPS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}

    data[mode] = datetime.now().isoformat()

    TIMESTAMPS_FILE.parent.mkdir(parents=True, exist_ok=True)
    TIMESTAMPS_FILE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def format_age(iso_str: str | None) -> str:
    """Format an ISO timestamp as a human-readable age string.

    Args:
        iso_str: ISO datetime string, or None if never run

    Returns:
        String like '2 days ago', '3 hours ago', 'just now', or 'never'
    """
    if not iso_str:
        return "never"

    try:
        then = datetime.fromisoformat(iso_str)
    except (ValueError, TypeError):
        return "unknown"

    delta = datetime.now() - then
    seconds = int(delta.total_seconds())

    if seconds < 60:
        return "just now"
    elif seconds < 3600:
        mins = seconds // 60
        return f"{mins} min{'s' if mins != 1 else ''} ago"
    elif seconds < 86400:
        hours = seconds // 3600
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    else:
        days = seconds // 86400
        return f"{days} day{'s' if days != 1 else ''} ago"
