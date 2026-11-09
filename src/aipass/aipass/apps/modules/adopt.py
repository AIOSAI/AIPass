# =================== AIPass ====================
# Name: adopt.py
# Description: aipass adopt — bring an existing directory anywhere on disk into AIPass
# Version: 2.0.0
# Created: 2026-07-20
# Modified: 2026-11-08
# =============================================

"""
aipass adopt — turn an existing directory anywhere on disk into an AIPass
project, in framework mode (the AIPass layout) or contractor mode (local,
untracked state only).

Unlike `aipass new`, adopt starts from a directory that already has its
own content and git history — every write is additive, nothing existing
is ever overwritten.
"""

from __future__ import annotations

import sys
from pathlib import Path

from rich.markup import escape

from aipass.aipass.apps.handlers.json import json_handler
from aipass.cli.apps.modules import console, error, success, warning
from aipass.aipass.apps.handlers.help_flag import wants_help
from aipass.prax import logger

COMMAND = "adopt"


def print_introspection() -> None:
    """Bare invocation — usage pointer."""
    console.print()
    console.print("[bold cyan]aipass adopt[/bold cyan] — bring an existing directory into AIPass")
    console.print()
    console.print(
        "[dim]Usage: aipass adopt <name-or-path> [--mode framework|contractor] "
        "[--citizen @name | --no-agent] [--dry-run][/dim]"
    )
    console.print()


def print_help() -> None:
    """Print usage help for the adopt command."""
    console.print()
    console.print("[bold cyan]aipass adopt[/bold cyan] — adopt an existing directory as an AIPass project")
    console.print()
    console.print("[yellow]USAGE:[/yellow]")
    console.print("  [green]aipass adopt <path>[/green]                    [dim]# framework mode, any path[/dim]")
    console.print("  [green]aipass adopt <name>[/green]                    [dim]# <host>/projects/<name>[/dim]")
    console.print("  [green]aipass adopt <path> --mode contractor[/green]  [dim]# no tracked file changes[/dim]")
    console.print("  [green]aipass adopt <path> --citizen @name[/green]    [dim]# bring an existing citizen[/dim]")
    console.print("  [green]aipass adopt <path> --no-agent[/green]         [dim]# no agent at all[/dim]")
    console.print(
        "  [green]aipass adopt <path> --dry-run[/green]          [dim]# every path and clash, nothing written[/dim]"
    )
    console.print()
    console.print("[yellow]MODES:[/yellow]")
    console.print("  framework   The AIPass layout: registry, .aipass/.claude scaffold, switch files and a")
    console.print("              fresh resident agent, all additive. .gitignore gets the AIPass local-state")
    console.print("              block first: the target may be a public repo.")
    console.print("  contractor  The project keeps its own stack: no tracked file and no .gitignore is")
    console.print("              written. Only the registry and the local hook scaffold (.aipass/hooks.json,")
    console.print("              tier0/tier1, .claude/settings.local.json), each listed in .git/info/exclude.")
    console.print("              A tracked AIPass file is a clash: named, never overwritten, apply refused.")
    console.print("              Needs --citizen or --no-agent: a fresh resident would land in src/.")
    console.print()
    console.print("[yellow]CITIZEN:[/yellow]")
    console.print("  --citizen @name runs drone @spawn adopt-citizen @name <path>, embeds its preview and")
    console.print("  leaves the registry to @spawn. A @spawn refusal stops adopt before its first write.")
    console.print()
    console.print("[yellow]TRUST:[/yellow]")
    console.print("  Either mode enrols the project when adopt writes .aipass/hooks.json. An existing")
    console.print("  hooks.json keeps its enrolment; run aipass trust <path> after editing it.")
    console.print()
    console.print("[yellow]DRY RUN:[/yellow]")
    console.print("  Each path as create, append, skip or clash, with its reason.")
    console.print("  Use 'aipass new' instead to create a brand-new project.")
    console.print()


def _print_citizen(citizen: dict | None) -> None:
    """Embed @spawn adopt-citizen's own preview verbatim; a refusal reads BLOCKED with its reason."""
    if not citizen:
        return
    console.print()
    state = "" if citizen["ok"] else " — [red]BLOCKED[/red]"
    console.print(f"[dim]Citizen: @spawn adopt-citizen {citizen['name']}[/dim]{state}")
    for line in citizen["output"].splitlines():
        console.print(f"  {escape(line)}")
    if not citizen["ok"]:
        warning(citizen["reason"])


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
    rest = list(args[1:])
    values: dict = {}
    for flag in ("--mode", "--citizen"):
        if flag in rest:
            at = rest.index(flag)
            if at + 1 >= len(rest):
                error(f"{flag} needs a value")
                print_help()
                return True
            values[flag] = rest[at + 1]
            del rest[at : at + 2]
    known = {"--no-agent", "--dry-run"}
    unknown = [a for a in rest if a not in known]
    if unknown:
        error(f"Unknown option: {unknown[0]}")
        print_help()
        return True
    no_agent = "--no-agent" in rest
    dry_run = "--dry-run" in rest
    mode = values.get("--mode", "framework")
    citizen = values.get("--citizen")

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
        result = adopt_project(target_path, no_agent=no_agent, dry_run=dry_run, mode=mode, citizen=citizen)
    except RuntimeError as e:
        logger.warning("[AIPASS] adopt failed: %s", e)
        error(str(e))
        sys.exit(1)

    console.print()
    verb = "Would adopt" if dry_run else "Adopted"
    success(f"{verb} '{result['name']}' at {result['target']} ({result['mode']} mode)")
    for note in result.get("notes", []):
        warning(note)
    console.print()
    console.print(f"  [dim]Registry:[/dim]   {result['registry_file']}")
    console.print(f"  [dim]Gitignore:[/dim]  {result['gitignore_action']}")
    if citizen:
        console.print(f"  [dim]Agent:[/dim]      {citizen} via @spawn adopt-citizen")
    elif result["agent_home"]:
        state = "created" if result["agent_created"] else "planned"
        console.print(f"  [dim]Agent:[/dim]      {state} ({result['agent_home']})")
    else:
        console.print("  [dim]Agent:[/dim]      skipped (--no-agent)")
    console.print()
    console.print("[dim]Plan:[/dim]")
    for row in result["rows"]:
        console.print(f"  {row['action']:<7} {escape(row['path'])}  [dim]{escape(row['reason'])}[/dim]")
    _print_citizen(result.get("citizen"))
    clashes = [row["path"] for row in result["rows"] if row["action"] == "clash"]
    if dry_run and clashes:
        warning(f"Apply would refuse: {len(clashes)} clash(es) to resolve first.")
    console.print()

    json_handler.log_operation(
        "adopt_project",
        {"name": result["name"], "target": result["target"], "dry_run": dry_run},
    )
    logger.info("[AIPASS] adopt: %s at %s (dry_run=%s)", result["name"], result["target"], dry_run)
    return True
