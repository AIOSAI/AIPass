# =================== AIPass ====================
# Name: activity_collector.py
# Description: Branch Activity Data Collector
# Version: 0.1.0
# Created: 2026-01-30
# Modified: 2026-01-30
# =============================================

"""
Branch Activity Data Collector Handler

Collects activity data from all branches in the AIPass system.
Scans for code files (.py) and memory files (.trinity/*.json, README.md, DASHBOARD.local.json).
Provides file modification timestamps for activity tracking.
"""

import os
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

from aipass.daemon.apps.handlers.json import json_handler


# Constants — find registry: env var > repo root > ~/.aipass/
_REPO_ROOT = Path(__file__).resolve().parents[6]  # src/aipass/daemon/apps/handlers/monitoring -> repo root
_REGISTRY_CANDIDATES = [
    Path(os.environ.get('AIPASS_REGISTRY', '')),
    _REPO_ROOT / 'AIPASS_REGISTRY.json',
    Path.home() / '.aipass' / 'AIPASS_REGISTRY.json',
]
REGISTRY_PATH = next((p for p in _REGISTRY_CANDIDATES if p.name and p.exists()), _REGISTRY_CANDIDATES[-1])
MEMORY_FILE_PATTERNS = ["local.json", "observations.json", "passport.json", "README.md", "DASHBOARD.local.json"]
CODE_FILE_EXTENSION = ".py"


def load_branch_registry() -> Dict[str, Any]:
    """
    Load the BRANCH_REGISTRY.json file.

    Returns:
        Dict containing registry data with 'metadata' and 'branches' keys.
        Returns empty dict with empty branches list on error.
    """
    if not REGISTRY_PATH.exists():
        return {"metadata": {}, "branches": []}

    try:
        with open(REGISTRY_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"metadata": {}, "branches": []}


def get_branch_paths() -> List[Dict[str, str]]:
    """
    Get all branch names and absolute paths from the registry.

    Registry stores relative paths (e.g. 'src/aipass/daemon').
    This resolves them against the repo root so consumers get absolute paths.

    Returns:
        List of dicts with 'name' and 'path' keys for each branch.
    """
    registry = load_branch_registry()
    branches = registry.get("branches", [])

    result = []
    for b in branches:
        name = b.get("name", "")
        raw_path = b.get("path", "")
        if not name or not raw_path:
            continue
        # Resolve relative registry paths against repo root
        resolved = Path(raw_path)
        if not resolved.is_absolute():
            resolved = _REPO_ROOT / raw_path
        result.append({"name": name, "path": str(resolved)})
    return result


def _get_file_mtime(file_path: Path) -> Optional[datetime]:
    """
    Get modification time of a file.

    Args:
        file_path: Path to the file.

    Returns:
        datetime of last modification, or None if file doesn't exist.
    """
    try:
        if file_path.exists():
            return datetime.fromtimestamp(file_path.stat().st_mtime)
    except OSError:
        pass
    return None


def _is_memory_file(file_path: Path, branch_name: str) -> bool:
    """
    Check if a file is a memory file for this branch.

    Memory files follow patterns:
    - .trinity/local.json
    - .trinity/observations.json
    - .trinity/passport.json
    - README.md
    - DASHBOARD.local.json

    Args:
        file_path: Path to check.
        branch_name: Name of the branch (uppercase).

    Returns:
        True if file is a memory file.
    """
    name = file_path.name
    parent_name = file_path.parent.name

    # Check for .trinity/ memory files
    if parent_name == ".trinity" and name in ("local.json", "observations.json", "passport.json"):
        return True
    if name == "README.md":
        return True
    if name == "DASHBOARD.local.json":
        return True

    return False


def _scan_directory_files(
    directory: Path,
    branch_name: str,
    since: Optional[datetime] = None,
    max_depth: int = 5
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Scan a directory for code and memory files.

    Args:
        directory: Directory to scan.
        branch_name: Name of the branch (uppercase).
        since: Only include files modified since this time.
        max_depth: Maximum directory depth to scan.

    Returns:
        Dict with 'code_files' and 'memory_files' lists.
    """
    code_files: List[Dict[str, Any]] = []
    memory_files: List[Dict[str, Any]] = []

    if not directory.exists() or not directory.is_dir():
        return {"code_files": code_files, "memory_files": memory_files}

    def scan_recursive(path: Path, depth: int = 0) -> None:
        if depth > max_depth:
            return

        try:
            for item in path.iterdir():
                # Skip hidden directories and __pycache__ (but allow .trinity)
                if item.is_dir():
                    if item.name == '__pycache__':
                        continue
                    if item.name.startswith('.') and item.name != '.trinity':
                        continue
                    scan_recursive(item, depth + 1)
                elif item.is_file():
                    mtime = _get_file_mtime(item)
                    if mtime is None:
                        continue

                    # Apply time filter if specified
                    if since and mtime < since:
                        continue

                    file_info = {
                        "path": str(item),
                        "name": item.name,
                        "mtime": mtime.isoformat(),
                        "mtime_datetime": mtime,
                    }

                    # Categorize file
                    if _is_memory_file(item, branch_name):
                        memory_files.append(file_info)
                    elif item.suffix == CODE_FILE_EXTENSION:
                        code_files.append(file_info)
        except PermissionError:
            pass
        except OSError:
            pass

    scan_recursive(directory)

    return {"code_files": code_files, "memory_files": memory_files}


def scan_branch_activity(
    branch_name: str,
    branch_path: str,
    since: Optional[datetime] = None
) -> Dict[str, Any]:
    """
    Scan a single branch directory and collect file modification times.

    Args:
        branch_name: Name of the branch (e.g., "DRONE").
        branch_path: Absolute path to the branch directory.
        since: Only include files modified since this time.
               Defaults to last 24 hours if not specified.

    Returns:
        Dict with structure:
        {
            "branch_name": str,
            "path": str,
            "code_files": [{"path": str, "name": str, "mtime": str}],
            "memory_files": [{"path": str, "name": str, "mtime": str}],
            "last_activity": str (ISO format) or None,
            "total_files": int,
            "scan_time": str
        }
    """
    # Default to last 24 hours
    if since is None:
        since = datetime.now() - timedelta(hours=24)

    directory = Path(branch_path)
    scan_result = _scan_directory_files(directory, branch_name, since)

    # Find the most recent activity
    all_files = scan_result["code_files"] + scan_result["memory_files"]
    last_activity = None
    if all_files:
        most_recent = max(all_files, key=lambda f: f["mtime_datetime"])
        last_activity = most_recent["mtime"]

    # Clean up internal datetime objects before returning
    for f in scan_result["code_files"]:
        del f["mtime_datetime"]
    for f in scan_result["memory_files"]:
        del f["mtime_datetime"]

    return {
        "branch_name": branch_name,
        "path": branch_path,
        "code_files": scan_result["code_files"],
        "memory_files": scan_result["memory_files"],
        "last_activity": last_activity,
        "total_files": len(all_files),
        "scan_time": datetime.now().isoformat(),
    }


def get_all_branch_activity(
    since: Optional[datetime] = None
) -> Dict[str, Any]:
    """
    Collect activity data for ALL branches in the system.

    Args:
        since: Only include files modified since this time.
               Defaults to last 24 hours if not specified.

    Returns:
        Dict with structure:
        {
            "scan_time": str,
            "time_window_hours": float,
            "branches_scanned": int,
            "branches_with_activity": int,
            "total_files_modified": int,
            "branches": {
                "BRANCH_NAME": {branch activity dict}
            }
        }
    """
    if since is None:
        since = datetime.now() - timedelta(hours=24)

    json_handler.log_operation("activity_scan")
    time_window_hours = (datetime.now() - since).total_seconds() / 3600

    branch_paths = get_branch_paths()
    results: Dict[str, Any] = {}
    total_files = 0
    active_count = 0

    for branch_info in branch_paths:
        name = branch_info["name"]
        path = branch_info["path"]

        activity = scan_branch_activity(name, path, since)
        results[name] = activity

        if activity["total_files"] > 0:
            active_count += 1
            total_files += activity["total_files"]

    return {
        "scan_time": datetime.now().isoformat(),
        "time_window_hours": round(time_window_hours, 2),
        "branches_scanned": len(branch_paths),
        "branches_with_activity": active_count,
        "total_files_modified": total_files,
        "branches": results,
    }


if __name__ == "__main__":
    # Simple test
    print("Testing activity_collector...")
    print(f"Registry path: {REGISTRY_PATH}")
    print(f"Registry exists: {REGISTRY_PATH.exists()}")

    branches = get_branch_paths()
    print(f"Found {len(branches)} branches")

    if branches:
        # Test scanning one branch
        first = branches[0]
        print(f"\nScanning {first['name']}...")
        activity = scan_branch_activity(first['name'], first['path'])
        print(f"  Code files: {len(activity['code_files'])}")
        print(f"  Memory files: {len(activity['memory_files'])}")
        print(f"  Last activity: {activity['last_activity']}")
