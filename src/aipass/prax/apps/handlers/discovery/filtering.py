# =================== AIPass ====================
# Name: filtering.py
# Description: Path Filtering
# Version: 1.1.0
# Created: 2025-11-10
# Modified: 2026-10-24
# =============================================

"""PRAX Discovery Filtering"""

from pathlib import Path
from typing import Optional, Set

from aipass.prax.apps.handlers.config.ignore_patterns import load_ignore_patterns_from_config

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


def should_ignore_path(path: Path, root: Optional[Path] = None, patterns: Optional[Set[str]] = None) -> bool:
    """True when a part of path (below root, when given) exactly matches an ignore pattern."""
    parts = Path(path).parts
    if root is not None and Path(path).is_relative_to(root):
        parts = Path(path).relative_to(root).parts
    if patterns is None:
        patterns = load_ignore_patterns_from_config()
    return any(part in patterns for part in parts)
