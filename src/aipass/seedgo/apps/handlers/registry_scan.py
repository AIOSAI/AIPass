# =================== AIPass ====================
# Name: registry_scan.py
# Description: Case-Exact Registry Discovery
# Version: 1.0.0
# Created: 2026-08-31
# Modified: 2026-10-17
# =============================================

"""
Case-Exact Registry Discovery

pathlib's glob is case-insensitive on Windows and macOS; the SUFFIX is checked case-exactly, never the stem."""

import os
from pathlib import Path
from typing import List, Optional

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler

#: Cased on purpose: comparing it case-insensitively puts the defect back.
REGISTRY_SUFFIX = "_REGISTRY.json"

DEFAULT_REGISTRY_NAME = "AIPASS_REGISTRY.json"

CALLER_CWD_VAR = "AIPASS_CALLER_CWD"


def registries_in(directory: Path) -> List[Path]:
    """Registry files sitting directly in ``directory``, name-exact and sorted."""
    try:
        entries = sorted(directory.iterdir())
    except OSError as exc:
        logger.info("registry_scan: cannot list %s: %s", directory, exc)
        return []
    return [entry for entry in entries if entry.name.endswith(REGISTRY_SUFFIX) and entry.is_file()]


def find_registry_upward(start: Path) -> Optional[Path]:
    """First registry at or above ``start``, or None if the walk finds none."""
    for parent in [start] + list(start.parents):
        found = registries_in(parent)
        if found:
            return found[0]
    return None


def find_registry() -> Path:
    """The registry this process should read: CWD first, then this file's tree.

    An empty walk returns a NAME, not a file; callers treat it as an empty world."""
    from_cwd = find_registry_upward(Path.cwd())
    if from_cwd is not None:
        return from_cwd
    from_source = find_registry_upward(Path(__file__).resolve().parent)
    if from_source is not None:
        return from_source
    return Path.cwd() / DEFAULT_REGISTRY_NAME


def caller_registries() -> List[Path]:
    """Every registry in the first directory at or above the CALLING project.

    ``AIPASS_CALLER_CWD`` comes from drone, because seedgo's own cwd is seedgo."""
    caller_cwd = os.environ.get(CALLER_CWD_VAR, "")
    if not caller_cwd:
        return []
    caller_path = Path(caller_cwd)
    for parent in [caller_path] + list(caller_path.parents):
        found = registries_in(parent)
        if found:
            json_handler.log_operation(
                "caller_registries_found",
                {"directory": str(parent), "count": len(found)},
            )
            return found
    return []
