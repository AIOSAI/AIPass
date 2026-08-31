# =================== AIPass ====================
# Name: project_scope.py
# Description: Project-Scope Resolution (a project is its register)
# Version: 1.0.0
# Created: 2026-08-22
# Modified: 2026-08-22
# =============================================

"""
Project Scope Resolution

Answers one question: **which project does this path belong to?**

Patrick's ruling (2026-08-22): A PROJECT IS ITS REGISTER. Not its repository
marker, not the presence of citizens, not nesting depth. A directory is a
project root if and only if it holds a project register -- a
``<NAME>_REGISTRY.json`` whose top level carries a ``branches`` key. That is
what distinguishes 15 real projects on this machine, including ones with ZERO
citizens (SPEAKEASY, FEEL_GOOD_APP) and one with no repository marker at all
(MARKETSTAND).

The ``branches`` key is load-bearing, not decoration. Three files on this
machine match ``*_REGISTRY.json`` and are NOT project registers:
``marketstand/inventory/LISTINGS_REGISTRY.json`` (a listings index),
``flow/flow_json/PLAN_REGISTRY.json`` and ``.../BRANCH_REGISTRY.json``
variants. A name-only test would have made ``inventory/`` and ``flow_json/``
into projects of their own -- and under a nearest-ancestor rule that is not a
cosmetic error: it silently removes rows from their real project's scope.

WHY THIS EXISTS SEPARATELY: seven files in flow answer "where am I" from
``Path(__file__)`` -- they find the tree flow's SOURCE lives in, which is the
right answer for flow's own registries and the wrong answer for "whose plan is
this". This module never consults ``__file__``. It reads the caller's location
as EVIDENCE (``AIPASS_CALLER_CWD``) and each row's own ``location``, and walks
up from there.

Usage:
    from aipass.flow.apps.handlers.plan.project_scope import (
        find_project_root, caller_project_root, describe_project,
    )

    caller = caller_project_root()          # Path | None
    cache  = {}                             # share across one operation
    row    = find_project_root(Path(loc), cache)
    in_scope = caller is not None and row == caller
"""

import json
import os
from pathlib import Path
from typing import Dict, Optional

from aipass.prax import logger

from aipass.flow.apps.handlers.json import json_handler
from aipass.flow.apps.handlers.repo_root import exactly_named

MODULE_NAME = "project_scope"

# A project register is named <NAME>_REGISTRY.json and carries a top-level
# "branches" list. Both halves are required -- see the module docstring.
REGISTER_GLOB = "*_REGISTRY.json"
REGISTER_KEY = "branches"


def _holds_register(directory: Path) -> bool:
    """True if `directory` holds a project register.

    A read failure is NOT treated as "yes". An unreadable or malformed
    candidate tells us nothing about whether this directory is a project, and
    answering "yes" on no evidence is how a subdirectory becomes its own
    project and its rows fall out of the real project's scope.
    """
    try:
        # exactly_named, not the glob alone: pathlib's glob is case-INSENSITIVE
        # on Windows and default macOS, so REGISTER_GLOB also matches flow's own
        # lowercase flow_json/*_registry.json plan registries there. Measured on
        # the live tree 2026-08-31: 237 files match the folded pattern and 0 of
        # them carry a "branches" key, so this was reachable-not-armed — the
        # second clause was holding, not the glob. A register-shaped file under a
        # lowercase name would make a subdirectory read as its own project.
        candidates = exactly_named(sorted(directory.glob(REGISTER_GLOB)), "_REGISTRY.json")
    except OSError as e:
        logger.warning(f"[{MODULE_NAME}] Cannot list {directory}: {e}")
        return False

    for candidate in candidates:
        try:
            with open(candidate, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
            logger.warning(f"[{MODULE_NAME}] Unreadable register candidate {candidate}: {e}")
            continue
        if isinstance(data, dict) and REGISTER_KEY in data:
            return True
    return False


def find_project_root(start: Optional[Path], cache: Optional[Dict[Path, Optional[Path]]] = None) -> Optional[Path]:
    """Return the nearest ancestor of `start` (inclusive) holding a register.

    Args:
        start: Absolute path to a file or directory. A relative path, an empty
               path or None yields None -- see below.
        cache: Optional directory -> root map, filled in as the walk proceeds.
               Resolving many rows shares one walk per ancestor chain; pass the
               SAME dict for the duration of one operation and drop it after.
               Deliberately not module state: a memo with no invalidation path
               is only safe while flow stays a one-shot CLI, and that is an
               assumption the caller can hold but the resolver cannot.

    Returns:
        The project root, or None when no register stands above `start`.

    A relative path is refused rather than resolved. ``Path("").resolve()`` is
    the process CWD, so an empty ``location`` field would silently attribute
    that row to whoever happened to be running the command -- the row would
    join the caller's project by accident. No base, no attribution.
    """
    if start is None:
        return None
    if not str(start):
        return None
    if not start.is_absolute():
        logger.warning(f"[{MODULE_NAME}] Refusing to attribute relative path: {start}")
        return None

    current = start if start.is_dir() else start.parent
    try:
        current = current.resolve()
    except OSError as e:
        logger.warning(f"[{MODULE_NAME}] Cannot resolve {start}: {e}")
        return None

    memo: Dict[Path, Optional[Path]] = cache if cache is not None else {}
    walked = []
    result: Optional[Path] = None
    while True:
        if current in memo:
            result = memo[current]
            break
        walked.append(current)
        if _holds_register(current):
            result = current
            break
        if current.parent == current:
            result = None
            break
        current = current.parent

    for seen in walked:
        memo[seen] = result
    return result


def caller_cwd() -> Path:
    """Return where the caller stood, as evidence.

    Drone sets AIPASS_CALLER_CWD before invoking flow. When it is absent flow
    was invoked directly (a test, or the module run in place) and the process
    CWD *is* the same kind of evidence -- a location, observed. What is never
    consulted is a CLAIM about identity: no branch name, no passport, no
    directory name.
    Mirrors handlers/plan/resolve_location.py, deliberately.
    """
    env_cwd = os.environ.get("AIPASS_CALLER_CWD")
    if env_cwd:
        return Path(env_cwd)
    return Path.cwd()


def caller_project_root() -> Optional[Path]:
    """Return the project the caller is standing in, or None if none is.

    Logged once per invocation, not per row: this is the single answer every
    scope decision in the run is measured against, and when a sweep later
    looks wrong the first question is which project it thought it was in.
    """
    cwd = caller_cwd()
    root = find_project_root(cwd)
    json_handler.log_operation(
        "caller_project_resolved",
        {"caller_cwd": str(cwd), "project": describe_project(root), "resolved": root is not None},
    )
    return root


def describe_project(root: Optional[Path]) -> str:
    """Human-readable name for a project root, for refusal messages."""
    return root.name if root is not None else "no project"
