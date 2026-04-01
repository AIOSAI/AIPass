# =================== AIPass ====================
# Name: artifact.py
# Description: Artifact Orchestration Module
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-03-07
# =============================================

"""
Artifact Orchestration Module

Router + display layer for artifact workflows. Delegates all logic
to handlers/artifacts/artifact_ops.py and renders results with Rich.

Handles: craft, artifacts, inspect, collab, sign commands.
"""

from typing import List

from aipass.prax.apps.modules.logger import system_logger as logger

try:
    from aipass.cli.apps.modules import console
except ImportError:
    logger.warning("[artifact] CLI console unavailable, using fallback")
    from rich.console import Console
    console = Console()

from rich.panel import Panel
from rich.table import Table

from commons.apps.handlers.artifacts.artifact_ops import (
    craft_artifact, list_artifacts, inspect_artifact, collab_artifact, sign_artifact,
    RARITY_COLORS,
)
from commons.apps.handlers.json import json_handler


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("artifact")
    console.print("Router and display layer for artifact workflows — crafting, listing, inspecting, collaborating, and signing.")
    console.print()
    console.print("Connected Handlers:")
    console.print("  handlers/artifacts/")
    console.print("    - artifact_ops.py (craft_artifact — create a new artifact)")
    console.print("    - artifact_ops.py (list_artifacts — list artifacts in collection or system)")
    console.print("    - artifact_ops.py (inspect_artifact — show artifact details and provenance)")
    console.print("    - artifact_ops.py (collab_artifact — initiate a joint artifact requiring multiple signers)")
    console.print("    - artifact_ops.py (sign_artifact — add signature to a pending joint artifact)")
    console.print("    - artifact_ops.py (RARITY_COLORS — color mapping for artifact rarity tiers)")
    console.print()


# =============================================================================
# COMMAND ROUTING
# =============================================================================

def handle_command(command: str, args: List[str]) -> bool:
    """Handle artifact-related commands."""
    if command not in ["craft", "artifacts", "inspect", "collab", "sign"]:
        return False

    if command == "craft":
        result = _handle_craft(args)
    elif command == "artifacts":
        result = _handle_list(args)
    elif command == "inspect":
        result = _handle_inspect(args)
    elif command == "collab":
        result = _handle_collab(args)
    elif command == "sign":
        result = _handle_sign(args)
    else:
        return False

    if result:
        json_handler.log_operation(f"{command}_executed", {"command": command, "success": True})
    return result


# =============================================================================
# DISPLAY HANDLERS
# =============================================================================

def _handle_craft(args: List[str]) -> bool:
    result = craft_artifact(args)
    if not result["success"]:
        console.print(f"[red]{result['error']}[/red]")
        return True

    rarity_color = RARITY_COLORS.get(result["rarity"], "white")
    console.print()
    console.print("[green]Artifact crafted![/green]")
    console.print(f"  [dim]ID:[/dim] {result['artifact_id']}")
    console.print(f"  [dim]Name:[/dim] {result['name']}")
    console.print(f"  [dim]Type:[/dim] {result['type']}")
    console.print(f"  [dim]Rarity:[/dim] [{rarity_color}]{result['rarity']}[/{rarity_color}]")
    console.print(f"  [dim]Creator:[/dim] {result['creator']}")
    console.print(f"  [dim]Description:[/dim] {result['description']}")
    console.print()
    return True


def _handle_list(args: List[str]) -> bool:
    result = list_artifacts(args)
    if not result["success"]:
        console.print(f"[red]{result['error']}[/red]")
        return True

    artifacts = result["artifacts"]
    if not artifacts:
        scope = "in the system" if result["show_all"] else "in your collection"
        console.print(f"\n[dim]No artifacts found {scope}.[/dim]\n")
        return True

    table = Table(title=result["scope_label"], border_style="cyan")
    table.add_column("ID", style="dim", width=5)
    table.add_column("Name", style="bold")
    table.add_column("Type", style="dim")
    table.add_column("Rarity", width=10)
    table.add_column("Creator", style="dim")
    table.add_column("Owner", style="dim")
    table.add_column("Created", style="dim", width=12)

    for a in artifacts:
        rarity_color = RARITY_COLORS.get(a["rarity"], "white")
        created_short = a["created_at"][:10] if a["created_at"] else ""
        table.add_row(
            str(a["id"]), a["name"], a["type"],
            f"[{rarity_color}]{a['rarity']}[/{rarity_color}]",
            a["creator"], a["owner"], created_short,
        )

    console.print()
    console.print(table)
    console.print(f"\n[dim]Total: {len(artifacts)} artifact(s)[/dim]\n")
    return True


def _handle_inspect(args: List[str]) -> bool:
    result = inspect_artifact(args)
    if not result["success"]:
        console.print(f"[red]{result['error']}[/red]")
        return True

    artifact = result["artifact"]
    history = result["history"]
    show_full = result["show_full"]
    metadata = artifact.get("_parsed_metadata", {})

    rarity_color = RARITY_COLORS.get(artifact["rarity"], "white")

    details = []
    details.append(f"[bold]Name:[/bold]        {artifact['name']}")
    details.append(f"[bold]Type:[/bold]        {artifact['type']}")
    details.append(f"[bold]Rarity:[/bold]      [{rarity_color}]{artifact['rarity']}[/{rarity_color}]")
    details.append(f"[bold]Creator:[/bold]     {artifact['creator']}")
    details.append(f"[bold]Owner:[/bold]       {artifact['owner']}")
    details.append(f"[bold]Description:[/bold] {artifact['description']}")
    details.append(f"[bold]Created:[/bold]     {artifact['created_at']}")

    if artifact.get("expires_at"):
        details.append(f"[bold]Expires:[/bold]     {artifact['expires_at']}")
    if artifact.get("room_found"):
        details.append(f"[bold]Found in:[/bold]   r/{artifact['room_found']}")
    if metadata:
        details.append("[bold]Metadata:[/bold]")
        for key, value in metadata.items():
            details.append(f"  {key}: {value}")

    console.print()
    console.print(Panel("\n".join(details), title=f"Artifact #{artifact['id']}", border_style=rarity_color))

    if history:
        total_entries = len(history)
        max_display = 10

        if show_full or total_entries <= max_display:
            display_entries = history
            header_text = f"Provenance Chain ({total_entries} entries)"
        else:
            display_entries = history[-max_display:]
            header_text = f"Provenance Chain (showing last {max_display} of {total_entries} entries)"

        console.print(f"\n[bold]{header_text}:[/bold]\n")

        for entry in display_entries:
            action = entry["action"]
            from_agent = entry["from_agent"] or "?"
            to_agent = entry["to_agent"] or "?"
            timestamp = entry["created_at"] or ""

            if action == "created":
                console.print(f"  [green]+[/green] {timestamp[:19]} | Created by {from_agent}")
            elif action in ("traded", "gifted"):
                console.print(f"  [cyan]>[/cyan] {timestamp[:19]} | {action.title()}: {from_agent} -> {to_agent}")
            elif action == "found":
                console.print(f"  [yellow]*[/yellow] {timestamp[:19]} | Found by {to_agent}")
            elif action == "expired":
                console.print(f"  [red]x[/red] {timestamp[:19]} | Expired: {entry.get('details', '')}")
            else:
                console.print(f"  [dim]-[/dim] {timestamp[:19]} | {action.title()}: {entry.get('details', '')}")

        if not show_full and total_entries > max_display:
            console.print(f"\n  [dim]Full provenance: {total_entries} entries (use --full to see all)[/dim]")
    else:
        console.print("\n[dim]  No provenance history recorded.[/dim]")

    console.print()
    return True


def _handle_collab(args: List[str]) -> bool:
    result = collab_artifact(args)
    if not result["success"]:
        console.print(f"[red]{result['error']}[/red]")
        return True

    for warning in result.get("warnings", []):
        console.print(f"[yellow]Warning: {warning}[/yellow]")

    rarity_color = RARITY_COLORS.get(result["rarity"], "white")
    console.print()
    console.print("[green]Joint artifact initiated![/green]")
    console.print(f"  [dim]Pending ID:[/dim] {result['pending_id']}")
    console.print(f"  [dim]Name:[/dim] {result['name']}")
    console.print(f"  [dim]Rarity:[/dim] [{rarity_color}]{result['rarity']}[/{rarity_color}]")
    console.print(f"  [dim]Initiator:[/dim] {result['initiator']}")
    console.print(f"  [dim]Required signers:[/dim] {', '.join(result['signers'])}")
    console.print(f"  [dim]Expires:[/dim] {result['expires_at']}")
    console.print()
    console.print(f"[dim]Signers can complete with: commons sign {result['pending_id']}[/dim]")
    console.print()
    return True


def _handle_sign(args: List[str]) -> bool:
    result = sign_artifact(args)
    if not result["success"]:
        console.print(f"[red]{result['error']}[/red]")
        return True

    if result["completed"]:
        rarity_color = RARITY_COLORS.get(result["rarity"], "white")
        console.print()
        console.print("[bold green]Joint artifact completed![/bold green]")
        console.print(f"  [dim]Artifact ID:[/dim] {result['artifact_id']}")
        console.print(f"  [dim]Name:[/dim] [{rarity_color}]{result['name']}[/{rarity_color}]")
        console.print(f"  [dim]Rarity:[/dim] [{rarity_color}]{result['rarity']}[/{rarity_color}]")
        console.print(f"  [dim]Created by:[/dim] {', '.join(result['participants'])}")
        console.print(f"  [dim]Owner:[/dim] {result['owner']}")
        console.print()
    else:
        console.print()
        console.print(f"[green]Signed! {result['signer']} added signature to joint artifact {result['pending_id']}[/green]")
        console.print(f"  [dim]Signed:[/dim] {', '.join(result['signed'])}")
        console.print(f"  [dim]Still needed:[/dim] {', '.join(result['remaining'])}")
        console.print()

    return True
