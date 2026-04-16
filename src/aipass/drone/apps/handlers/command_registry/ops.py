# =================== AIPass ====================
# Name: ops.py
# Description: Registry CRUD operations for custom command shortcuts
# Version: 1.0.0
# Created: 2026-03-17
# Modified: 2026-03-17
# =============================================

"""Registry CRUD Operations for Custom Commands.

Core operations for loading, saving, and managing the drone command registry.
The registry maps shortcut names to full drone commands so users can type
``audit`` instead of ``drone @seedgo audit aipass``.

Usage:
    from aipass.drone.apps.handlers.command_registry.ops import (
        load_registry, save_registry, add_command, remove_command,
    )

    registry = load_registry()
    add_command("audit", "@seedgo", "audit", ["aipass"], "Run audit", "seedgo")
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from aipass.prax import logger
from aipass.drone.apps.handlers.json import json_handler

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MODULE_NAME = "command_registry"

# ops.py -> command_registry/ -> handlers/ -> apps/ -> drone/
_BRANCH_ROOT: Path = Path(__file__).resolve().parents[3]
REGISTRY_FILE: Path = _BRANCH_ROOT / "drone_command_registry.json"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _today() -> str:
    """Return today's date as ISO string."""
    return datetime.now().date().isoformat()


def _empty_registry() -> dict[str, Any]:
    """Return a new empty registry structure."""
    today = _today()
    return {
        "commands": {},
        "metadata": {
            "version": "1.0.0",
            "last_updated": today,
            "command_count": 0,
        },
    }


def _registry_path() -> Path:
    """Return the current registry file path.

    Wrapped in a function so tests can monkeypatch ``ops.REGISTRY_FILE``.
    """
    return REGISTRY_FILE


# ---------------------------------------------------------------------------
# Core CRUD
# ---------------------------------------------------------------------------


def load_registry() -> dict[str, Any]:
    """Load the command registry from disk, auto-creating if missing.

    Returns:
        Registry dict with ``commands`` and ``metadata`` keys.
    """
    path = _registry_path()

    if not path.exists():
        logger.info("[%s] Registry not found, creating at %s", MODULE_NAME, path)
        registry = _empty_registry()
        save_registry(registry)
        return registry

    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("[%s] Corrupt registry, recreating: %s", MODULE_NAME, exc)
        registry = _empty_registry()
        save_registry(registry)
        return registry

    # Auto-heal missing keys
    if not isinstance(data, dict):
        logger.warning("[%s] Invalid registry structure, recreating", MODULE_NAME)
        registry = _empty_registry()
        save_registry(registry)
        return registry

    if "commands" not in data:
        data["commands"] = {}
    if "metadata" not in data:
        data["metadata"] = {
            "version": "1.0.0",
            "last_updated": _today(),
            "command_count": len(data["commands"]),
        }

    return data


def save_registry(data: dict[str, Any]) -> bool:
    """Save the command registry to disk with validation.

    Args:
        data: Registry dict to persist.

    Returns:
        True if saved successfully, False on error.
    """
    path = _registry_path()

    if not isinstance(data, dict) or "commands" not in data:
        logger.error("[%s] Cannot save invalid registry structure", MODULE_NAME)
        return False

    # Refresh metadata
    data.setdefault("metadata", {})
    data["metadata"]["last_updated"] = _today()
    data["metadata"]["command_count"] = len(data["commands"])

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        json_handler.log_operation(
            "save_registry",
            {"command_count": data["metadata"]["command_count"]},
            module_name=MODULE_NAME,
        )
        return True
    except OSError as exc:
        logger.error("[%s] Failed to save registry: %s", MODULE_NAME, exc)
        return False


def add_command(
    name: str,
    target: str,
    command: str,
    args: list[str] | None = None,
    description: str = "",
    source_branch: str = "",
) -> bool:
    """Add a new custom command to the registry.

    Args:
        name: Shortcut name (e.g. ``"audit"``).
        target: Target branch (e.g. ``"@seedgo"``).
        command: Actual command to run on the target.
        args: Extra arguments for the command.
        description: Human-readable description.
        source_branch: Branch the command originated from.

    Returns:
        True if added, False if name already exists or save fails.
    """
    registry = load_registry()

    if name in registry["commands"]:
        logger.warning("[%s] Command '%s' already exists", MODULE_NAME, name)
        return False

    registry["commands"][name] = {
        "name": name,
        "target": target,
        "command": command,
        "args": args if args is not None else [],
        "description": description,
        "created": _today(),
        "source_branch": source_branch,
    }

    result = save_registry(registry)
    if result:
        json_handler.log_operation(
            "add_command",
            {"name": name, "target": target, "command": command},
            module_name=MODULE_NAME,
        )
    return result


def remove_command(name: str) -> bool:
    """Remove a custom command from the registry.

    Args:
        name: Shortcut name to remove.

    Returns:
        True if removed, False if not found or save fails.
    """
    registry = load_registry()

    if name not in registry["commands"]:
        logger.warning("[%s] Command '%s' not found", MODULE_NAME, name)
        return False

    del registry["commands"][name]

    result = save_registry(registry)
    if result:
        json_handler.log_operation(
            "remove_command",
            {"name": name},
            module_name=MODULE_NAME,
        )
    return result


def update_command(name: str, **kwargs: Any) -> bool:
    """Update fields of an existing custom command.

    Args:
        name: Shortcut name to update.
        **kwargs: Fields to update (e.g. ``target="@prax"``, ``description="..."``).

    Returns:
        True if updated, False if not found or save fails.
    """
    registry = load_registry()

    if name not in registry["commands"]:
        logger.warning("[%s] Command '%s' not found for update", MODULE_NAME, name)
        return False

    allowed_keys = {"target", "command", "args", "description", "source_branch"}
    for key, value in kwargs.items():
        if key in allowed_keys:
            registry["commands"][name][key] = value

    result = save_registry(registry)
    if result:
        json_handler.log_operation(
            "update_command",
            {"name": name, "updated_fields": list(kwargs.keys())},
            module_name=MODULE_NAME,
        )
    return result


def command_exists(name: str) -> bool:
    """Check whether a custom command exists in the registry.

    Args:
        name: Shortcut name to check.

    Returns:
        True if the command exists, False otherwise.
    """
    registry = load_registry()
    return name in registry["commands"]
