
# ===================AIPASS====================
# META DATA HEADER
# Name: vscode_integration.py - VS Code diff viewer integration
# Date: 2025-11-16
# Version: 2.0.0
# Category: handlers
#
# CHANGELOG (Max 5 entries):
#   - v2.0.0 (2025-11-16): Extracted from backup_diff.py
#     * VS Code diff viewer integration
#     * File comparison logic
#     * Baseline vs current comparison
#     * Updated imports to new handler locations
#
# CODE STANDARDS:
#   - Follow seed 3-layer architecture
#   - Handlers must be independent and transportable
#   - No cross-handler imports except within same domain
# =============================================

"""
VS Code Integration Handler

Opens file diffs in VS Code editor for visual comparison.
Supports baseline vs current and version-to-version comparisons.
"""

# =============================================
# IMPORTS
# =============================================

import sys
import os
import subprocess
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Import from handlers
from aipass.backup.apps.handlers.utils.system_utils import safe_print
from aipass.backup.apps.handlers.diff.version_manager import get_versioned_files

# =============================================
# VS CODE INTEGRATION
# =============================================

def show_file_diff(backup_path: Path, source_dir: Path, file_path: str, version1: str | None = None, version2: str | None = None) -> bool:
    """Show diff between two versions of a file in VS Code.

    Args:
        backup_path: Path to backup root directory
        source_dir: Path to source directory (for current file comparison)
        file_path: File path to show diff for
        version1: First version timestamp (optional)
        version2: Second version timestamp (optional)

    Returns:
        True if diff was opened successfully, False otherwise
    """
    try:
        versioned_files = get_versioned_files(backup_path, file_path)

        if not versioned_files:
            safe_print(f"No versioned files found for: {file_path}")
            return False

        # Find the matching file with normalized path comparison
        matching_file = None
        normalized_search_path = str(Path(file_path)).replace('\\', '/').lower()
        for base_path in versioned_files:
            normalized_base_path = str(base_path).replace('\\', '/').lower()
            if normalized_search_path in normalized_base_path:
                matching_file = base_path
                break

        if not matching_file:
            safe_print(f"File not found: {file_path}")
            return False

        versions = versioned_files[matching_file]

        if len(versions) < 1:
            safe_print(f"Only one version found for: {file_path}")
            return False

        # Determine which versions to compare
        if version1 and version2:
            if version1 not in versions or version2 not in versions:
                safe_print(f"Version not found. Available: {', '.join(versions)}")
                return False
        else:
            # Compare latest version with current file, or two most recent versions
            current_file = backup_path / matching_file
            if current_file.exists() and len(versions) >= 1:
                version1 = "current"
                version2 = versions[0]  # Most recent version
            elif len(versions) >= 2:
                version1 = versions[1]  # Second most recent
                version2 = versions[0]  # Most recent
            else:
                safe_print(f"Need at least 2 versions to compare")
                return False

        # Determine file paths for comparison using NEW STRUCTURE
        # For VS Code diff, we need actual files, not diff patches
        try:
            # NEW STRUCTURE: matching_file is like "root/CLAUDE.local.md/CLAUDE.local.md"
            # We need to find the file folder and look for baseline + current file

            # Extract the base filename for pattern matching
            base_filename = Path(matching_file).name
            file_folder_path = backup_path / Path(matching_file).parent

            # Look for baseline file in the file folder
            # Handle files with extensions like CLAUDE.local.md -> CLAUDE.local-baseline-*
            name_without_ext = base_filename.rsplit('.', 1)[0] if '.' in base_filename else base_filename
            baseline_pattern = f"{name_without_ext}-baseline-*"
            baseline_files = list(file_folder_path.glob(baseline_pattern))

            # Current backup file path (in the organized structure)
            current_backup_file = file_folder_path / base_filename

            # Source file path (live file in source directory)
            # Convert backup path back to source path
            matching_file_normalized = str(Path(matching_file)).replace('\\', '/')
            if matching_file_normalized.startswith("root/"):
                # Root level file: root/filename/filename -> filename
                source_relative_path = base_filename
            else:
                # Nested file: folder/filename/filename -> folder/filename
                source_relative_path = str(Path(matching_file).parent.parent / base_filename)

            source_file_path = source_dir / source_relative_path

            if baseline_files:
                # ALWAYS prefer baseline comparison when available
                file1_path = baseline_files[0]  # Use first baseline found
                file2_path = source_file_path   # Current source
                label1 = f"{base_filename} (baseline)"
                label2 = f"{base_filename} (current)"
            elif current_backup_file.exists():
                # No baseline, compare backup against current source
                file1_path = current_backup_file  # Backup version
                file2_path = source_file_path     # Live source
                label1 = f"{base_filename} (backup)"
                label2 = f"{base_filename} (current)"

                # Check if they're the same
                if file1_path.exists() and file2_path.exists():
                    if file1_path.stat().st_mtime == file2_path.stat().st_mtime:
                        safe_print(f"Note: Backup is identical to current file (no changes)")
                        safe_print(f"   This happens when Google Drive sync updates the backup")
            else:
                safe_print(f"Could not find backup file in new structure: {matching_file}")
                return False

            # Verify files exist
            if not file1_path.exists():
                safe_print(f"File not found: {file1_path}")
                return False
            if not file2_path.exists():
                safe_print(f"File not found: {file2_path}")
                return False

        except Exception as e:
            safe_print(f"Error locating files: {e}")
            logger.error(f"[vscode_integration] Error locating files for diff: {e}")
            return False

        # Open diff in VS Code
        safe_print(f"\n{'='*70}")
        safe_print(f"Opening diff in VS Code: {matching_file}")
        safe_print(f"Comparing: {label2} -> {label1}")
        safe_print('='*70)

        # Launch VS Code with diff view
        try:
            # Try to find VS Code command
            code_cmd = 'code'
            if sys.platform == 'win32':
                # On Windows, try common VS Code paths if 'code' not in PATH
                import shutil
                if not shutil.which('code'):
                    # Platform-specific VS Code detection
                    if sys.platform == 'win32':
                        # Windows VS Code path
                        vscode_path = Path(r"C:\Users") / os.environ.get('USERNAME', 'input') / r"AppData\Local\Programs\Microsoft VS Code\bin\code.cmd"
                        if vscode_path.exists():
                            code_cmd = str(vscode_path)
                        else:
                            code_cmd = 'code.cmd'
                    else:
                        # Linux - VS Code is usually in PATH or use snap
                        if Path('/snap/bin/code').exists():
                            code_cmd = '/snap/bin/code'
                        elif Path('/usr/bin/code').exists():
                            code_cmd = '/usr/bin/code'
                        else:
                            code_cmd = 'code'

            # Use subprocess for better error handling
            # Swap order so baseline (older) is on left, current (newer) is on right
            result = subprocess.run(
                [code_cmd, '--diff', str(file1_path), str(file2_path)],
                capture_output=True,
                text=True,
                shell=True if sys.platform == 'win32' else False
            )
            if result.returncode == 0:
                safe_print(f"Diff opened in VS Code")
            else:
                safe_print(f"VS Code returned code {result.returncode}")
                if result.stderr:
                    safe_print(f"Error: {result.stderr}")
        except FileNotFoundError:
            safe_print(f"VS Code command not found. Make sure 'code' is in your PATH")
            safe_print(f"You can manually compare:")
            safe_print(f"   File 1: {file2_path}")
            safe_print(f"   File 2: {file1_path}")
            return False
        except Exception as e:
            safe_print(f"Error launching VS Code: {e}")
            logger.error(f"[vscode_integration] Error launching VS Code: {e}")
            return False

        safe_print('='*70)
        return True

    except Exception as e:
        safe_print(f"Error generating diff: {e}")
        logger.error(f"[vscode_integration] Error in show_file_diff: {e}")
        return False
