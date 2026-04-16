# =================== AIPass ====================
# Name: registry.py
# Description: *_REGISTRY.json discovery and CRUD operations
# Version: 1.0.0
# Created: 2026-03-05
# Modified: 2026-03-13
# =============================================

"""*_REGISTRY.json discovery and CRUD operations."""

import os
from datetime import datetime
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.spawn.apps.handlers.json import json_handler


def _branches_as_list(branches):
    """Normalize branches to a list regardless of storage format.

    The registry may store branches as:
    - A list of dicts (legacy format)
    - A dict keyed by name (dict format from setup.sh)

    Returns:
        list of branch entry dicts
    """
    if isinstance(branches, dict):
        return list(branches.values())
    if isinstance(branches, list):
        return branches
    return []


def _glob_registry(directory):
    """Find the first *_REGISTRY.json in a directory (sorted for consistency).

    Args:
        directory: Path to search in

    Returns:
        Path to the registry file, or None if not found
    """
    matches = sorted(directory.glob("*_REGISTRY.json"))
    return matches[0] if matches else None


def find_registry(start_path=None):
    """
    Find *_REGISTRY.json — walks up from __file__ and start_path/cwd.

    The first *_REGISTRY.json found while walking up IS the project boundary.
    If multiple exist in the same directory, picks the first alphabetically.

    Priority:
    1. AIPASS_REGISTRY environment variable
    2. Walk up from __file__ — first dir containing *_REGISTRY.json
    3. Walk up from start_path/cwd — first dir containing *_REGISTRY.json
    4. Last resort: cwd / AIPASS_REGISTRY.json (backwards compat)

    Args:
        start_path: Directory to start searching from

    Returns:
        Path to *_REGISTRY.json
    """
    # Check environment variable first (same as drone's config.py)
    env_path = os.environ.get("AIPASS_REGISTRY")
    if env_path:
        return Path(env_path)

    # Walk up from start_path or cwd FIRST — user's location takes priority
    current = Path(start_path).resolve() if start_path else Path.cwd()
    for parent in [current] + list(current.parents):
        found = _glob_registry(parent)
        if found:
            return found

    # Walk up from package location (fallback for editable installs)
    pkg_dir = Path(__file__).resolve().parent
    for parent in [pkg_dir] + list(pkg_dir.parents):
        found = _glob_registry(parent)
        if found:
            return found

    # Last resort: cwd
    return Path.cwd() / "AIPASS_REGISTRY.json"


def load_registry(registry_path):
    """
    Load registry from JSON file. Returns empty schema if missing.

    Args:
        registry_path: Path to AIPASS_REGISTRY.json

    Returns:
        Dict with metadata and branches list
    """
    registry_path = Path(registry_path)
    if not registry_path.exists():
        return {
            "metadata": {
                "version": "1.0.0",
                "last_updated": datetime.now().strftime("%Y-%m-%d"),
                "total_branches": 0,
            },
            "branches": [],
        }

    data = json_handler.read_json(registry_path)
    if data is not None:
        return data
    return {
        "metadata": {
            "version": "1.0.0",
            "last_updated": datetime.now().strftime("%Y-%m-%d"),
            "total_branches": 0,
        },
        "branches": [],
    }


def save_registry(registry_path, data):
    """
    Save registry to JSON file. Auto-updates timestamp and sorts branches.

    Args:
        registry_path: Path to AIPASS_REGISTRY.json
        data: Registry dict to save

    Returns:
        True on success, False on error
    """
    registry_path = Path(registry_path)
    data["metadata"]["last_updated"] = datetime.now().strftime("%Y-%m-%d")

    if "branches" in data:
        branches = data["branches"]
        if isinstance(branches, dict):
            branch_list = list(branches.values())
        else:
            branch_list = branches
        data["branches"] = sorted(branch_list, key=lambda b: b.get("name", ""))

    return json_handler.write_json(registry_path, data)


def get_next_citizen_number(registry_path):
    """Get next citizen number from registry (count of existing branches + 1).

    Args:
        registry_path: Path to AIPASS_REGISTRY.json

    Returns:
        int: Next citizen number
    """
    data = load_registry(registry_path)
    branches = data.get("branches", [])
    return len(_branches_as_list(branches)) + 1


def add_to_registry(registry_path, branch_name, branch_path, profile, email, purpose=""):
    """
    Add a new branch entry to the registry.

    Args:
        registry_path: Path to AIPASS_REGISTRY.json
        branch_name: Uppercase branch name (e.g. "MY_AGENT")
        branch_path: Absolute path to branch directory
        profile: Profile string (e.g. "AIPass Workshop")
        email: Branch email (e.g. "@my_agent")
        purpose: Optional purpose description

    Returns:
        True if added, False if already exists or error
    """
    registry = load_registry(registry_path)
    branches = registry.get("branches", [])

    # Check for duplicates — handle both dict and list formats
    if isinstance(branches, dict):
        if branch_name in branches:
            return False
    else:
        for branch in branches:
            if branch.get("name") == branch_name:
                return False

    today = datetime.now().strftime("%Y-%m-%d")
    entry = {
        "name": branch_name,
        "path": str(branch_path),
        "profile": profile,
        "description": purpose or "New agent - purpose TBD",
        "email": email,
        "status": "active",
        "created": today,
        "last_active": today,
    }

    # Add entry — handle both dict and list formats
    if isinstance(branches, dict):
        branches[branch_name] = entry
    else:
        branches.append(entry)
    registry["branches"] = branches
    registry["metadata"]["total_branches"] = len(_branches_as_list(branches))

    json_handler.log_operation("registry_updated", data={"branch": branch_name})

    return save_registry(registry_path, registry)


def fix_passport_registry_id(branch_dir: Path, registry_path: Path) -> bool:
    """Update passport.json registry_id if it doesn't match the current registry.

    Call when adopting an existing agent or during sync-registry --fix to repair
    registry_id mismatches caused by registry recreation.

    Args:
        branch_dir: Path to the branch directory (containing .trinity/passport.json)
        registry_path: Path to the project registry (*_REGISTRY.json)

    Returns:
        True if passport was updated, False if already correct or failed.
    """
    passport_path = branch_dir / ".trinity" / "passport.json"
    if not passport_path.exists():
        return False
    if not registry_path.exists():
        return False

    try:
        registry_data = json_handler.read_json(registry_path)
        if registry_data is None:
            return False
        current_id = registry_data.get("metadata", {}).get("id", "")
    except Exception as e:
        logger.warning("[registry] Cannot read registry_id from %s: %s", registry_path.name, e)
        return False

    if not current_id:
        return False

    try:
        passport = json_handler.read_json(passport_path)
        if passport is None:
            return False
        old_id = passport.get("citizenship", {}).get("registry_id", "")
        if old_id == current_id:
            return False  # Already correct, no update needed

        passport.setdefault("citizenship", {})["registry_id"] = current_id
        success = json_handler.write_json(passport_path, passport)
        if success:
            logger.info(
                "[registry] Fixed registry_id for %s: %s → %s",
                branch_dir.name,
                old_id[:8] if old_id else "empty",
                current_id[:8],
            )
        return success
    except Exception as e:
        logger.warning("[registry] Failed to fix registry_id for %s: %s", branch_dir.name, e)
        return False
