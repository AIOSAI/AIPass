# =================== AIPass ====================
# Name: backup.py
# Description: Entry point CLI for drone @backup
# Version: 1.2.0
# Created: 2026-03-08
# Modified: 2026-03-08
# =============================================

"""
Backup System - Main Entry Point

Modular architecture with explicit module imports.
Main handles routing, modules implement functionality.
"""

# Standard library imports
import sys
import argparse
from pathlib import Path
from collections.abc import Sequence
from typing import Any

from aipass.cli.apps.modules import console, error
from aipass.prax import logger

# Explicit module imports (replaces dynamic discover_modules)
from aipass.backup.apps.modules import backup_core, google_drive_sync


def get_modules():
    """Return list of modules with handle_command() interface"""
    modules = []
    for mod in [backup_core, google_drive_sync]:
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

def _dispatch_to_module(module, args, pre_scanned):
    """Call module.handle_command, passing pre_scanned only if supported."""
    if not pre_scanned:
        return module.handle_command(args)
    try:
        return module.handle_command(args, pre_scanned=pre_scanned)
    except TypeError as e:
        logger.info(f"Module {getattr(module, '__name__', '?')} does not accept pre_scanned: {e}")
        return module.handle_command(args)


def route_command(args: argparse.Namespace, modules: Sequence[Any], pre_scanned=None) -> bool:
    """
    Route command to appropriate module

    Args:
        args: Parsed command line arguments
        modules: List of discovered modules
        pre_scanned: Optional pre-scanned file list to pass through to backup_core.

    Returns:
        True if command was handled
    """
    for module in modules:
        try:
            handled = _dispatch_to_module(module, args, pre_scanned)
            if handled:
                return True
        except Exception as e:
            # Show the actual error — don't mask it behind "Unknown command"
            module_name = getattr(module, '__name__', str(module)).split('.')[-1]
            logger.error(f"Module error in {module_name}: {e}")
            error(f"{module_name} failed: {e}")
            return True  # Command was handled (by crashing) — don't show "Unknown command"

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
    console.print("backup v1.2.0")


def main():
    """Main entry point - follows Seed CLI flags standard."""

    # 1. No args → introspection
    if len(sys.argv) == 1:
        print_introspection()
        return 0

    # 2. Universal flags (checked before command routing, execute and exit)
    if sys.argv[1] in ['--help', '-h', 'help']:
        console.print()
        console.print("[bold cyan]backup[/bold cyan] — Automated File Protection")
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
        description='backup Branch Operations',
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
        error("No modules found")
        return 1

    # 5. Handle 'all' command: snapshot → versioned → drive-sync
    if args.command == 'all':
        console.print("[bold cyan]Full Backup Cycle: snapshot → versioned → drive-sync[/bold cyan]")
        console.print()

        # Scan files ONCE and share between snapshot + versioned (saves ~20s)
        console.print("[dim]Scanning files...[/dim]")
        pre_scanned = backup_core.scan_source_files()
        console.print(f"[dim]Found {len(pre_scanned[0])} files to process[/dim]")
        console.print()

        # Step 1: Snapshot (reuses pre-scanned files)
        snapshot_args = argparse.Namespace(
            command='snapshot', path=None, verbose=args.verbose,
            note=args.note, dry_run=args.dry_run, project=args.project,
            force=args.force, test=False, limit=0
        )
        if not route_command(snapshot_args, modules, pre_scanned=pre_scanned):
            error("Snapshot failed - aborting")
            return 1

        console.print()
        console.print("[dim]─── snapshot complete, starting versioned ───[/dim]")
        console.print()

        # Step 2: Versioned (reuses pre-scanned files)
        versioned_args = argparse.Namespace(
            command='versioned', path=None, verbose=args.verbose,
            note=args.note, dry_run=args.dry_run, project=args.project,
            force=args.force, test=False, limit=0
        )
        if not route_command(versioned_args, modules, pre_scanned=pre_scanned):
            error("Versioned backup failed - aborting")
            return 1

        console.print()
        console.print("[dim]─── versioned complete, starting drive-sync ───[/dim]")
        console.print()

        # Step 3: Drive sync (skip in dry-run — no point uploading nothing)
        if args.dry_run:
            console.print("[dim]Drive sync skipped (dry-run mode)[/dim]")
        else:
            sync_args = argparse.Namespace(
                command='drive-sync', path=None, verbose=args.verbose,
                note=args.note, dry_run=args.dry_run, project=args.project,
                force=args.force, test=False, limit=args.limit
            )
            if not route_command(sync_args, modules):
                error("Drive sync failed")
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
