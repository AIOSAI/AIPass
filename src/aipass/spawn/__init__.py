# =================== AIPass ====================
# Name: __init__.py
# Description: Spawn's front door: the names other branches take, each loaded from its home
# Version: 2.4.0
# Created: 2026-03-05
# Modified: 2026-11-21
# =============================================

"""Spawn - the agent factory: mint, update, retire and register citizens.

Public surface for other branches: from aipass.spawn import <name>. apps/spawn.py stays the command door.
"""

import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # each name typed from its home
    from aipass.spawn.apps.handlers.bootstrap_render import render_bootstrap_trinity, restore_citizen
    from aipass.spawn.apps.handlers.class_registry import (
        CITIZEN_CLASSES,
        FORBIDDEN_CLASSES,
        LEGACY_CLASSES,
        get_available_classes,
        get_template_dir,
        refuse_legacy_class,
        refuse_retired_or_forbidden,
        validate_class,
    )
    from aipass.spawn.apps.handlers.registry import find_registry, get_owner, is_owner, registry_is_writable_document
    from aipass.spawn.apps.handlers.sync_registry_ops import rebuild_registry
    from aipass.spawn.apps.modules.core import spawn_agent

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
    "rebuild_registry": f"{_HANDLERS}.sync_registry_ops",
    "render_bootstrap_trinity": f"{_HANDLERS}.bootstrap_render",
    "restore_citizen": f"{_HANDLERS}.bootstrap_render",
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
