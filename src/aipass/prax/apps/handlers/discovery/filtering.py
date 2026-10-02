# =================== AIPass ====================
# Name: filtering.py
# Description: Path Filtering
# Version: 1.1.0
# Created: 2025-11-10
# Modified: 2026-10-02
# =============================================

"""
PRAX Discovery Filtering

Path filtering for module discovery using ignore patterns.
"""

from pathlib import Path

# Import from prax config
from aipass.prax.apps.handlers.config.ignore_patterns import load_ignore_patterns_from_config
from aipass.prax.apps.handlers.json import json_handler

# The owner's ruling of 09-27 (20:37, 20:42): nothing looks into a dropbox, it is a
# sandbox like .archive. Three literal names, kept here rather than imported.
SANDBOX_DIRS = frozenset({"dropbox", ".archive", "__pycache__"})


def in_sandbox(path: Path, root: Path) -> bool:
    """True when path lies in a dropbox, an .archive or a __pycache__ below root.

    Only the parts of the path below root are compared, so a root that itself
    stands inside a directory of one of these names still sees its own tree. A
    path outside root is in none of root's sandboxes: False.
    """
    try:
        parts = Path(path).relative_to(root).parts
    except ValueError:
        return False
    return any(part in SANDBOX_DIRS for part in parts)


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
