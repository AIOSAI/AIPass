# =================== AIPass ====================
# Name: setup.py
# Description: Logger Setup & Management
# Version: 1.0.0
# Created: 2025-11-10
# Modified: 2026-03-09
# =============================================

"""
PRAX Logger Setup

Creates and configures individual loggers for modules.
Handles dual logging (system-wide + branch-local) and terminal output.
"""

import logging
import threading

logger = logging.getLogger(__name__)
from pathlib import Path
from typing import Dict, Optional
from logging.handlers import RotatingFileHandler

# Import from prax config
from aipass.prax.apps.handlers.config.load import (
    get_system_logs_dir,
    get_module_logs_dir,
    DEFAULT_LOG_LEVEL,
    load_log_config,
    lines_to_bytes,
)

# Import introspection functions
from aipass.prax.apps.handlers.logging.introspection import get_calling_module_path, detect_branch_from_path

from aipass.prax.apps.handlers.json import json_handler

# Global state for logging system
logger = logging.getLogger(__name__)
_system_logger: Optional[logging.Logger] = None
_captured_loggers: Dict[str, logging.Logger] = {}
_captured_loggers_lock = threading.Lock()
_terminal_output_enabled = False

# Try to import terminal handler support
_terminal_module_available = False
try:
    from aipass.prax.apps.handlers.logging.terminal.formatting import create_terminal_handler
    from aipass.prax.apps.handlers.logging.terminal.filtering import should_display_terminal

    _terminal_module_available = True
except ImportError as e:
    logger.info(f"[setup] Terminal handler modules not available: {e}")
    create_terminal_handler = None  # type: ignore[assignment]
    should_display_terminal = None  # type: ignore[assignment]


class _WindowsSafeRotatingHandler(RotatingFileHandler):
    """RotatingFileHandler that catches PermissionError/OSError during rotation on Windows.

    Windows enforces mandatory file locking — rename fails if another handle
    has the file open. On rotation failure, skip the rotation and keep writing
    to the current file. Non-fatal.
    """

    def doRollover(self) -> None:
        """Rotate log file; skip on Windows file-lock errors rather than crash."""
        try:
            super().doRollover()
        except (PermissionError, OSError) as exc:
            # Windows: file locked by another process. Skip rotation, keep writing.
            logger.warning("Log rotation skipped (file locked): %s", exc)


def _safe_rotating_handler(log_file: Path, max_bytes: int, backup_count: int) -> logging.Handler:
    """Create RotatingFileHandler — self-heals missing directories, never crashes."""
    try:
        parent = log_file.parent
        if not parent.exists():
            parent.mkdir(parents=True, exist_ok=True)
            if _system_logger:
                _system_logger.warning(f"Self-healed missing log directory: {parent}")
        return _WindowsSafeRotatingHandler(log_file, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8")
    except OSError as e:
        logger.error("Log handler failed for %s: %s", log_file, e)
        return logging.NullHandler()


def setup_individual_logger(
    module_name: str,
    caller_path: Optional[str] = None,
    caller_branch: Optional[str] = None,
) -> logging.Logger:
    """Setup individual logger for a specific module with dual logging support

    Creates:
    - System-wide log: {repo_root}/system_logs/{branch}_{module_name}.log
    - Module-local log: src/aipass/{branch}/logs/{module_name}.log
    - Terminal handler (if enabled)

    Args:
        module_name: Name of the module requesting a logger
        caller_path: Pre-resolved caller file path (avoids redundant stack walk)
        caller_branch: Pre-resolved branch name (avoids redundant stack walk)

    Returns:
        Configured logger instance
    """
    with _captured_loggers_lock:
        if module_name in _captured_loggers:
            return _captured_loggers[module_name]

    # Log new logger creation
    if _system_logger:
        _system_logger.info(f"Creating logger for module: {module_name}")

    # Create individual logger for this module
    logger = logging.getLogger(f"captured_{module_name}")
    logger.setLevel(DEFAULT_LOG_LEVEL)
    logger.handlers.clear()

    # Load config-driven limits
    log_config = load_log_config()

    # Use pre-resolved branch if provided, otherwise detect from stack
    import os

    branch_name: Optional[str] = caller_branch
    if not branch_name:
        module_path = caller_path or get_calling_module_path()
        branch_path = detect_branch_from_path(module_path) if module_path else None
        branch_name = Path(branch_path).name if branch_path else None

    # Environment variable fallback (set by drone for dispatched commands)
    if not branch_name:
        branch_name = os.environ.get("AIPASS_BRANCH_NAME") or "unknown_branch"

    # Create formatter (shared by all handlers)
    formatter = logging.Formatter(log_config["log_format"], log_config["date_format"])

    # HANDLER 1: System-wide log (central aggregation)
    system_log_file = get_system_logs_dir() / f"{branch_name}_{module_name}.log"
    system_limits = log_config["system_logs"]
    system_max_bytes = lines_to_bytes(system_limits["max_lines"])
    system_handler = _safe_rotating_handler(system_log_file, system_max_bytes, system_limits["backup_count"])
    system_handler.setFormatter(formatter)
    logger.addHandler(system_handler)

    # HANDLER 2: Branch-root local log (two-tier: system_logs/ + branch logs/)
    local_logs_dir = get_module_logs_dir(branch_name)
    module_log_file = local_logs_dir / f"{module_name}.log"
    local_limits = log_config["local_logs"]
    local_max_bytes = lines_to_bytes(local_limits["max_lines"])
    local_handler = _safe_rotating_handler(module_log_file, local_max_bytes, local_limits["backup_count"])
    local_handler.setFormatter(formatter)
    logger.addHandler(local_handler)

    if _system_logger:
        _system_logger.info(
            f"Logger created for {module_name} → system: {system_log_file} ({system_limits['max_lines']} lines), local: {module_log_file} ({local_limits['max_lines']} lines)"
        )

    # HANDLER 3: Terminal output (if enabled)
    if _terminal_output_enabled and _terminal_module_available:
        if should_display_terminal(module_name):  # type: ignore[misc]
            terminal_handler = create_terminal_handler()  # type: ignore[misc]
            logger.addHandler(terminal_handler)

    # Store for reuse (thread-safe)
    with _captured_loggers_lock:
        _captured_loggers[module_name] = logger

    return logger


def setup_system_logger() -> logging.Logger:
    """Setup prax_logger's own logging

    Creates the system logger used by prax itself.

    Returns:
        Prax system logger instance
    """
    global _system_logger

    if _system_logger:
        return _system_logger

    # Load config-driven limits
    log_config = load_log_config()

    # Create prax_logger's own logger
    _system_logger = logging.getLogger("prax_system_logger")
    _system_logger.setLevel(DEFAULT_LOG_LEVEL)
    _system_logger.handlers.clear()

    # Formatter shared by both handlers
    log_config_fmt = logging.Formatter(log_config["log_format"], log_config["date_format"])

    # HANDLER 1: System-wide log (central aggregation)
    system_log_file = get_system_logs_dir() / "prax_logger.log"
    system_limits = log_config["system_logs"]
    system_max_bytes = lines_to_bytes(system_limits["max_lines"])
    system_handler = _safe_rotating_handler(system_log_file, system_max_bytes, system_limits["backup_count"])
    system_handler.setFormatter(log_config_fmt)
    _system_logger.addHandler(system_handler)

    # HANDLER 2: Module-local log (local debugging)
    local_log_file = get_module_logs_dir("prax") / "prax_logger.log"
    local_limits = log_config["local_logs"]
    local_max_bytes = lines_to_bytes(local_limits["max_lines"])
    local_handler = _safe_rotating_handler(local_log_file, local_max_bytes, local_limits["backup_count"])
    local_handler.setFormatter(log_config_fmt)
    _system_logger.addHandler(local_handler)

    # Log system logger creation
    _system_logger.info("Prax system logger initialized successfully")
    _system_logger.info(f"System logger writing to: {system_log_file} + {local_log_file}")

    json_handler.log_operation(
        "logger_setup_complete", {"system_log": str(system_log_file), "local_log": str(local_log_file)}
    )

    return _system_logger


def get_captured_loggers_count() -> int:
    """Get count of captured loggers

    Returns:
        Number of module loggers created
    """
    return len(_captured_loggers)


def enable_terminal_output():
    """Enable terminal output for all future loggers"""
    global _terminal_output_enabled
    _terminal_output_enabled = True
    if _system_logger:
        _system_logger.info("Terminal output enabled")


def disable_terminal_output():
    """Disable terminal output"""
    global _terminal_output_enabled
    _terminal_output_enabled = False
    if _system_logger:
        _system_logger.info("Terminal output disabled")
