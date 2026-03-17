# =================== AIPass ====================
# Name: space_module.py
# Description: Spatial Navigation Module
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-03-07
# =============================================

"""
Spatial Navigation Module

Router + renderer for spatial room commands.
Delegates data retrieval to handlers/rooms/space_ops.py.

Handles: enter, look, decorate, visitors commands.
"""

from typing import List

from aipass.prax.apps.modules.logger import system_logger as logger

try:
    from aipass.cli.apps.modules import console, error
except ImportError:
    from rich.console import Console
    console = Console()

    def error(message: str, suggestion: str | None = None) -> None:  # type: ignore[misc]
        console.print(f"[red]{message}[/red]")
        if suggestion:
            console.print(f"  [yellow]{suggestion}[/yellow]")

from rich.panel import Panel

from commons.apps.handlers.rooms.space_ops import (
    get_room_enter_data,
    get_room_look_data,
    place_decoration,
    get_visitors_data,
)
from commons.apps.modules.commons_identity import get_caller_branch
from commons.apps.handlers.json import json_handler


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("space_module Module")
    console.print("Spatial navigation — entering rooms, looking around, decorating, and visitor tracking")
    console.print()
    console.print("Connected Handlers:")
    console.print("  handlers/rooms/")
    console.print("    - space_ops.py (get_room_enter_data — retrieve room data for entering)")
    console.print("    - space_ops.py (get_room_look_data — retrieve room data for looking around)")
    console.print("    - space_ops.py (place_decoration — place a decoration in a room)")
    console.print("    - space_ops.py (get_visitors_data — get recent visitors for a room)")
    console.print()
    console.print("Connected Modules:")
    console.print("  modules/")
    console.print("    - commons_identity.py (get_caller_branch — detect calling branch for decorate)")
    console.print()


# =============================================================================
# MOOD DISPLAY HELPERS
# =============================================================================

MOOD_STYLES = {
    "welcoming": ("green", "~"),
    "relaxed": ("blue", "~"),
    "focused": ("yellow", "|"),
    "neutral": ("dim", "-"),
    "tense": ("red", "!"),
    "celebratory": ("magenta", "*"),
}


def _mood_style(mood: str) -> str:
    """Return Rich color for a mood string."""
    return MOOD_STYLES.get(mood, ("dim", "-"))[0]


def _mood_icon(mood: str) -> str:
    """Return a text icon for a mood string."""
    return MOOD_STYLES.get(mood, ("dim", "-"))[1]


# =============================================================================
# COMMAND ROUTING
# =============================================================================

def handle_command(command: str, args: List[str]) -> bool:
    """
    Handle spatial navigation commands.

    Args:
        command: Command name (enter, look, decorate, visitors)
        args: Command arguments

    Returns:
        True if command handled, False otherwise
    """
    if command not in ["enter", "look", "decorate", "visitors"]:
        return False

    # Action commands that work without args — route before introspection gate
    if command in ("look", "visitors"):
        if command == "look":
            result = _cmd_look(args)
        else:
            result = _cmd_visitors(args)
        if result:
            json_handler.log_operation(f"{command}_executed", {"command": command, "success": True})
        return result

    if not args:
        print_introspection()
        return True

    if command == "enter":
        result = _cmd_enter(args)
    elif command == "decorate":
        result = _cmd_decorate(args)
    else:
        return False

    if result:
        json_handler.log_operation(f"{command}_executed", {"command": command, "success": True})
    return result


# =============================================================================
# ENTER
# =============================================================================

def _cmd_enter(args: List[str]) -> bool:
    """Enter a room -- render entrance panel with mood, flavor, decorations."""
    if not args:
        console.print("[red]Usage: commons enter <room>[/red]")
        return True

    room_name = args[0].lower()
    data = get_room_enter_data(room_name)

    if data.get("error"):
        console.print(f"[red]{data['error']}[/red]")
        return True

    if not data["found"]:
        console.print(f"[red]Room '{room_name}' not found[/red]")
        return True

    room = data["room"]
    mood = room.get("mood") or "neutral"
    entrance_msg = room.get("entrance_message") or f"You enter {room_name}."
    flavor = room.get("flavor_text") or ""
    style = _mood_style(mood)
    icon = _mood_icon(mood)

    body_parts = []
    body_parts.append(f"[italic]{entrance_msg}[/italic]")
    body_parts.append("")

    if flavor:
        body_parts.append(f"[dim]{flavor}[/dim]")
        body_parts.append("")

    body_parts.append(f"[{style}]Mood: {mood} {icon}[/{style}]")
    body_parts.append(
        f"[dim]Posts: {data['post_count']} total | {data['recent_count']} in last 48h[/dim]"
    )

    decorations = data.get("decorations", {})
    if decorations:
        body_parts.append("")
        body_parts.append("[bold]Decorations:[/bold]")
        for key, desc in decorations.items():
            item_name = key.replace("decor_", "").replace("_", " ").title()
            body_parts.append(f"  [cyan]{item_name}[/cyan] - {desc}")

    console.print()
    console.print(Panel(
        "\n".join(body_parts),
        title=f"[bold]r/{room_name}[/bold] - {room.get('display_name', room_name)}",
        subtitle=f"[dim]{room.get('description', '')}[/dim]",
        border_style=style,
        padding=(1, 2),
    ))
    console.print()

    return True


# =============================================================================
# LOOK
# =============================================================================

def _cmd_look(args: List[str]) -> bool:
    """Look around -- show description, mood, decorations, recent posts."""
    room_name = args[0].lower() if args else "general"
    data = get_room_look_data(room_name)

    if data.get("error"):
        console.print(f"[red]{data['error']}[/red]")
        return True

    if not data["found"]:
        console.print(f"[red]Room '{room_name}' not found[/red]")
        return True

    room = data["room"]
    mood = room.get("mood") or "neutral"
    flavor = room.get("flavor_text") or ""
    style = _mood_style(mood)
    icon = _mood_icon(mood)

    console.print()
    console.print(f"[bold cyan]r/{room_name}[/bold cyan] - {room.get('display_name', room_name)}")
    console.print(f"  [dim]{room.get('description', '')}[/dim]")
    console.print()

    if flavor:
        console.print(f"  [italic]{flavor}[/italic]")
        console.print()

    console.print(f"  [{style}]Mood: {mood} {icon}[/{style}]")
    console.print()

    decorations = data.get("decorations", {})
    if decorations:
        console.print("  [bold]Decorations:[/bold]")
        for key, desc in decorations.items():
            item_name = key.replace("decor_", "").replace("_", " ").title()
            console.print(f"    [cyan]{item_name}[/cyan] - {desc}")
        console.print()

    recent_posts = data.get("recent_posts", [])
    if recent_posts:
        console.print("  [bold]Recent posts:[/bold]")
        for p in recent_posts:
            console.print(
                f"    [dim]#{p['id']}[/dim] {p['title']} "
                f"[dim]by {p['author']} | {p['created_at']}[/dim]"
            )
    else:
        console.print("  [dim]No posts yet. Be the first![/dim]")

    console.print()
    return True


# =============================================================================
# DECORATE
# =============================================================================

def _cmd_decorate(args: List[str]) -> bool:
    """Place a decoration in a room."""
    if len(args) < 3:
        error('Usage: commons decorate <room> "item_name" "description"')
        return True

    room_name = args[0].lower()
    item_name = args[1].lower().replace(" ", "_")
    description = args[2]

    caller = get_caller_branch()
    if not caller:
        error("Could not detect calling branch. Run from a branch directory.")
        return True

    branch_name = caller["name"]
    result = place_decoration(room_name, item_name, description, branch_name)

    if result.get("error"):
        error(result['error'])
        return True

    if result["success"]:
        console.print()
        console.print(f"[green]Placed '{result['display_name']}' in r/{room_name}[/green]")
        console.print(f"  [dim]{description}[/dim]")
        console.print()
    else:
        console.print("[red]Failed to place decoration[/red]")

    return True


# =============================================================================
# VISITORS
# =============================================================================

def _cmd_visitors(args: List[str]) -> bool:
    """Show recent visitors in a room (last 48h)."""
    if not args:
        console.print("[red]Usage: commons visitors <room>[/red]")
        return True

    room_name = args[0].lower()
    data = get_visitors_data(room_name)

    if data.get("error"):
        console.print(f"[red]{data['error']}[/red]")
        return True

    if not data["found"]:
        console.print(f"[red]Room '{room_name}' not found[/red]")
        return True

    visitors = data["visitors"]

    console.print()
    console.print(f"[bold cyan]r/{room_name}[/bold cyan] - Recent Visitors (48h)")
    console.print()

    if visitors:
        for name in visitors:
            console.print(f"  [green]{name}[/green]")
        console.print()
        console.print(f"  [dim]{len(visitors)} visitor(s) in the last 48 hours[/dim]")
    else:
        console.print("  [dim]No visitors in the last 48 hours.[/dim]")

    console.print()
    return True
