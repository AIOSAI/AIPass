
# ===================AIPASS====================
# META DATA HEADER
# Name: diff_generator.py - Unified diff generation with binary detection
# Date: 2025-11-16
# Version: 2.0.0
# Category: handlers
#
# CHANGELOG (Max 5 entries):
#   - v2.0.0 (2025-11-16): Extracted from backup_diff.py
#     * Diff generation functionality
#     * Binary file detection
#     * Unified diff content generation
#     * Updated imports to new handler locations
#
# CODE STANDARDS:
#   - Follow seed 3-layer architecture
#   - Handlers must be independent and transportable
#   - No cross-handler imports except within same domain
# =============================================

"""
Diff Generation Handler

Generates unified diffs between file versions with binary file detection.
Supports pattern-based filtering for diff creation.
"""

# =============================================
# IMPORTS
# =============================================

import datetime
import difflib
from pathlib import Path

# Import from handlers
from aipass.backup.apps.handlers.utils.system_utils import safe_print
from aipass.backup.apps.handlers.config.config_handler import DIFF_IGNORE_PATTERNS, DIFF_INCLUDE_PATTERNS

# =============================================
# DIFF GENERATION
# =============================================

def should_create_diff(file_path: Path) -> bool:
    """Check if file should have diffs created based on ignore patterns.

    Args:
        file_path: Path to file to check

    Returns:
        True if diff should be created, False otherwise
    """
    # Check include patterns first (exceptions that should always have diffs)
    for pattern in DIFF_INCLUDE_PATTERNS:
        if file_path.match(pattern):
            return True

    # Then check ignore patterns
    for pattern in DIFF_IGNORE_PATTERNS:
        if file_path.match(pattern):
            return False

    # Default: create diff for all other files
    return True


def is_binary_file(file_path: Path) -> bool:
    """Check if a file is likely binary.

    Args:
        file_path: Path to file to check

    Returns:
        True if file appears to be binary, False otherwise
    """
    try:
        with open(file_path, 'rb') as f:
            chunk = f.read(1024)
        return b'\0' in chunk
    except Exception:
        return True  # Assume binary if we can't read it


def generate_diff_content(old_file: Path, new_file: Path) -> str:
    """Generate unified diff content between two files.

    Args:
        old_file: Path to old version of file
        new_file: Path to new version of file

    Returns:
        Unified diff string showing changes
    """
    try:
        # Check if files are likely binary
        if is_binary_file(old_file) or is_binary_file(new_file):
            return f"Binary file {old_file.name} changed\n"

        # Read file contents
        with open(old_file, 'r', encoding='utf-8', errors='replace') as f:
            old_lines = f.readlines()
        with open(new_file, 'r', encoding='utf-8', errors='replace') as f:
            new_lines = f.readlines()

        # Generate unified diff
        diff_lines = difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/{old_file.name}",
            tofile=f"b/{new_file.name}",
            fromfiledate=datetime.datetime.fromtimestamp(old_file.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
            tofiledate=datetime.datetime.fromtimestamp(new_file.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
            lineterm=''
        )

        return '\n'.join(diff_lines)

    except Exception as e:
        return f"Error generating diff: {e}\n"
