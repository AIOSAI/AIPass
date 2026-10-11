# =================== AIPass ====================
# Name: subcommand_help_content.py
# Description: Subcommand Help Standards Content
# Version: 2.0.0
# Created: 2026-07-10
# Modified: 2026-09-20
# =============================================

"""Subcommand Help Standards Content.

Provides Rich-formatted reference text for the subcommand help standard.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_subcommand_help_standards() -> str:
    """Return Rich-formatted subcommand help standards text."""
    json_handler.log_operation("standard_content_queried", {"standard": "subcommand_help"})
    return """[bold white]SUBCOMMAND HELP STANDARD[/bold white]

[yellow]PURPOSE:[/yellow]
  Every branch entry point must handle [bold]<cmd> --help[/bold] by showing
  that subcommand's help — never execute the command, never silently
  fall back to top-level help.

[yellow]THE CONTRACT:[/yellow]

  [dim]drone @branch cmd --help[/dim]   →  shows cmd-specific help
  [dim]drone @branch cmd --help[/dim]   ✗  executes cmd (side-effect risk)
  [dim]drone @branch cmd --help[/dim]   ✗  shows top-level help (unhelpful)

[yellow]CANONICAL PATTERN (module-discovery branches):[/yellow]

  [dim]command = args[0][/dim]
  [dim]remaining = args[1:][/dim]

  [bold cyan]# Subcommand --help guard (REQUIRED)[/bold cyan]
  [dim]if remaining and remaining[0] in ["--help", "-h"]:[/dim]
  [dim]    for module in modules:[/dim]
  [dim]        if module.handle_command(command, ["--help"]):[/dim]
  [dim]            return 0[/dim]
  [dim]    print_help()  # fallback to top-level[/dim]
  [dim]    return 0[/dim]

  [dim]# Normal dispatch (only reached if NOT --help)[/dim]
  [dim]if route_command(command, remaining, modules):[/dim]
  [dim]    return 0[/dim]

[yellow]ALTERNATIVE PATTERNS (also accepted):[/yellow]

  [bold cyan]argparse with parse_known_args:[/bold cyan]
  [dim]parser.add_argument("--help", action="store_true", dest="show_help")[/dim]
  [dim]parsed, remaining = parser.parse_known_args()[/dim]
  [dim]if parsed.show_help:[/dim]
  [dim]    all_args = ["--help"] + all_args  # pass to handler[/dim]

  [bold cyan]Post-dispatch fallback:[/bold cyan]
  [dim]if not route_command(command, remaining, modules):[/dim]
  [dim]    if remaining and remaining[0] in ["--help", "-h"]:[/dim]
  [dim]        print_module_help(command, modules)[/dim]

[yellow]WHAT RULE 1 DETECTS (the guard, entry points):[/yellow]

  [green]✓[/green] A [bold]--help[/bold] comparison on remaining/subcommand args (not args[0])
  [green]✓[/green] argparse [bold]parse_known_args()[/bold] call (absorbs --help)
  [red]✗[/red] Only top-level --help check (args[0] in ["--help", ...])
  [red]✗[/red] No --help handling at all

[yellow]RULE 2 — PER-VERB HELP MUST BE REACHABLE (any module):[/yellow]

  Intercepting [bold]--help[/bold] is not the same as ANSWERING it. A module can
  hold a paragraph per verb and still hand back the index, and rule 1
  scores that 100 — correctly, by its own terms.

  [bold cyan]THE VIOLATION (drone fc032265, live for months):[/bold cyan]
  [dim]def get_help(command=None):        # 19 per-verb paragraphs[/dim]
  [dim]    if command == "commit": ...[/dim]
  [dim]def print_help():                  # takes no verb[/dim]
  [dim]    console.print(get_help())      [/dim][red]← the verb never arrives[/red]

  [bold cyan]THE CURE:[/bold cyan]
  [dim]def print_help(command=None):[/dim]
  [dim]    console.print(get_help(command))[/dim]

  The checker convicts a help-text function that selects content by testing
  its own parameter against [bold]two or more[/bold] string literals when every
  in-module call to it omits that argument. A provider with no call site
  here is left alone — its callers are in another module, and this lane
  cannot read them.

  [bold white]A printer that takes no verb is not a violation.[/bold white] 125 of the
  fleet's 129 help dispatch sites hand their printer nothing, and they are
  right to: there is no per-verb content to reach. The defect is in the
  chain, not at either end.

[yellow]KEY RULES:[/yellow]

  [bold white]Intercept before dispatch[/bold white] — don't let --help reach the handler
  [bold white]Show subcommand help[/bold white] — not top-level help
  [bold white]Never execute[/bold white] — --help must never trigger side effects
  [bold white]Keep per-verb help reachable[/bold white] — per-verb content nothing can
    reach is dead code that reads as a feature
  [bold white]Scope[/bold white] — rule 1 reports on apps/{branch}.py; rule 2 walks every
    production module, because that is where it was found"""
