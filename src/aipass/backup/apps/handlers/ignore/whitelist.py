# =================== AIPass ====================
# Name: whitelist.py
# Description: Whitelist loader and path membership check
# Version: 1.0.0
# Created: 2026-04-16
# Modified: 2026-04-23
# =============================================

"""Whitelist handler.

Loads an allow-list of paths that should always be included in a backup even
when a matching ignore pattern would otherwise skip them.
"""

import fnmatch

from ..audit import trail
from ..project import config


def load_whitelist(project_root: str) -> list[str]:
    """Load whitelist entries from project config.

    Args:
        project_root: Absolute path to the project root.

    Returns:
        List of whitelist path/glob entries.
    """
    cfg = config.load_project_config(project_root)
    entries = cfg.get("whitelist", [])
    trail.log_operation("load_whitelist", {"project_root": project_root, "count": len(entries)})
    return entries


def is_whitelisted(rel_path: str, whitelist: list[str]) -> bool:
    """Check whether a relative path is whitelisted.

    Args:
        rel_path: Path relative to the project root.
        whitelist: Whitelist entries loaded from configuration.

    Returns:
        True when the path is whitelisted (should be included regardless of ignore).
    """
    rel = rel_path.replace("\\", "/")
    for entry in whitelist:
        if fnmatch.fnmatch(rel, entry):
            return True
    return False


# =============================================
