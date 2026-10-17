# =================== AIPass ====================
# Name: memory_config.py
# Description: Host API Memory Config Handler — @memory's rollover limits, served
# Version: 2.0.0
# Created: 2026-08-16
# Modified: 2026-10-17
# =============================================

"""
Host API Memory Config Handler

@memory's rollover limits through @memory's own --json verbs: this file routes,
decodes and reports, and resolves nothing itself. Reference: docs/host_api.md
"""

import json
from typing import Any, Dict, List, Optional

from aipass.prax import logger

# drone's router, the same door the verb lane uses: how a branch is reached is drone's to resolve.
import aipass.drone as drone

from aipass.api.apps.handlers.json import json_handler

MEMORY_TARGET = "@memory"
CONFIG_COMMAND = "config"
ROLLOVER_COMMAND = "rollover"

JSON_FLAG = "--json"

# Checks what a caller sends, never iterates their answer: a fourth type is @memory's to add.
ENTRY_TYPES = ("sessions", "key_learnings", "observations")

# A pre-check only: @memory validates too, and theirs rules if the two disagree.
LIMIT_MINIMUM = 1
LIMIT_MAXIMUM = 100

READ_TIMEOUT_SECONDS = 30
WRITE_TIMEOUT_SECONDS = 45


class MemoryConfigRefused(Exception):
    """The write was refused. The caller's problem, whoever noticed it."""

    def __init__(self, message: str, raw: str = "", suggestion: Optional[str] = None) -> None:
        """
        Args:
            message: The sentence to show the caller.
            raw: @memory's verbatim payload, when there is any.
            suggestion: Their remedy line, when the refusal carries one.
        """
        super().__init__(message)
        self.raw = raw
        self.suggestion = suggestion


class MemoryConfigUnavailable(Exception):
    """@memory could not be reached, or did not answer. Never their refusal."""


def read_config(branch: str = "") -> Dict[str, Any]:
    """Read the rollover limits — fleet-wide, or one branch's effective set."""
    args = ["get"]
    target_branch = _clean_branch(branch)
    if target_branch:
        args.append("@" + target_branch)

    document, raw = _document_of(_route(CONFIG_COMMAND, args, READ_TIMEOUT_SECONDS))

    # Refuse, never return empty rows: those would read as 'this branch has no limits'.
    _refuse_if_they_did(document, raw)

    if target_branch:
        payload: Dict[str, Any] = {
            "scope": "branch",
            "branch": document.get("branch", target_branch),
            "limits": _rows_of(document.get("limits")),
            "raw": raw,
        }
    else:
        payload = {
            "scope": "fleet",
            "defaults": _defaults_of(document.get("defaults")),
            "overrides": _overrides_of(document.get("overrides")),
            "raw": raw,
        }

    json_handler.log_operation("host_api_memory_config_read", {"scope": payload["scope"]})
    return payload


def set_branch_limit(branch: str, entry_type: str, count: Any) -> Dict[str, Any]:
    """Override one branch's limit for one entry type."""
    target_branch = _require_branch(branch)
    checked_type = _require_type(entry_type)
    checked_count = _require_count(count)

    document, raw = _route_write(
        CONFIG_COMMAND,
        ["set", "@" + target_branch, checked_type, str(checked_count)],
    )

    # Their echoes over the arguments sent: if normalisation ever differs, theirs is on disk.
    written_branch = document.get("branch", target_branch)
    written_type = document.get("entry_type", checked_type)
    written_count = document.get("count", checked_count)

    answer = _answer(document, raw, f"@{written_branch} {written_type} limit set to {written_count}")
    answer.update({"branch": written_branch, "type": written_type, "count": written_count})

    json_handler.log_operation(
        "host_api_memory_config_set",
        {"branch": written_branch, "type": written_type, "count": written_count},
    )
    return answer


def set_default_limit(entry_type: str, count: Any) -> Dict[str, Any]:
    """Change one global default, leaving every per-branch override alone."""
    checked_type = _require_type(entry_type)
    checked_count = _require_count(count)

    document, raw = _route_write(CONFIG_COMMAND, ["set-default", checked_type, str(checked_count)])

    written_type = document.get("entry_type", checked_type)
    written_count = document.get("count", checked_count)

    answer = _answer(document, raw, f"Default {written_type} limit set to {written_count}")
    answer.update({"type": written_type, "count": written_count})

    json_handler.log_operation(
        "host_api_memory_config_set_default",
        {"type": written_type, "count": written_count},
    )
    return answer


def push_defaults() -> Dict[str, Any]:
    """Reset EVERY branch's limits to the defaults."""
    document, raw = _route_write(ROLLOVER_COMMAND, ["push"])

    branches = document.get("branches")
    answer = _answer(document, raw, f"Pushed defaults to {branches} branches")
    answer["branches"] = branches

    json_handler.log_operation("host_api_memory_config_push", {"branches": branches})
    return answer


def _route(command: str, args: List[str], timeout: int) -> Any:
    """Run one @memory command through drone's router, asking for JSON."""
    # The flag is appended here and nowhere else: a call site without it gets prose, a 503.
    try:
        return drone.route_command(MEMORY_TARGET, command, [*args, JSON_FLAG], timeout=timeout)
    except drone.RoutingError as e:
        logger.error("[host_api] drone could not run %s %s: %s", MEMORY_TARGET, command, e)
        raise MemoryConfigUnavailable(f"{MEMORY_TARGET} {command} could not be run: {e}") from e


def _route_write(command: str, args: List[str]) -> Any:
    """Route a write, decode it, and raise their refusal if they spoke one."""
    document, raw = _document_of(_route(command, args, WRITE_TIMEOUT_SECONDS))
    _refuse_if_they_did(document, raw)
    return document, raw


def _text_of(result: Any) -> str:
    """The output to read, whichever stream it arrived on."""
    # The exit code is never consulted: @memory refuses with 0 branch-wide.
    stdout = (getattr(result, "stdout", "") or "").strip()
    if stdout:
        return stdout
    return (getattr(result, "stderr", "") or "").strip()


def _document_of(result: Any) -> Any:
    """Their one JSON object, or the honest admission that there was none."""
    raw = _text_of(result)

    try:
        document = json.loads(raw)
    except ValueError:
        logger.error("[host_api] @memory answered with something that is not JSON: %r", raw[:400])
        raise MemoryConfigUnavailable(f"{MEMORY_TARGET} did not answer with a JSON document: {raw[:400]}") from None

    # A missing ok defaults neither way: true passes malformed answers, false invents a refusal.
    if not isinstance(document, dict) or not isinstance(document.get("ok"), bool):
        logger.error("[host_api] @memory answered JSON with no verdict in it: %r", raw[:400])
        raise MemoryConfigUnavailable(f"{MEMORY_TARGET} did not answer with a verdict: {raw[:400]}")

    return document, raw


def _refuse_if_they_did(document: Dict[str, Any], raw: str) -> None:
    """Raise @memory's refusal, in their words, if the document carries one."""
    if document.get("ok"):
        return

    message = str(document.get("error") or "").strip() or f"{MEMORY_TARGET} refused, without saying why"
    offered = document.get("suggestion")
    suggestion = offered.strip() if isinstance(offered, str) and offered.strip() else None

    logger.info("[host_api] @memory refused: %s", message)
    json_handler.log_operation("host_api_memory_config_refused", {"detail": message})

    raise MemoryConfigRefused(
        f"{message} — Try: {suggestion}" if suggestion else message,
        raw=raw,
        suggestion=suggestion,
    )


def _answer(document: Dict[str, Any], raw: str, detail: str) -> Dict[str, Any]:
    """The success envelope for a write that is already known to have happened."""
    # ok is always true yet stays: @baud's client guards on it.
    answer: Dict[str, Any] = {"ok": True, "detail": detail, "raw": raw}

    if isinstance(document.get("pushed"), bool):
        answer["pushed"] = document["pushed"]

    return answer


def _defaults_of(defaults: Any) -> Dict[str, Any]:
    """The fleet defaults, one entry per type @memory reported."""
    if not isinstance(defaults, dict):
        return {}

    return {
        str(entry_type): {
            "count": row.get("count"),
            "auto_compact_cap": row.get("auto_compact_cap"),
        }
        for entry_type, row in defaults.items()
        if isinstance(row, dict)
    }


def _overrides_of(overrides: Any) -> List[Dict[str, Any]]:
    """Every branch deviating from the defaults, with the rows that deviate."""
    if not isinstance(overrides, dict):
        return []

    return [
        {"branch": str(name), "limits": _rows_of(limits)}
        for name, limits in overrides.items()
        if isinstance(limits, dict)
    ]


def _rows_of(limits: Any) -> List[Dict[str, Any]]:
    """One branch's limits as a list of rows, in @memory's own order."""
    if not isinstance(limits, dict):
        return []

    return [
        {
            "type": str(entry_type),
            "count": row.get("count"),
            "default": row.get("default_count"),
            "is_override": bool(row.get("is_override")),
            "source": row.get("source"),
            "auto_compact_cap": row.get("auto_compact_cap"),
        }
        for entry_type, row in limits.items()
        if isinstance(row, dict)
    ]


def _clean_branch(branch: Any) -> str:
    """A branch name with any leading '@' removed."""
    if not isinstance(branch, str):
        return ""
    return branch.strip().lstrip("@").strip()


def _require_branch(branch: Any) -> str:
    """A branch name that is present and shaped like one."""
    # Whether it EXISTS is @memory's ruling: a second copy of their registry would drift.
    name = _clean_branch(branch)
    if not name:
        raise MemoryConfigRefused("A branch is required, for example 'api' or '@api'")

    if not all(character.isalnum() or character in "_-" for character in name):
        raise MemoryConfigRefused(f"'{name}' is not a branch name")

    return name


def _require_type(entry_type: Any) -> str:
    """One of @memory's three entry types."""
    if not isinstance(entry_type, str) or entry_type.strip() not in ENTRY_TYPES:
        raise MemoryConfigRefused(f"Entry type must be one of: {', '.join(ENTRY_TYPES)}")

    return entry_type.strip()


def _require_count(count: Any) -> int:
    """A whole number inside @memory's documented bounds."""
    # bool first: it is an int to Python, and 'sessions True' is not a limit.
    if isinstance(count, bool) or not isinstance(count, int):
        raise MemoryConfigRefused(f"Count must be a whole number between {LIMIT_MINIMUM} and {LIMIT_MAXIMUM}")

    if count < LIMIT_MINIMUM or count > LIMIT_MAXIMUM:
        raise MemoryConfigRefused(
            f"Count must be between {LIMIT_MINIMUM} and {LIMIT_MAXIMUM} (got {count}) — "
            f"{LIMIT_MINIMUM} rolls over almost everything, past {LIMIT_MAXIMUM} defeats rollover entirely"
        )

    return count
