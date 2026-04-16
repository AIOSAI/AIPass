# =================== AIPass ====================
# Name: filtering.py
# Description: Path Filtering
# Version: 1.0.0
# Created: 2025-11-10
# Modified: 2026-03-09
# =============================================

"""
PRAX Discovery Filtering

Path filtering for module discovery using ignore patterns.
"""

from pathlib import Path

# Import from prax config
from aipass.prax.apps.handlers.config.ignore_patterns import load_ignore_patterns_from_config
from aipass.prax.apps.handlers.json import json_handler


def should_ignore_path(path: Path) -> bool:
    """Check if path should be ignored based on patterns from config

    Args:
        path: Path to check against ignore patterns

    Returns:
        True if path should be ignored, False otherwise
    """
    path_parts = path.parts  # Keep original case for exact matching

    # Load ignore patterns from config (with fallback to hardcoded)
    ignore_patterns = load_ignore_patterns_from_config()

    # Check against ignore patterns
    for part in path_parts:
        if part in ignore_patterns:
            json_handler.log_operation("discovery_filtered", {"ignored_path": str(path)})
            return True

    return False
