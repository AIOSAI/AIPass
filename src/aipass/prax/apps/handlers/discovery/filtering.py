# =================== AIPass ====================
# Name: filtering.py
# Description: Path Filtering
# Version: 1.1.0
# Created: 2025-11-10
# Modified: 2026-10-17
# =============================================

"""PRAX Discovery Filtering"""

from pathlib import Path

from aipass.prax.apps.handlers.config.ignore_patterns import load_ignore_patterns_from_config
from aipass.prax.apps.handlers.json import json_handler

# Nothing looks into a dropbox: it is a sandbox like .archive. Literal names, not imported.
SANDBOX_DIRS = frozenset({"dropbox", ".archive", "__pycache__"})


def in_sandbox(path: Path, root: Path) -> bool:
    """True when path lies in a dropbox, an .archive or a __pycache__ below root.

    Only parts below root count, so a root inside such a directory still sees its own tree."""
    try:
        parts = Path(path).relative_to(root).parts
    except ValueError:
        return False
    return any(part in SANDBOX_DIRS for part in parts)


def should_ignore_path(path: Path) -> bool:
    """Check if path should be ignored based on patterns from config"""
    path_parts = path.parts  # Keep original case for exact matching

    ignore_patterns = load_ignore_patterns_from_config()

    for part in path_parts:
        if part in ignore_patterns:
            json_handler.log_operation("discovery_filtered", {"ignored_path": str(path)})
            return True

    return False
