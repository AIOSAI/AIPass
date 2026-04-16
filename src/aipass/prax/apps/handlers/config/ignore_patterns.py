# =================== AIPass ====================
# Name: ignore_patterns.py
# Description: Load Ignore Patterns Handler
# Version: 1.0.0
# Created: 2025-11-07
# Modified: 2026-03-09
# =============================================

"""
Load Ignore Patterns Handler

Loads ignore patterns for module discovery from prax_logger_config.json.
Returns set of folder names to ignore during Python module scanning.

Features:
- Loads ignore_patterns from prax_logger_config.json
- Fallback to hardcoded defaults if config missing
- Returns as Set for fast lookup
- Used by module discovery system

Usage:
    from aipass.prax.apps.handlers.config.ignore_patterns import load_ignore_patterns_from_config

    patterns = load_ignore_patterns_from_config()
    if 'node_modules' in patterns:
        print("Will ignore node_modules")
"""

import json
import logging
from typing import Set

from aipass.prax.apps.handlers.config.load import PRAX_ROOT
from aipass.prax.apps.handlers.json import json_handler

logger = logging.getLogger(__name__)

# =============================================
# CONFIGURATION
# =============================================

MODULE_NAME = "ignore_patterns"
PRAX_JSON_DIR = PRAX_ROOT / "prax_json"
PRAX_LOGGER_CONFIG_FILE = PRAX_JSON_DIR / "prax_logger_config.json"

# Hardcoded fallback patterns
DEFAULT_IGNORE_FOLDERS = {
    ".git",
    "__pycache__",
    ".venv",
    "vendor",
    "node_modules",
    "Archive",
    "Backups",
    "External_Code_Sources",
    "WorkShop",
    ".claude-server-commander-logs",
    "backup",
    "backups",
    "archive.local",
}

# =============================================
# HANDLER FUNCTION
# =============================================


def load_ignore_patterns_from_config() -> Set[str]:
    """Load ignore patterns from prax_logger config file

    Returns:
        Set of folder names to ignore during module discovery.
        Falls back to DEFAULT_IGNORE_FOLDERS if config missing or invalid.

    The ignore patterns are used by should_ignore_path() to filter
    directories during recursive module scanning.

    Example:
        >>> patterns = load_ignore_patterns_from_config()
        >>> if '.git' in patterns:
        >>>     print("Will skip .git directories")
    """
    try:
        if not PRAX_LOGGER_CONFIG_FILE.exists():
            return DEFAULT_IGNORE_FOLDERS

        with open(PRAX_LOGGER_CONFIG_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)

        patterns = config.get("config", {}).get("ignore_patterns", [])
        if patterns:
            json_handler.log_operation("ignore_patterns_loaded", {"pattern_count": len(patterns)})
            return set(patterns)
    except Exception as e:
        logger.warning(
            "ignore_patterns: failed to load config from '%s', using defaults: %s", PRAX_LOGGER_CONFIG_FILE, e
        )

    return DEFAULT_IGNORE_FOLDERS
