# =================== AIPass ====================
# Name: cli_ux_content.py
# Description: CLI UX Standards Content Handler
# Version: 1.1.0
# Created: 2026-07-17
# Modified: 2026-10-18
# =============================================

"""
CLI UX Standards Content Handler

Provides formatted CLI UX standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_cli_ux_standards() -> str:
    """Return formatted CLI UX standards content with Rich markup.

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold red]CLI UX STANDARD[/bold red]",
        "",
        "[bold cyan]CORE RULE:[/bold cyan] Entry points must follow the AIPass house pattern",
        "",
        "[yellow]RULE:[/yellow] Every branch entry point (apps/{branch}.py) must provide",
        "  a two-tier help surface: print_introspection() for bare invocation and",
        "  print_help() for --help, both using Rich console.print() from aipass.cli.",
        "",
        "=" * 70,
        "",
        "[bold cyan]THE HOUSE PATTERN:[/bold cyan]",
        "",
        "  [green]1.[/green] [bold]Two-tier help[/bold] -- print_introspection() (light) + print_help() (full)",
        "  [green]2.[/green] [bold]Rich console[/bold] -- console.print() with markup, never bare print()",
        "  [green]3.[/green] [bold]Title + purpose[/bold] -- styled title line + dim tagline in introspection",
        "  [green]4.[/green] [bold]Closing pointer[/bold] -- introspection ends with --help reference",
        "  [green]5.[/green] [bold]Usage + examples[/bold] -- print_help() includes USAGE and EXAMPLES sections",
        "  [green]6.[/green] [bold]No internal leaks[/bold] -- modules/ must not expose internal plumbing",
        "",
        "=" * 70,
        "",
        "[bold cyan]WHAT IS CHECKED:[/bold cyan]",
        "",
        "  [yellow]Scope:[/yellow] entry_point -- only apps/{branch}.py files",
        "",
        "  [yellow]Check 1:[/yellow] two_tier_help",
        "    Both print_introspection() and print_help() defined as top-level functions",
        "",
        "  [yellow]Check 2:[/yellow] rich_console",
        "    Help functions use console.print(), no bare print() calls",
        "",
        "  [yellow]Check 3:[/yellow] title_markup",
        "    print_introspection() contains a [bold]-styled title line",
        "",
        "  [yellow]Check 4:[/yellow] purpose_line",
        "    print_introspection() contains a [dim]-styled purpose/tagline",
        "",
        "  [yellow]Check 5:[/yellow] help_pointer",
        "    print_introspection() references --help for more info",
        "",
        "  [yellow]Check 6:[/yellow] usage_section",
        "    print_help() contains a Usage section",
        "",
        "  [yellow]Check 7:[/yellow] examples_section",
        "    print_help() prints a heading that starts with Examples (a docstring does not count)",
        "",
        "  [yellow]Check 8:[/yellow] no_internal_modules",
        "    modules/ directory does not expose internal plumbing names",
        "",
        "=" * 70,
        "",
        "[bold cyan]GOOD EXAMPLE (flow.py introspection):[/bold cyan]",
        "",
        '  console.print("[bold cyan]Flow - PLAN Management System[/bold cyan]")',
        '  console.print("[dim]Task orchestration and workflow management[/dim]")',
        "  # ... module list ...",
        "  console.print(\"[dim]Run 'drone @flow --help' for usage information[/dim]\")",
        "",
        "[bold cyan]BAD EXAMPLE (aipass.py -- fails all checks):[/bold cyan]",
        "",
        '  print(f"AIPASS - {len(modules)} modules discovered")  # bare print',
        "  # no print_introspection/print_help, no title/purpose, no pointer",
        "",
        "=" * 70,
        "",
        "[bold cyan]HOW TO FIX:[/bold cyan]",
        "",
        "  1. Define print_introspection() with: styled title, dim purpose, module list, --help pointer",
        "  2. Define print_help() with: USAGE section, command list, EXAMPLES section",
        "  3. Replace all bare print() with console.print() from aipass.cli",
        "  4. Prefix internal modules with underscore or set COMMAND attribute",
        "",
        "=" * 70,
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  Score = (passed_checks / 8) * 100",
        "  Pass requires all 8 checks green",
        "",
        "[bold cyan]REFERENCE:[/bold cyan]",
        "  [dim]See: seedgo standards pack (cli_ux)[/dim]",
        "  [dim]Compare: drone @flow (good) vs aipass --help (bad)[/dim]",
    ]

    json_handler.log_operation("standard_content_queried", {"standard": "cli_ux"})
    return "\n".join(lines)
