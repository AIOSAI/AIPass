# =================== AIPass ====================
# Name: __init__.py
# Description: API's front door: the names other branches take, each loaded from its home
# Version: 1.0.0
# Created: 2026-11-17
# Modified: 2026-11-17
# =============================================

"""API - External API integrations for AIPass.

Public surface for other branches: from aipass.api import <name>. apps/api.py stays the command door.
"""

import importlib
from typing import Any

_HOST = "aipass.api.apps.handlers.host"
_HOST_CONFIG = f"{_HOST}.config"
_HOST_LIFETIME = f"{_HOST}.lifetime"
_HOST_AUTOSTART = f"{_HOST}.autostart"
_HOST_PAIRINGS = f"{_HOST}.pairings"
# autostart, install_unit and enable_unit are composed in host_api, not passed through: that module is their home.
_HOST_API = "aipass.api.apps.modules.host_api"

_HOMES = {
    "load_config": _HOST_CONFIG,
    "face_dir": _HOST_CONFIG,
    "set_face_dir": _HOST_CONFIG,
    "baud_bin": _HOST_CONFIG,
    "set_baud_bin": _HOST_CONFIG,
    "set_bind": _HOST_CONFIG,
    "BindRefused": _HOST_CONFIG,
    "serve_detached": _HOST_LIFETIME,
    "LifetimeError": _HOST_LIFETIME,
    "AutostartUnsupported": _HOST_AUTOSTART,
    "SupervisorUnreachable": _HOST_AUTOSTART,
    "mint_pairing": _HOST_PAIRINGS,
    "render_qr": _HOST_PAIRINGS,
    "PairingError": _HOST_PAIRINGS,
    "autostart": _HOST_API,
    "install_unit": _HOST_API,
    "enable_unit": _HOST_API,
    "get_drive_service": "aipass.api.apps.modules.google_client",
    "api_call_with_retry": "aipass.api.apps.handlers.google.retry",
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
