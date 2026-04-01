# =================== AIPass ====================
# Name: capsule.py
# Description: Time Capsule Orchestration Module
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-03-07
# =============================================

"""
Time Capsule Orchestration Module

Router + display layer for time capsule workflows. Delegates all logic
to handlers/artifacts/capsule_ops.py and renders results with Rich.

Handles: capsule, capsules, open commands.
"""

from typing import List

from aipass.prax.apps.modules.logger import system_logger as logger

try:
    from aipass.cli.apps.modules import console
except ImportError:
    logger.warning("[capsule] CLI console unavailable, using fallback")
    from rich.console import Console
    console = Console()

from rich.panel import Panel
from rich.table import Table

from commons.apps.handlers.artifacts.capsule_ops import (
    seal_capsule, list_capsules, open_capsule,
)
from commons.apps.handlers.json import json_handler


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("capsule")
    console.print("Time capsule orchestration — sealing, listing, and opening time capsules")
    console.print()
    console.print("Connected Handlers:")
    console.print("  handlers/artifacts/")
    console.print("    - capsule_ops.py (seal_capsule — seal a new time capsule)")
    console.print("    - capsule_ops.py (list_capsules — list all time capsules)")
    console.print("    - capsule_ops.py (open_capsule — open a ready time capsule)")
    console.print()


# =============================================================================
# COMMAND ROUTING
# =============================================================================

def handle_command(command: str, args: List[str]) -> bool:
    """Handle time capsule commands."""
    if command not in ["capsule", "capsules", "open"]:
        return False

    if command == "capsule":
        result = _handle_seal(args)
    elif command == "capsules":
        result = _handle_list(args)
    elif command == "open":
        result = _handle_open(args)
    else:
        return False

    if result:
        json_handler.log_operation(f"{command}_executed", {"command": command, "success": True})
    return result


# =============================================================================
# DISPLAY HANDLERS
# =============================================================================

def _handle_seal(args: List[str]) -> bool:
    result = seal_capsule(args)
    if not result["success"]:
        console.print(f"[red]{result['error']}[/red]")
        return True

    console.print()
    console.print(Panel(
        f"[bold]Time capsule sealed![/bold]\n\n"
        f"[dim]ID:[/dim] {result['capsule_id']}\n"
        f"[dim]Title:[/dim] {result['title']}\n"
        f"[dim]Sealed by:[/dim] {result['creator']}\n"
        f"[dim]Opens in:[/dim] {result['days']} day(s)\n"
        f"[dim]Opens at:[/dim] {result['opens_at']}\n"
        f"[dim]Room:[/dim] r/time-capsule-vault\n\n"
        f"[italic]The contents are sealed until the appointed time.[/italic]",
        title="Time Capsule Sealed",
        border_style="magenta",
    ))
    console.print()
    return True


def _handle_list(args: List[str]) -> bool:
    result = list_capsules(args)
    if not result["success"]:
        console.print(f"[red]{result['error']}[/red]")
        return True

    capsules = result["capsules"]
    if not capsules:
        console.print("\n[dim]No time capsules exist yet. Seal one with: commons capsule[/dim]\n")
        return True

    table = Table(title="Time Capsules", border_style="magenta")
    table.add_column("ID", style="dim", width=5)
    table.add_column("Title", style="bold")
    table.add_column("Creator", style="dim")
    table.add_column("Status")
    table.add_column("Opens At", style="dim")

    for capsule in capsules:
        status = capsule["_status"]
        status_text = capsule["_status_text"]

        if status == "opened":
            styled_status = f"[green]{status_text}[/green]"
        elif status == "ready":
            styled_status = f"[yellow]{status_text}[/yellow]"
        else:
            styled_status = f"[dim]{status_text}[/dim]"

        table.add_row(
            str(capsule["id"]),
            capsule["title"],
            capsule["creator"],
            styled_status,
            capsule["opens_at"][:10],
        )

    console.print()
    console.print(table)
    console.print(f"\n[dim]Total: {len(capsules)} capsule(s)[/dim]\n")
    return True


def _handle_open(args: List[str]) -> bool:
    result = open_capsule(args)
    if not result["success"]:
        console.print(f"[red]{result['error']}[/red]")
        return True

    capsule = result["capsule"]

    if result.get("already_opened"):
        console.print()
        console.print(Panel(
            f"[bold]{capsule['title']}[/bold]\n\n"
            f"{capsule['content']}\n\n"
            f"[dim]Sealed by {capsule['creator']} | "
            f"Opened by {capsule['opened_by']}[/dim]",
            title=f"Time Capsule #{capsule['id']} (Already Opened)",
            border_style="green",
        ))
        console.print()
    else:
        console.print()
        console.print(Panel(
            f"[bold]{capsule['title']}[/bold]\n\n"
            f"{capsule['content']}\n\n"
            f"[dim]Sealed by {capsule['creator']} on {capsule.get('sealed_at', '')[:10]}[/dim]\n"
            f"[dim]Opened by {result['opener']}[/dim]",
            title=f"Time Capsule #{capsule['id']} - Opened!",
            border_style="green",
        ))
        console.print()

    return True
