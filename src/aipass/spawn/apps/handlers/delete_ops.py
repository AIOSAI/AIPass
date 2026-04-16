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

from aipass.prax.apps.modules.logger import system_logger as logger

from aipass.spawn.apps.handlers.registry import (
    find_registry,
    load_registry,
    save_registry,
    _branches_as_list,
)
from aipass.spawn.apps.handlers.json import json_handler

# Branches that cannot be deleted (critical infrastructure)
_PROTECTED_BRANCHES = {"spawn", "devpulse", "drone"}


# =============================================================================
# PUBLIC API
# =============================================================================


def _resolve_branch_dir(branch_name, registry_path, registry):
    """Find branch entry and directory from registry.

    Returns:
        Tuple of (branch_entry, branch_dir) or (None, None) if not found.
    """
    project_root = registry_path.parent
    for entry in _branches_as_list(registry.get("branches", [])):
        if entry.get("name", "").lower() == branch_name.lower():
            rel_path = entry.get("path", "")
            branch_dir = (project_root / rel_path).resolve() if rel_path else None
            return entry, branch_dir
    return None, None


def _archive_branch(branch_dir, archive_dir):
    """Copy branch to archive directory. Cleans up on failure.

    Returns:
        Error message string, or None on success.
    """
    archive_dir.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copytree(str(branch_dir), str(archive_dir))
        logger.info(f"[delete] Archived to {archive_dir}")
        return None
    except Exception as exc:
        msg = f"Failed to create archive: {exc}"
        logger.error(f"[delete] {msg}")
        _cleanup_partial_archive(archive_dir)
        return msg


def _cleanup_partial_archive(archive_dir):
    """Remove partially-created archive directory."""
    if not archive_dir.exists():
        return
    try:
        shutil.rmtree(str(archive_dir))
    except Exception as cleanup_exc:
        logger.warning("[delete] Failed to clean up partial archive %s: %s", archive_dir, cleanup_exc)


def _remove_from_registry(registry, branch_name, registry_path):
    """Remove branch from registry and save.

    Returns:
        True if registry was updated successfully.
    """
    branches = registry.get("branches", [])
    if isinstance(branches, dict):
        for key in list(branches.keys()):
            if key.lower() == branch_name.lower() or branches[key].get("name", "").lower() == branch_name.lower():
                del branches[key]
        registry["branches"] = branches
    else:
        registry["branches"] = [b for b in branches if b.get("name", "").lower() != branch_name.lower()]
    registry["metadata"]["total_branches"] = len(_branches_as_list(registry["branches"]))
    return save_registry(registry_path, registry)


def _error_result(branch_name, msg, archive_path="", registry_updated=False):
    """Build a failure result dict."""
    return {
        "branch": branch_name,
        "success": False,
        "archive_path": archive_path,
        "registry_updated": registry_updated,
        "error": msg,
    }


def delete_branch(
    branch_name: str,
    confirm: bool = True,
    dry_run: bool = False,
) -> dict:
    """Archive and deregister a branch.

    SAFETY: Cannot delete spawn, devpulse, or drone (protected).
    Archive ALWAYS created before deletion.

    Returns:
        Dict with deletion results.
    """
    # Safety: check protected branches
    if branch_name.lower() in _PROTECTED_BRANCHES:
        msg = f"Cannot delete '{branch_name}' — protected branch ({', '.join(sorted(_PROTECTED_BRANCHES))})"
        logger.warning(f"[delete] {msg}")
        return _error_result(branch_name, msg)

    # 1. Resolve branch path from registry
    registry_path = find_registry()
    project_root = registry_path.parent
    registry = load_registry(registry_path)
    branch_entry, branch_dir = _resolve_branch_dir(branch_name, registry_path, registry)

    if branch_entry is None:
        msg = f"Branch '{branch_name}' not found in registry"
        logger.warning(f"[delete] {msg}")
        return _error_result(branch_name, msg)

    if branch_dir is None or not branch_dir.is_dir():
        msg = f"Branch directory does not exist: {branch_dir}"
        logger.warning(f"[delete] {msg}")
        return _error_result(branch_name, msg)

    # 2. Confirmation prompt
    if confirm and not dry_run:
        try:
            answer = input("Are you sure? (y/N): ").strip().lower()
        except (EOFError, KeyboardInterrupt) as e:
            logger.warning("Delete confirmation prompt interrupted: %s", e)
            answer = ""
        if answer != "y":
            return _error_result(branch_name, "Cancelled by user")

    # 3. Dry run — report and return
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_dir = project_root / ".archive" / "deleted_branches" / f"{branch_name}_{timestamp}"

    if dry_run:
        logger.info(f"[delete] Dry run: would archive {branch_name} to {archive_dir}")
        return {
            "branch": branch_name,
            "success": True,
            "archive_path": str(archive_dir),
            "registry_updated": False,
            "dry_run": True,
        }

    # 4. Create archive
    archive_error = _archive_branch(branch_dir, archive_dir)
    if archive_error:
        return _error_result(branch_name, archive_error)

    # 5. Remove from registry
    registry_updated = _remove_from_registry(registry, branch_name, registry_path)
    if registry_updated:
        logger.info(f"[delete] Removed {branch_name} from registry")
    else:
        logger.error(f"[delete] Failed to update registry after removing {branch_name}")

    # 6. Remove branch directory
    try:
        shutil.rmtree(str(branch_dir))
        logger.info(f"[delete] Removed branch directory: {branch_dir}")
    except Exception as exc:
        msg = f"Archive created but failed to remove directory: {exc}"
        logger.error(f"[delete] {msg}")
        return _error_result(branch_name, msg, str(archive_dir), registry_updated)

    json_handler.log_operation("delete_executed", data={"branch": branch_name})

    return {
        "branch": branch_name,
        "success": True,
        "archive_path": str(archive_dir),
        "registry_updated": registry_updated,
    }
