# =================== AIPass ====================
# Name: repair_ops.py
# Description: Repair handler — move branches, update registry paths, clean pollution
# Version: 1.0.0
# Created: 2026-05-15
# Modified: 2026-05-15
# =============================================

"""Repair handler implementation for project structure fixes.

Contains core logic for moving branches to correct locations, updating
registry paths without re-creating entries, and detecting/cleaning init
pollution (duplicate nested directories).
"""

import shutil
import sys
from datetime import datetime
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger

ARCHIVE_EXCLUDE = {".venv", ".git", "__pycache__", ".chroma", "node_modules", ".pytest_cache"}

from aipass.spawn.apps.handlers.registry import (
    find_registry,
    is_protected,
    load_registry,
    save_registry,
    branches_as_list,
)
from aipass.spawn.apps.handlers.json import json_handler


# =============================================================================
# REGISTRY PATH UPDATE
# =============================================================================


def update_registry_path(registry_path, branch_name, new_path):
    """Update a branch's path in the registry without re-creating the entry.

    Preserves creation date, citizen_number, status, and all other fields.
    Uses file locking to prevent concurrent corruption.

    Args:
        registry_path: Path to *_REGISTRY.json
        branch_name: Branch name (case-insensitive match)
        new_path: New relative path for the branch

    Returns:
        True if updated, False if branch not found or error.
    """
    registry_path = Path(registry_path)
    lock_path = registry_path.parent / f".{registry_path.stem}.lock"

    lock_fd = None
    if sys.platform != "win32":
        import fcntl  # noqa: windows_compat — guarded by platform check

        lock_fd = open(lock_path, "w", encoding="utf-8")  # noqa: SIM115
        fcntl.flock(lock_fd, fcntl.LOCK_EX)

    try:
        registry = load_registry(registry_path)
        branches = registry.get("branches", [])
        branch_list = branches_as_list(branches)

        updated = False
        for entry in branch_list:
            if entry.get("name", "").lower() == branch_name.lower():
                old_path = entry.get("path", "")
                entry["path"] = Path(new_path).as_posix()
                entry["last_active"] = datetime.now().strftime("%Y-%m-%d")
                logger.info(
                    "[repair] Updated registry path for %s: %s → %s",
                    branch_name,
                    old_path,
                    new_path,
                )
                updated = True
                break

        if not updated:
            logger.warning("[repair] Branch '%s' not found in registry", branch_name)
            return False

        registry["branches"] = branch_list
        return save_registry(registry_path, registry)
    finally:
        if lock_fd is not None:
            # fcntl is already bound: lock_fd is only ever assigned in the
            # sys.platform != "win32" branch above, which imports it there.
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()


# =============================================================================
# PASSPORT PATH UPDATE
# =============================================================================


def _update_passport_paths(branch_dir, new_relative_path, project_name=None):
    """Update passport.json branch_info paths after a move.

    Args:
        branch_dir: New branch directory location
        new_relative_path: New path relative to project root
        project_name: Project package name (for module path)

    Returns:
        True if updated, False if passport missing or error.
    """
    passport_path = branch_dir / ".trinity" / "passport.json"
    if not passport_path.exists():
        return False

    try:
        passport = json_handler.read_json(passport_path)
        if passport is None:
            return False

        branch_info = passport.get("branch_info", {})
        branch_info["path"] = new_relative_path

        if project_name:
            branch_name = branch_dir.name
            branch_info["module"] = f"{project_name}.{branch_name}"

        passport["branch_info"] = branch_info
        return json_handler.write_json(passport_path, passport)
    except Exception as e:
        logger.error("[repair] Failed to update passport paths: %s", e)
        return False


def _detect_project_package(branch_rel_path):
    """Detect the project package name from the branch's relative path.

    E.g., "src/compass/navigator" → "compass"
    """
    parts = Path(branch_rel_path).parts
    if len(parts) >= 2 and parts[0] == "src":
        return parts[1]
    return None


# =============================================================================
# ARTIFACT RELOCATION
# =============================================================================


def _relocate_chroma(project_root, branch_dir, branches):
    """Move project-root .chroma/ into a branch when only one branch exists.

    Only relocates when .chroma/ exists at project root AND the registry
    has exactly one branch (the one being moved).

    Args:
        project_root: Project root directory
        branch_dir: Target branch directory (already moved)
        branches: List of branch entries from registry

    Returns:
        True if relocated, False otherwise.
    """
    chroma_src = project_root / ".chroma"
    if not chroma_src.is_dir():
        return False

    if len(branches) != 1:
        logger.info("[repair] Skipping .chroma relocation — %d branches (need exactly 1)", len(branches))
        return False

    chroma_dest = branch_dir / ".chroma"
    if chroma_dest.exists():
        logger.warning("[repair] .chroma already exists in branch dir, skipping relocation")
        return False

    try:
        shutil.move(str(chroma_src), str(chroma_dest))
        logger.info("[repair] Relocated .chroma/ into %s", branch_dir.name)
        return True
    except Exception as e:
        logger.error("[repair] Failed to relocate .chroma: %s", e)
        return False


# =============================================================================
# BRANCH MOVE
# =============================================================================


def move_branch(branch_name, new_path, registry_path=None, dry_run=False, relocate_artifacts=False):
    """Move a branch to a new location, updating registry and passport.

    Archive-first: creates backup before any destructive operation.

    Args:
        branch_name: Branch name (looked up in registry)
        new_path: New absolute or relative-to-project-root path
        registry_path: Path to registry (auto-discovered if None)
        dry_run: If True, report what would happen without changes
        relocate_artifacts: If True and project has only 1 branch, move .chroma/ into branch

    Returns:
        Dict with move results.
    """
    if registry_path is None:
        registry_path = find_registry()
    if registry_path is None:
        msg = "No *_REGISTRY.json found above the current directory — nothing to relocate against"
        logger.error("[repair] %s", msg)
        return {"success": False, "error": msg, "moved": False, "registry_updated": False}
    registry_path = Path(registry_path)
    project_root = registry_path.parent

    registry = load_registry(registry_path)
    branches = branches_as_list(registry.get("branches", []))

    entry = None
    for b in branches:
        if b.get("name", "").lower() == branch_name.lower():
            entry = b
            break

    if entry is None:
        return {"success": False, "error": f"Branch '{branch_name}' not found in registry"}

    old_rel_path = entry.get("path", "")
    old_abs_path = (project_root / old_rel_path).resolve()

    new_abs_path = Path(new_path)
    if not new_abs_path.is_absolute():
        new_abs_path = (project_root / new_path).resolve()

    try:
        new_rel_path = new_abs_path.relative_to(project_root).as_posix()
    except ValueError:
        logger.warning("[repair] Path %s is outside project root %s", new_abs_path, project_root)
        return {
            "success": False,
            "error": f"New path {new_abs_path} is outside project root {project_root}",
        }

    if not old_abs_path.exists():
        return {"success": False, "error": f"Source directory does not exist: {old_abs_path}"}

    if new_abs_path.exists():
        return {"success": False, "error": f"Target directory already exists: {new_abs_path}"}

    if dry_run:
        return {
            "success": True,
            "dry_run": True,
            "branch": branch_name,
            "old_path": old_rel_path,
            "new_path": new_rel_path,
            "actions": [
                f"Archive {old_rel_path} to .archive/repair_moves/",
                f"Move {old_rel_path} → {new_rel_path}",
                "Update registry path",
                "Update passport paths",
            ],
        }

    # Archive first
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_dir = project_root / ".archive" / "repair_moves" / f"{branch_name}_{timestamp}"
    archive_dir.parent.mkdir(parents=True, exist_ok=True)

    try:
        shutil.copytree(
            str(old_abs_path),
            str(archive_dir),
            ignore=shutil.ignore_patterns(*ARCHIVE_EXCLUDE),
        )
        logger.info("[repair] Archived %s to %s", branch_name, archive_dir)
    except Exception as e:
        logger.error("[repair] Archive failed for %s: %s", branch_name, e)
        return {"success": False, "error": f"Archive failed: {e}"}

    # Move directory
    new_abs_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.move(str(old_abs_path), str(new_abs_path))
        logger.info("[repair] Moved %s → %s", old_abs_path, new_abs_path)
    except Exception as e:
        logger.error("[repair] Move failed for %s: %s", branch_name, e)
        return {"success": False, "error": f"Move failed: {e}", "archive_path": str(archive_dir)}

    # Update registry
    reg_updated = update_registry_path(registry_path, branch_name, new_rel_path)

    # Update passport
    project_name = _detect_project_package(new_rel_path)
    passport_updated = _update_passport_paths(new_abs_path, new_rel_path, project_name)

    # Relocate .chroma into branch if requested and conditions met
    chroma_relocated = False
    if relocate_artifacts:
        chroma_relocated = _relocate_chroma(project_root, new_abs_path, branches)

    json_handler.log_operation(
        "branch_moved",
        data={"branch": branch_name, "old_path": old_rel_path, "new_path": new_rel_path},
    )

    return {
        "success": True,
        "branch": branch_name,
        "old_path": old_rel_path,
        "new_path": new_rel_path,
        "archive_path": str(archive_dir),
        "registry_updated": reg_updated,
        "passport_updated": passport_updated,
        "chroma_relocated": chroma_relocated,
    }


# =============================================================================
# POLLUTION DETECTION & CLEANUP
# =============================================================================


def _check_nested_pollution(nested_dir, label, project_root, registry_path):
    """Check if a nested duplicate directory is real pollution.

    Returns an issue dict if pollution, or None if the directory is a
    protected branch (active passport, registry owner, infrastructure floor).
    """
    protected, _reason = is_protected(
        nested_dir.name,
        branch_dir=nested_dir,
        registry_path=registry_path,
    )
    if protected:
        return None

    rel = nested_dir.relative_to(project_root).as_posix()
    return {
        "type": "duplicate_nested_dir",
        "path": rel,
        "description": f"Duplicate nested directory: {label}/",
    }


def detect_pollution(project_root):
    """Detect init pollution — duplicate nested directories.

    Init pollution: project_name/project_name/ exists (e.g., compass/compass/).
    Skips directories that are protected branches (active passport, registry
    owner, or infrastructure floor).

    Args:
        project_root: Path to the project root directory

    Returns:
        List of dicts describing pollution issues.
    """
    project_root = Path(project_root)
    issues = []
    project_name = project_root.name

    registry_path = None
    for f in sorted(project_root.glob("*_REGISTRY.json")):
        registry_path = f
        break

    nested = project_root / project_name
    if nested.is_dir():
        issue = _check_nested_pollution(
            nested,
            f"{project_name}/{project_name}",
            project_root,
            registry_path,
        )
        if issue:
            issues.append(issue)

    src_dir = project_root / "src"
    if src_dir.is_dir():
        for child in sorted(src_dir.iterdir()):
            if not child.is_dir() or child.name.startswith(".") or child.name.startswith("__"):
                continue
            nested_dup = child / child.name
            if not nested_dup.is_dir():
                continue
            issue = _check_nested_pollution(
                nested_dup,
                f"src/{child.name}/{child.name}",
                project_root,
                registry_path,
            )
            if issue:
                issues.append(issue)

    return issues


def cleanup_pollution(project_root, dry_run=False):
    """Archive and remove detected pollution directories.

    Args:
        project_root: Path to the project root directory
        dry_run: If True, report without changes

    Returns:
        Dict with cleanup results.
    """
    project_root = Path(project_root)
    issues = detect_pollution(project_root)

    if not issues:
        return {"success": True, "issues_found": 0, "cleaned": []}

    if dry_run:
        return {
            "success": True,
            "dry_run": True,
            "issues_found": len(issues),
            "issues": issues,
        }

    cleaned = []
    errors = []
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    for issue in issues:
        pollution_path = project_root / issue["path"]
        if not pollution_path.exists():
            continue

        archive_dir = project_root / ".archive" / "pollution" / f"{pollution_path.name}_{timestamp}"
        archive_dir.parent.mkdir(parents=True, exist_ok=True)

        try:
            shutil.copytree(
                str(pollution_path),
                str(archive_dir),
                ignore=shutil.ignore_patterns(*ARCHIVE_EXCLUDE),
            )
            shutil.rmtree(str(pollution_path))
            logger.info("[repair] Cleaned pollution: %s (archived to %s)", issue["path"], archive_dir)
            cleaned.append({"path": issue["path"], "archive": str(archive_dir)})
        except Exception as e:
            logger.error("[repair] Failed to clean pollution at %s: %s", issue["path"], e)
            errors.append({"path": issue["path"], "error": str(e)})

    json_handler.log_operation(
        "pollution_cleaned",
        data={"project": project_root.name, "cleaned": len(cleaned)},
    )

    return {
        "success": len(errors) == 0,
        "issues_found": len(issues),
        "cleaned": cleaned,
        "errors": errors,
    }


# =============================================================================
# PROJECT SCAN
# =============================================================================


def repair_project(project_path, dry_run=False):
    """Scan a project for structural issues and report findings.

    Checks:
    1. Init pollution (duplicate nested dirs)
    2. Registry path mismatches (registered path doesn't exist on disk)

    Args:
        project_path: Path to the project root
        dry_run: If True, report only (same as default — scan is always read-only)

    Returns:
        Dict with scan results.
    """
    project_path = Path(project_path).resolve()
    if not project_path.is_dir():
        return {"success": False, "error": f"Project path does not exist: {project_path}"}

    registry_path = None
    for f in sorted(project_path.glob("*_REGISTRY.json")):
        registry_path = f
        break

    if registry_path is None:
        return {"success": False, "error": f"No *_REGISTRY.json found in {project_path}"}

    results = {
        "project": project_path.name,
        "registry": registry_path.name,
        "dry_run": dry_run,
        "pollution": detect_pollution(project_path),
        "registry_mismatches": [],
        "actions_taken": [],
    }

    registry = load_registry(registry_path)
    branches = branches_as_list(registry.get("branches", []))

    for entry in branches:
        rel_path = entry.get("path", "")
        abs_path = (project_path / rel_path).resolve()

        if not abs_path.exists():
            results["registry_mismatches"].append(
                {
                    "branch": entry.get("name", "?"),
                    "registered_path": rel_path,
                    "issue": "Directory missing — registered path does not exist",
                }
            )

    total_issues = len(results["pollution"]) + len(results["registry_mismatches"])
    results["total_issues"] = total_issues
    results["success"] = True

    return results
