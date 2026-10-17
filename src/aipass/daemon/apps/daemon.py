# =================== AIPass ====================
# Name: daemon.py
# Description: Entry point CLI for drone @daemon
# Version: 1.2.0
# Created: 2026-03-08
# Modified: 2026-10-17
# =============================================

"""
DAEMON Branch - Main Orchestrator
"""

import os
import sys
from typing import List, Any

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

from aipass.prax.apps.modules.logger import system_logger as logger

from aipass.cli.apps.modules import console, error, reset_command_state, resolve_exit
from aipass.daemon.apps.handlers.json import json_handler
from aipass.daemon.apps.modules import (
    UnknownArgument,
    update,
    schedule,
    activity_report,
    actions,
    run,
    timer_install,
    queue,
    inbox_sweep,
    rotation,
)


def _header(text):
    console.print(f"\n[bold cyan]{'=' * 70}[/bold cyan]")
    console.print(f"[bold cyan]  {text}[/bold cyan]")
    console.print(f"[bold cyan]{'=' * 70}[/bold cyan]")


def get_modules() -> List[Any]:
    """Return list of known modules that implement handle_command()."""
    modules = []
    for mod in [update, schedule, activity_report, actions, run, timer_install, queue, inbox_sweep, rotation]:
        if hasattr(mod, "handle_command"):
            modules.append(mod)
    return modules


def route_command(command: str, args: List[str], modules: List[Any]) -> bool:
    """Route command to appropriate module. True if handled.

    A module exception or UnknownArgument stops routing: error() names the verb, exit 1.
    """
    for module in modules:
        try:
            if module.handle_command(command, args):
                return True
        # Before the generic handler, so the refusal names the argument, not "unknown command".
        except UnknownArgument as refusal:
            error(f"{refusal.verb}: unknown argument '{refusal.token}'", refusal.usage or None)
            sys.exit(1)
        # Modules refuse unowned verbs before any work, so this exception is the owner's: stop.
        except Exception as e:
            logger.error(f"[DAEMON] Module {module.__name__} error: {e}", exc_info=True)
            error(f"{command} failed: {e}")
            sys.exit(1)

    return False


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
            description = "No description"
            if module.__doc__:
                description = module.__doc__.strip().split("\n")[0]
            console.print(f"  [cyan]*[/cyan] {module_name:20} [dim]{description}[/dim]")
    else:
        console.print("  [dim]No modules discovered[/dim]")

    console.print()
    console.print("[dim]Run 'drone @daemon --help' for usage information[/dim]")
    console.print()


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
    console.print("  [dim]drone @daemon --version[/dim]")
    console.print()
    console.print("-" * 70)
    console.print()

    console.print("[bold cyan]AVAILABLE COMMANDS:[/bold cyan]")
    console.print()

    _COMMAND_HELP = [
        ("update", "Returns digest of DAEMON activity for check-ins."),
        ("queue", "Unified job queue view (--json for frozen schema)."),
        ("activity", "Quick 24-hour activity summary."),
        ("activity-report", "Full detailed activity report (--json for raw)."),
        ("branch-health", "Single branch deep dive (e.g., branch-health DAEMON)."),
        ("run", "One scheduler tick: discover .daemon/ jobs, fire due ones."),
        ("rotation", "Steward rotation — roster, whose turn is next, recent turns."),
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
    console.print("    [dim]drone @daemon rotation[/dim]                          [dim]# Whose rounds night[/dim]")
    console.print("    [dim]drone @daemon install-timer[/dim]                     [dim]# Enable systemd timer[/dim]")
    console.print()
    console.print("  [yellow]Fleet mail:[/yellow]")
    console.print("    [dim]drone @daemon inbox-sweep --dry-run[/dim]             [dim]# Who has stale mail[/dim]")
    console.print("    [dim]drone @daemon inbox-sweep[/dim]                       [dim]# Wake those owners[/dim]")
    console.print()

    console.print("[bold]TIP:[/bold] For module-specific help:")
    console.print("  [dim]drone @daemon <command> --help[/dim]")
    console.print()


def main():
    """Main entry point - routes commands or shows help.

    Returns resolve_exit(handled): 0 clean, 2 routed but error() was called, 1 not routed.
    """
    reset_command_state()

    modules = get_modules()

    args = sys.argv[1:]

    if len(args) == 0:
        print_introspection(modules)
        return 0

    if args[0] in ["--version", "-V"]:
        console.print("DAEMON v1.1.0")
        return 0

    if args[0] in ["--help", "-h", "help"]:
        print_help(modules)
        return 0

    command = args[0]
    remaining_args = args[1:] if len(args) > 1 else []

    # Scans EVERY arg: a help flag after other tokens must never fall through and fire jobs.
    if any(arg in ("--help", "-h") for arg in remaining_args):
        for module in modules:
            if module.handle_command(command, ["--help"]):
                return 0
        print_help(modules)
        return 0

    json_handler.log_operation("daemon_command", {"command": command})

    handled = route_command(command, remaining_args, modules)
    if handled:
        logger.info("[DAEMON] Command routed successfully: %s", command)
    else:
        console.print()
        error(f"Unknown command: {command}", suggestion="Run 'drone @daemon --help' for available commands")
        console.print()
    return resolve_exit(handled)


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
