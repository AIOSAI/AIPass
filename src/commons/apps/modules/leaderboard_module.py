# =================== AIPass ====================
# Name: leaderboard_module.py
# Description: Leaderboard Module
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-03-07
# =============================================

"""
Leaderboard Module

Thin router for leaderboard commands. Delegates all query logic
to handlers/social/leaderboard_ops.py and renders results as Rich tables.

Handles: leaderboard, leaderboards commands.
"""

from typing import List

from aipass.prax.apps.modules.logger import system_logger as logger

try:
    from aipass.cli.apps.modules import console
except ImportError:
    from rich.console import Console
    console = Console()

from rich.table import Table

from commons.apps.handlers.social.leaderboard_ops import show_leaderboard, VALID_CATEGORIES
from commons.apps.handlers.json import json_handler


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("leaderboard_module Module")
    console.print("Thin router for leaderboard queries rendered as Rich tables.")
    console.print()
    console.print("Connected Handlers:")
    console.print("  handlers/social/")
    console.print("    - leaderboard_ops.py (show_leaderboard — query ranked leaderboard data by category)")
    console.print("    - leaderboard_ops.py (VALID_CATEGORIES — list of supported leaderboard categories)")
    console.print()


# =============================================================================
# COMMAND ROUTING
# =============================================================================

def handle_command(command: str, args: List[str]) -> bool:
    """
    Handle leaderboard commands.

    Args:
        command: Command name (leaderboard, leaderboards)
        args: Command arguments

    Returns:
        True if command handled, False otherwise
    """
    if command not in ("leaderboard", "leaderboards"):
        return False

    return _handle_leaderboard(args)


# =============================================================================
# DISPLAY HANDLER
# =============================================================================

BOARD_TITLES = {
    "artifacts": "Most Artifacts",
    "trades": "Most Trades",
    "posts": "Most Posts",
    "rooms": "Most Active Rooms (7 days)",
    "karma": "Top Karma",
}

BOARD_COLUMNS = {
    "artifacts": ("Branch", "Artifacts"),
    "trades": ("Branch", "Trades/Gifts"),
    "posts": ("Branch", "Posts"),
    "rooms": ("Room", "Posts (7d)"),
    "karma": ("Branch", "Karma"),
}


def _handle_leaderboard(args: List[str]) -> bool:
    """Query leaderboard data and render as Rich tables."""
    result = show_leaderboard(args)

    if not result["success"]:
        console.print(f"[red]{result['error']}[/red]")
        return True

    boards = result["boards"]

    console.print()
    console.print("[bold cyan]--- Leaderboards ---[/bold cyan]")
    console.print()

    for category in VALID_CATEGORIES:
        if category not in boards:
            continue

        rows = boards[category]
        title = BOARD_TITLES[category]
        name_col, count_col = BOARD_COLUMNS[category]

        if not rows:
            console.print(f"[dim]No data for {title.lower()}.[/dim]")
            console.print()
            continue

        table = Table(title=title, border_style="cyan")
        table.add_column("Rank", style="dim", width=5)
        table.add_column(name_col, style="bold")
        table.add_column(count_col, justify="right")

        for i, row in enumerate(rows, 1):
            if category == "rooms":
                name = f"r/{row['room']}"
            else:
                name = row["branch"]
            table.add_row(str(i), name, str(row["count"]))

        console.print(table)
        console.print()

    json_handler.log_operation("leaderboard_executed", {"command": "leaderboard", "success": True})
    return True
