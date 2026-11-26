# =================== AIPass ====================
# Name: comment.py
# Description: Comment orchestration module
# Version: 1.1.1
# Created: 2026-03-07
# Modified: 2026-11-26
# =============================================

"""Comment Orchestration Module"""

from typing import List

from aipass.prax import logger  # noqa: F401 - the imports standard requires the prax logger in every module
from aipass.cli import console, error, success

from aipass.commons.apps.handlers.comments.comment_ops import add_comment, vote_on_content
from aipass.commons.apps.handlers.identity.identity_ops import resolve_display_name
from aipass.commons.apps.handlers.json import json_handler


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("[bold cyan]comment - Comments and Votes[/bold cyan]")
    console.print("[dim]Adds comments to posts and records up/down votes on content.[/dim]")
    console.print()
    console.print("[bold cyan]Connected Handlers:[/bold cyan]")
    console.print("  [cyan]handlers/comments/[/cyan]")
    console.print("    [cyan]-[/cyan] comment_ops.py [dim](add_comment — add a comment to a post)[/dim]")
    console.print("    [cyan]-[/cyan] comment_ops.py [dim](vote_on_content — upvote or downvote content)[/dim]")
    console.print("  [cyan]handlers/identity/[/cyan]")
    console.print(
        "    [cyan]-[/cyan] identity_ops.py [dim](resolve_display_name — map branch name to display name)[/dim]"
    )
    console.print()
    console.print("[dim]Run 'drone @commons comment --help' for usage[/dim]")
    console.print()


def print_help():
    """Display usage help."""
    console.print()
    console.print("[bold cyan]comment - Comments and Votes[/bold cyan]")
    console.print("[dim]Adds comments to posts and records up/down votes on content.[/dim]")
    console.print()
    console.print("[bold cyan]Usage:[/bold cyan]")
    console.print("  [cyan]drone @commons comment[/cyan] <post_id> <content> \\[--parent <parent_id>]")
    console.print("  [cyan]drone @commons vote[/cyan] <post|comment> <id> <up|down>")
    console.print()
    console.print("[bold cyan]Examples:[/bold cyan]")
    console.print('  [cyan]drone @commons comment 12 "Nice work"[/cyan]')
    console.print('  [cyan]drone @commons comment 12 "Agreed" --parent 3[/cyan]')
    console.print("  [cyan]drone @commons vote post 12 up[/cyan]")
    console.print()


def handle_command(command: str, args: List[str]) -> bool:
    """Handle comment and vote commands; False if the command is not ours."""
    if command in ("comment", "vote") and ("--help" in args or "-h" in args):
        print_help()
        return True

    if command == "comment":
        result = _handle_comment(args)
    elif command == "vote":
        result = _handle_vote(args)
    else:
        return False

    if result:
        json_handler.log_operation(f"{command}_executed", {"command": command, "success": True})
    return result


def _handle_comment(args: List[str]) -> bool:
    """Add a comment and display the result."""
    result = add_comment(args)

    if not result["success"]:
        error(result["error"])
        return True

    parent_note = f" (reply to comment {result['parent_id']})" if result.get("parent_id") else ""
    console.print()
    success(f"Comment added to post {result['post_id']}{parent_note}")
    console.print(f"  [dim]Comment ID:[/dim] {result['comment_id']}")
    console.print(f"  [dim]Author:[/dim] {resolve_display_name(result['author'])}")
    if result.get("mentions"):
        console.print(f"  [dim]Mentions:[/dim] {', '.join(f'@{m}' for m in result['mentions'])}")
    if result.get("mentions_error"):
        console.print(f"  [yellow]Commented; {result['mentions_error']}[/yellow]")
    console.print()

    return True


def _handle_vote(args: List[str]) -> bool:
    """Vote on content and display the result."""
    result = vote_on_content(args)

    if not result["success"]:
        error(result["error"])
        return True

    action_msg = {
        "voted": f"Voted {result['direction']}",
        "changed": f"Changed vote to {result['direction']}",
        "removed": "Vote removed",
    }.get(result["action"], result["action"])

    arrow = "^" if result["direction"] == "up" else "v"

    console.print()
    success(f"{arrow} {action_msg} on {result['target_type']} {result['target_id']} (score: {result['new_score']})")
    console.print()

    return True
