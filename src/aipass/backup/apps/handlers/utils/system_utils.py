# =================== AIPass ====================
# Name: system_utils.py
# Description: Platform-aware file and console utilities
# Version: 2.1.1
# Created: 2025-11-23
# Modified: 2026-03-09
# =============================================

"""
System Utilities

Platform-aware helper functions and context managers for file operations and console output.
Provides critical utilities for read-only file handling on Linux and emoji-safe printing
across platforms.

Key Functions:
    - temporarily_writable(): Context manager for safe read-only file modification
    - safe_print(): Emoji-aware console output with fallback support
    - EMOJI_SUPPORT: Platform-specific emoji capability constant
"""

# =============================================
# IMPORTS
# =============================================

import os
import stat
import sys
from contextlib import contextmanager
from pathlib import Path

from aipass.prax import logger
from aipass.backup.apps.handlers.json import json_handler

# =============================================
# CONSTANTS
# =============================================

# Fix console encoding for emojis (Linux/Windows compatibility)
EMOJI_SUPPORT = True
if sys.platform == 'win32':
    try:
        # Try to enable UTF-8 output on Windows
        os.system('chcp 65001 > nul')
        # Use getattr to safely call reconfigure if it exists
        reconfigure_stdout = getattr(sys.stdout, 'reconfigure', None)
        if reconfigure_stdout:
            reconfigure_stdout(encoding='utf-8', errors='replace')
        reconfigure_stderr = getattr(sys.stderr, 'reconfigure', None)
        if reconfigure_stderr:
            reconfigure_stderr(encoding='utf-8', errors='replace')
    except Exception as e:
        logger.info(f"[system_utils] UTF-8 console setup failed, disabling emoji support: {e}")
        EMOJI_SUPPORT = False

# =============================================
# CONTEXT MANAGERS
# =============================================

@contextmanager
def temporarily_writable(path):
    """Context manager to temporarily make a directory/file writable on Linux.

    This is critical for Linux because it strictly enforces read-only permissions,
    unlike Windows which allows owners to bypass them.

    Used in 10+ locations throughout backup operations for:
    - Creating new directories in read-only backup roots
    - Updating files in protected backup directories
    - Deleting files from read-only locations

    Args:
        path: Path object or string path to make temporarily writable

    Yields:
        Path object with write permissions temporarily enabled

    Example:
        with temporarily_writable(backup_path):
            # Perform operations that need write access
            shutil.copy2(source, target)
        # Permissions automatically restored here
    """
    path_obj = Path(path)
    original_mode = None

    try:
        # Store original permissions if path exists
        if path_obj.exists():
            original_mode = path_obj.stat().st_mode

            # Make writable for owner
            if path_obj.is_dir():
                # Directory: add write and execute permissions for owner
                path_obj.chmod(original_mode | stat.S_IWUSR | stat.S_IXUSR)
            else:
                # File: add write permission for owner
                path_obj.chmod(original_mode | stat.S_IWUSR)

        yield path_obj

    finally:
        # Restore original permissions if we changed them
        if original_mode is not None and path_obj.exists():
            try:
                path_obj.chmod(original_mode)
            except Exception as e:
                logger.warning(f"[system_utils] Failed to restore permissions on {path_obj}: {e}")

# =============================================
# FILESYSTEM OPERATIONS
# =============================================

def ensure_backup_directory(backup_dest: Path, backup_path: Path, is_dynamic: bool) -> tuple[bool, str | None]:
    """Create backup directory if needed with proper permission handling.

    Args:
        backup_dest: Root backup destination path
        backup_path: Specific backup folder path
        is_dynamic: True if dynamic mode (needs special handling)

    Returns:
        Tuple of (success: bool, error_message: str or None)
    """
    json_handler.log_operation("backup_directory_ensured")

    try:
        # Check if backup_dest exists and might be read-only
        if backup_dest.exists():
            # Use context manager to temporarily make parent writable
            with temporarily_writable(backup_dest.parent):
                with temporarily_writable(backup_dest):
                    backup_dest.mkdir(parents=True, exist_ok=True)
        else:
            # Create normally if it doesn't exist
            backup_dest.mkdir(parents=True, exist_ok=True)

        if is_dynamic:
            if backup_path.exists():
                with temporarily_writable(backup_path.parent):
                    with temporarily_writable(backup_path):
                        backup_path.mkdir(parents=True, exist_ok=True)
            else:
                backup_path.mkdir(parents=True, exist_ok=True)
        return True, None
    except PermissionError as e:
        logger.warning(f"[system_utils] Permission denied creating backup directory {backup_dest}: {e}")
        return False, f"Permission denied creating backup directory {backup_dest}: {e}"
    except OSError as e:
        logger.warning(f"[system_utils] OS error creating backup directory {backup_dest}: {e}")
        return False, f"OS error creating backup directory {backup_dest}: {e}"
    except Exception as e:
        logger.warning(f"[system_utils] Unexpected error creating backup directory {backup_dest}: {e}")
        return False, f"Unexpected error creating backup directory {backup_dest}: {e}"


def remove_empty_dirs(path: Path):
    """Remove empty directories recursively.

    Args:
        path: Root path to clean empty directories from
    """
    try:
        for item in path.iterdir():
            if item.is_dir():
                remove_empty_dirs(item)
                try:
                    item.rmdir()
                except OSError as e:
                    logger.info(f"[system_utils] Could not remove directory {item}: {e}")
    except Exception as e:
        logger.warning(f"[system_utils] Failed to remove empty dirs under {path}: {e}")


# =============================================
# HELPER FUNCTIONS
# =============================================

def safe_print(text):
    """Print text with emoji fallback for systems that don't support them.

    Handles console encoding issues across different platforms.

    Args:
        text: String to print (may contain emoji characters)

    Returns:
        None (prints to stdout)

    Example:
        safe_print("Backup complete!")
    """
    if not EMOJI_SUPPORT:
        # Replace emojis with text equivalents
        text = text.replace('!', '[CRITICAL]')
        text = text.replace('X', '[ERROR]')
        text = text.replace('!', '[WARNING]')
        text = text.replace('OK', '[SUCCESS]')
    try:
        # Use plain print() to avoid Rich console truncation at 80 chars
        # This preserves full paths for terminal clickability
        logger.info(text)
    except UnicodeEncodeError:
        # Final fallback - strip all non-ASCII characters
        safe_text = text.encode('ascii', errors='replace').decode('ascii')
        logger.info(safe_text)

# =============================================
# MODULE INITIALIZATION
# =============================================

# No initialization needed - pure utility functions
