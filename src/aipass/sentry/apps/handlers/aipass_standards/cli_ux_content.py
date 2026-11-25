# =================== AIPass ====================
# Name: cli_ux_content.py
# Description: CLI UX Standards Content Handler
# Version: 2.0.0
# Created: 2026-07-17
# Modified: 2026-11-25
# =============================================

"""
CLI UX Standards Content Handler

Provides formatted CLI UX standards content.
Module orchestrates, handler implements.
"""

from aipass.sentry.apps.handlers.json import json_handler


def get_cli_ux_standards() -> str:
    """Return formatted CLI UX standards content with Rich markup.

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold red]CLI UX STANDARD[/bold red]",
        "",
        "[bold cyan]CORE RULE:[/bold cyan] Every help surface and every command output looks like one product",
        "",
        "[yellow]RULE:[/yellow] The entry point (apps/{branch}.py) and every module the CLI discovers",
        "  (apps/modules/<name>.py, no leading underscore, defining handle_command) provide a two-tier",
        "  help: print_introspection() for a bare call, print_help() for --help. Every print anywhere in",
        "  apps/ and shared/ keeps its styling deliberate.",
        "",
        "=" * 70,
        "",
        "[bold cyan]WHAT IS CHECKED:[/bold cyan]",
        "",
        "  [yellow]Scope:[/yellow] every production .py; a file with no print and no help function scores nothing",
        "",
        "  [bold]The help tiers[/bold] (entry point and discovered modules):",
        "  [yellow]two_tier_help[/yellow]      both print_introspection() and print_help() at top level",
        "  [yellow]rich_console[/yellow]       help functions use console.print(), never bare print()",
        "  [yellow]title_markup[/yellow]       introspection prints a \\[bold ...] title",
        "  [yellow]purpose_line[/yellow]       introspection prints a \\[dim] purpose line",
        "  [yellow]help_pointer[/yellow]       introspection points at --help",
        "  [yellow]usage_section[/yellow]      print_help() has a Usage section",
        "  [yellow]examples_section[/yellow]   print_help() prints a heading starting with Examples",
        "  [yellow]no_internal_modules[/yellow] (entry point only) modules/ hides _wire/_fix/_impl/_internal plumbing",
        "",
        "  [bold]Every print[/bold] (help surfaces and command output):",
        "  [yellow]markup_kept[/yellow]        no markup=False inside a help function (any function named",
        "                     *help*, *usage*, *introspection*) or on a line holding a style tag",
        "  [yellow]help_styled[/yellow]        a help function styles something: a tag, a style= keyword, header()",
        "  [yellow]heading_styled[/yellow]     a heading (capital at column 0, up to four words, ends with ':')",
        "                     carries a style tag",
        "  [yellow]group_explained[/yellow]    in command output, a heading that opens a list (a loop or an indented",
        "                     item next) has a \\[dim] line, on it or next, saying what the group is",
        "  [yellow]highlight_deliberate[/yellow] an unstyled line shows no number: Rich's highlighter would colour",
        "                     it, so the colour is an accident (digits, len(), a number format, a",
        "                     value named count/total/version/num/score/size)",
        "",
        "=" * 70,
        "",
        "[bold cyan]THE SPELLING:[/bold cyan]",
        "",
        '  console.print("\\[bold cyan]drone\\[/bold cyan] - command routing")',
        '  console.print("\\[dim]Routes @agent commands to their modules\\[/dim]")',
        '  console.print("\\[yellow]Usage:\\[/yellow]")',
        '  console.print(escape("  drone @git log \\[count] \\[path]"))',
        '  console.print("\\[bold]Services:\\[/bold] \\[dim]libraries every branch imports\\[/dim]")',
        '  console.print(f"Found \\[cyan]{len(items)}\\[/cyan] items")',
        '  console.print(f"drone v{VERSION}", highlight=False)',
        "",
        "  [bold]Not:[/bold] console.print(line, markup=False) over a help block - every tag on it prints",
        "  as text and the page looks like another product. escape() the data, keep the line styled.",
        "",
        "=" * 70,
        "",
        "[bold cyan]WHAT IT LEAVES OUT:[/bold cyan]",
        "  - text built elsewhere and printed through a variable: its styling is judged where it is a literal",
        "  - a number inside data the line interpolates under another name ({desc} holding '14s')",
        "  - a heading longer than four words, or one with a ':' inside it: read as prose",
        "  - bare print() outside help functions: debug_print owns that",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  Per file: passed rows / rows judged. The branch score averages the files judged.",
        "",
        "[bold cyan]REFERENCE:[/bold cyan]",
        "  [dim]cli branch: docs/rich_markup.md (escape the data, do not disarm the line)[/dim]",
    ]

    json_handler.log_operation("standard_content_queried", {"standard": "cli_ux"})
    return "\n".join(lines)
