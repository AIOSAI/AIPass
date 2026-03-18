# =================== AIPass ====================
# Name: line_counter.py
# Description: Memory File Line Counter Handler
# Version: 0.2.0
# Created: 2025-11-16
# Modified: 2026-03-06
# =============================================

"""
Line Counter Handler

Updates document_metadata.status.current_lines field in memory files.
Called after any edit to keep metadata accurate.

Purpose:
    Keep memory file metadata in sync with actual file state.
    Provides accurate current_lines count for rollover detection.

Independence:
    Uses json_handler for safe, atomic metadata updates
"""

import logging
from pathlib import Path
from typing import Dict, Any
from datetime import datetime

# Handler imports (relative within package)
from aipass.memory.apps.handlers.json.memory_files import update_metadata
from aipass.prax.apps.modules.logger import get_system_logger
from aipass.memory.apps.handlers.json.json_handler import log_operation

logger = get_system_logger()


# =============================================================================
# LINE COUNTING
# =============================================================================

def _count_physical_lines(file_path: Path) -> int:
    """
    Count physical lines in file

    Args:
        file_path: Path to file

    Returns:
        Number of lines
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return len(f.readlines())
    except Exception:
        return 0


# =============================================================================
# METADATA UPDATE
# =============================================================================

def update_line_count(file_path: Path) -> Dict[str, Any]:
    """
    Update current_lines in document_metadata.status

    Reads file, counts lines, updates metadata field using safe json_handler.

    Args:
        file_path: Path to memory JSON file

    Returns:
        Dict with success status and updated line count
    """
    if not file_path.exists():
        return {
            'success': False,
            'error': f"File not found: {file_path}"
        }

    # Count lines
    line_count = _count_physical_lines(file_path)

    # Update metadata using safe handler (atomic write)
    result = update_metadata(
        file_path,
        current_lines=line_count,
        last_health_check=datetime.now().strftime("%Y-%m-%d")
    )

    if not result['success']:
        return {
            'success': False,
            'error': f"Failed to update metadata: {result['error']}"
        }

    log_operation("update_line_count", {"file": file_path.name, "lines": line_count, "success": True})

    return {
        'success': True,
        'file': str(file_path),
        'lines': line_count
    }


def update_all_memory_files() -> Dict[str, Any]:
    """
    Update line counts for all memory files in AIPASS_REGISTRY

    Returns:
        Dict with update statistics
    """
    from aipass.memory.apps.handlers.monitor.detector import _read_registry, _get_memory_file_path

    branches = _read_registry()
    if not branches:
        return {
            'success': True,
            'updated': 0,
            'failed': 0,
            'message': 'No branches in registry'
        }

    updated = 0
    failed = []

    for branch in branches:
        branch_name = branch.get('name', 'UNKNOWN')

        for memory_type in ['observations', 'local']:
            file_path = _get_memory_file_path(branch, memory_type)

            if file_path is None:
                continue

            result = update_line_count(file_path)

            if result['success']:
                updated += 1
            else:
                failed.append((branch_name, memory_type, result.get('error')))

    return {
        'success': True,
        'updated': updated,
        'failed': len(failed),
        'failures': failed
    }
