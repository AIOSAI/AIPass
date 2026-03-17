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

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.spawn.apps.handlers.json import json_handler

# Branch metadata location
_BRANCH_META_DIR = ".spawn"
_MIGRATIONS_FILE = ".migrations.json"


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
# MIGRATIONS
# =============================================================================

def load_migrations(branch_dir: Path) -> Optional[list]:
    """Load .spawn/.migrations.json from a branch directory.

    Args:
        branch_dir: Path to the branch directory.

    Returns:
        List of migration dicts, or None if file is missing/unreadable.
    """
    branch_dir = Path(branch_dir)
    migrations_path = branch_dir / _BRANCH_META_DIR / _MIGRATIONS_FILE

    if not migrations_path.exists():
        return None

    try:
        data = json.loads(migrations_path.read_text(encoding="utf-8"))
        migrations_list = data.get("migrations", [])
        return migrations_list if migrations_list else None
    except (json.JSONDecodeError, IOError) as exc:
        logger.error(f"Failed to load migrations: {exc}")
        return None


def apply_migrations(data: dict, migrations: list) -> dict:
    """Apply migration operations to a data dict.

    Supported operation types:
    - ``key_rename``: Rename a key (old_key -> new_key).
    - ``move_to_nested``: Move keys under a parent key.
    - ``add_missing_keys``: Add keys if they don't exist.

    Each migration has an ``id``, ``applies_to_files`` (glob patterns),
    and ``operations`` list. Operations are applied in order.

    Args:
        data: Data dict to migrate (modified in place).
        migrations: List of migration dicts.

    Returns:
        The modified data dict.
    """
    for migration in migrations:
        migration_id = migration.get("id", "unknown")
        operations = migration.get("operations", [])

        for op in operations:
            op_type = op.get("type", "")

            try:
                if op_type == "key_rename":
                    _apply_key_rename(data, op, migration_id)

                elif op_type == "move_to_nested":
                    _apply_move_to_nested(data, op, migration_id)

                elif op_type == "add_missing_keys":
                    _apply_add_missing_keys(data, op, migration_id)

                else:
                    logger.warning(
                        f"[json_ops] Unknown migration operation '{op_type}' "
                        f"in migration {migration_id}"
                    )

            except Exception as exc:
                logger.error(
                    f"[json_ops] Migration {migration_id} operation "
                    f"'{op_type}' failed: {exc}"
                )

        json_handler.log_operation("migration_applied", data={"migration": migration_id})

    return data


def _apply_key_rename(data: dict, op: dict, _migration_id: str) -> None:
    """Rename a key, preserving its value.

    Args:
        data: Data dict (modified in place).
        op: Operation dict with 'from' and 'to' keys.
        migration_id: Migration ID for logging.
    """
    from_key = op.get("from", "")
    to_key = op.get("to", "")

    if not from_key or not to_key:
        return

    # Skip if target already exists
    if _get_nested_value(data, to_key) is not None:
        return

    # Get source value
    value = _get_nested_value(data, from_key)
    if value is None:
        return

    # Perform rename: set new key, delete old key
    _set_nested_value(data, to_key, value)
    _delete_nested_key(data, from_key)


def _apply_move_to_nested(data: dict, op: dict, _migration_id: str) -> None:
    """Move multiple keys under a new parent key.

    Args:
        data: Data dict (modified in place).
        op: Operation dict with 'source_keys' and 'target_parent'.
        migration_id: Migration ID for logging.
    """
    source_keys = op.get("source_keys", [])
    target_parent = op.get("target_parent", "")

    if not source_keys or not target_parent:
        return

    # Check if already migrated
    parent = data.get(target_parent)
    if isinstance(parent, dict) and all(k in parent for k in source_keys):
        return

    # Collect values to move
    values_to_move = {}
    for key in source_keys:
        if key in data:
            values_to_move[key] = data[key]

    if not values_to_move:
        return

    # Create parent if needed
    if target_parent not in data:
        data[target_parent] = {}
    elif not isinstance(data[target_parent], dict):
        return

    # Move keys
    for key, value in values_to_move.items():
        data[target_parent][key] = value
        del data[key]


def _apply_add_missing_keys(data: dict, op: dict, _migration_id: str) -> None:
    """Add keys with default values if they don't exist.

    Args:
        data: Data dict (modified in place).
        op: Operation dict with 'parent' and 'keys'.
        migration_id: Migration ID for logging.
    """
    parent_path = op.get("parent", "")
    keys_to_add = op.get("keys", {})

    if not keys_to_add:
        return

    # Get target location
    if parent_path:
        target = _get_nested_value(data, parent_path)
        if target is None:
            # Create parent if missing
            _set_nested_value(data, parent_path, {})
            target = _get_nested_value(data, parent_path)
        if not isinstance(target, dict):
            return
    else:
        target = data

    # Add missing keys
    for key, value in keys_to_add.items():
        if key not in target:
            target[key] = value


# =============================================================================
# NESTED VALUE HELPERS
# =============================================================================

def _get_nested_value(data: dict, key_path: str) -> Any:
    """Get value from nested dict using dot notation (e.g. 'metadata.version')."""
    if not key_path:
        return data

    keys = key_path.split(".")
    current = data

    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]

    return current


def _set_nested_value(data: dict, key_path: str, value: Any) -> bool:
    """Set value in nested dict using dot notation, creating intermediates."""
    if not key_path:
        return False

    keys = key_path.split(".")
    current = data

    for key in keys[:-1]:
        if key not in current:
            current[key] = {}
        elif not isinstance(current[key], dict):
            return False
        current = current[key]

    current[keys[-1]] = value
    return True


def _delete_nested_key(data: dict, key_path: str) -> bool:
    """Delete key from nested dict using dot notation."""
    if not key_path:
        return False

    keys = key_path.split(".")
    current = data

    for key in keys[:-1]:
        if not isinstance(current, dict) or key not in current:
            return False
        current = current[key]

    if isinstance(current, dict) and keys[-1] in current:
        del current[keys[-1]]
        return True

    return False


# =============================================================================
# BACKUP
# =============================================================================

def backup_json(file_path: Path) -> Path:
    """Create a timestamped backup of a JSON file before modifying.

    The backup is placed in a ``.backup/`` directory alongside the file,
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
    backup_dir = file_path.parent / ".backup"
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
