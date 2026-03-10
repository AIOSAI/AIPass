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
from typing import Callable

# =============================================
# FILE SCANNING OPERATIONS
# =============================================

def scan_files(source_dir: Path, should_ignore: Callable, show_progress: bool = False) -> tuple[list[Path], dict]:
    """Scan source directory for files to backup.

    Args:
        source_dir: Root directory to scan
        should_ignore: Function to check if path should be ignored
        show_progress: Whether to show progress spinner (default: False)

    Returns:
        Tuple of (file_list, skipped_items_dict)
        - file_list: List of Path objects for files to backup
        - skipped_items: Dict with 'directories' and 'files' sets
    """
    files_to_backup = []
    skipped_items = {"directories": set(), "files": set()}

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
                    else:
                        files_to_backup.append(file_path)
                        # Update spinner description with count occasionally
                        if len(files_to_backup) % 100 == 0:
                            progress.update(task, description=f"Found {len(files_to_backup)} files...")
    else:
        # Walk directory tree without progress display
        def _walk_error(err):
            """Handle os.walk errors (broken symlinks, permission denied)."""
            pass  # Skip inaccessible paths silently

        for dirpath, dirnames, filenames in os.walk(source_dir, onerror=_walk_error):
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
                elif file_path.exists():
                    files_to_backup.append(file_path)

    return files_to_backup, skipped_items


# =============================================
# MODULE INITIALIZATION
# =============================================

# No initialization needed - pure utility functions
