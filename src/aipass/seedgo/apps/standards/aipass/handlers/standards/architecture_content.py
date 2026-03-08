"""
Architecture Standards Content Handler

Provides formatted Architecture standards content.
Module orchestrates, handler implements.
"""

# =================== AIPass ====================
# Name: architecture_content.py
# Description: Architecture Standards Content Handler
# Version: 1.0.0
# Created: 2026-03-05
# Modified: 2026-03-05
# =============================================


def get_architecture_standards() -> str:
    """Return formatted architecture standards content with Rich markup

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE:[/bold cyan]",
        "  Separate [yellow]routing[/yellow] ≠ [yellow]orchestration[/yellow] ≠ [yellow]implementation[/yellow]",
        "  Keep files small (< 500 lines), handlers transportable, context clean",
        "",
        "[bold cyan]THE 3-LAYER PATTERN:[/bold cyan]",
        "",
        "  [dim]apps/branch.py[/dim] (Entry) → Auto-discover modules, route commands",
        "  [dim]apps/modules/[/dim] (Orchestrate) → Coordinate workflow, call handlers",
        "  [dim]apps/handlers/[/dim] (Implement) → ALL business logic, domain-organized",
        "",
        "[bold cyan]TEMPLATE BASELINE COMPLIANCE:[/bold cyan]",
        "  All branches must match spawn template structure",
        "",
        "  [yellow]Source of Truth:[/yellow] [dim].template_registry.json[/dim] (30 files + 20 dirs = 50 checks)",
        "  [yellow]Transformations:[/yellow] BRANCH.ID.json → .trinity/passport.json, {{BRANCH}} → SEEDGO, etc.",
        "  [yellow]Why:[/yellow] Template is the contract - branches that drift break during updates",
        "",
        "  [bold]Example scores:[/bold]",
        "  [green]98%:[/green] BACKUP_SYSTEM, SEEDGO   [green]94%:[/green] FLOW   [yellow]86%:[/yellow] API",
        "",
        "[yellow]KEY RULES:[/yellow]",
        "",
        "  1. [bold]Handlers CANNOT import modules[/bold] (breaks transportability)",
        "     [green]✓[/green] Modules import handlers",
        "     [green]✓[/green] Handlers import handlers (same domain package)",
        "     [red]✗[/red] Handlers import modules (circular dependency)",
        "",
        "  2. [bold red]CRITICAL:[/bold red] [bold]Foundation services CANNOT import each other[/bold]",
        "     CLI ↔ Prax = [red]SYSTEM-WIDE BREAKAGE[/red] (circular dependency)",
        "     [green]✓[/green] Branches import CLI + Prax",
        "     [red]✗[/red] CLI imports Prax",
        "     [red]✗[/red] Prax imports CLI",
        "",
        "  3. [bold]Command Routing: handle_command() pattern[/bold]",
        "     [yellow]Rule:[/yellow] Each module implements [dim]handle_command(command, args)[/dim] returning True if handled",
        "     [green]✓[/green] One primary command per module (no aliases)",
        "     [red]✗[/red] No alias system (removed Session 14)",
        "     [dim]Example:[/dim] [green]if command != 'primary_name': return False[/green]",
        "",
        "  4. [bold]Organize by domain, not by technical role[/bold]",
        "     [dim]handlers/json/[/dim] not [dim]handlers/utils/json_helpers.py[/dim]",
        "     [dim]handlers/branch/[/dim] not [dim]handlers/operations/branch_ops.py[/dim]",
        "",
        "  5. [bold]File size guidelines[/bold]",
        "     [green]< 300:[/green] Perfect   [green]300-500:[/green] Good   [yellow]500-700:[/yellow] Heavy   [red]700+:[/red] Split it",
        "",
        "  6. [bold]Path = context, name = action[/bold]",
        "     [dim]handlers/json/ops.py[/dim] NOT [dim]handlers/json/json_ops.py[/dim]",
        "",
        "[bold cyan]TWO-LEVEL INTROSPECTION:[/bold cyan]",
        "  [yellow]Level 1 - Main Entry (shows modules only):[/yellow]",
        "  [dim]$ python3 flow.py[/dim]",
        "  ",
        "  [cyan]Flow - PLAN Management System[/cyan]",
        "  Discovered Modules: 5",
        "    • create_plan",
        "    • delete_plan",
        "    • list_plans",
        "  ",
        "  [yellow]Level 2 - Individual Module (shows handlers):[/yellow]",
        "  [dim]$ python3 create_plan.py[/dim]",
        "  ",
        "  [cyan]create_plan Module[/cyan]",
        "  Connected Handlers:",
        "    handlers/plan/",
        "      - command_parser.py",
        "      - create_file.py",
        "    handlers/registry/",
        "      - load_registry.py",
        "",
        "[yellow]WHY INTROSPECTION:[/yellow]",
        "  Manual navigation: 5-10 min, context burn, error-prone",
        "  Auto-discovery: 5 sec, zero maintenance, no hardcoded lists",
        "",
        "[yellow]WARNINGS:[/yellow]",
        "  • Handlers importing modules = [red]circular dependency death[/red]",
        "  • Files over 700 lines = [red]AI context degrades, errors increase[/red]",
        "  • Technical organization (utils/, helpers/) = [red]navigation nightmare[/red]",
        "",
        "[bold]Exception:[/bold] Service imports OK (e.g., [dim]prax.apps.modules.logger[/dim] system-wide)",
        "",
        "[bold cyan]REFERENCE:[/bold cyan]",
        "  [dim]See: seedgo standards pack (architecture)[/dim]",
        "  [dim]See: src/aipass/seedgo/apps/ (showroom)[/dim]",
        "  [dim]See: src/aipass/*/apps/ (production examples)[/dim]",
    ]

    return "\n".join(lines)
