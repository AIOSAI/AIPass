# =================== AIPass ====================
# Name: adopt.py
# Description: aipass adopt — bring an existing projects/ directory into AIPass
# Version: 1.0.0
# Created: 2026-07-20
# Modified: 2026-07-20
# =============================================

"""
aipass adopt — turn an existing directory under projects/ into a full
AIPass project (registry, resident agent, .aipass/.claude scaffold).

Unlike `aipass new`, adopt starts from a directory that already has its
own content and git history — every write is additive, nothing existing
is ever overwritten.
"""

from __future__ import annotations

import sys
from pathlib import Path

from aipass.aipass.apps.handlers.json import json_handler
from aipass.cli.apps.modules import console, error, success
from aipass.aipass.apps.handlers.help_flag import wants_help
from aipass.prax import logger

COMMAND = "adopt"


def print_introspection() -> None:
    """Bare invocation — usage pointer."""
    console.print()
    console.print("[bold cyan]aipass adopt[/bold cyan] — bring an existing directory into projects/")
    console.print()
    console.print("[dim]Usage: aipass adopt <name-or-path> [--no-agent] [--dry-run][/dim]")
    console.print()


def print_help() -> None:
    """Print usage help for the adopt command."""
    console.print()
    console.print("[bold cyan]aipass adopt[/bold cyan] — adopt an existing directory as an AIPass project")
    console.print()
    console.print("[yellow]USAGE:[/yellow]")
    console.print("  [green]aipass adopt <name>[/green]              [dim]# Adopt <host>/projects/<name>[/dim]")
    console.print("  [green]aipass adopt <path>[/green]              [dim]# Adopt by relative/absolute path[/dim]")
    console.print("  [green]aipass adopt <name> --no-agent[/green]   [dim]# Skip resident agent[/dim]")
    console.print("  [green]aipass adopt <name> --dry-run[/green]    [dim]# Preview, write nothing[/dim]")
    console.print()
    console.print("[yellow]WHAT IT DOES:[/yellow]")
    console.print("  Seats a sealed registry, scaffolds .aipass/.claude, and (unless")
    console.print("  --no-agent) creates a resident agent — all ADDITIVE. Never touches")
    console.print("  the target's existing git history or tracked files. If the target")
    console.print("  has no .gitignore covering AIPass local state, one is created or")
    console.print("  appended to first — the target may be a public repo.")
    console.print()
    console.print("[yellow]REQUIRES:[/yellow]")
    console.print("  Target must be an existing directory at <host>/projects/<name>.")
    console.print("  Use 'aipass new' instead to create a brand-new project.")
    console.print()


def handle_command(command: str, args: list[str]) -> bool:
    """Route the 'adopt' command. Returns True if handled."""
    if command != COMMAND:
        return False

    if not args:
        json_handler.log_operation("adopt_usage", {"command": command})
        print_introspection()
        return True
    if wants_help(args):
        json_handler.log_operation("adopt_help", {"command": command})
        print_help()
        return True

    name_or_path = args[0]
    known = {"--no-agent", "--dry-run"}
    unknown = [a for a in args[1:] if a not in known]
    if unknown:
        error(f"Unknown option: {unknown[0]}")
        print_help()
        return True
    no_agent = "--no-agent" in args[1:]
    dry_run = "--dry-run" in args[1:]

    from aipass.aipass.apps.handlers.new_project import find_host_root
    from aipass.aipass.apps.handlers.new_project.adopt import adopt_project

    target_path = Path(name_or_path)
    if not target_path.exists():
        host = find_host_root(Path.cwd())
        if host is None:
            error("Not inside an AIPass installation (no *_REGISTRY.json found).")
            sys.exit(1)
        target_path = host / "projects" / name_or_path

    try:
        result = adopt_project(target_path, no_agent=no_agent, dry_run=dry_run)
    except RuntimeError as e:
        logger.warning("[AIPASS] adopt failed: %s", e)
        error(str(e))
        sys.exit(1)

    console.print()
    verb = "Would adopt" if dry_run else "Adopted"
    success(f"{verb} '{result['name']}' at {result['target']}")
    console.print()
    console.print(f"  [dim]Registry:[/dim]   {result['registry_file']}")
    console.print(f"  [dim]Gitignore:[/dim]  {result['gitignore_action']}")
    if result["agent_home"]:
        state = "created" if result["agent_created"] else "planned"
        console.print(f"  [dim]Agent:[/dim]      {state} ({result['agent_home']})")
    else:
        console.print("  [dim]Agent:[/dim]      skipped (--no-agent)")
    console.print()
    console.print("[dim]Files:[/dim]")
    for f in result["files"]:
        console.print(f"  [dim]{f}[/dim]")
    console.print()

    json_handler.log_operation(
        "adopt_project",
        {"name": result["name"], "target": result["target"], "dry_run": dry_run},
    )
    logger.info("[AIPASS] adopt: %s at %s (dry_run=%s)", result["name"], result["target"], dry_run)
    return True
