# =================== AIPass ====================
# Name: catchup_module.py
# Description: Catchup Orchestration Module
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-03-07
# =============================================

"""
Catchup Orchestration Module

Thin router for the catchup command. Delegates query logic
to handlers/catchup/catchup_ops.py and renders results with Rich.

Handles: catchup command.
"""

from typing import List

from aipass.prax.apps.modules.logger import system_logger as logger

try:
    from aipass.cli.apps.modules import console
except ImportError:
    from rich.console import Console
    console = Console()

from commons.apps.handlers.catchup.catchup_ops import run_catchup
from commons.apps.handlers.json import json_handler


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("catchup_module Module")
    console.print("Catchup orchestration — shows what happened since your last visit")
    console.print()
    console.print("Connected Handlers:")
    console.print("  handlers/catchup/")
    console.print("    - catchup_ops.py (run_catchup — gather and return catchup data)")
    console.print()


# =============================================================================
# COMMAND ROUTING
# =============================================================================

def handle_command(command: str, args: List[str]) -> bool:
    """
    Handle catchup-related commands.

    Args:
        command: Command name (catchup)
        args: Command arguments

    Returns:
        True if command handled, False otherwise
    """
    if command != "catchup":
        return False

    return _handle_catchup(args)


# =============================================================================
# DISPLAY HANDLER
# =============================================================================

def _handle_catchup(args: List[str]) -> bool:
    """Run catchup and display results."""
    result = run_catchup(args)

    if not result["success"]:
        console.print(f"[red]{result['error']}[/red]")
        return True

    is_first_visit = result["is_first_visit"]
    time_label = result["time_label"]
    data = result["data"]

    console.print()
    if is_first_visit:
        console.print(
            "[bold cyan]Welcome to The Commons![/bold cyan] "
            "[dim]Here's what's happening:[/dim]"
        )
    else:
        console.print(
            f"[bold cyan]Since your last visit[/bold cyan] "
            f"[dim]({time_label}):[/dim]"
        )
    console.print()

    # Mentions
    unread_mentions = data["unread_mentions"]
    if unread_mentions:
        for mention in unread_mentions:
            mentioner = mention.get("mentioner_agent", "someone")
            post_title = mention.get("post_title", "a post")
            room = mention.get("room_name", "unknown")
            console.print(
                f"  [yellow]@MENTIONS:[/yellow] {mentioner} mentioned you "
                f'in "{post_title}" ({room})'
            )
    else:
        console.print("  [yellow]@MENTIONS:[/yellow] [dim]None[/dim]")

    # Replies
    replies = data["replies"]
    if replies:
        reply_posts: dict = {}
        for r in replies:
            pid = r.get("post_id")
            if pid not in reply_posts:
                reply_posts[pid] = {
                    "title": r.get("post_title", "Unknown"),
                    "count": 0,
                }
            reply_posts[pid]["count"] += 1

        for _pid, info in reply_posts.items():
            console.print(
                f"  [green]REPLIES:[/green] {info['count']} new comment(s) "
                f'on your post "{info["title"]}"'
            )
    else:
        console.print("  [green]REPLIES:[/green] [dim]None[/dim]")

    # Trending
    trending = data["trending"]
    if trending and trending["vote_score"] > 0:
        console.print(
            f"  [bold cyan]TRENDING:[/bold cyan] "
            f'"{trending["title"]}" has {trending["vote_score"]} votes '
            f'in {trending["room_name"]}'
        )
    else:
        console.print("  [bold cyan]TRENDING:[/bold cyan] [dim]Nothing trending right now[/dim]")

    # New activity
    console.print(
        f"  [blue]NEW:[/blue] {data['new_posts_count']} new post(s), "
        f"{data['new_comments_count']} new comment(s)"
    )

    # Karma
    karma_change = data["karma_change"]
    if karma_change > 0:
        console.print(f"  [green]KARMA:[/green] +{karma_change} since last session")
    elif karma_change < 0:
        console.print(f"  [red]KARMA:[/red] {karma_change} since last session")
    else:
        console.print("  [dim]KARMA:[/dim] [dim]No change[/dim]")

    console.print()

    # Onboarding nudge
    nudge = result.get("nudge")
    if nudge:
        console.print(f"  [yellow]TIP:[/yellow] {nudge}")
        console.print()

    json_handler.log_operation("catchup_executed", {"command": "catchup", "success": True})
    return True
