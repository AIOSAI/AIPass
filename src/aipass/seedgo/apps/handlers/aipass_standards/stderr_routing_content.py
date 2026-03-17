# =================== AIPass ====================
# Name: stderr_routing_content.py
# Description: Stderr Routing Standards Content Handler
# Version: 1.0.0
# Created: 2026-03-13
# Modified: 2026-03-13
# =============================================

"""
Stderr Routing Standards Content Handler

Provides formatted stderr routing standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_stderr_routing_standards() -> str:
    """Return formatted stderr routing standards content with Rich markup."""
    lines = [
        "[bold red]STDERR ROUTING STANDARD[/bold red]",
        "",
        "[yellow]POLICY:[/yellow] Error and warning output MUST route to stderr",
        "via CLI display functions. Normal output stays on stdout.",
        "",
        "[bold cyan]WHY:[/bold cyan]",
        "  CLI display.py has [dim]err_console = Console(stderr=True)[/dim].",
        "  [dim]error()[/dim], [dim]warning()[/dim], and [dim]fatal()[/dim] route through it.",
        "  Branches using [dim]console.print('[red]Error...[/red]')[/dim] bypass this",
        "  and send errors to stdout, breaking piping and redirection.",
        "",
        "\u2500" * 70,
        "",
        "[bold cyan]CORRECT PATTERN:[/bold cyan]",
        "  [dim]from aipass.cli.apps.modules import error, warning, fatal[/dim]",
        "",
        "  [green]\u2713[/green] [dim]error('Branch not found', suggestion='Check spelling')[/dim]",
        "  [green]\u2713[/green] [dim]warning('Template mismatch', details='Expected v2')[/dim]",
        "  [green]\u2713[/green] [dim]fatal('Config missing')  # stderr + sys.exit(1)[/dim]",
        "",
        "[bold cyan]WRONG PATTERN:[/bold cyan]",
        "  [red]\u2717[/red] [dim]console.print('[red]Error: Branch not found[/red]')[/dim]",
        "  [red]\u2717[/red] [dim]console.print('[yellow]Warning: mismatch[/yellow]')[/dim]",
        "  [red]\u2717[/red] [dim]Console(stderr=True)  # Don't create your own[/dim]",
        "",
        "\u2500" * 70,
        "",
        "[bold cyan]WHAT THE CHECKER CATCHES:[/bold cyan]",
        "  1. [dim]console.print()[/dim] with [red][red]/[bold red][/red] markup",
        "     \u2192 Should use [dim]error()[/dim] or [dim]fatal()[/dim]",
        "  2. [dim]console.print()[/dim] with [yellow][yellow]/[bold yellow][/yellow] markup",
        "     \u2192 Should use [dim]warning()[/dim]",
        "  3. Custom [dim]Console(stderr=True)[/dim] creation",
        "     \u2192 Import [dim]err_console[/dim] from CLI instead",
        "",
        "[bold cyan]CLI DISPLAY EXPORTS:[/bold cyan]",
        "  [dim]from aipass.cli.apps.modules import ([/dim]",
        "  [dim]    error,        # \u2718 message + optional suggestion \u2192 stderr[/dim]",
        "  [dim]    warning,      # \u26a0 message + optional details \u2192 stderr[/dim]",
        "  [dim]    fatal,        # \u2718 message + sys.exit(1) \u2192 stderr[/dim]",
        "  [dim]    err_console,  # Raw stderr Console (rare, prefer functions)[/dim]",
        "  [dim])[/dim]",
        "",
        "[bold cyan]SCOPE:[/bold cyan]",
        "  All branches except CLI (which defines these functions).",
        "  Handlers are exempt from CLI output standards (separate concern).",
        "",
        "[bold cyan]REFERENCE:[/bold cyan]",
        "  [dim]See: src/aipass/cli/apps/modules/display.py (error, warning, fatal)[/dim]",
        "  [dim]See: FPLAN-0032 (Phase 1+2: CLI stderr standardization)[/dim]",
        "  [dim]See: FPLAN-0033 (Phase 3: branch migration — gates on this standard)[/dim]",
    ]

    json_handler.log_operation("standard_content_queried", {"standard": "stderr_routing"})
    return "\n".join(lines)
