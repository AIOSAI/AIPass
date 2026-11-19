# =================== AIPass ====================
# Name: logging_allowed.py
# Description: The files the logging checkers let through: prax's published list, and what prax cannot own
# Version: 2.1.1
# Created: 2026-11-15
# Modified: 2026-11-16
# =============================================

"""The files the logging checkers let through, by exact path tail under ``src/aipass``.

K0 (stdlib logging) and K1 (a level-shaped class) are prax's own lists, ``LOGGING_ALLOWED`` and
``LOGGER_DOORS`` in prax's logger module, read with ``ast``: a broken prax import chain is when prax
most needs judging, and importing that module would raise then. ``ALLOWED`` holds only what prax cannot own.
"""

import ast
from pathlib import Path
from typing import Dict, FrozenSet, Iterable

from aipass.sentry.apps.handlers.json import json_handler

PRAX_LOGGER = Path(__file__).resolve().parents[4] / "prax" / "apps" / "modules" / "logger.py"
PUBLISHED: Dict[str, str] = {"K0": "LOGGING_ALLOWED", "K1": "LOGGER_DOORS"}

_CRASH_RECORD = "crash record: a plain append of the break, outside the logger, where the logger can be what broke"

ALLOWED: Dict[str, Dict[str, str]] = {
    "K2": {
        "hooks/apps/handlers/bridges/claude.py": _CRASH_RECORD,
        "hooks/apps/handlers/bridges/codex.py": _CRASH_RECORD,
        "hooks/apps/handlers/bridges/opencode.py": _CRASH_RECORD,
        "hooks/apps/handlers/bridges/seed.py": _CRASH_RECORD,
    },
}

#: The transcripts @ai_mail's dispatch writes into every target's logs/, not the branch's own logs.
MAIL_LANE_LOG_NAMES: FrozenSet[str] = frozenset({"dispatch_wake.log", "dispatch_stdout.log", "dispatch_stderr.log"})


def prax_published(name: str) -> Dict[str, str]:
    """One of prax's published ``{path tail: reason}`` lists. Raises ValueError when it cannot be read."""
    try:
        tree = ast.parse(Path(PRAX_LOGGER).read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError) as exc:
        raise ValueError(f"prax's {name} unreadable at {PRAX_LOGGER}: {exc}") from exc
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign):
            targets, value = [node.target], node.value
        else:
            continue
        if any(isinstance(t, ast.Name) and t.id == name for t in targets) and value is not None:
            return {str(tail): str(why) for tail, why in ast.literal_eval(value)}
    raise ValueError(f"prax's {name} not found in {PRAX_LOGGER}")


def prax_logging_allowed() -> Dict[str, str]:
    """The files prax publishes as building door one on stdlib logging."""
    return prax_published(PUBLISHED["K0"])


def published_lists() -> Dict[str, Dict[str, str]]:
    """Every list prax publishes, by the key it answers. Raises ValueError when one cannot be read."""
    return {key: prax_published(name) for key, name in PUBLISHED.items()}


def tail_in(path: str | Path, tails: Iterable[str]) -> bool:
    """Whether the path ends with one of these whole path tails."""
    posix = Path(path).as_posix()
    return any(posix == tail or posix.endswith("/" + tail) for tail in tails)


def allowed_by(path: str | Path, key: str, published: Dict[str, Dict[str, str]]) -> str | None:
    """The reason this file may do what ``key`` convicts, or None. ``published`` is ``published_lists()``."""
    entries = published[key] if key in published else ALLOWED.get(key, {})
    for tail, why in entries.items():
        if tail_in(path, (tail,)):
            json_handler.log_operation("logging_allowed", {"file": str(path), "key": key})
            return why
    return None
