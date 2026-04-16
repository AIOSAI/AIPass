# =================== AIPass ====================
# Name: cli_flags_content.py
# Description: CLI Flags Standards Content
# Version: 1.0.0
# Created: 2026-03-05
# Modified: 2026-03-05
# =============================================

"""
CLI Flags Standards Content

Provides Rich-formatted reference text for the CLI flags standard.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_cli_flags_standards() -> str:
    """Return Rich-formatted CLI flags standards text"""
    json_handler.log_operation("standard_content_queried", {"standard": "cli_flags"})
    return """[bold white]CLI FLAGS STANDARD[/bold white]

[yellow]PURPOSE:[/yellow]
  Consistent CLI flags across all AIPass branches.
  Users learn one interface, every branch honors it.

[yellow]TIER 1 - REQUIRED FLAGS:[/yellow]

  [bold cyan]--help[/bold cyan] / [bold cyan]-h[/bold cyan] / [bold cyan]help[/bold cyan]
    Rich-formatted help panel with usage, description, and
    [dim]Commands:[/dim] line listing available actions.
    Already universal - keep it that way.

  [bold cyan]--version[/bold cyan] / [bold cyan]-V[/bold cyan]
    Print "[dim]BRANCH vX.Y.Z[/dim]" from the META header and exit.
    Example: [dim]flow v2.4.0[/dim]

[yellow]TIER 2 - RECOMMENDED FLAGS:[/yellow]

  [bold cyan]--verbose[/bold cyan] / [bold cyan]-v[/bold cyan]
    Extra diagnostic output for multi-step operations.
    Show what the branch is doing under the hood.

  [bold cyan]--dry-run[/bold cyan]
    Preview what would happen without executing.
    For branches that mutate state (files, mail, config).

  [bold cyan]--test[/bold cyan]
    Quick self-check, prints pass/fail and exits.
    For branches with testable functionality.

[yellow]FLAG HANDLING ORDER:[/yellow]

  [green]1.[/green] Universal flags first - execute and exit:
     [dim]if args.command in ("--help", "-h", "help"):  show_help(); return
     if args.command in ("--version", "-V"):        print_version(); return
     if args.command == "--test":                    run_test(); return[/dim]

  [green]2.[/green] Behavioral flags - strip and pass through:
     [dim]verbose = "--verbose" in sys.argv or "-v" in sys.argv
     dry_run = "--dry-run" in sys.argv
     # Remove from argv before routing to modules[/dim]

[yellow]KEY RULES:[/yellow]

  [bold white]-V[/bold white] uppercase for version (because [bold white]-v[/bold white] is verbose)
  [bold white]Drone passes flags through[/bold white] - does not intercept them
  [bold white]Verbose output[/bold white] uses [dim][dim] formatting[/dim]
  [bold white]Dry-run output[/bold white] prefixes with [bold yellow]DRY RUN[/bold yellow]"""
