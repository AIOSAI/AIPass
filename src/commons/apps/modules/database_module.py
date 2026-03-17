# =================== AIPass ====================
# Name: database_module.py
# Description: Database Module Layer
# Version: 1.1.0
# Created: 2026-03-08
# Modified: 2026-03-08
# =============================================

"""
Database Module

Module-layer wrapper for database handler. Provides database initialization
and connection management to the entry point without direct handler imports.

This is a service module — it does not handle user-facing commands.
Other modules import init_db/close_db/get_db directly.
"""

from typing import List

from aipass.prax import logger

try:
    from aipass.cli.apps.modules import console
except ImportError:
    from rich.console import Console
    console = Console()

from commons.apps.handlers.database import init_db, close_db, get_db
from commons.apps.handlers.json import json_handler

__all__ = ["init_db", "close_db", "get_db", "handle_command"]


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("database_module Module")
    console.print("Service module providing database initialization and connection management.")
    console.print()
    console.print("Connected Handlers:")
    console.print("  handlers/database/")
    console.print("    - db.py (init_db — initialize SQLite database and create schema)")
    console.print("    - db.py (close_db — safely close a database connection)")
    console.print("    - db.py (get_db — get or create a database connection)")
    console.print()


# =============================================================================
# COMMAND ROUTING
# =============================================================================

def handle_command(command: str, args: List[str]) -> bool:
    """
    Handle commands routed by the entry point.

    This is a service module providing database connections to other modules.
    It does not handle any user-facing commands directly.

    Args:
        command: The command name.
        args: Additional arguments.

    Returns:
        Always False — this module is infrastructure only.
    """
    if command == "database":
        if not args:
            print_introspection()
            json_handler.log_operation("database_executed", {"command": "database", "success": True})
            return True
    return False
