# =================== AIPass ====================
# Name: __init__.py
# Description: Sentry's front door: the names other branches take, each loaded from its home
# Version: 1.0.0
# Created: 2026-11-17
# Modified: 2026-11-20
# =============================================

"""Sentry's front door: from aipass.sentry import <name>; apps/sentry.py stays the command door."""

import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # each name typed from its home
    from aipass.sentry.apps.handlers.aipass_standards.trinity_check import check_branch
    from aipass.sentry.apps.handlers.aipass_standards.trinity_groups import expected_meta_line
    from aipass.sentry.apps.handlers.audit.branch_audit import audit_branch
    from aipass.sentry.apps.handlers.bypass.bypass_handler import load_bypass_rules
    from aipass.sentry.apps.handlers.context_standards import name_ratchet, startup_ratchet
    from aipass.sentry.apps.modules.checklist import ADVICE_MARKER, FINDING_MARKER

_HANDLERS = "aipass.sentry.apps.handlers"
_CHECKLIST = "aipass.sentry.apps.modules.checklist"
_CONTEXT = f"{_HANDLERS}.context_standards"

_HOMES = {
    "ADVICE_MARKER": _CHECKLIST,
    "FINDING_MARKER": _CHECKLIST,
    "audit_branch": f"{_HANDLERS}.audit.branch_audit",
    "load_bypass_rules": f"{_HANDLERS}.bypass.bypass_handler",
    "check_branch": f"{_HANDLERS}.aipass_standards.trinity_check",
    "expected_meta_line": f"{_HANDLERS}.aipass_standards.trinity_groups",
}
_MODULES = {  # names that are whole modules: the door hands out the module itself
    "name_ratchet": f"{_CONTEXT}.name_ratchet",
    "startup_ratchet": f"{_CONTEXT}.startup_ratchet",
}

__all__ = [*_HOMES, *_MODULES]


def __getattr__(name: str) -> Any:
    """Hand out a door name from its home on each access; nothing under apps loads at package import."""
    if name in _MODULES:
        return importlib.import_module(_MODULES[name])
    if name not in _HOMES:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    # Never cached on the package: a patch on the home attribute must reach every caller reading through here.
    return getattr(importlib.import_module(_HOMES[name]), name)


def __dir__() -> list:
    """Public names, whether or not they have been resolved yet."""
    return sorted(set(globals()) | set(__all__))
