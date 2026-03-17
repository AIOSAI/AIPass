# =================== AIPass ====================
# Name: agent_status_module.py
# Description: PRAX Agent Status Push Command
# Version: 0.1.0
# Created: 2026-02-25
# Modified: 2026-03-09
# =============================================

"""
PRAX Agent Status Module

Implements the 'agent-status-push' command using handle_command interface.
Pushes agent_status section to all branch dashboards showing active/stale agents.
"""

import sys
from typing import List

from aipass.cli.apps.modules import console, error
from aipass.prax.apps.handlers.json import json_handler


def print_introspection():
    """Display module introspection - shows connected handlers"""
    console.print()
    console.print("[bold cyan]PRAX Agent Status Module[/bold cyan]")
    console.print()
    console.print("[yellow]Purpose:[/yellow]")
    console.print("  Push agent_status section to all branch dashboards")
    console.print()

    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print()
    console.print("  [cyan]prax/handlers/dashboard/[/cyan]")
    console.print("    [dim]- agent_status_writer.py (push_agent_status_dashboard, build_agent_status_section)[/dim]")
    console.print()

    console.print("[dim]Run 'drone @prax agent-status-push' to execute[/dim]")
    console.print()


def print_help():
    """Drone-compliant help output"""
    console.print()
    console.print("[bold cyan]PRAX Agent Status Push[/bold cyan]")
    console.print()

    console.print("[yellow]Purpose:[/yellow]")
    console.print("  Scan for active dispatch agents and push status to all dashboards")
    console.print()

    console.print("[yellow]Usage:[/yellow]")
    console.print()
    console.print("  [dim]# Push agent status to all branch dashboards[/dim]")
    console.print("  $ drone @prax agent-status-push")
    console.print()
    console.print("  [dim]# Preview section data without pushing[/dim]")
    console.print("  $ drone @prax agent-status-push --dry-run")
    console.print()


def handle_command(command: str, args: List[str]) -> bool:
    """
    Handle agent-status-push command

    Args:
        command: Command name
        args: Command arguments

    Returns:
        True if command was handled
    """
    if command != 'agent-status-push':
        return False

    if not args:
        print_introspection()
        return True

    from aipass.prax.apps.handlers.dashboard.agent_status_writer import (
        build_agent_status_section,
        push_agent_status_dashboard,
    )

    json_handler.log_operation("agent_status_push_executed", {"args": args})

    if '--help' in args:
        print_help()
        return True

    if '--dry-run' in args:
        import json
        section = build_agent_status_section()
        console.print("\n[bold cyan]Agent Status Section (dry-run)[/bold cyan]")
        console.print(json.dumps(section, indent=2))
        return True

    section = build_agent_status_section()
    active = section["agent_count"]
    stale = len(section["stale_agents"])

    console.print(f"\n[bold cyan]Agent Status Push[/bold cyan]")
    console.print(f"  Active agents: {active}")
    console.print(f"  Stale agents: {stale}")

    result = push_agent_status_dashboard()

    if result:
        console.print("[green]✅ Pushed to all branch dashboards[/green]\n")
    else:
        error("Push failed — check logs")

    return True


if __name__ == "__main__":
    if len(sys.argv) == 1:
        print_introspection()
        sys.exit(0)

    if '--help' in sys.argv:
        print_help()
        sys.exit(0)

    if '--introspect' in sys.argv:
        print_introspection()
        sys.exit(0)

    args = [arg for arg in sys.argv[1:] if not arg.startswith('--')]
    handle_command('agent-status-push', args + [a for a in sys.argv[1:] if a.startswith('--')])
