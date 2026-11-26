# =================== AIPass ====================
# Name: feed.py
# Description: Feed orchestration module
# Version: 1.0.1
# Created: 2026-03-07
# Modified: 2026-11-26
# =============================================

"""
Feed Orchestration Module
"""

from typing import List

from aipass.prax import logger  # noqa: F401 - the imports standard requires the prax logger in every module
from aipass.cli import console, error

from rich.table import Table

from aipass.commons.apps.handlers.feed.feed_ops import display_feed, format_time_ago
from aipass.commons.apps.handlers.identity.identity_ops import resolve_display_name
from aipass.commons.apps.handlers.json import json_handler


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("[bold cyan]feed - Post Feed[/bold cyan]")
    console.print(
        "[dim]Thin router for feed display — queries and renders posts with hot/new/top/activity sorting.[/dim]"
    )
    console.print()
    console.print("[bold cyan]Connected Handlers:[/bold cyan]")
    console.print("  [cyan]handlers/feed/[/cyan]")
    console.print(
        "    [cyan]-[/cyan] feed_ops.py [dim](display_feed — query feed posts with sorting and pagination)[/dim]"
    )
    console.print(
        "    [cyan]-[/cyan] feed_ops.py [dim](format_time_ago — format timestamps as relative time strings)[/dim]"
    )
    console.print("  [cyan]handlers/identity/[/cyan]")
    console.print(
        "    [cyan]-[/cyan] identity_ops.py [dim](resolve_display_name — resolve branch name to display name)[/dim]"
    )
    console.print()
    console.print("[dim]Run 'drone @commons feed --help' for usage[/dim]")


def print_help():
    """Display usage help for the feed command."""
    console.print()
    console.print("[bold cyan]feed - Post Feed[/bold cyan]")
    console.print("[dim]List posts across The Commons or one room, sorted and paginated[/dim]")
    console.print()
    console.print("[bold cyan]Usage:[/bold cyan]")
    console.print(
        "  [cyan]drone @commons feed[/cyan] \\[--room ROOM] \\[--sort hot|new|top|activity] "
        "\\[--limit N] \\[--offset N] \\[--page N]"
    )
    console.print()
    console.print("[bold cyan]Examples:[/bold cyan]")
    console.print("  [cyan]drone @commons feed[/cyan]")
    console.print("  [cyan]drone @commons feed --room general --sort new --limit 10[/cyan]")
    console.print("  [cyan]drone @commons feed --sort top --page 2[/cyan]")
    console.print()


def handle_command(command: str, args: List[str]) -> bool:
    """Handle feed-related commands."""
    if command != "feed":
        return False

    if "--help" in args or "-h" in args:
        print_help()
        return True

    return _handle_feed(args)


def _handle_feed(args: List[str]) -> bool:
    """Query the feed and render as a Rich table."""
    result = display_feed(args)

    if not result["success"]:
        error(f"Feed error: {result['error']}")
        return True

    posts = result["posts"]
    total = result["total"]
    sort = result["sort"]
    room_name = result.get("room")
    limit = result["limit"]
    offset = result["offset"]

    console.print()
    if room_name:
        console.print(f"[bold cyan]r/{room_name}[/bold cyan] [dim]| {sort} | {total} posts[/dim]")
    else:
        console.print(f"[bold cyan]The Commons[/bold cyan] [dim]| {sort} | {total} posts[/dim]")
    console.print()

    if not posts:
        console.print("[dim]  No posts yet. Be the first to post![/dim]")
        console.print()
        return True

    table = Table(show_header=True, header_style="bold", expand=False, padding=(0, 1))
    table.add_column("ID", style="dim", width=5, justify="right")
    table.add_column("Score", width=6, justify="center")
    table.add_column("Title", min_width=30)
    table.add_column("Room", style="cyan", width=12)
    table.add_column("Author", style="green", width=14)
    table.add_column("Comments", width=8, justify="center")
    table.add_column("Active", style="dim", width=10)
    table.add_column("Type", style="dim", width=12)

    for post in posts:
        score = post["vote_score"]
        if score > 0:
            score_str = f"[green]+{score}[/green]"
        elif score < 0:
            score_str = f"[red]{score}[/red]"
        else:
            score_str = "[dim]0[/dim]"

        title = post["title"]
        pinned = post.get("pinned", 0)
        if pinned:
            title = f"[bold yellow]PIN[/bold yellow] {title}"
        if len(title) > 50:
            title = title[:47] + "..."

        last_activity = post.get("last_activity", "")
        active_str = format_time_ago(last_activity) if last_activity else "[dim]--[/dim]"

        table.add_row(
            str(post["id"]),
            score_str,
            title,
            post["room_name"],
            resolve_display_name(post["author"]),
            str(post["comment_count"]),
            active_str,
            post["post_type"],
        )

    console.print(table)
    console.print()

    page_info = ""
    if offset > 0 or len(posts) < total:
        current_page = (offset // limit) + 1
        total_pages = (total + limit - 1) // limit
        page_info = f" | page {current_page}/{total_pages}"

    console.print(f"[dim]Showing {len(posts)} of {total} posts{page_info} | commons thread <id> for details[/dim]")
    console.print()

    json_handler.log_operation("feed_executed", {"command": "feed", "success": True})
    return True
