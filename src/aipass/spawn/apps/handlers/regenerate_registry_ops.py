# =================== AIPass ====================
# Name: regenerate_registry_ops.py
# Description: Regenerate .template_registry.json for spawn template directories
# Version: 1.0.0
# Created: 2026-03-25
# Modified: 2026-03-25
# =============================================

"""Regenerate template registry — walk template directory, hash files, build registry.

Scans a template directory, computes content hashes for all tracked files,
and builds a fresh .template_registry.json while preserving existing IDs
where possible (by content hash match first, then by path match).
"""

import json
from datetime import datetime
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.spawn.apps.handlers.meta_ops import compute_file_hash, load_template_registry

# =============================================================================
# CONSTANTS
# =============================================================================

_SPAWN_DIR = ".spawn"
_TEMPLATE_REGISTRY_FILE = ".template_registry.json"

# Directories to skip entirely during scan
_SKIP_DIRS = {"__pycache__", ".git"}

# Files to skip within .spawn/ (tracking files that shouldn't be in the registry)
_SKIP_SPAWN_FILES = {".template_registry.json", ".branch_meta.json"}

# Placeholder patterns to detect in filenames
_BRANCH_PLACEHOLDERS = ("{{BRANCH}}", "{{BRANCHNAME}}")


# =============================================================================
# PUBLIC API
# =============================================================================

def regenerate_template_registry(template_dir: Path) -> dict:
    """Walk a template directory, hash files, and build a fresh registry.

    Preserves existing file/directory IDs where possible by matching
    on content hash first, then path, before assigning new IDs.

    Args:
        template_dir: Absolute path to the template directory (e.g. builder/).

    Returns:
        dict with keys: metadata, files, directories, stats.
        The stats key is extra (not written to JSON) — used for CLI output.
    """
    template_dir = Path(template_dir)

    if not template_dir.is_dir():
        logger.error(f"Template directory does not exist: {template_dir}")
        return {"error": f"Template directory does not exist: {template_dir}"}

    # Load existing registry for ID preservation
    existing_registry = load_template_registry(template_dir)

    # Scan and build new registry entries
    files, directories = _scan_template_directory(template_dir, existing_registry)

    today = datetime.now().strftime("%Y-%m-%d")

    registry = {
        "metadata": {
            "version": "1.0.0",
            "last_updated": today,
            "description": "Template file tracking registry for ID-based updates",
        },
        "files": files,
        "directories": directories,
    }

    # Write the registry
    spawn_dir = template_dir / _SPAWN_DIR
    spawn_dir.mkdir(parents=True, exist_ok=True)
    registry_path = spawn_dir / _TEMPLATE_REGISTRY_FILE

    try:
        tmp_path = registry_path.with_suffix(".tmp")
        tmp_path.write_text(
            json.dumps(registry, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        tmp_path.rename(registry_path)
    except (IOError, OSError) as exc:
        logger.error(f"Failed to write template registry: {exc}")
        return {"error": f"Failed to write registry: {exc}"}

    # Build stats for CLI output (not part of the persisted registry)
    existing_file_count = len(existing_registry.get("files", {})) if existing_registry else 0
    existing_dir_count = len(existing_registry.get("directories", {})) if existing_registry else 0

    stats = {
        "files_tracked": len(files),
        "directories_tracked": len(directories),
        "previous_files": existing_file_count,
        "previous_directories": existing_dir_count,
        "registry_path": str(registry_path),
        "template_dir": str(template_dir),
        "template_name": template_dir.name,
    }

    logger.info(
        f"Regenerated template registry for {template_dir.name}: "
        f"{len(files)} files, {len(directories)} directories"
    )

    return {**registry, "stats": stats}


# =============================================================================
# INTERNAL — SCANNING
# =============================================================================

def _scan_template_directory(
    template_dir: Path,
    existing_registry: dict | None,
) -> tuple[dict, dict]:
    """Walk template directory and build files and directories dicts.

    ID preservation strategy:
      Files:
        Priority 1 — content hash match in existing registry -> keep ID
        Priority 2 — path match in existing registry -> keep ID
        Priority 3 — new file -> assign next available ID (f001, f002, ...)

      Directories:
        Priority 1 — path match in existing registry -> keep ID
        Priority 2 — name match in existing registry -> keep ID
        Priority 3 — new dir -> assign next available ID (d001, d002, ...)

    Args:
        template_dir: Absolute path to template root.
        existing_registry: Previously loaded registry dict, or None.

    Returns:
        Tuple of (files_dict, directories_dict).
    """
    # Build reverse lookups from existing registry
    existing_files = existing_registry.get("files", {}) if existing_registry else {}
    existing_dirs = existing_registry.get("directories", {}) if existing_registry else {}

    # File lookups: hash -> id, path -> id
    # Index both the full hash AND the 12-char prefix to handle old registries
    # that used 16-char hashes (file_ops.py) vs current 12-char (compute_file_hash)
    hash_to_id: dict[str, str] = {}
    path_to_file_id: dict[str, str] = {}
    for fid, finfo in existing_files.items():
        path_to_file_id[finfo.get("path", "")] = fid
        content_hash = finfo.get("content_hash", "")
        if content_hash and content_hash != "placeholder":
            hash_to_id[content_hash] = fid
            # Also index the 12-char prefix for cross-format matching
            if len(content_hash) > 12:
                hash_to_id[content_hash[:12]] = fid

    # Directory lookups: path -> id, name -> id
    path_to_dir_id: dict[str, str] = {}
    name_to_dir_id: dict[str, str] = {}
    for did, dinfo in existing_dirs.items():
        path_to_dir_id[dinfo.get("path", "")] = did
        name_to_dir_id[dinfo.get("name", "")] = did

    # Track which IDs have been claimed
    claimed_file_ids: set[str] = set()
    claimed_dir_ids: set[str] = set()

    # Collect raw entries before assigning IDs
    raw_files: list[dict] = []
    raw_dirs: list[dict] = []

    for item in sorted(template_dir.rglob("*")):
        rel = item.relative_to(template_dir)
        rel_str = str(rel)

        # Skip excluded directories and their contents
        if any(part in _SKIP_DIRS for part in rel.parts):
            continue

        # Skip tracking files within .spawn/ (but allow README.md etc.)
        if ".spawn" in rel.parts and item.is_file() and item.name in _SKIP_SPAWN_FILES:
            continue

        if item.is_dir():
            has_placeholder = any(p in item.name for p in _BRANCH_PLACEHOLDERS)
            raw_dirs.append({
                "path": rel_str,
                "name": item.name,
                "has_branch_placeholder": has_placeholder,
            })

        elif item.is_file():
            content_hash = compute_file_hash(item)
            has_placeholder = any(p in item.name for p in _BRANCH_PLACEHOLDERS)
            raw_files.append({
                "path": rel_str,
                "name": item.name,
                "content_hash": content_hash,
                "has_branch_placeholder": has_placeholder,
            })

    # Assign IDs to files with three-pass global matching.
    # This prevents new files from stealing IDs that existing files should claim.
    files: dict[str, dict] = {}
    unmatched_files: list[dict] = []

    # Pass 1: hash matching for all files
    for entry in raw_files:
        content_hash = entry.get("content_hash", "")
        if content_hash and content_hash in hash_to_id:
            candidate = hash_to_id[content_hash]
            if candidate not in claimed_file_ids:
                claimed_file_ids.add(candidate)
                files[candidate] = entry
                continue
        unmatched_files.append(entry)

    # Pass 2: path matching for remaining files
    still_unmatched: list[dict] = []
    for entry in unmatched_files:
        path = entry.get("path", "")
        if path and path in path_to_file_id:
            candidate = path_to_file_id[path]
            if candidate not in claimed_file_ids:
                claimed_file_ids.add(candidate)
                files[candidate] = entry
                continue
        still_unmatched.append(entry)

    # Pass 3: new IDs for truly new files
    for entry in still_unmatched:
        fid = _next_id("f", claimed_file_ids)
        claimed_file_ids.add(fid)
        files[fid] = entry

    # Assign IDs to directories with two-pass matching
    directories: dict[str, dict] = {}
    unmatched_dirs: list[dict] = []

    # Pass 1: path matching
    for entry in raw_dirs:
        path = entry.get("path", "")
        if path and path in path_to_dir_id:
            candidate = path_to_dir_id[path]
            if candidate not in claimed_dir_ids:
                claimed_dir_ids.add(candidate)
                directories[candidate] = entry
                continue
        unmatched_dirs.append(entry)

    # Pass 2: name matching for remaining dirs
    still_unmatched_dirs: list[dict] = []
    for entry in unmatched_dirs:
        name = entry.get("name", "")
        if name and name in name_to_dir_id:
            candidate = name_to_dir_id[name]
            if candidate not in claimed_dir_ids:
                claimed_dir_ids.add(candidate)
                directories[candidate] = entry
                continue
        still_unmatched_dirs.append(entry)

    # Pass 3: new IDs for truly new dirs
    for entry in still_unmatched_dirs:
        did = _next_id("d", claimed_dir_ids)
        claimed_dir_ids.add(did)
        directories[did] = entry

    return files, directories


def _next_id(prefix: str, claimed: set[str]) -> str:
    """Generate the next sequential ID with the given prefix.

    Scans f001..f999 or d001..d999 to find the first unclaimed slot.

    Args:
        prefix: "f" for files, "d" for directories.
        claimed: Set of already-claimed IDs.

    Returns:
        Next available ID string (e.g. "f027").
    """
    for i in range(1, 1000):
        candidate = f"{prefix}{i:03d}"
        if candidate not in claimed:
            return candidate
    # Fallback — should never happen with < 1000 items
    logger.warning(f"ID space exhausted for prefix '{prefix}'")
    return f"{prefix}999"
