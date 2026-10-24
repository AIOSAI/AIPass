# =================== AIPass ====================
# Name: formatter.py
# Description: Format a BackupResult into a human-readable CLI string
# Version: 1.0.1
# Created: 2026-04-16
# Modified: 2026-10-23
# =============================================

"""Backup result formatter."""

from datetime import datetime

from aipass.prax import logger

from ..audit import trail
from .result import BackupResult


def _human_bytes(byte_count: int) -> str:
    """Format byte count as human-readable string."""
    n = float(byte_count)
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def format_age(iso_str: str | None) -> str:
    """Format an ISO timestamp as a human-readable age string."""
    if not iso_str:
        return "never"

    try:
        then = datetime.fromisoformat(iso_str)
    except (ValueError, TypeError) as e:
        logger.info(f"[backup] Could not parse timestamp '{iso_str}': {e}")
        return "unknown"

    # Changelog stamps are UTC-aware; now() takes their zone so the subtraction is legal.
    delta = datetime.now(then.tzinfo) - then
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


def format_result(result: BackupResult) -> str:
    """Format a backup run outcome for CLI display."""
    lines = [
        f"Backup complete ({result.mode})",
        f"  Project:  {result.project_root}",
        f"  Files:    {result.files_copied}",
        f"  Size:     {_human_bytes(result.bytes_copied)}",
        f"  Duration: {result.duration_seconds:.1f}s",
    ]

    if result.errors:
        lines.append(f"  Errors:   {len(result.errors)}")
        for err in result.errors[:5]:
            lines.append(f"    - {err}")
        if len(result.errors) > 5:
            lines.append(f"    ... and {len(result.errors) - 5} more")

    trail.log_operation("format_result", {"mode": result.mode})
    return "\n".join(lines)
