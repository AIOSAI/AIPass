# =================== AIPass ====================
# Name: path_builder.py
# Description: Backup path construction
# Version: 1.0.0
# Created: 2025-11-18
# Modified: 2026-03-09
# =============================================

"""
Path Builder - Backup destination path construction

Constructs destination paths based on backup mode and file structure.
"""

# =============================================
# IMPORTS
# =============================================

import hashlib
from pathlib import Path

from aipass.backup.apps.handlers.json import json_handler

# =============================================
# PATH CONSTRUCTION OPERATIONS
# =============================================

def build_backup_path(source_file: Path, source_dir: Path, backup_path: Path, mode: str) -> Path:
    """Construct backup destination path based on mode.

    Args:
        source_file: Source file path
        source_dir: Source directory root
        backup_path: Backup destination root
        mode: Backup mode ('snapshot' or 'versioned')

    Returns:
        Full backup file path
    """
    json_handler.log_operation("path_built")

    rel_path = source_file.relative_to(source_dir)

    if mode == 'versioned':
        # Versioned mode: file-based folders for version tracking
        # Check if filename is too long (>50 chars) and needs shortening
        if len(rel_path.name) > 50:
            # Use shortened hash-based folder name for long filenames
            name_hash = hashlib.md5(rel_path.name.encode()).hexdigest()[:8]
            short_name = rel_path.name[:30] + f"_{name_hash}"

            if str(rel_path.parent) == ".":
                file_folder = backup_path / "root" / short_name
            else:
                file_folder = backup_path / rel_path.parent / short_name
            return file_folder / rel_path.name
        else:
            # Normal path structure for shorter filenames
            if str(rel_path.parent) == ".":
                # Root-level file: AGENTS.md -> root/AGENTS.md/AGENTS.md
                file_folder = backup_path / "root" / rel_path.name
                return file_folder / rel_path.name
            else:
                # Subfolder file: backup.py -> backup/backup.py/backup.py
                file_folder = backup_path / rel_path.parent / rel_path.name
                return file_folder / rel_path.name
    else:
        # Snapshot and other modes: keep original flat structure
        return backup_path / rel_path


# =============================================
# MODULE INITIALIZATION
# =============================================

# Pure handler - no initialization needed
