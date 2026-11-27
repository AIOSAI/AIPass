# =================== AIPass ====================
# Name: provider.py
# Description: aipass provider NAME: the install's last step, callable any time
# Version: 1.0.0
# Created: 2026-11-24
# Modified: 2026-11-26
# =============================================

"""aipass provider claude|codex|opencode: install the CLI if missing, wire it, open devpulse in it.

The same ending `aipass install` runs. Idempotent: an installed CLI is never installed
again; its wiring is refreshed and devpulse opens.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from aipass.cli import console, error, escape
from aipass.aipass.apps.handlers import provider_choice
from aipass.aipass.apps.handlers.help_flag import wants_help
from aipass.aipass.apps.handlers.json import json_handler
from aipass.aipass.apps.modules.install import DEFAULT_HOME, WAKE_PROMPT
from aipass.prax import logger

COMMAND = "provider"


def print_introspection() -> None:
    """Each provider and whether its CLI is on this machine."""
    console.print("[bold cyan]aipass provider[/bold cyan]")
    console.print("[dim]Each provider CLI and where it is installed.[/dim]")
    for key in provider_choice.ORDER:
        where = provider_choice.cli_path(key) or "not installed"
        console.print(f"  {key:<9} {provider_choice.PROVIDERS[key].title:<12} {escape(where)}")
    console.print("[dim]Run 'aipass provider --help' for usage and examples.[/dim]")


def print_help() -> None:
    """Usage for aipass provider."""
    console.print()
    console.print("[bold cyan]aipass provider[/bold cyan]: talk to devpulse with one CLI")
    console.print()
    console.print("[yellow]EXAMPLES:[/yellow]")
    console.print("  [green]aipass provider codex --dry-run[/green]")
    console.print()
    console.print("[yellow]USAGE:[/yellow]")
    console.print("  [green]aipass provider[/green]                 [dim]# each CLI and where it is installed[/dim]")
    console.print(
        "  [green]aipass provider NAME[/green]            [dim]# claude|codex|opencode: install it with its vendor's"
        " installer if missing, wire it, open devpulse in it[/dim]"
    )
    console.print("  [green]aipass provider NAME --dry-run[/green]  [dim]# say what would happen, run nothing[/dim]")
    console.print()
    console.print("[dim]The home is $AIPASS_HOME, else ~/AIPass.[/dim]")


def handle_command(command: str, args: list[str]) -> bool:
    """Route `aipass provider`. Exits with the ending's code: 1 when the vendor installer failed, 2 on bad usage."""
    if command != COMMAND:
        return False
    if not args:
        print_introspection()
        return True
    if wants_help(args):
        print_help()
        return True
    unknown = [arg for arg in args if arg.startswith("-") and arg not in ("--dry-run", "--info")]
    if unknown:
        error(f"aipass provider: unknown flag(s): {' '.join(unknown)} (only --dry-run)")
        sys.exit(2)
    names = [arg for arg in args if not arg.startswith("-")]
    if not names or args[0] == "--info":
        print_introspection()
        return True
    if names[0] not in provider_choice.PROVIDERS or len(names) > 1:
        error(f"aipass provider takes one of: {', '.join(provider_choice.ORDER)}")
        sys.exit(2)
    home = Path(os.environ.get("AIPASS_HOME") or DEFAULT_HOME).expanduser().resolve()
    if not (home / ".claude" / "provider_manifest.json").is_file():
        error(f"No AIPass install at {home}: set AIPASS_HOME, or run 'aipass install'")
        sys.exit(2)
    logger.info("[provider] %s for %s", names[0], home)
    code = provider_choice.run_ending(
        names[0],
        home,
        WAKE_PROMPT,
        non_interactive=True,
        dry_run="--dry-run" in args,
        prompt=input,
        say=lambda line: console.print(line, markup=False, highlight=False),
    )
    json_handler.log_operation("provider", {"provider": names[0], "home": str(home), "exit": code})
    sys.exit(code)
