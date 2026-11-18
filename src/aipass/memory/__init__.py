# =================== AIPass ====================
# Name: __init__.py
# Description: Memory's front door: the names other branches take, each loaded from its home
# Version: 1.0.1
# Created: 2026-11-16
# Modified: 2026-11-18
# =============================================

"""Memory - the fleet's long-term memory: rollover, search, the .trinity caps and shape.

Public surface for other branches: from aipass.memory import <name>. apps/memory.py stays the command door.
"""

import importlib
from typing import Any

_HANDLERS = "aipass.memory.apps.handlers"
_SCOPE = f"{_HANDLERS}.monitor.registry_scope"
_LIMITS = f"{_HANDLERS}.json.entry_limits"
_CONFIG = f"{_HANDLERS}.json.config_loader"
_TABS = f"{_HANDLERS}.tracking.tab_renderer"

# Each name's home, loaded on access; a home named only here is inline (dead_code reads strings, not names).
_HOMES = {
    "fleet_branches": _SCOPE,
    "external_branches": _SCOPE,
    "declared_roots": _SCOPE,
    "declared_residency": _SCOPE,
    "find_repo_root": _SCOPE,
    "RESIDENCY_CORE": _SCOPE,
    "RESIDENCY_RESIDENT": _SCOPE,
    "RESIDENCY_EXTERNAL": _SCOPE,
    "should_surface": f"{_HANDLERS}.governance.engine",
    "record_message": f"{_HANDLERS}.governance.engine",
    "new_state": f"{_HANDLERS}.governance.engine",
    "load_entry_limits": _LIMITS,
    "check_file_budget": _LIMITS,
    "changed_entries": _LIMITS,
    "fields_for": _LIMITS,
    "draft_target": _LIMITS,
    "get_todos_count": _CONFIG,
    "section": _CONFIG,
    "compose_meta": _TABS,
    "render_all_meta_tabs": _TABS,
    "entry_rules": f"{_HANDLERS}.templates.trinity_push",
    "READY_PHRASE": f"{_HANDLERS}.rollover.todo_report",
    "spawn_background": f"{_HANDLERS}.intake.auto_process",
    "process_plans": f"{_HANDLERS}.intake.plans_processor",
    "get_branch_health": "aipass.memory.apps.modules.health",
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
