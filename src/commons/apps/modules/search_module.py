# =================== AIPass ====================
# Name: search_module.py
# Description: Search & Log Orchestration Module
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-03-07
# =============================================

"""
Search & Log Orchestration Module

Thin router for search and log export workflows. Delegates query logic
to handlers/search/search_ops.py and renders results with Rich.

Handles: search, log commands.
"""

from typing import List

from aipass.prax.apps.modules.logger import system_logger as logger

try:
    from aipass.cli.apps.modules import console
except ImportError:
    from rich.console import Console
    console = Console()

from commons.apps.handlers.search.search_ops import run_search, run_log_export
from commons.apps.handlers.json import json_handler


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("search_module Module")
    console.print("Thin router for search and log export workflows.")
    console.print()
    console.print("Connected Handlers:")
    console.print("  handlers/search/")
    console.print("    - search_ops.py (run_search — execute content search across posts and comments)")
    console.print("    - search_ops.py (run_log_export — export activity log for a branch or room)")
    console.print()


# =============================================================================
# COMMAND ROUTING
# =============================================================================

def handle_command(command: str, args: List[str]) -> bool:
    """
    Handle search and log commands.

    Args:
        command: Command name (search, log)
        args: Command arguments

    Returns:
        True if command handled, False otherwise
    """
    if command == "search":
        result = _handle_search(args)
    elif command == "log":
        result = _handle_log(args)
    else:
        return False

    if result:
        json_handler.log_operation(f"{command}_executed", {"command": command, "success": True})
    return result


# =============================================================================
# DISPLAY HANDLERS
# =============================================================================

def _handle_search(args: List[str]) -> bool:
    """Run search and display results."""
    result = run_search(args)

    if not result["success"]:
        console.print(f"[red]{result['error']}[/red]")
        return True

    posts = result["posts"]
    comments_list = result["comments"]
    query = result["query"]

    console.print()
    console.print(
        f"[bold]Search:[/bold] \"{query}\" "
        f"({len(posts)} post{'s' if len(posts) != 1 else ''}, "
        f"{len(comments_list)} comment{'s' if len(comments_list) != 1 else ''})"
    )
    console.print()

    if posts:
        console.print("[bold]Posts:[/bold]")
        for post in posts:
            snippet = post.get("content_snippet", "")
            if len(snippet) > 60:
                snippet = snippet[:60] + "..."
            score = post["vote_score"]
            score_str = f"+{score}" if score >= 0 else str(score)
            console.print(
                f"  #{post['id']} [{score_str}] \"{post['title']}\" "
                f"by {post['author']} in r/{post['room_name']}"
            )
            console.print(f"       [dim]{snippet}[/dim]")
        console.print()

    if comments_list:
        console.print("[bold]Comments:[/bold]")
        for comment in comments_list:
            snippet = comment.get("content_snippet", "")
            if len(snippet) > 60:
                snippet = snippet[:60] + "..."
            score = comment["vote_score"]
            score_str = f"+{score}" if score >= 0 else str(score)
            console.print(
                f"  On post #{comment['post_id']} \"{comment['post_title']}\":",
            )
            console.print(
                f"    {comment['author']}: {snippet} [{score_str}]"
            )
        console.print()

    if not posts and not comments_list:
        console.print("[dim]No results found.[/dim]")
        console.print()

    return True


def _handle_log(args: List[str]) -> bool:
    """Run log export and display results."""
    result = run_log_export(args)

    if not result["success"]:
        console.print(f"[red]{result['error']}[/red]")
        return True

    console.print()
    console.print(result["log_text"])
    console.print()

    return True
