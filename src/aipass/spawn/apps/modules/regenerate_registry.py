# =================== AIPass ====================
# Name: regenerate_registry.py
# Description: CLI module for regenerating template registries
# Version: 1.0.0
# Created: 2026-03-25
# Modified: 2026-03-25
# =============================================

"""Regenerate template registry — thin CLI layer.

Parses arguments and delegates to regenerate_registry_ops handler.
All implementation logic lives in apps/handlers/regenerate_registry_ops.py.
"""

from aipass.prax import logger
from aipass.cli.apps.modules import console, error, warning

from aipass.spawn.apps.handlers.regenerate_registry_ops import regenerate_template_registry
from aipass.spawn.apps.handlers.class_registry import get_template_dir, get_available_classes
from aipass.spawn.apps.handlers.json import json_handler


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("regenerate_registry Module")
    console.print("Regenerate .template_registry.json for spawn template directories")
    console.print()
    console.print("Connected Handlers:")
    console.print("  handlers/")
    console.print(
        "    - regenerate_registry_ops.py (regenerate_template_registry — walk template, hash files, build registry)"
    )
    console.print()


# =============================================================================
# DRONE ROUTING
# =============================================================================


def handle_command(command: str, args: list) -> bool:
    """Handle commands routed by the entry point.

    Args:
        command: The command string (e.g. "regenerate-registry")
        args: List of arguments for the command

    Returns:
        True if command was handled, False otherwise.
    """
    if command != "regenerate-registry":
        return False

    # No args → introspection
    if not args:
        print_introspection()
        return True

    if "--help" in args:
        print_introspection()
        return True

    return handle_regenerate_registry(args) == 0


# =============================================================================
# PUBLIC API
# =============================================================================


def handle_regenerate_registry(args: list[str]) -> int:
    """Parse args and execute template registry regeneration.

    Args patterns:
        []              -> regenerate builder (default)
        ["builder"]     -> regenerate builder template
        ["birthright"]  -> regenerate birthright template
        ["--all"]       -> regenerate all template registries
        ["--help"]      -> show help

    Returns exit code (0=success, 1=failure).
    """
    if args and args[0] in ["--help", "-h"]:
        _print_help()
        return 0

    regen_all = "--all" in args

    if regen_all:
        # Regenerate all known template classes
        classes = get_available_classes()
        all_results: list[dict] = []
        had_error = False

        for class_name in classes:
            try:
                template_dir = get_template_dir(class_name)
                result = regenerate_template_registry(template_dir)
                if "error" in result:
                    error(f"[{class_name}] {result['error']}")
                    had_error = True
                else:
                    all_results.append(result)
            except Exception as exc:
                logger.error(f"[regenerate-registry] Error for {class_name}: {exc}")
                error(f"[{class_name}] {exc}")
                had_error = True

        for result in all_results:
            _print_summary(result)

        if not had_error:
            json_handler.log_operation("regenerate_registry_all", data={"classes": list(classes)})
        return 1 if had_error else 0

    # Single class — default to builder
    clean_args = [a for a in args if not a.startswith("--")]
    class_name = clean_args[0] if clean_args else "builder"

    available = get_available_classes()
    if class_name not in available:
        error(
            f"Unknown template class '{class_name}'",
            suggestion=f"Available: {', '.join(available)}",
        )
        return 1

    try:
        template_dir = get_template_dir(class_name)
        result = regenerate_template_registry(template_dir)
    except Exception as exc:
        logger.error(f"[regenerate-registry] Unexpected error: {exc}")
        error(str(exc))
        return 1

    if "error" in result:
        error(result["error"])
        return 1

    _print_summary(result)
    json_handler.log_operation("regenerate_registry", data={"class": class_name})
    return 0


# =============================================================================
# OUTPUT HELPERS
# =============================================================================


def _print_help() -> None:
    """Print usage help for regenerate-registry command."""
    warning("Usage: drone @spawn regenerate-registry [class_name | --all]")
    console.print()
    console.print("  [green](no args)[/green]       Regenerate builder template registry (default)")
    console.print("  [green]<class>[/green]          Regenerate registry for a specific template class")
    console.print("  [green]--all[/green]            Regenerate registries for all template classes")
    console.print()
    console.print("[dim]Available classes:[/dim]")
    for cls in get_available_classes():
        console.print(f"  [green]{cls}[/green]")
    console.print()


def _print_summary(result: dict) -> None:
    """Print a rich summary of the registry regeneration."""
    stats = result.get("stats", {})
    name = stats.get("template_name", "unknown")
    files_tracked = stats.get("files_tracked", 0)
    dirs_tracked = stats.get("directories_tracked", 0)
    prev_files = stats.get("previous_files", 0)
    prev_dirs = stats.get("previous_directories", 0)
    registry_path = stats.get("registry_path", "")

    console.print()
    console.print(f"[bold]Registry Regenerated: {name}[/bold]")
    console.print()
    console.print(f"  Files tracked:       {files_tracked} [dim](was {prev_files})[/dim]")
    console.print(f"  Directories tracked: {dirs_tracked} [dim](was {prev_dirs})[/dim]")
    console.print(f"  Registry path:       [dim]{registry_path}[/dim]")

    # Show file list
    files = result.get("files", {})
    if files:
        console.print()
        console.print("  [bold cyan]Files:[/bold cyan]")
        for fid in sorted(files.keys()):
            finfo = files[fid]
            path = finfo.get("path", "")
            placeholder = " [yellow](placeholder)[/yellow]" if finfo.get("has_branch_placeholder") else ""
            console.print(f"    {fid}: {path}{placeholder}")

    # Show directory list
    directories = result.get("directories", {})
    if directories:
        console.print()
        console.print("  [bold cyan]Directories:[/bold cyan]")
        for did in sorted(directories.keys()):
            dinfo = directories[did]
            path = dinfo.get("path", "")
            placeholder = " [yellow](placeholder)[/yellow]" if dinfo.get("has_branch_placeholder") else ""
            console.print(f"    {did}: {path}{placeholder}")

    console.print()
