# =================== AIPass ====================
# Name: support_escalation.py
# Description: Shared event payloads and lane helpers for test_escalation.py and test_escalation_digest.py
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-17
# =============================================

"""Helpers for the tests of apps/handlers/escalation.py (no test_ prefix: never collected)."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that the module parses and imports

import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict

import pytest

# Never opened; branch-relative and built with Path so no absolute path or separator is hardcoded.
FLOW_LOG = str(Path("flow") / "logs" / "flow.log")

ERROR_EVENT = {
    "branch": "flow",
    "module": "cfg",
    "message": "connection refused",
    "log_file": FLOW_LOG,
    "fingerprint": "fp-connection-refused",
}

WARNING_EVENT = {
    "branch": "flow",
    "module": "watcher",
    "message": "queue depth at 91%",
    "log_file": FLOW_LOG,
    "raw_line": "2026-08-08 10:00:00.000 | watcher | WARNING | queue depth at 91%",
}


def _fire_error(lane, times: int = 1, **overrides: Any) -> Any:
    """Record *times* identical ERROR occurrences, returning the last decision."""
    payload = {**ERROR_EVENT, **overrides}
    decision = None
    for _ in range(times):
        decision = lane.record_error(**payload)
    return decision


def _fire_warning(lane, times: int = 1, **overrides: Any) -> Any:
    """Record *times* identical WARNING occurrences, returning the last decision."""
    payload = {**WARNING_EVENT, **overrides}
    decision = None
    for _ in range(times):
        decision = lane.record_warning(**payload)
    return decision


# Not "warning number {i}": the lane collapses integers, so those would all share one signature.
DISTINCT_WARNINGS = [
    "disk is filling up",
    "memory is filling up",
    "socket pool exhausted",
    "cache is cold",
    "queue is backed up",
]


def _fire_distinct(lane, index: int) -> Any:
    """Record one occurrence of the *index*-th genuinely distinct warning."""
    return _fire_warning(lane, times=1, message=DISTINCT_WARNINGS[index])


def _freeze_clock(monkeypatch: pytest.MonkeyPatch, lane) -> None:
    """Pin datetime.now() so every last_seen string comes out byte-identical.

    Reproduces the coarse Windows clock: tied last_seen values fall back to insertion order.
    """
    frozen = datetime(2026, 8, 9, 12, 0, 0)
    monkeypatch.setattr(
        lane,
        "datetime",
        SimpleNamespace(now=lambda: frozen, fromisoformat=datetime.fromisoformat),
    )


def _read_state(lane) -> Dict[str, Any]:
    """Read the raw state document off disk."""
    return json.loads(lane.STATE_FILE.read_text(encoding="utf-8"))


def _entry(lane, signature: str) -> Dict[str, Any]:
    """Read one signature's state entry off disk."""
    return _read_state(lane)["signatures"][signature]


def _write_state(lane, state: Dict[str, Any]) -> None:
    """Write the state document back to disk (test-side edit, single process)."""
    lane.STATE_FILE.write_text(json.dumps(state), encoding="utf-8")


def _age_first_seen(lane, signature: str, hours: float) -> None:
    """Backdate when a signature was first seen, so the aged-warning lane opens."""
    state = _read_state(lane)
    state["signatures"][signature]["first_seen"] = (datetime.now() - timedelta(hours=hours)).isoformat()
    _write_state(lane, state)


def _fire_aged_warning(lane, hours: float = 25, **overrides: Any) -> Any:
    """Seed a signature, backdate it past the age limit, then cross the threshold."""
    signature = _fire_warning(lane, times=1, **overrides)["signature"]
    _age_first_seen(lane, signature, hours)
    return _fire_warning(lane, times=2, **overrides)


def _age_last_digest(lane, signature: str, minutes: float) -> None:
    """Backdate a signature's last digest so its cooldown has elapsed."""
    state = _read_state(lane)
    state["signatures"][signature]["last_digest"] = (datetime.now() - timedelta(minutes=minutes)).isoformat()
    _write_state(lane, state)
