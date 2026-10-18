# =================== AIPass ====================
# Name: save.py
# Description: Save Module Registry Handler
# Version: 1.1.0
# Created: 2025-11-07
# Modified: 2026-10-17
# =============================================

"""Save Module Registry Handler"""

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional

from aipass.prax.apps.handlers.config.load import PRAX_ROOT, ECOSYSTEM_ROOT
from aipass.prax.apps.handlers.json import json_handler

logger = logging.getLogger(__name__)

MODULE_NAME = "save"
PRAX_JSON_DIR = PRAX_ROOT / "prax_json"
REGISTRY_FILE = PRAX_JSON_DIR / "prax_registry.json"


def _existing_last_scan() -> Optional[Dict[str, Any]]:
    """The last_scan block already on disk, or None when there is none.

    Never raises: losing the previous scan stamp must not cost the write."""
    try:
        with open(REGISTRY_FILE, "r", encoding="utf-8") as handle:
            existing = json.load(handle)
    except (OSError, ValueError) as exc:
        logger.debug("save: no previous last_scan to carry over (%s)", exc)
        return None
    block = existing.get("last_scan") if isinstance(existing, dict) else None
    return block if isinstance(block, dict) else None


def _atomic_write(json_path: Path, content: str) -> None:
    """Write content to file atomically via temp file + rename.

    Concurrent writers share this file with no lock; os.replace never leaves torn JSON."""
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


def save_module_registry(modules: Dict[str, Dict[str, Any]], scan_stats: Optional[Dict[str, Any]] = None) -> bool:
    """Save module registry to prax_registry.json (system registry)"""
    try:
        PRAX_JSON_DIR.mkdir(parents=True, exist_ok=True)

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

        # Only a scan writes last_scan; every other writer carries it over (status reports it).
        if scan_stats is not None:
            registry_structure["last_scan"] = scan_stats
        else:
            previous = _existing_last_scan()
            if previous is not None:
                registry_structure["last_scan"] = previous

        content = json.dumps(registry_structure, indent=2, ensure_ascii=False)
        _atomic_write(REGISTRY_FILE, content)

        json_handler.log_operation("registry_saved", {"total_modules": len(modules)})

        return True

    except Exception as e:
        logger.error("save: failed to save module registry to '%s': %s", REGISTRY_FILE, e)
        return False
