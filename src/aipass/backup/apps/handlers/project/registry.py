# =================== AIPass ====================
# Name: registry.py
# Description: Project registry handler — load/register/lookup backup projects
# Version: 1.0.0
# Created: 2026-04-16
# Modified: 2026-04-23
# =============================================

"""Project registry handler.

Tracks registered backup projects (name -> absolute path) in the central
backup project registry stored at backup_json/project_registry.json.
"""

from pathlib import Path

from ..path.module_paths import branch_root
from ..json import json_handler

REGISTRY_PATH = branch_root(__file__, 3) / "backup_json" / "project_registry.json"


def load_project_registry() -> dict:
    """Load the project registry from disk.

    Returns:
        Dict mapping project name to project metadata.
    """
    data = json_handler.load_json(str(REGISTRY_PATH))
    json_handler.log_operation("project_registry_loaded", {"count": len(data.get("projects", {}))})
    return data.get("projects", {})


def register_project(name: str, path: str) -> bool:
    """Register a new backup project.

    Args:
        name: Project identifier (unique).
        path: Absolute path to the project root.

    Returns:
        True when the project was added or updated.
    """
    data = json_handler.load_json(str(REGISTRY_PATH))
    if "projects" not in data:
        data["projects"] = {}

    data["projects"][name] = {
        "path": str(Path(path).resolve()),
        "name": name,
    }
    json_handler.save_json(str(REGISTRY_PATH), data)
    json_handler.log_operation("project_registered", {"name": name, "path": path})
    return True


def lookup_project(name: str) -> str | None:
    """Resolve a project name to its filesystem path.

    Args:
        name: Registered project identifier.

    Returns:
        Absolute path string or None when not registered.
    """
    projects = load_project_registry()
    entry = projects.get(name)
    if entry:
        return entry.get("path")
    json_handler.log_operation("project_lookup_miss", {"name": name})
    return None


def list_projects() -> dict:
    """Return all registered projects."""
    return load_project_registry()


# =============================================
