# =================== AIPass ====================
# Name: __init__.py
# Description: Skills' front door: the skill functions other branches import
# Version: 2.0.0
# Created: 2026-03-07
# Modified: 2026-11-17
# =============================================

"""Skills' import door: `from aipass.skills import <name>`, each read from its home skill on access (PEP 562)."""

import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aipass.skills.lib.screen_lock.handler import lock_screen, lock_state
    from aipass.skills.lib.system_status.handler import machine_processes, machine_vitals

_SCREEN_LOCK = "aipass.skills.lib.screen_lock.handler"
_SYSTEM_STATUS = "aipass.skills.lib.system_status.handler"
_HOMES = {
    "lock_state": _SCREEN_LOCK,
    "lock_screen": _SCREEN_LOCK,
    "machine_processes": _SYSTEM_STATUS,
    "machine_vitals": _SYSTEM_STATUS,
}

__all__ = list(_HOMES)


def __getattr__(name: str) -> Any:
    """Hand out a door name from its home on each access; nothing under lib loads at package import."""
    # importlib, never a from-import: that re-enters this package and recurses.
    if name not in _HOMES:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    # Never cached on the package: a patch on the home attribute must reach every caller reading through here.
    return getattr(importlib.import_module(_HOMES[name]), name)


def __dir__() -> list:
    """Public names, whether or not they have been resolved yet."""
    return sorted(set(globals()) | set(__all__))
