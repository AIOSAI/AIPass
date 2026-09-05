"""Prax - Monitoring and logging for AIPass.

The package init is LAZY (PEP 562). Importing ``aipass.prax`` costs nothing but
this file: ``logger``, ``append_jsonl`` and ``json_handler`` are resolved on
first attribute access and cached in ``globals()``. Eager consumers are
unchanged — ``from aipass.prax import logger`` triggers ``__getattr__`` and
still hands back the same ``SystemLogger`` INSTANCE it always did.

Why: the eager form pulled the whole logger graph (30 aipass modules plus
watchdog and aipass.trigger) into every process that touched prax for any
reason. The json service (DPLAN-0325) must be reachable without it.

``__getattr__`` uses ``importlib.import_module`` and never a from-import: a
from-import inside this function re-enters ``aipass.prax`` and recurses.
"""

import importlib
import logging as _logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # Type-checker view only — never executed. Keeps `logger` resolving to
    # SystemLogger and `json_handler` to the module, exactly as the eager
    # imports did.
    from aipass.prax.apps.handlers.json import json_service as json_handler
    from aipass.prax.apps.modules.logger import append_jsonl as append_jsonl
    from aipass.prax.apps.modules.logger import system_logger as logger

__all__ = ["append_jsonl", "json_handler", "logger"]

_LOGGER_MODULE = "aipass.prax.apps.modules.logger"
_JSON_MODULE = "aipass.prax.apps.handlers.json.json_service"


class NullLogger:
    """Fallback logger when prax SystemLogger fails to import.

    Branches must not crash if prax is broken. Provides info/warning/error/debug
    so callers keep running. Every method on SystemLogger must exist here too: a
    branch that adopts a level the fallback lacks would crash with AttributeError
    precisely when prax is already broken.
    """

    def __init__(self):
        self._logger = _logging.getLogger("aipass.prax.fallback")
        if not self._logger.handlers:
            self._logger.addHandler(_logging.StreamHandler())
        self._logger.warning("Prax SystemLogger unavailable — using fallback NullLogger")

    def info(self, message, *args, **kwargs):
        self._logger.info(message, *args, **kwargs)

    def warning(self, message, *args, **kwargs):
        self._logger.warning(message, *args, **kwargs)

    def error(self, message, *args, **kwargs):
        self._logger.error(message, *args, **kwargs)

    def debug(self, message, *args, **kwargs):
        self._logger.debug(message, *args, **kwargs)


def __getattr__(name: str) -> Any:
    """Resolve a public prax name on first access, then cache it in globals().

    The fallback's moment moves from import time to first access: a broken
    logger chain still yields a NullLogger, and append_jsonl still degrades to
    None, exactly as the eager try/except did.
    """
    if name == "logger":
        try:
            value = importlib.import_module(_LOGGER_MODULE).system_logger
        except Exception:
            value = NullLogger()
    elif name == "append_jsonl":
        try:
            value = importlib.import_module(_LOGGER_MODULE).append_jsonl
        except Exception:
            value = None
    elif name == "json_handler":
        # No fallback: a broken json service is an error, not a silent no-op.
        value = importlib.import_module(_JSON_MODULE)
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    globals()[name] = value
    return value


def __dir__() -> list:
    """Public names, whether or not they have been resolved yet."""
    return sorted(set(globals()) | set(__all__))
