# =================== AIPass ====================
# Name: meta_ops.py
# Description: Branch metadata operations for update tracking
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-03-10
# =============================================

"""Branch metadata operations — manages .spawn/.branch_meta.json for per-branch tracking.

Provides functions to load/save template registries and branch metadata,
generate initial metadata for branches that predate the tracking system,
and compute file content hashes for change detection.
"""

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.spawn.apps.handlers.json import json_handler

# =============================================================================
# CONSTANTS
# =============================================================================

_BRANCH_META_DIR = ".spawn"
_BRANCH_META_FILE = ".branch_meta.json"
_TEMPLATE_REGISTRY_FILE = ".template_registry.json"


# =============================================================================
# PATH HELPERS
# =============================================================================

def get_template_dir(citizen_class: str = "builder") -> Path:
    """Return path to template directory for a citizen class.

    Args:
        citizen_class: Name of the citizen class. Defaults to "builder".

    Returns:
        Path to the template directory.
    """
    from aipass.spawn.apps.handlers.class_registry import get_template_dir as _class_get_template_dir
    return _class_get_template_dir(citizen_class)


# =============================================================================
# FILE HASHING
# =============================================================================

def compute_file_hash(file_path: Path) -> str:
    """Compute SHA-256 hash of a file, returning the first 12 hex characters.

    Args:
        file_path: Path to the file to hash.

    Returns:
        First 12 characters of the SHA-256 hex digest, or empty string on error.
    """
    file_path = Path(file_path)
    if not file_path.is_file():
        return ""

    try:
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()[:12]
    except (IOError, PermissionError) as exc:
        logger.warning(f"Could not hash {file_path.name}: {exc}")
        return ""


# =============================================================================
# TEMPLATE REGISTRY OPERATIONS
# =============================================================================

def load_template_registry(template_dir: Path) -> Optional[dict]:
    """Load .spawn/.template_registry.json from a template directory.

    Args:
        template_dir: Path to the template directory (e.g. builder/).

    Returns:
        Parsed dict of the template registry, or None if missing/unreadable.
    """
    template_dir = Path(template_dir)
    registry_path = template_dir / _BRANCH_META_DIR / _TEMPLATE_REGISTRY_FILE

    if not registry_path.exists():
        logger.warning(f"Template registry not found at {registry_path}")
        return None

    try:
        data = json.loads(registry_path.read_text(encoding="utf-8"))
        return data
    except (json.JSONDecodeError, IOError) as exc:
        logger.error(f"Failed to load template registry: {exc}")
        return None


# =============================================================================
# BRANCH METADATA OPERATIONS
# =============================================================================

def load_branch_meta(branch_dir: Path) -> Optional[dict]:
    """Load .spawn/.branch_meta.json from a branch directory.

    Args:
        branch_dir: Path to the branch directory.

    Returns:
        Parsed dict of the branch metadata, or None if missing/unreadable.
        None is normal for branches that predate the tracking system.
    """
    branch_dir = Path(branch_dir)
    meta_path = branch_dir / _BRANCH_META_DIR / _BRANCH_META_FILE

    if not meta_path.exists():
        return None

    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        return data
    except (json.JSONDecodeError, IOError) as exc:
        logger.error(f"Failed to load branch metadata: {exc}")
        return None


def save_branch_meta(branch_dir: Path, meta: dict) -> bool:
    """Write .spawn/.branch_meta.json atomically.

    Creates the .spawn/ directory if it doesn't exist.

    Args:
        branch_dir: Path to the branch directory.
        meta: Metadata dict to write.

    Returns:
        True on success, False on error.
    """
    branch_dir = Path(branch_dir)
    spawn_dir = branch_dir / _BRANCH_META_DIR
    meta_path = spawn_dir / _BRANCH_META_FILE

    try:
        spawn_dir.mkdir(parents=True, exist_ok=True)

        # Write to temp file first, then rename for atomicity
        tmp_path = meta_path.with_suffix(".tmp")
        tmp_path.write_text(
            json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        tmp_path.rename(meta_path)
        return True
    except (IOError, TypeError, OSError) as exc:
        logger.error(f"Failed to save branch metadata: {exc}")
        # Clean up temp file if it exists
        tmp_path = meta_path.with_suffix(".tmp")
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        return False


def generate_branch_meta(branch_dir: Path, template_registry: dict) -> dict:
    """Generate initial .branch_meta.json for an existing branch.

    This is the "adoption" path for branches that predate the tracking system.
    Scans the filesystem, matches files against the template registry (by path
    first, then by content hash), assigns IDs, and computes current SHA-256 hashes.

    Args:
        branch_dir: Path to the existing branch directory.
        template_registry: Loaded template registry dict.

    Returns:
        A dict in .branch_meta.json format with metadata, file_tracking,
        and directory_tracking sections.
    """
    branch_dir = Path(branch_dir)
    branch_name = branch_dir.name

    # Build reverse lookups from template registry
    # path -> (file_id, file_info) for matching by path
    template_path_to_id: dict[str, tuple[str, dict]] = {}
    # hash -> (file_id, file_info) for matching by content hash
    template_hash_to_id: dict[str, tuple[str, dict]] = {}

    for file_id, file_info in template_registry.get("files", {}).items():
        path = file_info.get("path", file_info.get("current_name", ""))
        template_path_to_id[path] = (file_id, file_info)

        content_hash = file_info.get("content_hash", "")
        # Don't index empty-file hashes (too many collisions)
        if content_hash and content_hash != "e3b0c44298fc":
            template_hash_to_id[content_hash] = (file_id, file_info)

    # Directory lookup
    template_dir_path_to_id: dict[str, tuple[str, dict]] = {}
    for dir_id, dir_info in template_registry.get("directories", {}).items():
        path = dir_info.get("path", dir_info.get("current_name", ""))
        template_dir_path_to_id[path] = (dir_id, dir_info)

    # Scan the branch filesystem and build tracking
    file_tracking: dict[str, dict[str, Any]] = {}
    directory_tracking: dict[str, dict[str, str]] = {}
    matched_file_ids: set[str] = set()
    matched_dir_ids: set[str] = set()

    for item in sorted(branch_dir.rglob("*")):
        rel = str(item.relative_to(branch_dir))

        # Skip .spawn internals and __pycache__
        if _BRANCH_META_DIR in Path(rel).parts or "__pycache__" in Path(rel).parts:
            continue

        if item.is_dir():
            # Try to match directory by path
            if rel in template_dir_path_to_id:
                dir_id, dir_info = template_dir_path_to_id[rel]
                if dir_id not in matched_dir_ids:
                    directory_tracking[dir_id] = {
                        "template_name": dir_info.get("path", dir_info.get("current_name", "")),
                        "current_name": item.name,
                        "current_path": rel,
                    }
                    matched_dir_ids.add(dir_id)

        elif item.is_file():
            content_hash = compute_file_hash(item)

            # Try to match by path first
            matched = False
            if rel in template_path_to_id:
                file_id, file_info = template_path_to_id[rel]
                if file_id not in matched_file_ids:
                    file_tracking[file_id] = {
                        "template_name": file_info.get("path", file_info.get("current_name", "")),
                        "current_name": item.name,
                        "current_path": rel,
                        "content_hash": content_hash,
                    }
                    matched_file_ids.add(file_id)
                    matched = True

            # Fall back to hash matching if path didn't match
            if not matched and content_hash and content_hash in template_hash_to_id:
                file_id, file_info = template_hash_to_id[content_hash]
                if file_id not in matched_file_ids:
                    file_tracking[file_id] = {
                        "template_name": file_info.get("path", file_info.get("current_name", "")),
                        "current_name": item.name,
                        "current_path": rel,
                        "content_hash": content_hash,
                    }
                    matched_file_ids.add(file_id)

    # Build the metadata structure
    template_version = template_registry.get("metadata", {}).get("version", "1.0.0")
    today = datetime.now().strftime("%Y-%m-%d")

    meta = {
        "metadata": {
            "version": "1.0.0",
            "template_version": template_version,
            "last_updated": today,
            "branch_name": branch_name,
        },
        "file_tracking": file_tracking,
        "directory_tracking": directory_tracking,
    }

    json_handler.log_operation("meta_generated", data={"branch": branch_name})

    return meta
