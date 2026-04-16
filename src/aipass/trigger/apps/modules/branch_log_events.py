# =================== AIPass ====================
# Name: branch_log_events.py
# Description: Branch log events module for log watcher public API
# Version: 1.0.0
# Created: 2026-02-02
# Modified: 2026-02-02
# =============================================

"""
Branch Log Events Module - Public API for branch log watching

Provides start/stop/status commands for the branch log watcher.
Watches src/aipass/*/logs/*.log for ERROR entries.
Fires error_detected events handled by AI_Mail's error_handler.

Commands: start, stop, status
Architecture: Module orchestrates handlers
"""

import sys


from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.trigger.apps.handlers.json import json_handler
from aipass.trigger.apps.modules.core import trigger

from aipass.trigger.apps.handlers.log_watcher import (
    set_event_callback,
    start_branch_log_watcher,
    stop_branch_log_watcher,
    get_watcher_status,
    clear_seen_hashes,
)
from aipass.trigger.apps.config import AIPASS_PKG_ROOT


def print_introspection():
    """Display module introspection info."""
    try:
        from aipass.cli.apps.modules.display import console
    except ImportError:
        logger.info("CLI console not available, using rich fallback")
        from rich.console import Console

        console = Console()

    console.print()
    console.print("branch_log_events Module")
    console.print("Branch log watcher — watches branch logs for ERROR entries and fires events")
    console.print()
    console.print("Connected Handlers:")
    console.print("  handlers/")
    console.print("    - log_watcher.py (set_event_callback — set callback for detected events)")
    console.print("    - log_watcher.py (start_branch_log_watcher — start filesystem watcher)")
    console.print("    - log_watcher.py (stop_branch_log_watcher — stop filesystem watcher)")
    console.print("    - log_watcher.py (is_branch_log_watcher_active — check watcher state)")
    console.print("    - log_watcher.py (get_watcher_status — get full status dict)")
    console.print("    - log_watcher.py (clear_seen_hashes — reset error deduplication)")
    console.print()


def start() -> bool:
    """
    Start the branch log watcher.

    Watches src/aipass/*/logs/*.log for ERROR entries.
    Fires error_detected events to registered handlers.

    Returns:
        True if started successfully, False otherwise
    """
    logger.info("[TRIGGER] Starting branch log watcher")

    # Set the event callback to trigger.fire
    set_event_callback(trigger.fire)

    # Start the watcher
    observer = start_branch_log_watcher()
    if observer:
        logger.info(f"[TRIGGER] Branch log watcher started, monitoring: {AIPASS_PKG_ROOT}/*/logs/*.log")
        return True
    logger.error("[TRIGGER] Failed to start branch log watcher")
    return False


def stop() -> None:
    """
    Stop the branch log watcher.
    """
    logger.info("[TRIGGER] Stopping branch log watcher")
    stop_branch_log_watcher()
    logger.info("[TRIGGER] Branch log watcher stopped")


def status() -> dict:
    """
    Get branch log watcher status.

    Returns:
        Dict with status info from handler
    """
    return get_watcher_status()


def reset_hashes() -> None:
    """
    Clear the error deduplication hash set.

    Useful after extended runtime or for testing.
    """
    clear_seen_hashes()
    logger.info("[TRIGGER] Branch log watcher hash set cleared")


def print_help() -> None:
    """Print module help."""
    from aipass.cli.apps.modules import console
    from rich.panel import Panel

    console.print(Panel("Branch Log Events - Branch Log Watcher", style="bold"))
    console.print()
    console.print("Watches branch log directories for ERROR entries.")
    console.print("Fires error_detected events for the Medic dispatch pipeline.")
    console.print()
    console.rule("USAGE")
    console.print()
    console.print("  drone @trigger branch_log_events <command>")
    console.print()
    console.rule("COMMANDS")
    console.print()
    console.print("  [bold]start[/bold]   Start watching branch logs for errors")
    console.print("  [bold]stop[/bold]    Stop the branch log watcher")
    console.print("  [bold]status[/bold]  Show watcher status")
    console.print("  [bold]reset[/bold]   Clear error deduplication hashes")
    console.print()
    console.rule("MONITORING")
    console.print()
    console.print(f"  [dim]Path:[/dim]   {AIPASS_PKG_ROOT}/*/logs/*.log")
    console.print("  [dim]Format:[/dim] Prax log format (timestamp | module | LEVEL | message)")
    console.print()
    console.rule("EVENTS FIRED")
    console.print()
    console.print("  [bold]error_detected[/bold]  When ERROR/CRITICAL level log detected")
    console.print("                   Handled by Medic dispatch pipeline")
    console.print()


def handle_command(command: str, args: list) -> bool:
    """
    Handle branch_log_events commands - orchestrate handler calls.

    Args:
        command: Module name or subcommand (branch_log_events, start, stop, status, reset)
        args: Additional arguments

    Returns:
        True if command was handled, False otherwise
    """
    from aipass.cli.apps.modules import console

    # Handle module-name routing (drone @trigger branch_log_events <subcmd>)
    if command == "branch_log_events":
        if not args:
            print_introspection()
            return True
        if args[0] in ["--help", "-h", "help"]:
            print_help()
            return True
        subcommand = args[0]
        remaining = args[1:]
        return handle_command(subcommand, remaining)

    # Help gate — catch --help passed as direct command
    if command in ["--help", "-h", "help"]:
        print_help()
        return True

    # Handle direct subcommands
    if command not in ["start", "stop", "status", "reset"]:
        return False

    if args and args[0] in ["--help", "-h", "help"]:
        print_help()
        return True

    if command == "start":
        if start():
            console.print("✅ Branch log watcher started")
            console.print(f"   Monitoring: {AIPASS_PKG_ROOT}/*/logs/*.log")
            console.print("   Events: error_detected → AI_Mail error_handler")
        else:
            console.print("❌ Failed to start branch log watcher")
            console.print("   Check if watchdog package is installed")
    elif command == "stop":
        stop()
        console.print("✅ Branch log watcher stopped")
    elif command == "status":
        info = status()
        console.print("Branch Log Watcher Status")
        console.print(f"  Active: {info['active']}")
        console.print(f"  Watchdog available: {info['watchdog_available']}")
        console.print(f"  Seen error hashes: {info['seen_hashes_count']}")
        console.print(f"  AIPASS root: {info['aipass_root']}")
    elif command == "reset":
        reset_hashes()
        console.print("✅ Error deduplication hashes cleared")

    json_handler.log_operation("watcher_command", {"command": command})
    return True


if __name__ == "__main__":
    import argparse

    if len(sys.argv) == 1 or sys.argv[1] in ["--help", "-h", "help"]:
        print_help()
        sys.exit(0)

    parser = argparse.ArgumentParser(description="Branch Log Events Module")
    parser.add_argument("command", choices=["start", "stop", "status", "reset"])
    parsed_args = parser.parse_args()

    handle_command(parsed_args.command, sys.argv[2:])
