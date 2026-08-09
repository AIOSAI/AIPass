# =================== AIPass ====================
# Name: read.py
# Description: aipass read — render a branch README in the terminal
# Version: 1.1.0
# Created: 2026-08-07
# Modified: 2026-08-08
# =============================================

"""
aipass read — view any branch's README, rendered, straight from the live file.

The depth step behind `aipass help`: help answers with matched sections,
read shows the whole document. Content is never cached — every invocation
reads the current file via the readme_map handler.

Usage:
    aipass read              # list branches with a README
    aipass read drone        # render drone's README
    aipass read @drone       # @-prefix tolerated
    aipass read --help
"""

from __future__ import annotations

from aipass.aipass.apps.handlers.json import json_handler
from aipass.aipass.apps.handlers.readme_map import get_readme_path, list_branches, read_readme_at
from aipass.cli.apps.modules import console, error
from aipass.prax import logger

COMMAND = "read"
_MODULE_NAME = "read"
_VERSION = "1.1.0"
_DESCRIPTION = "Render a branch README in the terminal, live-read"


def print_help() -> None:
    """Print usage help for the read command."""
    console.print()
    console.print("[bold cyan]aipass read[/bold cyan] — view a branch README")
    console.print()
    console.print("[yellow]USAGE:[/yellow]")
    console.print("  [green]aipass read[/green]           [dim]# list branches with a README[/dim]")
    console.print("  [green]aipass read <branch>[/green]  [dim]# render that branch's README[/dim]")
    console.print()
    console.print("[yellow]EXAMPLES:[/yellow]")
    console.print("  [green]aipass read drone[/green]")
    console.print("  [green]aipass read ai_mail[/green]")
    console.print()


def print_introspection() -> None:
    """Print module info plus the live roster of branches this module can read."""
    console.print(f"[bold cyan]Module:[/bold cyan] {_MODULE_NAME}")
    console.print(f"[bold cyan]Command:[/bold cyan] {COMMAND}")
    console.print(f"[bold cyan]Description:[/bold cyan] {_DESCRIPTION}")
    console.print(f"[bold cyan]Version:[/bold cyan] {_VERSION}")
    _print_branch_list()


def _print_branch_list() -> None:
    """List every branch that has a README, discovered live."""
    branches = list_branches()
    console.print()
    console.print("[bold cyan]aipass read[/bold cyan] — branches with a README:")
    console.print()
    for branch in sorted(branches):
        console.print(f"  [green]{branch}[/green]")
    console.print()
    console.print("[dim]Run 'aipass read <branch>' to view one.[/dim]")
    console.print()


def _render_readme(branch: str) -> None:
    """Live-read and render one branch README as Markdown."""
    from rich.markdown import Markdown

    readme_path = get_readme_path(branch)
    if readme_path is None:
        available = ", ".join(sorted(list_branches()))
        error(f"No README found for branch '{branch}'.")
        console.print(f"[dim]Available: {available}[/dim]")
        return

    text = read_readme_at(readme_path)
    if text is None:
        logger.error("[read] README unreadable for branch '%s' at %s", branch, readme_path)
        error(f"Could not read {readme_path}.")
        return

    console.print()
    console.print(f"[dim]{readme_path}[/dim]")
    console.print()
    console.print(Markdown(text))
    console.print()


def handle_command(command: str, args: list[str]) -> bool:
    """Route `aipass read [branch]` — returns True if handled."""
    if command != COMMAND:
        return False

    json_handler.ensure_module_jsons(_MODULE_NAME)

    if not args:
        print_introspection()
        json_handler.log_operation("read_list", data={}, module_name=_MODULE_NAME)
        return True

    if args[0] in ("--help", "-h", "help"):
        print_help()
        return True

    if args[0] == "--info":
        print_introspection()
        return True

    branch = args[0].lstrip("@")
    _render_readme(branch)
    json_handler.log_operation("read_branch", data={"branch": branch}, module_name=_MODULE_NAME)
    return True
