# =================== AIPass ====================
# Name: metadata.py
# Description: Backup result to metadata payload builder
# Version: 1.0.0
# Created: 2026-04-16
# Modified: 2026-04-23
# =============================================

"""Metadata builder.

Converts a BackupResult into a metadata payload for changelog entries
and backup artifacts.
"""

import platform
from datetime import datetime, timezone

from ..audit import trail
from ..report.result import BackupResult


def build_metadata(result: BackupResult) -> dict:
    """Build a metadata payload from a backup result.

    Args:
        result: BackupResult instance from a completed backup run.

    Returns:
        Dict of metadata fields ready for JSON serialization.
    """
    meta = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": result.mode,
        "files_copied": result.files_copied,
        "bytes_copied": result.bytes_copied,
        "duration_seconds": result.duration_seconds,
        "errors": result.errors,
        "hostname": platform.node(),
        "platform": platform.system(),
    }
    trail.log_operation("build_metadata", {"mode": result.mode})
    return meta


# =============================================
