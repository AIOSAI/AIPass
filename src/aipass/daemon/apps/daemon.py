# =================== AIPass ====================
# Name: daemon.py
# Description: Entry point CLI for drone @daemon
# Version: 1.0.1
# Created: 2026-03-08
# Modified: 2026-08-11
# =============================================

"""
DAEMON Branch - Main Orchestrator

Explicit module imports:
- Imports known modules from modules/ directory
- Routes commands to discovered modules automatically
"""

# Standard library imports
import os
import sys
from typing import List, Any

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

# Logger
from aipass.prax.apps.modules.logger import system_logger as logger

# Console
from aipass.cli.apps.modules import console, error
from aipass.daemon.apps.handlers.json import json_handler
from aipass.daemon.apps.modules import (
    update,
    schedule,
    activity_report,
    actions,
    run,
    timer_install,
    queue,
    inbox_sweep,
)


def _header(text):
    console.print(f"\n[bold cyan]{'=' * 70}[/bold cyan]")
    console.print(f"[bold cyan]  {text}[/bold cyan]")
    console.print(f"[bold cyan]{'=' * 70}[/bold cyan]")


# =============================================================================
# MODULE DISCOVERY
# =============================================================================


def get_modules() -> List[Any]:
    """
    Return list of known modules that implement handle_command().

    Returns:
        List of module objects with handle_command function
    """
    modules = []
    for mod in [update, schedule, activity_report, actions, run, timer_install, queue, inbox_sweep]:
        if hasattr(mod, "handle_command"):
            modules.append(mod)
    return modules


def route_command(command: str, args: List[str], modules: List[Any]) -> bool:
    """
    Route command to appropriate module

    Args:
        command: Command name (e.g., 'create', 'update', 'list')
        args: Additional arguments
        modules: List of discovered modules

    Returns:
        True if command was handled, False otherwise
    """
    for module in modules:
        try:
            if module.handle_command(command, args):
                return True
        except Exception as e:
            logger.error(f"[DAEMON] Module {module.__name__} error: {e}")

    return False


# =============================================================================
# INTROSPECTION DISPLAY
# =============================================================================


def print_introspection(modules: List[Any]):
    """Display discovered modules when run without arguments"""
    console.print()
    console.print("[bold cyan]DAEMON - Branch Management System[/bold cyan]")
    console.print()
    console.print("[dim]Module orchestration[/dim]")
    console.print()

    console.print(f"[yellow]Modules:[/yellow] {len(modules)}")
    console.print()

    if modules:
        for module in modules:
            module_name = module.__name__.split(".")[-1]
            # Get first line of docstring
            description = "No description"
            if module.__doc__:
                description = module.__doc__.strip().split("\n")[0]
            console.print(f"  [cyan]*[/cyan] {module_name:20} [dim]{description}[/dim]")
    else:
        console.print("  [dim]No modules discovered[/dim]")

    console.print()
    console.print("[dim]Run 'drone @daemon --help' for usage information[/dim]")
    console.print()


# =============================================================================
# DRONE COMPLIANCE - HELP SYSTEM
# =============================================================================


def print_help(modules: List[Any]):
    """Display Rich-formatted help"""
    console.print()
    _header("DAEMON - Branch Management System")
    console.print()

    console.print("[dim]Module orchestration[/dim]")
    console.print()
    console.print("-" * 70)
    console.print()

    console.print("[bold cyan]USAGE:[/bold cyan]")
    console.print()
    console.print("  [dim]drone @daemon <command> \\[args...][/dim]")
    console.print("  [dim]drone @daemon --help[/dim]")
    console.print()
    console.print("-" * 70)
    console.print()

    console.print("[bold cyan]AVAILABLE COMMANDS:[/bold cyan]")
    console.print()

    # Show actual routable commands, not module names
    _COMMAND_HELP = [
        ("update", "Returns digest of DAEMON activity for check-ins."),
        ("queue", "Unified job queue view (--json for frozen schema)."),
        ("activity", "Quick 24-hour activity summary."),
        ("activity-report", "Full detailed activity report (--json for raw)."),
        ("branch-health", "Single branch deep dive (e.g., branch-health DAEMON)."),
        ("run", "One scheduler tick: discover .daemon/ jobs, fire due ones."),
        ("inbox-sweep", "Wake branches sitting on mail unread past 24h."),
        ("install-timer", "Install + enable daemon-tick systemd user timer (~2 min)."),
        ("uninstall-timer", "Stop + remove daemon-tick systemd user timer."),
        ("schedule", "(retired) Use .daemon/schedule.json — see run --help."),
        ("actions", "(retired) Use .daemon/schedule.json — see run --help."),
    ]

    for cmd_name, desc in _COMMAND_HELP:
        console.print(f"  [green]{cmd_name:20}[/green] [dim]{desc}[/dim]")

    console.print()
    console.print("-" * 70)
    console.print()

    console.print("[bold cyan]EXAMPLES:[/bold cyan]")
    console.print()
    console.print("  [yellow]Status & monitoring:[/yellow]")
    console.print("    [dim]drone @daemon update[/dim]                            [dim]# Status digest[/dim]")
    console.print("    [dim]drone @daemon activity[/dim]                          [dim]# Quick 24h summary[/dim]")
    console.print("    [dim]drone @daemon activity-report --json[/dim]            [dim]# Full report (raw)[/dim]")
    console.print("    [dim]drone @daemon branch-health DAEMON[/dim]              [dim]# Single branch dive[/dim]")
    console.print()
    console.print("  [yellow]Scheduler:[/yellow]")
    console.print("    [dim]drone @daemon queue[/dim]                             [dim]# View pending jobs[/dim]")
    console.print("    [dim]drone @daemon run[/dim]                               [dim]# Fire due jobs now[/dim]")
    console.print("    [dim]drone @daemon install-timer[/dim]                     [dim]# Enable systemd timer[/dim]")
    console.print()
    console.print("  [yellow]Fleet mail:[/yellow]")
    console.print("    [dim]drone @daemon inbox-sweep --dry-run[/dim]             [dim]# Who has stale mail[/dim]")
    console.print("    [dim]drone @daemon inbox-sweep[/dim]                       [dim]# Wake those owners[/dim]")
    console.print()

    console.print("[bold]TIP:[/bold] For module-specific help:")
    console.print("  [dim]drone @daemon <command> --help[/dim]")
    console.print()


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================


def main():
    """Main entry point - routes commands or shows help"""

    # Get available modules
    modules = get_modules()

    # Parse arguments
    args = sys.argv[1:]

    # Show introspection when run with no arguments
    if len(args) == 0:
        print_introspection(modules)
        return 0

    # Version flag
    if args[0] in ["--version", "-V"]:
        console.print("DAEMON v1.0.0")
        return 0

    # Show help for explicit help flags
    if args[0] in ["--help", "-h", "help"]:
        print_help(modules)
        return 0

    # Extract command and remaining args
    command = args[0]
    remaining_args = args[1:] if len(args) > 1 else []

    # Subcommand --help guard — intercept before dispatch
    if remaining_args and remaining_args[0] in ["--help", "-h"]:
        for module in modules:
            if module.handle_command(command, ["--help"]):
                return 0
        print_help(modules)
        return 0

    json_handler.log_operation("daemon_command", {"command": command})

    # Route to modules
    if route_command(command, remaining_args, modules):
        logger.info("[DAEMON] Command routed successfully: %s", command)
        return 0
    else:
        console.print()
        error(f"Unknown command: {command}", suggestion="Run 'drone @daemon --help' for available commands")
        console.print()
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        logger.warning("DAEMON operation cancelled by user (KeyboardInterrupt)")
        console.print("\n\nOperation cancelled by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"DAEMON entry point error: {e}", exc_info=True)
        console.print(f"\nError: {e}")
        sys.exit(1)
