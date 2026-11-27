# =================== AIPass ====================
# Name: trade.py
# Description: Trade Orchestration Module
# Version: 1.1.2
# Created: 2026-03-07
# Modified: 2026-11-26
# =============================================

"""
Trade Orchestration Module

Router + display layer for trading workflows. Delegates all logic
to handlers/artifacts/trade_ops.py and renders results with Rich.

Handles: gift, trade, drop, find, mint commands.
"""

from typing import List

from aipass.prax import logger  # noqa: F401 - the imports standard requires the prax logger in every module
from aipass.cli import console, error, warning

from rich.panel import Panel

from aipass.commons.apps.handlers.artifacts.trade_ops import (
    gift_artifact,
    trade_artifact,
    drop_item,
    find_item,
    mint_event_artifact,
)
from aipass.commons.apps.handlers.json import json_handler
from aipass.commons.apps.modules.artifact import RARITY_COLORS


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("[bold cyan]trade - Trading[/bold cyan]")
    console.print(
        "[dim]Router and display layer for trading workflows — gifting, trading, dropping, finding, and minting artifacts.[/dim]"
    )
    console.print()
    console.print("[bold cyan]Connected Handlers:[/bold cyan]")
    console.print("  [cyan]handlers/artifacts/[/cyan]")
    console.print("    [cyan]-[/cyan] trade_ops.py [dim](gift_artifact — gift an artifact to another branch)[/dim]")
    console.print("    [cyan]-[/cyan] trade_ops.py [dim](trade_artifact — swap artifacts between two branches)[/dim]")
    console.print(
        "    [cyan]-[/cyan] trade_ops.py [dim](drop_item — drop an artifact in a room for others to find)[/dim]"
    )
    console.print("    [cyan]-[/cyan] trade_ops.py [dim](find_item — pick up a dropped artifact)[/dim]")
    console.print(
        "    [cyan]-[/cyan] trade_ops.py [dim](mint_event_artifact — mint event badge artifacts for participants)[/dim]"
    )
    console.print()
    console.print("[dim]Run 'drone @commons gift --help' for usage[/dim]")


def print_help():
    """Display usage help for the trade module."""
    console.print()
    console.print("[bold cyan]trade - Trading[/bold cyan]")
    console.print("[dim]Gift, trade, drop, find and mint artifacts.[/dim]")
    console.print()
    console.print("[bold cyan]Usage:[/bold cyan]")
    console.print("  [cyan]drone @commons gift[/cyan] <artifact_id> @branch")
    console.print("  [cyan]drone @commons trade[/cyan] <your_artifact_id> <their_artifact_id> @branch")
    console.print('  [cyan]drone @commons drop[/cyan] "name" "description" <room> \\[--expires 5]')
    console.print("  [cyan]drone @commons find[/cyan] <artifact_id>")
    console.print('  [cyan]drone @commons mint[/cyan] "Event Name" @branch1 @branch2 ...')
    console.print()
    console.print("[bold cyan]Examples:[/bold cyan]")
    console.print("  [cyan]drone @commons gift 12 @seedgo[/cyan]")
    console.print("  [cyan]drone @commons trade 12 34 @seedgo[/cyan]")
    console.print('  [cyan]drone @commons drop "Lucky Coin" "A shiny coin" general --expires 10[/cyan]')
    console.print("  [cyan]drone @commons find 56[/cyan]")
    console.print('  [cyan]drone @commons mint "Launch Party" @seedgo @prax[/cyan]')
    console.print()


# =============================================================================
# COMMAND ROUTING
# =============================================================================

TRADE_COMMANDS = ["gift", "trade", "drop", "find", "mint"]


def handle_command(command: str, args: List[str]) -> bool:
    """Handle trade-related commands."""
    if command not in TRADE_COMMANDS:
        return False

    if "--help" in args or "-h" in args:
        print_help()
        return True

    if command == "gift":
        result = _handle_gift(args)
    elif command == "trade":
        result = _handle_trade(args)
    elif command == "drop":
        result = _handle_drop(args)
    elif command == "find":
        result = _handle_find(args)
    elif command == "mint":
        result = _handle_mint(args)
    else:
        return False

    if result:
        json_handler.log_operation(f"{command}_executed", {"command": command, "success": True})
    return result


# =============================================================================
# DISPLAY HANDLERS
# =============================================================================


def _handle_gift(args: List[str]) -> bool:
    result = gift_artifact(args)
    if not result["success"]:
        error(result["error"])
        return True

    rarity_color = RARITY_COLORS.get(result["rarity"], "white")
    console.print()
    console.print(
        Panel(
            f"[bold]{result['sender']}[/bold] gifted [{rarity_color}]{result['name']}[/{rarity_color}] "
            f"([dim]{result['rarity']} {result['type']}[/dim]) to [bold]{result['recipient']}[/bold]\n\n"
            f"[dim]Artifact ID: {result['artifact_id']}[/dim]\n"
            f"[dim]New owner: {result['recipient']}[/dim]",
            title="Gift Sent",
            border_style="green",
        )
    )
    console.print()
    return True


def _handle_trade(args: List[str]) -> bool:
    result = trade_artifact(args)
    if not result["success"]:
        error(result["error"])
        return True

    yours = result["your_artifact"]
    theirs = result["their_artifact"]
    your_color = RARITY_COLORS.get(yours["rarity"], "white")
    their_color = RARITY_COLORS.get(theirs["rarity"], "white")

    console.print()
    console.print(
        Panel(
            f"[bold]{result['sender']}[/bold] traded [{your_color}]{yours['name']}[/{your_color}] "
            f"([dim]{yours['rarity']}[/dim])\n"
            f"  for\n"
            f"[bold]{result['partner']}[/bold]'s [{their_color}]{theirs['name']}[/{their_color}] "
            f"([dim]{theirs['rarity']}[/dim])\n\n"
            f"[dim]Both artifacts have swapped owners.[/dim]",
            title="Trade Complete",
            border_style="cyan",
        )
    )
    console.print()
    return True


def _handle_drop(args: List[str]) -> bool:
    result = drop_item(args)
    if not result["success"]:
        error(result["error"])
        return True

    console.print()
    console.print(
        Panel(
            f"[bold]{result['name']}[/bold] dropped in [cyan]r/{result['room']}[/cyan]\n\n"
            f"[dim]Description:[/dim] {result['description']}\n"
            f"[dim]Artifact ID:[/dim] {result['artifact_id']}\n"
            f"[dim]Expires in:[/dim] {result['expires_minutes']} minute(s)\n"
            f"[dim]Expires at:[/dim] {result['expires_at']}\n\n"
            f"[yellow]Anyone can pick it up with:[/yellow] commons find {result['artifact_id']}",
            title="Item Dropped",
            border_style="yellow",
        )
    )
    console.print()
    return True


def _handle_find(args: List[str]) -> bool:
    result = find_item(args)
    if not result["success"]:
        error(result["error"])
        return True

    rarity_color = RARITY_COLORS.get(result["rarity"], "white")
    console.print()
    console.print(
        Panel(
            f"[bold]{result['finder']}[/bold] found [{rarity_color}]{result['name']}[/{rarity_color}]!\n\n"
            f"[dim]Description:[/dim] {result['description']}\n"
            f"[dim]Found in:[/dim] r/{result['room_found']}\n"
            f"[dim]Artifact ID:[/dim] {result['artifact_id']}\n"
            f"[dim]Originally dropped by:[/dim] {result['creator']}\n\n"
            f"[green]This item is now yours permanently![/green]",
            title="Item Found!",
            border_style="yellow",
        )
    )
    if result.get("sweep_failed"):
        warning("The sweep of expired items failed (see the commons log); expired drops may still be listed.")
    console.print()
    return True


def _handle_mint(args: List[str]) -> bool:
    result = mint_event_artifact(args)
    if not result["success"]:
        error(result["error"])
        return True

    for warn_msg in result.get("warnings", []):
        warning(f"Warning: {warn_msg}")

    minted = result["minted"]
    lines = [f"[bold]Event:[/bold] {result['event_name']}\n"]
    lines.append(f"[dim]Minted {len(minted)} badge(s):[/dim]\n")
    for item in minted:
        lines.append(f"  [blue]*[/blue] {item['branch']} -> Artifact #{item['artifact_id']}")

    console.print()
    console.print(Panel("\n".join(lines), title="Event Badges Minted", border_style="blue"))
    console.print()
    return True
