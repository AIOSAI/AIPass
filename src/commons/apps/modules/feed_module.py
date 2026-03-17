# =================== AIPass ====================
# Name: feed_module.py
# Description: Feed orchestration module
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-03-07
# =============================================

"""
Feed Orchestration Module

Thin router for feed display. Delegates query logic to
handlers/feed/feed_ops.py and renders the results as a Rich table.

Handles: feed command with hot/new/top/activity sorting.
"""

from typing import List

from aipass.prax.apps.modules.logger import system_logger as logger

try:
    from aipass.cli.apps.modules import console
except ImportError:
    from rich.console import Console
    console = Console()

from rich.table import Table

from commons.apps.handlers.feed.feed_ops import display_feed, format_time_ago
from commons.apps.handlers.identity.identity_ops import resolve_display_name
from commons.apps.handlers.json import json_handler


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("feed_module Module")
    console.print("Thin router for feed display — queries and renders posts with hot/new/top/activity sorting.")
    console.print()
    console.print("Connected Handlers:")
    console.print("  handlers/feed/")
    console.print("    - feed_ops.py (display_feed — query feed posts with sorting and pagination)")
    console.print("    - feed_ops.py (format_time_ago — format timestamps as relative time strings)")
    console.print("  handlers/identity/")
    console.print("    - identity_ops.py (resolve_display_name — resolve branch name to display name)")
    console.print()


# =============================================================================
# COMMAND ROUTING
# =============================================================================

def handle_command(command: str, args: List[str]) -> bool:
    """
    Handle feed-related commands.

    Args:
        command: Command name (feed).
        args: Command arguments.

    Returns:
        True if command handled, False otherwise.
    """
    if command != "feed":
        return False

    return _handle_feed(args)


# =============================================================================
# DISPLAY HANDLER
# =============================================================================

def _handle_feed(args: List[str]) -> bool:
    """Query the feed and render as a Rich table."""
    result = display_feed(args)

    if not result["success"]:
        console.print(f"[red]Feed error: {result['error']}[/red]")
        return True

    posts = result["posts"]
    total = result["total"]
    sort = result["sort"]
    room_name = result.get("room")
    limit = result["limit"]
    offset = result["offset"]

    # Header
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

    # Build table
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

    console.print(
        f"[dim]Showing {len(posts)} of {total} posts{page_info} | "
        f"commons thread <id> for details[/dim]"
    )
    console.print()

    json_handler.log_operation("feed_executed", {"command": "feed", "success": True})
    return True
