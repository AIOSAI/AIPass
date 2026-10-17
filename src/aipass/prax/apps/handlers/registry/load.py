# =================== AIPass ====================
# Name: load.py
# Description: Load Module Registry Handler
# Version: 1.2.0
# Created: 2025-11-07
# Modified: 2026-10-17
# =============================================

"""Load Module Registry Handler"""

import json
import logging
from typing import Any, Dict, Optional

from aipass.prax.apps.handlers.config.load import PRAX_ROOT
from aipass.prax.apps.handlers.json import json_handler

logger = logging.getLogger(__name__)

MODULE_NAME = "load"
PRAX_JSON_DIR = PRAX_ROOT / "prax_json"
REGISTRY_FILE = PRAX_JSON_DIR / "prax_registry.json"


def load_module_registry() -> Optional[Dict[str, Dict[str, Any]]]:
    """Load module registry from prax_registry.json (system registry)

    {} when never written; None when unreadable, so no writer saves one module over the registry."""
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
        return None


def load_last_scan() -> Optional[Dict[str, Any]]:
    """What the last full scan reported, {} when no scan is on record, None when unreadable.

    None, not {}, so status's Last Scan line does not print "never" over a scanned registry."""
    if not REGISTRY_FILE.exists():
        return {}

    try:
        with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
            block = json.load(f).get("last_scan", {})
    except Exception as e:
        logger.warning("load: failed to read last_scan from '%s': %s", REGISTRY_FILE, e)
        return None

    return block if isinstance(block, dict) else {}
