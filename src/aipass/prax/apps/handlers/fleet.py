# =================== AIPass ====================
# Name: fleet.py
# Description: The fleet's citizens, read through @memory's door under a short cache
# Version: 1.0.0
# Created: 2026-11-08
# Modified: 2026-11-08
# =============================================

"""Fleet Rows Handler: prax keeps no census of its own; every census site reads these rows."""

import time
from pathlib import Path
from typing import Dict, List, Tuple

from aipass.prax.apps.handlers.json import json_handler

_TTL = 60.0

_cache: Dict[str, Tuple[float, List[Dict]]] = {}


def fleet_rows(repo_root: Path) -> List[Dict]:
    """Core, resident and declared-root citizens under *repo_root*; a door failure raises."""
    # Lazy: memory imports prax, so a top-level import of the door risks a cycle.
    from aipass.memory.apps.modules.door_registry_scope import fleet_branches

    key = str(repo_root)
    now = time.monotonic()
    hit = _cache.get(key)
    if hit is not None and now - hit[0] < _TTL:
        return hit[1]
    # The door logs every refused row at ERROR on each read, hence the cache.
    rows = fleet_branches(repo_root=Path(repo_root), name_from="registry", strict=True)
    _cache[key] = (now, rows)
    json_handler.log_operation("fleet_rows_read", {"repo_root": key, "rows": len(rows)})
    return rows
