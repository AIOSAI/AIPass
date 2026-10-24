# =================== AIPass ====================
# Name: setup.py
# Description: Project setup handler — scaffold .backup/ directory in target
# Version: 1.1.2
# Created: 2026-04-16
# Modified: 2026-10-24
# =============================================

"""Project setup handler."""

from datetime import datetime, timezone
from pathlib import Path

from ..path.module_paths import branch_root
from ..audit import trail
from ..json import json_handler
from ..path import builder
from .config import DEFAULTS

_TEMPLATE_PATH = branch_root(__file__, 3) / "templates" / "backupignore.template"


def _build_backupignore() -> str:
    """Read the seed .backupignore content from the template file."""
    if not _TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"Seed template missing: {_TEMPLATE_PATH} — cannot create a safe .backupignore")
    return _TEMPLATE_PATH.read_text(encoding="utf-8")


def create_backup_dir(project_path: str) -> Path | None:
    """Create the ``.backup/`` scaffold inside a project path; None on failure, config write included."""
    root = Path(project_path)
    if not root.is_dir():
        trail.log_operation("setup_failed", {"project_path": project_path, "reason": "not a directory"})
        return None

    backup_dir = builder.backup_root(project_path)
    (backup_dir / "snapshots").mkdir(parents=True, exist_ok=True)

    config_path = builder.build_config_path(project_path)
    if not config_path.exists():
        config = {
            **DEFAULTS,
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
        # Read before writing: a missing template must not leave a zero-byte file exists() never reseeds.
        content = _build_backupignore()
        ignore_path.write_text(content, encoding="utf-8")

    trail.log_operation("setup_complete", {"project_path": project_path})
    return backup_dir
