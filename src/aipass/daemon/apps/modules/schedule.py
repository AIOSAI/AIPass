# =================== AIPass ====================
# Name: schedule.py
# Description: DAEMON Scheduled Follow-ups Module (RETIRED)
# Version: 2.1.0
# Created: 2026-02-04
# Modified: 2026-11-26
# =============================================

"""
RETIRED — the old fire-and-forget follow-up CLI.
Author jobs in a branch's .daemon/schedule.json; see drone @daemon run --help."""

from typing import List

from aipass.prax import logger
from aipass.cli import console
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


def print_help():
    """Retired verb: the only usage left is the notice; jobs are authored in .daemon/schedule.json."""
    console.print()
    console.print("[bold cyan]schedule[/bold cyan] [yellow](RETIRED)[/yellow]")
    console.print()
    console.print("[yellow]USAGE:[/yellow]")
    console.print("  drone @daemon schedule           Print the retirement notice")
    console.print("  drone @daemon run --help        The job schema that replaced it")
    console.print()
    console.print("[yellow]EXAMPLES:[/yellow]")
    console.print("  drone @daemon queue")
    console.print("  drone @daemon run --dry-run")
    console.print()


def handle_command(command: str, args: List[str]) -> bool:
    """Handle 'schedule' command — retired, shows migration notice."""
    if command != "schedule":
        return False

    if not args:
        print_introspection()
        return True

    if args[0] in ("--help", "-h", "help"):
        print_help()
        return True

    # Notice first, then refuse by name: exiting 0 would tell the caller's `&&` the retired verb worked.
    json_handler.log_operation("schedule_command_retired", {"args": args[:2]})
    logger.info("[schedule] Retired CLI invoked with %r", args[0])
    print_introspection()
    gate("schedule", args, usage="drone @daemon schedule   (retired — see drone @daemon run --help)")
    return True
