# =================== AIPass ====================
# Name: branch_detection.py
# Description: Branch Auto-Detection Handler
# Version: 1.0.0
# Created: 2025-11-18
# Modified: 2025-11-18
# =============================================

"""
Branch Auto-Detection Handler

Detects which branch is calling AI_MAIL based on PWD/CWD.
Walks up directory tree to find branch root (has .trinity/passport.json).
"""

# =============================================
# IMPORTS
# =============================================
import os
import json
from pathlib import Path
from typing import Dict

from aipass.prax.apps.modules.logger import system_logger as logger

# =============================================
# CONSTANTS
# =============================================
def _find_repo_root() -> Path:
    """Walk up from this file to find AIPASS_REGISTRY.json (repo root)."""
    current = Path(__file__).resolve().parent
    for parent in [current] + list(current.parents):
        if (parent / "AIPASS_REGISTRY.json").exists():
            return parent
    return Path.cwd()


BRANCH_REGISTRY_PATH = _find_repo_root() / "AIPASS_REGISTRY.json"


def _get_branches_list(registry: dict) -> list:
    """Normalize branches from registry to a list of dicts.

    Handles both formats:
    - List: [{"name": "DEVPULSE", ...}, ...]
    - Dict: {"devpulse": {"name": "devpulse", ...}, ...}
    """
    branches = registry.get("branches", [])
    if isinstance(branches, dict):
        return list(branches.values())
    return branches


# =============================================
# BRANCH DETECTION FUNCTIONS
# =============================================

def detect_branch_from_pwd() -> Dict | None:
    """
    Detect which branch is calling based on current working directory.

    Walks up directory tree from PWD to find branch root (directory with .trinity/passport.json).
    Then looks up branch info in BRANCH_REGISTRY.json.

    Returns:
        Dict with branch info if detected:
        {
            "name": "SEED",
            "path": "src/aipass/seedgo",
            "email": "@seed",
            "display_name": "Seed (Standards Branch)",
            ...
        }
        None if no branch detected
    """
    try:
        # Primary: use explicit branch name passed by drone (works in Docker + local)
        caller_branch = os.environ.get("AIPASS_CALLER_BRANCH")
        if caller_branch:
            branch_info = _lookup_branch_by_name(caller_branch)
            if branch_info:
                return branch_info

        # Fallback: use caller's CWD for path-based detection (local only)
        caller_cwd = os.environ.get("AIPASS_CALLER_CWD")
        cwd = Path(caller_cwd) if caller_cwd else Path.cwd()

        # Find branch root
        branch_root = find_branch_root(cwd)
        if not branch_root:
            return None

        # Get branch info from registry
        branch_info = get_branch_info_from_registry(branch_root)
        if not branch_info:
            return None

        return branch_info

    except Exception as e:
        logger.warning("[identity] detect_branch_from_pwd() failed: %s", e)
        return None


def _lookup_branch_by_name(branch_name: str) -> Dict | None:
    """
    Look up branch in the registry by name (case-insensitive).

    Handles both registry formats:
    - List format: {"branches": [{"name": "DEVPULSE", ...}, ...]}
    - Dict format: {"branches": {"devpulse": {"name": "devpulse", ...}, ...}}

    Args:
        branch_name: Branch name (e.g., "DEVPULSE", "devpulse")

    Returns:
        Dict with branch info from registry, or None if not found
    """
    if not BRANCH_REGISTRY_PATH.exists():
        return None

    try:
        with open(BRANCH_REGISTRY_PATH, 'r', encoding='utf-8') as f:
            registry = json.load(f)

        name_lower = branch_name.lower()
        for branch in _get_branches_list(registry):
            if branch.get("name", "").lower() == name_lower:
                return branch

        return None

    except Exception as e:
        logger.warning("[identity] _lookup_branch_by_name(%s) failed: %s", branch_name, e)
        return None


def find_branch_root(start_path: Path) -> Path | None:
    """
    Walk up directory tree to find branch root.

    Branch root = directory containing .trinity/passport.json.
    Example: src/aipass/seedgo/ contains .trinity/passport.json

    Args:
        start_path: Directory to start searching from (usually PWD)

    Returns:
        Path to branch root directory, or None if not found
    """
    current = start_path.resolve()

    # Walk up directory tree (max 10 levels to prevent infinite loop)
    for _ in range(10):
        # Check for .trinity/passport.json (AIPass identity pattern)
        if (current / ".trinity" / "passport.json").exists():
            return current

        # Move up one level
        parent = current.parent
        if parent == current:  # Reached filesystem root
            break
        current = parent

    return None


def get_branch_info_from_registry(branch_path: Path) -> Dict | None:
    """
    Look up branch information in BRANCH_REGISTRY.json by path.

    Args:
        branch_path: Path to branch directory

    Returns:
        Dict with branch info from registry, or None if not found
    """
    if not BRANCH_REGISTRY_PATH.exists():
        return None

    try:
        with open(BRANCH_REGISTRY_PATH, 'r', encoding='utf-8') as f:
            registry = json.load(f)

        registry_dir = BRANCH_REGISTRY_PATH.parent
        branch_path_resolved = branch_path.resolve()

        # Search registry for matching path
        for branch in _get_branches_list(registry):
            reg_path = Path(branch["path"])
            # Resolve relative paths against registry location, not CWD
            if not reg_path.is_absolute():
                reg_path = (registry_dir / reg_path).resolve()
            else:
                reg_path = reg_path.resolve()
            if reg_path == branch_path_resolved:
                return branch

        return None

    except Exception as e:
        logger.warning("[identity] get_branch_info_from_registry(%s) failed: %s", branch_path, e)
        return None


def get_branch_display_name(branch_info: Dict) -> str:
    """
    Generate display name for branch from registry info.

    Args:
        branch_info: Branch dict from registry

    Returns:
        Display name string (e.g., "Seed (Standards Branch)")
    """
    name = branch_info.get("name", "Unknown")
    description = branch_info.get("description", "")

    if description and description != "New branch - purpose TBD":
        # Use description as context
        return f"{name.title()} ({description})"
    else:
        # Just use name
        return name.title()


def get_local_config_path(branch_path: Path, branch_name: str) -> Path:
    """
    Get path to local user_config.json for a branch.

    Args:
        branch_path: Path to branch directory
        branch_name: Branch name (e.g., "SEED", "DRONE")

    Returns:
        Path to local config file ([branch_name]_json/user_config.json)
    """
    branch_name_lower = branch_name.lower()
    return branch_path / f"{branch_name_lower}_json" / "user_config.json"


if __name__ == "__main__":
    from aipass.cli.apps.modules import console

    console.print("\n" + "="*70)
    console.print("BRANCH AUTO-DETECTION HANDLER")
    console.print("="*70)
    console.print("\nPURPOSE:")
    console.print("  Detects which branch is calling AI_MAIL based on PWD/CWD")
    console.print("  Walks up directory tree to find branch root")
    console.print()
    console.print("FUNCTIONS PROVIDED:")
    console.print("  - detect_branch_from_pwd() -> Dict | None")
    console.print("  - find_branch_root(start_path) -> Path | None")
    console.print("  - get_branch_info_from_registry(branch_path) -> Dict | None")
    console.print("  - get_branch_display_name(branch_info) -> str")
    console.print("  - get_local_config_path(branch_path) -> Path")
    console.print()
    console.print("HANDLER CHARACTERISTICS:")
    console.print("  ✓ Independent - no module dependencies")
    console.print("  ✓ Can import Prax (service provider)")
    console.print("  ✓ Pure business logic")
    console.print("  ✗ CANNOT import parent modules")
    console.print()
    console.print("DETECTION FLOW:")
    console.print("  1. Get current working directory (PWD)")
    console.print("  2. Walk up tree to find .trinity/passport.json")
    console.print("  3. Look up branch path in BRANCH_REGISTRY.json")
    console.print("  4. Return branch info (name, email, path, etc.)")
    console.print()
    console.print("="*70 + "\n")
