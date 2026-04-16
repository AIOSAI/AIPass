# =================== AIPass ====================
# Name: sync_templates_ops.py
# Description: Template sync handler — implementation logic for template sync
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-03-10
# =============================================

"""Template synchronization handler for branch lifecycle management.

Contains the core sync logic: loading template owners, comparing hashes
between source branches and template files, and optionally pulling updates.
"""

import hashlib
import json
import shutil
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.spawn.apps.handlers.json import json_handler

# Repo root — resolved from spawn package location
_REPO_ROOT = Path(__file__).parents[5]  # handlers/apps/spawn/aipass/src/AIPass

# Path to template_owners.json
_TEMPLATE_OWNERS_PATH = Path(__file__).parent / "templates" / "template_owners.json"


# =============================================================================
# PUBLIC API
# =============================================================================


def sync_templates(sync: bool = False, dry_run: bool = False) -> dict:
    """Pull managed files from authoritative source branches.

    Uses template_owners.json to know which files are "owned" by which branches.
    The owner branch has the canonical version — template should match.

    Workflow:
    1. Load template_owners.json from spawn/apps/handlers/templates/
    2. For each managed file:
       a. Find the source file in the owner branch
       b. Compare hash with template version
       c. If different -> stale
    3. If sync=True and not dry_run:
       - Copy source files into template
    4. Report what was synced/stale

    Returns:
        Dict with sync results.
    """
    # 1. Load template_owners.json
    owners_data = _load_template_owners()
    managed_files = owners_data.get("managed_files", {})

    current: list[str] = []
    stale: list[str] = []
    synced: list[str] = []
    errors: list[str] = []

    if not managed_files:
        logger.info("[sync-templates] No managed files configured in template_owners.json")
        return {
            "managed_files": 0,
            "current": current,
            "stale": stale,
            "synced": synced,
            "errors": errors,
        }

    # 2. Check each managed file
    for file_key, file_info in managed_files.items():
        source_branch = file_info.get("source_branch", "")
        source_path = file_info.get("source_path", "")
        template_path = file_info.get("template_path", "")

        if not source_branch or not source_path or not template_path:
            errors.append(f"Incomplete config for managed file: {file_key}")
            continue

        # Resolve paths
        source_file = _REPO_ROOT / "src" / "aipass" / source_branch / source_path
        template_file = Path(__file__).parent / "templates" / template_path

        if not source_file.exists():
            errors.append(f"Source file not found: {source_file}")
            continue

        # Compare hashes
        source_hash = _file_hash(source_file)

        if template_file.exists():
            template_hash = _file_hash(template_file)
            if source_hash == template_hash:
                current.append(file_key)
                continue

        # File is stale (different hash or doesn't exist in template)
        stale.append(file_key)

        # 3. Sync if requested
        if sync and not dry_run:
            try:
                template_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(source_file), str(template_file))
                synced.append(file_key)
                logger.info(f"[sync-templates] Synced: {file_key} from {source_branch}")
            except Exception as exc:
                errors.append(f"Failed to sync {file_key}: {exc}")
                logger.error(f"[sync-templates] Failed to sync {file_key}: {exc}")

    json_handler.log_operation("templates_pulled")

    return {
        "managed_files": len(managed_files),
        "current": current,
        "stale": stale,
        "synced": synced,
        "errors": errors,
    }


# =============================================================================
# INTERNAL HELPERS
# =============================================================================


def _load_template_owners() -> dict:
    """Load template_owners.json. Returns empty structure if missing."""
    if not _TEMPLATE_OWNERS_PATH.exists():
        logger.warning(f"[sync-templates] template_owners.json not found: {_TEMPLATE_OWNERS_PATH}")
        return {"managed_files": {}}

    try:
        data = json.loads(_TEMPLATE_OWNERS_PATH.read_text(encoding="utf-8"))
        return data
    except (json.JSONDecodeError, IOError) as exc:
        logger.error(f"[sync-templates] Failed to load template_owners.json: {exc}")
        return {"managed_files": {}}


def _file_hash(filepath: Path) -> str:
    """Compute SHA-256 hash (first 12 chars) of a file."""
    try:
        content = filepath.read_bytes()
        return hashlib.sha256(content).hexdigest()[:12]
    except IOError as e:
        logger.warning(f"Failed to hash file {filepath}: {e}")
        return ""
