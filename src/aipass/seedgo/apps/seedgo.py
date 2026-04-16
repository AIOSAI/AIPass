# =================== AIPass ====================
# Name: seedgo.py
# Description: SEEDGO - Standards Platform for AIPass
# Version: 2.0.0
# Created: 2026-03-05
# Modified: 2026-03-09
# =============================================

"""
SEEDGO - Standards Platform for AIPass

Routes commands to seedgo modules for standards compliance.
- 'audit aipass' → standards_audit module (pack-aware compliance scanning)
- 'standards_query aipass_standards architecture' → content query module
- Modules auto-discovered from modules/ directory
"""

import sys
import importlib.util
from pathlib import Path
from typing import List, Any

from aipass.prax import logger
from aipass.cli import console, header
from aipass.cli.apps.modules import error

VERSION = "2.0.0"
SEEDGO_ROOT = Path(__file__).parent
MODULES_DIR = SEEDGO_ROOT / "modules"


# =============================================================================
# MODULE DISCOVERY
# =============================================================================


def discover_modules() -> List[Any]:
    """Auto-discover seedgo-level modules in modules/ directory."""
    modules = []

    if not MODULES_DIR.exists():
        return modules

    for file_path in sorted(MODULES_DIR.glob("*.py")):
        if file_path.name.startswith("_"):
            continue

        try:
            spec = importlib.util.spec_from_file_location(file_path.stem, file_path)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            if hasattr(module, "handle_command"):
                modules.append(module)
        except Exception as e:
            logger.error(f"[SEEDGO] Failed to load module {file_path.stem}: {e}")

    return modules


def route_command(command: str, args: List[str], modules: List[Any]) -> bool:
    """Route command to appropriate module."""
    for module in modules:
        try:
            if module.handle_command(command, args):
                return True
        except Exception as e:
            logger.error(f"[SEEDGO] Module error: {e}")
    return False


# =============================================================================
# PACK DISCOVERY (handler-based)
# =============================================================================


def discover_handler_packs() -> list:
    """Discover checker packs from handlers/*_standards/ directories.

    Returns list of dicts with name, path, check_count, content_count.
    Used by introspection and help displays.
    """
    handlers_dir = SEEDGO_ROOT / "handlers"
    packs = []
    if not handlers_dir.exists():
        return packs
    for d in sorted(handlers_dir.iterdir()):
        if not d.is_dir() or not d.name.endswith("_standards"):
            continue
        check_files = list(d.glob("*_check.py"))
        content_files = list(d.glob("*_content.py"))
        if check_files:
            packs.append(
                {
                    "name": d.name,
                    "path": d,
                    "check_count": len(check_files),
                    "content_count": len(content_files),
                }
            )
    return packs


# =============================================================================
# DISPLAY
# =============================================================================


def print_introspection() -> None:
    """Display discovered modules and handler packs."""
    modules = discover_modules()
    packs = discover_handler_packs()

    console.print()
    console.print("[bold cyan]SEEDGO - Standards Platform for AIPass[/bold cyan]")
    console.print(f"  Version: {VERSION}")
    console.print()

    # Discovered modules
    console.print(f"[yellow]Discovered Modules:[/yellow] {len(modules)}")
    for module in modules:
        name = getattr(module, "__name__", "unknown").split(".")[-1]
        desc = (module.__doc__ or "").strip().split("\n")[0] if module.__doc__ else "No description"
        console.print(f"  [cyan]•[/cyan] {name} — {desc}")
    if not modules:
        console.print("  [dim]No modules discovered[/dim]")
    console.print()

    # Discovered handler packs
    if packs:
        console.print(f"[yellow]Checker Packs:[/yellow] {len(packs)}")
        for pack in packs:
            console.print(
                f"  [cyan]•[/cyan] {pack['name']} "
                f"({pack['check_count']} checkers, {pack['content_count']} content modules)"
            )
        console.print()

    console.print("[yellow]Next:[/yellow]  Explore a module")
    console.print("  [green]drone @seedgo standards_query[/green]       [dim]# Browse standards content[/dim]")
    console.print("  [green]drone @seedgo audit aipass[/green]          [dim]# Run compliance audit[/dim]")
    console.print("  [green]drone @seedgo checklist <file>[/green]      [dim]# Per-standard checklist on a file[/dim]")
    console.print("  [green]drone @seedgo --help[/green]                [dim]# Full usage guide[/dim]")
    console.print()


def print_help() -> None:
    """Show seedgo help with usage and available commands."""
    packs = discover_handler_packs()

    console.print()
    header("SEEDGO - Standards Platform for AIPass")
    console.print()
    console.print("[dim]Code standards reference and automated compliance for all AIPass branches[/dim]")
    console.print()
    console.print("─" * 70)
    console.print()

    # What is seedgo
    console.print("[bold cyan]WHAT IS SEEDGO?[/bold cyan]")
    console.print()
    console.print("Seedgo is the [bold]AIPass Standards Platform[/bold] — it:")
    console.print("  [green]✓[/green] Provides [green]queryable code standards[/green] via content modules")
    console.print("  [green]✓[/green] Runs automated checkers that score files 0-100 per standard")
    console.print("  [green]✓[/green] Audits all branches with a single command")
    console.print("  [green]✓[/green] Supports bypass rules for deliberate exceptions")
    console.print()

    # Handler packs
    if packs:
        console.print("[bold cyan]CHECKER PACKS:[/bold cyan]")
        console.print()
        for pack in packs:
            console.print(
                f"  [cyan]•[/cyan] {pack['name']}  "
                f"({pack['check_count']} checkers, {pack['content_count']} content modules)"
            )
        console.print()

    console.print("─" * 70)
    console.print()

    # Usage
    console.print("[bold cyan]USAGE:[/bold cyan]")
    console.print()

    console.print("[yellow]Audit:[/yellow]")
    console.print(
        "  [green]drone @seedgo audit[/green]                          [dim]# Show available checker packs[/dim]"
    )
    console.print("  [green]drone @seedgo audit aipass[/green]                   [dim]# Audit all branches[/dim]")
    console.print("  [green]drone @seedgo audit aipass @flow[/green]             [dim]# Audit single branch[/dim]")
    console.print()

    console.print("[yellow]Query Standards:[/yellow]")
    console.print("  [green]drone @seedgo standards_query[/green]                [dim]# List available packs[/dim]")
    console.print(
        "  [green]drone @seedgo standards_query aipass_standards[/green]        [dim]# List standards in pack[/dim]"
    )
    console.print(
        "  [green]drone @seedgo standards_query aipass_standards cli[/green]    [dim]# Show standard content[/dim]"
    )
    console.print()

    console.print("[yellow]Checklist:[/yellow]")
    console.print(
        "  [green]drone @seedgo checklist[/green]                      [dim]# Show checklist introspection[/dim]"
    )
    console.print(
        "  [green]drone @seedgo checklist <file>[/green]               [dim]# Run per-standard checklist on file[/dim]"
    )
    console.print()

    console.print("[yellow]Diagnostics:[/yellow]")
    console.print(
        "  [green]drone @seedgo diagnostics[/green]                    [dim]# Pyright errors across all branches[/dim]"
    )
    console.print(
        "  [green]drone @seedgo diagnostics @flow[/green]              [dim]# Single branch diagnostics[/dim]"
    )
    console.print()

    console.print("[yellow]Proof (Self-Check):[/yellow]")
    console.print(
        "  [green]drone @seedgo proof[/green]                          [dim]# List available proof packs[/dim]"
    )
    console.print(
        "  [green]drone @seedgo proof aipass[/green]                   [dim]# Run all proofs for aipass pack[/dim]"
    )
    console.print("  [green]drone @seedgo proof_query[/green]                    [dim]# Query proof pack content[/dim]")
    console.print()

    console.print("[yellow]Test Map:[/yellow]")
    console.print(
        "  [green]drone @seedgo test_map @flow[/green]                 [dim]# Function test coverage map for branch[/dim]"
    )
    console.print()

    console.print("─" * 70)
    console.print()

    # Commands line for drone discovery
    console.print(
        "[dim]Commands: audit, standards_audit, standards_query, checklist, diagnostics, diagnostics_audit, proof, proof_query, test_map, readme, readme_update, --help[/dim]"
    )
    console.print()


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================


def main() -> int:
    """Main entry point - routes to modules."""
    try:
        modules = discover_modules()
        args = sys.argv[1:]

        # No args → introspection (discovery mode)
        if not args:
            print_introspection()
            return 0

        # Help flag → full help with usage
        if args[0] in ["--help", "-h", "help"]:
            print_help()
            return 0

        if args[0] in ["--version", "-V"]:
            console.print(f"seedgo v{VERSION}")
            return 0

        command = args[0]
        remaining = args[1:] if len(args) > 1 else []

        # Route to modules
        if route_command(command, remaining, modules):
            return 0

        error(f"Unknown command: {command}", suggestion="Run 'seedgo --help' for usage")
        return 1
    except Exception as exc:
        logger.error("[seedgo] Unhandled error in main: %s", exc)
        raise


if __name__ == "__main__":
    sys.exit(main())
