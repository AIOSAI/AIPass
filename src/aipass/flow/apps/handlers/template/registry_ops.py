# =================== AIPass ====================
# Name: registry_ops.py
# Description: Template registry CRUD operations
# Version: 1.0.0
# Created: 2026-03-18
# Modified: 2026-03-18
# =============================================

"""Template Registry CRUD Operations.

Core operations for loading, saving, and managing the template registry.
The registry maps template directory names to plan type prefixes so that
:mod:`plan_type_loader` can discover plan types dynamically instead of
relying on a hardcoded ``PREFIX_MAP``.

The registry lives at ``flow_json/template_registry.json``.

Usage:
    from aipass.flow.apps.handlers.template.registry_ops import (
        load_registry, save_registry, add_type, remove_type,
        get_prefix_map, get_type_map, scan_unregistered,
    )

    registry = load_registry()
    add_type("task_plans", "TPLAN")
    prefix_map = get_prefix_map()          # {"flow_plans": "FPLAN", ...}
    type_map   = get_type_map()            # {"fplan": "flow_plans", ...}
    unregistered = scan_unregistered()     # dirs without a registry entry
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.flow.apps.handlers.json import json_handler

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MODULE_NAME = "registry_ops"

# registry_ops.py -> template/ -> handlers/ -> apps/ -> flow/
FLOW_ROOT: Path = Path(__file__).resolve().parents[3]
REGISTRY_PATH: Path = FLOW_ROOT / "flow_json" / "template_registry.json"

# Default seed data -- ensures existing plan types work on fresh install
_DEFAULT_TYPES: Dict[str, Dict[str, str]] = {
    "flow_plans": {
        "prefix": "FPLAN",
        "shorthand": "fplan",
        "created": "2026-03-18",
        "registered_by": "system",
    },
    "dev_plans": {
        "prefix": "DPLAN",
        "shorthand": "dplan",
        "created": "2026-03-18",
        "registered_by": "system",
    },
}

# Plan types that cannot be removed via remove_type()
_PROTECTED_TYPES: frozenset[str] = frozenset({"flow_plans", "dev_plans"})


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _today() -> str:
    """Return today's date as ISO string."""
    return datetime.now().date().isoformat()


def _registry_path() -> Path:
    """Return the current registry file path.

    Wrapped in a function so tests can monkeypatch ``REGISTRY_PATH``.
    """
    return REGISTRY_PATH


def _empty_registry() -> Dict[str, Any]:
    """Return a new registry seeded with the default plan types."""
    today = _today()
    return {
        "types": dict(_DEFAULT_TYPES),
        "metadata": {
            "version": "1.0.0",
            "last_updated": today,
            "type_count": len(_DEFAULT_TYPES),
        },
    }


# ---------------------------------------------------------------------------
# Core CRUD
# ---------------------------------------------------------------------------


def load_registry() -> Dict[str, Any]:
    """Load the template registry from disk, auto-creating if missing.

    Auto-heals missing ``types`` or ``metadata`` keys.

    Returns:
        Registry dict with ``types`` and ``metadata`` keys.
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

    # Auto-heal: must be a dict
    if not isinstance(data, dict):
        logger.warning("[%s] Invalid registry structure, recreating", MODULE_NAME)
        registry = _empty_registry()
        save_registry(registry)
        return registry

    # Auto-heal: missing "types" key
    if "types" not in data:
        logger.warning("[%s] Missing 'types' key, recreating with defaults", MODULE_NAME)
        data["types"] = dict(_DEFAULT_TYPES)

    # Auto-heal: missing "metadata" key
    if "metadata" not in data:
        data["metadata"] = {
            "version": "1.0.0",
            "last_updated": _today(),
            "type_count": len(data["types"]),
        }

    # Auto-heal: prune orphans + register new dirs
    if _prune_orphaned_types(data):
        save_registry(data)
    if _auto_register_new_types(data):
        save_registry(data)

    return data


def _prune_orphaned_types(data: Dict[str, Any]) -> bool:
    """Remove registry entries whose template directory no longer exists.

    Returns True if any entries were pruned.
    """
    templates_dir = FLOW_ROOT / "templates"
    orphaned = [d for d in data["types"] if d not in _PROTECTED_TYPES and not (templates_dir / d).is_dir()]
    if not orphaned:
        return False

    plan_registry_dir = FLOW_ROOT / "flow_json"
    for dir_name in orphaned:
        entry = data["types"][dir_name]
        shorthand = entry.get("shorthand", entry.get("prefix", "").lower())
        logger.info("[%s] Auto-pruning orphaned type '%s' (directory missing)", MODULE_NAME, dir_name)
        del data["types"][dir_name]
        if shorthand:
            plan_reg = plan_registry_dir / f"{shorthand}_registry.json"
            if plan_reg.exists():
                plan_reg.unlink()
                logger.info("[%s] Removed orphaned plan registry: %s", MODULE_NAME, plan_reg.name)
    return True


def _auto_register_new_types(data: Dict[str, Any]) -> bool:
    """Detect unregistered template directories and register them.

    Returns True if any new types were registered.
    """
    templates_dir = FLOW_ROOT / "templates"
    if not templates_dir.is_dir():
        return False

    registered = set(data["types"].keys())
    used_prefixes = {entry.get("prefix", "").upper() for entry in data["types"].values()}
    changed = False

    for child in sorted(templates_dir.iterdir()):
        if not child.is_dir() or child.name.startswith(("_", ".")) or child.name == "__pycache__":
            continue
        if child.name in registered or not list(child.glob("*.md")):
            continue
        prefix = _derive_prefix(child.name, used_prefixes)
        if prefix is None:
            continue  # Collision — needs manual registration
        shorthand = prefix.lower()
        data["types"][child.name] = {
            "prefix": prefix,
            "shorthand": shorthand,
            "created": _today(),
            "registered_by": "auto",
        }
        used_prefixes.add(prefix)
        registered.add(child.name)
        changed = True
        logger.info("[%s] Auto-registered new type '%s' with prefix %s", MODULE_NAME, child.name, prefix)
        _create_plan_registry(shorthand)
    return changed


def _derive_prefix(dir_name: str, used: set) -> str | None:
    """Derive a unique prefix from a directory name, or None if collision."""
    first_word = dir_name.split("_")[0]
    prefix = (first_word[0].upper() + "PLAN") if first_word else "XPLAN"
    if prefix in used and len(first_word) > 1:
        prefix = first_word[:2].upper() + "PLAN"
    return None if prefix in used else prefix


def _create_plan_registry(shorthand: str) -> None:
    """Create an empty plan registry JSON for a new type."""
    plan_reg = FLOW_ROOT / "flow_json" / f"{shorthand}_registry.json"
    if plan_reg.exists():
        return
    try:
        plan_reg.parent.mkdir(parents=True, exist_ok=True)
        with open(plan_reg, "w", encoding="utf-8") as fh:
            json.dump({"next_number": 1, "plans": {}, "last_updated": _today()}, fh, indent=2)
    except OSError as exc:
        logger.warning("[%s] Failed to create plan registry for %s: %s", MODULE_NAME, shorthand, exc)


def save_registry(data: Dict[str, Any]) -> bool:
    """Save the template registry to disk.

    Updates ``metadata.last_updated`` and ``metadata.type_count`` before
    writing.

    Args:
        data: Registry dict to persist.

    Returns:
        True if saved successfully, False on error.
    """
    path = _registry_path()

    if not isinstance(data, dict) or "types" not in data:
        logger.error("[%s] Cannot save invalid registry structure", MODULE_NAME)
        return False

    # Refresh metadata
    data.setdefault("metadata", {})
    data["metadata"]["last_updated"] = _today()
    data["metadata"]["type_count"] = len(data["types"])

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        json_handler.log_operation(
            "save_template_registry",
            {"type_count": data["metadata"]["type_count"]},
            module_name=MODULE_NAME,
        )
        return True
    except OSError as exc:
        logger.error("[%s] Failed to save registry: %s", MODULE_NAME, exc)
        return False


def add_type(
    dir_name: str,
    prefix: str,
    registered_by: str = "flow",
) -> bool:
    """Register a new plan type in the template registry.

    Validates that:
    - ``dir_name`` is not already registered.
    - ``prefix`` is not already taken by another type.
    - The template directory exists under ``templates/``.
    - The directory contains at least one ``.md`` file.

    On success, also creates an empty plan registry JSON at
    ``flow_json/<prefix_lower>_registry.json``.

    Args:
        dir_name: Subdirectory name under ``templates/``.
        prefix: Plan ID prefix (e.g. ``"TPLAN"``).
        registered_by: Who registered this type.

    Returns:
        True if added, False on validation failure or save error.
    """
    registry = load_registry()

    # Validate: dir_name not already registered
    if dir_name in registry["types"]:
        logger.error(
            "[%s] Type '%s' is already registered",
            MODULE_NAME,
            dir_name,
        )
        return False

    # Validate: prefix not already taken (case-insensitive)
    if prefix_exists(prefix):
        logger.error(
            "[%s] Prefix '%s' is already in use by another type",
            MODULE_NAME,
            prefix,
        )
        return False

    # Validate: template directory exists
    templates_dir = FLOW_ROOT / "templates" / dir_name
    if not templates_dir.is_dir():
        logger.error(
            "[%s] Templates directory not found: %s",
            MODULE_NAME,
            templates_dir,
        )
        return False

    # Validate: directory contains at least one .md file
    md_files = list(templates_dir.glob("*.md"))
    if not md_files:
        logger.error(
            "[%s] No .md template files found in %s",
            MODULE_NAME,
            templates_dir,
        )
        return False

    # Derive shorthand from prefix
    shorthand = prefix.lower()

    # Add entry
    registry["types"][dir_name] = {
        "prefix": prefix,
        "shorthand": shorthand,
        "created": _today(),
        "registered_by": registered_by,
    }

    # Save registry first
    if not save_registry(registry):
        return False

    # Auto-create empty plan registry for the new type
    plan_registry_path = FLOW_ROOT / "flow_json" / f"{shorthand}_registry.json"
    if not plan_registry_path.exists():
        empty_plan_registry: Dict[str, Any] = {
            "next_number": 1,
            "plans": {},
            "last_updated": _today(),
        }
        try:
            with open(plan_registry_path, "w", encoding="utf-8") as fh:
                json.dump(empty_plan_registry, fh, indent=2, ensure_ascii=False)
        except OSError as exc:
            logger.warning(
                "[%s] Created type but failed to create plan registry: %s",
                MODULE_NAME,
                exc,
            )

    json_handler.log_operation(
        "add_type",
        {"dir_name": dir_name, "prefix": prefix, "registered_by": registered_by},
        module_name=MODULE_NAME,
    )
    return True


def remove_type(dir_name: str) -> bool:
    """Unregister a plan type from the template registry.

    Protected types (``flow_plans``, ``dev_plans``) cannot be removed.
    This only removes the registry entry -- it does **not** delete the
    template directory or the plan registry JSON file.

    Args:
        dir_name: The type directory name to unregister.

    Returns:
        True if removed, False if not found or protected.
    """
    registry = load_registry()

    if dir_name not in registry["types"]:
        logger.error("[%s] Type '%s' not found in registry", MODULE_NAME, dir_name)
        return False

    if dir_name in _PROTECTED_TYPES:
        logger.error(
            "[%s] Cannot remove protected type '%s'",
            MODULE_NAME,
            dir_name,
        )
        return False

    del registry["types"][dir_name]

    result = save_registry(registry)
    if result:
        json_handler.log_operation(
            "remove_type",
            {"dir_name": dir_name},
            module_name=MODULE_NAME,
        )
    return result


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------


def prefix_exists(prefix: str) -> bool:
    """Check whether any registered type uses *prefix* (case-insensitive).

    Args:
        prefix: The prefix to look for.

    Returns:
        True if the prefix is already in use.
    """
    registry = load_registry()
    upper = prefix.upper()
    return any(entry.get("prefix", "").upper() == upper for entry in registry["types"].values())


def get_prefix_map() -> Dict[str, str]:
    """Return ``{dir_name: prefix}`` for all registered types.

    This is the dynamic replacement for the hardcoded ``PREFIX_MAP`` in
    :mod:`plan_type_loader`.
    """
    registry = load_registry()
    return {dir_name: entry["prefix"] for dir_name, entry in registry["types"].items() if "prefix" in entry}


def get_type_map() -> Dict[str, str]:
    """Return ``{shorthand: dir_name}`` for all registered types.

    Always includes ``{"default": "flow_plans"}`` so callers can resolve
    the bare ``flow`` command without extra logic.
    """
    registry = load_registry()
    result: Dict[str, str] = {"default": "flow_plans"}
    for dir_name, entry in registry["types"].items():
        shorthand = entry.get("shorthand", entry.get("prefix", "").lower())
        if shorthand:
            result[shorthand] = dir_name
    return result


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def scan_unregistered() -> list[Dict[str, str | int | list[str]]]:
    """Scan ``templates/`` for directories not yet in the registry.

    Skips directories whose names start with ``_`` or ``.``, and
    directories that are already registered.

    Returns:
        List of dicts, each with ``dir_name``, ``template_count``, and
        ``templates`` (list of ``.md`` file stems).
    """
    registry = load_registry()
    registered = set(registry["types"].keys())
    templates_dir = FLOW_ROOT / "templates"

    if not templates_dir.is_dir():
        logger.warning(
            "[%s] Templates directory not found: %s",
            MODULE_NAME,
            templates_dir,
        )
        return []

    unregistered: list[Dict[str, str | int | list[str]]] = []

    for child in sorted(templates_dir.iterdir()):
        if not child.is_dir():
            continue
        if child.name.startswith(("_", ".")):
            continue
        if child.name in registered:
            continue

        md_files = sorted(child.glob("*.md"))
        if not md_files:
            continue

        stems = [p.stem for p in md_files]
        unregistered.append(
            {
                "dir_name": child.name,
                "template_count": len(stems),
                "templates": stems,
            }
        )

    return unregistered
