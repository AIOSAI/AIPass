# =================== AIPass ====================
# Name: scan.py
# Description: One-shot module discovery scan
# Version: 1.0.0
# Created: 2026-09-12
# Modified: 2026-09-12
# =============================================

"""One-shot discovery scan — the registry's only writer that tells the truth.

DPLAN-0339 step 4. Discovery used to be incremental: every process that logged
started a recursive inotify watch over the whole ecosystem on a daemon thread,
and a module was registered only if it happened to be created while some process
was both alive and still walking. Measured 2026-09-11: the registry held 250 of
the 1,442 modules a scan finds — 17%, and it never pruned, so entries for files
deleted in August were still in it.

A scan does not have that failure mode. It walks once, compares what is on disk
against what is recorded, and writes the result. It is a SNAPSHOT, not a diff
log: after a scan the registry equals what the walk found, which is the property
the incremental path could never hold.

Cheap enough to schedule: the walk is ~0.18 s and the whole scan ~4.5 s on this
tree (1,589 directories), nearly all of it in the scanner's per-file stat calls.
No inotify, no thread, no observer — a plain walk that returns.
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

    Returns:
        Dict with ``added``/``removed`` (sorted module-name lists), ``unchanged``,
        ``total``, ``timestamp`` and ``saved`` (False when the write failed).

    A module counts as REMOVED when the scan no longer finds it — its file is
    gone, or it now matches an ignore rule. Both mean the same thing to every
    reader of the registry: it is not there any more.

    ``discovered_time`` is carried over for a module already on record, so the
    field keeps meaning "first seen" rather than "last scanned". A scan is not a
    rediscovery.
    """
    before = load_module_registry()
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
    }

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
