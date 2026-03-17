# =================== AIPass ====================
# Name: delete_ops.py
# Description: Delete handler — implementation logic for branch deletion
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-03-10
# =============================================

"""Delete handler implementation for branch lifecycle management.

Contains the core deletion logic: resolving branch paths, archiving branch
directories, removing from registry, and safety checks for protected branches.
"""

import shutil
from datetime import datetime
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger

from aipass.spawn.apps.handlers.registry import (
    find_registry,
    load_registry,
    save_registry,
    _branches_as_list,
)
from aipass.spawn.apps.handlers.json import json_handler

# Repo root — resolved from spawn package location
_REPO_ROOT = Path(__file__).parents[5]  # handlers/apps/spawn/aipass/src/AIPass

# Branches that cannot be deleted (critical infrastructure)
_PROTECTED_BRANCHES = {"spawn", "devpulse", "drone"}


# =============================================================================
# PUBLIC API
# =============================================================================

def delete_branch(
    branch_name: str,
    confirm: bool = True,
    dry_run: bool = False,
) -> dict:
    """Archive and deregister a branch.

    Workflow:
    1. Resolve branch path from AIPASS_REGISTRY.json
    2. Verify branch exists on filesystem
    3. If confirm=True -> print what will happen, prompt "Are you sure? (y/N)"
    4. If dry_run -> print summary, return
    5. Create archive directory: {repo_root}/.archive/deleted_branches/{name}_{timestamp}/
    6. Copy entire branch directory to archive (shutil.copytree)
    7. Remove branch from AIPASS_REGISTRY.json
    8. Remove branch directory (shutil.rmtree)
    9. Log and return summary

    SAFETY:
    - Cannot delete spawn (self-protection)
    - Cannot delete devpulse (orchestration hub protection)
    - Cannot delete drone (routing infrastructure protection)
    - Archive ALWAYS created before deletion

    Returns:
        Dict with deletion results.
    """
    # Safety: check protected branches
    if branch_name.lower() in _PROTECTED_BRANCHES:
        msg = f"Cannot delete '{branch_name}' — protected branch ({', '.join(sorted(_PROTECTED_BRANCHES))})"
        logger.warning(f"[delete] {msg}")
        return {
            "branch": branch_name,
            "success": False,
            "archive_path": "",
            "registry_updated": False,
            "error": msg,
        }

    # 1. Resolve branch path from registry
    registry_path = find_registry()
    registry = load_registry(registry_path)
    branch_entry = None
    branch_dir = None

    for entry in _branches_as_list(registry.get("branches", [])):
        if entry.get("name", "").lower() == branch_name.lower():
            branch_entry = entry
            rel_path = entry.get("path", "")
            if rel_path:
                branch_dir = (_REPO_ROOT / rel_path).resolve()
            break

    if branch_entry is None:
        msg = f"Branch '{branch_name}' not found in registry"
        logger.warning(f"[delete] {msg}")
        return {
            "branch": branch_name,
            "success": False,
            "archive_path": "",
            "registry_updated": False,
            "error": msg,
        }

    # 2. Verify branch exists on filesystem
    if branch_dir is None or not branch_dir.is_dir():
        msg = f"Branch directory does not exist: {branch_dir}"
        logger.warning(f"[delete] {msg}")
        return {
            "branch": branch_name,
            "success": False,
            "archive_path": "",
            "registry_updated": False,
            "error": msg,
        }

    # 3. Confirmation prompt
    if confirm and not dry_run:
        try:
            answer = input("Are you sure? (y/N): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = ""
        if answer != "y":
            return {
                "branch": branch_name,
                "success": False,
                "archive_path": "",
                "registry_updated": False,
                "error": "Cancelled by user",
            }

    # 4. Dry run — report and return
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_dir = _REPO_ROOT / ".archive" / "deleted_branches" / f"{branch_name}_{timestamp}"

    if dry_run:
        logger.info(f"[delete] Dry run: would archive {branch_name} to {archive_dir}")
        return {
            "branch": branch_name,
            "success": True,
            "archive_path": str(archive_dir),
            "registry_updated": False,
            "dry_run": True,
        }

    # 5. Create archive
    archive_dir.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copytree(str(branch_dir), str(archive_dir))
        logger.info(f"[delete] Archived {branch_name} to {archive_dir}")
    except Exception as exc:
        msg = f"Failed to create archive: {exc}"
        logger.error(f"[delete] {msg}")
        return {
            "branch": branch_name,
            "success": False,
            "archive_path": "",
            "registry_updated": False,
            "error": msg,
        }

    # 6. Remove from registry
    branches = registry.get("branches", [])
    if isinstance(branches, dict):
        # Dict format: remove by key (try both cases)
        for key in list(branches.keys()):
            if key.lower() == branch_name.lower() or branches[key].get("name", "").lower() == branch_name.lower():
                del branches[key]
        registry["branches"] = branches
    else:
        registry["branches"] = [
            b for b in branches
            if b.get("name", "").lower() != branch_name.lower()
        ]
    registry["metadata"]["total_branches"] = len(_branches_as_list(registry["branches"]))
    registry_updated = save_registry(registry_path, registry)

    if registry_updated:
        logger.info(f"[delete] Removed {branch_name} from registry")
    else:
        logger.error(f"[delete] Failed to update registry after removing {branch_name}")

    # 7. Remove branch directory
    try:
        shutil.rmtree(str(branch_dir))
        logger.info(f"[delete] Removed branch directory: {branch_dir}")
    except Exception as exc:
        msg = f"Archive created but failed to remove directory: {exc}"
        logger.error(f"[delete] {msg}")
        return {
            "branch": branch_name,
            "success": False,
            "archive_path": str(archive_dir),
            "registry_updated": registry_updated,
            "error": msg,
        }

    json_handler.log_operation("delete_executed", data={"branch": branch_name})

    return {
        "branch": branch_name,
        "success": True,
        "archive_path": str(archive_dir),
        "registry_updated": registry_updated,
    }
