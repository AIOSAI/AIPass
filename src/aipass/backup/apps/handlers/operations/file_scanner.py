# =================== AIPass ====================
# Name: file_scanner.py
# Description: File system scanning operations
# Version: 1.0.0
# Created: 2025-11-18
# Modified: 2026-03-09
# =============================================

"""
File Scanner - File system discovery and scanning

Scans source directory for files to backup, applying ignore patterns.
"""

# =============================================
# IMPORTS
# =============================================

import os
from pathlib import Path
from typing import Callable, List, Optional

from aipass.prax import logger
from aipass.backup.apps.handlers.json import json_handler

# =============================================
# FILE SCANNING OPERATIONS
# =============================================

def scan_files(source_dir: Path, should_ignore: Callable, show_progress: bool = False,
               whitelist: Optional[List[str]] = None,
               max_file_size_mb: int = 0) -> tuple[list[Path], dict]:
    """Scan source directory for files to backup.

    Args:
        source_dir: Root directory to scan
        should_ignore: Function to check if path should be ignored
        show_progress: Whether to show progress spinner (default: False)
        whitelist: Top-level directory names to scan. Empty/None = scan all (backwards compatible).
        max_file_size_mb: Skip files larger than this (MB). 0 = no limit.

    Returns:
        Tuple of (file_list, skipped_items_dict)
        - file_list: List of Path objects for files to backup
        - skipped_items: Dict with 'directories', 'files', and 'too_large' sets
    """
    json_handler.log_operation("scan_started")

    files_to_backup = []
    skipped_items = {"directories": set(), "files": set(), "too_large": set()}
    max_bytes = max_file_size_mb * 1024 * 1024 if max_file_size_mb > 0 else 0
    source_dir_str = str(source_dir)

    def _apply_whitelist(dirpath: str, dirnames: list) -> None:
        """At the top level only, filter dirnames to whitelist entries."""
        if whitelist and dirpath == source_dir_str:
            whitelist_set = set(whitelist)
            removed = [d for d in dirnames if d not in whitelist_set]
            dirnames[:] = [d for d in dirnames if d in whitelist_set]
            for d in removed:
                rel_dir = str(Path(dirpath).relative_to(source_dir) / d)
                skipped_items["directories"].add(rel_dir)

    def _check_file_size(file_path: Path) -> bool:
        """Check if file exceeds size cap. Returns True if too large."""
        if max_bytes <= 0:
            return False
        try:
            size = file_path.stat().st_size
            if size > max_bytes:
                rel_file = str(file_path.relative_to(source_dir))
                skipped_items["too_large"].add((rel_file, size))
                return True
        except OSError as e:
            logger.info(f"[file_scanner] Could not stat file for size check: {e}")
        return False

    if show_progress:
        from rich.progress import Progress, SpinnerColumn, TextColumn
        from rich.console import Console

        console = Console()

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            transient=True,
            console=console
        ) as progress:
            task = progress.add_task("Counting files...", total=None)

            # Walk directory tree
            for dirpath, dirnames, filenames in os.walk(source_dir):
                # Apply whitelist at top level
                _apply_whitelist(dirpath, dirnames)

                # Filter directories (modify in-place to prune walk)
                original_dirs = dirnames.copy()
                dirnames[:] = [d for d in dirnames if not should_ignore(Path(dirpath) / d)]

                # Track skipped directories
                for d in original_dirs:
                    if d not in dirnames:
                        rel_dir = str(Path(dirpath).relative_to(source_dir) / d)
                        skipped_items["directories"].add(rel_dir)

                # Process files
                for filename in filenames:
                    file_path = Path(dirpath) / filename

                    if should_ignore(file_path):
                        rel_file = str(file_path.relative_to(source_dir))
                        skipped_items["files"].add(rel_file)
                    elif _check_file_size(file_path):
                        continue  # Already tracked in too_large
                    else:
                        files_to_backup.append(file_path)
                        # Update spinner description with count occasionally
                        if len(files_to_backup) % 100 == 0:
                            progress.update(task, description=f"Found {len(files_to_backup)} files...")
    else:
        # Walk directory tree without progress display
        def _walk_error(err):
            """Handle os.walk errors (broken symlinks, permission denied)."""
            logger.info(f"[file_scanner] Skipping inaccessible path during walk: {err}")

        for dirpath, dirnames, filenames in os.walk(source_dir, onerror=_walk_error):
            # Apply whitelist at top level
            _apply_whitelist(dirpath, dirnames)

            # Filter directories (modify in-place to prune walk)
            original_dirs = dirnames.copy()
            dirnames[:] = [d for d in dirnames if not should_ignore(Path(dirpath) / d)]

            # Track skipped directories
            for d in original_dirs:
                if d not in dirnames:
                    rel_dir = str(Path(dirpath).relative_to(source_dir) / d)
                    skipped_items["directories"].add(rel_dir)

            # Process files
            for filename in filenames:
                file_path = Path(dirpath) / filename

                if should_ignore(file_path):
                    rel_file = str(file_path.relative_to(source_dir))
                    skipped_items["files"].add(rel_file)
                elif _check_file_size(file_path):
                    continue  # Already tracked in too_large
                elif file_path.exists():
                    files_to_backup.append(file_path)

    return files_to_backup, skipped_items


# =============================================
# MODULE INITIALIZATION
# =============================================

# No initialization needed - pure utility functions
