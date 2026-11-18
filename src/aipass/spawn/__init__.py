# =================== AIPass ====================
# Name: __init__.py
# Description: Spawn's front door: the names other branches take, each loaded from its home
# Version: 2.1.0
# Created: 2026-03-05
# Modified: 2026-11-17
# =============================================

"""Spawn - the agent factory: mint, update, retire and register citizens.

Public surface for other branches: from aipass.spawn import <name>. apps/spawn.py stays the command door.
"""

import importlib
from typing import Any

_HANDLERS = "aipass.spawn.apps.handlers"
_CLASSES = f"{_HANDLERS}.class_registry"
_REGISTRY = f"{_HANDLERS}.registry"

_HOMES = {
    "spawn_agent": "aipass.spawn.apps.modules.core",
    "CITIZEN_CLASSES": _CLASSES,
    "FORBIDDEN_CLASSES": _CLASSES,
    "LEGACY_CLASSES": _CLASSES,
    "get_available_classes": _CLASSES,
    "get_template_dir": _CLASSES,
    "refuse_legacy_class": _CLASSES,
    "refuse_retired_or_forbidden": _CLASSES,
    "validate_class": _CLASSES,
    "find_registry": _REGISTRY,
    "get_owner": _REGISTRY,
    "is_owner": _REGISTRY,
    "registry_is_writable_document": _REGISTRY,
    "render_bootstrap_trinity": f"{_HANDLERS}.bootstrap_render",
}

__all__ = list(_HOMES)


def __getattr__(name: str) -> Any:
    """Hand out a door name from its home on each access; nothing under apps loads at package import."""
    if name not in _HOMES:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    # Never cached on the package: a patch on the home attribute must reach every caller reading through here.
    return getattr(importlib.import_module(_HOMES[name]), name)


def __dir__() -> list:
    """Public names, whether or not they have been resolved yet."""
    return sorted(set(globals()) | set(__all__))
