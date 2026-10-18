# =================== AIPass ====================
# Name: refusals.py
# Description: Host API Refusal Memory — a root that cannot be read is not re-asked every 5s
# Version: 1.0.0
# Created: 2026-08-19
# Modified: 2026-10-17
# =============================================

"""Host API Refusal Memory"""

import threading
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

from aipass.api.apps.handlers.json import json_handler

# Drone's answer, never drone's rule (a passport check here would drift); a minute, so a fixed root recovers.
REFUSAL_TTL_SECONDS = 60.0

# Keyed on (root, lane): a lane failing for its own reason must not silence the working lanes.
_refusals: Dict[Tuple[str, str], Tuple[float, str]] = {}
_refusal_guard = threading.Lock()


def _refusal_key(root: Path, lane: str) -> Tuple[str, str]:
    """What a remembered refusal is filed under.
    One definition: reader and writer disagreeing makes every lookup miss silently, tests still green."""
    return (str(root), lane)


def _reset_refusals() -> None:
    """Forget every remembered refusal — the door is asked fresh next time.
    Tests only (conftest, around every test): the window outlives a suite run; the server relies on the TTL."""
    with _refusal_guard:
        _refusals.clear()


def remembered_refusal(root: Path, lane: str) -> Optional[str]:
    """A refusal this lane already collected for this root, if it is still recent."""
    with _refusal_guard:
        remembered = _refusals.get(_refusal_key(root, lane))

        if remembered is None:
            return None

        refused_at, reason = remembered

        if time.monotonic() - refused_at > REFUSAL_TTL_SECONDS:
            del _refusals[_refusal_key(root, lane)]
            return None

        return reason


def remember_refusal(root: Path, lane: str, reason: str) -> None:
    """Keep a could-not-read answer so the next poll costs nothing."""
    with _refusal_guard:
        first_time = _refusal_key(root, lane) not in _refusals
        _refusals[_refusal_key(root, lane)] = (time.monotonic(), reason)

    if first_time:
        json_handler.log_operation(
            "host_api_root_unreadable",
            {"root": str(root), "lane": lane, "reason": reason},
        )
