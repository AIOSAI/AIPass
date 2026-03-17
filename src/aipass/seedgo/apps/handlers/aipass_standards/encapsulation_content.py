# =================== AIPass ====================
# Name: encapsulation_content.py
# Description: Encapsulation Standards Content Handler
# Version: 1.0.0
# Created: 2026-03-09
# Modified: 2026-03-09
# =============================================

"""
Encapsulation Standards Content Handler

Provides formatted encapsulation standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_encapsulation_standards() -> str:
    """Return formatted encapsulation standards content with Rich markup."""
    sep = "─" * 70
    lines = [
        f"[dim]{sep}[/dim]",
        "[bold red]ENCAPSULATION STANDARDS[/bold red]",
        "[dim]Handlers are implementation details. Modules are the public API.[/dim]",
        f"[dim]{sep}[/dim]",
        "",
        "[bold cyan]WHY IT MATTERS:[/bold cyan]",
        "  Cross-branch handler imports create tight coupling.",
        "  Modules provide stable entry points that evolve without breaking callers.",
        "",
        f"[dim]{sep}[/dim]",
        "[bold cyan]THE THREE RULES:[/bold cyan]",
        "",
        "[yellow]RULE 1: No Cross-Branch Handler Imports[/yellow]",
        "  [red]✗[/red] [dim]from aipass.flow.apps.handlers.plan.validator import validate_plan[/dim]",
        "  [green]✓[/green] [dim]from aipass.flow.apps.modules.plan_validator import validate_plan[/dim]",
        "",
        "[yellow]RULE 2: No Cross-Package Handler Imports[/yellow]",
        "  Handlers must not import other handler packages within the same branch.",
        "  [red]✗[/red] [dim]from aipass.seedgo.apps.handlers.error.formatter import format_error[/dim]",
        "  [green]✓[/green] [dim]from aipass.seedgo.apps.modules.error_handler import format_error[/dim]",
        "  [green]✓[/green] [dim]from .validator import X[/dim]  (same-package relative OK)",
        "",
        "[yellow]RULE 3: Entry Points Don't Import Handlers[/yellow]",
        "  Main entry points (branch.py) use modules, not handlers directly.",
        "  [red]✗[/red] [dim]from aipass.api.apps.handlers.openrouter.client import get_response[/dim]",
        "  [green]✓[/green] [dim]from aipass.api.apps.modules.openrouter_client import get_response[/dim]",
        "",
        f"[dim]{sep}[/dim]",
        "[bold cyan]ALLOWED HANDLER IMPORTS:[/bold cyan]",
        "  [green]✓[/green] json_handler  - Default JSON operations",
        "  [green]✓[/green] file_handler  - Default file operations",
        "  [green]✓[/green] Same-package relative imports (from .X import Y)",
        "",
        f"[dim]{sep}[/dim]",
        "[bold cyan]EXCEPTIONS:[/bold cyan]",
        "",
        "[yellow]Service Branches (module imports allowed everywhere):[/yellow]",
        "  [green]✓[/green] [dim]from aipass.prax.apps.modules.logger import system_logger as logger[/dim]",
        "  [green]✓[/green] [dim]from aipass.cli.apps.modules import console, header, success, error[/dim]",
        "  Note: These are MODULE imports, not handler imports.",
        "",
        "[yellow]Trigger Branch (cross-branch handler imports allowed):[/yellow]",
        "  Trigger centralizes cross-branch reaction logic.",
        "  Configure bypass in [dim].seedgo/bypass.json[/dim]:",
        '  [dim]{"bypass": [{"file": "...", "standard": "encapsulation", "reason": "..."}]}[/dim]',
        "",
        f"[dim]{sep}[/dim]",
        "[bold cyan]BYPASS CONFIGURATION:[/bold cyan]",
        "  File: [dim].seedgo/bypass.json[/dim]",
        "  Fields: file, standard, lines (optional), reason",
        "  Line-specific bypasses supported for granular control.",
        f"[dim]{sep}[/dim]",
    ]
    json_handler.log_operation("standard_content_queried", {"standard": "encapsulation"})
    return "\n".join(lines)
