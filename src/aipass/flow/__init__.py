# =================== AIPass ====================
# Name: __init__.py
# Description: Flow's front door: the names other branches take, each loaded from its home
# Version: 1.0.1
# Created: 2026-11-17
# Modified: 2026-11-20
# =============================================

"""Flow, the plan service. Other branches import from here: from aipass.flow import <name>."""

import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # each name typed from its home
    from aipass.flow.apps.handlers.plan.get_open_plans import get_open_plans

_HOMES = {
    "get_open_plans": "aipass.flow.apps.handlers.plan.get_open_plans",
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
