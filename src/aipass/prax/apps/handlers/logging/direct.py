# =================== AIPass ====================
# Name: direct.py
# Description: Direct Logger (Event Pipeline Bypass)
# Version: 1.0.0
# Created: 2026-02-27
# Modified: 2026-03-09
# =============================================

"""
PRAX Direct Logger

Writes to the same log locations with the same format and rotation as the
regular system_logger, but WITHOUT triggering the event pipeline.

The regular system_logger flow:
    caller -> SystemLogger -> setup_individual_logger -> RotatingFileHandler
    + starts file watchers -> log_watcher detects changes -> MonitoringEvent

The direct logger flow:
    caller -> DirectLogger -> RotatingFileHandler
    (no watchers, no triggers, no event queue)

Use this ONLY for infrastructure handlers that would cause recursion:
    - log_watcher.py (watches the same log files it would write to)
    - error_registry.py (called by log_watcher on every error)
    - log_streamer.py (tails system_logs/ for Telegram streaming)
    - base_bot.py (owns log_streamer, writes to tailed directory)

Everyone else should use the regular system_logger.
"""

import inspect
import logging
from logging.handlers import RotatingFileHandler as _BaseRotatingFileHandler

logger = logging.getLogger(__name__)


class RotatingFileHandler(_BaseRotatingFileHandler):
    """Windows-safe RotatingFileHandler — skips rotation on file locking errors."""

    def doRollover(self) -> None:
        """Rotate log file; skip on Windows file-lock errors rather than crash."""
        try:
            super().doRollover()
        except (PermissionError, OSError) as exc:
            logger.warning("Log rotation skipped (file locked): %s", exc)


from pathlib import Path
from typing import Dict, Optional, Tuple

from aipass.prax.apps.handlers.config.load import (
    get_system_logs_dir,
    get_module_logs_dir,
    DEFAULT_LOG_LEVEL,
    load_log_config,
    lines_to_bytes,
)
from aipass.prax.apps.handlers.logging.introspection import detect_branch_from_path
from aipass.prax.apps.handlers.json import json_handler

# Use original stdlib getLogger (not the prax-overridden version).
# This is intentional: direct.py creates raw stdlib loggers for
# RotatingFileHandler management. Using prax logger would cause
# recursion since direct.py IS the pipeline-bypass mechanism.
from aipass.prax.apps.handlers.logging.override import _original_getLogger as _stdlib_getLogger

# Cache for direct loggers - keyed by "branch_module"
_direct_loggers: Dict[str, logging.Logger] = {}


def _get_direct_caller_info() -> Tuple[str, Optional[str]]:
    """Stack introspection for direct logger callers.

    Unlike the regular introspection (which skips ALL prax handler frames),
    this only skips frames from this file and the public API (logger.py).
    This is necessary because the direct logger IS designed for prax handlers.

    Returns:
        Tuple of (module_name, branch_path) where branch_path may be None.
    """
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
            # Only skip our own internal frames
            if "/logging/direct.py" in path or "/modules/logger.py" in path:
                continue
            module_name = Path(path).stem
            branch_path = detect_branch_from_path(path)
            return module_name, branch_path
        return "unknown_module", None
    finally:
        del frame


def _create_direct_logger(module_name: str, branch_name: str, branch_path: Optional[str]) -> logging.Logger:
    """Create a standalone logger with dual RotatingFileHandlers.

    Same dual-logging setup as setup_individual_logger but with NO
    connection to the event pipeline. Uses logging.Logger internally
    only for RotatingFileHandler management - no root logger propagation.

    Args:
        module_name: Name of the calling module (e.g., 'log_watcher')
        branch_name: Short branch name (e.g., 'prax', 'trigger', 'api')
        branch_path: Module/branch name (e.g., 'prax') or None

    Returns:
        Configured logger with dual file handlers and no propagation.
    """
    logger_key = f"direct_{branch_name}_{module_name}"
    # _stdlib_getLogger: raw stdlib logger for file handler management (no prax pipeline)
    logger = _stdlib_getLogger(logger_key)
    logger.setLevel(DEFAULT_LOG_LEVEL)
    logger.handlers.clear()
    logger.propagate = False  # Critical: no root logger propagation

    config = load_log_config()
    formatter = logging.Formatter(config["log_format"], config["date_format"])

    target = branch_name if branch_path else "prax"

    # Handler 1: System-wide log (central aggregation)
    sys_log_file = get_system_logs_dir() / f"{target}_{module_name}.log"
    sys_limits = config["system_logs"]
    sys_handler = RotatingFileHandler(
        sys_log_file,
        maxBytes=lines_to_bytes(sys_limits["max_lines"]),
        backupCount=sys_limits["backup_count"],
        encoding="utf-8",
    )
    sys_handler.setFormatter(formatter)
    logger.addHandler(sys_handler)

    # Handler 2: Module-local log (local debugging)
    local_log_file = get_module_logs_dir(target) / f"{module_name}.log"
    local_limits = config["local_logs"]
    local_handler = RotatingFileHandler(
        local_log_file,
        maxBytes=lines_to_bytes(local_limits["max_lines"]),
        backupCount=local_limits["backup_count"],
        encoding="utf-8",
    )
    local_handler.setFormatter(formatter)
    logger.addHandler(local_handler)

    return logger


def _get_or_create_logger(module_name: str, branch_path: Optional[str]) -> logging.Logger:
    """Get cached logger or create a new one.

    Args:
        module_name: Name of the calling module.
        branch_path: Full branch path or None.

    Returns:
        Cached or newly created direct logger.
    """
    branch_name = Path(branch_path).name if branch_path else "unknown"
    key = f"{branch_name}_{module_name}"
    if key not in _direct_loggers:
        _direct_loggers[key] = _create_direct_logger(module_name, branch_name, branch_path)
    return _direct_loggers[key]


class DirectLogger:
    """Logger that bypasses the event pipeline.

    Writes to the same locations with the same format and rotation
    as the regular system_logger. Module and branch are resolved
    once at creation time via stack introspection.

    Usage:
        from aipass.prax.apps.modules.logger import get_direct_logger
        direct_logger = get_direct_logger()
        direct_logger.info("Safe to log from infrastructure handlers")
    """

    def __init__(self, module_name: str, branch_path: Optional[str]):
        self._module_name = module_name
        self._branch_path = branch_path
        self._logger: Optional[logging.Logger] = None

    def _ensure_logger(self) -> logging.Logger:
        """Lazily create the underlying logger on first use.

        Returns:
            The cached direct logger instance.
        """
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

    Resolves module name and branch path at creation time via
    stack introspection. The returned logger can be stored as a
    module-level variable and reused.

    Returns:
        DirectLogger instance bound to the caller's module/branch.
    """
    module_name, branch_path = _get_direct_caller_info()
    json_handler.log_operation("direct_log_created", {"module": module_name, "branch_path": branch_path})
    return DirectLogger(module_name, branch_path)


def direct_log(level: str, message: str) -> None:
    """Log a single message directly without event pipeline.

    Resolves the calling module automatically. For repeated use,
    prefer get_direct_logger() to avoid repeated stack walks.

    Args:
        level: Log level string ('info', 'warning', 'error', 'debug')
        message: The log message
    """
    module_name, branch_path = _get_direct_caller_info()
    logger = _get_or_create_logger(module_name, branch_path)
    log_fn = getattr(logger, level.lower(), logger.info)
    log_fn(message)
