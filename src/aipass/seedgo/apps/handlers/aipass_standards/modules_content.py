# =================== AIPass ====================
# Name: modules_content.py
# Description: Modules Standards Content Handler
# Version: 1.0.0
# Created: 2026-03-05
# Modified: 2026-03-05
# =============================================

"""
Modules Standards Content Handler

Provides formatted module standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler

def get_modules_standards() -> str:
    """Return formatted module standards content with Rich markup

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE:[/bold cyan]",
        "  [bold]Modules orchestrate, handlers implement[/bold]",
        "",
        "  • Modules coordinate workflows by calling handlers in sequence",
        "  • Modules are thin (orchestration), handlers are thick (business logic)",
        "  • Dependencies flow one way: Modules → Handlers (never reverse)",
        "",
        "[yellow]RULE:[/yellow] Modules delegate to handlers, never implement business logic",
        "",
        "[bold cyan]KEY PATTERNS:[/bold cyan]",
        "",
        "[bold]1. handle_command() Entry Point[/bold]",
        "  [dim]def handle_command(command: str, args: List[str]) -> bool:[/dim]",
        "  • Check if command matches module's commands",
        "  • Log operation: [dim]json_handler.log_operation()[/dim]",
        "  • Execute workflow (delegate to handlers)",
        "  • Return [green]True[/green] if handled, [red]False[/red] otherwise",
        "",
        "[bold]2. Import Many Handlers (20+ is fine)[/bold]",
        "  [green]✓[/green] Modules CAN import handlers",
        "  [green]✓[/green] Modules CAN import services (Prax, CLI)",
        "  [red]✗[/red] Modules CANNOT import other modules",
        "  [red]✗[/red] Handlers CANNOT import modules",
        "",
        "[bold]3. Orchestrate, Don't Implement[/bold]",
        "  [dim]# ❌ BAD - business logic in module[/dim]",
        "  [dim]branch_path.mkdir(parents=True, exist_ok=True)[/dim]",
        "  [dim]config = {...}[/dim]",
        "  [dim]with open(config_file, 'w') as f:[/dim]",
        "",
        "  [dim]# ✅ GOOD - orchestrate handler calls[/dim]",
        "  [dim]validate_branch_name(name)[/dim]",
        "  [dim]create_branch_structure(name, template)[/dim]",
        "  [dim]initialize_branch_config(name)[/dim]",
        "",
        "[bold]4. File Size Guidelines[/bold]",
        "  • 110-135 lines: Simple modules (single operation)",
        "  • 135-155 lines: Standard modules (multiple operations)",
        "  • 250-300 lines: Complex modules (batch operations, examples)",
        "  • 400+ lines: Consider splitting by domain",
        "",
        "[bold cyan]ESSENTIAL IMPORTS:[/bold cyan]",
        "  [dim]from aipass.prax.apps.modules.logger import system_logger as logger[/dim]",
        "  [dim]from aipass.cli.apps.modules"
        " import console, header, success, error[/dim]",
        "  [dim]from aipass.seedgo.apps.handlers.json import json_handler[/dim]",
        "",
        "[bold cyan]WARNINGS:[/bold cyan]",
        "  • NEVER use [dim]logger.debug()[/dim] - use [dim]logger.info()[/dim] only",
        "  • Module business logic = code smell (move to handlers)",
        "  • Heavy file operations belong in handlers, not modules",
        "",
        "[bold cyan]DEMONSTRATION:[/bold cyan]",
        "  [dim]src/aipass/seedgo/apps/standards/aipass/modules/cli_standard.py[/dim] (reference example)",
        "  [dim]src/aipass/seedgo/apps/standards/aipass/modules/ (all standard modules)[/dim]",
        "",
        "[bold cyan]REFERENCE:[/bold cyan]",
        "  [dim]See: seedgo standards pack (modules)[/dim]",
    ]

    json_handler.log_operation("standard_content_queried", {"standard": "modules"})
    return "\n".join(lines)
