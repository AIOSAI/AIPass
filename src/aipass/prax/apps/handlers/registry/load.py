# =================== AIPass ====================
# Name: load.py
# Description: Load Module Registry Handler
# Version: 1.0.0
# Created: 2025-11-07
# Modified: 2026-03-09
# =============================================

"""
Load Module Registry Handler

Loads the Prax system-wide module discovery registry (prax_registry.json).
Returns empty dict if file doesn't exist or on error.

Features:
- Loads prax_registry.json from prax_json directory
- Extracts modules dict from registry structure
- Graceful error handling with logger
- Returns empty dict as fallback

Usage:
    from aipass.prax.apps.handlers.registry.load import load_module_registry

    modules = load_module_registry()
    print(f"Loaded {len(modules)} modules")
"""

import json
import logging
from typing import Dict, Any

from aipass.prax.apps.handlers.config.load import PRAX_ROOT
from aipass.prax.apps.handlers.json import json_handler

logger = logging.getLogger(__name__)

# =============================================
# CONFIGURATION
# =============================================

MODULE_NAME = "load"
PRAX_JSON_DIR = PRAX_ROOT / "prax_json"
REGISTRY_FILE = PRAX_JSON_DIR / "prax_registry.json"

# =============================================
# HANDLER FUNCTION
# =============================================


def load_module_registry() -> Dict[str, Dict[str, Any]]:
    """Load module registry from prax_registry.json (system registry)

    Returns:
        Dict mapping module names to module info dicts.
        Returns empty dict if file doesn't exist or on error.

    The registry structure is:
    {
        "registry_version": "1.0.0",
        "timestamp": "2025-11-07T...",
        "modules": {
            "module_name": {
                "relative_path": "...",
                "size": 1234,
                "modified_time": "..."
            }
        },
        "statistics": {...}
    }

    Example:
        >>> modules = load_module_registry()
        >>> if modules:
        >>>     print(f"Found {len(modules)} modules")
    """
    if not REGISTRY_FILE.exists():
        return {}

    try:
        with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            modules = data.get("modules", {})
            json_handler.log_operation("registry_loaded", {"module_count": len(modules)})
            return modules
    except Exception as e:
        logger.warning("load: failed to load module registry from '%s': %s", REGISTRY_FILE, e)
        return {}
