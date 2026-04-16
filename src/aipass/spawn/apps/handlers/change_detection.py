# =================== AIPass ====================
# Name: change_detection.py
# Description: Template change detection — template vs branch metadata
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-03-10
# =============================================

"""Template change detection handler.

Compares the template registry (what the template currently defines) against
branch metadata (what the branch currently has). Uses ID-based detection to
identify additions, updates, renames, and pruned files.
"""

from pathlib import Path
from typing import Any


# =============================================================================
# CHANGE DETECTION
# =============================================================================


def detect_changes(
    template_registry: dict,
    branch_meta: dict,
    branch_dir: Path,
    old_branch_tracking: dict | None = None,
) -> dict:
    """Detect changes between template registry and branch metadata.

    Uses ID-based matching:
    - ID exists in both template and branch -> compare paths (rename?) and hashes (update?)
    - ID only in template -> addition (new template file)
    - ID only in branch -> pruned (removed from template)

    Args:
        template_registry: Template registry dict (from .template_registry.json).
        branch_meta: Branch metadata dict (from .branch_meta.json).
        branch_dir: Path to the branch directory (for existence checks).
        old_branch_tracking: Snapshot of file_tracking from BEFORE metadata
            regeneration (Phase 0 pattern). Used for accurate rename detection.
            When None, falls back to current branch_meta tracking.

    Returns:
        Dict with change categories::

            {
                "additions": [{"file_id": ..., "template_path": ..., "hash": ...}, ...],
                "updates": [{"file_id": ..., "template_path": ..., "branch_path": ...,
                             "template_hash": ..., "branch_hash": ...}, ...],
                "renames": [{"file_id": ..., "template_path": ..., "branch_path": ...,
                             "old_name": ..., "new_name": ...}, ...],
                "pruned": [{"file_id": ..., "branch_path": ..., "name": ...}, ...],
            }
    """
    branch_dir = Path(branch_dir)

    additions: list[dict[str, Any]] = []
    updates: list[dict[str, Any]] = []
    renames: list[dict[str, Any]] = []
    pruned: list[dict[str, Any]] = []

    # Extract tracking data from branch metadata
    branch_file_tracking = branch_meta.get("file_tracking", {})
    branch_dir_tracking = branch_meta.get("directory_tracking", {})

    # Merge file and directory IDs from branch meta into a single set for lookup
    branch_ids = set(branch_file_tracking.keys()) | set(branch_dir_tracking.keys())

    # Build template ID sets
    template_files = template_registry.get("files", {})
    template_dirs = template_registry.get("directories", {})
    template_ids = set(template_files.keys()) | set(template_dirs.keys())

    # -----------------------------------------------------------------
    # 1. Detect ADDITIONS: IDs in template but not in branch
    # -----------------------------------------------------------------
    for file_id in template_ids - branch_ids:
        # Get template info (could be file or directory)
        t_info = template_files.get(file_id) or template_dirs.get(file_id)
        if not t_info:
            continue

        template_path = t_info.get("path", t_info.get("current_name", ""))

        entry: dict[str, Any] = {
            "file_id": file_id,
            "template_path": template_path,
        }

        # Include hash for files (directories don't have hashes)
        if file_id in template_files:
            entry["hash"] = t_info.get("content_hash", "")

        additions.append(entry)

    # -----------------------------------------------------------------
    # 2. Detect PRUNED: IDs in branch but not in template
    # -----------------------------------------------------------------
    for file_id in branch_ids - template_ids:
        b_info = branch_file_tracking.get(file_id) or branch_dir_tracking.get(file_id)
        if not b_info:
            continue

        branch_path = b_info.get("current_path", "")
        name = b_info.get("current_name", "")

        pruned.append(
            {
                "file_id": file_id,
                "branch_path": branch_path,
                "name": name,
            }
        )

    # -----------------------------------------------------------------
    # 3. Detect RENAMES and UPDATES: IDs in both template and branch
    # -----------------------------------------------------------------
    common_ids = template_ids & branch_ids

    for file_id in common_ids:
        # Get info from both sides
        t_info = template_files.get(file_id) or template_dirs.get(file_id)
        b_info = branch_file_tracking.get(file_id) or branch_dir_tracking.get(file_id)

        if not t_info or not b_info:
            continue

        template_path = t_info.get("path", t_info.get("current_name", ""))
        branch_path = b_info.get("current_path", "")

        # Check for RENAME: same ID but path changed in template
        # Use old tracking snapshot for comparison if available (Phase 0 pattern)
        if old_branch_tracking and file_id in old_branch_tracking:
            old_info = old_branch_tracking[file_id]
            old_template_name = old_info.get("template_name", "")
            if old_template_name and template_path != old_template_name:
                renames.append(
                    {
                        "file_id": file_id,
                        "template_path": template_path,
                        "branch_path": branch_path,
                        "old_name": old_template_name,
                        "new_name": template_path,
                    }
                )
        else:
            # Fallback: compare against current branch meta
            branch_template_name = b_info.get("template_name", "")
            if branch_template_name and template_path != branch_template_name:
                renames.append(
                    {
                        "file_id": file_id,
                        "template_path": template_path,
                        "branch_path": branch_path,
                        "old_name": branch_template_name,
                        "new_name": template_path,
                    }
                )

        # Check for UPDATE: same ID, same location, content hash changed
        # Only applies to files (directories don't have content hashes)
        if file_id in template_files and file_id in branch_file_tracking:
            template_hash = t_info.get("content_hash", "")
            branch_hash = b_info.get("content_hash", "")

            if template_hash and branch_hash and template_hash != branch_hash:
                updates.append(
                    {
                        "file_id": file_id,
                        "template_path": template_path,
                        "branch_path": branch_path,
                        "template_hash": template_hash,
                        "branch_hash": branch_hash,
                    }
                )

    return {
        "additions": additions,
        "updates": updates,
        "renames": renames,
        "pruned": pruned,
    }
