# =================== AIPass ====================
# Name: ignore_patterns.py
# Description: Ignore pattern loading and matching from JSON config
# Version: 1.0.0
# Created: 2026-03-14
# Modified: 2026-03-14
# =============================================

"""
Ignore Patterns Handler

Loads ignore/exception patterns from apps/json_templates/ignore_patterns.json
and provides pattern matching functions for backup file filtering.

Extracted from config_handler.py (FPLAN-0037) to separate data (JSON) from logic.
"""

# =============================================
# IMPORTS
# =============================================

import json
import os
from pathlib import Path
from typing import Dict, Set, List, Optional

from aipass.prax import logger
from aipass.backup.apps.handlers.json import json_handler

# =============================================
# PATTERN LOADING
# =============================================

_PATTERNS_JSON = Path(__file__).parents[2] / "json_templates" / "ignore_patterns.json"


def load_patterns() -> dict:
    """Load all pattern sets from the ignore_patterns.json file.

    Returns:
        Dictionary with all pattern sections from the JSON file.

    Raises:
        FileNotFoundError: If the JSON file is missing (fail loud).
        json.JSONDecodeError: If the JSON file is malformed.
    """
    if not _PATTERNS_JSON.exists():
        raise FileNotFoundError(
            f"[ignore_patterns] CRITICAL: Pattern file missing: {_PATTERNS_JSON}\n"
            f"Expected at: apps/json_templates/ignore_patterns.json\n"
            f"Cannot proceed without ignore patterns — backup would copy everything."
        )

    with open(_PATTERNS_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)

    json_handler.log_operation("patterns_loaded")
    logger.info(f"[ignore_patterns] Loaded patterns from {_PATTERNS_JSON}")
    return data


# =============================================
# LOAD PATTERN CONSTANTS
# =============================================

_data = load_patterns()

GLOBAL_IGNORE_PATTERNS: List[str] = _data["global_ignore_patterns"]["patterns"]
IGNORE_EXCEPTIONS: List[str] = _data["ignore_exceptions"]["patterns"]
CLI_TRACKING_PATTERNS: List[str] = _data["cli_tracking_patterns"]["patterns"]
DIFF_IGNORE_PATTERNS: List[str] = _data["diff_ignore_patterns"]["patterns"]
DIFF_INCLUDE_PATTERNS: List[str] = _data["diff_include_patterns"]["patterns"]
SOURCE_WHITELIST: List[str] = _data.get("source_whitelist", {}).get("directories", [])
MAX_FILE_SIZE_MB: int = _data.get("max_file_size_mb", {}).get("value", 100)

# =============================================
# HELPER FUNCTIONS
# =============================================


def get_ignore_patterns() -> List[str]:
    """Get the global ignore patterns list.

    Returns:
        Copy of global ignore patterns list
    """
    return GLOBAL_IGNORE_PATTERNS.copy()


def get_cli_tracking_patterns() -> List[str]:
    """Get the CLI tracking patterns list.

    Returns:
        Copy of CLI tracking patterns list
    """
    return CLI_TRACKING_PATTERNS.copy()


def filter_tracked_items(skipped_items: Dict[str, Set[str]]) -> Dict[str, Set[str]]:
    """Filter skipped items to only show project-specific items.

    Uses CLI tracking patterns to identify important items worth showing to user.

    Args:
        skipped_items: Dictionary with 'directories' and 'files' sets

    Returns:
        Filtered dictionary with only tracked items
    """
    tracking_patterns = get_cli_tracking_patterns()
    filtered_items = {
        "directories": set(),
        "files": set()
    }

    def matches_pattern(item_path: str, patterns: List[str]) -> bool:
        """Check if item path matches any tracking pattern."""
        for pattern in patterns:
            if pattern in item_path or item_path.startswith(pattern):
                return True
            # Check wildcard patterns
            if pattern.startswith('*') and item_path.endswith(pattern[1:]):
                return True
        return False

    # Filter directories
    for directory in skipped_items.get("directories", set()):
        if matches_pattern(directory, tracking_patterns):
            filtered_items["directories"].add(directory)

    # Filter files
    for file_path in skipped_items.get("files", set()):
        if matches_pattern(file_path, tracking_patterns):
            filtered_items["files"].add(file_path)

    return filtered_items


def _matches_exception(path_str: str, name: str, parts: set, exception: str) -> bool:
    """Check if a path matches a single exception pattern."""
    if "**" in exception:
        exception_parts = exception.split("/**")[0]
        return exception_parts in path_str or exception_parts in "/".join(parts)
    if exception.startswith('*') and name.endswith(exception[1:]):
        return True
    if exception == name:
        return True
    if exception in path_str:
        return True
    return False


def _matches_ignore_pattern(name: str, parts: set, path_str: str, pattern: str) -> bool:
    """Check if a path matches a single ignore pattern."""
    if pattern == "backups":
        return "backups" in parts
    if pattern == name:
        return True
    if pattern.startswith('*') and name.endswith(pattern[1:]):
        return True
    return pattern in parts or pattern in path_str


def should_ignore(path: Path, ignore_patterns: Optional[List[str]] = None,
                  exceptions: Optional[List[str]] = None,
                  backup_dest: Optional[Path] = None) -> bool:
    """Check if a file/folder should be ignored based on patterns.

    Centralizes ignore pattern matching logic used during backup scanning.
    Checks exceptions first (files that should NOT be ignored), then patterns.

    Args:
        path: Path object to check
        ignore_patterns: List of patterns to ignore (defaults to GLOBAL_IGNORE_PATTERNS)
        exceptions: List of exception patterns (defaults to IGNORE_EXCEPTIONS)
        backup_dest: Optional backup destination to always ignore

    Returns:
        True if path should be ignored, False otherwise

    Example:
        # From backup engine
        should_ignore(Path("/home/user/file.pyc"))  # True
        should_ignore(Path("/home/user/.gitignore"))  # False (exception)
    """
    if ignore_patterns is None:
        ignore_patterns = GLOBAL_IGNORE_PATTERNS
    if exceptions is None:
        exceptions = IGNORE_EXCEPTIONS

    path_str = str(path)
    parts = set(path_str.split(os.sep))
    name = path.name

    if backup_dest and str(backup_dest) in path_str:
        return True

    if 'Backups' in parts:
        return True

    for exception in exceptions:
        if _matches_exception(path_str, name, parts, exception):
            return False

    for pattern in ignore_patterns:
        if _matches_ignore_pattern(name, parts, path_str, pattern):
            return True

    return False


# =============================================
# MODULE INITIALIZATION
# =============================================

logger.info(f"[ignore_patterns] Module loaded — {len(GLOBAL_IGNORE_PATTERNS)} global patterns, "
            f"{len(IGNORE_EXCEPTIONS)} exceptions, {len(DIFF_IGNORE_PATTERNS)} diff-ignore, "
            f"{len(DIFF_INCLUDE_PATTERNS)} diff-include, "
            f"whitelist: {SOURCE_WHITELIST if SOURCE_WHITELIST else '(all)'}, "
            f"max_file_size: {MAX_FILE_SIZE_MB}MB")
