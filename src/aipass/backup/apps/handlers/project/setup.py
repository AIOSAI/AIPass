# =================== AIPass ====================
# Name: setup.py
# Description: Project setup handler — scaffold .backup/ directory in target
# Version: 1.1.0
# Created: 2026-04-16
# Modified: 2026-09-03
# =============================================

"""Project setup handler.

Creates the ``.backup/`` scaffold (config, snapshots/, logs/)
inside a target project path, and a ``.backupignore`` at the project root.
"""

from datetime import datetime, timezone
from pathlib import Path

from ..path.module_paths import branch_root
from ..audit import trail
from ..json import json_handler
from ..path import builder

_TEMPLATE_PATH = branch_root(__file__, 3) / "templates" / "backupignore.template"


def _build_backupignore() -> str:
    """Read the seed .backupignore content from the template file.

    Raises:
        FileNotFoundError: If the template is missing.
        OSError: If the template cannot be read.
    """
    if not _TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"Seed template missing: {_TEMPLATE_PATH} — cannot create a safe .backupignore")
    return _TEMPLATE_PATH.read_text(encoding="utf-8")


DEFAULT_CONFIG = {
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


def create_backup_dir(project_path: str) -> Path | None:
    """Create the ``.backup/`` scaffold inside a project path.

    Args:
        project_path: Absolute filesystem path to the target project.

    Returns:
        Path to the created ``.backup/`` directory, or None on failure --
        including a config that could not be written, which used to be
        reported as a successful setup.
    """
    root = Path(project_path)
    if not root.is_dir():
        trail.log_operation("setup_failed", {"project_path": project_path, "reason": "not a directory"})
        return None

    backup_dir = builder.backup_root(project_path)
    subdirs = [
        backup_dir / "snapshots",
        backup_dir / "logs",
    ]

    for d in subdirs:
        d.mkdir(parents=True, exist_ok=True)

    config_path = builder.build_config_path(project_path)
    if not config_path.exists():
        config = {
            **DEFAULT_CONFIG,
            "project_name": root.name,
            "project_path": str(root),
            "created": datetime.now(timezone.utc).isoformat(),
        }
        if not json_handler.write_json(config_path, config):
            trail.log_operation(
                "setup_failed",
                {"project_path": project_path, "reason": "config write failed"},
            )
            return None

    ignore_path = builder.build_ignore_path(project_path)
    if not ignore_path.exists():
        with open(ignore_path, "w", encoding="utf-8") as f:
            f.write(_build_backupignore())

    trail.log_operation("setup_complete", {"project_path": project_path})
    return backup_dir


# =============================================
