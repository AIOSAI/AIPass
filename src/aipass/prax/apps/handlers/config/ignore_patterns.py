# =================== AIPass ====================
# Name: ignore_patterns.py
# Description: Load Ignore Patterns Handler
# Version: 1.2.0
# Created: 2025-11-07
# Modified: 2026-11-17
# =============================================

"""
Load Ignore Patterns Handler
"""

import json
from typing import Set

from aipass.prax.apps.handlers.config.load import PRAX_JSON_DIR
from aipass.prax.apps.handlers.json import json_handler

MODULE_NAME = "ignore_patterns"
PRAX_LOGGER_CONFIG_FILE = PRAX_JSON_DIR / "prax_logger_config.json"

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
    ".backup",
    "backups",
    "archive.local",
}


def load_ignore_patterns_from_config() -> Set[str]:
    """Ignore patterns from prax_logger config; the defaults when none are set; an unreadable config raises."""
    if not PRAX_LOGGER_CONFIG_FILE.exists():
        return DEFAULT_IGNORE_FOLDERS

    with open(PRAX_LOGGER_CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)

    patterns = config.get("config", {}).get("ignore_patterns", [])
    if patterns:
        json_handler.log_operation("ignore_patterns_loaded", {"pattern_count": len(patterns)})
        return set(patterns)

    return DEFAULT_IGNORE_FOLDERS
