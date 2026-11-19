# =================== AIPass ====================
# Name: whitelist.py
# Description: Whitelist loader and path membership check
# Version: 1.0.0
# Created: 2026-04-16
# Modified: 2026-11-14
# =============================================

"""Whitelist handler."""

import fnmatch

from ..audit import trail
from ..project import config


def load_whitelist(project_root: str) -> list[str]:
    """Load whitelist entries from project config."""
    cfg = config.load_project_config(project_root)
    entries = cfg.get("whitelist", [])
    trail.log_operation("load_whitelist", {"project_root": project_root, "count": len(entries)})
    return entries


def is_whitelisted(rel_path: str, whitelist: list[str]) -> bool:
    """Check whether a relative path is whitelisted."""
    for entry in whitelist:
        if fnmatch.fnmatch(rel_path, entry):
            return True
    return False
