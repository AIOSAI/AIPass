# =================== AIPass ====================
# Name: project_scope.py
# Description: Project-Scope Resolution (a project is its register)
# Version: 1.1.0
# Created: 2026-08-22
# Modified: 2026-10-17
# =============================================

"""Project Scope Resolution

A project root holds a ``*_REGISTRY.json`` with a top-level ``branches`` key (name alone matches plan registries).
Never consults ``__file__``: scope comes from the caller's location and each row's ``location``.
"""

import json
import os
from pathlib import Path
from typing import Dict, Optional

from aipass.prax import logger

from aipass.flow.apps.handlers.json import json_handler
from aipass.flow.apps.handlers.repo_root import exactly_named

MODULE_NAME = "project_scope"

REGISTER_GLOB = "*_REGISTRY.json"
REGISTER_KEY = "branches"


class UnreadableRegisterError(Exception):
    """A register candidate exists but cannot be listed, read or parsed."""


def _holds_register(directory: Path) -> bool:
    """True if `directory` holds a project register.

    Raises UnreadableRegisterError on a read failure: "no" would attribute rows to the enclosing project.
    """
    try:
        # glob is case-insensitive on Windows/macOS; exactly_named drops lowercase *_registry.json.
        candidates = exactly_named(sorted(directory.glob(REGISTER_GLOB)), "_REGISTRY.json")
    except OSError as e:
        raise UnreadableRegisterError(f"Cannot list {directory} for a project register: {e}") from e

    for candidate in candidates:
        try:
            with open(candidate, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
            raise UnreadableRegisterError(f"Unreadable project register {candidate}: {e}") from e
        if isinstance(data, dict) and REGISTER_KEY in data:
            return True
    return False


def find_project_root(start: Optional[Path], cache: Optional[Dict[Path, Optional[Path]]] = None) -> Optional[Path]:
    """Return the nearest ancestor of `start` (inclusive) holding a register.

    None, empty or relative `start` yields None: resolving it would use the process CWD.
    `cache` is per-operation, never module state: it has no invalidation path.
    """
    if start is None:
        return None
    if not str(start):
        return None
    if not start.is_absolute():
        logger.warning(f"[{MODULE_NAME}] Refusing to attribute relative path: {start}")
        return None

    # resolve() errors propagate: None would claim "no register above" unchecked.
    current = start if start.is_dir() else start.parent
    current = current.resolve()

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

    AIPASS_CALLER_CWD (set by drone), else the process CWD; never a branch name or passport.
    """
    env_cwd = os.environ.get("AIPASS_CALLER_CWD")
    if env_cwd:
        return Path(env_cwd)
    return Path.cwd()


def caller_project_root() -> Optional[Path]:
    """Return the project the caller is standing in, or None if none is."""
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
