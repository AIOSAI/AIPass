# =================== META ====================
# Name: registry.py
# Description: AIPASS_REGISTRY.json CRUD operations
# Version: 1.0.0
# Created: 2026-03-05
# Modified: 2026-03-07
# =============================================

"""AIPASS_REGISTRY.json CRUD operations."""

import json
import os
from datetime import datetime
from pathlib import Path


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


def find_registry(start_path=None):
    """
    Find AIPASS_REGISTRY.json — consistent with drone's resolution.

    Priority:
    1. AIPASS_REGISTRY environment variable
    2. Project root (directory with pyproject.toml or .git) — walk up from __file__
    3. Project root — walk up from start_path/cwd
    4. Walk up from __file__ for any existing registry
    5. Last resort: cwd

    Args:
        start_path: Directory to start searching from

    Returns:
        Path to AIPASS_REGISTRY.json
    """
    # Check environment variable first (same as drone's config.py)
    env_path = os.environ.get("AIPASS_REGISTRY")
    if env_path:
        return Path(env_path)

    # Walk up from package location — find project root first
    pkg_dir = Path(__file__).resolve().parent
    for parent in [pkg_dir] + list(pkg_dir.parents):
        if (parent / "pyproject.toml").exists() or (parent / ".git").exists():
            candidate = parent / "AIPASS_REGISTRY.json"
            if candidate.exists():
                return candidate
            # Project root found but no registry — create here
            return candidate

    # Walk up from start_path or cwd
    current = Path(start_path).resolve() if start_path else Path.cwd()
    for parent in [current] + list(current.parents):
        if (parent / "pyproject.toml").exists() or (parent / ".git").exists():
            return parent / "AIPASS_REGISTRY.json"

    # Fallback: any existing registry walking up from package
    for parent in [pkg_dir] + list(pkg_dir.parents):
        candidate = parent / "AIPASS_REGISTRY.json"
        if candidate.exists():
            return candidate

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

    try:
        data = json.loads(registry_path.read_text(encoding="utf-8"))
        return data
    except (json.JSONDecodeError, IOError):
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
        data["branches"] = sorted(
            branch_list, key=lambda b: b.get("name", "")
        )

    try:
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        registry_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return True
    except (IOError, TypeError):
        return False


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

    return save_registry(registry_path, registry)
