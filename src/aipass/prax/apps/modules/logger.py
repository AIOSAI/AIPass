# =================== AIPass ====================
# Name: logger.py
# Description: PRAX Public API
# Version: 1.8.0
# Created: 2025-11-15
# Modified: 2026-11-17
# =============================================

"""
PRAX Logger - Public API

Reference: docs/logging_api.md
"""

__all__ = [
    "system_logger",
    "get_system_logger",
    "SystemLogger",
    "get_system_status",
    "print_introspection",
    "handle_command",
    "MODULE_NAME",
    "DATA_FILE",
    "log_backup_count",
    "LOGGING_ALLOWED",
    "LOGGER_DOORS",
]

from typing import Dict, Any, Tuple

# CLI imports prax logger, so CLI is imported lazily inside functions, never here.
from aipass.prax.apps.handlers.logging.setup import (
    setup_individual_logger,
    get_captured_loggers_count,
)
from aipass.prax.apps.handlers.logging.introspection import get_caller_info
from aipass.prax.apps.handlers.registry.load import load_module_registry, load_last_scan
from aipass.prax.apps.handlers.config.load import (
    get_system_logs_dir,
    get_module_logs_dir,
    load_log_config,
    PRAX_JSON_DIR,
)
from aipass.prax.apps.handlers.json import json_handler

MODULE_NAME = "prax_logger"
DATA_FILE = PRAX_JSON_DIR / f"{MODULE_NAME}_data.json"

#: The prax files allowed to import stdlib logging, by path under src/aipass, each with why. Every other prax
#: file holds none; even these send their own diagnostics to prax's trail.
LOGGING_ALLOWED: Tuple[Tuple[str, str], ...] = (
    (
        "prax/apps/handlers/logging/setup.py",
        "builds door one's per-module loggers on stdlib Logger and RotatingFileHandler",
    ),
    (
        "prax/apps/handlers/logging/direct.py",
        "builds door one's direct loggers on stdlib Logger, Formatter and handlers",
    ),
)

#: The prax files whose classes are prax's logging doors, by path under src/aipass, each with why. No other
#: file in the fleet may define a level-shaped logger class.
LOGGER_DOORS: Tuple[Tuple[str, str], ...] = (
    ("prax/apps/modules/logger.py", "SystemLogger: door one, from aipass.prax import logger"),
    ("prax/apps/handlers/logging/direct.py", "DirectLogger: door one bound at creation, for prax's own handlers"),
    ("prax/apps/handlers/logging/trail.py", "TrailLogger and PraxTrail: door two, from aipass.prax import trail"),
)


def log_backup_count() -> int:
    """Backups the .log tiers keep, the deeper of the two, from the config read now: a rotated-file reader's depth."""
    config = load_log_config()
    return max(config["system_logs"]["backup_count"], config["local_logs"]["backup_count"])


def get_system_logger():
    """Get logger that automatically routes to correct module log file.

    One stack walk for name, path and branch: separate walks can disagree on depth.
    """
    module_name, caller_path, branch = get_caller_info()
    return setup_individual_logger(module_name, caller_path=caller_path, caller_branch=branch)


class SystemLogger:
    """Auto-routing logger that writes to calling module's log file"""

    def info(self, message, *args, **kwargs):
        """Log info message to calling module's log file"""
        logger = get_system_logger()
        logger.info(message, *args, **kwargs)

    def warning(self, message, *args, **kwargs):
        """Log warning message to calling module's log file"""
        logger = get_system_logger()
        logger.warning(message, *args, **kwargs)

    def error(self, message, *args, **kwargs):
        """Log error message to calling module's log file"""
        logger = get_system_logger()
        logger.error(message, *args, **kwargs)

    def debug(self, message, *args, **kwargs):
        """Log debug message to calling module's log file.

        Silent at the default INFO level; the level binds when a module's logger is created.
        """
        logger = get_system_logger()
        logger.debug(message, *args, **kwargs)


system_logger = SystemLogger()


def get_system_status() -> Dict[str, Any]:
    """Get current logging system status"""
    from aipass.prax.apps.handlers.discovery.watcher import is_file_watcher_active
    from aipass.prax.apps.handlers.registry.load import REGISTRY_FILE

    modules = load_module_registry()

    return {
        # None when the registry cannot be read, never a count of 0.
        "total_modules": None if modules is None else len(modules),
        "individual_loggers": get_captured_loggers_count(),
        "system_logs_dir": str(get_system_logs_dir()),
        "module_logs_dir": str(get_module_logs_dir("prax")),
        "registry_file": str(REGISTRY_FILE),
        "file_watcher_active": is_file_watcher_active(),
        "last_scan": load_last_scan(),
    }


def print_introspection():
    """Display module introspection info."""
    from aipass.cli import console

    console.print()
    console.print("[bold cyan]logger Module[/bold cyan]")
    console.print("Public API for PRAX system-wide logging with auto-routing")
    console.print()
    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print()
    console.print("  [cyan]handlers/logging/[/cyan]")
    console.print("    [dim]→ setup.py (setup_individual_logger — creates per-module log files)[/dim]")
    console.print("    [dim]→ setup.py (get_captured_loggers_count — returns active logger count)[/dim]")
    console.print("    [dim]→ introspection.py (get_caller_info — resolves caller module name)[/dim]")
    console.print("    [dim]→ direct.py (get_direct_logger — bypasses event pipeline for infrastructure logging)[/dim]")
    console.print("    [dim]→ direct.py (DirectLogger — direct logger class)[/dim]")
    console.print()
    console.print("  [cyan]handlers/discovery/[/cyan]")
    console.print("    [dim]→ watcher.py (is_file_watcher_active — checks watcher status)[/dim]")
    console.print()
    console.print("  [cyan]handlers/registry/[/cyan]")
    console.print("    [dim]→ load.py (load_module_registry — loads discovered module registry)[/dim]")
    console.print()
    console.print("  [cyan]handlers/config/[/cyan]")
    console.print("    [dim]→ load.py (get_system_logs_dir — returns system logs directory path)[/dim]")
    console.print("    [dim]→ load.py (get_module_logs_dir — returns per-module logs directory path)[/dim]")
    console.print("    [dim]→ load.py (load_log_config — the tiers' backup_count, published as log_backup_count)[/dim]")
    console.print("    [dim]→ load.py (PRAX_JSON_DIR — base path for prax JSON data files)[/dim]")
    console.print()


def handle_command(_command: str, args: list) -> bool:
    """Handle commands routed by the entry point."""
    json_handler.log_operation("logger_handle_command", {"args": args})
    if not args:
        print_introspection()
        return True
    if args[0] in ("--help", "-h", "help"):
        print_introspection()  # Logger has no user commands — introspection IS the help
        return True
    return False
