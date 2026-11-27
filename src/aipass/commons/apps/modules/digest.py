# =================== AIPass ====================
# Name: digest.py
# Description: Digest Orchestration Module
# Version: 1.0.1
# Created: 2026-03-07
# Modified: 2026-11-26
# =============================================

"""
Digest Orchestration Module
"""

from typing import List

from aipass.prax import logger  # noqa: F401 - the imports standard requires the prax logger in every module
from aipass.cli import console, error

from rich.panel import Panel

from aipass.commons.apps.handlers.digest.digest_ops import show_digest
from aipass.commons.apps.handlers.json import json_handler


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("[bold cyan]digest - Community Digest[/bold cyan]")
    console.print(
        "[dim]Thin router for community digest workflows. "
        "Queries digest data and renders activity summaries with Rich.[/dim]"
    )
    console.print()
    console.print("[bold cyan]Connected Handlers:[/bold cyan]")
    console.print("  [cyan]handlers/digest/[/cyan]")
    console.print(
        "    [cyan]-[/cyan] digest_ops.py [dim](show_digest — query and compile community activity digest)[/dim]"
    )
    console.print()
    console.print("[dim]Run 'drone @commons digest --help' for usage[/dim]")


def print_help():
    """Display usage help for the digest command."""
    console.print()
    console.print("[bold cyan]digest - Community Digest[/bold cyan]")
    console.print("[dim]Summarize the last 24 hours: top posts, most active branches, new branches[/dim]")
    console.print()
    console.print("[bold cyan]Usage:[/bold cyan]")
    console.print("  [cyan]drone @commons digest[/cyan]")
    console.print()
    console.print("[bold cyan]Examples:[/bold cyan]")
    console.print("  [cyan]drone @commons digest[/cyan]")
    console.print()


def handle_command(command: str, args: List[str]) -> bool:
    """Handle digest-related commands."""
    if command != "digest":
        return False

    if "--help" in args or "-h" in args:
        print_help()
        return True

    return _handle_digest()


def _handle_digest() -> bool:
    """Query digest and display results."""
    result = show_digest()

    if not result["success"]:
        error(f"Failed to generate digest: {result['error']}")
        return True

    top_posts = result["top_posts"]
    active_branches = result["active_branches"]
    new_branches = result["new_branches"]
    totals = result["totals"]

    console.print()

    console.print(
        Panel(
            "[bold]Community Activity Digest[/bold]\n[dim]Last 24 hours[/dim]",
            border_style="cyan",
            expand=False,
        )
    )
    console.print()

    console.print(
        f"  [bold cyan]Activity:[/bold cyan] {totals['total_posts']} posts, {totals['total_comments']} comments"
    )
    console.print()

    if top_posts:
        console.print("[bold cyan]Top Posts by Engagement:[/bold cyan]")
        console.print()
        for i, post in enumerate(top_posts, 1):
            engagement = post["engagement_count"]
            console.print(
                f"  [bold]{i}.[/bold] "
                f'[yellow]#{post["id"]}[/yellow] "{post["title"]}" '
                f"by [green]{post['author']}[/green] in r/{post['room_name']}"
            )
            console.print(
                f"     {engagement} engagements "
                f"({post['vote_count']} votes, "
                f"{post['comment_count']} comments, "
                f"{post['reaction_count']} reactions)"
            )
        console.print()
    else:
        console.print("[dim]  No posts with engagement in the last 24h[/dim]")
        console.print()

    if active_branches:
        console.print("[bold cyan]Most Active Branches:[/bold cyan]")
        console.print()
        for branch in active_branches:
            console.print(
                f"  [green]{branch['agent']}[/green] - "
                f"{branch['total_activity']} actions "
                f"({branch['post_count']} posts, {branch['comment_count']} comments)"
            )
        console.print()
    else:
        console.print("[dim]  No branch activity in the last 24h[/dim]")
        console.print()

    if new_branches:
        console.print("[bold cyan]New Branches:[/bold cyan]")
        console.print()
        for name in new_branches:
            console.print(f"  [green]+[/green] {name}")
        console.print()
    else:
        console.print("[dim]  No new branches in the last 24h[/dim]")
        console.print()

    json_handler.log_operation("digest_executed", {"command": "digest", "success": True})
    return True
