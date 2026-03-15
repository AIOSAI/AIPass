# =================== AIPass ====================
# Name: backup_core.py
# Description: Main backup system orchestration module
# Version: 2.1.0
# Created: 2025-11-23
# Modified: 2026-03-09
# =============================================

"""
Backup System Core Module

Main entry point for backup functionality following seed architecture standards.
Provides CLI command routing and BackupEngine orchestration.

This module coordinates the complete backup workflow by bringing together:
- Configuration (BACKUP_MODES, GLOBAL_IGNORE_PATTERNS)
- Models (BackupResult)
- File operations (copy_file_with_structure, copy_versioned_file)
- Utilities (safe_print, temporarily_writable, system logging)
- JSON tracking (log_operation)

Architecture Pattern:
- handle_command(args) - CLI entry point for backup commands
- BackupEngine class - Main orchestrator (delegates to handlers)
- Follows seed 3-layer architecture (cli -> modules -> handlers)
"""

# =============================================
# IMPORTS
# =============================================

# Infrastructure
import sys
import datetime
from pathlib import Path
from typing import Dict

from aipass.cli.apps.modules import console, header, success, error
from aipass.cli.apps.modules.display import warning
from aipass.prax import logger


# Import handlers (core dependencies) - relative imports
from aipass.backup.apps.handlers.config.config_handler import (
    BACKUP_MODES,
    GLOBAL_IGNORE_PATTERNS,
    IGNORE_EXCEPTIONS,
    filter_tracked_items,
    should_ignore
)
from aipass.backup.apps.handlers.models.backup_models import BackupResult
from aipass.backup.apps.handlers.operations.file_operations import copy_file_with_structure, copy_versioned_file
from aipass.backup.apps.handlers.utils.system_utils import safe_print
from aipass.backup.apps.handlers.json.json_handler import log_operation, ensure_module_jsons
from aipass.backup.apps.handlers.json.changelog_handler import (
    load_changelog as load_changelog_file,
    save_changelog_entry as save_changelog_entry_file,
    display_previous_comments as display_previous_comments_file
)
from aipass.backup.apps.handlers.json.backup_info_handler import (
    load_backup_info as load_backup_info_file,
    save_backup_info as save_backup_info_file
)

# Integration stubs and JSON setup moved to handlers
# sync_to_drive → handlers/integrations/ (when implemented)
# set_backup_readonly → handlers/integrations/ (when implemented)
# initialize_json_files → called directly in __init__

_BACKUP_ROOT = Path(__file__).resolve().parents[2]  # src/aipass/backup/
JSON_DIR = _BACKUP_ROOT / "backup_json"


# =============================================
# INTROSPECTION (SEED PATTERN)
# =============================================

def print_introspection():
    """Display module info and connected handlers"""
    from pathlib import Path

    console.print()
    console.print("[bold cyan]Backup Core Module[/bold cyan]")
    console.print()

    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print()

    # Show handler domains this module uses
    handlers_base = Path(__file__).parent.parent / "handlers"

    handler_domains = [
        "config",
        "models",
        "operations",
        "utils",
        "json",
        "reporting"
    ]

    for domain in handler_domains:
        domain_path = handlers_base / domain
        if domain_path.exists():
            console.print(f"  [cyan]handlers/{domain}/[/cyan]")

    console.print()
    console.print("[dim]Run 'python3 backup_core.py --help' for usage[/dim]")
    console.print()


# =============================================
# MODULE-LEVEL COMMAND HANDLER
# =============================================


def print_help():
    """Display help for the backup_core module."""
    console.print()
    console.print("[bold cyan]Backup Core Module[/bold cyan]")
    console.print()
    console.print("Main backup orchestration module")
    console.print()
    console.print("[yellow]Usage:[/yellow]")
    console.print("  python3 backup_core.py              # Show module info")
    console.print("  python3 backup_core.py --help       # Show this help")
    console.print()
    console.print("[yellow]Commands:[/yellow]")
    console.print("  snapshot    Full copy backup (overwrites destination)")
    console.print("  versioned   Timestamped backup with incremental copies")
    console.print("  all         Full backup cycle (snapshot + versioned + drive-sync)")
    console.print()


def handle_command(args) -> bool:
    """Route backup commands to appropriate handler.

    This is the module-level entry point for CLI commands related to backup.
    Checks if the command matches backup commands and routes accordingly.

    Args:
        args: Command-line arguments from CLI parser

    Returns:
        bool: True if command was handled, False if not a backup command
    """
    # Check if args has backup-related command
    if not hasattr(args, 'command'):
        return False

    # Check for backup commands ('all' handled by entry point, listed here for drone discovery)
    if args.command not in ['snapshot', 'versioned', 'all']:
        return False

    # 'all' is orchestrated by backup_system.py entry point (snapshot → versioned → drive-sync)
    if args.command == 'all':
        return False

    # Set mode directly from command
    mode = args.command

    # Check for dry-run flag
    dry_run = getattr(args, 'dry_run', False)

    # Get backup note if provided
    backup_note = getattr(args, 'note', 'No note provided')

    # Rich header
    header(f"Backup — {mode.title()}", {
        'Mode': mode,
        'Dry run': 'yes' if dry_run else 'no',
    })

    try:
        # Create engine and run backup
        engine = BackupEngine(mode, dry_run=dry_run)
        result = engine.run_backup(backup_note)

        # Rich summary
        duration = (datetime.datetime.now() - result.start_time).total_seconds()
        console.print()
        if result.critical_errors:
            error(f"{mode.title()} backup FAILED")
        elif result.errors > 0:
            warning(f"{mode.title()} completed with {result.errors} errors")
            console.print(f"  [dim]Files: {result.files_copied} copied, {result.files_skipped} skipped[/dim]")
        else:
            if dry_run:
                success(f"{mode.title()} dry-run complete",
                        files_scanned=result.files_checked,
                        would_copy=result.files_copied,
                        unchanged=result.files_skipped)
            else:
                success(f"{mode.title()} backup complete",
                        files_copied=result.files_copied,
                        files_skipped=result.files_skipped)
        console.print(f"  [dim]Duration: {duration:.1f}s | Location: {result.backup_path}[/dim]")

        return True
    except Exception as e:
        logger.error(f"[backup_core] Backup command failed: {e}")
        error(f"Backup failed: {e}")
        return True  # Still handled, just failed


# =============================================
# BACKUP ENGINE CLASS
# =============================================


class BackupEngine:
    """Main backup system orchestrator (seed-compliant wrapper).

    Provides the core backup workflow coordination following seed architecture.
    Delegates heavy lifting to handler modules rather than implementing logic here.

    This class is a thin orchestration layer that:
    - Initializes with backup mode and configuration
    - Coordinates file scanning and copying via handlers
    - Manages backup metadata persistence
    - Reports statistics and status

    Attributes:
        mode (str): Backup mode (e.g., 'snapshot', 'versioned')
        dry_run (bool): If True, scan files without copying
        mode_config (dict): Configuration for selected mode
        backup_path (Path): Destination path for backup
        source_dir (Path): Source directory to backup

    Raises:
        ValueError: If mode is invalid or configuration missing
    """

    def __init__(self, mode: str, dry_run: bool = False):
        """Initialize backup engine with specified mode.

        Validates mode, loads configuration, and prepares for backup operation.

        Args:
            mode: Backup mode from BACKUP_MODES ('snapshot' or 'versioned')
            dry_run: If True, scan files without copying (test ignore patterns)

        Raises:
            ValueError: If mode is invalid
            KeyError: If mode configuration is missing

        Example:
            engine = BackupEngine('versioned', dry_run=True)
            result = engine.run_backup("Before refactor")
        """
        if mode not in BACKUP_MODES:
            raise ValueError(f"Invalid backup mode: {mode}. Valid modes: {list(BACKUP_MODES.keys())}")

        self.mode = mode
        self.dry_run = dry_run
        self.mode_config = BACKUP_MODES[mode]

        # Auto-detect source directory
        self.source_dir = Path.home()
        self.backup_dest = Path(self.mode_config['destination'])
        self.ignore_patterns = GLOBAL_IGNORE_PATTERNS

        # Mode-specific paths - all modes use fixed folder names
        self.backup_folder_name = self.mode_config['folder_name']
        self.backup_path = self.backup_dest / self.backup_folder_name

        # Initialize JSON system (handler creates directory if needed)
        ensure_module_jsons("backup_core")

        # JSON files (mode-specific) - backup-specific tracking files
        self.backup_info_file = JSON_DIR / f"{mode}_backup.json"
        self.changelog_file = JSON_DIR / f"{mode}_backup_changelog.json"
        self.restore_log_file = JSON_DIR / f"{mode}_restore_history.json"

        # Display clear mode identification
        console.print(f"Mode: {self.mode_config['name']}")
        console.print(f"Source: {self.source_dir}")
        console.print(f"Destination: {self.backup_dest}")
        console.print(f"Usage: {self.mode_config['usage']}")

        logger.info(f"[backup_core] Initialized {mode} mode - source: {self.source_dir}")

    # =============================================
    # UTILITY METHODS
    # =============================================

    def should_ignore(self, path: Path) -> bool:
        """Check if a file/folder should be ignored based on patterns.

        Delegates to handler function for centralized pattern matching.

        Args:
            path: Path to check

        Returns:
            True if path should be ignored, False otherwise
        """
        return should_ignore(path, self.ignore_patterns, IGNORE_EXCEPTIONS, self.backup_dest)

    def ensure_backup_directory(self, result: BackupResult) -> bool:
        """Create backup directory if needed (delegates to handler)."""
        from aipass.backup.apps.handlers.utils.system_utils import ensure_backup_directory as ensure_dir
        success, error_msg = ensure_dir(self.backup_dest, self.backup_path, self.mode_config['behavior'] == 'dynamic')
        if not success:
            error_text = error_msg if error_msg is not None else "Unknown error creating backup directory"
            result.add_error(error_text, is_critical=True)
            safe_print(f"CRITICAL: {error_text}")
            logger.error(f"[backup_core] {error_text}")
        return success

    def file_needs_backup(self, source_file: Path, backup_file: Path, last_timestamps: dict) -> bool:
        """Check if file needs backup (delegates to handler)."""
        from aipass.backup.apps.handlers.operations.file_operations import file_needs_backup as check_file
        return check_file(source_file, backup_file, last_timestamps, self.source_dir)

    def remove_empty_dirs(self, path: Path):
        """Remove empty directories (delegates to handler)."""
        from aipass.backup.apps.handlers.utils.system_utils import remove_empty_dirs as clean_dirs
        clean_dirs(path)

    # Changelog and backup info operations (thin delegators to handlers)
    def load_changelog(self) -> Dict:
        """Load changelog data from JSON file."""
        return load_changelog_file(self.changelog_file)

    def save_changelog_entry(self, note: str) -> bool:
        """Save a changelog entry for the current backup operation."""
        return save_changelog_entry_file(self.changelog_file, note, self.mode, self.backup_path)

    def display_previous_comments(self):
        """Display previous changelog comments for the current backup mode."""
        display_previous_comments_file(self.changelog_file, self.mode_config['name'])

    def load_backup_info(self) -> Dict:
        """Load backup info metadata from JSON file."""
        return load_backup_info_file(self.backup_info_file, self.mode_config['behavior'])

    def save_backup_info(self, backup_info: Dict) -> bool:
        """Save backup info metadata to JSON file."""
        return save_backup_info_file(self.backup_info_file, backup_info)

    # =============================================
    # MAIN BACKUP EXECUTION
    # =============================================

    def run_backup(self, backup_note: str = "No note provided") -> BackupResult:
        """Execute backup - thin orchestration layer calling handlers.

        Coordinates backup workflow by delegating to specialized handlers.

        Args:
            backup_note: User note describing backup purpose/context

        Returns:
            BackupResult: Complete operation result with statistics and status
        """
        logger.info(f"[backup_core] Starting {self.mode} backup: {backup_note}")

        # Show last backup timestamps for all modes
        from aipass.backup.apps.handlers.utils.backup_timestamps import get_timestamps, format_age
        ts = get_timestamps()
        console.print()
        console.print("[dim]Last backups:[/dim]")
        console.print(f"  [dim]Snapshot:   {format_age(ts.get('snapshot'))}[/dim]")
        console.print(f"  [dim]Versioned:  {format_age(ts.get('versioned'))}[/dim]")
        console.print(f"  [dim]Drive sync: {format_age(ts.get('drive_sync'))}[/dim]")

        result = BackupResult()
        result.mode = self.mode
        result.backup_path = str(self.backup_path)

        # Display dry-run warning if in test mode
        if self.dry_run:
            console.print()
            warning("DRY-RUN MODE ACTIVE — Files will be scanned but NOT copied or deleted")
            console.print()

        header(f"AIPass {self.mode_config['name']} - {self.mode_config['description']}")
        # Ensure backup directory exists
        if not self.ensure_backup_directory(result):
            error("BACKUP FAILED: Could not create backup directory")
            return result

        # Load previous backup info
        backup_info = self.load_backup_info()
        last_timestamps = backup_info.get("file_timestamps", {}) if self.mode_config['behavior'] == 'dynamic' else {}
        if not isinstance(last_timestamps, dict):
            last_timestamps = {}

        # HANDLER: Scan files
        from aipass.backup.apps.handlers.operations.file_scanner import scan_files
        files_to_backup, skipped_items = scan_files(self.source_dir, self.should_ignore)

        # HANDLER: Process files
        from aipass.backup.apps.handlers.operations.path_builder import build_backup_path
        current_timestamps = {}
        total_files = len(files_to_backup)

        from rich.progress import Progress, BarColumn, TextColumn, TimeRemainingColumn

        # Progress tracking with Rich
        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeRemainingColumn(),
            console=console,
            transient=True
        ) as progress:
            task = progress.add_task("Processing files...", total=total_files)
            
            for idx, file_path in enumerate(files_to_backup):
                result.files_checked += 1

                # Build backup path
                backup_file = build_backup_path(file_path, self.source_dir, self.backup_path, self.mode)
                current_timestamps[str(file_path.relative_to(self.source_dir))] = file_path.stat().st_mtime

                # Process file
                try:
                    if self.dry_run:
                        # Show what WOULD happen in dry-run mode
                        is_new = not backup_file.exists()

                        if self.mode_config['behavior'] == 'versioned':
                            # Versioned mode: check if file actually changed (mtime comparison)
                            if is_new:
                                safe_print(f"📄 Would copy (new): {file_path}")
                                result.files_copied += 1
                            elif backup_file.exists():
                                # Check if file changed by comparing mtimes
                                source_mtime = file_path.stat().st_mtime
                                target_mtime = backup_file.stat().st_mtime
                                if source_mtime != target_mtime:
                                    safe_print(f"📄 Would copy (updated): {file_path}")
                                    result.files_copied += 1
                                else:
                                    result.files_skipped += 1  # Unchanged, would skip
                        else:
                            # Snapshot mode: use timestamp-based check
                            if is_new:
                                safe_print(f"📄 Would copy (new): {file_path}")
                                result.files_copied += 1
                            elif self.file_needs_backup(file_path, backup_file, last_timestamps):
                                safe_print(f"📄 Would copy (updated): {file_path}")
                                result.files_copied += 1
                            else:
                                result.files_skipped += 1  # Only skip if unchanged
                    elif self.mode_config['behavior'] == 'versioned':
                        # Skip unchanged files (mtime pre-check avoids expensive copy_versioned_file overhead)
                        if backup_file.exists() and backup_file.stat().st_mtime == file_path.stat().st_mtime:
                            result.files_skipped += 1
                        elif copy_versioned_file(file_path, backup_file, self.backup_path, result):
                            result.files_copied += 1
                    elif self.file_needs_backup(file_path, backup_file, last_timestamps):
                        if copy_file_with_structure(file_path, backup_file, self.backup_path, result):
                            result.files_copied += 1
                    else:
                        result.files_skipped += 1
                except Exception as e:
                    result.add_error(f"Error processing {file_path}: {e}", is_critical=True)
                    # Use console.print directly for critical errors so they appear above progress bar
                    error(f"CRITICAL: Error processing {file_path}: {e}")

                # Update progress
                progress.advance(task)

        console.print(f"Processing completed: {total_files}/{total_files} files checked")

        # HANDLER: Cleanup deleted files (dynamic mode only)
        # RE-ENABLED 2025-11-23: Fixed to respect IGNORE_EXCEPTIONS in third pass
        # Now runs in dry-run mode to show what WOULD be deleted
        if self.backup_path.exists() and self.mode_config['behavior'] == 'dynamic':
            from aipass.backup.apps.handlers.operations.file_cleanup import cleanup_deleted_files
            cleanup_deleted_files(self.backup_path, self.source_dir, self.should_ignore, result, self.dry_run)

        # HANDLER: Remove empty directories (handled by cleanup_deleted_files now)
        # self.remove_empty_dirs(self.backup_path)

        # HANDLER: Create and save backup metadata
        from aipass.backup.apps.handlers.json.backup_metadata_builder import create_backup_metadata
        backup_info = create_backup_metadata(
            self.mode, self.mode_config['behavior'], backup_note, self.backup_folder_name,
            self.backup_path, self.source_dir, result, current_timestamps, backup_info
        )
        self.save_backup_info(backup_info)

        # HANDLER: Display backup results
        from aipass.backup.apps.handlers.reporting.report_formatter import display_backup_results
        display_backup_results(result, self.mode_config, self.backup_path, skipped_items, filter_tracked_items, self.dry_run)

        # Update JSON system
        execution_time = int((datetime.datetime.now() - result.start_time).total_seconds() * 1000)
        if result.success and result.errors == 0:
            log_operation(
                "backup",
                {
                    "mode": self.mode,
                    "files_copied": result.files_copied,
                    "success": True,
                    "execution_time_ms": execution_time
                },
                module_name="backup_core"
            )
            logger.info(f"[backup_core] {self.mode} backup completed successfully - {result.files_copied} files copied in {execution_time}ms")

            # Update backup timestamp and show confirmation
            from aipass.backup.apps.handlers.utils.backup_timestamps import update_timestamp, get_timestamps, format_age
            update_timestamp(self.mode)
            ts = get_timestamps()
            console.print()
            console.print(f"[dim]Backups now:[/dim]")
            console.print(f"  [dim]Snapshot:   {format_age(ts.get('snapshot'))}[/dim]")
            console.print(f"  [dim]Versioned:  {format_age(ts.get('versioned'))}[/dim]")
            console.print(f"  [dim]Drive sync: {format_age(ts.get('drive_sync'))}[/dim]")

            # Integration hooks (stubs - implement in handlers/integrations/)
            if self.mode == 'versioned':
                logger.info("[backup_core] Drive sync skipped (not implemented)")
            logger.info("[backup_core] Read-only protection skipped (not implemented)")
        else:
            log_operation(
                "backup",
                {
                    "mode": self.mode,
                    "errors": result.errors,
                    "success": False,
                    "execution_time_ms": execution_time
                },
                module_name="backup_core"
            )
            logger.error(f"[backup_core] {self.mode} backup completed with {result.errors} errors in {execution_time}ms")

        from aipass.backup.apps.handlers.json.statistics_handler import update_data_file
        update_data_file(result)

        return result


# =============================================
# MODULE INITIALIZATION
# =============================================

# =============================================
# STANDALONE ENTRY POINT (SEED PATTERN)
# =============================================

if __name__ == "__main__":
    import sys

    # Show introspection when run without arguments
    if len(sys.argv) == 1:
        print_introspection()
        sys.exit(0)

    # Handle help flag
    if sys.argv[1] in ['--help', '-h', 'help']:
        print_help()
        sys.exit(0)

    console.print("[yellow]Note:[/yellow] Run via backup_system.py entry point for full functionality")
    console.print()
    print_introspection()
