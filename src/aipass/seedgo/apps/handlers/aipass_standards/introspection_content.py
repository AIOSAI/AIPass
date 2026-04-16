# =================== AIPass ====================
# Name: introspection_content.py
# Description: Introspection Standards Content Handler
# Version: 1.0.0
# Created: 2026-03-08
# Modified: 2026-03-08
# =============================================

"""
Introspection Standards Content Handler

Provides formatted introspection standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_introspection_standards() -> str:
    """Return formatted introspection standards content with Rich markup

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold red]TWO-LEVEL AUTO-DISCOVERY PATTERN[/bold red]",
        "",
        "[yellow]PURPOSE:[/yellow] When run with no arguments, entry points and modules",
        "  reveal their structure automatically — no directory browsing required",
        "",
        "─" * 70,
        "",
        "[bold cyan]LEVEL 1 — Entry Point (apps/{name}.py) with no args:[/bold cyan]",
        "",
        "  • Shows branch name + description",
        "  • Auto-discovers modules in [dim]modules/*.py[/dim] that have [dim]handle_command()[/dim]",
        "  • Lists discovered module names",
        "  • Points to [dim]--help[/dim] for full usage",
        "  • Function name: [bold]print_introspection()[/bold]",
        "",
        "  [dim]def print_introspection():[/dim]",
        '  [dim]    """Show branch structure via auto-discovery"""[/dim]',
        '  [dim]    modules_dir = Path(__file__).parent / "modules"[/dim]',
        '  [dim]    for file_path in sorted(modules_dir.glob("*.py")):[/dim]',
        '  [dim]        if file_path.name.startswith("_"):[/dim]',
        "  [dim]            continue[/dim]",
        "  [dim]        # load and check for handle_command()[/dim]",
        "",
        "  [green]Output example:[/green]",
        "  [dim]Flow - PLAN Management System[/dim]",
        "  [dim]Discovered Modules: 5[/dim]",
        "  [dim]  create_plan, delete_plan, list_plans, ...[/dim]",
        "  [dim]Run 'drone @flow --help' for usage information[/dim]",
        "",
        "─" * 70,
        "",
        "[bold cyan]LEVEL 2 — Module (apps/modules/*.py) with no args:[/bold cyan]",
        "",
        "  • Shows module name",
        "  • Lists Connected Handlers (handler files this module depends on)",
        "  • Points to [dim]--help[/dim] for usage",
        "  • Function name: [bold]print_introspection()[/bold]",
        "",
        "  [dim]def print_introspection():[/dim]",
        '  [dim]    """Show module structure - connected handlers"""[/dim]',
        '  [dim]    console.print("[bold cyan]create_plan[/bold cyan] Module")[/dim]',
        '  [dim]    console.print("[yellow]Connected Handlers:[/yellow]")[/dim]',
        '  [dim]    console.print("  handlers/plan/ - command_parser.py, ...")[/dim]',
        "",
        "  [green]Output example:[/green]",
        "  [dim]create_plan Module[/dim]",
        "  [dim]Connected Handlers:[/dim]",
        "  [dim]  handlers/plan/ - command_parser.py, resolve_location.py[/dim]",
        "  [dim]  handlers/registry/ - load_registry.py, save_registry.py[/dim]",
        "  [dim]Run 'drone @flow create --help' for usage[/dim]",
        "",
        "─" * 70,
        "",
        "[bold cyan]EXECUTION ORDER IN main() — STRICT:[/bold cyan]",
        "",
        "  [bold]1.[/bold] No args      → [bold]print_introspection()[/bold]  [yellow](FIRST)[/yellow]",
        "  [bold]2.[/bold] --help/-h    → [bold]print_help()[/bold]           [yellow](SECOND)[/yellow]",
        "  [bold]3.[/bold] --version/-V → show version",
        "  [bold]4.[/bold] Commands     → command routing",
        "",
        "  [dim]def main():[/dim]",
        "  [dim]    if len(sys.argv) < 2:[/dim]",
        "  [dim]        print_introspection()  # FIRST[/dim]",
        "  [dim]        return[/dim]",
        "  [dim]    command = sys.argv[1][/dim]",
        "  [dim]    if command in ['--help', '-h', 'help']:[/dim]",
        "  [dim]        print_help()  # SECOND[/dim]",
        "  [dim]        return[/dim]",
        "  [dim]    # ... version, then routing[/dim]",
        "",
        "─" * 70,
        "",
        "[bold cyan]KEY DISTINCTION:[/bold cyan]",
        "",
        "  [bold]Introspection (no args)[/bold] = Structure / Discovery",
        "    What IS this? What modules exist? What handlers are connected?",
        "",
        "  [bold]Help (--help)[/bold] = Usage / Commands",
        "    HOW do I use this? What commands and flags are available?",
        "",
        "  [yellow]Different functions, different purposes. Never combine them.[/yellow]",
        "",
        "[bold cyan]AUTO-DISCOVERY REQUIREMENTS:[/bold cyan]",
        "",
        "  [green]✓[/green] Level 1: Scan [dim]modules/*.py[/dim] dynamically (no hardcoded module lists)",
        "  [green]✓[/green] Level 1: Filter by [dim]handle_command()[/dim] presence",
        "  [green]✓[/green] Level 2: List connected handlers grouped by domain",
        "  [green]✓[/green] Both levels: Function named [dim]print_introspection()[/dim]",
        "",
        "  [red]✗[/red] Hardcoded module lists: [dim]MODULES = ['create', 'delete', 'list'][/dim]",
        "  [red]✗[/red] Combined introspection + help in one function",
        "  [red]✗[/red] Help before introspection in execution order",
        "",
        "[bold cyan]REFERENCE:[/bold cyan]",
        "  [dim]See: seedgo standards pack (introspection)[/dim]",
        "  [dim]See: src/aipass/seedgo/apps/seedgo.py (Level 1 reference)[/dim]",
    ]

    json_handler.log_operation("standard_content_queried", {"standard": "introspection"})
    return "\n".join(lines)
