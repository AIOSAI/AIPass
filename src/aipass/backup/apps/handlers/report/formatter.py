# =================== AIPass ====================
# Name: formatter.py
# Description: Format a BackupResult into a human-readable CLI string
# Version: 1.0.0
# Created: 2026-04-16
# Modified: 2026-04-23
# =============================================

"""Backup result formatter.

Turns a BackupResult into a summary suitable for terminal display.
"""

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


def format_result(result: BackupResult) -> str:
    """Format a backup run outcome for CLI display.

    Args:
        result: The backup run outcome to render.

    Returns:
        Multi-line string summarizing mode, counts, duration, and errors.
    """
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


# =============================================
