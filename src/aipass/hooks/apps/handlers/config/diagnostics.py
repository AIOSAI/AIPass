# =================== AIPass ====================
# Name: diagnostics.py
# Version: 1.2.0
# Description: JSONL diagnostic logging for hook engine
# Branch: hooks
# Layer: apps/handlers/config
# Created: 2026-05-19
# Modified: 2026-11-17
# =============================================

"""JSONL diagnostic logging — appends structured entries for hook activity."""

import sys
import tempfile
from pathlib import Path

from aipass.hooks.apps.handlers.json import json_handler
from aipass.prax import append_jsonl
from aipass.prax import logger

BRANCH_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_PROD_LOG_FILE = BRANCH_ROOT / "logs" / "engine.jsonl"


def _is_pytest_session() -> bool:
    """Detect pytest via sys.modules (immune to patch.dict(os.environ, clear=True))."""
    return "_pytest" in sys.modules


def _get_log_file() -> Path:
    """Resolve log path — temp dir during pytest, prod path otherwise."""
    if _is_pytest_session():
        p = Path(tempfile.gettempdir()) / "aipass_test_logs" / "hooks"
        p.mkdir(parents=True, exist_ok=True)
        return p / "engine.jsonl"
    return _PROD_LOG_FILE


LOG_FILE = _PROD_LOG_FILE


def log_entry(entry: dict) -> None:
    """Append a JSONL log entry for detailed diagnostics; the json trail is trail_event's, once per event."""
    try:
        append_jsonl(_get_log_file(), entry)
    except OSError as exc:
        logger.error("[HOOKS] log write failed: %s", exc)


def trail_event(event: str) -> None:
    """One json trail entry per engine event, however many rows it logged: engine.jsonl holds the rows."""
    json_handler.log_operation("trail_event", {"event": event, "log_file": str(_get_log_file())})


def tail_log(count: int = 20) -> list[str]:
    """Return the last N lines from the engine log."""
    if not LOG_FILE.exists():
        return []
    lines = LOG_FILE.read_text().strip().split("\n")
    return lines[-count:]
