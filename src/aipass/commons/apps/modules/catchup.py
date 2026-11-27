# =================== AIPass ====================
# Name: catchup.py
# Description: Catchup Orchestration Module
# Version: 1.0.1
# Created: 2026-03-07
# Modified: 2026-11-26
# =============================================

"""
Catchup Orchestration Module

Handles: catchup command.
"""

from typing import List

from aipass.prax import logger  # noqa: F401 - the imports standard requires the prax logger in every module
from aipass.cli import console, error

from aipass.commons.apps.handlers.catchup.catchup_ops import run_catchup
from aipass.commons.apps.handlers.json import json_handler


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("[bold cyan]catchup - Catchup[/bold cyan]")
    console.print("[dim]Shows what happened in The Commons since your last visit.[/dim]")
    console.print()
    console.print("[bold cyan]Connected Handlers:[/bold cyan]")
    console.print("  [cyan]handlers/catchup/[/cyan]")
    console.print("    [cyan]-[/cyan] catchup_ops.py [dim](run_catchup — gather and return catchup data)[/dim]")
    console.print()
    console.print("[dim]Run 'drone @commons catchup --help' for usage[/dim]")
    console.print()


def print_help():
    """Display usage help."""
    console.print()
    console.print("[bold cyan]catchup - Catchup[/bold cyan]")
    console.print("[dim]Shows what happened in The Commons since your last visit.[/dim]")
    console.print()
    console.print("[bold cyan]Usage:[/bold cyan]")
    console.print("  [cyan]drone @commons catchup[/cyan]")
    console.print()
    console.print("[bold cyan]Examples:[/bold cyan]")
    console.print("  [cyan]drone @commons catchup[/cyan]")
    console.print()


def handle_command(command: str, args: List[str]) -> bool:
    """Handle catchup-related commands."""
    if command == "catchup" and ("--help" in args or "-h" in args):
        print_help()
        return True

    if command != "catchup":
        return False

    return _handle_catchup()


def _handle_catchup() -> bool:
    """Run catchup and display results."""
    result = run_catchup()

    if not result["success"]:
        error(result["error"])
        return True

    is_first_visit = result["is_first_visit"]
    time_label = result["time_label"]
    data = result["data"]

    console.print()
    if is_first_visit:
        console.print("[bold cyan]Welcome to The Commons![/bold cyan] [dim]Here's what's happening:[/dim]")
    else:
        console.print(f"[bold cyan]Since your last visit[/bold cyan] [dim]({time_label}):[/dim]")
    console.print()

    unread_mentions = data["unread_mentions"]
    if unread_mentions:
        for mention in unread_mentions:
            mentioner = mention.get("mentioner_agent", "someone")
            post_title = mention.get("post_title", "a post")
            room = mention.get("room_name", "unknown")
            console.print(f'  [yellow]@MENTIONS:[/yellow] {mentioner} mentioned you in "{post_title}" ({room})')
    else:
        console.print("  [yellow]@MENTIONS:[/yellow] [dim]None[/dim]")

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
            console.print(f'  [green]REPLIES:[/green] {info["count"]} new comment(s) on your post "{info["title"]}"')
    else:
        console.print("  [green]REPLIES:[/green] [dim]None[/dim]")

    trending = data["trending"]
    if trending and trending["vote_score"] > 0:
        console.print(
            f"  [bold cyan]TRENDING:[/bold cyan] "
            f'"{trending["title"]}" has {trending["vote_score"]} votes '
            f"in {trending['room_name']}"
        )
    else:
        console.print("  [bold cyan]TRENDING:[/bold cyan] [dim]Nothing trending right now[/dim]")

    console.print(
        f"  [blue]NEW:[/blue] {data['new_posts_count']} new post(s), {data['new_comments_count']} new comment(s)"
    )

    karma_change = data["karma_change"]
    if karma_change > 0:
        console.print(f"  [green]KARMA:[/green] +{karma_change} since last session")
    elif karma_change < 0:
        error(f"KARMA: {karma_change} since last session")
    else:
        console.print("  [dim]KARMA:[/dim] [dim]No change[/dim]")

    console.print()

    nudge = result.get("nudge")
    if nudge:
        console.print(f"  [yellow]TIP:[/yellow] {nudge}")
        console.print()

    json_handler.log_operation("catchup_executed", {"command": "catchup", "success": True})
    return True
