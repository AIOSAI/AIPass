# =================== AIPass ====================
# Name: declared_pass_symbol_resolves_content.py
# Description: Declared Pass Symbol Resolves Standards Content Handler
# Version: 1.0.0
# Created: 2026-09-25
# Modified: 2026-09-25
# =============================================

"""
Declared Pass Symbol Resolves Standards Content Handler

Provides formatted Declared Pass Symbol Resolves standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_declared_pass_symbol_resolves_standards() -> str:
    """Return formatted declared_pass_symbol_resolves standards content with Rich markup

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE (test template v1 item 7, the WRONG-SYMBOL shape):[/bold cyan]",
        "  Every name a declared pass mentions has to resolve -- in the branch's apps/,",
        "  or on a (stdlib) line to a real stdlib name the product uses. A line whose",
        "  names resolve nowhere is a declared pass on nothing. H1 and H2 stay with",
        "  declared_pass_contradiction; a bare UPPER or snake_case name is H2's.",
        "",
        "[bold cyan]WHAT IS A NAME:[/bold cyan]",
        "  dotted [green]os.path.getsize[/green], called [green]resolve()[/green], private [green]_project[/green],",
        "  CamelCase [green]MagicMock[/green], a path [green]handlers/readme/[/green]. Plain words are not;",
        "  [yellow]production/tests[/yellow] is prose for 'production or tests'. On a (stdlib) line an",
        "  importable module word ([green]shutil[/green], [red]pathspec[/red]) is a name too.",
        "",
        "[bold cyan]WHAT RESOLVES:[/bold cyan]",
        "  A stdlib name: the chain is real AND the product uses it ([red]os.scandir[/red]: @backup",
        "  never calls it). Anything else: its last segment is a word in apps/ source text.",
        "  A path: apps/ has that directory or module.",
        "",
        "[bold cyan]A LINE THAT NAMES NOTHING:[/bold cyan]",
        "  Its own finding -- unless its category is a standard in this pack (ruff,",
        "  documentation, cli): then it points at the checker that covers it.",
        "  [red]constant -- dryrun mode and file size thresholds[/red] names nothing at all.",
        "",
        "[bold cyan]CHECK FIRST (2026-09-25):[/bold cyan]",
        "  40 files declare a pass. [red]10 convicted, 12 hits[/red] -- backup 9, trigger 1,",
        "  seedgo 0. The model file passes.",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  SCORED, per file. Every hit on ONE check.",
        "",
        "[bold cyan]THE CURE:[/bold cyan]",
        "  [green]Name the symbol the product has, or drop the line.[/green]",
    ]

    json_handler.log_operation("content_served", {"standard": "declared_pass_symbol_resolves"})
    return "\n".join(lines)
