
# ===================AIPASS====================
# META DATA HEADER
# Name: red_flag_detector.py - Branch Red Flag Detection Engine
# Date: 2026-01-30
# Version: 0.1.0
# Category: daemon/handlers/monitoring
#
# CHANGELOG (Max 5 entries):
#   - v0.1.0 (2026-01-30): Initial implementation - FPLAN-0266 Phase 2
#
# CODE STANDARDS:
#   - Handler implements detection logic, module orchestrates
#   - NO Prax logger in handlers (handlers don't log)
#   - Uses pathlib for all path operations
#   - Standard library only
# =============================================

"""
Branch Red Flag Detection Engine

Detects presence violations: branches that modified code but did NOT update their memory files.
A RED FLAG indicates a branch did work but didn't maintain their presence (memory files).

Detection Logic:
- If code files were modified within the time window
- AND memory files were NOT modified (or modified BEFORE the code changes)
- This is a RED FLAG violation

OK Conditions:
- No code changes in time window (nothing to update)
- Memory updated MORE RECENTLY than code (presence maintained)
- Memory updated WITHIN threshold_hours of code changes
"""

from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

from aipass.daemon.apps.handlers.monitoring import activity_collector


# Status constants
STATUS_RED_FLAG = "RED_FLAG"
STATUS_OK = "OK"
STATUS_NO_ACTIVITY = "NO_ACTIVITY"
STATUS_ERROR = "ERROR"


def _parse_iso_datetime(iso_string: str) -> Optional[datetime]:
    """
    Parse an ISO format datetime string to datetime object.

    Args:
        iso_string: ISO format datetime string (e.g., "2026-01-30T10:30:00.123456")

    Returns:
        datetime object or None if parsing fails.
    """
    if not iso_string:
        return None
    try:
        # Handle both with and without microseconds
        if '.' in iso_string:
            return datetime.fromisoformat(iso_string)
        else:
            return datetime.fromisoformat(iso_string)
    except (ValueError, TypeError):
        return None


def _get_most_recent_mtime(files: List[Dict[str, Any]]) -> Optional[datetime]:
    """
    Get the most recent modification time from a list of file entries.

    Args:
        files: List of file dicts with 'mtime' key (ISO format string).

    Returns:
        Most recent datetime or None if list is empty or no valid times.
    """
    if not files:
        return None

    mtimes = []
    for f in files:
        mtime_str = f.get("mtime")
        if mtime_str:
            dt = _parse_iso_datetime(mtime_str)
            if dt:
                mtimes.append(dt)

    return max(mtimes) if mtimes else None


def get_branch_status(
    branch_name: str,
    branch_path: str,
    since_timestamp: Optional[datetime] = None,
    threshold_hours: float = 2.0
) -> Dict[str, Any]:
    """
    Check a single branch for red flag violations.

    A RED FLAG occurs when:
    - Code files were modified since the timestamp
    - Memory files were NOT modified, OR were modified BEFORE the latest code change
      (with a grace period of threshold_hours)

    Args:
        branch_name: Name of the branch (uppercase, e.g., "DRONE").
        branch_path: Absolute path to the branch directory.
        since_timestamp: Only consider changes since this time.
                        Defaults to last 24 hours.
        threshold_hours: Grace period in hours. Memory must be updated within
                        this many hours AFTER the latest code change.

    Returns:
        Dict with structure:
        {
            "branch_name": str,
            "branch_path": str,
            "status": "RED_FLAG" | "OK" | "NO_ACTIVITY" | "ERROR",
            "code_changes": [{"file": str, "mtime": str}],
            "code_change_count": int,
            "latest_code_change": str (ISO) or None,
            "memory_files_modified": [{"file": str, "mtime": str}],
            "memory_last_update": str (ISO) or None,
            "hours_since_code": float or None,
            "threshold_hours": float,
            "reason": str,
            "check_time": str
        }
    """
    # Default time window: last 24 hours
    if since_timestamp is None:
        since_timestamp = datetime.now() - timedelta(hours=24)

    result = {
        "branch_name": branch_name,
        "branch_path": branch_path,
        "status": STATUS_OK,
        "code_changes": [],
        "code_change_count": 0,
        "latest_code_change": None,
        "memory_files_modified": [],
        "memory_last_update": None,
        "hours_since_code": None,
        "threshold_hours": threshold_hours,
        "reason": "",
        "check_time": datetime.now().isoformat(),
    }

    try:
        # Get activity data from the collector
        activity = activity_collector.scan_branch_activity(
            branch_name, branch_path, since_timestamp
        )
    except Exception as e:
        result["status"] = STATUS_ERROR
        result["reason"] = f"Failed to scan branch: {str(e)}"
        return result

    # Extract code file changes
    code_files = activity.get("code_files", [])
    memory_files = activity.get("memory_files", [])

    # Format code changes for output
    result["code_changes"] = [
        {"file": f.get("name", ""), "mtime": f.get("mtime", "")}
        for f in code_files
    ]
    result["code_change_count"] = len(code_files)

    # Format memory file modifications for output
    result["memory_files_modified"] = [
        {"file": f.get("name", ""), "mtime": f.get("mtime", "")}
        for f in memory_files
    ]

    # Get most recent times
    latest_code = _get_most_recent_mtime(code_files)
    latest_memory = _get_most_recent_mtime(memory_files)

    if latest_code:
        result["latest_code_change"] = latest_code.isoformat()
    if latest_memory:
        result["memory_last_update"] = latest_memory.isoformat()

    # Decision logic
    # Case 1: No code changes - OK (nothing to update)
    if not code_files:
        result["status"] = STATUS_NO_ACTIVITY
        result["reason"] = "No code changes in time window"
        return result

    # Case 2: Code changed, check if memory was updated appropriately
    if latest_code:
        if latest_memory:
            # Calculate how long after code the memory was updated
            time_diff = latest_memory - latest_code
            hours_diff = time_diff.total_seconds() / 3600

            if latest_memory >= latest_code:
                # Memory was updated at same time or after code - OK
                result["status"] = STATUS_OK
                result["hours_since_code"] = round(hours_diff, 2)
                result["reason"] = f"Memory updated {abs(hours_diff):.1f}h after code changes"
            elif abs(hours_diff) <= threshold_hours:
                # Memory was updated slightly before, but within threshold - OK
                # This covers cases where memory was updated just before final code commit
                result["status"] = STATUS_OK
                result["hours_since_code"] = round(hours_diff, 2)
                result["reason"] = f"Memory update within threshold ({abs(hours_diff):.1f}h before code)"
            else:
                # Memory was updated too long before code changes - RED FLAG
                result["status"] = STATUS_RED_FLAG
                hours_since = (datetime.now() - latest_code).total_seconds() / 3600
                result["hours_since_code"] = round(hours_since, 2)
                result["reason"] = f"Code changed but memory last updated {abs(hours_diff):.1f}h BEFORE code"
        else:
            # No memory files modified in time window - RED FLAG
            result["status"] = STATUS_RED_FLAG
            hours_since = (datetime.now() - latest_code).total_seconds() / 3600
            result["hours_since_code"] = round(hours_since, 2)
            result["reason"] = f"Code changed {hours_since:.1f}h ago but no memory updates in time window"

    return result


def detect_red_flags(
    since_timestamp: Optional[datetime] = None,
    threshold_hours: float = 2.0
) -> List[Dict[str, Any]]:
    """
    Detect red flag violations across ALL branches.

    Scans all branches in the system and identifies those where code was modified
    but memory files were not updated appropriately.

    Args:
        since_timestamp: Only consider changes since this time.
                        Defaults to last 24 hours.
        threshold_hours: Grace period in hours for memory updates after code changes.

    Returns:
        List of branch status dicts (same structure as get_branch_status),
        sorted with RED_FLAG violations first, then by branch name.
    """
    # Default time window: last 24 hours
    if since_timestamp is None:
        since_timestamp = datetime.now() - timedelta(hours=24)

    # Get all branch paths
    branches = activity_collector.get_branch_paths()
    results: List[Dict[str, Any]] = []

    for branch_info in branches:
        name = branch_info.get("name", "")
        path = branch_info.get("path", "")

        if not name or not path:
            continue

        status = get_branch_status(name, path, since_timestamp, threshold_hours)
        results.append(status)

    # Sort: RED_FLAG first, then by branch name
    def sort_key(item: Dict[str, Any]) -> tuple:
        status_order = {
            STATUS_RED_FLAG: 0,
            STATUS_ERROR: 1,
            STATUS_OK: 2,
            STATUS_NO_ACTIVITY: 3,
        }
        return (status_order.get(item.get("status", ""), 99), item.get("branch_name", ""))

    results.sort(key=sort_key)

    return results


def get_red_flag_summary(
    since_timestamp: Optional[datetime] = None,
    threshold_hours: float = 2.0
) -> Dict[str, Any]:
    """
    Get a summary of red flag detection across all branches.

    Args:
        since_timestamp: Only consider changes since this time.
        threshold_hours: Grace period in hours for memory updates.

    Returns:
        Dict with structure:
        {
            "scan_time": str,
            "time_window_hours": float,
            "threshold_hours": float,
            "total_branches": int,
            "red_flags": int,
            "ok": int,
            "no_activity": int,
            "errors": int,
            "violations": [{branch status for RED_FLAG only}],
            "all_branches": [{all branch statuses}]
        }
    """
    if since_timestamp is None:
        since_timestamp = datetime.now() - timedelta(hours=24)

    time_window = (datetime.now() - since_timestamp).total_seconds() / 3600

    all_results = detect_red_flags(since_timestamp, threshold_hours)

    # Count by status
    counts = {
        STATUS_RED_FLAG: 0,
        STATUS_OK: 0,
        STATUS_NO_ACTIVITY: 0,
        STATUS_ERROR: 0,
    }

    violations = []
    for result in all_results:
        status = result.get("status", "")
        if status in counts:
            counts[status] += 1
        if status == STATUS_RED_FLAG:
            violations.append(result)

    return {
        "scan_time": datetime.now().isoformat(),
        "time_window_hours": round(time_window, 2),
        "threshold_hours": threshold_hours,
        "total_branches": len(all_results),
        "red_flags": counts[STATUS_RED_FLAG],
        "ok": counts[STATUS_OK],
        "no_activity": counts[STATUS_NO_ACTIVITY],
        "errors": counts[STATUS_ERROR],
        "violations": violations,
        "all_branches": all_results,
    }


if __name__ == "__main__":
    # Simple test
    print("Testing red_flag_detector...")
    print("=" * 60)

    # Get summary
    summary = get_red_flag_summary()

    print(f"Scan time: {summary['scan_time']}")
    print(f"Time window: {summary['time_window_hours']} hours")
    print(f"Threshold: {summary['threshold_hours']} hours")
    print(f"\nTotal branches: {summary['total_branches']}")
    print(f"  RED FLAGS: {summary['red_flags']}")
    print(f"  OK: {summary['ok']}")
    print(f"  No activity: {summary['no_activity']}")
    print(f"  Errors: {summary['errors']}")

    if summary['violations']:
        print(f"\n{'='*60}")
        print("RED FLAG VIOLATIONS:")
        print("=" * 60)
        for v in summary['violations']:
            print(f"\n  Branch: {v['branch_name']}")
            print(f"  Status: {v['status']}")
            print(f"  Reason: {v['reason']}")
            print(f"  Code changes: {v['code_change_count']}")
            print(f"  Latest code change: {v['latest_code_change']}")
            print(f"  Memory last update: {v['memory_last_update']}")
    else:
        print("\nNo red flag violations detected.")
