"""Prax - Monitoring and logging for AIPass: the one import door other branches take prax names from.

Lazy (PEP 562), docs/json_service.md. ``__getattr__`` uses ``importlib.import_module``, never a from-import:
that re-enters ``aipass.prax`` and recurses."""

import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # each name typed from its home
    from aipass.prax.apps.handlers.dashboard.operations import (
        DASHBOARD_CHAR_BUDGET as DASHBOARD_CHAR_BUDGET,
        SUBJECT_CAP as SUBJECT_CAP,
        cap_subject as cap_subject,
        dashboard_lock as dashboard_lock,
    )
    from aipass.prax.apps.handlers.dashboard.refresh import (
        refresh_all_dashboards as refresh_all_dashboards,
        refresh_single_dashboard as refresh_single_dashboard,
    )
    from aipass.prax.apps.handlers.json import json_service as json_handler
    from aipass.prax.apps.handlers.logging.jsonl_writer import append_jsonl as append_jsonl
    from aipass.prax.apps.handlers.logging.trail import trail as trail
    from aipass.prax.apps.modules.logger import get_system_logger as get_system_logger
    from aipass.prax.apps.modules.logger import log_backup_count as log_backup_count
    from aipass.prax.apps.modules.logger import system_logger as logger

_LOGGER_MODULE = "aipass.prax.apps.modules.logger"
_JSON_MODULE = "aipass.prax.apps.handlers.json.json_service"
_WRITER_MODULE = "aipass.prax.apps.handlers.logging.jsonl_writer"
_TRAIL_MODULE = "aipass.prax.apps.handlers.logging.trail"
_OPS_MODULE = "aipass.prax.apps.handlers.dashboard.operations"
_REFRESH_MODULE = "aipass.prax.apps.handlers.dashboard.refresh"

# Door name -> (home module, attribute there); None hands out the home module itself.
_HOMES = {
    "logger": (_LOGGER_MODULE, "system_logger"),
    "get_system_logger": (_LOGGER_MODULE, "get_system_logger"),
    "log_backup_count": (_LOGGER_MODULE, "log_backup_count"),
    "append_jsonl": (_WRITER_MODULE, "append_jsonl"),
    "trail": (_TRAIL_MODULE, "trail"),
    "json_handler": (_JSON_MODULE, None),
    "SUBJECT_CAP": (_OPS_MODULE, "SUBJECT_CAP"),
    "DASHBOARD_CHAR_BUDGET": (_OPS_MODULE, "DASHBOARD_CHAR_BUDGET"),
    "cap_subject": (_OPS_MODULE, "cap_subject"),
    "dashboard_lock": (_OPS_MODULE, "dashboard_lock"),
    "refresh_single_dashboard": (_REFRESH_MODULE, "refresh_single_dashboard"),
    "refresh_all_dashboards": (_REFRESH_MODULE, "refresh_all_dashboards"),
}

__all__ = sorted(_HOMES)


def __getattr__(name: str) -> Any:
    """Hand out a door name from its home on every access; nothing under apps loads at package import."""
    if name not in _HOMES:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute = _HOMES[name]
    # Never cached, so a patch on the home reaches every later read; no fallback, a broken chain raises.
    home = importlib.import_module(module_name)
    return home if attribute is None else getattr(home, attribute)


def __dir__() -> list:
    """Public names, whether or not they have been resolved yet."""
    return sorted(set(globals()) | set(__all__))
