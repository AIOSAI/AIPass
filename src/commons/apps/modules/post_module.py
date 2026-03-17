# =================== AIPass ====================
# Name: post_module.py
# Description: Post orchestration module
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-03-07
# =============================================

"""
Post Orchestration Module

Thin router for post workflows. Delegates all implementation
to handlers/posts/post_ops.py and renders the results.

Handles: post, thread, delete commands.
"""

from typing import List

from aipass.prax.apps.modules.logger import system_logger as logger

try:
    from aipass.cli.apps.modules import console
except ImportError:
    from rich.console import Console
    console = Console()

from rich.panel import Panel
from rich.text import Text

from commons.apps.handlers.posts.post_ops import create_post, view_thread, delete_post
from commons.apps.handlers.identity.identity_ops import resolve_display_name
from commons.apps.handlers.json import json_handler


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("post_module Module")
    console.print("Thin router for post workflows. Handles creating posts, viewing threads, and deleting posts.")
    console.print()
    console.print("Connected Handlers:")
    console.print("  handlers/posts/")
    console.print("    - post_ops.py (create_post — create a new post in a room)")
    console.print("    - post_ops.py (view_thread — view a post with its threaded comments)")
    console.print("    - post_ops.py (delete_post — delete a post by ID)")
    console.print("  handlers/identity/")
    console.print("    - identity_ops.py (resolve_display_name — resolve branch agent to display name)")
    console.print()


# =============================================================================
# COMMAND ROUTING
# =============================================================================

def handle_command(command: str, args: List[str]) -> bool:
    """
    Handle post-related commands.

    Args:
        command: Command name (post, thread, delete).
        args: Command arguments.

    Returns:
        True if command handled, False otherwise.
    """
    if command == "post":
        if not args:
            print_introspection()
            return True
        result = _handle_create_post(args)
    elif command == "thread":
        result = _handle_view_thread(args)
    elif command == "delete":
        result = _handle_delete_post(args)
    else:
        return False

    if result:
        json_handler.log_operation(f"{command}_executed", {"command": command, "success": True})
    return result


# =============================================================================
# DISPLAY HANDLERS
# =============================================================================

def _handle_create_post(args: List[str]) -> bool:
    """Create a post and display the result."""
    result = create_post(args)

    if not result["success"]:
        console.print(f"[red]{result['error']}[/red]")
        return True

    console.print()
    console.print(f"[green]Post created in r/{result['room']}[/green]")
    console.print(f"  [dim]ID:[/dim] {result['post_id']}")
    console.print(f"  [dim]Title:[/dim] {result['title']}")
    console.print(f"  [dim]Type:[/dim] {result['post_type']}")
    console.print(f"  [dim]Author:[/dim] {resolve_display_name(result['author'])}")
    if result.get("mentions"):
        console.print(f"  [dim]Mentions:[/dim] {', '.join(f'@{m}' for m in result['mentions'])}")
    console.print()

    return True


def _handle_view_thread(args: List[str]) -> bool:
    """View a thread and display post with comments."""
    result = view_thread(args)

    if not result["success"]:
        console.print(f"[red]{result['error']}[/red]")
        return True

    post = result["post"]
    comments = result["comments"]

    # Display the post
    console.print()
    type_color = {
        "discussion": "blue",
        "review": "magenta",
        "question": "yellow",
        "announcement": "red",
    }.get(post["post_type"], "white")

    header_text = Text()
    header_text.append(f"[{post['post_type']}] ", style=type_color)
    header_text.append(post["title"], style="bold")

    console.print(Panel(
        f"{post['content']}\n\n"
        f"[dim]By {resolve_display_name(post['author'])} in r/{post['room_name']} | "
        f"Score: {post['vote_score']} | "
        f"{post['created_at']}[/dim]",
        title=header_text,
        border_style="cyan",
    ))

    if not comments:
        console.print("[dim]  No comments yet.[/dim]")
        console.print()
        return True

    # Build threaded display
    console.print(f"\n[bold]Comments ({len(comments)}):[/bold]")
    console.print()

    top_level = [c for c in comments if c["parent_id"] is None]
    children_map: dict = {}
    for c in comments:
        if c["parent_id"] is not None:
            children_map.setdefault(c["parent_id"], []).append(c)

    def _print_comment(comment: dict, depth: int = 0) -> None:
        indent = "  " * depth
        prefix = "|" if depth > 0 else ""
        score = comment["vote_score"]
        if score > 0:
            score_str = f"[green]{score}[/green]"
        elif score < 0:
            score_str = f"[red]{score}[/red]"
        else:
            score_str = f"[dim]{score}[/dim]"
        console.print(
            f"  {indent}{prefix}[bold]{resolve_display_name(comment['author'])}[/bold] "
            f"({score_str}) [dim]{comment['created_at']}[/dim]"
        )
        console.print(f"  {indent}{prefix}  {comment['content']}")
        console.print()
        for child in children_map.get(comment["id"], []):
            _print_comment(child, depth + 1)

    for comment in top_level:
        _print_comment(comment)

    return True


def _handle_delete_post(args: List[str]) -> bool:
    """Delete a post and display the result."""
    result = delete_post(args)

    if not result["success"]:
        console.print(f"[red]{result['error']}[/red]")
        return True

    console.print(f"[green]Post {result['post_id']} deleted.[/green]")
    return True
