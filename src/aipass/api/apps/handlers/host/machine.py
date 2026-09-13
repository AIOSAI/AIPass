# =================== AIPass ====================
# Name: machine.py
# Description: Host API Machine Handler — the phone's vitals, proxied from @skills
# Version: 1.0.0
# Created: 2026-09-13
# Modified: 2026-09-13
# =============================================

"""
Host API Machine Handler

`GET /v1/machine` (FPLAN-0561 row 2, ruled in DPLAN-0341): the machine's vitals
for BAUD's monitor wheel, so "how is the computer doing" has an answer from
across the room with the screen locked and the fans loud.

D0, THE SAME LINE THE VERB LANE HOLDS
------------------------------------------------------------------------
This server owns the pipe and never the meaning. Which sensor is the CPU, which
rows are nonsense, what an absence is called and what sentence says so all live
in @skills' system_status, behind the door it publishes for in-process callers:
`machine_vitals()`. This module asks it and relays the answer VERBATIM — the
dict, every section, every sentence. Rewriting another branch's diagnosis is how
one gets lost, and an allowlist copied here would be a second answer to the same
question, trusted by nobody the day the two disagree.

The import sits inside the call, not at the top of the module: a server that
never serves this route imports nothing new, and the skill consults its own
off-switch on every read rather than once at server start.

ONE READ PER SECOND, HOWEVER MANY PHONES ASK
------------------------------------------------------------------------
A warm read costs about 19 ms, 12 of them psutil's temperature sweep. A
ReadCache at 1.0 s with single flight means any number of callers cost at most
one read per second, and a screen that opens all at once shares one flight.
1.0 s and not the git lane's 1.5: vitals are a live gauge, and a fan spinning up
is the reading this exists for.

What the cache stores follows the skill's own line between an answer and a
refusal:
  * `ok: True` is an ANSWER, including one whose temp and fan sections are
    absent. A Mac running macOS has no sensors for psutil to read, and that is
    a fact like any other — stored and served for the window.
  * `ok: False` is a REFUSAL and is never cached. It is raised out of the
    producer, the one path ReadCache never stores, so a skill switched back on
    answers on the very next request.

The first read after a server start answers cpu and network as `warming` — a
rate needs two samples. That is relayed, not hidden; the next read carries
numbers and their window.

THE STATUS LINE
------------------------------------------------------------------------
Absence is a 200. A section with `available: False` IS the answer, never a zero
and never an error, and the face prints the skill's sentence for its code.

503 means the owner could not answer, and there are two ways that happens:
  * The skill REFUSED the whole read. `psutil_missing` (detail is the install
    recipe) and `switched_off` both answer 503 with the skill's code as `reason`
    and its detail as the message, verbatim; a client branches on the code,
    never on prose. switched_off is 503 by the rule SNAPSHOT_READY and
    KILL_SEAM_READY already hold: a closed switch answers an honest 503 naming
    itself, never a 200 dressed as a reading. A refusal code this module has
    never seen is a 503 too, code intact — the owner said no, and reading that
    as yes would be the worse bug.
  * The DOOR failed: it raised, or answered outside its published shape. The
    skill promises never to raise for a reading, so this is a defect in the
    door itself, and it is a 503 naming it rather than a 500 traceback.

NOT HERE: the process LIST. The dict's `processes` section is a count and rides
through as-is. A top-N sweep costs 30 ms and exposes process names, so it gets
its own route, its own cache and its own privacy rule — names and counts, never
a command line — in the row that builds it.

Classes:
    MachineRefused    - The skill refused the whole read, with its reason code
    MachineDoorFailed - The door raised, or answered outside its published shape

Functions:
    read_machine() - The machine's vitals, at most one read per second
"""

from typing import Any, Dict

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler
from aipass.api.apps.handlers.host.read_cache import ReadCache

# The window every caller shares. See the docstring for why not 1.5.
MACHINE_TTL_SECONDS = 1.0

# One question, one key: the route takes no parameters.
_VITALS_KEY = "vitals"

# What a refusal carries when the skill gave no detail at all. Only ever used in
# place of NOTHING — a detail the skill did give travels untouched.
NO_DETAIL = "@skills refused the machine read and gave no detail"

_vitals = ReadCache("machine_vitals", MACHINE_TTL_SECONDS)


class MachineRefused(Exception):
    """
    The skill refused the whole read.

    Attributes:
        reason: The skill's reason code, as it came.
        detail: The skill's detail, as it came (NO_DETAIL only when it gave none).
    """

    def __init__(self, reason: Any, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


class MachineDoorFailed(Exception):
    """The door raised, or answered outside its published shape."""


def read_machine() -> Dict[str, Any]:
    """
    The machine's vitals, as @skills' system_status answers them.

    Returns:
        The skill's dict, verbatim: ok, schema, sampled_at and its sections.
        Served from the cache within MACHINE_TTL_SECONDS of the last read.

    Raises:
        MachineRefused: The skill refused. Never cached.
        MachineDoorFailed: The door raised or broke its shape. Never cached.
    """
    return _vitals.get(_VITALS_KEY, _ask_the_skill)


def _ask_the_skill() -> Dict[str, Any]:
    """
    One read through @skills' published door.

    Returns:
        The skill's success dict, untouched.

    Raises:
        MachineRefused: The answer carries ok False.
        MachineDoorFailed: The call raised, or the answer carries no boolean ok.
    """
    # Imported here, never at module top — see the docstring.
    from aipass.skills.lib.system_status import handler as system_status

    try:
        vitals = system_status.machine_vitals()
    except Exception as exc:
        # The skill never raises for a reading, so reaching here is a defect in
        # the door itself: named, logged, and a 503 — never a 500 traceback.
        message = f"@skills' machine_vitals() raised {type(exc).__name__}: {exc}"
        logger.error("[host_api] %s", message)
        json_handler.log_operation("host_api_machine_door_failed", {"error": type(exc).__name__})
        raise MachineDoorFailed(message) from exc

    ok = vitals.get("ok") if isinstance(vitals, dict) else None
    if not isinstance(ok, bool):
        message = (
            f"@skills' machine_vitals() answered outside its published shape: "
            f"no boolean 'ok' in a {type(vitals).__name__}"
        )
        logger.error("[host_api] %s", message)
        json_handler.log_operation("host_api_machine_door_failed", {"error": "shape"})
        raise MachineDoorFailed(message)

    if not ok:
        reason = vitals.get("reason")
        detail = vitals.get("detail")
        logger.warning("[host_api] @skills refused the machine read: %s", reason)
        json_handler.log_operation("host_api_machine_refused", {"reason": reason})
        raise MachineRefused(reason, detail if isinstance(detail, str) and detail else NO_DETAIL)

    return vitals
