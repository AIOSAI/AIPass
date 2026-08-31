# =================== AIPass ====================
# Name: cli_content.py
# Description: CLI Standards Content Handler
# Version: 1.0.0
# Created: 2026-03-05
# Modified: 2026-03-05
# =============================================

"""
CLI Standards Content Handler

Provides formatted CLI standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_cli_standards() -> str:
    """Return formatted CLI standards content with Rich markup

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold white]OUTPUT STANDARD: Rich console.print() ONLY[/bold white]",
        "",
        "[yellow]POLICY:[/yellow] Rich formatting is THE standard for ALL AIPass output",
        "",
        "[green]✓ Approved:[/green]",
        "  [dim]from aipass.cli.apps.modules import console[/dim]",
        '  [dim]console.print("[cyan]This is the ONLY approved way[/cyan]")[/dim]',
        "",
        "[red]✗ Deprecated:[/red] Bare print() statements",
        "  • Only in test/temp code",
        "  • Remove before commit",
        "",
        "[red]✗ Never use:[/red] parser.print_help() or parser.format_help()",
        "  • Both produce plain argparse text (violates standard)",
        "  • console.print(parser.format_help()) still renders plain text",
        "  • Argparse is for PARSING only, not help output",
        "  • Write custom print_help() with console.print() and Rich markup",
        "",
        "─" * 70,
        "",
        "[bold cyan]DUAL APPROACH:[/bold cyan]",
        "",
        "[bold]1. Interactive (for humans)[/bold]",
        "   • Rich formatting, menus, questionary prompts",
        "   • Visual feedback, colors, progress bars",
        "",
        "[bold]2. Arguments (for AI via Drone)[/bold]",
        "   • Fast, scriptable, no interaction required",
        "   • [dim]drone <module> <command> [options][/dim]",
        "",
        "[yellow]RULE:[/yellow] Build BOTH or neither",
        "",
        "[bold cyan]CLI SERVICE PROVIDER:[/bold cyan]",
        "  [dim]from aipass.cli.apps.modules import console, header, success, error[/dim]",
        "  [dim]from aipass.cli.apps.modules import operation_start, track_operation[/dim]",
        "",
        "  • Consistent formatting across all branches",
        "  • Update CLI once → affects entire system",
        "  • Rich library wrappers for beautiful output",
        "",
        "[bold cyan]BRANCH-LEVEL CLI:[/bold cyan]",
        "  [dim]handlers/cli/prompts.py[/dim] - User interaction specific to branch",
        "",
        "[bold cyan]DRONE COMPLIANCE:[/bold cyan]",
        "  • Module responds to --help flag",
        "  • Help output includes 'Commands:' line",
        "  • Commands comma-separated with flags",
        "  • Example: [dim]Commands: cli, display, --help[/dim]",
        "",
        "[bold cyan]DEMONSTRATION:[/bold cyan]",
        "  [dim]src/aipass/seedgo/apps/standards/aipass/modules/ (standards modules)[/dim]",
        "  Shows CLI service usage with error handling",
        "",
        "[bold cyan]EXEMPTION -- RELAYING A CAPTURED SUBPROCESS STREAM:[/bold cyan]",
        "  sys.stdout.write() is ALLOWED when the argument is a completed",
        "  subprocess's captured stream AND the stream names correspond:",
        "     [green]sys.stdout.write(result.stdout)[/green]      relay -- allowed",
        "     [green]sys.stderr.write(result['stderr'])[/green]   relay -- allowed",
        "     [red]sys.stdout.write('hello')[/red]              your own output -- use Rich",
        "     [red]sys.stdout.write(f'{n} done')[/red]          your own output -- use Rich",
        "     [red]sys.stdout.write(result.stderr)[/red]        CROSSED streams -- a routing bug",
        "     [dim]Why: this rule means route YOUR OWN output through Rich. A router[/dim]",
        "     [dim]relays a child's bytes verbatim, and console.print would interpret[/dim]",
        "     [dim]markup in, wrap and re-style output it never authored.[/dim]",
        "  [yellow]![/yellow]  Keyed on the ARGUMENT, so it cannot be borrowed by writing",
        "     [dim]your own string. Crossed streams stay a violation on purpose.[/dim]",
        "",
        "[bold yellow]EXCEPTION 2 -- the pre-console bootstrap window:[/bold yellow]",
        "  A raw stream write is ALLOWED when it lexically PRECEDES the module's",
        "  own console import. Before that import has run the console does not",
        "  exist, so the rule is unsatisfiable and not merely inconvenient:",
        "     [green]sys.stderr.write('sys.path repair failed')[/green]   line 12 -- before",
        "     [dim]from aipass.cli... import console[/dim]              line 20",
        "     [red]sys.stderr.write('later failure')[/red]             line 40 -- after",
        "  [yellow]![/yellow]  STRICTLY prior. A write sharing the import's own statement",
        "     [dim]comes after it has run, so the console exists and Rich applies.[/dim]",
        "  [dim]Reported by @commons from an entry point's sys.path repair, where[/dim]",
        "  [dim]this rule and silent_catch were mutually unsatisfiable (2026-08-31).[/dim]",
        "",
        "[bold yellow]HANDLERS: the rule reads the STREAM, not the spelling:[/bold yellow]",
        "  Handler separation exists so a handler does not DISPLAY, and display",
        "  is stdout -- the channel a router's output travels on. stderr is where",
        "  a diagnostic goes so it does NOT pollute that channel:",
        "     [green]print(msg, file=sys.stderr)[/green]    a diagnostic -- allowed",
        "     [green]sys.stderr.write(msg)[/green]          the same thing -- always was",
        "     [red]print(msg)[/red]                       display -- use a logger",
        "     [red]print(msg, file=sys.stdout)[/red]      display, said out loud",
        "     [red]print(msg, file=some_handle)[/red]     a write nobody is watching",
        "  [yellow]![/yellow]  Corrected because the checker already passed the write form",
        "     [dim]and failed the print form: same stream, same bytes, 100 points[/dim]",
        "     [dim]apart on nothing but which call the author reached for. Found by[/dim]",
        "     [dim]@flow from the cross-branch import fence -- the one file in a[/dim]",
        "     [dim]branch that runs before any logger exists, being told to use one.[/dim]",
        "",
        "[bold cyan]REFERENCE:[/bold cyan]",
        "  [dim]See: seedgo standards pack (cli)[/dim]",
        "  [dim]See: src/aipass/cli/ (CLI service provider)[/dim]",
        "",
        "─" * 70,
        "",
        "[bold cyan]RICH FORMATTING QUICK REFERENCE:[/bold cyan]",
        "",
        "[bold]Colors:[/bold]",
        "  [red]red[/red], [green]green[/green], [yellow]yellow[/yellow],"
        " [blue]blue[/blue], [cyan]cyan[/cyan], [magenta]magenta[/magenta]",
        "",
        "[bold]Styles:[/bold]",
        "  [bold]bold[/bold], [italic]italic[/italic], [dim]dim[/dim], [underline]underline[/underline]",
        "",
        "[bold]Combined:[/bold]",
        "  [bold red]bold red[/bold red], [bold cyan]bold cyan[/bold cyan], [dim yellow]dim yellow[/dim yellow]",
        "",
        "[bold]Usage:[/bold]",
        '  [dim]console.print("[bold green]Success![/bold green]")[/dim]',
        '  [dim]console.print("[yellow]Note:[/yellow] Check this")[/dim]',
        '  [dim]console.print("[dim]Additional info...[/dim]")[/dim]',
        "",
        "[bold]Emojis:[/bold]",
        "  ✅ Success   ❌ Error   ⚠️  Warning   ℹ️  Info",
        "  ⚙️  Processing   📝 Note   🔍 Search   ✨ Feature",
        "",
        "[bold]Documentation:[/bold]",
        "  [link=https://rich.readthedocs.io/en/stable/markup.html]https://rich.readthedocs.io/en/stable/markup.html[/link]",
    ]

    json_handler.log_operation("standard_content_queried", {"standard": "cli"})
    return "\n".join(lines)
