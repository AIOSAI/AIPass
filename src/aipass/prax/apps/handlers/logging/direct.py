# =================== AIPass ====================
# Name: direct.py
# Description: Direct Logger (Event Pipeline Bypass)
# Version: 1.2.0
# Created: 2026-02-27
# Modified: 2026-10-17
# =============================================

"""PRAX Direct Logger

system_logger's files, format and rotation without the event pipeline, for handlers that would
recurse through it (log_watcher, error_registry, log_streamer, base_bot). Reference: docs/logging_api.md.
"""

import inspect
import logging
from logging.handlers import RotatingFileHandler as _BaseRotatingFileHandler
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

from aipass.prax.apps.handlers.config.load import (
    get_system_logs_dir,
    get_module_logs_dir,
    load_log_config,
    lines_to_bytes,
    level_to_int,
    resolve_log_level,
)
from aipass.prax.apps.handlers.logging.introspection import detect_branch_from_path
from aipass.prax.apps.handlers.json import json_handler

# The stdlib getLogger, not prax's override: the prax logger would recurse into this bypass.
from aipass.prax.apps.handlers.logging.override import _original_getLogger as _stdlib_getLogger

logger = logging.getLogger(__name__)


class RotatingFileHandler(_BaseRotatingFileHandler):
    """Windows-safe RotatingFileHandler — skips rotation on file locking errors."""

    def doRollover(self) -> None:
        """Rotate log file; skip on Windows file-lock errors rather than crash."""
        try:
            super().doRollover()
        except (PermissionError, OSError) as exc:
            logger.warning("Log rotation skipped (file locked): %s", exc)


_direct_loggers: Dict[str, logging.Logger] = {}


def _get_direct_caller_info() -> Tuple[str, Optional[str]]:
    """Stack introspection for direct logger callers.

    Skips only this file and logger.py, not every prax handler frame: prax handlers are its callers."""
    frame = inspect.currentframe()
    try:
        current = frame
        for _ in range(15):
            if current is None:
                break
            current = current.f_back
            if current is None:
                break
            path = current.f_globals.get("__file__", "")
            if not path:
                continue
            if "/logging/direct.py" in path or "/modules/logger.py" in path:
                continue
            module_name = Path(path).stem
            branch_path = detect_branch_from_path(path)
            return module_name, branch_path
        return "unknown_module", None
    finally:
        del frame


def _tier_handler(resolve_dir: Callable[[], Path], filename: str, limits: Dict[str, Any]) -> logging.Handler:
    """Open one tier's file. An unwritable log home is a NullHandler, never a raise.

    The first line a direct logger writes opens these files; a raise would land in the caller."""
    try:
        return RotatingFileHandler(
            resolve_dir() / filename,
            maxBytes=lines_to_bytes(limits["max_lines"]),
            backupCount=limits["backup_count"],
            encoding="utf-8",
        )
    except (OSError, RuntimeError) as e:  # RuntimeError: Path.home() with no home to find
        logger.error("Log handler failed for %s: %s", filename, e)
        return logging.NullHandler()


def _create_direct_logger(module_name: str, branch_name: str, branch_path: Optional[str]) -> logging.Logger:
    """Create a standalone logger with dual RotatingFileHandlers and no root propagation."""
    logger_key = f"direct_{branch_name}_{module_name}"
    logger = _stdlib_getLogger(logger_key)
    logger.handlers.clear()
    logger.propagate = False  # Critical: no root logger propagation

    config = load_log_config()
    formatter = logging.Formatter(config["log_format"], config["date_format"])

    # The lower tier level, as setup_individual_logger does, or debug() never reaches a handler.
    system_level = resolve_log_level(config["system_logs"].get("log_level"))
    local_level = resolve_log_level(config["local_logs"].get("log_level"))
    logger.setLevel(min(level_to_int(system_level), level_to_int(local_level)))

    target = branch_name if branch_path else "prax"

    sys_handler = _tier_handler(get_system_logs_dir, f"{target}_{module_name}.log", config["system_logs"])
    sys_handler.setFormatter(formatter)
    sys_handler.setLevel(system_level)
    logger.addHandler(sys_handler)

    local_handler = _tier_handler(lambda: get_module_logs_dir(target), f"{module_name}.log", config["local_logs"])
    local_handler.setFormatter(formatter)
    local_handler.setLevel(local_level)
    logger.addHandler(local_handler)

    return logger


def _get_or_create_logger(module_name: str, branch_path: Optional[str]) -> logging.Logger:
    """Get cached logger or create a new one."""
    branch_name = Path(branch_path).name if branch_path else "unknown"
    key = f"{branch_name}_{module_name}"
    if key not in _direct_loggers:
        _direct_loggers[key] = _create_direct_logger(module_name, branch_name, branch_path)
        # Recorded when the file opens, never in get_direct_logger(), which runs at import.
        json_handler.log_operation("direct_log_created", {"module": module_name, "branch_path": branch_path})
    return _direct_loggers[key]


class DirectLogger:
    """Logger that bypasses the event pipeline; module and branch resolve once at creation."""

    def __init__(self, module_name: str, branch_path: Optional[str]):
        self._module_name = module_name
        self._branch_path = branch_path
        self._logger: Optional[logging.Logger] = None

    def _ensure_logger(self) -> logging.Logger:
        """Lazily create the underlying logger on first use."""
        if self._logger is None:
            self._logger = _get_or_create_logger(self._module_name, self._branch_path)
        return self._logger

    def info(self, message: str, *args, **kwargs) -> None:
        """Log an INFO level message directly to file."""
        self._ensure_logger().info(message, *args, **kwargs)

    def warning(self, message: str, *args, **kwargs) -> None:
        """Log a WARNING level message directly to file."""
        self._ensure_logger().warning(message, *args, **kwargs)

    def error(self, message: str, *args, **kwargs) -> None:
        """Log an ERROR level message directly to file."""
        self._ensure_logger().error(message, *args, **kwargs)

    def debug(self, message: str, *args, **kwargs) -> None:
        """Log a DEBUG level message directly to file."""
        self._ensure_logger().debug(message, *args, **kwargs)


def get_direct_logger() -> DirectLogger:
    """Get a DirectLogger bound to the calling module.

    Writes nothing: most callers run it at module level, at import."""
    module_name, branch_path = _get_direct_caller_info()
    return DirectLogger(module_name, branch_path)


def direct_log(level: str, message: str) -> None:
    """Log a single message directly without event pipeline; get_direct_logger() avoids repeated stack walks."""
    module_name, branch_path = _get_direct_caller_info()
    logger = _get_or_create_logger(module_name, branch_path)
    log_fn = getattr(logger, level.lower(), logger.info)
    log_fn(message)
