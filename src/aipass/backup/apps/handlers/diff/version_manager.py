
# ===================AIPASS====================
# META DATA HEADER
# Name: version_manager.py - Version discovery and management
# Date: 2025-11-16
# Version: 2.0.0
# Category: handlers
#
# CHANGELOG (Max 5 entries):
#   - v2.0.0 (2025-11-16): Extracted from backup_diff.py
#     * Version file discovery functionality
#     * Versioned file listing
#     * Support for file-organized structure
#     * Updated imports to new handler locations
#
# CODE STANDARDS:
#   - Follow seed 3-layer architecture
#   - Handlers must be independent and transportable
#   - No cross-handler imports except within same domain
# =============================================

"""
Version Manager Handler

Discovers and manages versioned backup files using the file-organized structure.
Supports version listing and filtering.
"""

# =============================================
# IMPORTS
# =============================================

import logging
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Import from handlers
from aipass.backup.apps.handlers.utils.system_utils import safe_print

# =============================================
# VERSION FILE DISCOVERY
# =============================================

def get_versioned_files(backup_path: Path, file_path: str | None = None) -> Dict[str, List[str]]:
    """Get all versioned files using new file-organized structure.

    Args:
        backup_path: Path to backup root directory
        file_path: Optional filter to search for specific file

    Returns:
        Dictionary mapping file paths to lists of version timestamps
    """
    versioned_files = {}

    if not backup_path.exists():
        return versioned_files

    # Normalize search path for cross-platform compatibility
    normalized_search_path = None
    if file_path:
        normalized_search_path = str(Path(file_path)).replace('\\', '/').lower()

    # NEW STRUCTURE: Look for *_diffs folders
    for diff_folder in backup_path.rglob('*_diffs'):
        if not diff_folder.is_dir():
            continue

        # Extract base filename from diff folder name (remove _diffs suffix)
        if not diff_folder.name.endswith('_diffs'):
            continue

        base_filename = diff_folder.name[:-6]  # Remove '_diffs'

        # Get relative path from backup root to the file
        # diff_folder structure: .../filename/filename_diffs/
        file_folder = diff_folder.parent
        if file_folder.name != base_filename:
            continue  # Skip if structure doesn't match expected pattern

        # Calculate base path for this file
        rel_path_to_file_folder = file_folder.relative_to(backup_path)
        base_path = str(rel_path_to_file_folder / base_filename)

        # Filter by search path if provided
        if file_path:
            normalized_base_path = str(base_path).replace('\\', '/').lower()
            if normalized_search_path is not None and normalized_search_path not in normalized_base_path:
                continue

        # Find all diff files in this folder
        versions = []
        for diff_file in diff_folder.glob('*_v*.diff'):
            filename = diff_file.name
            if '_v' in filename and filename.endswith('.diff'):
                # Extract version from filename: basename_v<timestamp>.diff
                version_part = filename.split('_v')[1].replace('.diff', '')
                versions.append(version_part)

        if versions:
            versioned_files[base_path] = sorted(versions, reverse=True)  # Newest first

    return versioned_files


def list_versioned_files(backup_path: Path) -> bool:
    """List all versioned files with their version counts.

    Args:
        backup_path: Path to backup root directory

    Returns:
        True if files were found and listed, False otherwise
    """
    try:
        versioned_files = get_versioned_files(backup_path)

        if not versioned_files:
            safe_print("No versioned files found")
            return False

        safe_print(f"\n{'='*70}")
        safe_print("VERSIONED FILES HISTORY")
        safe_print('='*70)

        for file_path, versions in versioned_files.items():
            version_count = len(versions)
            latest_version = versions[0] if versions else "unknown"

            safe_print(f"  {file_path}")
            safe_print(f"   Versions: {version_count} | Latest: {latest_version}")

            # Show first 3 versions
            for i, version in enumerate(versions[:3]):
                marker = ">" if i == 0 else " "
                safe_print(f"   {marker} v{version}")

            if len(versions) > 3:
                safe_print(f"   ... and {len(versions) - 3} more versions")
            safe_print("")

        safe_print('='*70)
        safe_print(f"Use: python backup.py diff --file <path> to see changes")
        return True

    except Exception as e:
        safe_print(f"Error listing versioned files: {e}")
        logger.error(f"[version_manager] Failed to list versioned files: {e}")
        return False
