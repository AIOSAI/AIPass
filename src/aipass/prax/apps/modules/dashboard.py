# =================== AIPass ====================
# Name: dashboard.py
# Description: Dashboard Section Utilities
# Version: 0.2.0
# Created: 2026-02-25
# Modified: 2026-03-09
# =============================================

"""
Dashboard Section Utilities

Provides utilities for services to update their sections in branch
DASHBOARD.local.json files. Each service manages only its own section.

Run directly or via: python3 apps/modules/dashboard.py
"""

import json
import sys
from pathlib import Path
from typing import Dict, List

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.cli.apps.modules import console

# Import handlers
from aipass.prax.apps.handlers.dashboard.operations import (
    load_dashboard,
    save_dashboard,
    update_section as handler_update_section,
    write_section,
    get_dashboard_path,
)
from aipass.prax.apps.handlers.dashboard.status import (
    calculate_quick_status,
    get_branch_paths,
    resolve_branch_path,
)

# Import refresh handler - exposed as public API
from aipass.prax.apps.handlers.dashboard.refresh import (
    refresh_all_dashboards,
    refresh_single_dashboard
)

# Import template handlers
from aipass.prax.apps.handlers.dashboard.template_pusher import (
    push_dashboard_template,
    get_template_status
)
from aipass.prax.apps.handlers.dashboard.template_differ import (
    diff_dashboard_template
)


# ============================================
# DASHBOARD SCHEMA
# ============================================
DASHBOARD_TEMPLATE = {
    "branch": "",
    "last_updated": "",
    "sections": {
        "ai_mail": {
            "managed_by": "ai_mail",
            "new": 0,
            "opened": 0,
            "total": 0,
            "last_updated": ""
        },
        "flow": {
            "managed_by": "flow",
            "active_plans": 0,
            "recently_closed": [],
            "last_updated": ""
        },
        "memory_bank": {
            "managed_by": "memory_bank",
            "vectors_stored": 0,
            "notes": {},
            "last_updated": ""
        },
        "devpulse": {
            "managed_by": "devpulse",
            "summary": {},
            "last_updated": ""
        },
        "commons_activity": {
            "managed_by": "the_commons",
            "mentions": 0,
            "new_posts_since_last_visit": 0,
            "new_comments_since_last_visit": 0,
            "last_updated": ""
        }
    },
    "quick_status": {
        "new_mail": 0,
        "opened_mail": 0,
        "active_plans": 0,
        "commons_mentions": 0,
        "action_required": False,
        "summary": ""
    }
}


# ============================================
# MODULE-LEVEL WRAPPER FUNCTIONS
# ============================================
def update_section(
    branch_path: Path,
    section_name: str,
    section_data: Dict
) -> bool:
    """
    Update a specific section in branch dashboard (legacy wrapper).

    For new integrations, prefer write_section() from
    aipass_os.dev_central.devpulse.apps.handlers.dashboard.operations
    which is self-contained and dependency-free.

    Args:
        branch_path: Path to branch root
        section_name: Section to update (flow, ai_mail, etc)
        section_data: New data for section

    Returns:
        True if updated successfully
    """
    try:
        return handler_update_section(
            branch_path,
            section_name,
            section_data,
            DASHBOARD_TEMPLATE,
            calculate_quick_status
        )
    except Exception as e:
        logger.error(f"Failed to update section {section_name}: {e}")
        return False


# ============================================
# CLI INTERFACE
# ============================================
def print_introspection():
    """Display module info"""
    console.print()
    console.print("[bold cyan]Dashboard Section Utilities[/bold cyan]")
    console.print()
    console.print("[yellow]Template Sections:[/yellow]")
    for section in DASHBOARD_TEMPLATE["sections"]:
        console.print(f"  - {section}")
    console.print()
    console.print("[dim]Run 'python3 dashboard.py --help' for usage[/dim]")
    console.print()


def print_help():
    """Print drone-compliant help output"""
    console.print()
    console.print("[bold cyan]Dashboard Section Utilities[/bold cyan]")
    console.print("Utilities for updating branch dashboard sections")
    console.print()
    console.print("[yellow]COMMANDS:[/yellow]")
    console.print("  status           - Show dashboard status for all branches")
    console.print("  template         - Show dashboard template structure")
    console.print("  refresh          - Refresh dashboard(s) from central files")
    console.print("  push-template    - Push template to all branches")
    console.print("  diff-template    - Diff template against branch dashboards")
    console.print("  template-status  - Show template version and push info")
    console.print()
    console.print("[yellow]USAGE:[/yellow]")
    console.print("  drone @devpulse dashboard status")
    console.print("  drone @devpulse dashboard template")
    console.print("  drone @devpulse dashboard refresh          # refresh current branch")
    console.print("  drone @devpulse dashboard refresh @flow    # refresh specific branch")
    console.print("  drone @devpulse dashboard refresh --all    # refresh all branches")
    console.print("  drone @devpulse dashboard push-template             # push to all branches")
    console.print("  drone @devpulse dashboard push-template --dry-run   # preview changes")
    console.print("  drone @devpulse dashboard diff-template             # diff all branches")
    console.print("  drone @devpulse dashboard diff-template --branch FLOW  # diff single branch")
    console.print("  drone @devpulse dashboard template-status           # version info")
    console.print()
    console.print("[yellow]PROGRAMMATIC (write-through API):[/yellow]")
    console.print("  from aipass_os.dev_central.devpulse.apps.modules.dashboard import write_section")
    console.print("  write_section(branch_path, 'ai_mail', {'new': 3, 'total': 5})")
    console.print()


def print_status():
    """Show dashboard status for all branches"""
    try:
        branches = get_branch_paths()
    except Exception as e:
        console.print(f"[red]Error loading branches: {e}[/red]")
        return

    console.print()
    console.print(f"[bold]Dashboard Status ({len(branches)} branches)[/bold]")
    console.print("=" * 50)

    for branch_path in branches:
        dashboard_path = get_dashboard_path(branch_path)
        exists = dashboard_path.exists()
        status = "[green]exists[/green]" if exists else "[red]missing[/red]"
        console.print(f"  {branch_path.name}: {status}")

    console.print()


def print_template():
    """Show dashboard template"""
    console.print()
    console.print("[bold]Dashboard Template Structure[/bold]")
    console.print("=" * 50)
    console.print(json.dumps(DASHBOARD_TEMPLATE, indent=2))
    console.print()


def _resolve_branch_path(branch_ref: str) -> Path:
    """
    Resolve @branch reference to filesystem path via BRANCH_REGISTRY.json.

    Delegates to handler for file I/O (seedgo modules standard).

    Args:
        branch_ref: Branch reference like "@flow" or "@vera"

    Returns:
        Path to the branch directory

    Raises:
        FileNotFoundError: If registry missing or branch not found
    """
    return resolve_branch_path(branch_ref)


def _handle_refresh(args: List[str]) -> None:
    """
    Handle dashboard refresh command.

    Supports:
        refresh            - refresh current branch (CWD-based)
        refresh @branch    - refresh specific branch
        refresh --all      - refresh all branches

    Args:
        args: Command arguments
    """
    # --all flag: refresh every branch
    if args and args[0] == "--all":
        console.print("[dim]Refreshing all branch dashboards...[/dim]")
        result = refresh_all_dashboards()
        if result["status"] == "success":
            console.print(f"[green]Refreshed {result['branches_updated']} branches[/green]")
        elif result["status"] == "partial":
            console.print(f"[yellow]Refreshed {result['branches_updated']} branches, {result['branches_failed']} failed[/yellow]")
            for err in result.get("errors", []):
                console.print(f"  [red]{err}[/red]")
        else:
            console.print(f"[red]Refresh failed[/red]")
            for err in result.get("errors", []):
                console.print(f"  [red]{err}[/red]")
        return

    # @branch arg: refresh specific branch
    if args and args[0].startswith("@"):
        try:
            branch_path = _resolve_branch_path(args[0])
        except FileNotFoundError as e:
            console.print(f"[red]{e}[/red]")
            return
        console.print(f"[dim]Refreshing {branch_path.name.upper()} dashboard...[/dim]")
        result = refresh_single_dashboard(branch_path)
        if result["status"] == "success":
            console.print(f"[green]Refreshed {result['branch']}[/green]")
        else:
            console.print(f"[red]Failed: {result.get('error', 'unknown')}[/red]")
        return

    # No args: refresh current branch (detect from CWD)
    cwd = Path.cwd()
    # Walk up to find a directory that has DASHBOARD.local.json or is a branch
    branch_path = cwd
    # Try CWD itself first, then walk up
    while branch_path != branch_path.parent:
        if (branch_path / "DASHBOARD.local.json").exists() or (branch_path / ".aipass").exists():
            break
        branch_path = branch_path.parent
    else:
        # Fallback to CWD
        branch_path = cwd

    console.print(f"[dim]Refreshing {branch_path.name.upper()} dashboard...[/dim]")
    result = refresh_single_dashboard(branch_path)
    if result["status"] == "success":
        console.print(f"[green]Refreshed {result['branch']}[/green]")
    else:
        console.print(f"[red]Failed: {result.get('error', 'unknown')}[/red]")


def _handle_push_template(args: List[str]) -> None:
    """
    Handle push-template command.

    Supports:
        push-template            - push template to all branches
        push-template --dry-run  - preview changes without writing

    Args:
        args: Command arguments
    """
    dry_run = "--dry-run" in args
    mode = "DRY RUN" if dry_run else "PUSH"
    console.print(f"[dim]Running dashboard template {mode.lower()}...[/dim]")

    result = push_dashboard_template(dry_run=dry_run)

    console.print()
    console.print(f"[bold]Dashboard Template {mode} Results[/bold]")
    console.print("=" * 50)
    console.print(f"  Branches scanned:  {result['branches_scanned']}")
    console.print(f"  Branches updated:  {result['branches_updated']}")
    console.print(f"  Branches created:  {result['branches_created']}")
    console.print(f"  Branches skipped:  {result['branches_skipped']}")

    if result["changes"]:
        console.print()
        console.print(f"[yellow]Changes ({len(result['changes'])} branches):[/yellow]")
        for entry in result["changes"]:
            console.print(f"\n  [bold]{entry['branch']}:[/bold]")
            for action in entry["actions"]:
                console.print(f"    - {action}")

    if result["errors"]:
        console.print()
        console.print(f"[red]Errors ({len(result['errors'])}):[/red]")
        for err in result["errors"]:
            console.print(f"  [red]! {err}[/red]")

    if not result["changes"] and not result["errors"]:
        console.print()
        console.print("[green]All branches are up to date with template.[/green]")

    console.print()


def _handle_diff_template(args: List[str]) -> None:
    """
    Handle diff-template command.

    Supports:
        diff-template                    - diff all branches
        diff-template --branch BRANCHNAME - diff single branch

    Args:
        args: Command arguments
    """
    branch_name = None
    if "--branch" in args:
        idx = args.index("--branch")
        if idx + 1 < len(args):
            branch_name = args[idx + 1]
        else:
            console.print("[red]--branch requires a branch name[/red]")
            return

    result = diff_dashboard_template(branch_name=branch_name)

    if "error" in result:
        console.print(f"[red]Error: {result['error']}[/red]")
        return

    summary = result.get("summary", {})
    console.print()
    console.print("[bold]Dashboard Template Diff[/bold]")
    console.print("=" * 50)
    console.print(f"  Needs update: {summary.get('needs_update', 0)}")
    console.print(f"  Up to date:   {summary.get('up_to_date', 0)}")
    console.print(f"  Missing:      {summary.get('missing', 0)}")
    console.print(f"  Invalid JSON: {summary.get('invalid_json', 0)}")

    for branch_diff in result.get("branches", []):
        status = branch_diff["status"]
        if status == "up_to_date":
            continue
        color = "yellow" if status == "needs_update" else "red"
        console.print(f"\n  [{color}]{branch_diff['branch']} ({status})[/{color}]")
        for a in branch_diff.get("additions", []):
            console.print(f"    [green]+ {a}[/green]")
        for r in branch_diff.get("removals", []):
            console.print(f"    [red]- {r}[/red]")
        for m in branch_diff.get("modifications", []):
            console.print(f"    [yellow]~ {m}[/yellow]")

    console.print()


def _handle_template_status() -> None:
    """Handle template-status command. Displays version info."""
    status = get_template_status()

    console.print()
    console.print("[bold]Dashboard Template Status[/bold]")
    console.print("=" * 50)
    console.print(f"  Templates dir:   {status['templates_dir']}")
    console.print(f"  Template file:   {'[green]found[/green]' if status['template_exists'] else '[red]MISSING[/red]'}")
    console.print(f"  Schema version:  {status.get('version', 'unknown')}")
    console.print(f"  Last updated:    {status.get('last_updated', 'unknown')}")
    console.print(f"  Updated by:      {status.get('updated_by', 'unknown')}")
    console.print(f"  Last push:       {status.get('last_push') or 'never'}")

    pushed = status.get("last_push_branches", [])
    if pushed:
        preview = ", ".join(pushed[:5])
        suffix = "..." if len(pushed) > 5 else ""
        console.print(f"  Branches pushed: {len(pushed)} ({preview}{suffix})")

    changes = status.get("changes", [])
    if changes:
        console.print()
        console.print("[yellow]Change history:[/yellow]")
        for change in changes:
            console.print(f"  - {change}")

    console.print()


def handle_command(command: str, args: List[str]) -> bool:
    """
    Handle drone-routed commands.

    Supported commands:
        dashboard status          - Show dashboard status for all branches
        dashboard template        - Show dashboard template structure
        dashboard refresh         - Refresh dashboard(s) from central files
        dashboard push-template   - Push template to all branches
        dashboard diff-template   - Diff template against branch dashboards
        dashboard template-status - Show template version info

    Args:
        command: The command to execute
        args: Additional arguments

    Returns:
        True if command handled, False otherwise
    """
    if command != "dashboard":
        return False

    subcmd = args[0] if args else ""

    if subcmd == "status":
        print_status()
        return True
    elif subcmd == "template":
        print_template()
        return True
    elif subcmd == "refresh":
        _handle_refresh(args[1:])
        return True
    elif subcmd == "push-template":
        _handle_push_template(args[1:])
        return True
    elif subcmd == "diff-template":
        _handle_diff_template(args[1:])
        return True
    elif subcmd == "template-status":
        _handle_template_status()
        return True
    else:
        print_help()
        return True


def main():
    """Main entry point"""
    args = sys.argv[1:] if len(sys.argv) > 1 else []

    # No args = show introspection
    if not args:
        print_introspection()
        return

    # --help = show commands
    if "--help" in args or "-h" in args:
        print_help()
        return

    command = args[0].lower()
    remaining_args = args[1:]

    if not handle_command(command, remaining_args):
        console.print(f"[red]Unknown command: {command}[/red]")
        print_help()


if __name__ == "__main__":
    main()
