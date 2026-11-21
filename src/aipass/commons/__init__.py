# =================== AIPass ====================
# Name: __init__.py
# Description: The Commons' front door: the names other branches take, each loaded from its home
# Version: 1.1.0
# Created: 2026-03-07
# Modified: 2026-11-20
# =============================================

"""The Commons' public surface: from aipass.commons import <name>; apps/commons.py stays the command door."""

import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # each name typed from its home
    from aipass.commons.apps.handlers.identity.identity_ops import get_caller_branch

__version__ = "1.0.0"

_IDENTITY = "aipass.commons.apps.handlers.identity.identity_ops"

_HOMES = {
    "get_caller_branch": _IDENTITY,
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
