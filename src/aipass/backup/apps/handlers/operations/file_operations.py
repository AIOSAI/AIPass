
# ===================AIPASS====================
# META DATA HEADER
# Name: file_operations.py - Core backup file operations
# Date: 2025-11-23
# Version: 2.0.4
# Category: handlers
#
# CHANGELOG (Max 5 entries):
#   - v2.0.4 (2025-11-23): Fix baseline snapshot messages for VS Code clickability
#     * Changed baseline snapshot message from {baseline_name} to {baseline_path}
#     * Users can now Ctrl+click on baseline paths to jump directly to files
#     * Shows full path (e.g., /home/aipass/backups/project/README-baseline-2025-11-23.md)
#   - v2.0.3 (2025-11-23): CRITICAL performance fix for versioned backup
#     * Skip copying unchanged files (only copy if mtime differs)
#     * Fixes 5s -> <1s regression (was copying all 5000+ files every time)
#     * Added file_changed flag to track copy necessity
#     * Only copy if is_new_file or file_changed
#   - v2.0.2 (2025-11-23): Added per-file output to snapshot mode
#     * Snapshot backup now shows each file as it's copied
#     * Displays "Copied (new)" or "Copied (updated)" for each file
#     * Matches the verbosity of versioned backup mode
#   - v2.0.1 (2025-11-23): Fixed automatic VS Code diff opening
#     * Removed automatic VS Code integration from copy_versioned_file()
#     * Diffs are now created silently without opening in editor
#     * VS Code integration still available via separate command
#   - v2.0.0 (2025-11-16): Extraction from backup_operations.py
#     * Extracted core file operations (lines 49-271)
#     * copy_file_with_structure for snapshot mode
#     * copy_versioned_file with baseline snapshots and diff generation
#     * Extensive Linux permission handling with temporarily_writable()
#     * Retry logic for filesystem errors
#
# CODE STANDARDS:
#   - Follow seed 3-layer architecture
#   - Handlers must be independent and transportable
#   - No cross-handler imports except within same domain
# =============================================

"""
File Operations Module - Core backup file handling

Core file copy operations with version management and permission handling.
Handles both snapshot (simple copy) and versioned (with diffs) backup modes.

Functions:
    copy_file_with_structure: Copy file with directory structure (snapshot mode)
    copy_versioned_file: Copy file with versioning and diff tracking
"""

# =============================================
# IMPORTS
# =============================================

import logging
import shutil
import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Import from handlers modules
from aipass.backup.apps.handlers.utils.system_utils import temporarily_writable, safe_print
from aipass.backup.apps.handlers.diff.diff_generator import should_create_diff, generate_diff_content
from aipass.backup.apps.handlers.models.backup_models import BackupResult

# =============================================
# SNAPSHOT MODE OPERATIONS
# =============================================


def copy_file_with_structure(source_file: Path, target_file: Path, backup_path: Path, result: BackupResult) -> bool:
    """Copy file with directory structure (snapshot mode).

    Simple file copy operation with permission handling for Linux.
    Creates the necessary directory structure and copies the source file
    to the target location with proper permission handling.

    Args:
        source_file (Path): Source file to copy
        target_file (Path): Target destination path
        backup_path (Path): Root backup path (for permission handling)
        result (BackupResult): BackupResult instance to track errors

    Returns:
        bool: True if copy succeeded, False otherwise
    """
    try:
        if len(str(target_file)) > 260:
            error_msg = f"Path too long (>250 chars): {source_file}"
            result.add_warning(error_msg)
            safe_print(f"  {error_msg}")
            return False

        # Use context manager to handle read-only ancestors
        # Find the first existing ancestor (could be parent or further up)
        check_path = target_file.parent
        while not check_path.exists() and check_path.parent != check_path:
            check_path = check_path.parent

        # Make the first existing ancestor writable during mkdir
        with temporarily_writable(check_path):
            target_file.parent.mkdir(parents=True, exist_ok=True)

        if not source_file.exists():
            error_msg = f"Source file missing: {source_file}"
            result.add_error(error_msg)
            safe_print(f"  {error_msg}")
            return False

        # Track if this is a new file for appropriate messaging
        is_new_file = not target_file.exists()

        # Wrap the copy operation with permission handling
        with temporarily_writable(target_file.parent):
            if target_file.exists():
                with temporarily_writable(target_file):
                    shutil.copy2(source_file, target_file)
            else:
                shutil.copy2(source_file, target_file)

        # Show feedback for each file copied (with clickable path)
        if is_new_file:
            safe_print(f"  Copied (new): {source_file}")
        else:
            safe_print(f"  Copied (updated): {source_file}")

        return True
    except PermissionError as e:
        error_msg = f"Permission denied copying {source_file}: {e}"
        result.add_error(error_msg)
        safe_print(f"  {error_msg}")
        logger.error(f"[file_operations] {error_msg}")
        return False
    except OSError as e:
        error_msg = f"OS error copying {source_file}: {e}"
        result.add_error(error_msg)
        safe_print(f"  {error_msg}")
        logger.error(f"[file_operations] {error_msg}")
        return False
    except Exception as e:
        error_msg = f"Unexpected error copying {source_file}: {e}"
        result.add_error(error_msg, is_critical=True)
        safe_print(f"  CRITICAL: {error_msg}")
        logger.error(f"[file_operations] CRITICAL: {error_msg}")
        return False

# =============================================
# VERSIONED MODE OPERATIONS
# =============================================


def copy_versioned_file(source_file: Path, target_file: Path, backup_path: Path, result: BackupResult) -> bool:
    """Copy file with versioning - keep old versions as diffs when file changes.

    Creates baseline snapshots for new files and diff files for changes.
    Implements the file-organized structure (file.py/file.py_diffs/file.py_v*.diff).

    The function handles:
    - Baseline snapshot creation for new files
    - Diff generation when existing files change
    - Permission handling for read-only directories
    - Retry logic for filesystem errors
    - File state tracking in the BackupResult object

    Args:
        source_file (Path): Source file to copy
        target_file (Path): Target destination path
        backup_path (Path): Root backup path (for permission handling)
        result (BackupResult): BackupResult instance to track errors and new files

    Returns:
        bool: True if copy succeeded, False otherwise
    """
    try:
        if len(str(target_file)) > 260:
            error_msg = f"Path too long (>250 chars): {source_file}"
            result.add_warning(error_msg)
            safe_print(f"  {error_msg}")
            return False

        # Use context manager to handle read-only ancestors
        # Find the first existing ancestor (could be parent or further up)
        check_path = target_file.parent
        while not check_path.exists() and check_path.parent != check_path:
            check_path = check_path.parent

        # Make the first existing ancestor writable during mkdir
        with temporarily_writable(check_path):
            target_file.parent.mkdir(parents=True, exist_ok=True)

        if not source_file.exists():
            error_msg = f"Source file missing: {source_file}"
            result.add_error(error_msg)
            safe_print(f"  {error_msg}")
            return False

        # Track if this is a new file
        is_new_file = not target_file.exists()

        # If this is a new file, save a baseline snapshot (full file)
        if is_new_file:
            try:
                # Create baseline snapshot with Drive-friendly naming (hyphens + preserved extension)
                timestamp = datetime.datetime.now().strftime("%Y-%m-%d")

                # Split filename and extension to preserve file type for Drive preview
                name_parts = target_file.name.rsplit('.', 1)
                if len(name_parts) == 2:
                    # Has extension: README.md -> README-baseline-2025-09-03.md
                    baseline_name = f"{name_parts[0]}-baseline-{timestamp}.{name_parts[1]}"
                else:
                    # No extension: Makefile -> Makefile-baseline-2025-09-03
                    baseline_name = f"{target_file.name}-baseline-{timestamp}"
                # Baseline goes in same folder as the file
                baseline_path = target_file.parent / baseline_name

                # Copy the full file as baseline with permission handling
                with temporarily_writable(target_file.parent):
                    shutil.copy2(source_file, baseline_path)
                safe_print(f"  Created baseline snapshot: {baseline_path}")

            except Exception as e:
                error_msg = f"Error creating baseline snapshot for {target_file}: {e}"
                result.add_warning(error_msg)
                safe_print(f"  {error_msg}")
                logger.warning(f"[file_operations] {error_msg}")

        # Track if file needs to be copied (changed or new)
        file_changed = False

        # If target file exists and is different, create versioned diff
        if not is_new_file and target_file.exists():
            try:
                # Check if files are different
                source_mtime = source_file.stat().st_mtime
                target_mtime = target_file.stat().st_mtime

                if source_mtime != target_mtime:
                    # Files are different - mark for copying
                    file_changed = True

                    # Check if we should create a diff
                    if should_create_diff(source_file):
                        # Create versioned diff showing changes
                        timestamp = datetime.datetime.fromtimestamp(target_mtime).strftime("%Y-%m-%d_%H-%M-%S")

                        # NEW FILE-ORGANIZED STRUCTURE
                        # Create file-specific diff folder next to the file: file.py_diffs/
                        file_diff_folder = target_file.parent / f"{target_file.name}_diffs"
                        with temporarily_writable(target_file.parent):
                            file_diff_folder.mkdir(parents=True, exist_ok=True)

                        versioned_name = f"{target_file.name}_v{timestamp}.diff"
                        versioned_path = file_diff_folder / versioned_name

                        # Generate diff between old (target) and new (source) versions
                        diff_content = generate_diff_content(target_file, source_file)

                        # Write diff to versioned file with permission handling
                        with temporarily_writable(file_diff_folder):
                            with open(versioned_path, 'w', encoding='utf-8') as f:
                                f.write(diff_content)

                        safe_print(f"  Created diff: {versioned_path}")
                    else:
                        safe_print(f"  Updated (no diff): {target_file.name}")
            except Exception as e:
                error_msg = f"Error creating version diff for {target_file}: {e}"
                result.add_warning(error_msg)
                safe_print(f"  {error_msg}")
                logger.warning(f"[file_operations] {error_msg}")

        # Only copy if file is new or changed (skip unchanged files for performance)
        if is_new_file or file_changed:
            try:
                with temporarily_writable(target_file.parent):
                    if target_file.exists():
                        with temporarily_writable(target_file):
                            shutil.copy2(source_file, target_file)
                    else:
                        shutil.copy2(source_file, target_file)
            except (FileExistsError, OSError, PermissionError) as e:
                # Handle various file system errors with context manager
                try:
                    with temporarily_writable(target_file.parent):
                        if target_file.exists():
                            with temporarily_writable(target_file):
                                target_file.unlink()  # Remove existing file
                        # Try copy again
                        shutil.copy2(source_file, target_file)
                except Exception as retry_error:
                    error_msg = f"Failed to copy after retry {source_file} -> {target_file}: {retry_error}"
                    result.add_error(error_msg)
                    safe_print(f"  {error_msg}")
                    logger.error(f"[file_operations] {error_msg}")
                    return False

        # Track new files separately
        if is_new_file:
            result.files_added += 1

        return True
    except PermissionError as e:
        error_msg = f"Permission denied copying versioned file {source_file}: {e}"
        result.add_error(error_msg)
        safe_print(f"  {error_msg}")
        logger.error(f"[file_operations] {error_msg}")
        return False
    except OSError as e:
        error_msg = f"OS error copying versioned file {source_file}: {e}"
        result.add_error(error_msg)
        safe_print(f"  {error_msg}")
        logger.error(f"[file_operations] {error_msg}")
        return False
    except Exception as e:
        error_msg = f"Unexpected error copying versioned file {source_file}: {e}"
        result.add_error(error_msg, is_critical=True)
        safe_print(f"  CRITICAL: {error_msg}")
        logger.error(f"[file_operations] {error_msg}")
        return False

# =============================================
# FILE COMPARISON OPERATIONS
# =============================================

def file_needs_backup(source_file: Path, backup_file: Path, last_timestamps: dict, source_dir: Path) -> bool:
    """Check if file needs backup based on modification time.

    Args:
        source_file: Source file to check
        backup_file: Backup destination file
        last_timestamps: Dictionary of last backup timestamps
        source_dir: Source directory root (for relative path calculation)

    Returns:
        True if file needs backup, False otherwise
    """
    if not backup_file.exists():
        return True

    source_mtime = source_file.stat().st_mtime
    rel_path = str(source_file.relative_to(source_dir))

    last_mtime = last_timestamps.get(rel_path, 0)
    return source_mtime > last_mtime


# =============================================
# MODULE INITIALIZATION
# =============================================

# No module-level initialization needed
