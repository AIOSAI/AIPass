# =================== AIPass ====================
# Name: verbs.py
# Description: Host API Verb Handler — wake, kill and lock, each a proxy
# Version: 1.0.0
# Created: 2026-08-14
# Modified: 2026-08-14
# =============================================

"""
Host API Verb Handler

The verb lane (FPLAN-0411 Phase 3). Everything before this could only return the
wrong bytes; this module spawns agents, ends sessions and locks a machine.

D0, AND IT IS LOAD-BEARING HERE
------------------------------------------------------------------------
This server owns the pipe and never the meaning. Every verb below is a proxy to
the branch that owns the mechanism:

    wake  -> @ai_mail, through drone's router (`dispatch wake`)
    kill  -> @baud, through a seam that does not exist yet (gated, see below)
    lock  -> @skills, through the screen_lock skill's published function

This module deliberately imports no subprocess machinery. It cannot run a
program, so it cannot quietly grow its own implementation of somebody else's
verb on a night when a seam is missing — which is the exact temptation, because
each of these mechanisms is one short line away.

WHY WAKE GOES THROUGH THE CLI AND NOT THE FUNCTION
------------------------------------------------------------------------
`wake_branch()` takes an `admin` keyword its own docstring calls "an
ALREADY-DECIDED verdict" from a caller that ran the five-leg admin-grant check.
A phone cannot run that check, so the requirement was that a network request can
never set it.

Hardcoding `admin=False` satisfies that until somebody edits the line. Routing
through `drone @ai_mail dispatch wake` satisfies it structurally: that command
parses `--fresh`, `--sender` and `--model` and nothing else, so there is no
string a caller could send that reaches the keyword at all. The privilege is not
declined here — it is unreachable from here.

Two further things this lane refuses to forward:
  * `--sender`, because it reaches a privilege-bearing parameter behind a
    verified-caller check, and an unverified network claim does not get to try.
  * `--model`, because Patrick ruled the phone contract carries zero vendor
    words — the branch's own config decides what it runs.

The message IS forwarded opaquely, which is safe for a reason worth writing
down: `wake_branch()` builds its prompt as `f"Hi. {custom_message} "`, so a
caller-supplied string can never occupy position 0 and trip the fuzzy-autocomplete
trap from 2026-07-31. That defence lives in their code, verified, not assumed.

KILL WAS GATED, AND THE GATE WAS THE RIGHT CALL
------------------------------------------------------------------------
For one day this endpoint answered 503 naming a seam that did not exist. @baud's
binary opted into headless mode for `--snapshot` and nothing else; `room_kill`
was a `#[tauri::command]`, reachable only from inside the running desktop app.
Reaching for `tmux kill-session` here was one short line away and would have
been a SECOND door — and the day the two disagreed, neither would be trusted.
Patrick ruled on 2026-08-10 that `room_kill` is the one door.

@baud shipped `--end-room` the same evening. They also proved the single-mechanism
claim instead of asking to be trusted on it: the flag and the desktop button both
reach the same kill, with the resolved project passed as an ARGUMENT to the shared
half, so the headless path physically cannot reach a different one.

The exec lives in fleet.py, which already owns their binary — one resolution, one
cwd rule, one parser. This module still imports no subprocess machinery, so the
property below is unspent.

KILL_SEAM_READY stays as an OPERATIONAL kill switch, the same role SNAPSHOT_READY
plays for the read: closed means an honest 503, never a fabricated outcome. The
constant outlives the hazard that introduced it.

`ended` IS NOT A SUCCESS FLAG. True means a live session was ended; false with no
error means there was nothing to end, which is exit 0 because a room already gone
is the goal state. Both are `ok: true` and they are different facts, so both
travel — @baud's phone shows different sentences and flattening them here would
make that impossible.

THE RESPONSE SHAPE, AND THE LINE THAT MAKES IT HONEST
------------------------------------------------------------------------
@baud decodes `{ok, detail}`: `detail` is rendered VERBATIM on the operator's
chip, because a sentence beats a status word, and `ok: false` with a detail is a
first-class answer rather than an error.

The line this lane holds:

    ok=false means THE MECHANISM RAN AND SAID NO.
    If the mechanism was never reached, that is a status code, not an ok.

So a wake refused by @ai_mail's blocklist is `200 {ok: false}` carrying their own
sentence — the door answered, and the operator should read what it said. A wake
that could not reach drone at all is 503. A screen that did not lock is
`ok: false` with @skills' text; a kill whose seam does not exist is 503, because
nothing ran.

That line also retired an imprecision I had shipped an hour earlier: @ai_mail's
CLI reports one non-zero exit for both "refused by policy" and "the spawn died",
and I had mapped both to 503. Under `{ok, detail}` I no longer need to tell them
apart — both are outcomes of a door that answered, and the sentence differs.

`project` TRAVELS, ALWAYS, AND IS NEVER INFERRED
------------------------------------------------------------------------
@baud's rule, paid for with a killed session (their learning 22): a room name
carries its project scope, and resolving it against anything else names a
DIFFERENT room. So `project` is required on both verbs that take a target — not
optional, not defaulted from this server's seat.

That is deliberately stricter than the read lane, where an omitted project means
"the seated one". Reading the wrong project returns the wrong bytes; ending a
session in the wrong project ends somebody's work.

Functions:
    wake_branch() - Wake a citizen through @ai_mail's dispatch door
    kill_room()   - End a branch's session through @baud's --end-room
    lock_screen() - Lock the machine through @skills' screen_lock
"""

from typing import Any, Dict

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler
from aipass.api.apps.handlers.host import reads as host_reads

# fleet.py owns @baud's binary — one resolution, one cwd rule, one parser for
# their envelope. Kill routes through it so THIS module can keep importing no
# subprocess machinery at all (see the docstring, and the test that reads it).
from aipass.api.apps.handlers.host import fleet as host_fleet

# @drone's public package surface — the router every operator uses. @ai_mail
# publishes no package-level door, so this is the legal one.
import aipass.drone as drone

# @skills publishes this handler as the in-process door and names the host API
# verb lane as a consumer in SKILL.md. lib/ is their public shape, not internals.
from aipass.skills.lib.screen_lock import handler as screen_lock

# Spawning an agent is slower than a read but not open-ended: the dispatch
# returns once the session is started, not when the agent finishes.
WAKE_TIMEOUT_SECONDS = 120

# A prompt is not a payload. Over the cap is REFUSED, never trimmed — a trimmed
# instruction is worse than a rejected one, because it still runs.
MAX_MESSAGE_CHARS = 2000

# OPEN since 2026-08-14, on @baud's `--end-room`. Kept as an operational kill
# switch, exactly like fleet.SNAPSHOT_READY: closed means a 503 that says the
# switch is closed, never a session quietly not ended and reported as fine.
KILL_SEAM_READY = True

# Why the switch exists, phrased as the thing that was asked for. Kept so the
# refusal can quote it and so the shape of a future seam ask is on record.
KILL_SEAM_ASK = (
    "a headless room kill on the baud binary — a flag that ends one NAMED room "
    "in a NAMED project and exits with a status, the way --snapshot reads one"
)


class VerbRefused(Exception):
    """The caller asked for something invalid. Their fault, and they may know."""


class VerbUnavailable(Exception):
    """The verb could not be performed for a reason that is not the caller's."""


# ==============================================
# WAKE
# ==============================================


def wake_branch(branch: str, project: str, message: str = "", fresh: bool = False) -> Dict[str, Any]:
    """
    Wake a citizen through @ai_mail's dispatch door.

    Args:
        branch: Branch name or email, with or without the leading '@'.
        project: The target's project. Required — never inferred from the seat.
        message: Optional prompt for the woken agent. Forwarded opaquely.
        fresh: Start a fresh session rather than resuming.

    Returns:
        Dict with ok, detail, branch, project and fresh. ok is False when the
        door answered and refused; the door's own sentence is in detail.

    Raises:
        VerbRefused: No branch or project named, an unknown branch, a project
            this server does not serve, or an oversized message.
        VerbUnavailable: The door itself could not be reached.
    """
    require_project(project)

    # THE CAP IS CHECKED BEFORE ANYTHING IS RESOLVED. It used to sit under the
    # address lookup, which made an oversized message answer VerbUnavailable
    # whenever the registry was out of reach — a payload the caller controls
    # coming back as an infrastructure fault, and the refusal it deserves only
    # if the machine happened to be healthy. Malformed input is refused on its
    # own terms, before any door is knocked on.
    if len(message) > MAX_MESSAGE_CHARS:
        raise VerbRefused(f"Message is {len(message)} characters, over the {MAX_MESSAGE_CHARS} character cap")

    target = citizen_address(branch, project)

    # Positional order matters: @ai_mail reads the branch first and the message
    # second. An empty string is omitted rather than sent, because a blank
    # positional would land in the message slot and become a blank prompt.
    args = ["wake", target]
    if message:
        args.append(message)
    if fresh:
        args.append("--fresh")

    json_handler.log_operation(
        "host_api_verb_wake",
        {"branch": target, "project": project, "fresh": fresh, "message": bool(message)},
    )

    result = _route("@ai_mail", "dispatch", args, WAKE_TIMEOUT_SECONDS)

    # The door answered either way. A non-zero exit means it said no — @ai_mail
    # reports one code for "refused by policy" and "the spawn died", and under
    # {ok, detail} that no longer needs disentangling: both are answers, and
    # their sentence says which. What it must never be is a cheerful ok=true —
    # @ai_mail fixed exactly that bug in their own lane, a dead wake exiting 0.
    ok = result.exit_code == 0
    detail = _sentence(result.stdout if ok else (result.stderr or result.stdout))

    if ok:
        logger.info("[host_api] wake dispatched for %s (fresh=%s)", target, fresh)
    else:
        logger.warning("[host_api] wake refused for %s: %s", target, detail)

    return {
        "ok": ok,
        "detail": detail,
        "branch": target,
        "project": project,
        "fresh": fresh,
    }


# ==============================================
# KILL
# ==============================================


def kill_room(branch: str, project: str) -> Dict[str, Any]:
    """
    End a branch's session. Gated — @baud owns the only door that does this.

    The target is validated BEFORE the gate is consulted, on purpose. If the
    gate answered first, the no-default-target rules would sit untested until
    the exec went live, which is the same shape as a green test passing for the
    wrong reason.

    Args:
        branch: Branch whose session to end. Required — there is no default.
        project: The ROOM's project, never the caller's seat. Also required:
            resolving a room name against the wrong project names a different
            room, which is how a session nobody asked about gets killed.

    Returns:
        Dict with ok, detail, branch, project, room and ended. `ended` is a
        FACT, not a success flag: false with ok true means there was nothing to
        end, which is the goal state and not a failure.

    Raises:
        VerbRefused: No branch or project named, or an unknown branch.
        VerbUnavailable: The switch is closed, or @baud's door could not be run.
    """
    require_project(project)
    target = citizen_address(branch, project)

    if not KILL_SEAM_READY:
        # Checked before the exec, not after — the point of a kill switch is
        # that the mechanism does not run.
        logger.warning("[host_api] kill refused for %s — the seam switch is closed", target)
        json_handler.log_operation("host_api_verb_kill_gated", {"branch": target, "project": project})
        raise VerbUnavailable(
            "Ending a session is switched off on this host (verbs.KILL_SEAM_READY is False). "
            f"The door it routes to: {KILL_SEAM_ASK}. No session is ended by another route — "
            "@baud's is the one door (Patrick, 2026-08-10)."
        )

    # The branch NAME, not the '@address' form — @baud's door takes names and
    # refuses anything carrying a separator, in their own words.
    name = target.lstrip("@")

    try:
        envelope = host_fleet.end_room(name, project.strip())
    except host_fleet.FleetUnavailable as e:
        # Their binary missing, wedged, or an invocation we got wrong. None of
        # those are the caller's fault and none of them ran a kill.
        raise VerbUnavailable(str(e)) from e

    # `error` and `detail` are mutually exclusive by construction, so this reads
    # one field and can never be misled about whether the kill happened.
    refusal = _sentence(envelope.get("error"))
    ok = not refusal
    ended = bool(envelope.get("ended"))

    if ok:
        logger.info("[host_api] room kill for %s: ended=%s", name, ended)
    else:
        logger.warning("[host_api] room kill refused for %s: %s", name, refusal)

    return {
        "ok": ok,
        "detail": _sentence(envelope.get("detail")) if ok else refusal,
        "branch": target,
        "project": project,
        # Straight from their envelope. Null when nothing was ended, which the
        # phone needs in order to say "already gone" rather than "ended it".
        "room": envelope.get("room"),
        "ended": ended,
    }


# ==============================================
# LOCK
# ==============================================


def lock_screen() -> Dict[str, Any]:
    """
    Lock the machine's screen. Never gated.

    @skills' doctrine, adopted verbatim: a destructive action never fires from a
    locked screen, and lock itself must work from anywhere — that is its whole
    point. So this asks nothing first: not screen state, not whether a desktop
    session can be resolved.

    The skill decides whether it locked, and owns the sentence explaining why
    not. A screen that never locked is never acked as locked — which is what
    `ok` carries. It is not raised, because the mechanism DID run and answered;
    the operator needs to read that answer, not a status word.

    Returns:
        Dict with ok, detail, method and session.
    """
    result = screen_lock.lock_screen()

    locked = bool(result.get("locked"))
    method = result.get("method")

    json_handler.log_operation("host_api_verb_lock", {"locked": locked, "method": method})

    if locked:
        logger.info("[host_api] screen locked via %s", method)
        detail = f"Screen locked via {method}" if method else "Screen locked"
    else:
        # The skill's own sentence, verbatim. Rewriting another branch's
        # diagnosis is how one gets lost — and an empty error still has to say
        # something rather than read as fine.
        detail = _sentence(result.get("error")) or "The skill reported no detail"
        logger.error("[host_api] screen lock failed: %s", detail)

    return {
        "ok": locked,
        "detail": detail,
        "method": method,
        "session": result.get("session"),
    }


# ==============================================
# THE ROOM-TARGETING RULES — published, because more than one lane needs them
# ==============================================
#
# These two are public rather than private because the attach socket enforces
# the SAME rules as the verbs, and a second copy of them in another module is
# how two lanes start disagreeing about which room a name means. One
# definition, imported by everything that targets a room.


def require_project(project: str) -> None:
    """
    Enforce that a room-targeting lane named its project.

    @baud's rule, paid for with a killed session: a room name carries its
    project scope, and resolving it against anything else names a DIFFERENT
    room.

    WHICH project is no longer this function's business — Patrick's
    one-terminal ruling (2026-08-16): "the flow is ONE terminal; it hosts the
    agent I choose, no matter where I spawn it... Baud is an aipass tenant in
    projects/, vera is outside, external - that should NOT matter. When you
    block you create friction." So the seat comparison is gone and any project
    @baud's census knows is reachable.

    THAT THE PROJECT WAS NAMED AT ALL IS STILL ENFORCED, and widening the
    reachable set makes that stricter rather than looser: when only one project
    could be meant, an inferred seat was merely sloppy. Now that any project can
    be meant, an inferred one would silently pick the wrong room.

    Args:
        project: Project name from the request.

    Raises:
        VerbRefused: No project named.
    """
    if not project or not project.strip():
        raise VerbRefused("A project is required on this verb — it is never inferred from the server's seat")


# ==============================================
# INTERNALS
# ==============================================


def _sentence(text: Any) -> str:
    """
    Normalise a door's output into the one sentence an operator will read.

    @baud renders `detail` verbatim on the chip, so this trims and nothing else.
    Rewriting another branch's words here is how a diagnosis gets lost.

    Args:
        text: Raw output from a proxied door, possibly None.

    Returns:
        The trimmed text, or an empty string.
    """
    return str(text or "").strip()


def citizen_address(branch: str, project: str = "") -> str:
    """
    Validate a branch name and return its citizen address.

    Existence is checked through the READ lane's resolver, which is the one
    implementation of where a branch lives: the seated citizen registry for the
    seat, @baud's census for any other project. That door grew its foreign half
    earlier the same evening, so the operate lane inherited cross-project
    resolution rather than growing a second copy of it.

    Args:
        branch: Caller-supplied branch name or email.
        project: The branch's project. Empty means the seat.

    Returns:
        The address form, e.g. '@memory'.

    Raises:
        VerbRefused: Empty, not a registered citizen, or a project that has no
            branch by that name.
        VerbUnavailable: The registry or the census could not be read — an
            unknown project arrives here in @baud's own words.
    """
    if not branch or not branch.strip():
        # No verb in this lane picks its own target. Purchased with an incident:
        # a bare /kill that defaulted to a live session.
        raise VerbRefused("A branch name is required — this lane has no default target")

    try:
        host_reads.resolve_branch_root(branch, project)
    except host_reads.ReadRefused as e:
        raise VerbRefused(str(e)) from e
    except host_reads.ReadUnavailable as e:
        raise VerbUnavailable(str(e)) from e

    return "@" + branch.strip().lstrip("@")


def _route(target: str, command: str, args: list, timeout: int) -> Any:
    """
    Run a command through drone's router.

    Args:
        target: Branch address, e.g. '@ai_mail'.
        command: Command name.
        args: Command arguments.
        timeout: Seconds to allow.

    Returns:
        drone's CommandResult.

    Raises:
        VerbUnavailable: The router could not resolve or run the command.
    """
    try:
        return drone.route_command(target, command, args, timeout=timeout)
    except drone.RoutingError as e:
        # RoutingError is drone's family root — CommandExecutionError and the
        # resolution failures are all subclasses, so one clause covers the door
        # being unreachable and the command dying behind it. Both are OURS to
        # report, never the caller's fault, which is why they share a type here.
        logger.error("[host_api] drone could not run %s %s: %s", target, command, e)
        raise VerbUnavailable(f"{target} {command} could not be run: {e}") from e
