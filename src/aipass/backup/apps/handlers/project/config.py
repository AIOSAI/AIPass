# =================== AIPass ====================
# Name: config.py
# Description: Project config handler — load/save per-project backup config
# Version: 1.1.0
# Created: 2026-04-16
# Modified: 2026-09-03
# =============================================

"""Project configuration handler.

Reads and writes the per-project ``.backup/config.json`` that stores mode
preferences, size limits, and drive-sync settings.
"""

from aipass.prax import logger

from ..audit import trail
from ..json import json_handler
from ..path import builder

DEFAULTS = {
    "version": "1.0.0",
    "backup_mode": "snapshot",
    "max_versions": 10,
    "max_file_size_mb": 100,
    "max_backup_files": 25000,
    "max_backup_size_gb": 10,
    "auto_ignore_git": True,
    "drive_sync": False,
    "whitelist": [],
}


def load_project_config(project_root: str) -> dict:
    """Load the backup configuration for a project.

    Args:
        project_root: Absolute path to the project root.

    Returns:
        Dict containing config keys, merged with defaults for any missing keys.

    Raises:
        InvalidDocument: The config exists but cannot be read as a JSON object.
            Falling back to DEFAULTS would quietly reset the project's own
            size ceilings and ignore rules mid-backup.
    """
    config_path = builder.build_config_path(project_root)
    config = json_handler.read_json(config_path)
    if config is None:
        if config_path.exists():
            raise json_handler.InvalidDocument(f"Project config unreadable: {config_path}")
        config = {}
    if not isinstance(config, dict):
        raise json_handler.InvalidDocument(f"Project config is not a JSON object: {config_path}")
    merged = {**DEFAULTS, **config}
    trail.log_operation("project_config_loaded", {"project_root": project_root})
    return merged


def save_project_config(project_root: str, config: dict) -> bool:
    """Persist the backup configuration for a project.

    Args:
        project_root: Absolute path to the project root.
        config: Configuration payload to serialize to JSON.

    Returns:
        True when the write succeeded, False otherwise.
    """
    config_path = builder.build_config_path(project_root)
    if not json_handler.write_json(config_path, config):
        logger.warning(f"Failed to save config for {project_root} at {config_path}")
        trail.log_operation(
            "project_config_save_failed",
            {"project_root": project_root, "config_path": str(config_path)},
        )
        return False
    trail.log_operation("project_config_saved", {"project_root": project_root})
    return True


# =============================================
