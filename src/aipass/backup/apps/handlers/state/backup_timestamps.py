# =================== AIPass ====================
# Name: backup_timestamps.py
# Description: Tracks last-run timestamps for all backup modes
# Version: 1.0.0
# Created: 2026-06-12
# Modified: 2026-06-12
# =============================================

"""Backup timestamps — tracks when each backup mode was last run."""

import json
import os
import tempfile
from datetime import datetime

from aipass.prax import logger

from ..path.module_paths import branch_root
from ..audit import trail

_BACKUP_ROOT = branch_root(__file__, 3)
TIMESTAMPS_FILE = _BACKUP_ROOT / "backup_json" / "backup_timestamps.json"

MODES = ["snapshot", "versioned", "drive_sync"]


def get_timestamps() -> dict:
    """Read all backup timestamps from disk."""
    data = {}
    if TIMESTAMPS_FILE.exists():
        try:
            data = json.loads(TIMESTAMPS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"[backup_timestamps] Failed to read timestamps file: {e}")
            data = {}
    return {mode: data.get(mode) for mode in MODES}


def update_timestamp(mode: str) -> None:
    """Update the timestamp for a backup mode to now."""
    trail.log_operation("timestamp_updated", {"mode": mode})

    data = {}
    if TIMESTAMPS_FILE.exists():
        try:
            data = json.loads(TIMESTAMPS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"[backup_timestamps] Failed to read timestamps for update: {e}")
            data = {}

    data[mode] = datetime.now().isoformat()

    TIMESTAMPS_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(suffix=".tmp", dir=str(TIMESTAMPS_FILE.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, str(TIMESTAMPS_FILE))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError as cleanup_err:
            logger.warning(f"[backup_timestamps] Failed to clean temp file: {cleanup_err}")
        raise


def format_age(iso_str: str | None) -> str:
    """Format an ISO timestamp as a human-readable age string."""
    if not iso_str:
        return "never"

    try:
        then = datetime.fromisoformat(iso_str)
    except (ValueError, TypeError) as e:
        logger.info(f"[backup_timestamps] Could not parse timestamp '{iso_str}': {e}")
        return "unknown"

    delta = datetime.now() - then
    seconds = int(delta.total_seconds())

    if seconds < 60:
        return "just now"
    if seconds < 3600:
        mins = seconds // 60
        return f"{mins} min{'s' if mins != 1 else ''} ago"
    if seconds < 86400:
        hours = seconds // 3600
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = seconds // 86400
    return f"{days} day{'s' if days != 1 else ''} ago"


# =============================================
