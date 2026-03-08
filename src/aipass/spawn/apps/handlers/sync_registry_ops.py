# =================== META ====================
# Name: sync_registry_ops.py
# Description: Registry sync handler — implementation logic for registry repair
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-03-07
# =============================================

"""Registry synchronization handler for branch lifecycle management.

Contains the core sync logic: scanning the filesystem, comparing with
AIPASS_REGISTRY.json, detecting stale/unregistered branches, and
optionally repairing mismatches.
"""

import json
from datetime import datetime
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger

from aipass.spawn.apps.handlers.registry import (
    find_registry,
    load_registry,
    save_registry,
    _branches_as_list,
)

# Repo root — resolved from spawn package location
_REPO_ROOT = Path(__file__).parents[5]  # handlers/apps/spawn/aipass/src/AIPass


# =============================================================================
# PUBLIC API
# =============================================================================

def sync_registry(fix: bool = False) -> dict:
    """Synchronize AIPASS_REGISTRY.json with filesystem.

    Workflow:
    1. Load AIPASS_REGISTRY.json
    2. Scan src/aipass/ for directories that have .trinity/passport.json (branch marker)
    3. Compare:
       - Stale entries: registered in JSON but directory missing or no passport
       - Unregistered: directory exists with passport but not in JSON
    4. Report findings
    5. If fix=True:
       - Remove stale entries
       - Add unregistered branches with basic metadata
       - Save updated registry

    Returns:
        Dict with sync results.
    """
    # 1. Load registry
    registry_path = find_registry()
    registry = load_registry(registry_path)
    branches = _branches_as_list(registry.get("branches", []))

    # Build lookup of registered branch names (lowercase) -> entry
    registered: dict[str, dict] = {}
    for entry in branches:
        name = entry.get("name", "").lower()
        if name:
            registered[name] = entry

    # 2. Scan filesystem for branch directories with .trinity/passport.json
    src_aipass = _REPO_ROOT / "src" / "aipass"
    filesystem_branches: dict[str, Path] = {}

    if src_aipass.is_dir():
        for child in sorted(src_aipass.iterdir()):
            if child.is_dir() and not child.name.startswith(".") and not child.name.startswith("__"):
                passport = child / ".trinity" / "passport.json"
                if passport.exists():
                    filesystem_branches[child.name.lower()] = child

    # 3. Compare
    stale: list[str] = []
    unregistered_list: list[str] = []
    healthy: list[str] = []

    # Check registered branches against filesystem
    for name, entry in registered.items():
        rel_path = entry.get("path", "")
        branch_dir = (_REPO_ROOT / rel_path).resolve() if rel_path else None

        if branch_dir and branch_dir.is_dir():
            passport = branch_dir / ".trinity" / "passport.json"
            if passport.exists():
                healthy.append(name)
            else:
                # Directory exists but no passport — treat as stale
                stale.append(name)
        else:
            stale.append(name)

    # Check filesystem branches against registry
    for name, path in filesystem_branches.items():
        if name not in registered:
            unregistered_list.append(name)

    logger.info(
        f"[sync-registry] Scan complete: "
        f"healthy={len(healthy)}, stale={len(stale)}, unregistered={len(unregistered_list)}"
    )

    # 4/5. Fix if requested
    fixed = False
    if fix and (stale or unregistered_list):
        # Remove stale entries
        raw_branches = registry.get("branches", [])
        if stale:
            if isinstance(raw_branches, dict):
                for key in list(raw_branches.keys()):
                    entry_name = raw_branches[key].get("name", "").lower() if isinstance(raw_branches[key], dict) else key.lower()
                    if entry_name in stale or key.lower() in stale:
                        del raw_branches[key]
            else:
                raw_branches = [
                    b for b in raw_branches
                    if b.get("name", "").lower() not in stale
                ]
            registry["branches"] = raw_branches
            for s in stale:
                logger.info(f"[sync-registry] Removed stale entry: {s}")

        # Add unregistered branches
        today = datetime.now().strftime("%Y-%m-%d")
        for name in unregistered_list:
            branch_path = filesystem_branches[name]
            rel_path = str(branch_path.relative_to(_REPO_ROOT))

            entry = {
                "name": name.upper(),
                "path": rel_path,
                "profile": "library",
                "description": f"Auto-registered branch",
                "email": f"@{name}",
                "status": "active",
                "created": today,
                "last_active": today,
            }
            raw_branches = registry["branches"]
            if isinstance(raw_branches, dict):
                raw_branches[name.upper()] = entry
            else:
                raw_branches.append(entry)
            logger.info(f"[sync-registry] Added unregistered branch: {name}")

        # Update total and save
        registry["metadata"]["total_branches"] = len(_branches_as_list(registry["branches"]))
        save_result = save_registry(registry_path, registry)
        fixed = save_result

        if fixed:
            logger.info("[sync-registry] Registry updated successfully")
        else:
            logger.error("[sync-registry] Failed to save updated registry")

    return {
        "stale": stale,
        "unregistered": unregistered_list,
        "healthy": healthy,
        "fixed": fixed,
    }
