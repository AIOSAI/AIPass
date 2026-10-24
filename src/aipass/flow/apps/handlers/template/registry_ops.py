# =================== AIPass ====================
# Name: registry_ops.py
# Description: Template registry CRUD operations
# Version: 1.2.0
# Created: 2026-03-18
# Modified: 2026-10-23
# =============================================

"""Template Registry CRUD Operations.

Maps template directory names to plan type prefixes (flow_json/template_registry.json),
so plan types are discovered from disk instead of a hardcoded PREFIX_MAP.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Tuple

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.flow.apps.handlers.json import json_handler
from aipass.flow.apps.handlers.repo_root import module_file

MODULE_NAME = "registry_ops"

# registry_ops.py -> template/ -> handlers/ -> apps/ -> flow/
FLOW_ROOT: Path = module_file(__file__).parents[3]
REGISTRY_PATH: Path = FLOW_ROOT / "flow_json" / "template_registry.json"

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

_PROTECTED_TYPES: frozenset[str] = frozenset({"flow_plans", "dev_plans"})


def _today() -> str:
    """Return today's date as ISO string."""
    return datetime.now().date().isoformat()


def _registry_path() -> Path:
    """Return the current registry file path; a function so tests can monkeypatch REGISTRY_PATH."""
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


def _read_or_seed(path: Path) -> Tuple[Dict[str, Any], bool]:
    """Return ``(registry, seeded)`` for `path`, seeding defaults when unusable.

    The seed is returned, not saved: the caller runs auto-discovery first so a fresh install
    writes its file once, complete.
    """
    if not path.exists():
        logger.info("[%s] Registry not found, creating at %s", MODULE_NAME, path)
        return _empty_registry(), True

    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("[%s] Corrupt registry, recreating: %s", MODULE_NAME, exc)
        return _empty_registry(), True

    if not isinstance(data, dict):
        logger.warning("[%s] Invalid registry structure, recreating", MODULE_NAME)
        return _empty_registry(), True

    return data, False


def load_registry() -> Dict[str, Any]:
    """Load the template registry from disk, auto-creating if missing.

    Auto-discovery runs on a seeded registry too: the registered set must not depend on how
    many times it has been asked for.
    """
    path = _registry_path()
    data, seeded = _read_or_seed(path)

    if "types" not in data:
        logger.warning("[%s] Missing 'types' key, recreating with defaults", MODULE_NAME)
        data["types"] = dict(_DEFAULT_TYPES)

    if "metadata" not in data:
        data["metadata"] = {
            "version": "1.0.0",
            "last_updated": _today(),
            "type_count": len(data["types"]),
        }

    # A seeded registry is always written, or a corrupt file is re-parsed and re-warned every read.
    changed = _prune_orphaned_types(data)
    changed = _auto_register_new_types(data) or changed
    if changed or seeded:
        save_registry(data)

    return data


def _prune_orphaned_types(data: Dict[str, Any]) -> bool:
    """Remove registry entries whose template directory no longer exists.

    The type's plan registry stays on disk: a directory missing for a moment must not cost its plan rows.
    """
    templates_dir = FLOW_ROOT / "templates"
    orphaned = [d for d in data["types"] if d not in _PROTECTED_TYPES and not (templates_dir / d).is_dir()]
    for dir_name in orphaned:
        logger.info("[%s] Auto-pruning orphaned type '%s' (directory missing)", MODULE_NAME, dir_name)
        del data["types"][dir_name]
    return bool(orphaned)


def _auto_register_new_types(data: Dict[str, Any]) -> bool:
    """Detect unregistered template directories and register them."""
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
    """Derive a unique prefix from a directory name, or None if collision.

    One initial per word, trailing ``plans`` dropped: ``team_dev_plans`` -> ``TDPLAN``. Must be
    deterministic, or existing plan files are unreadable on a new clone. Only the collision
    fallback (first two letters of the first word) consults *used*.
    """
    words = [word for word in dir_name.split("_") if word]
    if words and words[-1].lower() == "plans" and len(words) > 1:
        words = words[:-1]
    prefix = ("".join(word[0] for word in words).upper() + "PLAN") if words else "XPLAN"
    first_word = words[0] if words else ""
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

    Returns False only when the write failed (OSError).
    Raises ValueError when ``data`` is not a dict with ``types``: a caller's bug, not a failed write.
    """
    path = _registry_path()

    if not isinstance(data, dict) or "types" not in data:
        raise ValueError(f"[{MODULE_NAME}] Cannot save invalid registry structure: {type(data).__name__}")

    data.setdefault("metadata", {})
    data["metadata"]["last_updated"] = _today()
    data["metadata"]["type_count"] = len(data["types"])

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # tmp + replace: a reader of a half-written file would reseed the defaults over it.
        tmp_path = path.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        os.replace(tmp_path, path)
        json_handler.log_operation(
            "save_template_registry",
            {"type_count": data["metadata"]["type_count"]},
            module_name=MODULE_NAME,
        )
        return True
    except OSError as exc:
        logger.error("[%s] Failed to save registry: %s", MODULE_NAME, exc)
        return False


def _try_override_auto_entry(registry: Dict[str, Any], dir_name: str, new_prefix: str) -> str | None:
    """Remove an auto-registered entry so add_type() can re-add with explicit prefix.

    Returns an error message on failure, or None on success.
    """
    existing = registry["types"][dir_name]
    old_shorthand = existing.get("shorthand", existing.get("prefix", "").lower())
    old_prefix = existing.get("prefix", "")

    if old_prefix.upper() != new_prefix.upper():
        old_reg = FLOW_ROOT / "flow_json" / f"{old_shorthand}_registry.json"
        if old_reg.exists():
            has_plans = _auto_reg_has_plans(old_reg)
            if has_plans:
                return f"Cannot override auto-registered '{dir_name}' — {old_reg.name} has existing plans"
            old_reg.unlink()

    del registry["types"][dir_name]
    logger.info(
        "[%s] Overriding auto-registered type '%s' (%s -> %s)",
        MODULE_NAME,
        dir_name,
        old_prefix,
        new_prefix,
    )
    return None


def _auto_reg_has_plans(reg_path: Path) -> bool:
    """Check whether a plan registry file contains any plans."""
    try:
        with open(reg_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return bool(data.get("plans"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("[%s] Could not read plan registry %s: %s", MODULE_NAME, reg_path.name, exc)
        return False


def add_type(
    dir_name: str,
    prefix: str,
    registered_by: str = "flow",
) -> bool:
    """Register a new plan type in the template registry."""
    registry = load_registry()

    existing = registry["types"].get(dir_name)
    if existing and existing.get("registered_by") != "auto":
        logger.error(
            "[%s] Type '%s' is already registered (by %s)",
            MODULE_NAME,
            dir_name,
            existing.get("registered_by", "unknown"),
        )
        return False

    if existing and existing.get("registered_by") == "auto":
        override_err = _try_override_auto_entry(registry, dir_name, prefix)
        if override_err:
            logger.error("[%s] %s", MODULE_NAME, override_err)
            return False

    upper = prefix.upper()
    if any(entry.get("prefix", "").upper() == upper for d, entry in registry["types"].items() if d != dir_name):
        logger.error(
            "[%s] Prefix '%s' is already in use by another type",
            MODULE_NAME,
            prefix,
        )
        return False

    templates_dir = FLOW_ROOT / "templates" / dir_name
    if not templates_dir.is_dir():
        logger.error(
            "[%s] Templates directory not found: %s",
            MODULE_NAME,
            templates_dir,
        )
        return False

    md_files = list(templates_dir.glob("*.md"))
    if not md_files:
        logger.error(
            "[%s] No .md template files found in %s",
            MODULE_NAME,
            templates_dir,
        )
        return False

    shorthand = prefix.lower()

    registry["types"][dir_name] = {
        "prefix": prefix,
        "shorthand": shorthand,
        "created": _today(),
        "registered_by": registered_by,
    }

    if not save_registry(registry):
        return False

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
    """Unregister a plan type; the template directory and plan registry file are kept."""
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


def get_prefix_map() -> Dict[str, str]:
    """Return ``{dir_name: prefix}`` for all registered types."""
    registry = load_registry()
    return {dir_name: entry["prefix"] for dir_name, entry in registry["types"].items() if "prefix" in entry}


def get_type_map() -> Dict[str, str]:
    """Return ``{shorthand: dir_name}`` for all registered types.

    Always includes ``{"default": "flow_plans"}`` so the bare ``flow`` command resolves.
    """
    registry = load_registry()
    result: Dict[str, str] = {"default": "flow_plans"}
    for dir_name, entry in registry["types"].items():
        shorthand = entry.get("shorthand", entry.get("prefix", "").lower())
        if shorthand:
            result[shorthand] = dir_name
    return result


def scan_unregistered() -> list[Dict[str, str | int | list[str]]]:
    """Scan ``templates/`` for directories not yet in the registry."""
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
