# =================== AIPass ====================
# Name: refusals.py
# Description: Host API Refusal Memory — a root that cannot be read is not re-asked every 5s
# Version: 1.0.0
# Created: 2026-08-19
# Modified: 2026-08-19
# =============================================

"""
Host API Refusal Memory

One short-lived memory of which roots the git doors could not read, so a phone
polling every five seconds stops paying for the same refusal 720 times an hour.

Split out of git_reads.py rather than living beside the parsing it protects:
that file is at its 1500-line cap, and this is a different job anyway. Nothing
here knows what a git document looks like — it remembers ANSWERS about roots,
which is why it could serve another door tomorrow without moving again.

Functions:
    _reset_refusals()     - Forget everything (test support, see its docstring)
    remembered_refusal()  - A recent refusal for this root and lane, or None
    remember_refusal()    - Keep one so the next poll costs nothing
"""

import threading
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

from aipass.api.apps.handlers.json import json_handler

# A ROOT THAT CANNOT BE READ IS NOT RE-ASKED EVERY FIVE SECONDS.
#
# @trigger measured the cost on 2026-08-19 (signature d7605b500bbc): a phone
# polls this lane every 5 SECONDS, and for an external project whose branch
# carries no .trinity/passport.json, drone refuses the CALLER before the door
# ever runs. So 720 polls an hour each spawned a subprocess that was never going
# to work and warned in THREE places — this branch's git_reads.log plus @drone's
# auth.log and git_module.log. Two branches' logs filling with the same true
# sentence about the same unchanged fact.
#
# WHAT IS KEPT IS DRONE'S ANSWER, NEVER DRONE'S RULE. Checking for a passport
# file here would be this branch reimplementing another branch's authentication,
# and it would drift the day they change it — in the worst direction, refusing
# work that would have succeeded. Asking once and remembering the answer cannot
# drift, because drone is still the only thing that decides.
#
# THE WINDOW IS THE RECOVERY STORY. A permanent deny-list would mean running
# spawn on a project and then wondering why the phone still says no until
# somebody restarts a server. Sixty seconds turns 720 spawns an hour into 60,
# and a root that gains a passport starts working on its own within a minute.
REFUSAL_TTL_SECONDS = 60.0

# Keyed on (root, lane), not root alone. The caller refusal is root-scoped and
# either key would kill the spam — but a lane failing for its OWN reason would
# then silence three working lanes, and telling the two apart means reading
# drone's refusal TEXT, which this branch does not do to another branch's words.
_refusals: Dict[Tuple[str, str], Tuple[float, str]] = {}
_refusal_guard = threading.Lock()


def _refusal_key(root: Path, lane: str) -> Tuple[str, str]:
    """
    What a remembered refusal is filed under.

    Defined once because the reader and the writer disagreeing is a silent
    failure — every lookup misses, the door is asked every time, and the lane
    behaves exactly as it did before the fix while every test still passes.
    Found that way: a mutation that changed only the read side survived.

    Args:
        root: The branch directory.
        lane: The lane's own name.

    Returns:
        The key.
    """
    return (str(root), lane)


def _reset_refusals() -> None:
    """
    Forget every remembered refusal — the door is asked fresh next time.

    PRIVATE ON PURPOSE, and the underscore is the honest label rather than a
    style choice. Nothing in the running server should ever need this: the
    memory expires on its own, which is the whole recovery story, and a caller
    that wanted to clear it early would be working around the TTL rather than
    using it.

    It exists because a 60-second window outlives an entire suite run, so one
    test provoking a refusal would silence every later test on the same lane —
    and they would still pass, because a remembered refusal raises exactly what
    a fresh one does. conftest clears it around every test.
    """
    with _refusal_guard:
        _refusals.clear()


def remembered_refusal(root: Path, lane: str) -> Optional[str]:
    """
    A refusal this lane already collected for this root, if it is still recent.

    Args:
        root: The branch directory.
        lane: The lane's own name.

    Returns:
        Drone's own sentence, or None if the door should be asked again.
    """
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
    """
    Keep a could-not-read answer so the next poll costs nothing.

    Args:
        root: The branch directory.
        lane: The lane's own name.
        reason: Drone's own sentence, kept verbatim so the second poll's 503
            reads exactly like the first. A cached refusal that loses the reason
            would be worse than the spam it replaced.
    """
    with _refusal_guard:
        first_time = _refusal_key(root, lane) not in _refusals
        _refusals[_refusal_key(root, lane)] = (time.monotonic(), reason)

    if first_time:
        # Once per root per window, matching the log line — the durable record
        # of WHICH roots this server cannot read, which is the fleet-level
        # question behind the noise (@trigger, 2026-08-19). Recording every
        # poll would be the spam again, in a file instead of a log.
        json_handler.log_operation(
            "host_api_root_unreadable",
            {"root": str(root), "lane": lane, "reason": reason},
        )
