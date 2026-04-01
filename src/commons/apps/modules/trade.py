# =================== AIPass ====================
# Name: trade.py
# Description: Trade Orchestration Module
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-03-07
# =============================================

"""
Trade Orchestration Module

Router + display layer for trading workflows. Delegates all logic
to handlers/artifacts/trade_ops.py and renders results with Rich.

Handles: gift, trade, drop, find, mint commands.
"""

from typing import List

from aipass.prax.apps.modules.logger import system_logger as logger

try:
    from aipass.cli.apps.modules import console
except ImportError:
    logger.warning("[trade] CLI console unavailable, using fallback")
    from rich.console import Console
    console = Console()

from rich.panel import Panel

from commons.apps.handlers.artifacts.trade_ops import (
    gift_artifact, trade_artifact, drop_item, find_item, mint_event_artifact,
    RARITY_COLORS,
)
from commons.apps.handlers.json import json_handler


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("trade")
    console.print("Router and display layer for trading workflows — gifting, trading, dropping, finding, and minting artifacts.")
    console.print()
    console.print("Connected Handlers:")
    console.print("  handlers/artifacts/")
    console.print("    - trade_ops.py (gift_artifact — gift an artifact to another branch)")
    console.print("    - trade_ops.py (trade_artifact — swap artifacts between two branches)")
    console.print("    - trade_ops.py (drop_item — drop an artifact in a room for others to find)")
    console.print("    - trade_ops.py (find_item — pick up a dropped artifact)")
    console.print("    - trade_ops.py (mint_event_artifact — mint event badge artifacts for participants)")
    console.print("    - trade_ops.py (RARITY_COLORS — color mapping for artifact rarity tiers)")
    console.print()


# =============================================================================
# COMMAND ROUTING
# =============================================================================

TRADE_COMMANDS = ["gift", "trade", "drop", "find", "mint"]


def handle_command(command: str, args: List[str]) -> bool:
    """Handle trade-related commands."""
    if command not in TRADE_COMMANDS:
        return False

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
        console.print(f"[red]{result['error']}[/red]")
        return True

    rarity_color = RARITY_COLORS.get(result["rarity"], "white")
    console.print()
    console.print(Panel(
        f"[bold]{result['sender']}[/bold] gifted [{rarity_color}]{result['name']}[/{rarity_color}] "
        f"([dim]{result['rarity']} {result['type']}[/dim]) to [bold]{result['recipient']}[/bold]\n\n"
        f"[dim]Artifact ID: {result['artifact_id']}[/dim]\n"
        f"[dim]New owner: {result['recipient']}[/dim]",
        title="Gift Sent",
        border_style="green",
    ))
    console.print()
    return True


def _handle_trade(args: List[str]) -> bool:
    result = trade_artifact(args)
    if not result["success"]:
        console.print(f"[red]{result['error']}[/red]")
        return True

    yours = result["your_artifact"]
    theirs = result["their_artifact"]
    your_color = RARITY_COLORS.get(yours["rarity"], "white")
    their_color = RARITY_COLORS.get(theirs["rarity"], "white")

    console.print()
    console.print(Panel(
        f"[bold]{result['sender']}[/bold] traded [{your_color}]{yours['name']}[/{your_color}] "
        f"([dim]{yours['rarity']}[/dim])\n"
        f"  for\n"
        f"[bold]{result['partner']}[/bold]'s [{their_color}]{theirs['name']}[/{their_color}] "
        f"([dim]{theirs['rarity']}[/dim])\n\n"
        f"[dim]Both artifacts have swapped owners.[/dim]",
        title="Trade Complete",
        border_style="cyan",
    ))
    console.print()
    return True


def _handle_drop(args: List[str]) -> bool:
    result = drop_item(args)
    if not result["success"]:
        console.print(f"[red]{result['error']}[/red]")
        return True

    console.print()
    console.print(Panel(
        f"[bold]{result['name']}[/bold] dropped in [cyan]r/{result['room']}[/cyan]\n\n"
        f"[dim]Description:[/dim] {result['description']}\n"
        f"[dim]Artifact ID:[/dim] {result['artifact_id']}\n"
        f"[dim]Expires in:[/dim] {result['expires_minutes']} minute(s)\n"
        f"[dim]Expires at:[/dim] {result['expires_at']}\n\n"
        f"[yellow]Anyone can pick it up with:[/yellow] commons find {result['artifact_id']}",
        title="Item Dropped",
        border_style="yellow",
    ))
    console.print()
    return True


def _handle_find(args: List[str]) -> bool:
    result = find_item(args)
    if not result["success"]:
        console.print(f"[red]{result['error']}[/red]")
        return True

    rarity_color = RARITY_COLORS.get(result["rarity"], "white")
    console.print()
    console.print(Panel(
        f"[bold]{result['finder']}[/bold] found [{rarity_color}]{result['name']}[/{rarity_color}]!\n\n"
        f"[dim]Description:[/dim] {result['description']}\n"
        f"[dim]Found in:[/dim] r/{result['room_found']}\n"
        f"[dim]Artifact ID:[/dim] {result['artifact_id']}\n"
        f"[dim]Originally dropped by:[/dim] {result['creator']}\n\n"
        f"[green]This item is now yours permanently![/green]",
        title="Item Found!",
        border_style="yellow",
    ))
    console.print()
    return True


def _handle_mint(args: List[str]) -> bool:
    result = mint_event_artifact(args)
    if not result["success"]:
        console.print(f"[red]{result['error']}[/red]")
        return True

    for warning in result.get("warnings", []):
        console.print(f"[yellow]Warning: {warning}[/yellow]")

    minted = result["minted"]
    lines = [f"[bold]Event:[/bold] {result['event_name']}\n"]
    lines.append(f"[dim]Minted {len(minted)} badge(s):[/dim]\n")
    for item in minted:
        lines.append(f"  [blue]*[/blue] {item['branch']} -> Artifact #{item['artifact_id']}")

    console.print()
    console.print(Panel("\n".join(lines), title="Event Badges Minted", border_style="blue"))
    console.print()
    return True
