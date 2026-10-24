# =================== AIPass ====================
# Name: ignore_patterns.py
# Description: Load Ignore Patterns Handler
# Version: 1.0.0
# Created: 2025-11-07
# Modified: 2026-10-24
# =============================================

"""
Load Ignore Patterns Handler
"""

import json
import logging
from typing import Set

from aipass.prax.apps.handlers.config.load import PRAX_ROOT
from aipass.prax.apps.handlers.json import json_handler

logger = logging.getLogger(__name__)

MODULE_NAME = "ignore_patterns"
PRAX_JSON_DIR = PRAX_ROOT / "prax_json"
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
    """Load ignore patterns from prax_logger config file"""
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
