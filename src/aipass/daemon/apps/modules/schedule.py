# =================== AIPass ====================
# Name: schedule.py
# Description: DAEMON Scheduled Follow-ups Module (RETIRED)
# Version: 2.0.0
# Created: 2026-02-04
# Modified: 2026-06-25
# =============================================

"""
RETIRED — the old fire-and-forget follow-up CLI.

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
    console.print("[bold cyan]schedule Module[/bold cyan] [yellow](RETIRED)[/yellow]")
    console.print()
    console.print("[dim]This CLI has been retired. Jobs now live in per-branch .daemon/schedule.json files.[/dim]")
    console.print("[dim]Run [bold]drone @daemon run --help[/bold] for the schema and schedule types.[/dim]")
    console.print("[dim]Run [bold]drone @daemon queue[/bold] to see the unified job queue.[/dim]")
    console.print()


def handle_command(command: str, args: List[str]) -> bool:
    """Handle 'schedule' command — retired, shows migration notice."""
    if command != "schedule":
        return False

    if not args:
        print_introspection()
        return True

    if args[0] in ("--help", "-h", "help"):
        print_introspection()
        return True

    # The migration notice is still the right GUIDANCE, so it prints - but a
    # retired subcommand did not do what the caller asked, and exiting 0 told
    # their `&&` that it did. Notice first, then refuse by name.
    json_handler.log_operation("schedule_command_retired", {"args": args[:2]})
    logger.info("[schedule] Retired CLI invoked with %r", args[0])
    print_introspection()
    gate("schedule", args, usage="drone @daemon schedule   (retired — see drone @daemon run --help)")
    return True
