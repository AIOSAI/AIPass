# ===================AIPASS====================
# META DATA HEADER
# Name: backup.py - Backup System Entry Point
# Date: 2025-11-22
# Version: 1.3.0
# Category: core/backup
#
# CHANGELOG (Max 5 entries):
#   - v1.3.0 (2026-03-06): Adapted for AIPass public repo
#     * Removed shebang, sys.path manipulation, prax/cli imports
#     * Replaced get_modules() with explicit relative imports
#     * Uses standard logging and rich console
#   - v1.2.0 (2026-02-22): Seed CLI flags standard: --version, backup all command
#   - v1.1.0 (2025-11-22): Fixed META header - correct filename, category, and standards
#   - v1.0.0 (2025-11-08): Initial version - modular architecture
#
# CODE STANDARDS:
#   - Handlers implement logic, modules orchestrate
# =============================================

"""
Backup System - Main Entry Point

Modular architecture with explicit module imports.
Main handles routing, modules implement functionality.
"""

# Standard library imports
import sys
import argparse
import logging
from pathlib import Path
from typing import Any, List

from rich.console import Console

logger = logging.getLogger(__name__)
console = Console()

# Explicit module imports (replaces dynamic discover_modules)
from aipass.backup.apps.modules import backup_core, google_drive_sync, integrations, reauth_drive


def get_modules():
    """Return list of modules with handle_command() interface"""
    modules = []
    for mod in [backup_core, google_drive_sync, integrations, reauth_drive]:
        if hasattr(mod, 'handle_command'):
            modules.append(mod)
    return modules


# =============================================================================
# CONSTANTS & CONFIG
# =============================================================================

# Module root (same directory as this file)
MODULE_ROOT = Path(__file__).parent

# =============================================================================
# COMMAND ROUTING
# =============================================================================

def route_command(args: argparse.Namespace, modules: List[Any]) -> bool:
    """
    Route command to appropriate module

    Args:
        args: Parsed command line arguments
        modules: List of discovered modules

    Returns:
        True if command was handled
    """
    for module in modules:
        try:
            if module.handle_command(args):
                return True
        except Exception as e:
            logger.error(f"Module error: {e}")

    return False

# =============================================================================
# INTROSPECTION DISPLAY
# =============================================================================

def print_introspection():
    """Display discovered modules - SEED pattern"""
    console.print()
    console.print("[bold cyan]Backup System - Automated File Protection[/bold cyan]")
    console.print()
    console.print("[dim]AIPass backup orchestration and versioning[/dim]")
    console.print()

    # Discover modules
    modules = get_modules()

    console.print(f"[yellow]Discovered Modules:[/yellow] {len(modules)}")
    console.print()

    for module in modules:
        module_name = module.__name__ if hasattr(module, '__name__') else str(module)
        # Extract just the module filename (last part)
        if '.' in module_name:
            module_name = module_name.split('.')[-1]
        console.print(f"  [cyan]•[/cyan] {module_name}")

    console.print()
    console.print("[dim]Run 'backup --help' for usage information[/dim]")
    console.print()


# =============================================================================
# MAIN
# =============================================================================

def show_version():
    """Print version from META DATA HEADER."""
    console.print("BACKUP_SYSTEM v1.2.0")


def main():
    """Main entry point - follows Seed CLI flags standard."""

    # 1. No args → introspection
    if len(sys.argv) == 1:
        print_introspection()
        return 0

    # 2. Universal flags (checked before command routing, execute and exit)
    if sys.argv[1] in ['--help', '-h', 'help']:
        console.print()
        console.print("[bold cyan]BACKUP_SYSTEM[/bold cyan] — Automated File Protection")
        console.print()
        console.print("[yellow]Commands:[/yellow]")
        console.print("  --all             Run snapshot + versioned + drive-sync (full backup cycle)")
        console.print("  snapshot          Create a system snapshot backup")
        console.print("  versioned         Create a versioned backup")
        console.print("  drive-test        Test Google Drive connectivity")
        console.print("  drive-sync        Sync backups to Google Drive")
        console.print("  drive-sync --test Run a small test sync to verify integration")
        console.print("  drive-stats       Show Drive file tracker statistics")
        console.print("  drive-clear-tracker  Clear Drive file tracker cache")
        console.print()
        console.print("[yellow]Options:[/yellow]")
        console.print("  --verbose, -v     Extra diagnostic output")
        console.print("  --dry-run         Preview what would happen, execute nothing")
        console.print("  --note NOTE       Add a backup note/description")
        console.print("  --project NAME    Project name for Drive sync (default: AIPass)")
        console.print("  --force           Force sync all files (ignore change tracker)")
        console.print("  --limit N         Limit drive-sync to first N files")
        console.print("  --version, -V     Show version and exit")
        console.print()
        return 0

    if sys.argv[1] in ['--version', '-V']:
        show_version()
        return 0

    # Normalize --all flag → 'all' command (so both syntaxes work)
    if sys.argv[1] == '--all':
        sys.argv[1] = 'all'

    # 3. Parse args (behavioral flags handled by argparse)
    parser = argparse.ArgumentParser(
        description='backup_system Branch Operations',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('command', nargs='?', help='Command to execute')
    parser.add_argument('path', nargs='?', default=None, help='Path argument (for sync commands)')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    parser.add_argument('--note', type=str, default='No note provided', help='Backup note/description')
    parser.add_argument('--dry-run', action='store_true', help='Scan files without copying (test mode)')
    parser.add_argument('--project', type=str, default='AIPass', help='Project name for Drive sync')
    parser.add_argument('--force', action='store_true', help='Force sync all files')
    parser.add_argument('--test', action='store_true', help='Run test mode (small test sync)')
    parser.add_argument('--limit', type=int, default=0, help='Limit sync to first N files (0 = no limit)')

    args = parser.parse_args()

    if not args.command:
        print_introspection()
        return 0

    # 4. Discover modules
    modules = get_modules()

    if not modules:
        console.print("❌ ERROR: No modules found")
        return 1

    # 5. Handle 'all' command: snapshot → versioned → drive-sync
    if args.command == 'all':
        console.print("[bold cyan]Full Backup Cycle: snapshot → versioned → drive-sync[/bold cyan]")
        console.print()

        # Step 1: Snapshot
        snapshot_args = argparse.Namespace(
            command='snapshot', path=None, verbose=args.verbose,
            note=args.note, dry_run=args.dry_run, project=args.project,
            force=args.force, test=False, limit=0
        )
        if not route_command(snapshot_args, modules):
            console.print("[red]Snapshot failed - aborting[/red]")
            return 1

        console.print()
        console.print("[dim]─── snapshot complete, starting versioned ───[/dim]")
        console.print()

        # Step 2: Versioned
        versioned_args = argparse.Namespace(
            command='versioned', path=None, verbose=args.verbose,
            note=args.note, dry_run=args.dry_run, project=args.project,
            force=args.force, test=False, limit=0
        )
        if not route_command(versioned_args, modules):
            console.print("[red]Versioned backup failed - aborting[/red]")
            return 1

        console.print()
        console.print("[dim]─── versioned complete, starting drive-sync ───[/dim]")
        console.print()

        # Step 3: Drive sync
        sync_args = argparse.Namespace(
            command='drive-sync', path=None, verbose=args.verbose,
            note=args.note, dry_run=args.dry_run, project=args.project,
            force=args.force, test=False, limit=args.limit
        )
        if not route_command(sync_args, modules):
            console.print("[red]Drive sync failed[/red]")
            return 1

        console.print()
        console.print("[green]Full backup cycle complete[/green]")
        return 0

    # 6. Route command to modules
    if route_command(args, modules):
        return 0
    else:
        console.print(f"❌ ERROR: Unknown command: {args.command}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
