# =================== AIPass ====================
# Name: __init__.py
# Description: Skills' front door: the skill functions and contract constants other branches import
# Version: 2.2.0
# Created: 2026-03-07
# Modified: 2026-11-17
# =============================================

"""Skills' import door: `from aipass.skills import <name>`, each read from its home skill on access (PEP 562)."""

import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aipass.skills.lib.screen_lock.handler import METHOD_DBUS as SCREEN_LOCK_METHOD_DBUS
    from aipass.skills.lib.screen_lock.handler import METHOD_LOGINCTL as SCREEN_LOCK_METHOD_LOGINCTL
    from aipass.skills.lib.screen_lock.handler import REASON_NO_READER as SCREEN_LOCK_REASON_NO_READER
    from aipass.skills.lib.screen_lock.handler import REASON_NO_SESSION as SCREEN_LOCK_REASON_NO_SESSION
    from aipass.skills.lib.screen_lock.handler import REASON_READ_FAILED as SCREEN_LOCK_REASON_READ_FAILED
    from aipass.skills.lib.screen_lock.handler import REASON_SWITCH_UNREADABLE as SCREEN_LOCK_REASON_SWITCH_UNREADABLE
    from aipass.skills.lib.screen_lock.handler import REASON_SWITCHED_OFF as SCREEN_LOCK_REASON_SWITCHED_OFF
    from aipass.skills.lib.screen_lock.handler import lock_screen, lock_state
    from aipass.skills.lib.system_status.handler import PSUTIL_RECIPE as SYSTEM_STATUS_PSUTIL_RECIPE
    from aipass.skills.lib.system_status.handler import REASONS as SYSTEM_STATUS_REASONS
    from aipass.skills.lib.system_status.handler import SECTIONS as SYSTEM_STATUS_SECTIONS
    from aipass.skills.lib.system_status.handler import machine_processes, machine_vitals

_SCREEN_LOCK = "aipass.skills.lib.screen_lock.handler"
_SYSTEM_STATUS = "aipass.skills.lib.system_status.handler"
# served name -> (home module, home name); a contract constant carries its skill's prefix so two skills never collide.
_HOMES = {
    "lock_state": (_SCREEN_LOCK, "lock_state"),
    "lock_screen": (_SCREEN_LOCK, "lock_screen"),
    "machine_processes": (_SYSTEM_STATUS, "machine_processes"),
    "machine_vitals": (_SYSTEM_STATUS, "machine_vitals"),
    "SYSTEM_STATUS_REASONS": (_SYSTEM_STATUS, "REASONS"),
    "SYSTEM_STATUS_SECTIONS": (_SYSTEM_STATUS, "SECTIONS"),
    "SYSTEM_STATUS_PSUTIL_RECIPE": (_SYSTEM_STATUS, "PSUTIL_RECIPE"),
    "SCREEN_LOCK_METHOD_LOGINCTL": (_SCREEN_LOCK, "METHOD_LOGINCTL"),
    "SCREEN_LOCK_METHOD_DBUS": (_SCREEN_LOCK, "METHOD_DBUS"),
    "SCREEN_LOCK_REASON_NO_SESSION": (_SCREEN_LOCK, "REASON_NO_SESSION"),
    "SCREEN_LOCK_REASON_NO_READER": (_SCREEN_LOCK, "REASON_NO_READER"),
    "SCREEN_LOCK_REASON_READ_FAILED": (_SCREEN_LOCK, "REASON_READ_FAILED"),
    "SCREEN_LOCK_REASON_SWITCHED_OFF": (_SCREEN_LOCK, "REASON_SWITCHED_OFF"),
    "SCREEN_LOCK_REASON_SWITCH_UNREADABLE": (_SCREEN_LOCK, "REASON_SWITCH_UNREADABLE"),
}

__all__ = list(_HOMES)


def __getattr__(name: str) -> Any:
    """Hand out a door name from its home on each access; nothing under lib loads at package import."""
    # importlib, never a from-import: that re-enters this package and recurses.
    if name not in _HOMES:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    # Never cached on the package: a patch on the home attribute must reach every caller reading through here.
    module_name, attribute = _HOMES[name]
    return getattr(importlib.import_module(module_name), attribute)


def __dir__() -> list:
    """Public names, whether or not they have been resolved yet."""
    return sorted(set(globals()) | set(__all__))
