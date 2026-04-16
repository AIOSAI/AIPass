# =================== AIPass ====================
# Name: templates.py
# Description: Living Template Orchestration Module
# Version: 0.2.0
# Created: 2026-02-14
# Modified: 2026-03-15
# =============================================

"""
Living Template Orchestration Module

Coordinates template management workflow by calling handlers:
1. Push template structural updates to branches (pusher)
2. Diff template vs branch state (differ)
3. Show template version and push status (pusher)

Purpose:
    Thin orchestration layer - no business logic implementation.
    All domain logic lives in handlers (pusher.py, differ.py).
"""

import sys
from pathlib import Path
from typing import List

from rich.panel import Panel
from rich import box

from aipass.prax import logger
from aipass.cli.apps.modules import console, error, warning
from aipass.memory.apps.handlers.json import json_handler

# =============================================================================
# INFRASTRUCTURE SETUP
# =============================================================================

# Handler imports (domain-organized)
from aipass.memory.apps.handlers.templates.pusher import push_templates, get_template_status
from aipass.memory.apps.handlers.templates.differ import diff_template_vs_branch
from aipass.memory.apps.handlers.templates.spawn_pusher import push_to_spawn_templates
from aipass.memory.apps.handlers.json.memory_files import read_memory_file_data


def _find_repo_root() -> Path:
    """Walk up from this file to find repo root (contains AIPASS_REGISTRY.json)."""
    current = Path(__file__).resolve().parent
    for parent in [current] + list(current.parents):
        if (parent / "AIPASS_REGISTRY.json").exists():
            return parent
    return Path.cwd()


_REPO_ROOT = _find_repo_root()
REGISTRY_PATH = _REPO_ROOT / "AIPASS_REGISTRY.json"


# =============================================================================
# COMMAND HANDLERS
# =============================================================================

_SUBCOMMANDS = {
    "push-templates": "Push template updates to all branches",
    "diff-templates": "Show template differences per branch",
    "template-status": "Show template version and push status",
}


def handle_command(command: str, args: List[str]) -> bool:
    """
    Handle living template commands with seedgo-compliant introspection.

    Routing:
        templates (no args)        -> print_introspection()
        templates --help/-h/help   -> print_help()
        templates push-templates   -> push template updates
        templates diff-templates   -> show template diffs
        templates template-status  -> show template status

    Backward-compatible top-level commands (routed from entry point):
        push-templates, diff-templates, template-status -> forwarded directly

    Args:
        command: Command name
        args: Additional arguments

    Returns:
        True if command handled, False otherwise
    """
    # Top-level help (backward compat -- entry point may send these)
    if command in ("--help", "-h", "help"):
        print_help()
        return True

    if command == "templates":
        # No args -> introspection (seedgo standard)
        if not args:
            print_introspection()
            return True

        # --help / -h / help -> full help
        if args[0] in ("--help", "-h", "help"):
            print_help()
            return True

        # Subcommand routing
        sub = args[0]
        remaining = args[1:]

        if sub == "push-templates":
            dry_run = "--dry-run" in remaining
            try:
                _display_push_results(push_templates(dry_run=dry_run), dry_run)
            except Exception as e:
                error(f"Template push crashed: {e}")
                logger.error(f"[templates] push-templates crashed: {e}")
            # Also push to spawn templates
            try:
                _display_spawn_push_results(push_to_spawn_templates(dry_run=dry_run), dry_run)
            except Exception as e:
                error(f"Spawn template push crashed: {e}")
                logger.error(f"[templates] spawn push crashed: {e}")
            return True

        if sub == "diff-templates":
            branch_name: str | None = None
            i = 0
            while i < len(remaining):
                if remaining[i] == "--branch" and i + 1 < len(remaining):
                    branch_name = remaining[i + 1]
                    i += 2
                else:
                    i += 1
            _display_diff_results(branch_name)
            return True

        if sub == "template-status":
            try:
                _display_status(get_template_status())
            except Exception as e:
                error(f"Template status failed: {e}")
                logger.error(f"[templates] template-status crashed: {e}")
            return True

        # Unknown subcommand
        error(
            f"Unknown subcommand: '{sub}'",
            suggestion="Available: " + ", ".join(_SUBCOMMANDS.keys()),
        )
        return True

    # Backward-compatible top-level commands (entry point still routes these)
    if command == "push-templates":
        dry_run = "--dry-run" in args
        try:
            _display_push_results(push_templates(dry_run=dry_run), dry_run)
        except Exception as e:
            error(f"Template push crashed: {e}")
            logger.error(f"[templates] push-templates crashed: {e}")
        # Also push to spawn templates
        try:
            _display_spawn_push_results(push_to_spawn_templates(dry_run=dry_run), dry_run)
        except Exception as e:
            error(f"Spawn template push crashed: {e}")
            logger.error(f"[templates] spawn push crashed: {e}")
        return True

    elif command == "diff-templates":
        branch_name = None
        i = 0
        while i < len(args):
            if args[i] == "--branch" and i + 1 < len(args):
                branch_name = args[i + 1]
                i += 2
            else:
                i += 1
        _display_diff_results(branch_name)
        return True

    elif command == "template-status":
        try:
            _display_status(get_template_status())
        except Exception as e:
            error(f"Template status failed: {e}")
            logger.error(f"[templates] template-status crashed: {e}")
        return True

    return False


def print_help() -> None:
    """Display templates module help"""
    console.print()
    console.print(
        Panel.fit(
            "[bold cyan]Templates Module - Living Template Management[/bold cyan]", border_style="cyan", box=box.ROUNDED
        )
    )
    console.print()
    console.print("[bold]USAGE:[/bold]")
    console.print("  drone @memory templates <command>")
    console.print()
    console.print("[bold]COMMANDS:[/bold]")
    console.print("  [cyan]push-templates[/cyan]              Push template updates to all branches")
    console.print("  [cyan]push-templates --dry-run[/cyan]    Preview changes without writing")
    console.print("  [cyan]diff-templates[/cyan]              Show template differences per branch")
    console.print("  [cyan]diff-templates --branch NAME[/cyan]  Diff a specific branch")
    console.print("  [cyan]template-status[/cyan]             Show template version and push status")
    console.print("  [cyan]help[/cyan]                        Show this help message")
    console.print()


# =============================================================================
# DISPLAY: PUSH RESULTS
# =============================================================================


def _display_push_results(result: dict, dry_run: bool) -> None:
    """Format and display push_templates() handler result."""
    console.print()
    mode_label = "DRY RUN" if dry_run else "Push"
    console.print(
        Panel.fit(f"[bold cyan]Memory - Template {mode_label}[/bold cyan]", border_style="cyan", box=box.ROUNDED)
    )
    console.print()

    if dry_run:
        console.print("[yellow]DRY RUN MODE[/yellow] - no files will be modified")
        console.print()

    if not result.get("success"):
        error("Template push failed")
        for err in result.get("errors", []):
            error(err)
        logger.error(f"[templates] Push failed: {result.get('errors')}")
        console.print()
        return

    # Summary
    console.print(f"[cyan]Branches scanned:[/cyan]  {result['branches_scanned']}")
    console.print(f"[cyan]Branches updated:[/cyan]  {result['branches_updated']}")
    console.print(f"[cyan]Files modified:[/cyan]    {result['files_modified']}")
    console.print()

    # Change details per branch/file
    changes = result.get("changes", [])
    if changes:
        console.print(f"[yellow]Changes ({len(changes)} files):[/yellow]")
        console.print()
        for entry in changes:
            branch = entry.get("branch", "UNKNOWN")
            file_name = entry.get("file", "unknown")
            file_changes = entry.get("changes", [])
            console.print(f"  [bold]{branch}[/bold]/{file_name}:")
            for chg in file_changes:
                console.print(f"    [green]+[/green] {chg}")
            console.print()
    else:
        console.print("[green]All branches are up to date with templates.[/green]")
        console.print()

    # Errors
    errors = result.get("errors", [])
    if errors:
        console.print(f"[red]Errors ({len(errors)}):[/red]")
        for err in errors:
            error(err)
        console.print()
        logger.error(f"[templates] Push completed with {len(errors)} errors")

    # Final status
    if result["branches_updated"] > 0 and not dry_run:
        console.print(
            f"[green]Template push complete:[/green] "
            f"{result['branches_updated']}/{result['branches_scanned']} branches updated"
        )
    elif dry_run and changes:
        console.print(f"[yellow]Dry run complete:[/yellow] {result['branches_updated']} branches would be updated")
    else:
        console.print("[green]No updates needed.[/green]")

    logger.info(
        f"[templates] Push {'(dry run) ' if dry_run else ''}complete: "
        f"{result['branches_updated']}/{result['branches_scanned']} branches, "
        f"{result['files_modified']} files"
    )
    json_handler.log_operation(
        "templates_push", {"branches_updated": result["branches_updated"], "files_modified": result["files_modified"]}
    )
    console.print()


# =============================================================================
# DISPLAY: SPAWN PUSH RESULTS
# =============================================================================


def _display_spawn_push_results(result: dict, dry_run: bool) -> None:
    """Format and display spawn template push results."""
    if not result.get("success"):
        for err in result.get("errors", []):
            error(f"Spawn push: {err}")
        return

    sets_found = result.get("template_sets_found", [])
    sets_updated = result.get("template_sets_updated", 0)
    files_mod = result.get("files_modified", 0)

    if files_mod == 0 and not result.get("changes"):
        console.print("[dim]Spawn templates: already up to date[/dim]")
        return

    mode = "would update" if dry_run else "updated"
    console.print(f"[cyan]Spawn templates:[/cyan] {sets_updated}/{len(sets_found)} sets {mode}, {files_mod} files")
    for change in result.get("changes", []):
        console.print(
            f"  [green]+[/green] {change.get('template_set')}/{change.get('file')} [dim]({change.get('action')})[/dim]"
        )

    logger.info(
        f"[templates] Spawn push {'(dry run) ' if dry_run else ''}complete: "
        f"{sets_updated}/{len(sets_found)} sets, {files_mod} files"
    )


# =============================================================================
# DISPLAY: DIFF RESULTS
# =============================================================================


def _display_diff_results(branch_name: str | None = None) -> None:
    """
    Call differ handler for all/specific branches, display results.

    Args:
        branch_name: Optional branch name filter (None = all branches)
    """
    console.print()
    console.print(Panel.fit("[bold cyan]Memory - Template Diff[/bold cyan]", border_style="cyan", box=box.ROUNDED))
    console.print()

    # Load registry to get branch paths
    branches = _load_branches_from_registry()
    if branches is None:
        error("Failed to load AIPASS_REGISTRY.json")
        logger.error("[templates] Failed to load AIPASS_REGISTRY.json for diff")
        console.print()
        return

    # Filter if branch specified
    if branch_name:
        branches = [b for b in branches if b.get("name", "").upper() == branch_name.upper()]
        if not branches:
            error(f"Branch not found: {branch_name}")
            console.print()
            return
        console.print(f"[cyan]Diffing branch:[/cyan] {branch_name.upper()}")
    else:
        console.print(f"[cyan]Diffing all {len(branches)} active branches...[/cyan]")
    console.print()

    total_diffs = 0
    total_errors = 0

    for branch in branches:
        name = branch.get("name", "UNKNOWN")
        path = branch.get("path", "")

        if not path or not Path(path).exists():
            error(f"{name}: path not found ({path})")
            logger.warning(f"[templates] Branch path not found: {name} ({path})")
            total_errors += 1
            continue

        # Call handler
        try:
            result = diff_template_vs_branch(path)
        except Exception as e:
            error(f"{name}: handler error: {e}")
            logger.error(f"[templates] Diff handler crashed for {name}: {e}")
            total_errors += 1
            continue

        local_diffs = result.get("local", [])
        obs_diffs = result.get("observations", [])
        errors = result.get("errors", [])
        branch_has_diffs = bool(local_diffs or obs_diffs)

        if branch_has_diffs:
            total_diffs += 1
        if errors:
            total_errors += len(errors)

        # Display branch results
        if branch_has_diffs:
            console.print(f"  [bold yellow]{name}[/bold yellow]")
            _display_file_diffs(local_diffs)
            _display_file_diffs(obs_diffs)
            console.print()
        elif not errors:
            console.print(f"  [green]{name}[/green]: up to date")

        for err in errors:
            error(f"{name}: {err}")
            logger.warning(f"[templates] Diff error for {name}: {err}")

    # Summary
    console.print()
    if total_diffs == 0 and total_errors == 0:
        console.print("[green]All branches are up to date with templates.[/green]")
    else:
        if total_diffs > 0:
            warning(f"{total_diffs} branches have template differences")
            console.print("[dim]Run 'push-templates --dry-run' to preview changes[/dim]")
        if total_errors > 0:
            console.print(f"[red]{total_errors} errors encountered[/red]")

    logger.info(f"[templates] Diff complete: {total_diffs} branches with diffs, {total_errors} errors")
    json_handler.log_operation(
        "templates_diff", {"branches_compared": len(branches), "branches_with_diffs": total_diffs}
    )
    console.print()


def _display_file_diffs(file_diffs: list) -> None:
    """Display diff entries for a list of files."""
    for entry in file_diffs:
        console.print(f"    [dim]{entry['file']}:[/dim]")
        if entry.get("additions"):
            for a in entry["additions"]:
                console.print(f"      [green]+ {a}[/green]")
        if entry.get("removals"):
            for r in entry["removals"]:
                console.print(f"      [red]- {r}[/red]")
        if entry.get("modifications"):
            for m in entry["modifications"]:
                console.print(f"      [yellow]~ {m}[/yellow]")


# =============================================================================
# DISPLAY: STATUS
# =============================================================================


def _display_status(status: dict) -> None:
    """Format and display get_template_status() handler result."""
    console.print()
    console.print(Panel.fit("[bold cyan]Memory - Template Status[/bold cyan]", border_style="cyan", box=box.ROUNDED))
    console.print()

    # Template files
    local_icon = "[green]found[/green]" if status.get("local_template_exists") else "[red]MISSING[/red]"
    obs_icon = "[green]found[/green]" if status.get("observations_template_exists") else "[red]MISSING[/red]"

    console.print(f"[cyan]Templates directory:[/cyan]  {status.get('templates_dir', 'unknown')}")
    console.print(f"[cyan]LOCAL template:[/cyan]      {local_icon}")
    console.print(f"[cyan]OBS template:[/cyan]        {obs_icon}")
    console.print()

    # Version info
    version = status.get("version") or "unknown"
    last_push = status.get("last_push") or "never"
    console.print(f"[cyan]Schema version:[/cyan]     {version}")
    console.print(f"[cyan]Last push:[/cyan]          {last_push}")

    # Branches pushed
    pushed = status.get("last_push_branches", [])
    if pushed:
        preview = ", ".join(pushed[:8])
        suffix = f"... (+{len(pushed) - 8} more)" if len(pushed) > 8 else ""
        console.print(f"[cyan]Branches pushed:[/cyan]    {len(pushed)} ({preview}{suffix})")
    else:
        console.print("[cyan]Branches pushed:[/cyan]    none")

    logger.info(f"[templates] Status checked - version: {version}, last push: {last_push}")
    json_handler.log_operation("templates_status", {"version": version, "branches_pushed": len(pushed)})
    console.print()


# =============================================================================
# HELPERS
# =============================================================================


def _load_branches_from_registry() -> list | None:
    """
    Load active branches from AIPASS_REGISTRY.json.

    Registry paths are relative -- resolved against repo root.

    Returns:
        List of branch dicts or None on error
    """
    if not REGISTRY_PATH.exists():
        return None
    try:
        data = read_memory_file_data(REGISTRY_PATH)
        if data is None:
            return None
        branches = data.get("branches", [])
        # Resolve relative paths against repo root
        for branch in branches:
            raw_path = branch.get("path", "")
            resolved = Path(raw_path)
            if not resolved.is_absolute():
                resolved = _REPO_ROOT / raw_path
            branch["path"] = str(resolved)
        return [b for b in branches if b.get("status") == "active"]
    except Exception as e:
        logger.error(f"[templates] Failed to load AIPASS_REGISTRY.json: {e}")
        return None


# =============================================================================
# INTROSPECTION
# =============================================================================


def _discover_handlers() -> dict[str, list[str]]:
    """Auto-discover handler directories and their Python files.

    Scans the handlers/ directory relative to this module.

    Returns:
        Dict mapping handler directory name to list of .py filenames
        (excluding __init__.py and __pycache__).
    """
    handlers_dir = Path(__file__).resolve().parent.parent / "handlers"
    result: dict[str, list[str]] = {}
    if not handlers_dir.exists():
        return result
    for d in sorted(handlers_dir.iterdir()):
        if not d.is_dir() or d.name.startswith("__"):
            continue
        py_files = sorted(f.name for f in d.iterdir() if f.is_file() and f.suffix == ".py" and f.name != "__init__.py")
        if py_files:
            result[d.name] = py_files
    return result


def print_introspection() -> None:
    """Display module introspection info (seedgo standard).

    Called when 'templates' is invoked with no arguments.
    Shows module identity, connected handlers, available subcommands,
    and next-step hints.
    """
    console.print()
    console.print("[bold cyan]templates Module[/bold cyan]")
    console.print("Orchestrates living template management: push structural updates, diff branches, and check status")
    console.print()

    # Connected handlers (auto-discovered)
    handlers = _discover_handlers()
    console.print("[yellow]Connected Handlers:[/yellow]")
    if handlers:
        for dir_name, files in handlers.items():
            file_list = ", ".join(files)
            console.print(f"  [cyan]handlers/{dir_name}/[/cyan]  [dim]{file_list}[/dim]")
    else:
        console.print("  [dim]No handlers found[/dim]")
    console.print()

    # Available subcommands
    console.print("[yellow]Subcommands:[/yellow]")
    for sub, desc in _SUBCOMMANDS.items():
        console.print(f"  [green]{sub:<20}[/green] {desc}")
    console.print()

    # Next-step hints
    console.print("[yellow]Next:[/yellow]")
    console.print("  [green]drone @memory templates push-templates[/green]          [dim]# Push updates[/dim]")
    console.print("  [green]drone @memory templates diff-templates[/green]          [dim]# View diffs[/dim]")
    console.print("  [green]drone @memory templates template-status[/green]         [dim]# Check status[/dim]")
    console.print("  [green]drone @memory templates --help[/green]                  [dim]# Full usage guide[/dim]")
    console.print()


# =============================================================================
# STANDALONE EXECUTION
# =============================================================================

if __name__ == "__main__":
    import sys

    # No args -> introspection (seedgo standard)
    if len(sys.argv) < 2:
        handle_command("templates", [])
        sys.exit(0)

    # --help -> full help
    if sys.argv[1] in ("--help", "-h", "help"):
        handle_command("templates", ["--help"])
        sys.exit(0)

    # Execute command via handle_command
    command = sys.argv[1]
    if not handle_command(command, sys.argv[2:]):
        console.print(f"[red]Unknown command:[/red] {command}")
        console.print("Run with [cyan]help[/cyan] for available commands")
        sys.exit(1)
