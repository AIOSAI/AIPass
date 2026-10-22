# =================== AIPass ====================
# Name: registry.py
# Description: Project registry handler — load/register/lookup backup projects
# Version: 1.2.0
# Created: 2026-04-16
# Modified: 2026-10-21
# =============================================

"""Project registry handler."""

from pathlib import Path

from ..audit import trail
from ..json import json_handler
from ..path.module_paths import branch_root

REGISTRY_PATH = branch_root(__file__, 3) / "backup_json" / "project_registry.json"


def _read_registry() -> dict:
    """Read the registry document."""
    # MUST NOT degrade to {}: register_project writes back what it read, wiping every other registration.
    data = json_handler.read_json(REGISTRY_PATH)
    if data is None:
        if REGISTRY_PATH.exists():
            raise json_handler.InvalidDocument(f"Project registry unreadable: {REGISTRY_PATH}")
        return {}
    if not isinstance(data, dict):
        raise json_handler.InvalidDocument(f"Project registry is not a JSON object: {REGISTRY_PATH}")
    return data


def load_project_registry() -> dict:
    """Load the project registry from disk."""
    projects = _read_registry().get("projects", {})
    trail.log_operation("project_registry_loaded", {"count": len(projects)})
    return projects


def register_project(name: str, path: str) -> bool:
    """Register a new backup project."""
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


def unregister_project(name: str) -> bool:
    """Drop a project from the registry; its .backup/ store stays where it is. False when absent or unwritten."""
    data = _read_registry()
    if data.get("projects", {}).pop(name, None) is None:
        trail.log_operation("project_lookup_miss", {"name": name})
        return False
    if not json_handler.write_json(REGISTRY_PATH, data):
        trail.log_operation("project_unregister_failed", {"name": name})
        return False
    trail.log_operation("project_unregistered", {"name": name})
    return True


def lookup_project(name: str) -> str | None:
    """Resolve a project name to its filesystem path."""
    projects = load_project_registry()
    entry = projects.get(name)
    if entry:
        return entry.get("path")
    trail.log_operation("project_lookup_miss", {"name": name})
    return None


def list_projects() -> dict:
    """Return all registered projects."""
    return load_project_registry()
