# =================== AIPass ====================
# Name: memory_config.py
# Description: Host API Memory Config Handler — @memory's rollover limits, served
# Version: 2.0.0
# Created: 2026-08-16
# Modified: 2026-08-16
# =============================================

"""
Host API Memory Config Handler

The phone's memory-settings lane (DPLAN-0302): @memory's rollover limits, read
and written through @memory's own verbs so there is ONE implementation of what a
limit means. This file resolves nothing itself — it routes, decodes and reports.

    drone @memory config get --json                     defaults + deviating branches
    drone @memory config get @branch --json             that branch's EFFECTIVE limits
    drone @memory config set @branch <type> <n> --json  writes rollover.per_branch
    drone @memory config set-default <type> <n> --json  writes rollover.defaults
    drone @memory rollover push --json                  resets every branch to defaults

THIS LANE READS A DOCUMENT, NOT A SCREEN. Version 1.0.0 of this file recovered
every value from @memory's rendered output — there was no machine surface, and
it was the most fragile handler in this branch: a heading they reworded was a
field it lost. That version asked them for --json, and on 2026-08-16 they
shipped it on all five verbs. The scraper is gone; nothing here reads a glyph,
a marker or a column position any more.

THE VERDICT IS ok. Every payload carries a top-level boolean: true on every
success, false on every refusal, with the exit code staying 0 underneath either
way (their branch-wide convention — a refusal is an answer, not a crash). So
the exit code is still never consulted here, for the same reason as before and
with a far better signal in its place.

WHAT IS NOT ONE PARSEABLE OBJECT IS UNAVAILABLE, never a verdict. If --json
ever stops being honoured — an older @memory on a fresh clone, a flag renamed,
a banner printed ahead of the payload — this lane gets prose back and answers
503. That is the honest report: after a write, "I cannot tell whether it
happened" is the truth, and a 200 would be a lie about Patrick's config. It is
also why the flag is appended in ONE place, _route, rather than at five call
sites where one could quietly be forgotten.

THEIR FACTS, NOT MY MEMORY OF THEM. pushed used to be a constant False here,
correct only for as long as @memory's semantics never changed — a fact about
their branch, pinned in mine. They now emit it themselves, and so does the
branch count on a push, so both are reported rather than remembered.

A REFUSAL HAS ONE SHAPE HERE, wherever it was decided — an argument this server
rejects before routing and a refusal @memory speaks after it both raise
MemoryConfigRefused and both answer 400. That was not true when this lane
shipped: the first was a 400 and the second a 200 with ok=false, so a client had
to check the status code AND a flag to learn whether the write happened. @baud
found it reading this file, devpulse confirmed it on the wire, and it is fixed.
Note this is deliberately NOT the verb lane's rule — there, ok=false is an
answer the phone renders, because a refused wake is a normal outcome of asking.
A refused write to fleet configuration is a caller error, and 400 says so.

THE ONE SENTENCE THIS LANE WRITES ITSELF is the success detail. Their refusals
carry error and suggestion and those travel verbatim, but their success
payloads carry facts and no prose — so detail is composed here, out of the
values they just returned and nothing else. It is the single place this file
speaks rather than relays, it is marked as such at the call site, and a detail
field on their side would retire it. That has been asked for.

SET-DEFAULT DOES NOT PUSH, and this file does not pretend otherwise. Writing a
default leaves per_branch alone, so every branch keeps its old number until a
push. That is @memory's documented semantics; masking it here would be a second
model of their own config.
"""

import json
from typing import Any, Dict, List, Optional

from aipass.prax import logger

# @drone's public package surface — the router every operator uses, and the same
# door the verb lane goes through. No subprocess machinery in this file: the one
# resolution of how a branch is reached belongs to drone, not to me.
import aipass.drone as drone

from aipass.api.apps.handlers.json import json_handler

# ==============================================
# CONSTANTS
# ==============================================

MEMORY_TARGET = "@memory"
CONFIG_COMMAND = "config"
ROLLOVER_COMMAND = "rollover"

# Their machine surface. It rides in any argument slot on their side — this
# lane appends it last, which is a choice rather than a requirement, and the
# kind of choice that only ever breaks against an older build.
JSON_FLAG = "--json"

# Their words, and the only three the verb accepts TODAY. Used to check what a
# caller sends BEFORE routing — never to iterate their answer. The list of entry
# types is @memory's to grow, and a fourth one must reach the phone without a
# release here, so every reader below walks their document's own keys.
ENTRY_TYPES = ("sessions", "key_learnings", "observations")

# Their bounds, checked here so an obviously bad value never becomes a routed
# command — but NOT trusted as the only gate: @memory validates too, and theirs
# is the ruling one if the two ever disagree.
LIMIT_MINIMUM = 1
LIMIT_MAXIMUM = 100

# A read walks the registry; a push rewrites every branch. Generous enough for a
# 17-branch sweep, short enough that a wedged router cannot park a phone request.
READ_TIMEOUT_SECONDS = 30
WRITE_TIMEOUT_SECONDS = 45


class MemoryConfigRefused(Exception):
    """
    The write was refused. The caller's problem, whoever noticed it.

    Raised for both halves of the same fact: arguments this server rejects
    before routing, and a refusal @memory speaks after it. One exception type
    because a client should never have to learn WHERE a refusal was decided in
    order to learn THAT it was.

    Attributes:
        raw: @memory's payload verbatim when they were the one refusing, so a
            caller is never trapped behind this lane's reading of it. Empty
            when the refusal was decided here and nothing was routed.
        suggestion: Their remedy line, kept as its own field as well as joined
            into the message. None when the refusal genuinely has none — their
            word for it, never the string 'None'.
    """

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
    """
    Read the rollover limits — fleet-wide, or one branch's effective set.

    Args:
        branch: Branch name, with or without '@'. Empty reads the fleet view.

    Returns:
        Fleet view: {scope: 'fleet', defaults: {...}, overrides: [...], raw}.
        Branch view: {scope: 'branch', branch, limits: [...], raw}.

    Raises:
        MemoryConfigRefused: @memory refused the read — an unknown branch is
            the usual reason, and their sentence says so.
        MemoryConfigUnavailable: The router could not run the command, or what
            came back was not one parseable answer.
    """
    args = ["get"]
    target_branch = _clean_branch(branch)
    if target_branch:
        args.append("@" + target_branch)

    document, raw = _document_of(_route(CONFIG_COMMAND, args, READ_TIMEOUT_SECONDS))

    # A refused read has no rows to show — the caller asked a question with no
    # answer, which is a 400 carrying their sentence. Returning an empty limit
    # list instead would render as 'this branch has no limits', a different and
    # false statement.
    _refuse_if_they_did(document, raw)

    if target_branch:
        payload: Dict[str, Any] = {
            "scope": "branch",
            # Their echo of the name, which is the one they actually resolved.
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
    """
    Override one branch's limit for one entry type.

    Args:
        branch: Branch name, with or without '@'.
        entry_type: One of ENTRY_TYPES.
        count: Whole number within the documented bounds.

    Returns:
        {ok, detail, raw, branch, type, count, pushed}. Returning at all means
        the write landed — ok is here for @baud's existing guard and is always
        True. pushed is @memory's own fact about whether branches were reset.

    Raises:
        MemoryConfigRefused: The arguments are unusable, or @memory refused.
            One exception for both, because a caller learning THAT a write was
            refused should not have to learn WHERE it was decided.
        MemoryConfigUnavailable: The router could not run the command, or what
            came back was not one parseable answer.
    """
    target_branch = _require_branch(branch)
    checked_type = _require_type(entry_type)
    checked_count = _require_count(count)

    document, raw = _route_write(
        CONFIG_COMMAND,
        ["set", "@" + target_branch, checked_type, str(checked_count)],
    )

    # Their echoes are preferred over the arguments that were sent: they report
    # what was actually written, and if their normalisation ever differs from
    # this lane's, theirs is the one on disk.
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
    """
    Change one global default, leaving every per-branch override alone.

    Args:
        entry_type: One of ENTRY_TYPES.
        count: Whole number within the documented bounds.

    Returns:
        {ok, detail, raw, type, count, pushed} — pushed says out loud whether
        branches were reset, and on set-default @memory reports False, because
        they keep their old numbers until a push. Their semantics, surfaced
        rather than smoothed, and now read from their answer rather than
        remembered here. It rides only on a write that HAPPENED: a refusal
        raises, so there is never a pushed describing a default that was never
        changed.

    Raises:
        MemoryConfigRefused: The arguments are unusable, or @memory refused.
        MemoryConfigUnavailable: The router could not run the command, or what
            came back was not one parseable answer.
    """
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
    """
    Reset EVERY branch's limits to the defaults.

    Returns:
        {ok, detail, raw, branches} — branches is how many @memory actually
        reset, which is the only evidence the sweep was fleet-wide.

    Raises:
        MemoryConfigRefused: @memory refused. Push takes no arguments, so this
            is the ONLY way it can be refused — and before the shapes were
            unified it was the one write with no path to a 400 at all.
        MemoryConfigUnavailable: The router could not run the command, or what
            came back was not one parseable answer.

    Note:
        Fleet-wide and not undoable from here: any per-branch override an
        operator set is gone afterwards. It takes no arguments, so there is
        nothing to validate — the confirmation belongs in the face, and a
        confirm dialog is pocket-safety, not authorisation.
    """
    document, raw = _route_write(ROLLOVER_COMMAND, ["push"])

    branches = document.get("branches")
    answer = _answer(document, raw, f"Pushed defaults to {branches} branches")
    answer["branches"] = branches

    json_handler.log_operation("host_api_memory_config_push", {"branches": branches})
    return answer


# ==============================================
# ROUTING
# ==============================================


def _route(command: str, args: List[str], timeout: int) -> Any:
    """
    Run one @memory command through drone's router, asking for JSON.

    THE FLAG IS APPENDED HERE AND NOWHERE ELSE. Every verb this file sends
    wants the machine surface, and that is a property of the file rather than
    of five separate call sites — one of which could quietly be written without
    it and would then get prose back, which this lane can only report as a 503.

    Args:
        command: Verb name.
        args: Verb arguments, without the flag.
        timeout: Seconds to allow.

    Returns:
        drone's CommandResult.

    Raises:
        MemoryConfigUnavailable: The router could not resolve or run it.
    """
    try:
        return drone.route_command(MEMORY_TARGET, command, [*args, JSON_FLAG], timeout=timeout)
    except drone.RoutingError as e:
        logger.error("[host_api] drone could not run %s %s: %s", MEMORY_TARGET, command, e)
        raise MemoryConfigUnavailable(f"{MEMORY_TARGET} {command} could not be run: {e}") from e


def _route_write(command: str, args: List[str]) -> Any:
    """
    Route a write, decode it, and raise their refusal if they spoke one.

    Args:
        command: Verb name.
        args: Verb arguments, without the flag.

    Returns:
        (document, raw) once the write is known to have happened.

    Raises:
        MemoryConfigRefused: @memory refused.
        MemoryConfigUnavailable: The router failed, or the answer was not one
            parseable object.
    """
    document, raw = _document_of(_route(command, args, WRITE_TIMEOUT_SECONDS))
    _refuse_if_they_did(document, raw)
    return document, raw


def _text_of(result: Any) -> str:
    """
    The output to read, whichever stream it arrived on.

    Args:
        result: drone's CommandResult.

    Returns:
        stdout, or stderr when stdout is empty.

    Note:
        @memory writes zero bytes to stderr, verified on their side before they
        shipped --json. The fallback stays anyway: it costs nothing, and the
        day a router wraps their payload onto the other stream, one document on
        the wrong pipe is still an answer. The exit code is deliberately not
        consulted — they refuse with 0 branch-wide.
    """
    stdout = (getattr(result, "stdout", "") or "").strip()
    if stdout:
        return stdout
    return (getattr(result, "stderr", "") or "").strip()


def _document_of(result: Any) -> Any:
    """
    Their one JSON object, or the honest admission that there was none.

    Args:
        result: drone's CommandResult.

    Returns:
        (document, raw) — the decoded object and the exact text it came from.

    Raises:
        MemoryConfigUnavailable: Nothing arrived, it was not JSON, it was not
            an object, or it carried no ok. All four are the same fact from the
            caller's side: @memory did not answer. A missing ok cannot be
            defaulted either way — true would make every malformed answer a
            success, false would invent a refusal they never spoke.
    """
    raw = _text_of(result)

    try:
        document = json.loads(raw)
    except ValueError:
        logger.error("[host_api] @memory answered with something that is not JSON: %r", raw[:400])
        raise MemoryConfigUnavailable(f"{MEMORY_TARGET} did not answer with a JSON document: {raw[:400]}") from None

    if not isinstance(document, dict) or not isinstance(document.get("ok"), bool):
        logger.error("[host_api] @memory answered JSON with no verdict in it: %r", raw[:400])
        raise MemoryConfigUnavailable(f"{MEMORY_TARGET} did not answer with a verdict: {raw[:400]}")

    return document, raw


def _refuse_if_they_did(document: Dict[str, Any], raw: str) -> None:
    """
    Raise @memory's refusal, in their words, if the document carries one.

    Args:
        document: Their decoded payload.
        raw: The text it was decoded from.

    Raises:
        MemoryConfigRefused: ok is false. Their error is the message and their
            suggestion rides both joined onto it and as its own field — the
            suggestion is half the sentence, and dropping it drops the fix.
    """
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
    """
    The success envelope for a write that is already known to have happened.

    ok can only ever be true here: a refusal raised before this was reached.
    That is deliberate rather than vestigial — @baud's client already guards on
    ok=false, and removing the field mid-train would break a live phone to tidy
    up a field that is now harmless. It comes out when their guard does.

    Args:
        document: Their decoded payload.
        raw: The text it was decoded from.
        detail: THE ONE SENTENCE THIS LANE WRITES ITSELF. Their success
            payloads carry facts and no prose, so the caller's line is composed
            by the verb above out of the values they just returned — never out
            of the values that were sent to them, and never invented. A detail
            field on their side retires this argument entirely.

    Returns:
        {ok: True, detail, raw, pushed} — pushed only where they stated it.
    """
    answer: Dict[str, Any] = {"ok": True, "detail": detail, "raw": raw}

    if isinstance(document.get("pushed"), bool):
        answer["pushed"] = document["pushed"]

    return answer


# ==============================================
# READING — their document, walked by their own keys
# ==============================================


def _defaults_of(defaults: Any) -> Dict[str, Any]:
    """
    The fleet defaults, one entry per type @memory reported.

    Args:
        defaults: Their defaults object.

    Returns:
        {entry_type: {count, auto_compact_cap}}. The cap key is always present
        and null where there is none — @memory omits it entirely, and a phone
        should not have to test for a missing field to learn that key_learnings
        has no compaction cap.
    """
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
    """
    Every branch deviating from the defaults, with the rows that deviate.

    Args:
        overrides: Their overrides object, keyed by branch name.

    Returns:
        [{branch, limits: [row]}], empty when every branch sits at the
        defaults. @memory projects only the deviating entry types into each
        branch, which is the same rule their human OVERRIDES block applies.
    """
    if not isinstance(overrides, dict):
        return []

    return [
        {"branch": str(name), "limits": _rows_of(limits)}
        for name, limits in overrides.items()
        if isinstance(limits, dict)
    ]


def _rows_of(limits: Any) -> List[Dict[str, Any]]:
    """
    One branch's limits as a list of rows, in @memory's own order.

    A list rather than their object because this lane publishes an ordered
    surface the phone renders top to bottom — so the order is a real decision,
    and it is theirs. Their document is ordered, and it is walked key by key
    rather than by ENTRY_TYPES: a fourth entry type is theirs to add, and
    iterating a triple pinned here would drop it from the phone silently.

    Args:
        limits: Their limits (or per-branch overrides) object.

    Returns:
        [{type, count, default, is_override, source, auto_compact_cap}].
    """
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


# ==============================================
# INPUT
# ==============================================


def _clean_branch(branch: Any) -> str:
    """
    A branch name with any leading '@' removed.

    Args:
        branch: The caller's value.

    Returns:
        The bare name, possibly empty.
    """
    if not isinstance(branch, str):
        return ""
    return branch.strip().lstrip("@").strip()


def _require_branch(branch: Any) -> str:
    """
    A branch name that is present and shaped like one.

    Args:
        branch: The caller's value.

    Returns:
        The bare name.

    Raises:
        MemoryConfigRefused: Missing, or carrying characters a name cannot
            hold. Whether the branch EXISTS is @memory's ruling, not mine —
            the registry is theirs and a second copy of it here would drift.
    """
    name = _clean_branch(branch)
    if not name:
        raise MemoryConfigRefused("A branch is required, for example 'api' or '@api'")

    if not all(character.isalnum() or character in "_-" for character in name):
        raise MemoryConfigRefused(f"'{name}' is not a branch name")

    return name


def _require_type(entry_type: Any) -> str:
    """
    One of @memory's three entry types.

    Args:
        entry_type: The caller's value.

    Returns:
        The type.

    Raises:
        MemoryConfigRefused: Not one of them. Named in full, because a client
            guessing at a fourth deserves the list rather than a shrug.
    """
    if not isinstance(entry_type, str) or entry_type.strip() not in ENTRY_TYPES:
        raise MemoryConfigRefused(f"Entry type must be one of: {', '.join(ENTRY_TYPES)}")

    return entry_type.strip()


def _require_count(count: Any) -> int:
    """
    A whole number inside @memory's documented bounds.

    Args:
        count: The caller's value.

    Returns:
        The count.

    Raises:
        MemoryConfigRefused: Not a whole number, or outside the bounds. A bool
            is refused explicitly — it is an int to Python, and 'sessions True'
            is not a limit anybody meant.
    """
    if isinstance(count, bool) or not isinstance(count, int):
        raise MemoryConfigRefused(f"Count must be a whole number between {LIMIT_MINIMUM} and {LIMIT_MAXIMUM}")

    if count < LIMIT_MINIMUM or count > LIMIT_MAXIMUM:
        raise MemoryConfigRefused(
            f"Count must be between {LIMIT_MINIMUM} and {LIMIT_MAXIMUM} (got {count}) — "
            f"{LIMIT_MINIMUM} rolls over almost everything, past {LIMIT_MAXIMUM} defeats rollover entirely"
        )

    return count
