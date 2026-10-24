# =================== AIPass ====================
# Name: ops.py
# Description: Registry CRUD operations for custom command shortcuts
# Version: 1.0.3
# Created: 2026-03-17
# Modified: 2026-10-23
# =============================================

"""Registry CRUD Operations for Custom Commands.

The registry maps shortcut names to full drone commands (``audit`` for
``drone @seedgo audit aipass``).
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from aipass.prax import logger

try:
    import fcntl
except ImportError:
    fcntl = None  # type: ignore[assignment]
    logger.info("command registry: fcntl unavailable (Windows) — concurrent writers are not serialised")
from aipass.drone.apps.handlers.exceptions import RegistryError
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.module_root import module_file

MODULE_NAME = "command_registry"

# ops.py -> command_registry/ -> handlers/ -> apps/ -> drone/
_BRANCH_ROOT: Path = module_file(__file__).parents[3]
REGISTRY_FILE: Path = _BRANCH_ROOT / "drone_command_registry.json"


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
    """Return the current registry file path, read at call time so tests can monkeypatch ``ops.REGISTRY_FILE``."""
    return REGISTRY_FILE


@contextmanager
def _registry_lock() -> Iterator[None]:
    """Hold an exclusive lock on a sibling .lock file so load+modify+save is not interleaved."""
    path = _registry_path()
    if fcntl is None:
        yield
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path.with_name(path.name + ".lock"), "a", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def load_registry() -> dict[str, Any]:
    """Load the command registry from disk; a missing file is an empty registry, and nothing is written.

    Raises RegistryError for an unreadable, non-JSON or non-object file, and
    writes nothing: recreating would bury damaged commands someone could repair.
    """
    path = _registry_path()

    if not path.exists():
        return _empty_registry()

    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except OSError as exc:
        raise RegistryError(f"command registry {path} could not be read ({type(exc).__name__}: {exc})") from exc
    except json.JSONDecodeError as exc:
        raise RegistryError(f"command registry {path} is not JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise RegistryError(f"command registry {path} is not a JSON object ({type(data).__name__})")

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
    """Save the command registry to disk with validation: True if written, False on error."""
    path = _registry_path()

    if not isinstance(data, dict) or "commands" not in data:
        logger.error("[%s] Cannot save invalid registry structure", MODULE_NAME)
        return False

    data.setdefault("metadata", {})
    data["metadata"]["last_updated"] = _today()
    data["metadata"]["command_count"] = len(data["commands"])

    # Atomic replace: a concurrent reader never sees an empty or half-written file.
    if not json_handler.write_json(path, data):
        logger.error("[%s] Failed to save registry %s", MODULE_NAME, path)
        return False
    json_handler.log_operation(
        "save_registry",
        {"command_count": data["metadata"]["command_count"]},
        module_name=MODULE_NAME,
    )
    return True


def add_command(
    name: str,
    target: str,
    command: str,
    args: list[str] | None = None,
    description: str = "",
    source_branch: str = "",
) -> bool:
    """Add a new custom command to the registry; False if the name exists or the save fails."""
    with _registry_lock():
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
    """Remove a custom command from the registry; False if not found or the save fails."""
    with _registry_lock():
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
