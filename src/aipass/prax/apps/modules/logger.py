# =================== AIPass ====================
# Name: logger.py
# Description: PRAX Public API
# Version: 1.4.0
# Created: 2025-11-15
# Modified: 2026-09-12
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
    is_file_watcher_active,
    check_file_watcher_liveness,
)
from aipass.prax.apps.handlers.registry.load import load_module_registry, load_last_scan
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

    def _ensure_watcher(self):
        """Keep an explicitly started discovery watcher honest. Starts nothing.

        Until 2026-09-12 the first log line of every process started a recursive
        inotify watch over the whole ecosystem on an unjoined daemon thread.
        That is gone (DPLAN-0339 step 4): discovery is a scheduled scan now
        (`drone @prax discover`, daily), so a process that merely logs costs the
        machine no watches and no thread. Logging itself never depended on the
        watcher — a module gets its log file when it logs, not when it is
        discovered.

        What is left is the liveness check, and it still has a job: a process
        that opens the explicit door (`initialize_logging_system()`, which starts
        the watcher synchronously and keeps it for the life of that process) must
        still find out if the watchdog dispatcher dies under it — DPLAN-0305,
        where it died in six processes at once and nobody knew for 15 hours. In
        every other process the check answers "no watcher here" and costs a
        throttled boolean.

        `_watcher_started` is therefore no longer a "did we start it" flag; it
        means "this process is past its first log line", which is the one moment
        a watcher cannot yet exist. No lock guards it any more: it gates nothing
        but a cheap check, and a racing double-set is the same value twice.
        """
        if SystemLogger._watcher_started:
            check_file_watcher_liveness()  # Throttled; ~1 real check/60s.
            return
        SystemLogger._watcher_started = True

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
#
# These two are the explicit system lifecycle doors seedgo's trigger standard
# names (trigger.md Pattern 9, `initialize_*_system` / `shutdown_*_system`), so
# each announces itself on trigger's bus: `logging_system_initialized` and
# `logging_system_shutdown`. The standard's event table names no lifecycle
# event, so those two names are prax's, following its rules (lowercase,
# underscore-separated, past tense).
#
# BOTH IMPORT TRIGGER INSIDE THEMSELVES, never at module level, and that is the
# whole design. `from aipass.prax import logger` and every log line the fleet
# writes must stay clear of the aipass.trigger import graph: DPLAN-0339 step 3
# took a fire off the first log line of every process and it was worth 0.339 s
# of that line's 0.361 s, nearly all of it importing that graph. A door called
# deliberately, once, can afford what a hot path cannot.
#
# Each fire is guarded (ImportError, OSError) exactly as the removed one was:
# these doors must still work on a host where trigger cannot import or inotify
# is exhausted. A fire that fails is a warning, never a failed initialize.
#
# Nothing listens to either event today, by design — the point of the standard
# is that a handler can plug in later without prax changing again.


def initialize_logging_system():
    """Initialize the complete logging system

    Steps:
    1. Create config file if missing
    2. Discover all Python modules
    3. Save module registry
    4. Setup system logger
    5. Install logger override
    6. Start file watcher
    7. Fire `logging_system_initialized`

    MODULE orchestration pattern: Thin wrapper that delegates to handler.
    See the section header above for why the trigger import is local.
    """
    from aipass.cli.apps.modules import console
    from aipass.prax.apps.handlers.logging.lifecycle import run_initialize

    console.print(f"\\[{MODULE_NAME}] Initializing system-wide logging...")

    result = run_initialize(MODULE_NAME)

    console.print(f"\\[{MODULE_NAME}] System initialized - {result['modules_count']} modules, individual logging")

    try:
        from aipass.trigger.apps.modules.core import trigger

        trigger.fire("logging_system_initialized", modules_count=result["modules_count"])
    except (ImportError, OSError) as e:
        logger.warning("Trigger logging_system_initialized fire skipped (not available or inotify full): %s", e)


def shutdown_logging_system():
    """Shutdown logging system cleanly

    Steps:
    1. Stop file watcher
    2. Restore original logger
    3. Log shutdown operation
    4. Fire `logging_system_shutdown`

    MODULE orchestration pattern: Thin wrapper that delegates to handler.
    Fired last on purpose: the event says the system IS down, not that it is
    going down, so a handler that reacts by writing is not racing the teardown.
    """
    from aipass.cli.apps.modules import console
    from aipass.prax.apps.handlers.logging.lifecycle import run_shutdown

    console.print(f"\\[{MODULE_NAME}] Shutting down logging system...")

    run_shutdown(MODULE_NAME)

    console.print(f"\\[{MODULE_NAME}] Shutdown complete")

    try:
        from aipass.trigger.apps.modules.core import trigger

        trigger.fire("logging_system_shutdown")
    except (ImportError, OSError) as e:
        logger.warning("Trigger logging_system_shutdown fire skipped (not available or inotify full): %s", e)


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
        - file_watcher_active: Watcher status in THIS process (see status.py)
        - last_scan: what the last `drone @prax discover` reported, {} if never
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
        "last_scan": load_last_scan(),
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
        "    [dim]→ watcher.py (check_file_watcher_liveness — reports a watcher that died under "
        "an explicit starter; the logger starts none)[/dim]"
    )
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
