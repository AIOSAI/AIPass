# =================== AIPass ====================
# Name: log_watchdog.py
# Description: System Log Size Watchdog
# Version: 0.1.0
# Created: 2026-02-26
# Modified: 2026-03-09
# =============================================

"""
System Log Size Watchdog

Scans system_logs/ and all branch logs/ directories for oversized files and
enforces size limits. Catches ALL log files regardless of how they were created
— even those bypassing PRAX's RotatingFileHandler (e.g., raw open("a") appenders
writing .jsonl files, telegram bots using plain FileHandler).

This is the safety net: even if a branch misconfigures logging, the watchdog
prevents unbounded growth that caused the 2026-02-26 system crash (DPLAN-037).

Two scopes:
  - system_logs/ (central) — scanned by scan_log_files()
  - src/aipass/*/logs/ (branch-local) — scanned by scan_branch_log_files()

Two modes:
  - audit: Report oversized files without changing anything
  - enforce: Truncate oversized files to keep last max_lines
"""

import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

from aipass.prax.apps.handlers.json import json_handler
from aipass.prax.apps.handlers.repo_root import find_repo_root

logger = logging.getLogger(__name__)


# =============================================================================
# CONSTANTS
# =============================================================================


def _find_repo_root() -> Path:
    """Walk up from this file to find the repo root, never reading the cwd.

    Delegates to ``handlers/repo_root.py``. Prax carried eight private copies of
    this walk, every one ending ``return Path.cwd()`` — @memory reported the
    consequence with a traceback on 2026-08-31: the walk runs at IMPORT time in
    most of the fleet, so a deleted working directory crashed the import, and a
    registry-less checkout (every clean CI clone) resolved against wherever the
    shell stood.
    """
    return find_repo_root(Path(__file__))


_system_logs_dir_cache: Path | None = None


def _get_system_logs_dir() -> Path:
    """Lazily resolve system_logs directory (package-relative)."""
    global _system_logs_dir_cache
    if _system_logs_dir_cache is None:
        _system_logs_dir_cache = _find_repo_root() / "system_logs"
    return _system_logs_dir_cache


# Thresholds — system_logs (line-based)
WARN_THRESHOLD_LINES = 5000  # Fire warning at this line count
DEFAULT_MAX_LINES = 1000  # Truncate to this many lines (matches prax config)
CRITICAL_THRESHOLD_LINES = 10000  # Immediate action recommended

# Thresholds — branch logs (size-based, catches .jsonl and unrotated .log)
BRANCH_WARN_SIZE_MB = 1.0
BRANCH_CRITICAL_SIZE_MB = 10.0
BRANCH_DEFAULT_MAX_LINES = 5000

# Sweep — stale log cleanup
SWEEP_MAX_AGE_DAYS = 30


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
# BRANCH LOG SCANNING — covers .log and .jsonl in src/aipass/*/logs/
# =============================================================================


def _get_ecosystem_root() -> Path:
    """Find src/aipass/ directory."""
    return _find_repo_root() / "src" / "aipass"


def _has_rotation_sibling(filepath: Path) -> bool:
    """Check if a file has a .1 rotation sibling."""
    return (filepath.parent / f"{filepath.name}.1").exists()


def _classify_branch_log(log_file: Path, branch_name: str) -> Dict[str, Any]:
    """Build an audit record for a single branch log file."""
    size_kb = _get_file_size_kb(log_file)
    size_mb = size_kb / 1024.0
    lines = _count_lines(log_file)
    has_rotation = _has_rotation_sibling(log_file)

    if size_mb >= BRANCH_CRITICAL_SIZE_MB:
        status = "critical"
    elif size_mb >= BRANCH_WARN_SIZE_MB and not has_rotation:
        status = "warning"
    else:
        status = "ok"

    return {
        "path": str(log_file),
        "name": log_file.name,
        "branch": branch_name,
        "lines": lines,
        "size_kb": round(size_kb, 1),
        "size_mb": round(size_mb, 1),
        "has_rotation": has_rotation,
        "status": status,
    }


def scan_branch_log_files() -> List[Dict[str, Any]]:
    """
    Scan all branch logs/ directories for files with unbounded growth.

    Checks .log and .jsonl files. Flags unrotated files exceeding size
    thresholds — the safety net for writers that bypass RotatingFileHandler.
    """
    results: List[Dict[str, Any]] = []
    eco_root = _get_ecosystem_root()

    if not eco_root.exists():
        return results

    for branch_dir in sorted(eco_root.iterdir()):
        logs_dir = branch_dir / "logs"
        if not branch_dir.is_dir() or not logs_dir.is_dir():
            continue
        for log_file in sorted(logs_dir.glob("*.log")) + sorted(logs_dir.glob("*.jsonl")):
            results.append(_classify_branch_log(log_file, branch_dir.name))

    results.sort(key=lambda x: x["size_kb"], reverse=True)
    json_handler.log_operation("branch_log_watchdog_check", {"files_scanned": len(results)})
    return results


def get_oversized_branch_files() -> List[Dict[str, Any]]:
    """Get branch log files exceeding size thresholds."""
    return [f for f in scan_branch_log_files() if f["status"] != "ok"]


def enforce_branch_log_limits(
    max_lines: int = BRANCH_DEFAULT_MAX_LINES,
) -> List[Dict[str, Any]]:
    """
    Truncate oversized branch log files (including .jsonl).

    Only truncates files flagged as warning or critical by scan_branch_log_files().
    """
    actions: List[Dict[str, Any]] = []

    for file_info in get_oversized_branch_files():
        filepath = Path(file_info["path"])
        original, new = truncate_log_file(filepath, max_lines)

        actions.append(
            {
                "name": file_info["name"],
                "branch": file_info["branch"],
                "original_lines": original,
                "new_lines": new,
                "size_mb": file_info["size_mb"],
                "truncated": original != new,
            }
        )

    return actions


def branch_log_health_summary() -> Dict[str, Any]:
    """Generate a health summary of branch logs."""
    files = scan_branch_log_files()

    if not files:
        return {
            "total_files": 0,
            "oversized_count": 0,
            "critical_count": 0,
            "total_size_mb": 0.0,
            "largest_file": None,
            "healthy": True,
        }

    oversized = [f for f in files if f["status"] in ("warning", "critical")]
    critical = [f for f in files if f["status"] == "critical"]
    largest = files[0] if files else None
    total_size = sum(f["size_mb"] for f in files)

    return {
        "total_files": len(files),
        "oversized_count": len(oversized),
        "critical_count": len(critical),
        "total_size_mb": round(total_size, 1),
        "largest_file": f"{largest['branch']}/{largest['name']}" if largest else None,
        "largest_size_mb": largest["size_mb"] if largest else 0.0,
        "healthy": len(oversized) == 0,
    }


# =============================================================================
# SWEEP — stale log cleanup (30-day policy)
# =============================================================================


def _file_age_days(filepath: Path) -> float:
    """Return file age in days based on mtime."""
    try:
        mtime = filepath.stat().st_mtime
    except OSError as exc:
        logger.warning("Cannot stat %s for age check: %s", filepath, exc)
        return 0.0
    return (time.time() - mtime) / 86400.0


def _sweep_directory(directory: Path, patterns: List[str], max_age_days: int) -> List[Dict[str, Any]]:
    """Delete files matching patterns that are older than max_age_days."""
    removed: List[Dict[str, Any]] = []
    if not directory.exists():
        return removed

    for pattern in patterns:
        for filepath in sorted(directory.glob(pattern)):
            age = _file_age_days(filepath)
            if age < max_age_days:
                continue
            size_kb = _get_file_size_kb(filepath)
            try:
                filepath.unlink()
                removed.append(
                    {
                        "path": str(filepath),
                        "name": filepath.name,
                        "age_days": round(age, 1),
                        "size_kb": round(size_kb, 1),
                    }
                )
            except OSError as exc:
                logger.warning("Sweep failed to delete %s: %s", filepath, exc)

    return removed


def sweep_stale_logs(max_age_days: int = SWEEP_MAX_AGE_DAYS) -> Dict[str, Any]:
    """Delete log files older than max_age_days across system_logs/ and branch logs/.

    Scans system_logs/ for *.log and *.log.1, and all branch logs/ directories
    for *.log, *.log.1, *.jsonl, and *.jsonl.1.

    Returns a summary with counts and the list of removed files.
    """
    all_removed: List[Dict[str, Any]] = []

    system_patterns = ["*.log", "*.log.1"]
    all_removed.extend(_sweep_directory(_get_system_logs_dir(), system_patterns, max_age_days))

    branch_patterns = ["*.log", "*.log.1", "*.jsonl", "*.jsonl.1"]
    eco_root = _get_ecosystem_root()
    if eco_root.exists():
        for branch_dir in sorted(eco_root.iterdir()):
            logs_dir = branch_dir / "logs"
            if branch_dir.is_dir() and logs_dir.is_dir():
                all_removed.extend(_sweep_directory(logs_dir, branch_patterns, max_age_days))

    json_handler.log_operation("log_sweep", {"max_age_days": max_age_days, "files_removed": len(all_removed)})

    return {
        "max_age_days": max_age_days,
        "files_removed": len(all_removed),
        "total_reclaimed_kb": round(sum(f["size_kb"] for f in all_removed), 1),
        "removed": all_removed,
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
