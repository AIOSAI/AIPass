# =================== AIPass ====================
# Name: activity_collector.py
# Description: Branch Activity Data Collector
# Version: 0.4.0
# Created: 2026-01-30
# Modified: 2026-11-09
# =============================================

"""
Branch Activity Data Collector Handler
"""

from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

from aipass.prax import logger
from aipass.daemon.apps.handlers.json import json_handler
from aipass.daemon.apps.handlers.module_root import module_file

# @memory's PUBLIC fleet gateway: who counts as a citizen is @memory's answer, one registry reader fleet-wide.
from aipass.memory.apps.modules import fleet

_REPO_ROOT = module_file(__file__).parents[6]  # src/aipass/daemon/apps/handlers/monitoring -> repo root
MEMORY_FILE_PATTERNS = ["local.json", "observations.json", "passport.json", "README.md", "DASHBOARD.local.json"]
CODE_FILE_EXTENSION = ".py"


def get_branch_paths() -> List[Dict[str, str]]:
    """Every citizen in @memory's fleet (core, residents, externals): registry name and absolute path."""
    return [{"name": b["name"], "path": str(b["path"])} for b in fleet.fleet_branches(_REPO_ROOT, name_from="registry")]


def _get_file_mtime(file_path: Path) -> Optional[datetime]:
    """Get modification time of a file, or None if it is missing or unreadable."""
    try:
        if file_path.exists():
            return datetime.fromtimestamp(file_path.stat().st_mtime)
    except OSError as e:
        logger.warning("Failed to get mtime for %s: %s", file_path, e)
    return None


def _is_memory_file(file_path: Path) -> bool:
    """Check if a file is a memory file for this branch."""
    name = file_path.name
    parent_name = file_path.parent.name

    if parent_name == ".trinity" and name in ("local.json", "observations.json", "passport.json"):
        return True
    if name == "README.md":
        return True
    if name == "DASHBOARD.local.json":
        return True

    return False


def _scan_directory_files(
    directory: Path, since: Optional[datetime] = None, max_depth: int = 5
) -> Dict[str, List[Dict[str, Any]]]:
    """Scan a directory for code and memory files."""
    code_files: List[Dict[str, Any]] = []
    memory_files: List[Dict[str, Any]] = []

    if not directory.exists() or not directory.is_dir():
        return {"code_files": code_files, "memory_files": memory_files}

    def _should_skip_dir(item: Path) -> bool:
        """Check if a directory should be skipped during scanning.
        A dropbox is a sandbox like .archive; judged by its own name below the root,
        so a branch that lives under a dropbox is still read."""
        if item.name in ("__pycache__", "dropbox"):
            return True
        return item.name.startswith(".") and item.name != ".trinity"

    def _process_file(item: Path) -> None:
        """Categorize a single file into code_files or memory_files."""
        mtime = _get_file_mtime(item)
        if mtime is None:
            return
        if since and mtime < since:
            return

        file_info = {
            "path": str(item),
            "name": item.name,
            "mtime": mtime.isoformat(),
            "mtime_datetime": mtime,
        }

        if _is_memory_file(item):
            memory_files.append(file_info)
        elif item.suffix == CODE_FILE_EXTENSION:
            code_files.append(file_info)

    def scan_recursive(path: Path, depth: int = 0) -> None:
        """Recursively collect code and memory files up to max_depth."""
        if depth > max_depth:
            return

        try:
            for item in path.iterdir():
                if item.is_dir():
                    if not _should_skip_dir(item):
                        scan_recursive(item, depth + 1)
                elif item.is_file():
                    _process_file(item)
        except PermissionError as e:
            logger.warning("Permission denied scanning %s: %s", path, e)
        except OSError as e:
            logger.warning("OS error scanning %s: %s", path, e)

    scan_recursive(directory)

    return {"code_files": code_files, "memory_files": memory_files}


def scan_branch_activity(branch_name: str, branch_path: str, since: Optional[datetime] = None) -> Dict[str, Any]:
    """Scan a single branch directory and collect file modification times."""
    if since is None:
        since = datetime.now() - timedelta(hours=24)

    directory = Path(branch_path)
    scan_result = _scan_directory_files(directory, since)

    all_files = scan_result["code_files"] + scan_result["memory_files"]
    last_activity = None
    if all_files:
        most_recent = max(all_files, key=lambda f: f["mtime_datetime"])
        last_activity = most_recent["mtime"]

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
    since: Optional[datetime] = None, branch_paths: Optional[List[Dict[str, str]]] = None
) -> Dict[str, Any]:
    """Collect activity data for ALL branches; ``branch_paths`` spares a second fleet read."""
    if since is None:
        since = datetime.now() - timedelta(hours=24)

    json_handler.log_operation("activity_scan")
    time_window_hours = (datetime.now() - since).total_seconds() / 3600

    if branch_paths is None:
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
    print("Testing activity_collector...")

    branches = get_branch_paths()
    print(f"Found {len(branches)} branches")

    if branches:
        first = branches[0]
        print(f"\nScanning {first['name']}...")
        activity = scan_branch_activity(first["name"], first["path"])
        print(f"  Code files: {len(activity['code_files'])}")
        print(f"  Memory files: {len(activity['memory_files'])}")
        print(f"  Last activity: {activity['last_activity']}")
