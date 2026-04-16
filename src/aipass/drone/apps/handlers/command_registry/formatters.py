# =================== AIPass ====================
# Name: formatters.py
# Description: Rich output formatting for custom command registry
# Version: 1.0.0
# Created: 2026-03-17
# Modified: 2026-03-17
# =============================================

"""Rich output formatting for custom command registry operations.

Renders command lists, activation results, and removal confirmations
using Rich tables and styled console output.
"""

from __future__ import annotations

from aipass.prax import logger

try:
    from aipass.cli.apps.modules import console
except ImportError:
    logger.warning("CLI console not available, falling back to default Rich Console")
    from rich.console import Console

    console = Console()

from rich.table import Table

from aipass.drone.apps.handlers.json import json_handler


def format_command_list(commands: list[dict]) -> None:
    """Display registered custom commands as a Rich table.

    Args:
        commands: List of command dicts with ``name``, ``target``,
                  ``command``, ``args``, ``description`` keys.
    """
    json_handler.log_operation(
        "format_command_list",
        {"command_count": len(commands)},
    )

    if not commands:
        console.print()
        console.print("No custom commands registered.")
        console.print("Use 'drone activate @branch' to register commands from a branch.")
        console.print()
        return

    console.print()

    table = Table(show_header=True, header_style="bold")
    table.add_column("Name", min_width=14)
    table.add_column("Target", min_width=10)
    table.add_column("Command", min_width=12)
    table.add_column("Args", min_width=12)
    table.add_column("Description", min_width=24)

    for cmd in commands:
        table.add_row(
            cmd.get("name", ""),
            cmd.get("target", ""),
            cmd.get("command", ""),
            " ".join(cmd.get("args", [])),
            cmd.get("description", ""),
        )

    console.print(table)
    console.print()
    console.print(f"{len(commands)} custom command(s) registered.")
    console.print()


def format_activation_results(
    branch: str,
    added: list[str],
    skipped: list[str],
) -> None:
    """Display what was registered during activation.

    Args:
        branch: Branch name (with or without ``@`` prefix).
        added: List of command names that were successfully registered.
        skipped: List of command names that were skipped (already exist).
    """
    display_name = branch if branch.startswith("@") else f"@{branch}"

    console.print()

    if added:
        console.print(f"Activated {len(added)} command(s) from [bold]{display_name}[/bold]:")
        for name in added:
            console.print(f"  + {name}")

    if skipped:
        if added:
            console.print()
        console.print(f"Skipped {len(skipped)} command(s) (already registered):")
        for name in skipped:
            console.print(f"  - {name}")

    if not added and not skipped:
        console.print(f"No commands discovered in {display_name}.")

    console.print()


def format_removal(name: str, success: bool) -> None:
    """Display the result of removing a custom command.

    Args:
        name: The command name that was targeted for removal.
        success: Whether the removal succeeded.
    """
    console.print()
    if success:
        console.print(f"Removed custom command '{name}'.")
    else:
        console.print(f"Command '{name}' not found in registry.")
    console.print()
