# =================== AIPass ====================
# Name: logger.py
# Description: PRAX Public API
# Version: 1.4.1
# Created: 2025-11-15
# Modified: 2026-10-23
# =============================================

"""
PRAX Logger - Public API

Reference: docs/logging_api.md
"""

__all__ = [
    "system_logger",
    "get_system_logger",
    "SystemLogger",
    "get_direct_logger",
    "direct_log",
    "DirectLogger",
    "get_system_status",
    "print_introspection",
    "handle_command",
    "MODULE_NAME",
    "DATA_FILE",
    "append_jsonl",
]

import logging
import sys
from typing import Dict, Any

# CLI imports prax logger, so CLI is imported lazily inside functions, never here.
from aipass.prax.apps.handlers.logging.setup import (
    setup_individual_logger,
    get_captured_loggers_count,
)
from aipass.prax.apps.handlers.logging.introspection import get_caller_info
from aipass.prax.apps.handlers.registry.load import load_module_registry, load_last_scan
from aipass.prax.apps.handlers.config.load import get_system_logs_dir, get_module_logs_dir, PRAX_JSON_DIR
from aipass.prax.apps.handlers.logging.direct import get_direct_logger, direct_log, DirectLogger
from aipass.prax.apps.handlers.logging.jsonl_writer import append_jsonl
from aipass.prax.apps.handlers.json import json_handler

# seedgo requires a module-level 'logger'; SystemLogger methods shadow it on purpose.
logger = logging.getLogger(__name__)

MODULE_NAME = "prax_logger"
DATA_FILE = PRAX_JSON_DIR / f"{MODULE_NAME}_data.json"


def get_system_logger():
    """Get logger that automatically routes to correct module log file.

    One stack walk for name, path and branch: separate walks can disagree on depth.
    """
    module_name, caller_path, branch = get_caller_info()
    return setup_individual_logger(module_name, caller_path=caller_path, caller_branch=branch)


class SystemLogger:
    """Auto-routing logger that writes to calling module's log file"""

    _watcher_started = False

    def _ensure_watcher(self):
        """Keep an explicitly started discovery watcher honest. Starts nothing.

        Only a process that imported and started the watcher has one; never imported here,
        since that pulls the watchdog library into every logging process. `_watcher_started`
        means "past the first log line"; unlocked, since a racing double-set writes the same value.
        """
        if SystemLogger._watcher_started:
            watcher = sys.modules.get("aipass.prax.apps.handlers.discovery.watcher")
            if watcher is not None:
                watcher.check_file_watcher_liveness()  # Throttled; ~1 real check/60s.
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

        Silent at the default INFO level; the level binds when a module's logger is created.
        """
        self._ensure_watcher()
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
    try:
        from aipass.cli.apps.modules.display import console
    except ImportError as e:
        logger.info("CLI console not available, using rich fallback: %s", e)
        from rich.console import Console

        console = Console()

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
    """Handle commands routed by the entry point."""
    json_handler.log_operation("logger_handle_command", {"args": args})
    if not args:
        print_introspection()
        return True
    if args[0] in ("--help", "-h", "help"):
        print_introspection()  # Logger has no user commands — introspection IS the help
        return True
    return False
