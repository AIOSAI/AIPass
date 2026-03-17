# =================== AIPass ====================
# Name: save_registry.py
# Description: Save Registry Handler
# Version: 1.1.0
# Created: 2025-11-07
# Modified: 2025-11-07
# =============================================

"""
Save Registry Handler

Saves the Flow PLAN registry to JSON file with automatic timestamp updates.

Features:
- Saves flow_registry.json
- Auto-updates last_updated timestamp
- Creates directory if missing
- Graceful error handling
- Reusable across Flow modules

Usage:
    from aipass.flow.apps.handlers.registry.save_registry import save_registry
    registry = {"plans": {}, "next_number": 1}
    save_registry(registry)
"""

import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any

# INFRASTRUCTURE IMPORT PATTERN
_PKG_ROOT = Path(__file__).resolve().parents[4]
FLOW_ROOT = _PKG_ROOT / "flow"

# =============================================
# CONFIGURATION
# =============================================

MODULE_NAME = "save_registry"
FLOW_JSON_DIR = FLOW_ROOT / "flow_json"
REGISTRY_FILE = FLOW_JSON_DIR / "flow_registry.json"

# =============================================
# HANDLER FUNCTION
# =============================================

def save_registry(registry: Dict[str, Any], registry_file: str | None = None) -> bool:
    """Save PLAN registry

    Args:
        registry: Dictionary containing registry data
        registry_file: Optional filename (e.g. "fplan_registry.json",
            "dplan_registry.json"). When provided, saves to
            ``FLOW_JSON_DIR / registry_file`` instead of the default
            ``flow_registry.json``.

    Returns:
        True if save successful, False on error

    Automatically updates the last_updated timestamp before saving.
    Creates the flow_json directory if it doesn't exist.
    """
    target = FLOW_JSON_DIR / registry_file if registry_file else REGISTRY_FILE

    try:
        FLOW_JSON_DIR.mkdir(parents=True, exist_ok=True)
        registry["last_updated"] = datetime.now(timezone.utc).isoformat()
        with open(target, 'w', encoding='utf-8') as f:
            json.dump(registry, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False
