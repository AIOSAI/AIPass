# =================== AIPass ====================
# Name: json_ops.py
# Description: JSON operations — deep merge, migrations, backups
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-03-10
# =============================================

"""JSON operations handler for branch updates.

Provides deep merge for JSON files (preserving existing user data while
adding new template structure), migration execution for structural
transformations, and backup utilities.
"""

import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from aipass.prax.apps.modules.logger import system_logger as logger


# =============================================================================
# DEEP MERGE
# =============================================================================


def deep_merge(template_data: Any, existing_data: Any) -> Any:
    """Recursively merge template structure with existing data.

    Merge strategy:
    - Both dicts: merge keys. Template defines structure, existing fills values.
    - Template has key that existing doesn't: add from template (default).
    - Existing has key that template doesn't: KEEP existing key (don't prune).
    - Both lists: keep existing list (don't overwrite user data).
    - Scalar values: keep existing value (don't overwrite).
    - If existing is None/empty but template has value: use template value.

    Args:
        template_data: Template structure (provides fields and defaults).
        existing_data: Existing data (provides values to preserve).

    Returns:
        Merged result combining template structure with existing values.
    """
    # If existing is None, use template
    if existing_data is None:
        return template_data

    # If template is None, keep existing
    if template_data is None:
        return existing_data

    # Both dicts: merge keys
    if isinstance(template_data, dict) and isinstance(existing_data, dict):
        result = {}

        # Add all template keys (ensures new fields exist)
        for key in template_data:
            if key in existing_data:
                # Recursively merge
                result[key] = deep_merge(template_data[key], existing_data[key])
            else:
                # New field from template — use template default
                result[key] = template_data[key]

        # Preserve existing keys not in template (user additions)
        for key in existing_data:
            if key not in result:
                result[key] = existing_data[key]

        return result

    # Both lists: keep existing if non-empty, else use template
    if isinstance(template_data, list) and isinstance(existing_data, list):
        if len(existing_data) > 0:
            return existing_data
        if len(template_data) > 0:
            return template_data
        return []

    # Type mismatch or scalars: preserve existing value
    # (existing was valid before, don't overwrite)
    if existing_data is not None:
        # Check for "empty" existing values — use template if existing is empty
        if isinstance(existing_data, str) and existing_data == "" and template_data:
            return template_data
        return existing_data

    return template_data


# =============================================================================
# BACKUP
# =============================================================================


def backup_json(file_path: Path) -> Path:
    """Create a timestamped backup of a JSON file before modifying.

    The backup is placed in a ``.recovery/`` directory alongside the file,
    named with a timestamp suffix.

    Args:
        file_path: Path to the JSON file to back up.

    Returns:
        Path to the backup file.

    Raises:
        FileNotFoundError: If the source file doesn't exist.
        IOError: If the backup copy fails.
    """
    file_path = Path(file_path)

    if not file_path.exists():
        raise FileNotFoundError(f"Cannot backup — file not found: {file_path}")

    # Create backup directory alongside the file
    backup_dir = file_path.parent / ".recovery"
    backup_dir.mkdir(parents=True, exist_ok=True)

    # Timestamped backup name
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"{file_path.name}.{timestamp}.backup"
    backup_path = backup_dir / backup_name

    try:
        shutil.copy2(file_path, backup_path)
        return backup_path
    except (IOError, OSError) as exc:
        logger.error(f"[json_ops] Backup failed for {file_path.name}: {exc}")
        raise
