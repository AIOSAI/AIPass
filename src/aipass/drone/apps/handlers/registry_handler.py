# =================== AIPass ====================
# Name: registry_handler.py
# Description: Handler for registry file operations
# Version: 1.0.0
# Created: 2026-03-09
# Modified: 2026-03-09
# =============================================

"""
Handler for registry file operations.

Handles loading, parsing, and normalizing *_REGISTRY.json files.
All file I/O and data transformation for the registry lives here.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from aipass.prax import logger
from .exceptions import (
    RegistryCorruptError,
    RegistryMismatchError,
    RegistryNotFoundError,
    RegistryPermissionError,
)
from aipass.drone.apps.handlers.json import json_handler


# ---------------------------------------------------------------------------
# Registry path resolution
# ---------------------------------------------------------------------------

_registry_path: Optional[Path] = None


def _first_registry_in(directory: Path) -> Optional[Path]:
    """Return the first *_REGISTRY.json in *directory*, or None.

    When multiple matches exist, the alphabetically-first name wins
    so the result is deterministic across platforms.
    """
    matches = sorted(directory.glob("*_REGISTRY.json"))
    return matches[0] if matches else None


def find_registry() -> Path:
    """Find a *_REGISTRY.json by walking up from this file's location.

    Search order:
    1. Explicitly set path via set_registry_path()
    2. AIPASS_REGISTRY environment variable
    3. Walk up from drone package location
    4. Walk up from cwd
    5. Default: package-relative path

    The first directory that contains any *_REGISTRY.json is treated
    as the project boundary.  If that directory holds more than one
    match, the alphabetically-first file is returned.
    """
    # Walk up from cwd FIRST — this is where the user is working
    cwd = Path.cwd()
    for parent in [cwd] + list(cwd.parents):
        hit = _first_registry_in(parent)
        if hit is not None:
            return hit

    # Walk up from this file (fallback for pip editable installs)
    current = Path(__file__).resolve().parent
    for parent in [current] + list(current.parents):
        hit = _first_registry_in(parent)
        if hit is not None:
            return hit

    # Fallback — use package-relative path; glob there too
    fallback_dir = Path(__file__).resolve().parents[4]
    hit = _first_registry_in(fallback_dir)
    if hit is not None:
        return hit
    # Ultimate fallback: return a conventional name so the caller
    # gets a clear "not found" path in the error message.
    return fallback_dir / "AIPASS_REGISTRY.json"


def get_registry_path() -> Path:
    """Get the current registry path.

    Priority:
    1. Explicitly set path via set_registry_path()
    2. AIPASS_REGISTRY environment variable
    3. Walk-up finder from package location
    """
    global _registry_path

    if _registry_path is not None:
        return _registry_path

    env_path = os.environ.get("AIPASS_REGISTRY")
    if env_path:
        return Path(env_path)

    return find_registry()


def _verify_registry_credential(registry_path: Path, registry_data: Dict[str, Any]) -> None:
    """Verify that the registry matches the caller's passport credential.

    Compares registry metadata.id against the nearest passport's
    citizenship.registry_id.  Only raises when BOTH sides have an ID
    and they don't match — silent pass otherwise.
    """
    try:
        registry_id = registry_data.get("metadata", {}).get("id")
        if not registry_id:
            return

        # Walk up from CWD looking for .trinity/passport.json
        cwd = Path.cwd()
        passport_path = None
        for parent in [cwd] + list(cwd.parents):
            candidate = parent / ".trinity" / "passport.json"
            if candidate.is_file():
                passport_path = candidate
                break

        if passport_path is None:
            return

        with open(passport_path, "r", encoding="utf-8") as f:
            passport = json.load(f)

        passport_id = passport.get("citizenship", {}).get("registry_id")
        if not passport_id:
            return

        if passport_id != registry_id:
            raise RegistryMismatchError(
                f"Registry mismatch: citizen belongs to registry "
                f"'{passport_id}' but found registry '{registry_id}' "
                f"at {registry_path}"
            )
    except RegistryMismatchError:
        raise
    except Exception:
        pass  # Verification should never crash drone


def set_registry_path(path: str | Path) -> None:
    """Set a custom registry path."""
    global _registry_path
    _registry_path = Path(path)


def reset_registry_path() -> None:
    """Reset registry path to default (useful for testing)."""
    global _registry_path
    _registry_path = None


# ---------------------------------------------------------------------------
# Registry loading and querying
# ---------------------------------------------------------------------------

def load_registry() -> Dict[str, Any]:
    """Load the branch registry from disk.

    Returns:
        Registry dictionary with branches (normalized to dict format)

    Raises:
        RegistryNotFoundError: If registry file doesn't exist
        RegistryCorruptError: If registry file is invalid JSON
        RegistryPermissionError: If registry file cannot be read
    """
    registry_path = get_registry_path()

    if not registry_path.exists():
        raise RegistryNotFoundError(
            f"Registry not found at {registry_path}. "
            "Create a *_REGISTRY.json file in your project root."
        )

    try:
        with open(registry_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except PermissionError as e:
        raise RegistryPermissionError(f"Permission denied reading registry: {e}")
    except json.JSONDecodeError as e:
        raise RegistryCorruptError(f"Registry file is corrupted: {e}")
    except Exception as e:
        raise RegistryCorruptError(f"Failed to read registry: {e}")

    if not isinstance(data, dict):
        raise RegistryCorruptError("Registry must be a JSON object")

    if "branches" not in data:
        raise RegistryCorruptError("Registry missing 'branches' field")

    # Normalize: AIPASS_REGISTRY uses list format, convert to dict keyed by name
    branches_raw = data["branches"]
    if isinstance(branches_raw, list):
        branches_dict = {}
        registry_dir = registry_path.parent
        for branch in branches_raw:
            name = branch.get("name", "").lower()
            if not name:
                continue
            # Resolve relative paths against registry location
            raw_path = branch.get("path", "")
            branch_path = Path(raw_path)
            if not branch_path.is_absolute():
                branch_path = (registry_dir / branch_path).resolve()
            entry = dict(branch)
            entry["name"] = name
            entry["path"] = str(branch_path)
            branches_dict[name] = entry
        data["branches"] = branches_dict
    elif not isinstance(branches_raw, dict):
        raise RegistryCorruptError("Registry 'branches' must be a list or dict")

    _verify_registry_credential(registry_path, data)

    branch_count = len(data.get("branches", {}))
    json_handler.log_operation("load_registry", {"path": str(registry_path), "branch_count": branch_count})

    return data


def get_all_branches(
    branch_type: Optional[str] = None,
    status: str = "active",
) -> List[Dict[str, Any]]:
    """Get all branches from the registry, optionally filtered."""
    try:
        registry = load_registry()
    except RegistryNotFoundError:
        return []

    branches = registry.get("branches", {}).values()

    filtered = []
    for branch in branches:
        if status and branch.get("status") != status:
            continue
        if branch_type and branch.get("type") != branch_type:
            continue
        filtered.append(branch)

    return filtered


def get_branch_by_name(name: str) -> Optional[Dict[str, Any]]:
    """Get a single branch by name (case-insensitive)."""
    try:
        registry = load_registry()
    except RegistryNotFoundError:
        return None

    return registry.get("branches", {}).get(name.lower())
