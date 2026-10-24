# =================== AIPass ====================
# Name: log_watchdog.py
# Description: System Log Size Watchdog
# Version: 0.2.0
# Created: 2026-02-26
# Modified: 2026-10-23
# =============================================

"""System Log Size Watchdog

Scans system_logs/ (scan_log_files) and src/aipass/*/logs/ (scan_branch_log_files);
audit reports oversized files, enforce truncates them to the last max_lines. The safety
net for writers that bypass PRAX's RotatingFileHandler (raw open("a") .jsonl appenders,
plain FileHandler bots), whose unbounded growth can take the system down.
"""

import logging
import os
import sys
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from aipass.prax.apps.handlers.config.load import get_system_logs_dir
from aipass.prax.apps.handlers.json import json_handler
from aipass.prax.apps.handlers.repo_root import find_repo_root

logger = logging.getLogger(__name__)


def _find_repo_root() -> Path:
    """Walk up from this file to find the repo root, never reading the cwd.

    The walk runs at import time across the fleet: a cwd fallback crashes the import in a
    deleted working directory and resolves a clean CI clone against wherever the shell stood.
    """
    return find_repo_root(Path(__file__))


def _get_system_logs_dir() -> Path:
    """The system_logs directory, the same home the loggers write to."""
    return get_system_logs_dir()


WARN_THRESHOLD_LINES = 5000  # Fire warning at this line count
DEFAULT_MAX_LINES = 1000  # Truncate to this many lines (matches prax config)
CRITICAL_THRESHOLD_LINES = 10000  # Immediate action recommended

# Branch logs are size-based: that catches .jsonl and unrotated .log files.
BRANCH_WARN_SIZE_MB = 1.0
BRANCH_CRITICAL_SIZE_MB = 10.0
BRANCH_DEFAULT_MAX_LINES = 5000

SWEEP_MAX_AGE_DAYS = 30


def _count_lines(filepath: Path) -> int:
    """Count lines in a file efficiently."""
    try:
        with open(filepath, "rb") as f:
            return sum(1 for _ in f)
    except OSError as e:
        logger.info("Failed to count lines in %s: %s", filepath, e)
        return 0


def _get_file_size_kb(filepath: Path) -> float:
    """Get file size in kilobytes."""
    try:
        return filepath.stat().st_size / 1024.0
    except OSError as e:
        logger.info("Failed to stat file %s: %s", filepath, e)
        return 0.0


def scan_log_files() -> List[Dict[str, Any]]:
    """Scan all .log files in system_logs/ and report their sizes."""
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

    # Biggest first: log_health_summary takes files[0] as the largest.
    results.sort(key=lambda x: x["lines"], reverse=True)
    json_handler.log_operation("log_watchdog_check", {"files_scanned": len(results)})
    return results


def get_oversized_files(threshold: int = WARN_THRESHOLD_LINES) -> List[Dict[str, Any]]:
    """Get only files exceeding the threshold."""
    return [f for f in scan_log_files() if f["lines"] >= threshold]


def truncate_log_file(filepath: Path, keep_lines: int = DEFAULT_MAX_LINES) -> Tuple[int, int]:
    """Truncate a log file to keep only the last N lines."""
    filepath = Path(filepath)
    try:
        original_count = 0
        kept_lines: deque = deque(maxlen=keep_lines)
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                original_count += 1
                kept_lines.append(line)

        if original_count <= keep_lines:
            return original_count, original_count

        marker = (
            f"--- LOG TRUNCATED by PRAX watchdog at {datetime.now().isoformat()} "
            f"| was {original_count} lines, kept last {keep_lines} ---\n"
        )

        # Sibling temp + replace: a crash mid-write never leaves the log empty; a leftover is overwritten next run.
        tmp_path = filepath.with_name(f".{filepath.name}.trunc")
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(marker)
            f.writelines(kept_lines)
        os.replace(tmp_path, filepath)

        return original_count, keep_lines + 1  # +1 for marker line

    except OSError as e:
        logger.warning("Failed to truncate log file %s: %s", filepath, e)
        return 0, 0


def enforce_log_limits(
    max_lines: int = DEFAULT_MAX_LINES, threshold: int = WARN_THRESHOLD_LINES
) -> List[Dict[str, Any]]:
    """Scan and truncate all oversized log files."""
    actions: List[Dict[str, Any]] = []

    oversized = get_oversized_files(threshold)

    for file_info in oversized:
        filepath = Path(file_info["path"])
        original, new = truncate_log_file(filepath, max_lines)

        actions.append(
            {"name": file_info["name"], "original_lines": original, "new_lines": new, "truncated": original != new}
        )

    return actions


def log_health_summary(files: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Generate a health summary of system logs (from an existing scan when given)."""
    if files is None:
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
    """Scan all branch logs/ directories for files with unbounded growth."""
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
    """Truncate oversized branch log files (including .jsonl)."""
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


def branch_log_health_summary(files: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Generate a health summary of branch logs (from an existing scan when given)."""
    if files is None:
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
    """Delete log files older than max_age_days across system_logs/ and branch logs/."""
    all_removed: List[Dict[str, Any]] = []

    system_patterns = ["*.log", "*.log.[0-9]"]
    all_removed.extend(_sweep_directory(_get_system_logs_dir(), system_patterns, max_age_days))

    branch_patterns = ["*.log", "*.log.[0-9]", "*.jsonl", "*.jsonl.[0-9]"]
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
