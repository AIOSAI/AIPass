# =================== AIPass ====================
# Name: filtering.py
# Description: Terminal Output Filtering
# Version: 1.0.0
# Created: 2025-11-10
# Modified: 2026-03-09
# =============================================

"""
PRAX Terminal Filtering

Filters terminal output to reduce noise from internal modules.
"""

import logging

logger = logging.getLogger(__name__)

import json
from typing import Set, Optional

# Import from prax config
from aipass.prax.apps.handlers.config.load import PRAX_JSON_DIR

from aipass.prax.apps.handlers.json import json_handler

# Module constants
MODULE_NAME = "prax_terminal"
CONFIG_FILE = PRAX_JSON_DIR / f"{MODULE_NAME}_config.json"

# Default modules to filter (prax internal modules)
DEFAULT_FILTERED_MODULES = {
    "prax_logger",
    "prax_handlers",
    "prax_config",
    "prax_registry",
    "prax_discovery",
    "prax_terminal",
}


def load_filtered_modules() -> Set[str]:
    """Load filtered modules from config

    Returns filtered modules set from config file,
    or default set if config doesn't exist.

    Returns:
        Set of module names to filter from terminal output
    """
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
                return set(config.get("filtered_modules", DEFAULT_FILTERED_MODULES))
        except Exception as e:
            logger.warning("Failed to load terminal filter config %s: %s", CONFIG_FILE, e)

    return DEFAULT_FILTERED_MODULES


def should_display_terminal(module_name: str, filtered_modules: Optional[Set[str]] = None) -> bool:
    """Determine if module should be displayed in terminal output

    Filters out prax internal modules by default to reduce noise.

    Args:
        module_name: Module name to check
        filtered_modules: Optional set of filtered modules (loads from config if None)

    Returns:
        True if module should be displayed, False if filtered
    """
    if filtered_modules is None:
        filtered_modules = load_filtered_modules()

    result = module_name not in filtered_modules
    json_handler.log_operation("terminal_filter_applied", {"module": module_name, "displayed": result})
    return result
