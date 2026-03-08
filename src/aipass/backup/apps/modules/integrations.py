# ===================AIPASS====================
# META DATA HEADER
# Name: integrations.py - External integrations and backup protection
# Date: 2025-11-29
# Version: 2.1.0
# Category: backup_system
#
# CHANGELOG (Max 5 entries):
#   - v2.1.0 (2026-03-06): Adapted for AIPass public repo
#     * Removed shebang, sys.path manipulation, prax/cli imports
#     * Uses standard logging and rich console
#     * Relative handler imports, GoogleDriveSync via sibling module
#   - v2.0.1 (2025-11-29): UX FIX - Import error and missing help output
#   - v2.0.0 (2025-11-16): Created seed-compliant layout module
#   - v1.1.0 (2025-10-30): Original backup_integrations features
#   - v1.0.0 (2025-10-14): Initial extraction
#
# CODE STANDARDS:
#   - Follow seed 3-layer architecture
#   - Orchestrate workflows, delegate to handlers
#   - Import handlers, never implement business logic
# =============================================

"""
Backup System Integrations Module

Handles external integrations for the backup system following seed architecture standards.
Provides CLI command routing and integration orchestration.

This module manages optional features that integrate with external services
or provide additional protection mechanisms for backups:
- Google Drive cloud synchronization (optional)
- Backup directory protection (read-only permissions)

Architecture Pattern:
- handle_command(args) - CLI entry point for integration commands
- Integration functions with proper error handling and logging
- Graceful degradation for optional dependencies (Google Drive)
"""

# =============================================
# IMPORTS
# =============================================

import sys
import os
import stat
import logging
from pathlib import Path

from rich.console import Console

logger = logging.getLogger(__name__)
console = Console()


def _header(text):
    console.print(f"\n[bold cyan]{'='*70}[/bold cyan]")
    console.print(f"[bold cyan]  {text}[/bold cyan]")
    console.print(f"[bold cyan]{'='*70}[/bold cyan]")


# Handler imports - relative imports
from aipass.backup.apps.handlers.utils.system_utils import safe_print
from aipass.backup.apps.handlers.operations.integration_ops import (
    sync_to_drive as _sync_to_drive_handler,
    set_backup_readonly as _set_backup_readonly_handler,
)

# Google Drive sync integration (optional - graceful degradation if not available)
try:
    from aipass.backup.apps.modules.google_drive_sync import GoogleDriveSync
    DRIVE_SYNC_AVAILABLE = True
except ImportError:
    GoogleDriveSync = None  # type: ignore
    DRIVE_SYNC_AVAILABLE = False
    logger.info("[integrations] Google Drive sync module not available - sync features disabled")

# =============================================
# MODULE-LEVEL COMMAND HANDLER
# =============================================


def handle_command(args) -> bool | None:
    """Route integration commands to appropriate handler.

    This is the module-level entry point for CLI commands related to integrations.
    Routes integration-specific commands like sync-to-drive and set-readonly.

    Args:
        args: Command-line arguments from CLI parser

    Returns:
        bool: True if command succeeded, False otherwise, None if command not matched

    Example:
        result = handle_command(args)
        if result:
            console.print("Integration command completed successfully")

    Supported commands:
        - sync-to-drive: Sync backup to Google Drive
        - set-readonly: Protect backup with read-only permissions
    """
    if not hasattr(args, 'integration_command'):
        return None

    if args.integration_command == 'sync-to-drive':
        backup_path = Path(args.backup_path) if hasattr(args, 'backup_path') else None
        source_dir = Path(args.source_dir) if hasattr(args, 'source_dir') else None
        mode = getattr(args, 'mode', 'versioned')
        backup_note = getattr(args, 'backup_note', '')

        if not backup_path or not source_dir:
            logger.warning("[integrations] Missing required arguments for sync-to-drive")
            return False

        return _sync_to_drive(backup_path, source_dir, mode, backup_note)

    elif args.integration_command == 'set-readonly':
        backup_path = Path(args.backup_path) if hasattr(args, 'backup_path') else None
        if not backup_path:
            logger.warning("[integrations] Missing backup_path argument for set-readonly")
            return False

        return _set_backup_readonly(backup_path)

    return None

# =============================================
# GOOGLE DRIVE INTEGRATION
# =============================================


def _sync_to_drive(backup_path: Path, source_dir: Path, mode: str, backup_note: str = "") -> bool:
    """Orchestrate sync to Google Drive using integration handler.

    Args:
        backup_path: Path to backup directory to sync
        source_dir: Source directory being backed up
        mode: Backup mode ('snapshot' or 'versioned')
        backup_note: Optional note describing the backup

    Returns:
        bool: True if sync succeeded, False otherwise
    """
    if not DRIVE_SYNC_AVAILABLE:
        safe_print("\033[93m[WARNING] Google Drive sync module not available - check backup_system installation\033[0m")
        logger.warning("[integrations] Drive sync requested but google_drive_sync module not found")
        return False

    if mode != 'versioned':
        safe_print("[INFO] Drive sync only available for versioned backups")
        logger.info(f"[integrations] Drive sync skipped - mode {mode} not supported (versioned only)")
        return False

    try:
        # Display sync header
        safe_print("\n" + "="*70)
        safe_print("\033[96m           GOOGLE DRIVE SYNC\033[0m")
        safe_print("="*70)

        project_name = "AIPass"
        safe_print(f"\033[92m✓\033[0m Google Drive folder name: \033[1m{project_name}\033[0m")
        safe_print(f"\033[92m✓\033[0m Destination: Google Drive (versioned backups)")
        safe_print("-"*70)

        logger.info("[integrations] Starting Google Drive sync")
        safe_print("\033[94m[AUTH]\033[0m Verifying Google Drive credentials...")

        success = _sync_to_drive_handler(
            backup_path=backup_path,
            source_dir=source_dir,
            mode=mode,
            backup_note=backup_note,
            drive_sync_module=GoogleDriveSync,
            drive_sync_available=DRIVE_SYNC_AVAILABLE,
        )

        if success:
            safe_print("\033[92m✓ Sync completed successfully\033[0m")
            logger.info(f"[integrations] Drive sync completed successfully for {project_name}")
        else:
            logger.error("[integrations] Drive sync completed with errors")
        return success

    except Exception as e:
        error_msg = f"Drive sync failed: {e}"
        safe_print(f"[ERROR] {error_msg}")
        logger.error(f"[integrations] {error_msg}")
        return False



# =============================================
# FILE PROTECTION
# =============================================


def _set_backup_readonly(backup_path: Path) -> bool:
    """Orchestrate backup directory read-only protection using handler.

    Args:
        backup_path: Path to backup directory to protect

    Returns:
        bool: True if protection applied successfully, False otherwise
    """
    try:
        if not backup_path.exists():
            warning_msg = f"Backup path does not exist: {backup_path}"
            safe_print(f"[WARNING] {warning_msg}")
            logger.warning(f"[integrations] {warning_msg}")
            return False

        success, message = _set_backup_readonly_handler(backup_path)

        if success:
            safe_print(f"[PROTECTION] Backup directory set to read-only: {backup_path}")
            logger.info(f"[integrations] Read-only set: {backup_path} ({message})")
        else:
            safe_print(f"[WARNING] {message}")
            logger.warning(f"[integrations] {message}")
        return success

    except Exception as e:
        warning_msg = f"Could not set read-only protection: {e}"
        safe_print(f"[WARNING] {warning_msg}")
        logger.warning(f"[integrations] {warning_msg}")
        return False



# =============================================
# MODULE INITIALIZATION
# =============================================

# Log module initialization
logger.info("[integrations] Module loaded - external integration support ready")
if DRIVE_SYNC_AVAILABLE:
    logger.info("[integrations] Google Drive sync available")
else:
    logger.info("[integrations] Google Drive sync unavailable - install google_drive_sync.py to enable")

# =============================================
# MAIN ENTRY POINT
# =============================================

def print_help():
    """Display help information for the integrations module."""
    _header("BACKUP SYSTEM - INTEGRATIONS MODULE")
    safe_print("")
    safe_print("\033[1mPURPOSE:\033[0m")
    safe_print("  External integrations for the backup system")
    safe_print("")
    safe_print("\033[1mAVAILABLE SUBCOMMANDS:\033[0m")
    safe_print("")
    safe_print("  \033[92msync-to-drive\033[0m")
    safe_print("    Sync versioned backups to Google Drive cloud storage")
    safe_print("    Requires: backup_path, source_dir, mode, backup_note")
    safe_print("    Status: " + ("\033[92mAvailable\033[0m" if DRIVE_SYNC_AVAILABLE else "\033[93mUnavailable (google_drive_sync module not found)\033[0m"))
    safe_print("")
    safe_print("  \033[92mset-readonly\033[0m")
    safe_print("    Protect backup directory with read-only permissions")
    safe_print("    Requires: backup_path")
    safe_print("    Status: \033[92mAvailable\033[0m")
    safe_print("")
    safe_print("\033[1mUSAGE:\033[0m")
    safe_print("  This module is called via the backup system CLI:")
    safe_print("  \033[90m$ backup integration sync-to-drive --backup-path <path> ...\033[0m")
    safe_print("  \033[90m$ backup integration set-readonly --backup-path <path>\033[0m")
    safe_print("")
    safe_print("\033[1mOR\033[0m import functions directly in Python:")
    safe_print("  \033[90mfrom aipass.backup.apps.modules.integrations import handle_command\033[0m")
    safe_print("")
    safe_print("-"*70)
    safe_print("\033[1mCommands:\033[0m sync-to-drive, set-readonly")
    safe_print("="*70)
    safe_print("")

if __name__ == "__main__":
    """Display help when module is run directly."""
    import sys as _sys
    if len(_sys.argv) > 1 and _sys.argv[1] in ['--help', '-h', 'help']:
        print_help()
    else:
        print_help()
