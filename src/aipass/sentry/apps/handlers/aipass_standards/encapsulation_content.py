# =================== AIPass ====================
# Name: encapsulation_content.py
# Description: Encapsulation Standards Content Handler
# Version: 1.3.1
# Created: 2026-03-09
# Modified: 2026-11-17
# =============================================

"""
Encapsulation Standards Content Handler

Provides formatted encapsulation standards content.
Module orchestrates, handler implements.
"""

from aipass.sentry.apps.handlers.json import json_handler


def get_encapsulation_standards() -> str:
    """Return formatted encapsulation standards content with Rich markup."""
    sep = "─" * 70
    lines = [
        f"[dim]{sep}[/dim]",
        "[bold red]ENCAPSULATION STANDARDS[/bold red]",
        "[dim]Handlers are implementation details. The front door is the public API.[/dim]",
        f"[dim]{sep}[/dim]",
        "",
        "[bold cyan]WHY IT MATTERS:[/bold cyan]",
        "  Cross-branch handler imports create tight coupling.",
        "  The front door (from aipass.<branch> import <name>) is the stable entry point.",
        "",
        f"[dim]{sep}[/dim]",
        "[bold cyan]THE THREE RULES:[/bold cyan]",
        "",
        "[yellow]RULE 1: No Cross-Branch Handler Imports[/yellow]",
        "  [red]✗[/red] [dim]from aipass.flow.apps.handlers.plan.validator import validate_plan[/dim]",
        "  [green]✓[/green] [dim]from aipass.flow import get_open_plans[/dim]  (a name flow's front door hands out)",
        "",
        "[yellow]RULE 2: Inside a Branch, Any Handler May Import Any Handler[/yellow]",
        "  Inside a branch, any handler may import any handler; across branches, only the front door.",
        "  [green]✓[/green] [dim]from aipass.sentry.apps.handlers.bypass.utils import is_bypassed[/dim]",
        "  [green]✓[/green] [dim]from ..bypass.utils import is_bypassed[/dim]",
        "",
        "[yellow]RULE 3: Entry Points Don't Import Handlers[/yellow]",
        "  Main entry points (branch.py) use modules, not handlers directly.",
        "  [red]✗[/red] [dim]from aipass.api.apps.handlers.openrouter.client import get_response[/dim]",
        "  [green]✓[/green] [dim]from aipass.api import load_config[/dim]  (the front door)",
        "",
        f"[dim]{sep}[/dim]",
        "[bold cyan]HANDLERS AN ENTRY POINT MAY IMPORT:[/bold cyan]",
        "  [green]✓[/green] json_handler  - Default JSON operations",
        "  [green]✓[/green] file_handler  - Default file operations",
        "  [green]✓[/green] Same-package relative imports (from .X import Y)",
        "",
        "[yellow]The package top file types its door names from their homes:[/yellow]",
        "  In src/aipass/<branch>/__init__.py, own-handler imports inside a top-level",
        "  if TYPE_CHECKING: block are acquitted; nothing loads at runtime.",
        "  [red]✗[/red] A runtime handler import there (it breaks the door's laziness).",
        "  [red]✗[/red] Another branch's handlers, or a TYPE_CHECKING block in any other file.",
        "",
        f"[dim]{sep}[/dim]",
        "[bold cyan]EXCEPTIONS:[/bold cyan]",
        "",
        "[yellow]Service Branches use their doors too:[/yellow]",
        "  [green]✓[/green] [dim]from aipass.prax import logger[/dim]",
        "  [green]✓[/green] [dim]from aipass.cli import console, header, success, error[/dim]",
        "  Their long paths under apps/ are front_door findings like any other.",
        "",
        "[yellow]No branch is an exception:[/yellow]",
        "  Trigger reaches other branches through their front doors like every branch.",
        "  A case a door cannot serve gets its own scoped bypass row with its reason.",
        "",
        f"[dim]{sep}[/dim]",
        "[bold cyan]BYPASS CONFIGURATION:[/bold cyan]",
        "  File: [dim].sentry/bypass.json[/dim]",
        "  Fields: file, standard, lines (optional), reason",
        "  Line-specific bypasses supported for granular control.",
        f"[dim]{sep}[/dim]",
    ]
    json_handler.log_operation("standard_content_queried", {"standard": "encapsulation"})
    return "\n".join(lines)
