# =================== AIPass ====================
# Name: config.py
# Description: Project config handler — load/save per-project backup config
# Version: 1.0.0
# Created: 2026-04-16
# Modified: 2026-04-23
# =============================================

"""Project configuration handler.

Reads and writes the per-project ``.backup/config.json`` that stores mode
preferences, size limits, and drive-sync settings.
"""

from aipass.prax import logger

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
    """
    config_path = str(builder.build_config_path(project_root))
    config = json_handler.load_json(config_path)
    merged = {**DEFAULTS, **config}
    json_handler.log_operation("project_config_loaded", {"project_root": project_root})
    return merged


def save_project_config(project_root: str, config: dict) -> bool:
    """Persist the backup configuration for a project.

    Args:
        project_root: Absolute path to the project root.
        config: Configuration payload to serialize to JSON.

    Returns:
        True when the write succeeded, False otherwise.
    """
    config_path = str(builder.build_config_path(project_root))
    try:
        json_handler.save_json(config_path, config)
        json_handler.log_operation("project_config_saved", {"project_root": project_root})
        return True
    except OSError as e:
        logger.warning(f"Failed to save config for {project_root}: {e}")
        json_handler.log_operation(
            "project_config_save_failed",
            {"project_root": project_root, "error": str(e)},
        )
        return False


# =============================================
