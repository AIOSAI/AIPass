# =================== AIPass ====================
# Name: lock.py
# Description: Host API Lock Handler — the screen lock's position, proxied from @skills
# Version: 1.0.0
# Created: 2026-09-13
# Modified: 2026-09-13
# =============================================

"""
Host API Lock Handler

`GET /v1/lock` (FPLAN-0585 row 2): whether the laptop's screen is locked, for
BAUD's header lock chip. Away from home, a glance answers "did I lock the
laptop?"; a tap on the same chip still locks it, through POST /v1/verbs/lock.

D0, THE SAME LINE THE MACHINE LANE HOLDS
------------------------------------------------------------------------
This server owns the pipe and never the meaning. Which logind session is the
graphical one, which reader answered and what sentence says so all live in
@skills' screen_lock, behind the door it publishes beside lock_screen():
`lock_state()`. This module asks it and relays the answer VERBATIM — all six
keys, the sentence included. The skill reads logind's LockedHint, the mechanism
its lock writes through, so read and write agree on its side by construction;
a second reader here would be a second answer to the same question.

The import sits inside the call, not at the top of the module: a server that
never serves this route imports nothing new.

READ SCOPE, NOT OPERATE
------------------------------------------------------------------------
A lock's position is observation. The POST that changes it stays under operate,
in verbs.py, untouched. Neither is gated: the lock never is, so its read is not
either.

THE STATUS LINE
------------------------------------------------------------------------
Every answer in the door's published shape is a 200:
  * `ok: True` with `locked` True or False — a reader answered, and `method`
    names which one.
  * `ok: False` with `locked` None — the skill COULD NOT TELL (`no_session`,
    `no_reader`, `read_failed`, its sentence in `detail`). That is a reading
    that says "cannot tell", not a failed owner, and the phone draws it as
    unknown — never as unlocked.

503 `lock_door_failed` only when the DOOR failed: it raised, or answered outside
its published shape. The skill promises never to raise, so either is a defect in
the door, named, and never a 500 traceback. The shape checked is what the chip
depends on and nothing more: a boolean `ok`, a `locked` key, and the two
agreeing — a bool when ok is True, None when it is False. An `ok: False` that
carried `locked: False` is exactly the answer a client could misdraw as
unlocked, so it is refused rather than relayed. Every other key rides through
untouched; its meaning is the skill's.

ONE READ PER SECOND
------------------------------------------------------------------------
A ReadCache at 1.0 s with single flight, the machine lane's window. A lock
changes rarely, but the phone re-reads at once after a tap and again a second
later, because the lock lands asynchronously.

What the cache stores:
  * Any answer in the published shape, `ok: False` included. Cannot-tell is a
    reading like any other and is served for its window.
  * A door failure, never. It is raised out of the producer, the one path
    ReadCache never stores, so the next request asks the door again.

KNOWN LIMIT — @skills', on record in FPLAN-0585
------------------------------------------------------------------------
The skill's reads carry no subprocess timeout. A hung logind or session bus
blocks the flight that asked, and nothing here can cut it short. Single flight
bounds the READS: one loginctl in flight however many phones ask, never one per
request. It does not bound the WAIT: every request behind that flight queues on
it, each holding a server worker thread while it waits, so a hang that outlasts
enough polls starves every other synchronous route too. Only a timeout inside
the skill bounds that.

Classes:
    LockDoorFailed - The door raised, or answered outside its published shape

Functions:
    read_lock() - The screen lock's position, at most one read per second
"""

from typing import Any, Dict

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler
from aipass.api.apps.handlers.host.read_cache import ReadCache

# The window every caller shares — the machine lane's. See the docstring.
LOCK_TTL_SECONDS = 1.0

# One question, one key: the route takes no parameters.
_STATE_KEY = "state"

_state = ReadCache("lock_state", LOCK_TTL_SECONDS)


class LockDoorFailed(Exception):
    """The door raised, or answered outside its published shape."""


def read_lock() -> Dict[str, Any]:
    """
    The screen lock's position, as @skills' screen_lock answers it.

    Returns:
        The skill's dict, verbatim: ok, locked, method, session, reason and
        detail, cannot-tell included. Served from the cache within
        LOCK_TTL_SECONDS of the last read.

    Raises:
        LockDoorFailed: The door raised or broke its shape. Never cached.
    """
    return _state.get(_STATE_KEY, _ask_the_skill)


def _ask_the_skill() -> Dict[str, Any]:
    """
    One read through @skills' published door.

    Returns:
        The skill's answer, untouched.

    Raises:
        LockDoorFailed: The call raised, or the answer broke the published shape.
    """
    # Imported here, never at module top — see the docstring.
    from aipass.skills.lib.screen_lock import handler as screen_lock

    try:
        answer = screen_lock.lock_state()
    except Exception as exc:
        # The skill never raises for a reading, so reaching here is a defect in
        # the door itself: named, logged, and a 503 — never a 500 traceback.
        message = f"@skills' lock_state() raised {type(exc).__name__}: {exc}"
        logger.error("[host_api] %s", message)
        json_handler.log_operation("host_api_lock_door_failed", {"error": type(exc).__name__})
        raise LockDoorFailed(message) from exc

    fault = _shape_fault(answer)
    if fault:
        message = f"@skills' lock_state() answered outside its published shape: {fault}"
        logger.error("[host_api] %s", message)
        json_handler.log_operation("host_api_lock_door_failed", {"error": "shape"})
        raise LockDoorFailed(message)

    return answer


def _shape_fault(answer: Any) -> str:
    """
    What breaks the published shape, or "" when nothing does.

    Args:
        answer: What the door returned.

    Returns:
        A clause naming the first fault found, for the 503's message.
    """
    if not isinstance(answer, dict):
        return f"a {type(answer).__name__}, not a dict"

    ok = answer.get("ok")
    if not isinstance(ok, bool):
        return "no boolean 'ok'"
    if "locked" not in answer:
        return "no 'locked' key"

    locked = answer["locked"]
    if ok and not isinstance(locked, bool):
        return f"ok True with 'locked' {locked!r}, not a bool"
    if not ok and locked is not None:
        return f"ok False with 'locked' {locked!r}, not None"
    return ""
