# =================== AIPass ====================
# Name: logging_allowed.py
# Description: The one list of files the logging checkers let through, by exact path
# Version: 1.0.0
# Created: 2026-11-15
# Modified: 2026-11-15
# =============================================

"""The files the logging checkers let through, by exact path tail under ``src/aipass``.

TEMPORARY until prax publishes its own list. ``ALLOWED`` serves ``one_logger`` per key;
``LEGACY_*`` are exactly the files the old path tests passed, so no score moves while it is advisory.
"""

from pathlib import Path
from typing import Dict, FrozenSet, Iterable

from aipass.sentry.apps.handlers.json import json_handler

_FLOOR = "crash floor: the bridge break record, written when prax can be what broke"

#: key -> {path tail: why it may}. K0 stdlib, K1 level-shaped class, K2 log-file writer, K3 stream writer.
ALLOWED: Dict[str, Dict[str, str]] = {
    "K0": {
        "prax/apps/handlers/logging/jsonl_writer.py": "prax's standalone writer: its own failure can only go to stderr",
    },
    "K1": {
        "prax/apps/modules/logger.py": "SystemLogger is door one itself",
        "prax/apps/handlers/logging/direct.py": "DirectLogger is door one's direct form",
    },
    "K2": {
        "hooks/apps/handlers/bridges/claude.py": _FLOOR,
        "hooks/apps/handlers/bridges/codex.py": _FLOOR,
        "hooks/apps/handlers/bridges/opencode.py": _FLOOR,
        "hooks/apps/handlers/bridges/seed.py": _FLOOR,
    },
    "K3": {},
}

LEGACY_IMPORTS_ROUTER: FrozenSet[str] = frozenset({"prax/apps/modules/logger.py"})

LEGACY_LOG_VISIBILITY: FrozenSet[str] = frozenset(
    {
        "prax/apps/handlers/logging/__init__.py",
        "prax/apps/handlers/logging/direct.py",
        "prax/apps/handlers/logging/introspection.py",
        "prax/apps/handlers/logging/jsonl_writer.py",
        "prax/apps/handlers/logging/log_watchdog.py",
        "prax/apps/handlers/logging/setup.py",
        "prax/apps/modules/logger.py",
    }
)

LEGACY_LOG_HANDLER: FrozenSet[str] = frozenset(
    {
        "prax/apps/handlers/logging/__init__.py",
        "prax/apps/handlers/logging/direct.py",
        "prax/apps/handlers/logging/introspection.py",
        "prax/apps/handlers/logging/jsonl_writer.py",
        "prax/apps/handlers/logging/log_watchdog.py",
        "prax/apps/handlers/logging/setup.py",
    }
)

#: The transcripts @ai_mail's dispatch writes into every target's logs/, not the branch's own logs.
MAIL_LANE_LOG_NAMES: FrozenSet[str] = frozenset({"dispatch_wake.log", "dispatch_stdout.log", "dispatch_stderr.log"})


def tail_in(path: str | Path, tails: Iterable[str]) -> bool:
    """Whether the path ends with one of these whole path tails."""
    posix = Path(path).as_posix()
    return any(posix == tail or posix.endswith("/" + tail) for tail in tails)


def allowed_by(path: str | Path, key: str) -> str | None:
    """The reason this file may do what ``key`` convicts, or None."""
    for tail, why in ALLOWED.get(key, {}).items():
        if tail_in(path, (tail,)):
            json_handler.log_operation("logging_allowed", {"file": str(path), "key": key})
            return why
    return None
