# =================== AIPass ====================
# Name: logger.py
# Description: PRAX Public API
# Version: 1.0.0
# Created: 2025-11-15
# Modified: 2026-03-09
# =============================================

"""
PRAX Logger - Public API

This is the main entry point for PRAX logging system.
Other branches import from here:
    from aipass.prax.apps.modules.prax_logger import system_logger

Provides:
- system_logger: Auto-routing logger for all modules
- get_direct_logger / direct_log: Event-pipeline-bypass logging for infrastructure
- Lifecycle functions: initialize, shutdown
- Status and control functions
"""

__all__ = [
    "system_logger",
    "get_system_logger",
    "SystemLogger",
    "get_direct_logger",
    "direct_log",
    "DirectLogger",
    "initialize_logging_system",
    "shutdown_logging_system",
    "get_system_status",
    "enable_terminal_output",
    "disable_terminal_output",
    "print_introspection",
    "handle_command",
    "MODULE_NAME",
    "DATA_FILE",
]

import logging
import threading
from typing import Dict, Any

# Stdlib logger for except-block compliance (seedgo requires variable named 'logger')
# SystemLogger methods shadow this with local 'logger = get_system_logger()' which is fine
logger = logging.getLogger(__name__)

# NOTE: CLI imports are done lazily inside functions to avoid circular dependency.
# CLI imports prax logger, so prax logger must not import CLI at module level.

# Import from handlers - internal implementation
from aipass.prax.apps.handlers.logging.setup import (
    setup_individual_logger,
    get_captured_loggers_count,
    enable_terminal_output as _enable_terminal,
    disable_terminal_output as _disable_terminal,
)
from aipass.prax.apps.handlers.logging.introspection import get_caller_info
from aipass.prax.apps.handlers.logging.override import is_override_active
from aipass.prax.apps.handlers.discovery.watcher import start_file_watcher, is_file_watcher_active
from aipass.prax.apps.handlers.registry.load import load_module_registry
from aipass.prax.apps.handlers.config.load import get_system_logs_dir, get_module_logs_dir, PRAX_JSON_DIR
from aipass.prax.apps.handlers.logging.direct import get_direct_logger, direct_log, DirectLogger
from aipass.prax.apps.handlers.json import json_handler

# Module constants
MODULE_NAME = "prax_logger"
DATA_FILE = PRAX_JSON_DIR / f"{MODULE_NAME}_data.json"

# =============================================
# SYSTEM LOGGER - THE MAIN EXPORT
# =============================================


def get_system_logger():
    """Get logger that automatically routes to correct module log file.

    Uses a single stack walk to detect module name, path, and branch
    together, avoiding the double-walk problem where separate calls
    could resolve different external callers at different stack depths.
    """
    module_name, caller_path, branch = get_caller_info()
    return setup_individual_logger(module_name, caller_path=caller_path, caller_branch=branch)


class SystemLogger:
    """Auto-routing logger that writes to calling module's log file"""

    _watcher_started = False
    _watcher_lock = threading.Lock()

    def _ensure_watcher(self):
        """Lazy-start file watchers on first logger use"""
        if SystemLogger._watcher_started:
            return
        with SystemLogger._watcher_lock:
            if SystemLogger._watcher_started:
                return  # Double-check after acquiring lock
            # Set flag FIRST to prevent recursion: trigger.fire() uses logger
            # internally, which would re-enter _ensure_watcher() before we return
            SystemLogger._watcher_started = True
            # Start prax watcher (Python file discovery)
            # Wrapped in try/except - inotify may be maxed by VS Code
            if not is_file_watcher_active():
                try:
                    start_file_watcher()
                except OSError as e:
                    logger.warning("inotify limit reached, continuing without file watcher: %s", e)
            # Fire startup event (trigger auto-initializes handlers)
            try:
                from aipass.trigger.apps.modules.core import trigger

                trigger.fire("startup")
            except (ImportError, OSError) as e:
                logger.warning("Trigger startup fire skipped (not available or inotify full): %s", e)

    def info(self, message, *args, **kwargs):
        """Log info message to calling module's log file"""
        self._ensure_watcher()
        logger = get_system_logger()
        logger.info(message, *args, **kwargs)

    def warning(self, message, *args, **kwargs):
        """Log warning message to calling module's log file"""
        self._ensure_watcher()
        logger = get_system_logger()
        logger.warning(message, *args, **kwargs)

    def error(self, message, *args, **kwargs):
        """Log error message to calling module's log file"""
        self._ensure_watcher()
        logger = get_system_logger()
        logger.error(message, *args, **kwargs)


# Export the logger object - this is what other branches import
system_logger = SystemLogger()

# =============================================
# LIFECYCLE FUNCTIONS
# =============================================


def initialize_logging_system():
    """Initialize the complete logging system

    Steps:
    1. Create config file if missing
    2. Discover all Python modules
    3. Save module registry
    4. Setup system logger
    5. Install logger override
    6. Start file watcher

    MODULE orchestration pattern: Thin wrapper that delegates to handler.
    """
    from aipass.cli.apps.modules import console
    from aipass.prax.apps.handlers.logging.lifecycle import run_initialize

    console.print(f"[{MODULE_NAME}] Initializing system-wide logging...")

    result = run_initialize(MODULE_NAME)

    console.print(f"[{MODULE_NAME}] System initialized - {result['modules_count']} modules, individual logging")


def shutdown_logging_system():
    """Shutdown logging system cleanly

    Steps:
    1. Stop file watcher
    2. Restore original logger
    3. Log shutdown operation

    MODULE orchestration pattern: Thin wrapper that delegates to handler.
    """
    from aipass.cli.apps.modules import console
    from aipass.prax.apps.handlers.logging.lifecycle import run_shutdown

    console.print(f"[{MODULE_NAME}] Shutting down logging system...")

    run_shutdown(MODULE_NAME)

    console.print(f"[{MODULE_NAME}] Shutdown complete")


# =============================================
# STATUS AND CONTROL
# =============================================


def get_system_status() -> Dict[str, Any]:
    """Get current logging system status

    Returns:
        Dict with system status information:
        - total_modules: Number of discovered modules
        - individual_loggers: Number of active loggers
        - module_logs_dir: Path to prax module logs
        - registry_file: Path to module registry
        - file_watcher_active: Watcher status
        - logger_override_active: Override status
    """
    modules = load_module_registry()

    return {
        "total_modules": len(modules),
        "individual_loggers": get_captured_loggers_count(),
        "system_logs_dir": str(get_system_logs_dir()),
        "module_logs_dir": str(get_module_logs_dir("prax")),
        "registry_file": str(DATA_FILE),
        "file_watcher_active": is_file_watcher_active(),
        "logger_override_active": is_override_active(),
    }


def enable_terminal_output():
    """Enable terminal output for all future loggers"""
    _enable_terminal()


def disable_terminal_output():
    """Disable terminal output"""
    _disable_terminal()


def print_introspection():
    """Display module introspection info."""
    try:
        from aipass.cli.apps.modules.display import console
    except ImportError as e:
        logger.info("CLI console not available, using rich fallback: %s", e)
        from rich.console import Console

        console = Console()

    console.print()
    console.print("logger Module")
    console.print("Public API for PRAX system-wide logging with auto-routing and lifecycle management")
    console.print()
    console.print("Connected Handlers:")
    console.print("  handlers/logging/")
    console.print("    - setup.py (setup_individual_logger — creates per-module log files)")
    console.print("    - setup.py (get_captured_loggers_count — returns active logger count)")
    console.print("    - setup.py (enable_terminal_output — enables live terminal log output)")
    console.print("    - setup.py (disable_terminal_output — disables terminal log output)")
    console.print("    - introspection.py (get_calling_module — resolves caller module name)")
    console.print("    - override.py (is_override_active — checks logger override status)")
    console.print("    - direct.py (get_direct_logger — bypasses event pipeline for infrastructure logging)")
    console.print("    - direct.py (direct_log — shorthand for direct logging calls)")
    console.print("    - direct.py (DirectLogger — direct logger class)")
    console.print("  handlers/discovery/")
    console.print("    - watcher.py (start_file_watcher — starts filesystem watcher for module discovery)")
    console.print("    - watcher.py (stop_file_watcher — stops the filesystem watcher)")
    console.print("    - watcher.py (is_file_watcher_active — checks watcher status)")
    console.print("  handlers/registry/")
    console.print("    - load.py (load_module_registry — loads discovered module registry)")
    console.print("  handlers/config/")
    console.print("    - load.py (get_system_logs_dir — returns system logs directory path)")
    console.print("    - load.py (get_module_logs_dir — returns per-module logs directory path)")
    console.print("    - load.py (PRAX_JSON_DIR — base path for prax JSON data files)")
    console.print()


def handle_command(_command: str, args: list) -> bool:
    """Handle commands routed by the entry point.

    Logger is a service module with no user-facing commands.
    All interaction happens through the system_logger API.
    """
    json_handler.log_operation("logger_handle_command", {"args": args})
    if not args:
        print_introspection()
        return True
    if args[0] in ("--help", "-h", "help"):
        print_introspection()  # Logger has no user commands — introspection IS the help
        return True
    return False
