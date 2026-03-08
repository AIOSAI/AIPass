# ===================AIPASS====================
# META DATA HEADER
# Name: detector.py - Rollover Trigger Detection Handler
# Date: 2025-11-16
# Version: 0.2.0
# Category: memory/handlers/monitor
#
# CHANGELOG (Max 5 entries):
#   - v0.2.0 (2026-03-06): Adapted for AIPass public repo - removed hardcoded paths
#   - v0.1.0 (2025-11-16): Initial version - detect 600-line rollover triggers
#
# CODE STANDARDS:
#   - Handler independence: No module imports
#   - Error handling: Returns status dicts (3-tier architecture)
#   - File size: <200 lines target
# =============================================

"""
Rollover Trigger Detection Handler

Monitors branch memory files via AIPASS_REGISTRY.json and detects when
files exceed their max_lines threshold (typically 600 lines).

Purpose:
    Detect rollover conditions without active monitoring. Called by
    rollover module to check all branches for files needing rollover.

Independence:
    No module imports - pure handler, transportable
"""

import json
import logging
from pathlib import Path
from typing import List, Dict, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# No service imports - handlers are pure workers (3-tier architecture)
# No module imports (handler independence)


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class RolloverTrigger:
    """Represents a file that needs rollover"""
    branch: str
    memory_type: str  # 'observations' or 'local'
    file_path: Path
    current_lines: int
    max_lines: int

    def __str__(self):
        return f"{self.branch}.{self.memory_type} ({self.current_lines}/{self.max_lines} lines)"


# =============================================================================
# REGISTRY OPERATIONS
# =============================================================================

def _read_registry() -> List[Dict[str, Any]]:
    """
    Read AIPASS_REGISTRY.json

    Returns:
        List of branch dictionaries
    """
    registry_path = Path.home() / "AIPASS_REGISTRY.json"

    if not registry_path.exists():
        return []

    try:
        with open(registry_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get('branches', [])
    except Exception as e:
        # No logging in handlers - let caller handle errors
        return []


def _get_memory_file_path(branch: Dict, memory_type: str) -> Path | None:
    """
    Get path to memory file for branch

    Args:
        branch: Branch dict from registry
        memory_type: 'observations' or 'local'

    Returns:
        Path to memory file, or None if not found
    """
    branch_path = Path(branch.get('path', ''))
    if not branch_path.exists():
        return None

    branch_name = branch.get('name', '').upper()
    file_name = f"{branch_name}.{memory_type}.json"
    file_path = branch_path / file_name

    return file_path if file_path.exists() else None


# =============================================================================
# CONFIG LOADING
# =============================================================================

def _load_config() -> Dict[str, Any]:
    """
    Load memory_bank.config.json

    Returns:
        Config dict, or empty dict on error
    """
    # Look for config relative to this handler's location
    config_path = Path(__file__).resolve().parents[3] / "config" / "memory_bank.config.json"

    if not config_path.exists():
        return {}

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


# =============================================================================
# LINE COUNTING
# =============================================================================

def _count_file_lines(file_path: Path) -> int:
    """
    Count physical lines in memory file

    Args:
        file_path: Path to JSON file

    Returns:
        Number of physical lines in file
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return len(f.readlines())
    except Exception:
        # Silent failure - handlers don't log (3-tier architecture)
        return 0


def _get_max_lines(file_path: Path, branch_name: str | None = None) -> int:
    """
    Get max_lines limit with priority: file metadata > branch config > default

    Args:
        file_path: Path to JSON file
        branch_name: Optional branch name for config lookup

    Returns:
        Max lines limit (default 600)
    """
    # 1. Try file-level metadata first (highest priority)
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            metadata = data.get('document_metadata', {})
            limits = metadata.get('limits', {})
            file_limit = limits.get('max_lines')
            if file_limit is not None:
                return file_limit
    except Exception:
        pass

    # 2. Try branch-level config (if branch_name provided or can be extracted)
    if branch_name is None:
        # Extract from filename (e.g., SEED.local.json -> SEED)
        parts = file_path.stem.split('.')
        branch_name = parts[0] if parts else None

    if branch_name:
        config = _load_config()
        branch_limits = config.get('rollover', {}).get('per_branch', {}).get(branch_name, {})
        if 'max_lines' in branch_limits:
            return branch_limits['max_lines']

    # 3. Fall back to global default from config
    config = _load_config()
    default_limit = config.get('rollover', {}).get('defaults', {}).get('max_lines')
    if default_limit is not None:
        return default_limit

    # 4. Final fallback to hardcoded 600
    return 600


# =============================================================================
# ROLLOVER DETECTION
# =============================================================================

def _should_rollover(file_path: Path) -> tuple[bool, int, int]:
    """
    Check if file should rollover

    Args:
        file_path: Path to memory JSON file

    Returns:
        Tuple of (should_rollover, current_lines, max_lines)
    """
    current_lines = _count_file_lines(file_path)
    max_lines = _get_max_lines(file_path)

    should_trigger = current_lines >= max_lines

    return (should_trigger, current_lines, max_lines)


def check_all_branches() -> Dict[str, Any]:
    """
    Check all branches for rollover triggers

    Scans AIPASS_REGISTRY.json and checks each branch's memory files
    (observations and local) for rollover conditions.

    Returns:
        Dict with success status, triggers list, and count
    """
    triggers = []

    # Read registry
    branches = _read_registry()
    if not branches:
        return {
            'success': True,
            'triggers': [],
            'count': 0,
            'message': 'No branches in registry'
        }

    # Check each branch
    for branch in branches:
        branch_name = branch.get('name', 'UNKNOWN')

        # Check both memory types
        for memory_type in ['observations', 'local']:
            file_path = _get_memory_file_path(branch, memory_type)

            if file_path is None:
                continue  # File doesn't exist, skip

            should_trigger, current_lines, max_lines = _should_rollover(file_path)

            if should_trigger:
                trigger = RolloverTrigger(
                    branch=branch_name,
                    memory_type=memory_type,
                    file_path=file_path,
                    current_lines=current_lines,
                    max_lines=max_lines
                )
                triggers.append(trigger)

    return {
        'success': True,
        'triggers': triggers,
        'count': len(triggers),
        'message': f'Found {len(triggers)} rollover triggers' if triggers else 'No rollover triggers detected'
    }


def check_single_file(file_path: Path) -> Dict[str, Any]:
    """
    Check single file for rollover trigger

    Args:
        file_path: Path to memory JSON file

    Returns:
        Dict with trigger status and details
    """
    if not file_path.exists():
        return {
            'success': False,
            'error': f"File not found: {file_path}"
        }

    should_trigger, current_lines, max_lines = _should_rollover(file_path)

    if should_trigger:
        # Extract branch and type from filename (e.g., SEED.observations.json)
        parts = file_path.stem.split('.')
        branch_name = parts[0] if len(parts) > 0 else "UNKNOWN"
        memory_type = parts[1] if len(parts) > 1 else "unknown"

        trigger = RolloverTrigger(
            branch=branch_name,
            memory_type=memory_type,
            file_path=file_path,
            current_lines=current_lines,
            max_lines=max_lines
        )

        return {
            'success': True,
            'trigger': trigger,
            'should_rollover': True
        }
    else:
        return {
            'success': True,
            'should_rollover': False,
            'current_lines': current_lines,
            'max_lines': max_lines,
            'remaining': max_lines - current_lines
        }


# =============================================================================
# STATISTICS
# =============================================================================

def get_rollover_stats() -> Dict[str, Any]:
    """
    Get rollover statistics for all branches

    Returns:
        Dict with statistics for all branches
    """
    stats = {
        'success': True,
        'total_branches': 0,
        'files_checked': 0,
        'files_ready': 0,
        'branches': {}
    }

    branches = _read_registry()
    stats['total_branches'] = len(branches)

    for branch in branches:
        branch_name = branch.get('name', 'UNKNOWN')
        branch_stats = {}

        for memory_type in ['observations', 'local']:
            file_path = _get_memory_file_path(branch, memory_type)

            if file_path is None:
                continue

            stats['files_checked'] += 1
            should_trigger, current_lines, max_lines = _should_rollover(file_path)

            branch_stats[memory_type] = {
                'current': current_lines,
                'max': max_lines,
                'ready': should_trigger,
                'remaining': max_lines - current_lines
            }

            if should_trigger:
                stats['files_ready'] += 1

        if branch_stats:
            stats['branches'][branch_name] = branch_stats

    return stats
