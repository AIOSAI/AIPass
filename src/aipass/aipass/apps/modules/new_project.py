# =================== AIPass ====================
# Name: new_project.py
# Description: aipass new — create projects inside the AIPass installation
# Version: 1.0.0
# Created: 2026-07-17
# Modified: 2026-07-17
# =============================================

"""
aipass new — create projects inside the AIPass installation (DPLAN-0247)

Creates a project at <host>/projects/<name> with its own git repo,
AIPass scaffold, and optional resident agent. Born deployable.
"""

from __future__ import annotations

import sys
from pathlib import Path

from aipass.aipass.apps.handlers.json import json_handler
from aipass.cli.apps.modules import console, error, success
from aipass.aipass.apps.handlers.help_flag import wants_help
from aipass.prax import logger

COMMAND = "new"


def print_introspection() -> None:
    """List existing projects in the installation."""
    from aipass.aipass.apps.handlers.new_project import find_host_root

    host = find_host_root(Path.cwd())
    console.print()
    console.print("[bold cyan]aipass new[/bold cyan] — project creator")
    console.print()

    if host is None:
        console.print("[dim]Not inside an AIPass installation.[/dim]")
        console.print()
        return

    projects_dir = host / "projects"
    if not projects_dir.is_dir():
        console.print(f"[dim]No projects/ directory at {host}[/dim]")
        console.print()
        return

    projects = [d for d in sorted(projects_dir.iterdir()) if d.is_dir() and not d.name.startswith(".")]
    if not projects:
        console.print("[dim]No projects yet. Create one:[/dim]")
    else:
        console.print(f"[yellow]{len(projects)} project(s):[/yellow]")
        for p in projects:
            has_git = (p / ".git").is_dir()
            has_reg = any(f.name.endswith("_REGISTRY.json") for f in p.iterdir() if f.is_file())
            markers = []
            if has_git:
                markers.append("git")
            if has_reg:
                markers.append("registry")
            info = f"  [dim]({', '.join(markers)})[/dim]" if markers else ""
            console.print(f"  [cyan]{p.name}[/cyan]{info}")

    console.print()
    console.print("[dim]Create: aipass new <name> [--template python] [--no-agent][/dim]")
    console.print()


def print_help() -> None:
    """Print usage help for the new command."""
    from aipass.aipass.apps.handlers.new_project import TEMPLATES

    console.print()
    console.print("[bold cyan]aipass new[/bold cyan] — create a project inside AIPass")
    console.print()
    console.print("[yellow]USAGE:[/yellow]")
    console.print("  [green]aipass new <name>[/green]                      [dim]# Create with empty template[/dim]")
    console.print("  [green]aipass new <name> --template python[/green]    [dim]# Create with Python template[/dim]")
    console.print("  [green]aipass new <name> --no-agent[/green]           [dim]# Skip agent creation[/dim]")
    console.print()
    console.print("[yellow]TEMPLATES:[/yellow]")
    console.print(f"  [dim]{', '.join(TEMPLATES)}[/dim]")
    console.print()
    console.print("[yellow]WHAT IT DOES:[/yellow]")
    console.print("  Creates projects/<name> with its own git repo, AIPass scaffold,")
    console.print("  and optional resident agent. Born deployable — repo + packaging")
    console.print("  from minute one.")
    console.print()


def _prompt_template(templates: list[str]) -> str:
    """Prompt user to choose a template interactively."""
    console.print()
    console.print("[yellow]Choose a template:[/yellow]")
    for idx, t in enumerate(templates, 1):
        console.print(f"  [green]{idx}[/green]. {t}")
    console.print()
    while True:
        try:
            choice = input("Template [1]: ").strip()
        except (EOFError, KeyboardInterrupt):
            logger.info("template prompt interrupted, defaulting to %s", templates[0])
            return templates[0]
        if not choice:
            return templates[0]
        if choice.isdigit() and 1 <= int(choice) <= len(templates):
            return templates[int(choice) - 1]
        if choice in templates:
            return choice
        error(f"Invalid choice. Enter 1-{len(templates)} or a template name.")


def _prompt_agent() -> bool:
    """Prompt user whether to skip agent creation. Returns no_agent flag."""
    console.print()
    while True:
        try:
            choice = input("Create resident agent? [Y/n]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            logger.info("agent prompt interrupted, defaulting to create agent")
            return False
        if choice in ("", "y", "yes"):
            return False
        if choice in ("n", "no"):
            return True
        error("Enter y or n.")


def handle_command(command: str, args: list[str]) -> bool:
    """Route the 'new' command. Returns True if handled."""
    if command != COMMAND:
        return False

    if not args:
        json_handler.log_operation("new_project_usage", {"command": command})
        print_introspection()
        return True
    if wants_help(args):
        json_handler.log_operation("new_project_help", {"command": command})
        print_help()
        return True
    if args[0] == "--info":
        json_handler.log_operation("new_project_info", {"command": command})
        print_introspection()
        return True

    name = args[0]
    template = None
    no_agent = None
    has_template_flag = False
    has_agent_flag = False

    i = 1
    while i < len(args):
        if args[i] == "--template" and i + 1 < len(args):
            template = args[i + 1]
            has_template_flag = True
            i += 2
        elif args[i] == "--no-agent":
            no_agent = True
            has_agent_flag = True
            i += 1
        else:
            error(f"Unknown option: {args[i]}")
            print_help()
            return True

    from aipass.aipass.apps.handlers.new_project import TEMPLATES, create_project

    if not has_template_flag:
        template = _prompt_template(list(TEMPLATES))
    elif template is None:
        template = "empty"
    if not has_agent_flag:
        no_agent = _prompt_agent()
    elif no_agent is None:
        no_agent = False

    try:
        result = create_project(name, template, no_agent)
    except (RuntimeError, ValueError) as e:
        logger.warning("[AIPASS] new project failed: %s", e)
        error(str(e))
        sys.exit(1)

    console.print()
    success(f"Project '{name}' created at {result['target']}")
    console.print()
    console.print(f"  [dim]Registry:[/dim]  {result['registry_file']}")
    console.print(f"  [dim]Template:[/dim]  {result['template']}")
    if result["agent_created"]:
        console.print("  [dim]Agent:[/dim]     created (full framework agent)")
    else:
        console.print("  [dim]Agent:[/dim]     skipped (--no-agent)")

    json_handler.log_operation(
        "new_project_create",
        {"name": name, "template": template, "target": result["target"]},
    )
    logger.info("[AIPASS] new project: %s (%s) at %s", name, template, result["target"])

    if result["agent_created"] and sys.stdin.isatty():
        from aipass.aipass.apps.handlers.handoff_platform import (
            launch_inline,
            return_path_breadcrumb,
        )

        console.print()
        console.print("[dim]Launching your manager agent — Ctrl-C to stay in the shell.[/dim]")
        console.print(f"[dim]Return anytime with: {return_path_breadcrumb(result['agent_home'])}[/dim]")
        console.print()

        launch_inline(
            "claude",
            "You are the new resident agent of this project."
            " Read your passport and README, then tell me what you can do.",
            result["agent_home"],
        )

    console.print()
    console.print("[yellow]Next steps:[/yellow]")
    if result["agent_created"]:
        console.print(f"  [cyan]cd {result['agent_home']}[/cyan]")
        console.print("  [cyan]claude[/cyan]              [dim]# meet your project agent[/dim]")
    else:
        console.print(f"  [cyan]cd {result['target']}[/cyan]")
    console.print()
    return True
