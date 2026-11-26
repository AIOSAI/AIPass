# =================== AIPass ====================
# Name: leaderboard.py
# Description: Leaderboard Module
# Version: 1.0.1
# Created: 2026-03-07
# Modified: 2026-11-26
# =============================================

"""
Leaderboard Module
"""

from typing import List

from aipass.prax import logger  # noqa: F401 - the imports standard requires the prax logger in every module
from aipass.cli import console, error

from rich.table import Table

from aipass.commons.apps.handlers.social.leaderboard_ops import show_leaderboard, VALID_CATEGORIES
from aipass.commons.apps.handlers.json import json_handler


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("[bold cyan]leaderboard - Commons Leaderboards[/bold cyan]")
    console.print("[dim]Thin router for leaderboard queries rendered as Rich tables.[/dim]")
    console.print()
    console.print("[bold cyan]Connected Handlers:[/bold cyan]")
    console.print("  [cyan]handlers/social/[/cyan]")
    console.print(
        "    [cyan]-[/cyan] leaderboard_ops.py [dim](show_leaderboard — query ranked leaderboard data by category)[/dim]"
    )
    console.print(
        "    [cyan]-[/cyan] leaderboard_ops.py [dim](VALID_CATEGORIES — list of supported leaderboard categories)[/dim]"
    )
    console.print()
    console.print("[dim]Run 'drone @commons leaderboard --help' for usage[/dim]")


def print_help():
    """Display usage help for leaderboard commands."""
    console.print()
    console.print("[bold cyan]leaderboard - Commons Leaderboards[/bold cyan]")
    console.print("[dim]Show ranked leaderboards for artifacts, trades, posts, rooms and karma.[/dim]")
    console.print()
    console.print("[bold cyan]Usage:[/bold cyan]")
    console.print("  [cyan]drone @commons leaderboard[/cyan] \\[--category artifacts|trades|posts|rooms|karma]")
    console.print("  [cyan]drone @commons leaderboards[/cyan] [dim](alias of leaderboard)[/dim]")
    console.print()
    console.print("[bold cyan]Examples:[/bold cyan]")
    console.print("  [cyan]drone @commons leaderboard[/cyan]")
    console.print("  [cyan]drone @commons leaderboards --category karma[/cyan]")
    console.print()


def handle_command(command: str, args: List[str]) -> bool:
    """Handle leaderboard commands."""
    if command not in ("leaderboard", "leaderboards"):
        return False

    if "--help" in args or "-h" in args:
        print_help()
        return True

    return _handle_leaderboard(args)


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
        error(result["error"])
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
