# =================== AIPass ====================
# Name: through_the_command_content.py
# Description: Through The Command Standards Content Handler
# Version: 1.0.0
# Created: 2026-09-21
# Modified: 2026-09-21
# =============================================

"""
Through The Command Standards Content Handler

Provides formatted Through The Command standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_through_the_command_standards() -> str:
    """Return formatted through_the_command standards content with Rich markup

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE (test template v1, item 10):[/bold cyan]",
        "  A test reaches behaviour the way a [green]user[/green] does -- through the",
        "  module's commands and its public functions. An underscore helper is",
        "  never called directly by a test.",
        "",
        "  [bold]A private helper is not a contract.[/bold] It is the shape the author",
        "  happened to cut the work into this week. A test bolted to it pins that",
        "  shape instead of the behaviour: rename the helper and a green suite goes",
        "  red with nothing user-visible changed; reroute the command past the",
        "  helper and the suite stays green while the product breaks.",
        "",
        "[bold cyan]WHAT IT CHECKS:[/bold cyan]",
        "  Two shapes, both convicted, in files under [dim]tests/[/dim] (conftest included):",
        "",
        "  [bold]a. An import of an underscore name from a product module, any scope[/bold]",
        "  [red]from aipass.seedgo.apps.handlers.audit.audit_display import _format_standard_name[/red]",
        "",
        "  [bold]b. A call or attribute READ of an underscore name on a product base[/bold]",
        "  [red]from aipass.memory.apps.handlers.chroma import chroma_subprocess[/red]",
        "  [red]...[/red]",
        '  [red]assert chroma_subprocess._source_matches(source, "DPLAN-0012")[/red]',
        "",
        "  The base is resolved from [dim]this file's own import bindings[/dim] and nothing",
        "  deeper. A name the file never imported from the product is not the product.",
        "",
        "[bold cyan]NEVER CONVICTED:[/bold cyan]",
        "  [green]Dunder names[/green] -- [dim]__init__[/dim], [dim]__version__[/dim], [dim]__all__[/dim].",
        "  Language surface, not a private helper.",
        "",
        "  [green]Underscore helpers the test file or its conftest defines itself.[/green]",
        "  They are the test's own scaffolding, not the product.",
        "",
        "  [green]An attribute read on a value RETURNED by a product call[/green] --",
        "  [dim]result._x[/dim]. That is dataflow, and this checker does not follow it.",
        "",
        "  [green]A WRITE to a private name[/green] -- [dim]m._cache = {}[/dim],",
        '  [dim]monkeypatch.setattr(m, "_cache", ...)[/dim], [dim]patch("aipass.x._helper")[/dim].',
        "  Those are [bold]item 15[/bold] (mock only at the edge) and a different cure.",
        "",
        "[bold cyan]THE FIX:[/bold cyan]",
        "  [green]Reach it through the command or a public function.[/green] Call the verb",
        "  the user calls, assert on what comes out.",
        "",
        "  If the helper's logic cannot be reached through any command at all, that",
        "  is a [bold]question about the product[/bold] -- an unreachable branch -- not a",
        "  licence to test it directly. Mail @devpulse with the helper.",
        "",
        "[bold cyan]WHY IT EXISTS:[/bold cyan]",
        "  Measured 2026-09-21 over 591 fleet test files: 258 carry at least one",
        "  hit -- 1,114 private imports and 1,336 private helper reaches. Every one",
        "  of them is a test that will survive a product break, or die on a rename.",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  UNSCORED. Test files are not in the audit's corpus, so no branch's",
        "  number moves. The audit reports the standing backlog through the info",
        "  channel; the per-file checklist convicts on the next write of a file.",
    ]

    json_handler.log_operation("content_served", {"standard": "through_the_command"})
    return "\n".join(lines)
