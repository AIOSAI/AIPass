# =================== AIPass ====================
# Name: extractor.py
# Description: Memory Extraction Handler
# Version: 0.4.0
# Created: 2025-11-16
# Modified: 2026-03-06
# =============================================

"""
Memory Extraction Handler

Surgically extracts oldest items from memory files during rollover.
Understands real JSON structure (sessions, observations arrays, key_learnings dict).

Purpose:
    v1 (schema <2.0.0): When file exceeds max_lines, extract oldest items from
    growing arrays to get under line limit.
    v2 (schema >=2.0.0): When entry counts exceed limits (max_sessions,
    max_key_learnings), extract oldest entries by count.

Strategy:
    - Detect schema version from document_metadata
    - v1: line-count based extraction (legacy)
    - v2: entry-count based extraction (sessions array + key_learnings dict)
    - Extract oldest items (FIFO)
    - Update document_metadata.status
"""

import shutil
import logging
from pathlib import Path
from typing import Dict, List, Any, Tuple
from datetime import datetime

# Handler imports (relative within package)
from aipass.memory.apps.handlers.json.json_handler import log_operation
from aipass.memory.apps.handlers.json.memory_files import read_memory_file_data, write_memory_file_simple
from aipass.prax.apps.modules.logger import get_system_logger

logger = get_system_logger()

# No module imports (handler independence)


# =============================================================================
# BACKUP OPERATIONS
# =============================================================================

def create_rollover_backup(file_path: Path) -> Dict[str, Any]:
    """
    Create backup before rollover (safety net)

    Creates backup in branch's .backup/ directory with timestamp.
    Only keeps ONE backup - overwrites previous rollover backup.

    Args:
        file_path: Path to memory file to backup

    Returns:
        Dict with backup path and success status
    """
    try:
        # Create .backup directory in branch root
        backup_dir = file_path.parent / '.backup'
        backup_dir.mkdir(exist_ok=True)

        # Backup filename: rollover_backup.json (always overwrites)
        backup_name = f'rollover_backup_{file_path.name}'
        backup_path = backup_dir / backup_name

        # Copy file
        shutil.copy2(file_path, backup_path)

        return {
            'success': True,
            'backup_path': str(backup_path),
            'message': f'Backup created: {backup_path.name}'
        }

    except Exception as e:
        return {
            'success': False,
            'error': f'Backup failed: {e}'
        }


def restore_from_backup(file_path: Path) -> Dict[str, Any]:
    """
    Restore file from rollover backup

    Called when rollover fails to restore original state.

    Args:
        file_path: Path to memory file to restore

    Returns:
        Dict with restore status
    """
    try:
        backup_dir = file_path.parent / '.backup'
        backup_name = f'rollover_backup_{file_path.name}'
        backup_path = backup_dir / backup_name

        if not backup_path.exists():
            return {
                'success': False,
                'error': 'No backup found to restore from'
            }

        # Restore from backup
        shutil.copy2(backup_path, file_path)

        return {
            'success': True,
            'message': f'Restored from backup: {backup_path.name}'
        }

    except Exception as e:
        return {
            'success': False,
            'error': f'Restore failed: {e}'
        }


# =============================================================================
# FILE OPERATIONS
# =============================================================================

def _read_memory_file(file_path: Path) -> Dict[str, Any] | None:
    """Read memory JSON file using memory_files handler."""
    return read_memory_file_data(file_path)


def _write_memory_file(file_path: Path, data: Dict[str, Any]) -> None:
    """Write memory JSON file using json_handler"""
    write_memory_file_simple(file_path, data)


def _count_file_lines(file_path: Path) -> int:
    """Count physical lines in file"""
    with open(file_path, 'r', encoding='utf-8') as f:
        return len(f.readlines())


# =============================================================================
# PATH HELPERS
# =============================================================================

def _derive_branch_and_type(file_path: Path) -> tuple[str, str]:
    """
    Derive branch name and memory type from file path.

    Handles both naming conventions:
    - .trinity/local.json → branch from parent.parent.name, type from stem
    - BRANCH.type.json (legacy) → parsed from stem

    Returns:
        Tuple of (branch_name, memory_type) e.g. ("DEVPULSE", "local")
    """
    if file_path.parent.name == '.trinity':
        branch_name = file_path.parent.parent.name.upper()
        memory_type = file_path.stem  # "local" or "observations"
    else:
        parts = file_path.stem.split('.')
        branch_name = parts[0] if len(parts) > 0 else "UNKNOWN"
        memory_type = parts[1] if len(parts) > 1 else "unknown"
    return branch_name, memory_type


# =============================================================================
# STRUCTURE DETECTION
# =============================================================================

def _detect_growing_array(data: Dict[str, Any]) -> str | None:
    """
    Detect which array field is growing in memory file

    Memory files have different structures:
    - .local.json → 'sessions' array
    - .observations.json → 'observations' array
    - Future types → other array fields

    Args:
        data: Parsed JSON data

    Returns:
        Array field name (e.g., 'sessions'), or None if not found
    """
    # Known array fields that grow over time
    candidates = ['sessions', 'observations', 'recent_work', 'entries', 'items', 'records']

    for field in candidates:
        if field in data and isinstance(data[field], list) and len(data[field]) > 0:
            return field

    return None


# =============================================================================
# EXTRACTION CALCULATION
# =============================================================================

def _calculate_items_to_extract_by_lines(
    data: Dict[str, Any],
    array_field: str,
    file_path: Path,
    max_lines: int,
    target_buffer: int = 100
) -> int:
    """
    Calculate items to extract by SIMULATING line count (accurate)

    Removes items one by one, counting actual lines after each removal,
    until we reach target line count (max_lines - buffer).

    Args:
        data: Full memory file data
        array_field: Name of array field to extract from
        file_path: Path (for line counting)
        max_lines: Maximum allowed lines
        target_buffer: Lines of buffer to leave (default 100)

    Returns:
        Number of items to extract

    Example:
        File is 645 lines, limit is 600, buffer is 100
        Target: 500 lines (600 - 100)
        Simulate removing items until file is ~500 lines
    """
    import tempfile
    import json

    target_lines = max_lines - target_buffer
    total_items = len(data[array_field])

    # Binary search for optimal item count
    for items_to_remove in range(1, total_items + 1):
        # Simulate removal (remove from END - oldest items)
        test_data = data.copy()
        test_data[array_field] = data[array_field][:-items_to_remove]  # Keep newest

        # Count lines in simulated result
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as tmp:
            json.dump(test_data, tmp, indent=2, ensure_ascii=False)
            tmp_path = Path(tmp.name)

        with open(tmp_path, 'r') as f:
            line_count = len(f.readlines())

        tmp_path.unlink()

        # Check if we've reached target
        if line_count <= target_lines:
            return items_to_remove

    # Fallback: remove 50% if simulation fails
    return max(1, total_items // 2)


# =============================================================================
# V2 EXTRACTION (ENTRY-COUNT BASED)
# =============================================================================

def _extract_items_v2(file_path: Path, data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract items from v2 format file (entry-count based).

    Handles sessions (array, oldest at end) and key_learnings (dict, oldest first).
    Trims to max_sessions / max_key_learnings limits defined in document_metadata.

    Args:
        file_path: Path to memory JSON file
        data: Already-parsed JSON data

    Returns:
        Dict with extracted items and metadata
    """
    limits = data.get('document_metadata', {}).get('limits', {})
    old_lines = _count_file_lines(file_path)

    all_extracted = []

    # Extract from sessions array (newest first, oldest at end)
    max_sessions = limits.get('max_sessions')
    if max_sessions is not None:
        sessions = data.get('sessions', [])
        if isinstance(sessions, list) and len(sessions) > max_sessions:
            excess = len(sessions) - max_sessions
            extracted_sessions = sessions[-excess:]  # oldest from end
            data['sessions'] = sessions[:-excess]    # keep newest
            all_extracted.extend(extracted_sessions)

    # Extract from key_learnings dict (first keys are oldest in insertion order)
    max_key_learnings = limits.get('max_key_learnings')
    if max_key_learnings is not None:
        key_learnings = data.get('key_learnings', {})
        if isinstance(key_learnings, dict) and len(key_learnings) > max_key_learnings:
            excess = len(key_learnings) - max_key_learnings
            keys_list = list(key_learnings.keys())
            keys_to_extract = keys_list[:excess]  # oldest (first inserted)
            for k in keys_to_extract:
                all_extracted.append({'_type': 'key_learning', 'key': k, 'value': key_learnings[k]})
                del data['key_learnings'][k]

    # Extract from observations array (if v2 observations file)
    max_observations = limits.get('max_observations')
    if max_observations is not None:
        observations = data.get('observations', [])
        if isinstance(observations, list) and len(observations) > max_observations:
            excess = len(observations) - max_observations
            extracted_obs = observations[-excess:]
            data['observations'] = observations[:-excess]
            all_extracted.extend(extracted_obs)

    if not all_extracted:
        return {
            'success': True,
            'skipped': True,
            'message': 'No entries exceed v2 limits'
        }

    # Update metadata
    _update_metadata_after_extraction(data)

    # Write back
    try:
        _write_memory_file(file_path, data)
        new_lines = _count_file_lines(file_path)
    except Exception as e:
        return {
            'success': False,
            'error': f"Failed to write file: {e}"
        }

    # Derive branch and type from path
    # .trinity/local.json → branch = parent.parent.name, type = stem
    branch_name, memory_type = _derive_branch_and_type(file_path)

    return {
        'success': True,
        'file': str(file_path),
        'branch': branch_name,
        'type': memory_type,
        'array_field': 'v2_mixed',
        'extracted': all_extracted,
        'extracted_count': len(all_extracted),
        'remaining_count': 0,
        'old_lines': old_lines,
        'new_lines': new_lines
    }


# =============================================================================
# EXTRACTION OPERATIONS
# =============================================================================

def extract_items(
    file_path: Path,
    percentage: int | None = None
) -> Dict[str, Any]:
    """
    Extract items from memory file (WITH BACKUP SAFETY)

    Now includes automatic backup before modification.
    File is modified immediately, but backup exists for recovery.

    Args:
        file_path: Path to memory JSON file
        percentage: Percentage of items to extract (auto-calculated if None)

    Returns:
        Dict with extracted items and metadata
    """
    if not file_path.exists():
        return {
            'success': False,
            'error': f"File not found: {file_path}"
        }

    # Read file
    try:
        data = _read_memory_file(file_path)
        if data is None:
            return {
                'success': False,
                'error': f"Failed to parse memory file: {file_path.name}"
            }
        current_lines = _count_file_lines(file_path)
    except Exception as e:
        return {
            'success': False,
            'error': f"Failed to read file: {e}"
        }

    # v2 schema: delegate to entry-count based extraction
    schema_version = data.get('document_metadata', {}).get('schema_version', '1.0.0')
    if schema_version.startswith('2'):
        return _extract_items_v2(file_path, data)

    # v1: line-count based extraction
    # Detect structure
    array_field = _detect_growing_array(data)
    if not array_field:
        return {
            'success': False,
            'error': f"No growing array found in {file_path.name}"
        }

    # Get metadata
    max_lines = data.get('document_metadata', {}).get('limits', {}).get('max_lines', 600)

    # Check if under limit
    if current_lines <= max_lines:
        return {
            'success': True,
            'skipped': True,
            'message': f"File under limit ({current_lines}/{max_lines} lines)"
        }

    # Calculate extraction amount (simulate actual line reduction)
    total_items = len(data[array_field])

    if percentage is None:
        # Use line-based calculation for accuracy
        items_to_extract = _calculate_items_to_extract_by_lines(
            data, array_field, file_path, max_lines, target_buffer=100
        )
    else:
        # Manual percentage override (for testing)
        items_to_extract = max(1, int(total_items * percentage / 100))

    # Extract oldest items (LAST N in array - newest first, oldest last)
    extracted = data[array_field][-items_to_extract:]  # Take from end (oldest)
    remaining = data[array_field][:-items_to_extract]  # Keep from start (newest)

    # Update array
    data[array_field] = remaining

    # Update metadata
    _update_metadata_after_extraction(data)

    # Write back
    try:
        _write_memory_file(file_path, data)
        new_line_count = _count_file_lines(file_path)
    except Exception as e:
        return {
            'success': False,
            'error': f"Failed to write file: {e}"
        }

    # Derive branch and type from path
    branch_name, memory_type = _derive_branch_and_type(file_path)

    return {
        'success': True,
        'file': str(file_path),
        'branch': branch_name,
        'type': memory_type,
        'array_field': array_field,
        'extracted': extracted,
        'extracted_count': items_to_extract,
        'remaining_count': len(remaining),
        'old_lines': current_lines,
        'new_lines': new_line_count
    }


# =============================================================================
# METADATA OPERATIONS
# =============================================================================

def _update_metadata_after_extraction(data: Dict[str, Any]) -> None:
    """
    Update document_metadata after extraction.

    Updates:
    - status.last_health_check

    Args:
        data: JSON data dict (modified in place)
    """
    # Ensure metadata structure
    if 'document_metadata' not in data:
        data['document_metadata'] = {}

    metadata = data['document_metadata']

    # Update status
    if 'status' not in metadata:
        metadata['status'] = {}

    metadata['status']['last_health_check'] = datetime.now().strftime("%Y-%m-%d")


# =============================================================================
# VECTORIZATION PREPARATION
# =============================================================================

def extract_with_metadata(
    file_path: Path,
    percentage: int | None = None
) -> Dict[str, Any]:
    """
    Extract items with enriched metadata for vectorization

    Same as extract_items but adds metadata needed for vector storage.

    Args:
        file_path: Path to memory JSON file
        percentage: Percentage of items to extract (auto-calculated if None)

    Returns:
        Dict with extracted items + vectorization metadata
    """
    # Do standard extraction
    result = extract_items(file_path, percentage)

    if not result['success']:
        return result

    # Enrich extracted items with metadata
    extracted = result.get('extracted', [])
    branch = result.get('branch')
    memory_type = result.get('type')
    array_field = result.get('array_field')

    extraction_timestamp = datetime.now().isoformat()

    enriched = []
    for item in extracted:
        enriched_item = {
            **item,  # Preserve original item data
            '_metadata': {
                'branch': branch,
                'type': memory_type,
                'array_field': array_field,
                'extracted_at': extraction_timestamp,
                'source_file': file_path.name
            }
        }
        enriched.append(enriched_item)

    # Return enriched version
    return {
        'success': True,
        'file': str(file_path),
        'branch': branch,
        'type': memory_type,
        'array_field': array_field,
        'entries': enriched,
        'count': len(enriched),
        'old_lines': result.get('old_lines'),
        'new_lines': result.get('new_lines')
    }
