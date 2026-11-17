"""Trigger's import door: `from aipass.trigger import <name>`, each loaded on first access (PEP 562)."""

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aipass.trigger.apps.modules.core import Trigger, trigger

_CORE = "aipass.trigger.apps.modules.core"
_HOMES = {"trigger": _CORE, "Trigger": _CORE}

__all__ = list(_HOMES)


def __getattr__(name: str):
    """Load a door name on first access and cache it on the package."""
    # importlib, never a from-import: that re-enters this package and recurses.
    if name not in _HOMES:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(_HOMES[name]), name)
    globals()[name] = value
    return value


def __dir__() -> list:
    """Public names, whether or not they have been resolved yet."""
    return sorted(set(globals()) | set(__all__))
