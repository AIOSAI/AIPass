"""Trigger's import door: `from aipass.trigger import <name>`, each read from its home on access (PEP 562)."""

import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aipass.trigger.apps.modules.core import Trigger, trigger

_CORE = "aipass.trigger.apps.modules.core"
_HOMES = {"trigger": _CORE, "Trigger": _CORE}

__all__ = list(_HOMES)


def __getattr__(name: str) -> Any:
    """Hand out a door name from its home on each access; nothing under apps loads at package import."""
    # importlib, never a from-import: that re-enters this package and recurses.
    if name not in _HOMES:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    # Never cached on the package: a patch on the home attribute must reach every caller reading through here.
    return getattr(importlib.import_module(_HOMES[name]), name)


def __dir__() -> list:
    """Public names, whether or not they have been resolved yet."""
    return sorted(set(globals()) | set(__all__))
