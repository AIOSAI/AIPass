# =================== AIPass ====================
# Name: __init__.py
# Description: Backup's front door: the names other branches take, each loaded from its home
# Version: 2.0.0
# Created: 2026-04-16
# Modified: 2026-11-17
# =============================================

"""Backup - project-owned, local-first snapshots and the optional Drive sync.

Public surface for other branches: from aipass.backup import <name>. apps/backup.py stays the command door.
"""

import importlib
from typing import Any

# Door name -> (home module, attribute there).
_HOMES = {"log_operation": ("aipass.backup.apps.handlers.audit.trail", "log_operation")}

__all__ = sorted(_HOMES)


def __getattr__(name: str) -> Any:
    """Hand out a door name from its home on each access; nothing under apps loads at package import."""
    if name not in _HOMES:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute = _HOMES[name]
    # Never cached on the package: a patch on the home attribute must reach every caller reading through here.
    return getattr(importlib.import_module(module_name), attribute)


def __dir__() -> list:
    """Public names, whether or not they have been resolved yet."""
    return sorted(set(globals()) | set(__all__))
