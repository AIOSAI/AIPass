# =================== AIPass ====================
# Name: metadata.py
# Description: Branch name extraction and profile detection
# Version: 1.0.0
# Created: 2026-03-05
# Modified: 2026-03-10
# =============================================

"""Branch name extraction and profile detection."""

from pathlib import Path


def get_branch_name(target_path):
    """Extract branch name from target path (last folder name)."""
    return Path(target_path).name


def normalize_branch_name(name, case="upper"):
    """Normalize branch name: replace hyphens with underscores, apply case."""
    normalized = name.replace("-", "_")
    return normalized.upper() if case == "upper" else normalized.lower()


def detect_profile(target_path):
    """Detect AIPass profile from path. Returns 'AIPass Workshop' by default."""
    path_str = str(target_path)
    if "/business/" in path_str.lower():
        return "Business"
    return "AIPass Workshop"
