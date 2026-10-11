# =================== AIPass ====================
# Name: formatters.py
# Description: Rich output formatting for scan results
# Version: 1.0.1
# Created: 2026-03-17
# Modified: 2026-09-28
# =============================================

"""Rich output formatting for scan results.

Renders discovered-command lists as clean Rich tables or informational
messages when no commands are found.
"""

from __future__ import annotations

try:
    from aipass.cli.apps.modules import console
except ImportError:
    from aipass.prax import logger

    logger.warning("formatters: aipass.cli.apps.modules.console unavailable, using fallback Rich Console")
    from rich.console import Console

    console = Console()

from rich.table import Table

from aipass.drone.apps.handlers.json import json_handler


def format_scan_results(branch_name: str, commands: list[dict]) -> None:
    """Display scan results as a Rich table.

    Args:
        branch_name: Branch name (with or without ``@`` prefix) for the title.
        commands: List of command dicts with ``name``, ``description``, ``source``.
    """
    display_name = branch_name if branch_name.startswith("@") else f"@{branch_name}"

    json_handler.log_operation(
        "format_scan_results",
        {"branch": display_name, "command_count": len(commands)},
    )

    console.print()
    console.print(f"Scan results for [bold]{display_name}[/bold]")
    console.print()

    table = Table(show_header=True, header_style="bold")
    table.add_column("#", justify="right", style="dim", width=4)
    table.add_column("Command", min_width=18)
    table.add_column("Description", min_width=30)
    table.add_column("Source", justify="center", width=8)

    for idx, cmd in enumerate(commands, start=1):
        table.add_row(
            str(idx),
            cmd.get("name", ""),
            cmd.get("description", ""),
            cmd.get("source", ""),
        )

    console.print(table)
    console.print()
    console.print(f"{len(commands)} command(s) discovered for {display_name}")
    console.print()


def format_no_commands(branch_name: str) -> None:
    """Display a message when no commands are found for a branch.

    Args:
        branch_name: Branch name (with or without ``@`` prefix).
    """
    display_name = branch_name if branch_name.startswith("@") else f"@{branch_name}"

    console.print()
    console.print(f"No commands discovered for [bold]{display_name}[/bold].")
    console.print("Ensure the branch has an entry point with --help or modules with handle_command().")
    console.print()


def format_help_scan_failure(branch_name: str, help_errors: list[str]) -> None:
    """Name a failed --help scan on stderr, after the results; nothing when the list is empty.

    Loud where the caller is (drone scan / drone activate): the results shown
    before are real but partial. Exit stays 0 (drone's decision, DPLAN-0354 leg 3).

    Args:
        branch_name: Branch name without the ``@`` prefix.
        help_errors: What scan_branch collected; the first entry is named.
    """
    if not help_errors:
        return
    from aipass.cli.apps.modules import err_console

    err_console.print(
        f"scan: @{branch_name}: the --help scan failed ({help_errors[0]}); showing module files only",
        markup=False,
    )
