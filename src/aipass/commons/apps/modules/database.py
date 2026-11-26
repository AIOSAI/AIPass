# =================== AIPass ====================
# Name: database.py
# Description: Database Module Layer
# Version: 1.2.0
# Created: 2026-03-08
# Modified: 2026-11-26
# =============================================

"""Database module: schema setup for the entry point, and introspection of handlers/database."""

from typing import List

from aipass.prax import logger  # noqa: F401 - the imports standard requires the prax logger in every module
from aipass.cli import console

from aipass.commons.apps.handlers.database import init_db, close_db
from aipass.commons.apps.handlers.json import json_handler

__all__ = ["init_schema", "handle_command"]


def init_schema() -> None:
    """Create the schema and default rooms, then release the connection."""
    close_db(init_db())


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("[bold cyan]database - Database Service[/bold cyan]")
    console.print("[dim]Service module providing database initialization and connection management.[/dim]")
    console.print()
    console.print("[bold cyan]Connected Handlers:[/bold cyan]")
    console.print("  [cyan]handlers/database/[/cyan]")
    console.print("    [cyan]-[/cyan] db.py [dim](init_db — initialize SQLite database and create schema)[/dim]")
    console.print("    [cyan]-[/cyan] db.py [dim](close_db — safely close a database connection)[/dim]")
    console.print("    [cyan]-[/cyan] db.py [dim](get_db — get or create a database connection)[/dim]")
    console.print()
    console.print("[dim]Run 'drone @commons database --help' for usage[/dim]")


def print_help():
    """Display usage help for the database command."""
    console.print()
    console.print("[bold cyan]database - Database Service[/bold cyan]")
    console.print("[dim]Show the database module's connected handlers[/dim]")
    console.print()
    console.print("[bold cyan]Usage:[/bold cyan]")
    console.print("  [cyan]drone @commons database[/cyan]")
    console.print()
    console.print("[bold cyan]Examples:[/bold cyan]")
    console.print("  [cyan]drone @commons database[/cyan]")
    console.print()


def handle_command(command: str, args: List[str]) -> bool:
    """Handle only bare `database` (introspection); every other command is declined."""
    if command == "database":
        if "--help" in args or "-h" in args:
            print_help()
            return True
        if not args:
            print_introspection()
            json_handler.log_operation("database_executed", {"command": "database", "success": True})
            return True
    return False
