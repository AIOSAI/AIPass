"""Prax - Monitoring and logging for AIPass.

Lazy (PEP 562). Reference: docs/json_service.md
``__getattr__`` uses ``importlib.import_module``, never a from-import: that re-enters ``aipass.prax`` and recurses."""

import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # Type-checker view only: `logger` is a SystemLogger, `json_handler` the module.
    from aipass.prax.apps.handlers.json import json_service as json_handler
    from aipass.prax.apps.handlers.logging.jsonl_writer import append_jsonl as append_jsonl
    from aipass.prax.apps.handlers.logging.trail import trail as trail
    from aipass.prax.apps.modules.logger import system_logger as logger

__all__ = ["append_jsonl", "json_handler", "logger", "trail"]

_LOGGER_MODULE = "aipass.prax.apps.modules.logger"
_JSON_MODULE = "aipass.prax.apps.handlers.json.json_service"
_WRITER_MODULE = "aipass.prax.apps.handlers.logging.jsonl_writer"
_TRAIL_MODULE = "aipass.prax.apps.handlers.logging.trail"


def __getattr__(name: str) -> Any:
    """Resolve a public prax name on first access, then cache it in globals()."""
    # No fallback for any name: a chain that cannot import raises here, as the long spelling does.
    if name == "logger":
        value = importlib.import_module(_LOGGER_MODULE).system_logger
    elif name == "append_jsonl":
        value = importlib.import_module(_WRITER_MODULE).append_jsonl
    elif name == "trail":
        value = importlib.import_module(_TRAIL_MODULE).trail
    elif name == "json_handler":
        value = importlib.import_module(_JSON_MODULE)
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    globals()[name] = value
    return value


def __dir__() -> list:
    """Public names, whether or not they have been resolved yet."""
    return sorted(set(globals()) | set(__all__))
