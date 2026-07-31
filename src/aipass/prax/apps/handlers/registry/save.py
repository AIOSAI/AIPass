# =================== AIPass ====================
# Name: save.py
# Description: Save Module Registry Handler
# Version: 1.0.0
# Created: 2025-11-07
# Modified: 2026-03-09
# =============================================

"""
Save Module Registry Handler

Saves the Prax system-wide module discovery registry with statistics.
Auto-updates timestamp and calculates statistics before saving.

Features:
- Saves registry to prax_registry.json
- Auto-updates timestamp to current UTC time
- Includes statistics (total modules, last updated, scan location)
- Creates directory if missing
- Logs save operation

Usage:
    from aipass.prax.apps.handlers.registry.save import save_module_registry

    modules = {"module1": {...}, "module2": {...}}
    save_module_registry(modules)
"""

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any

from aipass.prax.apps.handlers.config.load import PRAX_ROOT, ECOSYSTEM_ROOT
from aipass.prax.apps.handlers.json import json_handler

logger = logging.getLogger(__name__)

# =============================================
# CONFIGURATION
# =============================================

MODULE_NAME = "save"
PRAX_JSON_DIR = PRAX_ROOT / "prax_json"
REGISTRY_FILE = PRAX_JSON_DIR / "prax_registry.json"

# =============================================
# INTERNAL HELPERS
# =============================================


def _atomic_write(json_path: Path, content: str) -> None:
    """Write content to file atomically via temp file + rename.

    prax_registry.json is written by every branch's logging init plus the
    filesystem watcher, all racing on the same shared file with no lock.
    A plain open("w") can tear under concurrent writers and leave invalid
    JSON behind; os.replace() is atomic, so readers always see either the
    fully old or fully new file, never a partial mix.
    """
    fd, tmp_path = tempfile.mkstemp(dir=json_path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, json_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError as cleanup_err:
            logger.warning("save: temp file cleanup failed for '%s': %s", tmp_path, cleanup_err)
        raise


# =============================================
# HANDLER FUNCTION
# =============================================


def save_module_registry(modules: Dict[str, Dict[str, Any]]) -> bool:
    """Save module registry to prax_registry.json (system registry)

    Args:
        modules: Dict mapping module names to module info dicts

    Returns:
        True if save successful, False on error

    The registry is saved with this structure:
    {
        "registry_version": "1.0.0",
        "timestamp": "2025-11-07T...",
        "modules": {...},
        "statistics": {
            "total_modules": 42,
            "last_updated": "2025-11-07T...",
            "scan_location": "src/aipass"
        }
    }

    Example:
        >>> modules = {"test_module": {"relative_path": "test/module.py"}}
        >>> success = save_module_registry(modules)
        >>> if success:
        >>>     print(f"Saved {len(modules)} modules")
    """
    try:
        # Ensure directory exists
        PRAX_JSON_DIR.mkdir(parents=True, exist_ok=True)

        # Build registry structure with statistics
        registry_structure = {
            "registry_version": "1.0.0",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "modules": modules,
            "statistics": {
                "total_modules": len(modules),
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "scan_location": str(ECOSYSTEM_ROOT),
            },
        }

        # Save to file atomically (temp file + rename)
        content = json.dumps(registry_structure, indent=2, ensure_ascii=False)
        _atomic_write(REGISTRY_FILE, content)

        json_handler.log_operation("registry_saved", {"total_modules": len(modules)})

        return True

    except Exception as e:
        logger.error("save: failed to save module registry to '%s': %s", REGISTRY_FILE, e)
        return False
