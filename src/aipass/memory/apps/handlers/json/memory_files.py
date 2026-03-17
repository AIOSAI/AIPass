# =================== AIPass ====================
# Name: memory_files.py
# Description: Memory File Safe I/O Handler
# Version: 1.0.0
# Created: 2026-03-17
# Modified: 2026-03-17
# =============================================

"""
Memory File I/O Handler

Safe read/write operations for branch memory files (*.local.json, *.observations.json).
Handles atomic writes and proper error handling for .trinity/ file management.

Purpose:
    Prevent corruption of critical memory files during read/write operations.
    All memory file access should use these functions instead of direct json.load/dump.

Features:
    - Atomic writes (temp file + rename)
    - Safe error handling
    - Metadata helpers
    - Preserves formatting (indent=2, ensure_ascii=False)

Usage:
    from aipass.memory.apps.handlers.json.memory_files import read_memory_file, write_memory_file
"""

import json
import tempfile
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime

from aipass.prax.apps.modules.logger import get_system_logger

logger = get_system_logger()

# Resolve paths relative to handler location
_MEMORY_ROOT = Path(__file__).resolve().parents[3]
_CONFIG_DIR = _MEMORY_ROOT / "config"
_TEMPLATES_DIR = _MEMORY_ROOT / "apps" / "json_templates"

# No service imports - handlers are pure workers (3-tier architecture)
# No module imports (handler independence)


# =============================================================================
# CORE READ/WRITE OPERATIONS
# =============================================================================

def read_memory_file(file_path: Path) -> Dict[str, Any]:
    """
    Safe read of memory JSON file

    Handles file not found, corrupt JSON, and other read errors gracefully.

    Args:
        file_path: Path to memory JSON file

    Returns:
        Dict with success status and data: {'success': True, 'data': {...}} or {'success': False, 'error': '...'}

    Example:
        result = read_memory_file(Path("path/to/BRANCH.local.json"))
        if result['success']:
            data = result['data']
            sessions = data.get('sessions', [])
    """
    if not file_path.exists():
        return {
            'success': False,
            'error': f"File not found: {file_path}"
        }

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        return {
            'success': True,
            'file': str(file_path),
            'data': data
        }

    except json.JSONDecodeError as e:
        return {
            'success': False,
            'error': f"Corrupt JSON in {file_path.name}: {e}"
        }

    except PermissionError:
        return {
            'success': False,
            'error': f"Permission denied reading {file_path.name}"
        }

    except Exception as e:
        return {
            'success': False,
            'error': f"Failed to read {file_path.name}: {e}"
        }


def write_memory_file(file_path: Path, data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Atomic write of memory JSON file

    Uses temp file + rename strategy to prevent corruption on write failures.
    Preserves formatting (indent=2, ensure_ascii=False) for readability.

    Args:
        file_path: Path to memory JSON file
        data: JSON data to write (must be dict)

    Returns:
        Dict with success status: {'success': True, 'file': '...'} or {'success': False, 'error': '...'}

    Example:
        result = read_memory_file(path)
        if result['success']:
            data = result['data']
            data['sessions'].append(new_session)
            write_result = write_memory_file(path, data)

    Safety:
        - Writes to temp file first
        - Only renames if write succeeds
        - Original file unchanged if write fails
    """
    if not isinstance(data, dict):
        return {
            'success': False,
            'error': f"Data must be dict, got {type(data).__name__}"
        }

    try:
        # Create temp file in same directory (for atomic rename)
        temp_fd, temp_path = tempfile.mkstemp(
            dir=file_path.parent,
            prefix=f".{file_path.name}.",
            suffix=".tmp"
        )

        try:
            # Write to temp file
            with open(temp_fd, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.write('\n')  # Add final newline

            # Atomic rename (overwrites original)
            Path(temp_path).rename(file_path)

            return {
                'success': True,
                'file': str(file_path)
            }

        except Exception as e:
            # Clean up temp file on failure
            Path(temp_path).unlink(missing_ok=True)
            raise e

    except PermissionError:
        return {
            'success': False,
            'error': f"Permission denied writing {file_path.name}"
        }

    except Exception as e:
        return {
            'success': False,
            'error': f"Failed to write {file_path.name}: {e}"
        }


# =============================================================================
# METADATA HELPERS
# =============================================================================

def update_metadata(
    file_path: Path,
    **updates: Any,
) -> Dict[str, Any]:
    """
    Update document_metadata.status fields

    Convenient helper for updating metadata without manual read-modify-write.
    Only updates document_metadata.status fields, preserves rest of file.

    Args:
        file_path: Path to memory JSON file
        **updates: Key-value pairs to update in status section

    Returns:
        Dict with success status: {'success': True} or {'success': False, 'error': '...'}

    Example:
        # Update health and line count
        update_metadata(
            path,
            health="healthy",
            current_lines=450,
            last_health_check="2025-11-16"
        )

    Safety:
        - Uses atomic write
        - Creates metadata structure if missing
        - Preserves all other data
    """
    # Read current data
    read_result = read_memory_file(file_path)
    if not read_result['success']:
        return read_result

    data = read_result['data']

    # Ensure metadata structure exists
    if 'document_metadata' not in data:
        data['document_metadata'] = {}

    if 'status' not in data['document_metadata']:
        data['document_metadata']['status'] = {}

    # Apply updates
    status = data['document_metadata']['status']
    for key, value in updates.items():
        status[key] = value

    # Write back
    write_result = write_memory_file(file_path, data)

    return write_result


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def read_memory_file_data(file_path: Path) -> Optional[Dict[str, Any]]:
    """
    Read memory file and return data directly (no dict wrapper)

    Convenience function for simple reads where you just need the data.
    Returns None on any error.

    Args:
        file_path: Path to memory JSON file

    Returns:
        Parsed JSON data dict, or None on error

    Example:
        data = read_memory_file_data(path)
        if data:
            sessions = data.get('sessions', [])
    """
    result = read_memory_file(file_path)
    if result['success']:
        return result.get('data')
    return None


def write_memory_file_simple(file_path: Path, data: Dict[str, Any]) -> bool:
    """
    Write memory file and return simple success/failure boolean

    Convenience function for simple writes where you just need success flag.

    Args:
        file_path: Path to memory JSON file
        data: JSON data to write

    Returns:
        True if successful, False otherwise

    Example:
        data['sessions'].append(new_session)
        if write_memory_file_simple(path, data):
            print("Success!")
    """
    result = write_memory_file(file_path, data)
    return result['success']


# =============================================================================
# VALIDATION HELPERS
# =============================================================================

def validate_memory_file_structure(data: Dict[str, Any]) -> tuple[bool, str]:
    """
    Validate memory file has required structure

    Checks for document_metadata presence and basic structure.

    Args:
        data: Parsed JSON data

    Returns:
        Tuple of (is_valid, error_message)

    Example:
        data = read_memory_file_data(path)
        valid, error = validate_memory_file_structure(data)
        if not valid:
            logger.warning(f"Invalid structure: {error}")
    """
    if not isinstance(data, dict):
        return False, "Data is not a dictionary"

    if 'document_metadata' not in data:
        return False, "Missing 'document_metadata' field"

    metadata = data['document_metadata']

    if not isinstance(metadata, dict):
        return False, "'document_metadata' is not a dictionary"

    # Check for expected fields
    expected = ['document_type', 'document_name', 'version']
    missing = [field for field in expected if field not in metadata]

    if missing:
        return False, f"Missing metadata fields: {', '.join(missing)}"

    return True, ""


# =============================================================================
# TESTING
# =============================================================================

if __name__ == "__main__":
    import sys as _sys

    print("\n=== MEMORY FILE I/O HANDLER - Safe Operations Test ===\n")

    # Test with a file passed as argument, or show usage
    if len(_sys.argv) > 1:
        test_file = Path(_sys.argv[1])
    else:
        print("Usage: python memory_files.py <path_to_memory_file.json>")
        print("No file specified, exiting.")
        _sys.exit(0)

    if test_file.exists():
        print(f"[TEST] Reading {test_file.name}...")
        result = read_memory_file(test_file)

        if result['success']:
            file_data = result['data']
            print("+ Read successful")
            print(f"   Document type: {file_data.get('document_metadata', {}).get('document_type')}")
            file_status = file_data.get('document_metadata', {}).get('status', {}).get('health')
            print(f"   Status: {file_status}")

            # Validate structure
            valid, error = validate_memory_file_structure(file_data)
            if valid:
                print("+ Structure validation passed")
            else:
                print(f"- Structure validation failed: {error}")
        else:
            print(f"- Read failed: {result['error']}")
    else:
        print(f"\n[TEST] Test file not found: {test_file}")

    print()
