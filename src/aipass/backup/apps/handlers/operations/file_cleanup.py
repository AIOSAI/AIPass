
# ===================AIPASS====================
# META DATA HEADER
# Name: file_cleanup.py - File deletion operations
# Date: 2025-11-23
# Version: 1.0.2
# Category: handlers
#
# CHANGELOG (Max 5 entries):
#   - v1.0.2 (2025-11-23): Added dry-run support for cleanup operations
#     * Added dry_run parameter to cleanup_deleted_files()
#     * Shows "Would delete" messages instead of actually deleting in dry-run
#     * All three passes (directories, files, empty dirs) respect dry-run mode
#   - v1.0.1 (2025-11-23): CRITICAL BUG FIX - respect exceptions in empty dir cleanup
#     * Third pass now checks should_ignore() before removing empty directories
#     * Prevents deletion of empty template directories
#     * Added source_dir mapping to check exceptions properly
#     * Only removes empty dirs if source doesn't exist OR should be ignored
#   - v1.0.0 (2025-11-18): Extracted from backup_core.py
#     * Extracted file deletion logic for dynamic mode
#     * Handles cleanup of deleted source files
#
# CODE STANDARDS:
#   - Follow seed 3-layer architecture
#   - Handlers must be independent and transportable
#   - No cross-handler imports except within same domain
# =============================================

"""
File Cleanup - File deletion operations for dynamic backups

Handles cleanup of backup files when source files are deleted.
"""

# =============================================
# IMPORTS
# =============================================

import logging
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

from aipass.backup.apps.handlers.utils.system_utils import temporarily_writable, safe_print
from aipass.backup.apps.handlers.models.backup_models import BackupResult

# =============================================
# FILE CLEANUP OPERATIONS
# =============================================

def cleanup_deleted_files(backup_path: Path, source_dir: Path, should_ignore: Callable,
                          result: BackupResult, dry_run: bool = False) -> None:
    """Clean up backup files when source files no longer exist (dynamic mode only).

    Args:
        backup_path: Backup destination path
        source_dir: Source directory root
        should_ignore: Function to check if path should be ignored
        result: BackupResult to track deletions and errors
        dry_run: If True, only show what would be deleted without actually deleting
    """
    import shutil
    import stat

    if not backup_path.exists():
        return

    def handle_remove_readonly(func, path, exc_info):
        """Error handler for shutil.rmtree to handle read-only files."""
        import os
        # Make the file/directory writable (and executable if directory) and try again
        # Also make parent directory writable
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
        parent = Path(path).parent
        if parent.exists():
            os.chmod(parent, stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
        func(path)

    try:
        # Make backup_path writable for the duration of cleanup
        backup_path.chmod(stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)

        # First pass: Recursively check ALL directories and remove if ignored
        # Sort by depth (shallowest first) so we can remove parents and skip children
        all_dirs = sorted([d for d in backup_path.rglob('*') if d.is_dir()],
                         key=lambda p: len(p.parts))

        removed_dirs = set()

        for backup_dir in all_dirs:
            # Skip if this directory is inside a directory we already removed
            if any(str(backup_dir).startswith(str(removed)) for removed in removed_dirs):
                continue

            try:
                rel_path = backup_dir.relative_to(backup_path)
                source_dir_path = source_dir / rel_path

                # Check if source doesn't exist or should be ignored
                if not source_dir_path.exists() or should_ignore(source_dir_path):
                    if dry_run:
                        safe_print(f"Would delete directory: {backup_dir}/")
                    else:
                        # Remove entire tree
                        shutil.rmtree(backup_dir, onerror=handle_remove_readonly)
                        safe_print(f"Deleted directory: {backup_dir}/")
                    removed_dirs.add(backup_dir)
            except Exception as e:
                # Don't fail entire backup on one directory error
                pass

        # Second pass: delete individual files that no longer exist or should be ignored
        for backup_file in backup_path.rglob('*'):
            if backup_file.is_file():
                try:
                    rel_path = backup_file.relative_to(backup_path)
                    source_file = source_dir / rel_path

                    if not source_file.exists() or should_ignore(source_file):
                        if dry_run:
                            safe_print(f"Would delete: {backup_file}")
                        else:
                            # Use context manager to handle read-only files before deletion
                            with temporarily_writable(backup_file.parent):
                                with temporarily_writable(backup_file):
                                    backup_file.unlink()
                            safe_print(f"Deleted: {backup_file}")
                        result.files_deleted += 1
                except PermissionError as e:
                    error_msg = f"Permission denied deleting {backup_file}: {e}"
                    result.add_error(error_msg)
                    safe_print(f"{error_msg}")
                except Exception as e:
                    error_msg = f"Error deleting {backup_file}: {e}"
                    result.add_warning(error_msg)
                    safe_print(f"{error_msg}")

        # Third pass: remove empty directories (bottom-up)
        # CRITICAL FIX: Now checks should_ignore() to respect exceptions
        all_dirs = [d for d in backup_path.rglob('*') if d.is_dir()]
        all_dirs.sort(key=lambda p: len(p.parts), reverse=True)

        for backup_dir in all_dirs:
            try:
                if not any(backup_dir.iterdir()):  # Empty directory
                    # Map to source directory to check if it should be preserved
                    rel_path = backup_dir.relative_to(backup_path)
                    source_dir_path = source_dir / rel_path

                    # Only remove if source doesn't exist OR should be ignored
                    # This respects IGNORE_EXCEPTIONS (like templates/**)
                    if not source_dir_path.exists() or should_ignore(source_dir_path):
                        if dry_run:
                            safe_print(f"Would delete empty: {backup_dir}/")
                        else:
                            with temporarily_writable(backup_dir.parent):
                                backup_dir.chmod(stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
                                backup_dir.rmdir()
                            safe_print(f"Deleted empty: {backup_dir}/")
                    # else: Directory is in exceptions, preserve it even if empty
            except OSError:
                pass  # Directory not empty or other OS error
            except Exception as e:
                pass  # Silently skip other errors

    except Exception as e:
        error_msg = f"Error scanning for deleted files: {e}"
        result.add_warning(error_msg)
        logger.warning(f"[file_cleanup] {error_msg}")


# =============================================
# MODULE INITIALIZATION
# =============================================

# No module-level initialization needed
