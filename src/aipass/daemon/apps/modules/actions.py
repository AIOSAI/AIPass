# =================== AIPass ====================
# Name: actions.py
# Description: Action Registry CLI Module (RETIRED)
# Version: 2.0.0
# Created: 2026-03-02
# Modified: 2026-06-25
# =============================================

"""
RETIRED — the numbered action registry CLI.

Superseded by the decentralized .daemon/schedule.json model (DPLAN-0204).
Author jobs directly in a branch's .daemon/schedule.json file.
See: drone @daemon run --help (full schema + schedule types)
"""

from typing import List

from aipass.prax import logger
from aipass.cli.apps.modules import console
from aipass.daemon.apps.handlers.json import json_handler
from aipass.daemon.apps.handlers.cli.arg_gate import gate


def print_introspection():
    """Display retirement notice."""
    console.print()
    console.print("[bold cyan]actions Module[/bold cyan] [yellow](RETIRED)[/yellow]")
    console.print()
    console.print("[dim]This CLI has been retired. Jobs now live in per-branch .daemon/schedule.json files.[/dim]")
    console.print("[dim]Run [bold]drone @daemon run --help[/bold] for the schema and schedule types.[/dim]")
    console.print("[dim]Run [bold]drone @daemon queue[/bold] to see the unified job queue.[/dim]")
    console.print()


def handle_command(command: str, args: List[str]) -> bool:
    """Handle 'actions' command — retired, shows migration notice."""
    if command != "actions":
        return False

    if not args:
        print_introspection()
        return True

    if args[0] in ("--help", "-h", "help"):
        print_introspection()
        return True

    # Same as schedule: the notice is the guidance, the exit code is the verdict.
    json_handler.log_operation("actions_command_retired", {"args": args[:2]})
    logger.info("[actions] Retired CLI invoked with %r", args[0])
    print_introspection()
    gate("actions", args, usage="drone @daemon actions   (retired — see drone @daemon run --help)")
    return True
