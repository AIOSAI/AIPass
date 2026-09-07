# =================== AIPass ====================
# Name: logger.py
# Description: PRAX Public API
# Version: 1.1.0
# Created: 2025-11-15
# Modified: 2026-08-11
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
    "append_jsonl",
]

import logging
import threading
from typing import Dict, Any

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
from aipass.prax.apps.handlers.discovery.watcher import (
    start_file_watcher_in_background,
    is_file_watcher_active,
    check_file_watcher_liveness,
)
from aipass.prax.apps.handlers.registry.load import load_module_registry
from aipass.prax.apps.handlers.config.load import get_system_logs_dir, get_module_logs_dir, PRAX_JSON_DIR
from aipass.prax.apps.handlers.logging.direct import get_direct_logger, direct_log, DirectLogger
from aipass.prax.apps.handlers.logging.jsonl_writer import append_jsonl
from aipass.prax.apps.handlers.json import json_handler

# Stdlib logger for except-block compliance (seedgo requires variable named 'logger')
# SystemLogger methods shadow this with local 'logger = get_system_logger()' which is fine
logger = logging.getLogger(__name__)

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
        """Lazy-start file watchers on first logger use, then keep them honest.

        `_watcher_started` is set once and never reset, so everything below the
        early return runs exactly ONCE in the life of a process. That is correct
        for *starting* the watcher and was wrong for *trusting* it: the watcher
        can die at any moment afterwards (DPLAN-0305 — it did, in six processes
        at once, and no one found out for 15 hours). The throttled liveness call
        is the only thing here that runs after startup.
        """
        if SystemLogger._watcher_started:
            check_file_watcher_liveness()  # Throttled; ~1 real check/60s.
            return
        with SystemLogger._watcher_lock:
            if SystemLogger._watcher_started:
                return  # Double-check after acquiring lock
            # Set flag FIRST to prevent recursion: trigger.fire() uses logger
            # internally, which would re-enter _ensure_watcher() before we return
            SystemLogger._watcher_started = True
            # Start prax watcher (Python file discovery) WITHOUT waiting for it.
            # Scheduling the recursive watch is one inotify syscall per directory
            # (1605 of them here) and costs 0.119s on an idle thread but 13.9s
            # when any other Python thread is busy — measured 2026-09-04. This is
            # the first log line of the process, so that bill used to land on
            # whoever logged first, which in a test suite is the suite. The
            # background start swallows the inotify-limit OSError itself and logs
            # it with the same words; there is no caller left to hand it to.
            if not is_file_watcher_active():
                start_file_watcher_in_background()
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

    def debug(self, message, *args, **kwargs):
        """Log debug message to calling module's log file.

        Silent under the default INFO level — nothing reaches a log file
        until the level is lowered via AIPASS_LOG_LEVEL or the log_level
        config key. That is the point: use this for the verbose trail you
        want available on demand but absent from normal operation.

        The level binds when a module's logger is first created, so a
        long-running process picks up a change on restart, not mid-flight.
        """
        self._ensure_watcher()
        logger = get_system_logger()
        logger.debug(message, *args, **kwargs)


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

    console.print(f"\\[{MODULE_NAME}] Initializing system-wide logging...")

    result = run_initialize(MODULE_NAME)

    console.print(f"\\[{MODULE_NAME}] System initialized - {result['modules_count']} modules, individual logging")


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

    console.print(f"\\[{MODULE_NAME}] Shutting down logging system...")

    run_shutdown(MODULE_NAME)

    console.print(f"\\[{MODULE_NAME}] Shutdown complete")


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
    console.print("[bold cyan]logger Module[/bold cyan]")
    console.print("Public API for PRAX system-wide logging with auto-routing and lifecycle management")
    console.print()
    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print()
    console.print("  [cyan]handlers/logging/[/cyan]")
    console.print("    [dim]→ setup.py (setup_individual_logger — creates per-module log files)[/dim]")
    console.print("    [dim]→ setup.py (get_captured_loggers_count — returns active logger count)[/dim]")
    console.print("    [dim]→ setup.py (enable_terminal_output — enables live terminal log output)[/dim]")
    console.print("    [dim]→ setup.py (disable_terminal_output — disables terminal log output)[/dim]")
    console.print("    [dim]→ introspection.py (get_calling_module — resolves caller module name)[/dim]")
    console.print("    [dim]→ override.py (is_override_active — checks logger override status)[/dim]")
    console.print("    [dim]→ direct.py (get_direct_logger — bypasses event pipeline for infrastructure logging)[/dim]")
    console.print("    [dim]→ direct.py (direct_log — shorthand for direct logging calls)[/dim]")
    console.print("    [dim]→ direct.py (DirectLogger — direct logger class)[/dim]")
    console.print()
    console.print("  [cyan]handlers/discovery/[/cyan]")
    console.print(
        "    [dim]→ watcher.py (start_file_watcher_in_background — starts the module discovery "
        "watcher without waiting for the inotify walk)[/dim]"
    )
    console.print("    [dim]→ watcher.py (stop_file_watcher — stops the filesystem watcher)[/dim]")
    console.print("    [dim]→ watcher.py (is_file_watcher_active — checks watcher status)[/dim]")
    console.print()
    console.print("  [cyan]handlers/registry/[/cyan]")
    console.print("    [dim]→ load.py (load_module_registry — loads discovered module registry)[/dim]")
    console.print()
    console.print("  [cyan]handlers/config/[/cyan]")
    console.print("    [dim]→ load.py (get_system_logs_dir — returns system logs directory path)[/dim]")
    console.print("    [dim]→ load.py (get_module_logs_dir — returns per-module logs directory path)[/dim]")
    console.print("    [dim]→ load.py (PRAX_JSON_DIR — base path for prax JSON data files)[/dim]")
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
