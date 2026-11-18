# =================== AIPass ====================
# Name: registry_scan.py
# Description: Case-Exact Registry Discovery
# Version: 1.1.0
# Created: 2026-08-31
# Modified: 2026-11-17
# =============================================

"""
Case-Exact Registry Discovery

Whether a name is a registry's is drone's one predicate (the suffix, case-exact, never the stem); which entries
count is this file's policy: files only."""

import os
from pathlib import Path
from typing import List, Optional

from aipass.drone import is_registry_filename
from aipass.prax import logger
from aipass.sentry.apps.handlers.json import json_handler

DEFAULT_REGISTRY_NAME = "AIPASS_REGISTRY.json"

CALLER_CWD_VAR = "AIPASS_CALLER_CWD"


def registry_files_in(directory: Path) -> List[Path]:
    """Registry FILES sitting directly in ``directory``, sorted: drone names a registry, a directory is not one."""
    try:
        entries = sorted(directory.iterdir())
    except OSError as exc:
        logger.info("registry_scan: cannot list %s: %s", directory, exc)
        return []
    return [entry for entry in entries if is_registry_filename(entry.name) and entry.is_file()]


def find_registry_upward(start: Path) -> Optional[Path]:
    """First registry at or above ``start``, or None if the walk finds none."""
    for parent in [start] + list(start.parents):
        found = registry_files_in(parent)
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

    ``AIPASS_CALLER_CWD`` comes from drone, because sentry's own cwd is sentry."""
    caller_cwd = os.environ.get(CALLER_CWD_VAR, "")
    if not caller_cwd:
        return []
    caller_path = Path(caller_cwd)
    for parent in [caller_path] + list(caller_path.parents):
        found = registry_files_in(parent)
        if found:
            json_handler.log_operation(
                "caller_registries_found",
                {"directory": str(parent), "count": len(found)},
            )
            return found
    return []
