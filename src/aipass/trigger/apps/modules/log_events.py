# =================== AIPass ====================
# Name: log_events.py
# Description: Log events module for centralized log watcher public API
# Version: 1.0.0
# Created: 2026-01-31
# Modified: 2026-01-31
# =============================================

"""
Log Events Module - Public API for log event watching

Provides start/stop/status commands for the centralized log watcher.
Trigger owns all log event detection - other branches respond to events.

Commands: start, stop, status
Architecture: Module orchestrates handlers
"""

import sys
from pathlib import Path


from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.trigger.apps.handlers.json import json_handler

# Import handler functions
from aipass.trigger.apps.handlers.watchers.log_watcher import (
    start_log_watcher,
    stop_log_watcher,
    is_log_watcher_active,
    SYSTEM_LOGS_DIR
)


def print_introspection():
    """Display module introspection info."""
    try:
        from aipass.cli.apps.modules.display import console
    except ImportError:
        from rich.console import Console
        console = Console()

    console.print()
    console.print("log_events Module")
    console.print("Centralized log watcher — watches system_logs/ for error and warning events")
    console.print()
    console.print("Connected Handlers:")
    console.print("  handlers/watchers/")
    console.print("    - log_watcher.py (start_log_watcher — start centralized log watcher)")
    console.print("    - log_watcher.py (stop_log_watcher — stop centralized log watcher)")
    console.print("    - log_watcher.py (is_log_watcher_active — check if watcher is running)")
    console.print("    - log_watcher.py (SYSTEM_LOGS_DIR — monitored log directory path)")
    console.print()


def start() -> bool:
    """
    Start the centralized log watcher.

    Watches system_logs/ for log file changes.
    Fires error_logged and warning_logged events.

    Returns:
        True if started successfully, False otherwise
    """
    logger.info("[TRIGGER] Starting log watcher")
    observer = start_log_watcher()
    if observer:
        logger.info(f"[TRIGGER] Log watcher started, monitoring: {SYSTEM_LOGS_DIR}")
        return True
    logger.error("[TRIGGER] Failed to start log watcher")
    return False


def stop() -> None:
    """
    Stop the centralized log watcher.
    """
    logger.info("[TRIGGER] Stopping log watcher")
    stop_log_watcher()
    logger.info("[TRIGGER] Log watcher stopped")


def status() -> dict:
    """
    Get log watcher status.

    Returns:
        Dict with status info:
        {
            'active': bool,
            'log_dir': str
        }
    """
    return {
        'active': is_log_watcher_active(),
        'log_dir': str(SYSTEM_LOGS_DIR)
    }


def print_help() -> None:
    """Print module help."""
    from aipass.cli.apps.modules import console

    console.print("Log Events - Centralized Log Watcher\n")
    console.print("USAGE:")
    console.print("  drone trigger log_events <command>")
    console.print("  python3 log_events.py <command>\n")
    console.print("COMMANDS:")
    console.print("  start  - Start watching logs for errors/warnings")
    console.print("  stop   - Stop the log watcher")
    console.print("  status - Show watcher status\n")
    console.print("EVENTS FIRED:")
    console.print("  error_logged   - When ERROR level log detected")
    console.print("  warning_logged - When WARNING level log detected\n")


def handle_command(command: str, args: list) -> bool:
    """
    Handle log_events commands - orchestrate handler calls.

    Args:
        command: Command to execute (start, stop, status)
        args: Additional arguments

    Returns:
        True if command was handled, False otherwise
    """
    from aipass.cli.apps.modules import console

    # Handle module-name routing (drone @trigger log_events <subcmd>)
    if command == "log_events":
        if not args:
            print_introspection()
            return True
        if args[0] in ['--help', '-h', 'help']:
            print_help()
            return True
        return handle_command(args[0], args[1:])

    if command not in ["start", "stop", "status"]:
        return False

    if args and args[0] in ['--help', '-h', 'help']:
        print_help()
        return True

    if command == "start":
        if start():
            console.print("✅ Log watcher started")
            console.print(f"   Monitoring: {SYSTEM_LOGS_DIR}")
        else:
            console.print("❌ Failed to start log watcher")
    elif command == "stop":
        stop()
        console.print("✅ Log watcher stopped")
    elif command == "status":
        info = status()
        console.print("Log Watcher Status")
        console.print(f"  Active: {info['active']}")
        console.print(f"  Log dir: {info['log_dir']}")

    json_handler.log_operation("log_watcher_command", {"command": command})
    return True


if __name__ == "__main__":
    import argparse
    from aipass.cli.apps.modules import console

    if len(sys.argv) == 1 or sys.argv[1] in ['--help', '-h', 'help']:
        print_help()
        sys.exit(0)

    parser = argparse.ArgumentParser(description='Log Events Module')
    parser.add_argument('command', choices=['start', 'stop', 'status'])
    parsed_args = parser.parse_args()

    handle_command(parsed_args.command, sys.argv[2:])
