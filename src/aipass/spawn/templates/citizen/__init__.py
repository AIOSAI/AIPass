# =================== AIPass ====================
# Name: __init__.py
# Description: {{BRANCHNAME}}'s front door: the names other branches take, each loaded from its home
# Version: 1.0.0
# Created: {{DATE}}
# Modified: {{DATE}}
# =============================================

"""{{BRANCHNAME}}'s public surface: from aipass.{{BRANCH}} import <name>; apps/{{BRANCH}}.py stays the command door."""

import importlib
from typing import Any

# A name joins the table, mapped to the module that defines it, when another branch needs it.
_HOMES: dict[str, str] = {}

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
