# =================== AIPass ====================
# Name: google_drive_sync.py
# Description: Google Drive Integration for AIPass Backup System
# Version: 2.6.0
# Created: 2025-10-30
# Modified: 2026-03-09
# =============================================

"""
Google Drive Sync Module - Orchestrates Drive backup operations.

Routes drive-sync commands, displays CLI output, delegates to
drive_sync_client handler for API operations.
"""

# =============================================
# IMPORTS
# =============================================

import sys
from pathlib import Path
from rich.progress import Progress, BarColumn, TextColumn, TimeElapsedColumn, TimeRemainingColumn
from aipass.cli.apps.modules import console
from aipass.cli.apps.modules.display import error, warning
from aipass.prax import logger

_BACKUP_ROOT = Path(__file__).resolve().parents[2]  # src/aipass/backup/

# =============================================
# CONSTANTS & CONFIG
# =============================================

# OAuth scopes for Drive access
SCOPES = ['https://www.googleapis.com/auth/drive.file']

# Module configuration
MODULE_NAME = "google_drive_sync"
JSON_DIR = _BACKUP_ROOT / "backup_json"
CONFIG_FILE = JSON_DIR / f"{MODULE_NAME}_config.json"
DATA_FILE = JSON_DIR / f"{MODULE_NAME}_data.json"
LOG_FILE = JSON_DIR / f"{MODULE_NAME}_log.json"

# =============================================
# CLIENT CLASS (delegated to handler)
# =============================================

try:
    from aipass.backup.apps.handlers.operations.drive_sync_client import (
        GoogleDriveSync,
    )
    from aipass.backup.apps.handlers.json.drive_sync_json import (
        load_config as _load_config_fn,
        load_data as _load_data_fn,
    )
    DRIVE_AVAILABLE = True
except ImportError:
    GoogleDriveSync = None  # type: ignore
    _load_config_fn = None  # type: ignore
    _load_data_fn = None  # type: ignore
    DRIVE_AVAILABLE = False
    logger.info("[google_drive_sync] Google Drive dependencies not available")

def _load_config():
    """Load config using module JSON paths."""
    return _load_config_fn(CONFIG_FILE)

def _load_data():
    """Load data using module JSON paths."""
    return _load_data_fn(DATA_FILE)


# =============================================
# BUSINESS OPERATIONS (delegated to handlers)
# =============================================

try:
    from aipass.backup.apps.handlers.operations.drive_sync_ops import (
        clear_file_tracker as _clear_file_tracker_handler,
        get_file_tracker_stats,
        test_drive_connection as _test_drive_connection,
    )
except ImportError:
    _clear_file_tracker_handler = None  # type: ignore
    get_file_tracker_stats = None  # type: ignore
    _test_drive_connection = None  # type: ignore

from aipass.backup.apps.handlers.operations.sync_test_ops import (
    create_sync_test_files,
    cleanup_sync_test_dir,
)


def _show_file_tracker_stats() -> bool:
    """Display file tracker statistics."""
    try:
        stats = get_file_tracker_stats()
        console.print(f"File Tracker Statistics:")
        console.print(f"  - Total tracked files: {stats['total']}")
        if stats['sample']:
            console.print(f"  - Sample entries:")
            for i, entry in enumerate(stats['sample']):
                console.print(f"    {i+1}. {entry['file']} (last sync: {entry['last_sync']})")
            if stats['truncated']:
                remaining = stats['total'] - len(stats['sample'])
                console.print(f"    ... and {remaining} more files")
        return True
    except Exception as e:
        error(f"Error showing tracker stats: {e}")
        logger.error(f"Error showing tracker stats: {e}")
        return False


def _clear_file_tracker() -> bool:
    """Clear the file tracker cache for fresh sync."""
    try:
        data = _load_data()
        tracker_count = len(data.get("runtime_state", {}).get("file_tracker", {}))
        success = _clear_file_tracker_handler()
        if success:
            console.print(f"Cleared {tracker_count} entries from file tracker")
            logger.info(f"Cleared {tracker_count} entries from file tracker")
        else:
            console.print("File tracker already empty or clear failed")
        return success
    except Exception as e:
        error(f"Error clearing file tracker: {e}")
        logger.error(f"Error clearing file tracker: {e}")
        return False


def _test_drive_sync() -> bool:
    """Test Drive integration."""
    try:
        sync = GoogleDriveSync()
        if not sync.authenticate():
            return False
        console.print("Testing folder creation...")
        result = _test_drive_connection(sync)
        if result:
            folder_id = sync.get_or_create_backup_folder()
            console.print(f"Backup folder ready: {folder_id}")
        else:
            error("Failed to create backup folder")
        return result
    except Exception as e:
        error(f"Test failed: {e}")
        logger.error(f"Test failed: {e}")
        return False

def _run_sync_test() -> bool:
    """Run a small test sync to verify Drive integration."""
    console.print("[bold cyan]Drive Sync Test[/bold cyan]")
    console.print()

    # Create test files via handler
    setup = create_sync_test_files(_BACKUP_ROOT)
    if not setup["success"]:
        error(f"Failed to create test files: {setup['error']}")
        return False

    test_dir = setup["test_dir"]
    console.print(f"  Created {setup['file_count']} test files in {test_dir}")

    # Run sync
    sync = GoogleDriveSync()
    if not sync.authenticate():
        error("Auth failed")
        cleanup_sync_test_dir(test_dir)
        return False

    console.print(f"\nScanning...")
    files_to_upload, skipped, total = sync.prepare_sync(test_dir, force_sync=True)
    upload_count = len(files_to_upload)

    console.print(f"  Files: {total} total, {upload_count} to upload")

    # Verify Drive folder before uploading
    console.print(f"\nVerifying Drive folder: AIPass_Test...")
    folder_id = sync.get_or_create_project_folder("AIPass_Test")
    if not folder_id:
        error_msg = sync.last_error or "Unknown error"
        error(f"FAILED: {error_msg}")
        cleanup_sync_test_dir(test_dir)
        return False
    console.print(f"  Drive folder ready: AIPass_Test")

    console.print(f"Uploading...")

    def show_test_progress(completed, total_upload, _successes):
        """Display test upload progress to console."""
        console.print(f"  {completed}/{total_upload}")

    result = sync.sync_backup_files(
        test_dir, "AIPass_Test", "sync test", True,
        prepared_files=files_to_upload,
        skipped_count=skipped,
        total_count=total,
        progress_fn=show_test_progress
    )

    if result.get("error"):
        error(f"FAILED: {result['error']}")
        cleanup_sync_test_dir(test_dir)
        return False

    console.print()
    if result["success"]:
        console.print(f"[green]Test passed: {result['uploaded']}/{result['total']} files synced[/green]")
    else:
        error(f"Test failed: {result['uploaded']} OK, {result['failed']} failed")

    # Run it again to verify no duplicates
    console.print(f"\nRe-running sync (should show 0 to upload)...")
    files_to_upload2, _, _ = sync.prepare_sync(test_dir, force_sync=False)

    if len(files_to_upload2) == 0:
        console.print(f"[green]Dedup check passed: 0 files need re-upload[/green]")
    else:
        error(f"Dedup check failed: {len(files_to_upload2)} files flagged for re-upload")

    # Cleanup local test dir via handler
    cleanup_sync_test_dir(test_dir)
    console.print(f"\nCleaned up local test files")
    console.print(f"[dim]Test Drive folder 'AIPass_Test' left on Drive for inspection[/dim]")

    return result["success"]


# =============================================
# HANDLE_COMMAND (Drone Integration)
# =============================================

def handle_command(args) -> bool:
    """Route Google Drive sync commands from backup_system orchestrator.

    Args:
        args: Command-line arguments from CLI parser

    Returns:
        bool: True if command was handled, False if not a drive sync command
    """
    if not hasattr(args, 'command'):
        return False

    command = args.command

    if command in ['--help', '-h', 'help']:
        console.print()
        console.print("[bold cyan]google_drive_sync - Google Drive Integration[/bold cyan]")
        console.print()
        console.print("Syncs AIPass backups to Google Drive using OAuth2.")
        console.print()
        console.print("[yellow]Commands:[/yellow]")
        console.print("  drive-test          - Test Google Drive connectivity")
        console.print("  drive-sync          - Sync backup directory to Google Drive")
        console.print("  drive-sync --test   - Run a small test sync to verify integration")
        console.print("  drive-clear-tracker - Clear file tracker cache")
        console.print("  drive-stats         - Show file tracker statistics")
        console.print()
        console.print("[yellow]Options:[/yellow]")
        console.print("  --project  Project name (default: AIPass)")
        console.print("  --note     Sync note (default: Manual sync)")
        console.print("  --force    Force upload all files")
        console.print()
        return True

    if command == 'drive-test':
        return _test_drive_sync()

    elif command == 'drive-sync':
        # --test flag routes to test mode
        if getattr(args, 'test', False):
            return _run_sync_test()

        raw_path = getattr(args, 'path', None)
        if raw_path:
            backup_path = Path(raw_path)
        else:
            # Default to snapshot backup directory
            backup_path = _BACKUP_ROOT / "backups" / "system_snapshot"
        if not backup_path.exists():
            error(f"Backup directory not found: {backup_path}")
            return False

        project = getattr(args, 'project', 'AIPass') or 'AIPass'
        note = getattr(args, 'note', 'Manual sync') or 'Manual sync'
        force = getattr(args, 'force', False)

        sync = GoogleDriveSync()
        if not sync.authenticate():
            error("FAILED: Could not authenticate with Google Drive")
            return False

        limit = getattr(args, 'limit', 0) or 0

        # Show last backup timestamps for all modes
        from aipass.backup.apps.handlers.utils.backup_timestamps import get_timestamps, format_age
        ts = get_timestamps()
        console.print()
        console.print("[dim]Last backups:[/dim]")
        console.print(f"  [dim]Snapshot:   {format_age(ts.get('snapshot'))}[/dim]")
        console.print(f"  [dim]Versioned:  {format_age(ts.get('versioned'))}[/dim]")
        console.print(f"  [dim]Drive sync: {format_age(ts.get('drive_sync'))}[/dim]")
        console.print()

        # Pre-flight: verify Drive folder FIRST (may reset tracker)
        console.print(f"Verifying Drive folder (project: {project})...")
        folder_id = sync.get_or_create_project_folder(project)
        if not folder_id:
            error_msg = sync.last_error or "Unknown error"
            error(f"FAILED: {error_msg}")
            error("Sync aborted - no files uploaded")
            return False
        console.print(f"  Drive folder ready: {project}")

        if sync.tracker_was_reset:
            warning("Drive folder is new - tracker reset, full re-sync needed")

        # Phase 1: Scan (local only, fast) - runs AFTER folder check so tracker is accurate
        console.print(f"\nScanning {backup_path}...")
        files_to_upload, skipped, total = sync.prepare_sync(backup_path, force, limit)
        upload_count = len(files_to_upload)

        # Display plan
        console.print(f"  Files considered: {total}{f' (limited to {limit})' if limit > 0 else ''}")
        console.print(f"  To upload:       {upload_count} ({'forced' if force else 'changed/new'})")
        console.print(f"  Unchanged:       {skipped}")

        if upload_count == 0:
            console.print("[green]All files up to date - nothing to sync[/green]")
            return True

        console.print()

        # Phase 2: Upload with progress bar
        with Progress(
            TextColumn("{task.description}"),
            BarColumn(bar_width=40),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TextColumn("{task.completed}/{task.total}"),
            TextColumn("[green]{task.fields[ok]} OK[/green]"),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=console,
        ) as progress:
            task_id = progress.add_task("Uploading...", total=upload_count, ok=0)

            def show_progress(completed, total_upload, successes):
                """Update progress bar."""
                progress.update(task_id, completed=completed, ok=successes)

            result = sync.sync_backup_files(
                backup_path, project, note, force,
                prepared_files=files_to_upload,
                skipped_count=skipped,
                total_count=total,
                progress_fn=show_progress
            )

            # Update label when complete
            progress.update(task_id, description="Uploaded  ")

        # Check for errors
        if result.get("error"):
            error(f"FAILED: {result['error']}")
            error("Sync aborted - no files uploaded")
            return False

        # Summary
        console.print()
        if result["success"]:
            from aipass.backup.apps.handlers.utils.backup_timestamps import update_timestamp, get_timestamps, format_age
            update_timestamp("drive_sync")
            ts = get_timestamps()
            console.print(f"[green]Sync complete: {result['uploaded']} uploaded, {result['skipped']} unchanged[/green]")
            console.print()
            console.print(f"[dim]Backups now:[/dim]")
            console.print(f"  [dim]Snapshot:   {format_age(ts.get('snapshot'))}[/dim]")
            console.print(f"  [dim]Versioned:  {format_age(ts.get('versioned'))}[/dim]")
            console.print(f"  [dim]Drive sync: {format_age(ts.get('drive_sync'))}[/dim]")
        else:
            error(f"Sync failed: {result['uploaded']} uploaded, {result['failed']} failed, {result['skipped']} unchanged")

        return result["success"]

    elif command == 'drive-sync-test':
        return _run_sync_test()

    elif command == 'drive-clear-tracker':
        return _clear_file_tracker()

    elif command == 'drive-stats':
        return _show_file_tracker_stats()

    return False

# =============================================
# CLI/EXECUTION
# =============================================

def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("google_drive_sync Module")
    console.print("Orchestrates Google Drive backup sync with two-phase upload pipeline")
    console.print()
    console.print("Connected Handlers:")
    console.print("  handlers/operations/")
    console.print("    - drive_sync_client.py (GoogleDriveSync — Drive API client and upload engine)")
    console.print("    - drive_sync_ops.py (clear_file_tracker — reset sync tracker cache)")
    console.print("    - drive_sync_ops.py (get_file_tracker_stats — tracker statistics)")
    console.print("    - drive_sync_ops.py (test_drive_connection — connectivity verification)")
    console.print("    - sync_test_ops.py (create_sync_test_files — generate test fixtures)")
    console.print("    - sync_test_ops.py (cleanup_sync_test_dir — remove test fixtures)")
    console.print("  handlers/json/")
    console.print("    - drive_sync_json.py (load_config — read module config JSON)")
    console.print("    - drive_sync_json.py (load_data — read module data JSON)")
    console.print("  handlers/utils/")
    console.print("    - backup_timestamps.py (get_timestamps, update_timestamp, format_age — backup timing)")
    console.print()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Google Drive Sync for AIPass Backup System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
COMMANDS:
  Commands: test, sync, sync-test, clear-tracker, show-stats

  test          - Test Google Drive connectivity
  sync          - Sync backup directory to Google Drive
  sync-test     - Run a small test sync to verify integration
  clear-tracker - Clear file tracker cache
  show-stats    - Show file tracker statistics

OPTIONS:
  --project     - Project name for sync (default: AIPass)
  --note        - Note for sync operation (default: Manual sync)
  --force       - Force sync all files (ignore tracker)

EXAMPLES:
  python3 google_drive_sync.py test
  python3 google_drive_sync.py sync /path/to/backups
  python3 google_drive_sync.py sync /path/to/backups --project "MyProject" --note "Daily backup"
  python3 google_drive_sync.py sync /path/to/backups --force
  python3 google_drive_sync.py clear-tracker
  python3 google_drive_sync.py show-stats
        """
    )

    parser.add_argument("command",
                       choices=['test', 'sync', 'sync-test', 'clear-tracker', 'show-stats'],
                       help="Command to execute")
    parser.add_argument("path", nargs='?', help="Backup directory path (required for sync command)")
    parser.add_argument("--project", type=str, default="AIPass", help="Project name for sync")
    parser.add_argument("--note", type=str, default="Manual sync", help="Note for sync operation")
    parser.add_argument("--force", action="store_true", help="Force sync all files (ignore tracker)")

    args = parser.parse_args()

    # Check if module is enabled
    config = _load_config()
    if not config.get("config", {}).get("enabled", True):
        warning("Google Drive sync is disabled")
        sys.exit(0)

    if args.command == 'clear-tracker':
        if _clear_file_tracker():
            console.print("File tracker cleared successfully")
            sys.exit(0)
        else:
            error("Failed to clear file tracker")
            sys.exit(1)

    elif args.command == 'show-stats':
        if _show_file_tracker_stats():
            sys.exit(0)
        else:
            sys.exit(1)

    elif args.command == 'sync':
        if not args.path:
            error("sync command requires a path argument")
            console.print("Usage: python3 google_drive_sync.py sync /path/to/backups")
            sys.exit(1)

        backup_path = Path(args.path)

        if not backup_path.exists():
            error(f"Backup directory not found: {backup_path}")
            sys.exit(1)

        sync = GoogleDriveSync()
        if not sync.authenticate():
            error("Failed to authenticate with Google Drive")
            sys.exit(1)

        # Phase 1: Scan
        console.print(f"Scanning {backup_path}...")
        files_to_upload, skipped, total = sync.prepare_sync(backup_path, args.force)
        upload_count = len(files_to_upload)

        console.print(f"  Files scanned: {total}")
        console.print(f"  To upload:     {upload_count} ({'forced' if args.force else 'changed/new'})")
        console.print(f"  Unchanged:     {skipped}")

        if upload_count == 0:
            console.print("[green]All files up to date - nothing to sync[/green]")
            sys.exit(0)

        console.print(f"\nSyncing to Google Drive (project: {args.project})...")

        def cli_progress(completed, total_upload, successes):
            """Display CLI upload progress."""
            console.print(f"  Progress: {completed}/{total_upload} ({successes} OK)")

        # Phase 2: Upload
        result = sync.sync_backup_files(
            backup_path, args.project, args.note, args.force,
            prepared_files=files_to_upload,
            skipped_count=skipped,
            total_count=total,
            progress_fn=cli_progress
        )

        console.print()
        if result["success"]:
            console.print(f"[green]Sync complete: {result['uploaded']} uploaded, {result['skipped']} unchanged[/green]")
            sys.exit(0)
        else:
            warning(f"Sync finished: {result['uploaded']} uploaded, {result['failed']} failed, {result['skipped']} unchanged")
            sys.exit(1)

    elif args.command == 'sync-test':
        # Create a minimal args namespace for the test function
        if _run_sync_test():
            sys.exit(0)
        else:
            sys.exit(1)

    elif args.command == 'test':
        if _test_drive_sync():
            console.print("Google Drive sync test successful")
            sys.exit(0)
        else:
            console.print("Google Drive sync test failed")
            sys.exit(1)
