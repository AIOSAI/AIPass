# =================== AIPass ====================
# Name: __init__.py
# Description: aipass's front door: the names other branches take, each loaded from its home
# Version: 1.0.1
# Created: 2026-11-17
# Modified: 2026-11-20
# =============================================

"""AIPass machine concierge — host diagnosis, doctor, installer, project scaffold (init, new, adopt).

Public surface for other branches: from aipass.aipass import <name>. The `aipass` CLI stays the command door.
"""

import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # each name typed from its home
    from aipass.aipass.apps.handlers.new_project import TEMPLATES, create_project

_NEW_PROJECT = "aipass.aipass.apps.handlers.new_project"

_HOMES = {
    "create_project": _NEW_PROJECT,
    "TEMPLATES": _NEW_PROJECT,
}

__all__ = list(_HOMES)


def __getattr__(name: str) -> Any:
    """Hand out a door name from its home on each access, never cached, so a patch on the home reaches every caller."""
    if name not in _HOMES:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(importlib.import_module(_HOMES[name]), name)


def __dir__() -> list:
    """Public names, whether or not they have been resolved yet."""
    return sorted(set(globals()) | set(__all__))
