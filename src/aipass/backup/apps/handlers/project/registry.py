# =================== AIPass ====================
# Name: registry.py
# Description: Project registry handler — load/register/lookup backup projects
# Version: 1.1.0
# Created: 2026-04-16
# Modified: 2026-09-03
# =============================================

"""Project registry handler.

Tracks registered backup projects (name -> absolute path) in the central
backup project registry stored at backup_json/project_registry.json.
"""

from pathlib import Path

from ..audit import trail
from ..json import json_handler
from ..path.module_paths import branch_root

REGISTRY_PATH = branch_root(__file__, 3) / "backup_json" / "project_registry.json"


def _read_registry() -> dict:
    """Read the registry document.

    Returns:
        The document, or an empty one when the registry does not exist yet.

    Raises:
        InvalidDocument: The registry is present but unreadable, or is not a
            JSON object. This is the one read in the branch that MUST NOT
            degrade to an empty dict: register_project writes back what it
            read, so an empty answer here replaces every registration in the
            file with the single project being added.
    """
    data = json_handler.read_json(REGISTRY_PATH)
    if data is None:
        if REGISTRY_PATH.exists():
            raise json_handler.InvalidDocument(f"Project registry unreadable: {REGISTRY_PATH}")
        return {}
    if not isinstance(data, dict):
        raise json_handler.InvalidDocument(f"Project registry is not a JSON object: {REGISTRY_PATH}")
    return data


def load_project_registry() -> dict:
    """Load the project registry from disk.

    Returns:
        Dict mapping project name to project metadata.
    """
    projects = _read_registry().get("projects", {})
    trail.log_operation("project_registry_loaded", {"count": len(projects)})
    return projects


def register_project(name: str, path: str) -> bool:
    """Register a new backup project.

    Args:
        name: Project identifier (unique).
        path: Absolute path to the project root.

    Returns:
        True when the project was added or updated, False when the registry
        could not be written.
    """
    data = _read_registry()
    if "projects" not in data:
        data["projects"] = {}

    data["projects"][name] = {
        "path": str(Path(path).resolve()),
        "name": name,
    }
    if not json_handler.write_json(REGISTRY_PATH, data):
        trail.log_operation("project_register_failed", {"name": name, "path": path})
        return False
    trail.log_operation("project_registered", {"name": name, "path": path})
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
    trail.log_operation("project_lookup_miss", {"name": name})
    return None


def list_projects() -> dict:
    """Return all registered projects."""
    return load_project_registry()


# =============================================
