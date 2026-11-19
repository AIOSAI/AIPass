# =================== AIPass ====================
# Name: json_merge.py
# Description: Update's JSON merge (template fills, existing wins) and its timestamped backup
# Version: 1.0.0
# Created: 2026-11-17
# Modified: 2026-11-17
# =============================================

"""The update lane's JSON merge and backup: a citizen's values survive every template change."""

import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from aipass.prax import logger
from aipass.spawn.apps.handlers.json import json_handler


def deep_merge(template_data: Any, existing_data: Any) -> Any:
    """Recursively merge template structure with existing data.

    Existing data wins and is never pruned; the template only fills missing keys,
    None, empty lists and empty strings.
    """
    if existing_data is None:
        return template_data

    if template_data is None:
        return existing_data

    if isinstance(template_data, dict) and isinstance(existing_data, dict):
        result = {}

        for key in template_data:
            if key in existing_data:
                result[key] = deep_merge(template_data[key], existing_data[key])
            else:
                result[key] = template_data[key]

        for key in existing_data:
            if key not in result:
                result[key] = existing_data[key]

        return result

    if isinstance(template_data, list) and isinstance(existing_data, list):
        if len(existing_data) > 0:
            return existing_data
        if len(template_data) > 0:
            return template_data
        return []

    if isinstance(existing_data, str) and existing_data == "" and template_data:
        return template_data
    return existing_data


def backup_json(file_path: Path, backup_dir: Path | None = None) -> Path:
    """Copy a JSON file to a timestamped backup; raises when the file is missing or the copy fails."""
    file_path = Path(file_path)

    if not file_path.exists():
        raise FileNotFoundError(f"Cannot backup — file not found: {file_path}")

    if backup_dir is None:
        backup_dir = file_path.parent / ".recovery"
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"{file_path.name}.{timestamp}.backup"
    counter = 1
    while backup_path.exists():  # same-second backups must not overwrite each other
        counter += 1
        backup_path = backup_dir / f"{file_path.name}.{timestamp}-{counter}.backup"

    try:
        shutil.copy2(file_path, backup_path)
    except OSError as exc:
        logger.error("Backup failed for %s: %s", file_path.name, exc)
        raise
    json_handler.log_operation("json_backed_up", data={"file": str(file_path), "backup": str(backup_path)})
    return backup_path
