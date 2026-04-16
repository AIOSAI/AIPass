# =================== AIPass ====================
# Name: reconcile.py
# Description: Branch state reconciliation — filesystem vs metadata
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-03-10
# =============================================

"""Branch state reconciliation handler.

Compares what .branch_meta.json says should exist vs what actually exists
on the filesystem. Identifies missing files, untracked files, hash
mismatches, and missing directories.
"""

import hashlib
from pathlib import Path
from typing import Any

from aipass.prax.apps.modules.logger import system_logger as logger

# Directories/files to skip during filesystem scans
_SKIP_NAMES = {"__pycache__", ".git", ".branch_meta.json", ".template_registry.json"}


# =============================================================================
# HELPERS
# =============================================================================


def _compute_hash(file_path: Path) -> str:
    """Compute SHA-256 hash, first 12 hex chars."""
    try:
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()[:12]
    except (IOError, PermissionError) as e:
        logger.warning("Failed to compute hash for %s: %s", file_path, e)
        return ""


def _should_skip(name: str) -> bool:
    """Check if a file or directory name should be skipped during scan."""
    return name in _SKIP_NAMES


# =============================================================================
# RECONCILIATION
# =============================================================================


def reconcile_branch_state(
    branch_dir: Path,
    branch_meta: dict,
    trace: bool = False,
) -> dict:
    """Reconcile branch metadata with actual filesystem state.

    Compares tracked files/directories in .branch_meta.json against what
    exists on disk within the branch directory.

    Args:
        branch_dir: Path to the branch directory.
        branch_meta: Loaded branch metadata dict (from .branch_meta.json).
        trace: If True, enable verbose logging via prax.

    Returns:
        Dict with reconciliation results::

            {
                "missing_files": [{"file_id": ..., "path": ..., "template_name": ...}, ...],
                "untracked_files": [{"path": ..., "name": ...}, ...],
                "hash_mismatches": [{"file_id": ..., "path": ..., "tracked_hash": ..., "current_hash": ...}, ...],
                "missing_dirs": [{"dir_id": ..., "path": ..., "template_name": ...}, ...],
                "needs_update": bool,
            }
    """
    branch_dir = Path(branch_dir)
    file_tracking = branch_meta.get("file_tracking", {})
    dir_tracking = branch_meta.get("directory_tracking", {})

    missing_files: list[dict[str, Any]] = []
    untracked_files: list[dict[str, Any]] = []
    hash_mismatches: list[dict[str, Any]] = []
    missing_dirs: list[dict[str, Any]] = []

    if trace:
        logger.info(f"[reconcile] Starting reconciliation for {branch_dir.name}")
        logger.info(f"[reconcile] Tracked files: {len(file_tracking)}, dirs: {len(dir_tracking)}")

    # -------------------------------------------------------------------------
    # Check 1: Tracked files — do they still exist on disk?
    # -------------------------------------------------------------------------
    for file_id, file_info in file_tracking.items():
        tracked_path = file_info.get("current_path", "")
        if not tracked_path:
            continue

        full_path = branch_dir / tracked_path
        if not full_path.exists():
            entry = {
                "file_id": file_id,
                "path": tracked_path,
                "template_name": file_info.get("template_name", ""),
            }
            missing_files.append(entry)
            if trace:
                logger.info(f"[reconcile] MISSING: {file_id} -> {tracked_path}")
        elif full_path.is_file():
            # Check hash mismatch
            tracked_hash = file_info.get("content_hash", "")
            if tracked_hash:
                current_hash = _compute_hash(full_path)
                if current_hash and current_hash != tracked_hash:
                    entry = {
                        "file_id": file_id,
                        "path": tracked_path,
                        "tracked_hash": tracked_hash,
                        "current_hash": current_hash,
                    }
                    hash_mismatches.append(entry)
                    if trace:
                        logger.info(
                            f"[reconcile] HASH MISMATCH: {file_id} tracked={tracked_hash} current={current_hash}"
                        )

    # -------------------------------------------------------------------------
    # Check 2: Tracked directories — do they still exist?
    # -------------------------------------------------------------------------
    for dir_id, dir_info in dir_tracking.items():
        tracked_path = dir_info.get("current_path", "")
        if not tracked_path:
            continue

        full_path = branch_dir / tracked_path
        if not full_path.is_dir():
            entry = {
                "dir_id": dir_id,
                "path": tracked_path,
                "template_name": dir_info.get("template_name", ""),
            }
            missing_dirs.append(entry)
            if trace:
                logger.info(f"[reconcile] MISSING DIR: {dir_id} -> {tracked_path}")

    # -------------------------------------------------------------------------
    # Check 3: Untracked files — on disk but not in metadata
    # Only check within template-managed directories (tracked dir paths).
    # -------------------------------------------------------------------------
    tracked_paths = {info.get("current_path", "") for info in file_tracking.values()}
    tracked_dir_paths = {info.get("current_path", "") for info in dir_tracking.values()}

    # Scan within tracked directories for untracked files
    for dir_path_str in tracked_dir_paths:
        if not dir_path_str:
            continue
        scan_dir = branch_dir / dir_path_str
        if not scan_dir.is_dir():
            continue

        try:
            for item in scan_dir.iterdir():
                if _should_skip(item.name):
                    continue
                if not item.is_file():
                    continue

                rel_path = str(item.relative_to(branch_dir))
                if rel_path not in tracked_paths:
                    entry = {
                        "path": rel_path,
                        "name": item.name,
                    }
                    untracked_files.append(entry)
                    if trace:
                        logger.info(f"[reconcile] UNTRACKED: {rel_path}")
        except (PermissionError, OSError) as exc:
            if trace:
                logger.warning(f"[reconcile] Scan error in {dir_path_str}: {exc}")

    # Also check root-level files
    try:
        for item in branch_dir.iterdir():
            if _should_skip(item.name):
                continue
            if not item.is_file():
                continue
            rel_path = str(item.relative_to(branch_dir))
            if rel_path not in tracked_paths:
                entry = {
                    "path": rel_path,
                    "name": item.name,
                }
                untracked_files.append(entry)
                if trace:
                    logger.info(f"[reconcile] UNTRACKED (root): {rel_path}")
    except (PermissionError, OSError) as exc:
        if trace:
            logger.warning(f"[reconcile] Root scan error: {exc}")

    needs_update = bool(missing_files or untracked_files or hash_mismatches or missing_dirs)

    if trace:
        logger.info(
            f"[reconcile] Complete: missing={len(missing_files)}, "
            f"untracked={len(untracked_files)}, "
            f"hash_mismatches={len(hash_mismatches)}, "
            f"missing_dirs={len(missing_dirs)}, "
            f"needs_update={needs_update}"
        )

    return {
        "missing_files": missing_files,
        "untracked_files": untracked_files,
        "hash_mismatches": hash_mismatches,
        "missing_dirs": missing_dirs,
        "needs_update": needs_update,
    }
