# =================== AIPass ====================
# Name: meta_content.py
# Description: Meta Standards Content Handler
# Version: 1.0.0
# Created: 2026-03-09
# Modified: 2026-03-09
# =============================================

"""
Meta Standards Content Handler

Provides formatted meta standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_meta_standards() -> str:
    """Return formatted meta standards content with Rich markup.

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold red]META BLOCK STANDARD[/bold red]",
        "",
        "[bold cyan]CORE PRINCIPLE:[/bold cyan] Identity at the Top",
        "",
        "[yellow]RULE:[/yellow] Every Python file starts with a META block on line 1",
        "  META is the file's passport — name, purpose, version, timestamps.",
        "  No docstrings, no imports, no blank lines above it.",
        "",
        "─" * 70,
        "",
        "[bold cyan]REQUIRED FORMAT:[/bold cyan]",
        "",
        "  [dim]# =================== AIPass ====================[/dim]",
        "  [dim]# Name: filename.py[/dim]",
        "  [dim]# Description: Brief description of the file[/dim]",
        "  [dim]# Version: X.Y.Z[/dim]",
        "  [dim]# Created: YYYY-MM-DD[/dim]",
        "  [dim]# Modified: YYYY-MM-DD[/dim]",
        "  [dim]# =============================================[/dim]",
        "",
        "─" * 70,
        "",
        "[bold cyan]REQUIRED FIELDS:[/bold cyan]",
        "",
        "  [yellow]Name:[/yellow]        Must match actual filename on disk (e.g. router.py)",
        "  [yellow]Description:[/yellow] At least one word after the colon",
        "  [yellow]Version:[/yellow]     Semantic versioning — X.Y.Z (three integers)",
        "  [yellow]Created:[/yellow]     ISO date — YYYY-MM-DD (set once, never changed)",
        "  [yellow]Modified:[/yellow]    ISO date — YYYY-MM-DD (updated on every edit)",
        "",
        "─" * 70,
        "",
        "[bold cyan]PLACEMENT:[/bold cyan]",
        "",
        "  [yellow]RULE:[/yellow] META block header MUST be line 1 of the file",
        "  All code, docstrings, and imports go below the block.",
        "",
        "[bold]Good:[/bold]",
        "  [green]✓[/green] [dim]# =================== AIPass ====================[/dim]",
        "  [green]✓[/green] [dim]# Name: router.py[/dim]",
        "  [green]✓[/green] [dim]# Description: Command routing for drone[/dim]",
        "  [green]✓[/green] [dim]# Version: 2.1.0[/dim]",
        "  [green]✓[/green] [dim]# Created: 2025-10-15[/dim]",
        "  [green]✓[/green] [dim]# Modified: 2026-03-01[/dim]",
        "  [green]✓[/green] [dim]# =============================================[/dim]",
        "  [green]✓[/green] [dim](docstring and imports follow)[/dim]",
        "",
        "[bold]Bad:[/bold]",
        '  [red]✗[/red] [dim]"""Docstring first"""[/dim]  ← pushes META off line 1',
        "  [red]✗[/red] [dim]# Name: wrong_name.py[/dim]  ← doesn't match actual filename",
        "  [red]✗[/red] [dim]# Version: 1.0[/dim]          ← missing patch number (need X.Y.Z)",
        "  [red]✗[/red] [dim]# Created: March 2026[/dim]   ← wrong date format (need YYYY-MM-DD)",
        "",
        "─" * 70,
        "",
        "[bold cyan]HEADER MARKERS:[/bold cyan]",
        "",
        "  [green]✓[/green] Canonical: [dim]# =================== AIPass ====================[/dim]",
        "  [green]✓[/green] Legacy:    [dim]# =================== META ====================[/dim]",
        "  New files MUST use the AIPass header. Legacy is tolerated.",
        "",
        "─" * 70,
        "",
        "[bold cyan]EXCEPTIONS:[/bold cyan]",
        "",
        "  [yellow]__init__.py[/yellow] files are skipped — structural, not functional.",
        "  Files listed in [dim].seedgo/bypass.json[/dim] receive automatic 100%.",
        "",
        "─" * 70,
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "",
        "  7 checks: presence, placement, Name, Description, Version, Created, Modified",
        "  Pass threshold: 75% (at least 6 of 7 checks)",
        "  Score = (passed_checks / total_checks) * 100",
        "",
        "─" * 70,
        "",
        "[bold cyan]KEY WARNINGS:[/bold cyan]",
        "  [yellow]⚠[/yellow]  META is mandatory on all .py files (except __init__.py)",
        "  [yellow]⚠[/yellow]  Name field MUST match filename — mismatches are a failure",
        "  [yellow]⚠[/yellow]  Update Modified date on every meaningful change",
        "",
        "[bold cyan]REFERENCE:[/bold cyan]",
        "  [dim]See: seedgo standards pack (meta)[/dim]",
    ]

    json_handler.log_operation("standard_content_queried", {"standard": "meta"})
    return "\n".join(lines)
