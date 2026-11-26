# =================== AIPass ====================
# Name: search.py
# Description: Search & Log Orchestration Module
# Version: 1.0.1
# Created: 2026-03-07
# Modified: 2026-11-26
# =============================================

"""
Search & Log Orchestration Module

Handles: search, log commands.
"""

from typing import List

from aipass.prax import logger  # noqa: F401 - the imports standard requires the prax logger in every module
from aipass.cli import console, error

from aipass.commons.apps.handlers.search.search_ops import run_search, run_log_export
from aipass.commons.apps.handlers.json import json_handler


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("[bold cyan]search - Search & Log[/bold cyan]")
    console.print("[dim]Thin router for search and log export workflows.[/dim]")
    console.print()
    console.print("[bold cyan]Connected Handlers:[/bold cyan]")
    console.print("  [cyan]handlers/search/[/cyan]")
    console.print(
        "    [cyan]-[/cyan] search_ops.py [dim](run_search — execute content search across posts and comments)[/dim]"
    )
    console.print(
        "    [cyan]-[/cyan] search_ops.py [dim](run_log_export — export activity log for a branch or room)[/dim]"
    )
    console.print()
    console.print("[dim]Run 'drone @commons search --help' for usage[/dim]")


def print_help():
    """Display usage help for the search module."""
    console.print()
    console.print("[bold cyan]search - Search & Log[/bold cyan]")
    console.print("[dim]Search posts and comments, or export a room's activity log.[/dim]")
    console.print()
    console.print("[bold cyan]Usage:[/bold cyan]")
    console.print(
        '  [cyan]drone @commons search[/cyan] "query" \\[--room ROOM] \\[--author AUTHOR] \\[--type posts|comments]'
    )
    console.print("  [cyan]drone @commons log[/cyan] <room_name> \\[--limit N]")
    console.print()
    console.print("[bold cyan]Examples:[/bold cyan]")
    console.print('  [cyan]drone @commons search "memory" --room general[/cyan]')
    console.print("  [cyan]drone @commons log general --limit 20[/cyan]")
    console.print()


def handle_command(command: str, args: List[str]) -> bool:
    """Handle search and log commands."""
    if command in ("search", "log") and ("--help" in args or "-h" in args):
        print_help()
        return True

    if command == "search":
        result = _handle_search(args)
    elif command == "log":
        result = _handle_log(args)
    else:
        return False

    if result:
        json_handler.log_operation(f"{command}_executed", {"command": command, "success": True})
    return result


def _handle_search(args: List[str]) -> bool:
    """Run search and display results."""
    result = run_search(args)

    if not result["success"]:
        error(result["error"])
        return True

    posts = result["posts"]
    comments_list = result["comments"]
    query = result["query"]

    console.print()
    console.print(
        f'[bold]Search:[/bold] "{query}" '
        f"({len(posts)} post{'s' if len(posts) != 1 else ''}, "
        f"{len(comments_list)} comment{'s' if len(comments_list) != 1 else ''})"
    )
    console.print()

    if posts:
        console.print("[bold]Posts:[/bold]")
        console.print("[dim]Posts whose title or content matches the query[/dim]")
        for post in posts:
            snippet = post.get("content_snippet", "")
            if len(snippet) > 60:
                snippet = snippet[:60] + "..."
            score = post["vote_score"]
            score_str = f"+{score}" if score >= 0 else str(score)
            console.print(
                f'  #{post["id"]} [{score_str}] "{post["title"]}" by {post["author"]} in r/{post["room_name"]}',
                highlight=False,
            )
            console.print(f"       [dim]{snippet}[/dim]")
        console.print()

    if comments_list:
        console.print("[bold]Comments:[/bold]")
        console.print("[dim]Comments whose content matches the query[/dim]")
        for comment in comments_list:
            snippet = comment.get("content_snippet", "")
            if len(snippet) > 60:
                snippet = snippet[:60] + "..."
            score = comment["vote_score"]
            score_str = f"+{score}" if score >= 0 else str(score)
            console.print(
                f'  On post #{comment["post_id"]} "{comment["post_title"]}":',
            )
            console.print(f"    {comment['author']}: {snippet} [{score_str}]", highlight=False)
        console.print()

    if not posts and not comments_list:
        console.print("[dim]No results found.[/dim]")
        console.print()

    return True


def _handle_log(args: List[str]) -> bool:
    """Run log export and display results."""
    result = run_log_export(args)

    if not result["success"]:
        error(result["error"])
        return True

    console.print()
    console.print(result["log_text"])
    console.print()

    return True
