# =================== AIPass ====================
# Name: red_flag_detector.py
# Description: Branch Red Flag Detection Engine
# Version: 0.1.0
# Created: 2026-01-30
# Modified: 2026-10-17
# =============================================

"""
Branch Red Flag Detection Engine

RED FLAG: code changed in the window but memory was not updated after it (or within threshold_hours before).
Reference: docs/monitoring.md"""

from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

from aipass.prax import logger
from aipass.daemon.apps.handlers.json import json_handler
from aipass.daemon.apps.handlers.monitoring import activity_collector


STATUS_RED_FLAG = "RED_FLAG"
STATUS_OK = "OK"
STATUS_NO_ACTIVITY = "NO_ACTIVITY"
STATUS_ERROR = "ERROR"


def _parse_iso_datetime(iso_string: str) -> Optional[datetime]:
    """Parse an ISO format datetime string to datetime object.
    None (unparseable or empty) leaves that mtime out of the latest-change comparison."""
    if not iso_string:
        return None
    try:
        if "." in iso_string:
            return datetime.fromisoformat(iso_string)
        else:
            return datetime.fromisoformat(iso_string)
    except (ValueError, TypeError) as e:
        logger.warning("Failed to parse ISO datetime %s: %s", iso_string, e)
        return None


def _get_most_recent_mtime(files: List[Dict[str, Any]]) -> Optional[datetime]:
    """Get the most recent modification time from a list of file entries."""
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
    branch_name: str, branch_path: str, since_timestamp: Optional[datetime] = None, threshold_hours: float = 2.0
) -> Dict[str, Any]:
    """Check a single branch for red flag violations."""
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
        activity = activity_collector.scan_branch_activity(branch_name, branch_path, since_timestamp)
    except Exception as e:
        logger.error("Failed to scan branch %s: %s", branch_name, e)
        result["status"] = STATUS_ERROR
        result["reason"] = f"Failed to scan branch: {str(e)}"
        return result

    code_files = activity.get("code_files", [])
    memory_files = activity.get("memory_files", [])

    result["code_changes"] = [{"file": f.get("name", ""), "mtime": f.get("mtime", "")} for f in code_files]
    result["code_change_count"] = len(code_files)

    result["memory_files_modified"] = [{"file": f.get("name", ""), "mtime": f.get("mtime", "")} for f in memory_files]

    latest_code = _get_most_recent_mtime(code_files)
    latest_memory = _get_most_recent_mtime(memory_files)

    if latest_code:
        result["latest_code_change"] = latest_code.isoformat()
    if latest_memory:
        result["memory_last_update"] = latest_memory.isoformat()

    if not code_files:
        result["status"] = STATUS_NO_ACTIVITY
        result["reason"] = "No code changes in time window"
        return result

    if latest_code:
        if latest_memory:
            time_diff = latest_memory - latest_code
            hours_diff = time_diff.total_seconds() / 3600

            if latest_memory >= latest_code:
                result["status"] = STATUS_OK
                result["hours_since_code"] = round(hours_diff, 2)
                result["reason"] = f"Memory updated {abs(hours_diff):.1f}h after code changes"
            elif abs(hours_diff) <= threshold_hours:
                # Grace window: memory is often written just before the final code edit.
                result["status"] = STATUS_OK
                result["hours_since_code"] = round(hours_diff, 2)
                result["reason"] = f"Memory update within threshold ({abs(hours_diff):.1f}h before code)"
            else:
                result["status"] = STATUS_RED_FLAG
                hours_since = (datetime.now() - latest_code).total_seconds() / 3600
                result["hours_since_code"] = round(hours_since, 2)
                result["reason"] = f"Code changed but memory last updated {abs(hours_diff):.1f}h BEFORE code"
        else:
            result["status"] = STATUS_RED_FLAG
            hours_since = (datetime.now() - latest_code).total_seconds() / 3600
            result["hours_since_code"] = round(hours_since, 2)
            result["reason"] = f"Code changed {hours_since:.1f}h ago but no memory updates in time window"

    return result


def detect_red_flags(since_timestamp: Optional[datetime] = None, threshold_hours: float = 2.0) -> List[Dict[str, Any]]:
    """Detect red flag violations across ALL branches, RED_FLAG first then by name."""
    if since_timestamp is None:
        since_timestamp = datetime.now() - timedelta(hours=24)

    json_handler.log_operation("red_flag_scan")

    branches = activity_collector.get_branch_paths()
    results: List[Dict[str, Any]] = []

    for branch_info in branches:
        name = branch_info.get("name", "")
        path = branch_info.get("path", "")

        if not name or not path:
            continue

        status = get_branch_status(name, path, since_timestamp, threshold_hours)
        results.append(status)

    def sort_key(item: Dict[str, Any]) -> tuple:
        """Sort branches by status severity (RED_FLAG first), then alphabetically."""
        status_order = {
            STATUS_RED_FLAG: 0,
            STATUS_ERROR: 1,
            STATUS_OK: 2,
            STATUS_NO_ACTIVITY: 3,
        }
        return (status_order.get(item.get("status", ""), 99), item.get("branch_name", ""))

    results.sort(key=sort_key)

    return results


def get_red_flag_summary(since_timestamp: Optional[datetime] = None, threshold_hours: float = 2.0) -> Dict[str, Any]:
    """Get a summary of red flag detection across all branches."""
    if since_timestamp is None:
        since_timestamp = datetime.now() - timedelta(hours=24)

    time_window = (datetime.now() - since_timestamp).total_seconds() / 3600

    all_results = detect_red_flags(since_timestamp, threshold_hours)

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
    print("Testing red_flag_detector...")
    print("=" * 60)

    summary = get_red_flag_summary()

    print(f"Scan time: {summary['scan_time']}")
    print(f"Time window: {summary['time_window_hours']} hours")
    print(f"Threshold: {summary['threshold_hours']} hours")
    print(f"\nTotal branches: {summary['total_branches']}")
    print(f"  RED FLAGS: {summary['red_flags']}")
    print(f"  OK: {summary['ok']}")
    print(f"  No activity: {summary['no_activity']}")
    print(f"  Errors: {summary['errors']}")

    if summary["violations"]:
        print(f"\n{'=' * 60}")
        print("RED FLAG VIOLATIONS:")
        print("=" * 60)
        for v in summary["violations"]:
            print(f"\n  Branch: {v['branch_name']}")
            print(f"  Status: {v['status']}")
            print(f"  Reason: {v['reason']}")
            print(f"  Code changes: {v['code_change_count']}")
            print(f"  Latest code change: {v['latest_code_change']}")
            print(f"  Memory last update: {v['memory_last_update']}")
    else:
        print("\nNo red flag violations detected.")
