# =================== AIPass ====================
# Name: handlers_content.py
# Description: Handlers Content
# Version: 1.0.0
# Created: 2026-03-05
# Modified: 2026-03-05
# =============================================

import sys
from pathlib import Path

"""
Handlers Standards Content Handler

Provides formatted handlers standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler

def get_handlers_standards() -> str:
    """Return formatted handlers standards content with Rich markup

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE:[/bold cyan]",
        "  [yellow]Handlers are internal to their branch[/yellow]",
        "  • Same-branch handler imports: ALLOWED (even across packages)",
        "  • Cross-branch handler imports: BLOCKED (use modules instead)",
        "  • Future marketplace: grab handler → drop it in → works",
        "",
        "[bold cyan]KEY RULES:[/bold cyan]",
        "",
        "[bold]1. File Size Guidelines[/bold]",
        "  • [green]<300 lines:[/green] Ideal - AI quick scan, full comprehension",
        "  • [yellow]300-700 lines:[/yellow] Acceptable - still manageable",
        "  • [red]700+ lines:[/red] Consider splitting (unless cohesive domain)",
        "",
        "  Real examples:",
        "  • [dim]json_handler.py: 279-356 lines (perfect)[/dim]",
        "  • [dim]file_ops.py: 845-981 lines (heavy but cohesive)[/dim]",
        "",
        "[bold]2. Independence Rules (No Circular Dependencies)[/bold]",
        "  [green]✓ ALLOWED[/green] - Handler imports handler (same branch):",
        "  [dim]  # seedgo/apps/handlers/standards/check.py[/dim]",
        "  [dim]  from aipass.seedgo.apps.handlers.json import json_handler  # OK[/dim]",
        "",
        "  [red]✗ FORBIDDEN[/red] - Handler imports own-branch modules:",
        "  [dim]  # seedgo/apps/handlers/json/json_handler.py[/dim]",
        "  [dim]  from aipass.seedgo.apps.modules.create import something  # NO[/dim]",
        "",
        "  [yellow]Why?[/yellow] Modules import handlers. If handlers import modules → cycle.",
        "",
        "[bold]3. Handler Boundaries (External Access)[/bold]",
        "  Handlers are [red]INTERNAL[/red] to their branch.",
        "  External consumers use [green]MODULES[/green] as the public API.",
        "",
        "  [green]✓ Same-branch imports:[/green] ALLOWED",
        "  [dim]  # flow/apps/handlers/plan/create.py[/dim]",
        "  [dim]  from aipass.flow.apps.handlers.registry.load import load_registry  # OK[/dim]",
        "",
        "  [red]✗ Cross-branch imports:[/red] BLOCKED (security guard)",
        "  [dim]  # flow/apps/modules/list_plans.py[/dim]",
        "  [dim]  from aipass.prax.apps.handlers.logging.setup import get_logger  # BLOCKED[/dim]",
        "",
        "  [green]✓ Correct pattern:[/green] Import the MODULE (public API)",
        "  [dim]  from aipass.prax.apps.modules.logger import system_logger as logger  # OK[/dim]",
        "",
        "  [yellow]Special Note - Drone Architecture:[/yellow]",
        "  • Drone is [red]NOT imported[/red] by branches",
        "  • Drone resolves @ symbols [yellow]before[/yellow] routing",
        "  • Branches receive [green]resolved paths[/green], never @ symbols",
        "  • [dim]Example: @flow/plans → src/aipass/flow/plans[/dim]",
        "",
        "  Security guard location: [dim]handlers/__init__.py[/dim]",
        "  Reference impl: [dim]src/aipass/prax/apps/handlers/__init__.py[/dim]",
        "",
        "[bold]4. Domain Organization[/bold]",
        "  Organize by [yellow]business purpose[/yellow], not technical role:",
        "  [dim]handlers/[/dim]",
        "  [dim]  json/         → All JSON operations[/dim]",
        "  [dim]  error/        → All error handling[/dim]",
        "  [dim]  cli/          → All user interaction[/dim]",
        "  [dim]  branch/       → All branch lifecycle[/dim]",
        "  [dim]  standards/    → All standards checking[/dim]",
        "",
        "[bold cyan]AUTO-DETECTION PATTERN:[/bold cyan]",
        "  Handlers detect caller using [bold]inspect.stack()[/bold]:",
        "",
        "  [dim]import inspect[/dim]",
        "  [dim]def _get_caller_module_name() -> str:[/dim]",
        "  [dim]    stack = inspect.stack()[/dim]",
        "  [dim]    return stack[2].filename.stem  # Auto-detect[/dim]",
        "",
        "  [dim]def handler_function(data, module_name: str | None = None):[/dim]",
        "  [dim]    if module_name is None:[/dim]",
        "  [dim]        module_name = _get_caller_module_name()[/dim]",
        "",
        "  Modules just import and use - no boilerplate!",
        "",
        "[bold cyan]DEFAULT HANDLERS:[/bold cyan]",
        "  [yellow]json_handler.py[/yellow] - JSON operations (comes with every branch)",
        "  • Auto-creates config/data/log JSON files",
        "  • Self-healing when files corrupted",
        "  • Auto-detects calling module",
        "  • Standard across all branches",
        "  • [green]3-tier compliant[/green] - raises exceptions, modules log",
        "",
        "  [dim]from aipass.seedgo.apps.handlers.json import json_handler[/dim]",
        "  [dim]json_handler.log_operation('operation', data)[/dim]",
        "",
        "[bold cyan]KEY WARNINGS:[/bold cyan]",
        "  [red]✗[/red] Don't break independence - kills marketplace transportability",
        "  [red]✗[/red] Don't create 2000+ line god objects - AI comprehension fails",
        "  [red]✗[/red] Don't use technical organization (utils/, helpers/) - use domains",
        "",
        "[bold cyan]REFERENCE:[/bold cyan]",
        "  [dim]See: seedgo standards pack (handlers)[/dim]",
        "",
        "─" * 70,
    ]

    json_handler.log_operation("standard_content_queried", {"standard": "handlers"})
    return "\n".join(lines)
