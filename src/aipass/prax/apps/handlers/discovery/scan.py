# =================== AIPass ====================
# Name: scan.py
# Description: One-shot module discovery scan
# Version: 1.0.0
# Created: 2026-09-12
# Modified: 2026-10-24
# =============================================

"""One-shot discovery scan — the registry's only writer that tells the truth.

Reference: docs/discovery.md
"""

from datetime import datetime, timezone
from typing import Any, Dict, List

from aipass.prax.apps.handlers.discovery.scanner import discover_python_modules
from aipass.prax.apps.handlers.registry.load import load_module_registry
from aipass.prax.apps.handlers.registry.save import save_module_registry
from aipass.prax.apps.handlers.json import json_handler
from aipass.prax.apps.modules.logger import system_logger as logger

MODULE_NAME = "scan"


def run_scan() -> Dict[str, Any]:
    """Walk the ecosystem and make the registry a truthful snapshot.

    ``discovered_time`` carries over for a module on record: it means "first seen", not "last scanned".
    """
    before = load_module_registry()
    previous_unreadable = before is None
    if before is None:
        # Unreadable registry: the scan rebuilds it from disk, but nothing carries over or compares.
        before = {}
    found = discover_python_modules()

    for name, info in found.items():
        previous = before.get(name)
        if previous and previous.get("discovered_time"):
            info["discovered_time"] = previous["discovered_time"]

    added: List[str] = sorted(set(found) - set(before))
    removed: List[str] = sorted(set(before) - set(found))

    result: Dict[str, Any] = {
        "added": added,
        "removed": removed,
        "unchanged": len(found) - len(added),
        "total": len(found),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "previous_unreadable": previous_unreadable,
    }

    if not found and before:
        logger.warning("scan: found no modules, a broken root or filter; the %d on record were kept", len(before))
        result["saved"] = False
    else:
        result["saved"] = save_module_registry(
            found,
            scan_stats={
                "timestamp": result["timestamp"],
                "added": len(added),
                "removed": len(removed),
                "unchanged": result["unchanged"],
                "total": result["total"],
            },
        )
    if not result["saved"]:
        logger.error("scan: the registry could not be written; the counts above describe the walk, not the file")

    json_handler.log_operation(
        "module_scan",
        {"added": len(added), "removed": len(removed), "total": result["total"], "saved": result["saved"]},
    )
    return result
