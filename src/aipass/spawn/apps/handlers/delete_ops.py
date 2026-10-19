# =================== AIPass ====================
# Name: delete_ops.py
# Description: Delete handler — implementation logic for branch deletion
# Version: 1.2.0
# Created: 2026-03-07
# Modified: 2026-10-18
# =============================================

"""Delete handler implementation for branch lifecycle management."""

import json
import shutil
from datetime import datetime

from aipass.prax.apps.modules.logger import system_logger as logger

from aipass.spawn.apps.handlers.registry import (
    find_registry,
    is_protected,
    load_registry,
    save_registry,
    branches_as_list,
)
from aipass.spawn.apps.handlers.atomic_write import atomic_write_text
from aipass.spawn.apps.handlers.repair_ops import ARCHIVE_EXCLUDE
from aipass.spawn.apps.handlers.json import json_handler


def _resolve_branch_dir(branch_name, registry_path, registry):
    """Find branch entry and directory from registry; (None, None) if not found."""
    project_root = registry_path.parent
    for entry in branches_as_list(registry.get("branches", [])):
        if entry.get("name", "").lower() == branch_name.lower():
            rel_path = entry.get("path", "")
            branch_dir = (project_root / rel_path).resolve() if rel_path else None
            return entry, branch_dir
    return None, None


def _archive_branch(branch_dir, archive_dir):
    """Copy branch to archive directory, cleaning up on failure. Returns error text, None on success."""
    archive_dir.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copytree(str(branch_dir), str(archive_dir), ignore=shutil.ignore_patterns(*ARCHIVE_EXCLUDE))
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


def _unregister_archived_passport(archive_dir):
    """Set citizenship.registered false in the archived passport; error text, None on success or no passport."""
    passport_path = archive_dir / ".trinity" / "passport.json"
    if not passport_path.is_file():
        return None
    try:
        passport = json.loads(passport_path.read_text(encoding="utf-8"))
        passport.setdefault("citizenship", {})["registered"] = False
        atomic_write_text(passport_path, json.dumps(passport, indent=2, ensure_ascii=False) + "\n")
    except (OSError, ValueError, AttributeError) as exc:
        msg = f"Failed to unregister the archived passport {passport_path}: {exc}"
        logger.error(f"[delete] {msg}")
        return msg
    return None


def _remove_from_registry(registry, branch_name, registry_path):
    """Remove branch from registry and save; True if the save succeeded."""
    branches = registry.get("branches", [])
    if isinstance(branches, dict):
        for key in list(branches.keys()):
            if key.lower() == branch_name.lower() or branches[key].get("name", "").lower() == branch_name.lower():
                del branches[key]
        registry["branches"] = branches
    else:
        registry["branches"] = [b for b in branches if b.get("name", "").lower() != branch_name.lower()]
    registry["metadata"]["total_branches"] = len(branches_as_list(registry["branches"]))
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
    retire: bool = False,
) -> dict:
    """Archive and deregister a branch; the archive is always written before removal.

    retire=True lets an active citizen through and archives its passport with registered false;
    the floor and the registry owner stay refused.
    """
    registry_path = find_registry()
    if registry_path is None:
        # Without a registry the protection check cannot run, so the delete must not.
        msg = "Cannot delete: no *_REGISTRY.json found above the current directory"
        logger.error("[delete] %s", msg)
        return _error_result(branch_name, msg)

    protected, reason = is_protected(branch_name, registry_path=registry_path, count_passport=not retire)
    if protected:
        msg = f"Cannot delete '{branch_name}' — protected ({reason})"
        if not is_protected(branch_name, registry_path=registry_path, count_passport=False)[0]:
            msg += "; retire it with: drone @spawn delete @" + branch_name + " --retire"
        logger.warning(f"[delete] {msg}")
        return _error_result(branch_name, msg)
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

    # Protection is by name; this guards by location before the archive and removal see the path.
    root = project_root.resolve()
    if branch_dir == root or not branch_dir.is_relative_to(root):
        msg = f"Branch directory {branch_dir} is outside the project {root} - refusing to archive or remove it"
        logger.error(f"[delete] {msg}")
        return _error_result(branch_name, msg)

    if confirm and not dry_run:
        try:
            answer = input("Are you sure? (y/N): ").strip().lower()
        except (EOFError, KeyboardInterrupt) as e:
            logger.warning("Delete confirmation prompt interrupted: %s", e)
            answer = ""
        if answer != "y":
            return _error_result(branch_name, "Cancelled by user")

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
            "retired": retire,
        }

    archive_error = _archive_branch(branch_dir, archive_dir)
    if archive_error:
        return _error_result(branch_name, archive_error)

    # The archived copy is flipped, never the live tree: a failure here leaves the branch registered and whole.
    if retire:
        unregister_error = _unregister_archived_passport(archive_dir)
        if unregister_error:
            _cleanup_partial_archive(archive_dir)
            return _error_result(branch_name, unregister_error)

    registry_updated = _remove_from_registry(registry, branch_name, registry_path)
    if registry_updated:
        logger.info(f"[delete] Removed {branch_name} from registry")
    else:
        logger.error(f"[delete] Failed to update registry after removing {branch_name}")

    try:
        shutil.rmtree(str(branch_dir))
        logger.info(f"[delete] Removed branch directory: {branch_dir}")
    except Exception as exc:
        msg = f"Archive created but failed to remove directory: {exc}"
        logger.error(f"[delete] {msg}")
        return _error_result(branch_name, msg, str(archive_dir), registry_updated)

    # The archive is now the only copy, so whether .trinity went with it is logged here.
    archived_trinity = (
        sorted(p.name for p in (archive_dir / ".trinity").glob("*")) if (archive_dir / ".trinity").is_dir() else []
    )
    logger.info(
        "[spawn] RETIRED %s — archived to %s (trinity carried: %s)",
        branch_name,
        archive_dir,
        ", ".join(archived_trinity) if archived_trinity else "NONE",
    )
    json_handler.log_operation(
        "delete_executed",
        data={"branch": branch_name, "archive": str(archive_dir), "trinity_carried": archived_trinity},
    )

    return {
        "branch": branch_name,
        "success": True,
        "archive_path": str(archive_dir),
        "registry_updated": registry_updated,
        "retired": retire,
    }
