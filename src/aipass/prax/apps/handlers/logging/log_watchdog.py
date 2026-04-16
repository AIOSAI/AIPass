# =================== AIPass ====================
# Name: log_watchdog.py
# Description: System Log Size Watchdog
# Version: 0.1.0
# Created: 2026-02-26
# Modified: 2026-03-09
# =============================================

"""
System Log Size Watchdog

Scans the system_logs/ directory for oversized log files and enforces size limits.
Catches ALL log files regardless of how they were created — even those bypassing
PRAX's RotatingFileHandler (e.g., telegram bots using plain FileHandler).

This is the safety net: even if a branch misconfigures logging, the watchdog
prevents unbounded growth that caused the 2026-02-26 system crash (DPLAN-037).

Two modes:
  - audit: Report oversized files without changing anything
  - enforce: Truncate oversized files to keep last max_lines
"""

import logging

logger = logging.getLogger(__name__)
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

from aipass.prax.apps.handlers.json import json_handler


# =============================================================================
# CONSTANTS
# =============================================================================


def _find_repo_root() -> Path:
    """Walk up from this file to find the repo root (contains AIPASS_REGISTRY.json)."""
    current = Path(__file__).resolve().parent
    for parent in [current] + list(current.parents):
        if (parent / "AIPASS_REGISTRY.json").exists():
            return parent
    return Path.cwd()


_system_logs_dir_cache: Path | None = None


def _get_system_logs_dir() -> Path:
    """Lazily resolve system_logs directory (package-relative)."""
    global _system_logs_dir_cache
    if _system_logs_dir_cache is None:
        _system_logs_dir_cache = _find_repo_root() / "system_logs"
    return _system_logs_dir_cache


# Thresholds
WARN_THRESHOLD_LINES = 5000  # Fire warning at this line count
DEFAULT_MAX_LINES = 1000  # Truncate to this many lines (matches prax config)
CRITICAL_THRESHOLD_LINES = 10000  # Immediate action recommended


# =============================================================================
# SCANNING
# =============================================================================


def _count_lines(filepath: Path) -> int:
    """
    Count lines in a file efficiently.

    Args:
        filepath: Path to the file

    Returns:
        Line count, or 0 on error
    """
    try:
        with open(filepath, "rb") as f:
            return sum(1 for _ in f)
    except OSError as e:
        logger.info("Failed to count lines in %s: %s", filepath, e)
        return 0


def _get_file_size_kb(filepath: Path) -> float:
    """
    Get file size in kilobytes.

    Args:
        filepath: Path to the file

    Returns:
        Size in KB, or 0.0 on error
    """
    try:
        return filepath.stat().st_size / 1024.0
    except OSError as e:
        logger.info("Failed to stat file %s: %s", filepath, e)
        return 0.0


def scan_log_files() -> List[Dict[str, Any]]:
    """
    Scan all .log files in system_logs/ and report their sizes.

    Returns:
        List of dicts with path, name, lines, size_kb, status
        Status: 'ok', 'warning', 'critical'
    """
    results: List[Dict[str, Any]] = []

    if not _get_system_logs_dir().exists():
        return results

    for log_file in sorted(_get_system_logs_dir().glob("*.log")):
        lines = _count_lines(log_file)
        size_kb = _get_file_size_kb(log_file)

        if lines >= CRITICAL_THRESHOLD_LINES:
            status = "critical"
        elif lines >= WARN_THRESHOLD_LINES:
            status = "warning"
        else:
            status = "ok"

        results.append(
            {
                "path": str(log_file),
                "name": log_file.name,
                "lines": lines,
                "size_kb": round(size_kb, 1),
                "status": status,
            }
        )

    # Sort by line count descending (biggest problems first)
    results.sort(key=lambda x: x["lines"], reverse=True)
    json_handler.log_operation("log_watchdog_check", {"files_scanned": len(results)})
    return results


def get_oversized_files(threshold: int = WARN_THRESHOLD_LINES) -> List[Dict[str, Any]]:
    """
    Get only files exceeding the threshold.

    Args:
        threshold: Line count threshold

    Returns:
        List of file info dicts for files exceeding threshold
    """
    return [f for f in scan_log_files() if f["lines"] >= threshold]


# =============================================================================
# ENFORCEMENT
# =============================================================================


def truncate_log_file(filepath: Path, keep_lines: int = DEFAULT_MAX_LINES) -> Tuple[int, int]:
    """
    Truncate a log file to keep only the last N lines.

    Reads the file, keeps the tail, writes it back. This is the nuclear option
    for files that grew unbounded because they bypassed RotatingFileHandler.

    Args:
        filepath: Path to the log file
        keep_lines: Number of lines to keep from the end

    Returns:
        Tuple of (original_lines, new_lines)
    """
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()

        original_count = len(all_lines)

        if original_count <= keep_lines:
            return original_count, original_count

        # Keep only the last keep_lines
        kept_lines = all_lines[-keep_lines:]

        # Prepend a truncation marker
        marker = (
            f"--- LOG TRUNCATED by PRAX watchdog at {datetime.now().isoformat()} "
            f"| was {original_count} lines, kept last {keep_lines} ---\n"
        )

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(marker)
            f.writelines(kept_lines)

        return original_count, keep_lines + 1  # +1 for marker line

    except OSError as e:
        logger.warning("Failed to truncate log file %s: %s", filepath, e)
        return 0, 0


def enforce_log_limits(
    max_lines: int = DEFAULT_MAX_LINES, threshold: int = WARN_THRESHOLD_LINES
) -> List[Dict[str, Any]]:
    """
    Scan and truncate all oversized log files.

    Only truncates files exceeding the threshold. Files within limits are
    left untouched.

    Args:
        max_lines: Truncate to this many lines
        threshold: Only truncate files exceeding this many lines

    Returns:
        List of dicts describing what was truncated
    """
    actions: List[Dict[str, Any]] = []

    oversized = get_oversized_files(threshold)

    for file_info in oversized:
        filepath = Path(file_info["path"])
        original, new = truncate_log_file(filepath, max_lines)

        actions.append(
            {"name": file_info["name"], "original_lines": original, "new_lines": new, "truncated": original != new}
        )

    return actions


# =============================================================================
# HEALTH CHECK (for monitoring integration)
# =============================================================================


def log_health_summary() -> Dict[str, Any]:
    """
    Generate a health summary of system logs.

    Returns:
        Dict with total_files, total_lines, oversized_count,
        critical_count, largest_file, healthy
    """
    files = scan_log_files()

    if not files:
        return {
            "total_files": 0,
            "total_lines": 0,
            "oversized_count": 0,
            "critical_count": 0,
            "largest_file": None,
            "largest_lines": 0,
            "healthy": True,
        }

    total_lines = sum(f["lines"] for f in files)
    oversized = [f for f in files if f["status"] in ("warning", "critical")]
    critical = [f for f in files if f["status"] == "critical"]
    largest = files[0] if files else None  # Already sorted by lines desc

    return {
        "total_files": len(files),
        "total_lines": total_lines,
        "oversized_count": len(oversized),
        "critical_count": len(critical),
        "largest_file": largest["name"] if largest else None,
        "largest_lines": largest["lines"] if largest else 0,
        "healthy": len(oversized) == 0,
    }


# =============================================================================
# CLI ENTRY POINT (for testing)
# =============================================================================

if __name__ == "__main__":
    import json

    if len(sys.argv) > 1 and sys.argv[1] == "enforce":
        print("Enforcing log limits...")
        actions = enforce_log_limits()
        print(json.dumps(actions, indent=2))
    else:
        print("Log health summary:")
        summary = log_health_summary()
        print(json.dumps(summary, indent=2))
        print()
        print("Oversized files:")
        oversized = get_oversized_files()
        print(json.dumps(oversized, indent=2))
