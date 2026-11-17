"""DevPulse's import door: from aipass.devpulse import <name>, each read from its home on access, never cached."""

import importlib
from typing import Any

_COMPASS = "aipass.devpulse.apps.handlers.compass"
_GRANT = "aipass.devpulse.apps.handlers.owner.admin_grant"

_HOMES = {
    "recall_decisions": _COMPASS,
    "mark_surfaced": _COMPASS,
    "verify_admin_grant": _GRANT,
    "compute_signature": _GRANT,
}

__all__ = list(_HOMES)


def __getattr__(name: str) -> Any:
    """Hand out a door name from its home on each access; nothing under apps loads at package import."""
    if name not in _HOMES:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(importlib.import_module(_HOMES[name]), name)


def __dir__() -> list:
    """Public names, whether or not they have been resolved yet."""
    return sorted(set(globals()) | set(__all__))
