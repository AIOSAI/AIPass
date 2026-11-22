# =================== AIPass ====================
# Name: metadata.py
# Description: Branch name extraction and profile detection
# Version: 1.1.1
# Created: 2026-03-05
# Modified: 2026-11-22
# =============================================

"""Branch name extraction and profile detection."""

import re
from pathlib import Path

BRANCH_NAME_RULE = (
    "a branch name starts with a lowercase letter, then lowercase letters, digits, '_' or '-', at most 32 characters"
)
# Explicit a-z, never \w: \w admits é and other non-ASCII letters.
_BRANCH_NAME = re.compile(r"[a-z][a-z0-9_-]{0,31}")


def get_branch_name(target_path):
    """Extract branch name from target path (last folder name)."""
    return Path(target_path).name


def branch_name_refusal(name: str) -> str:
    """The refusal quoting BRANCH_NAME_RULE when name breaks it; empty when it keeps it."""
    if _BRANCH_NAME.fullmatch(name):
        return ""
    return f"REFUSED: {name!r} is not a valid branch name: {BRANCH_NAME_RULE}. Nothing was written."


def normalize_branch_name(name, case="lower"):
    """Normalize branch name: replace hyphens with underscores, apply case (the system stores lowercase)."""
    normalized = name.replace("-", "_")
    return normalized.upper() if case == "upper" else normalized.lower()


def detect_profile(target_path):
    """Detect the AIPass profile from a path. Returns 'AIPass Workshop' by default.

    Live value, not a fossil: birth certificates render it and the registry stores it."""
    path_str = str(target_path)
    if "/business/" in path_str.lower():
        return "Business"
    return "AIPass Workshop"
