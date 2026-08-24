# =================== AIPass ====================
# Name: dispatches.py
# Description: Watchdog seat attribution — which completions are THIS seat's, and what is still out
# Version: 2.0.0
# Created: 2026-08-22
# Modified: 2026-08-22
# =============================================

"""
Watchdog seat attribution — whose dispatch was that, and what is still out.

@ai_mail owns the dispatch register and its reconstruction. Nothing here reads
or folds that file: both questions go through their public doors, for the same
reason feed.py consumes the feed through ``feed_path()``.

Public surface:
  seat_email(repo_root=None) -> str
  is_mine(record, seat) -> bool
  outstanding(repo_root=None) -> list[dict]
  overdue(repo_root=None) -> list[dict]
  RegisterUnavailable

The commentary below is why this file is shaped the way it is, including the
design that was tried first and was wrong. See DPLAN-0317 for the design record
and FPLAN-0452 for the build.
"""

# WHY THIS FILE EXISTS (DPLAN-0317 rule 5, FPLAN-0452 P2): the wire used to wake
# this seat for EVERY citizen's completion, fleet-wide, because the notification
# feed named the branch that FINISHED and never the branch that SENT the work.
# "@flow completed" was expressible; "@flow completed the job you gave it" was
# not.
#
# @ai_mail closed that gap at the producer: a dispatch completion now carries
# ``sender`` on the feed line itself (FPLAN-0452 P1). So attribution is one
# field comparison against this seat's address — no file read on the delivery
# path, and no join to reconstruct.
#
# THE JOIN WAS TRIED FIRST AND IT WAS WRONG, which is worth keeping written
# down. The first version of this module folded @ai_mail's dispatch register to
# build an id allow-list. Two defects: it duplicated the append-only
# reconstruction rule that @ai_mail owns (a duplicated RULE has no day it
# breaks — it is simply, quietly wrong from the start), and it raced the
# producer, which closes the register entry and writes the feed line at the
# same terminal moment. Attribution must not depend on losing that race.
#
# WHAT THE REGISTER IS STILL FOR: crash coverage, and NOTHING RUNS TO PRODUCE
# IT. A dispatch past its expected_by with no completion record is a fact about
# a file — true whether or not anyone is looking, visible to whoever next looks.
# @ai_mail's own words on what it means: expected_by comes from
# dispatch_monitor's HARD_TIMEOUT, which a live monitor cannot legitimately
# overrun, so an overdue entry means THE MONITOR DIED — not "taking a while".
# That reading is theirs and it is reconstructed here through their door, never
# re-derived.
#
# NAME WARNING, and it is the reason this file is not called register.py:
# registry.py in this same package is the WATCH-HANDLE store (which watchdogs
# are armed). Two files one letter apart holding unrelated state is how someone
# edits the wrong one at 2am.

from pathlib import Path
from typing import Any

from aipass.prax.apps.modules.logger import system_logger as logger

from aipass.devpulse.apps.handlers.json import json_handler
from aipass.devpulse.apps.handlers.owner.guard import owner_address as _owner_address
from aipass import ai_mail as _ai_mail


class RegisterUnavailable(RuntimeError):
    """This seat's identity or the register could not be resolved.

    Deliberately an error and not an empty result. "Nothing is outstanding" and
    "I cannot tell what is outstanding" are different states, and a caller that
    cannot distinguish them will report coverage it does not have.

    Subclasses RuntimeError so it catches uniformly with the RuntimeError
    @ai_mail's own doors raise when they cannot re-root.
    """


def seat_email(repo_root: Path | None = None) -> str:
    """The address whose dispatches this seat owns — ``@devpulse`` here.

    Resolved through spawn's frozen owner contract, NOT from a directory name.
    A directory name is what ``resolve_caller_identity(<repo root>)`` used on
    2026-08-21 to answer "who am I" with the project's name, matching a real
    citizen and stamping it verified. Two questions, one string, $1.41.

    Portable by construction: @devpulse owns AIPass, @vera owns Vera Studio,
    and each seat filters for itself.

    Raises:
        RegisterUnavailable: when no sealed owner can be resolved, or the owner
            entry carries no email. Without an identity there is no "mine", and
            guessing one is the bug above.
    """
    # ONE lookup, two contracts. owner_address() is the single implementation of
    # "who owns this project" and returns None on any failure, because the other
    # caller is a refusal MESSAGE and a message-builder must never be able to
    # break the refusal it decorates. Arming is the opposite: it must not
    # proceed on a guess, so the soft answer is converted to a hard one here.
    # Two resolutions of one question is the mistake that cost $1.41 on
    # 2026-08-21 — this is deliberately not a second one.
    address: Any = _owner_address(start_path=repo_root)
    if not address:
        raise RegisterUnavailable(
            "no sealed owner for this project — cannot decide which dispatches are this seat's. "
            "Run: aipass doctor --fix"
        )
    return _normalise(address)


def _normalise(address: str) -> str:
    """One spelling for an address, so ``devpulse`` and ``@DevPulse`` compare equal."""
    return f"@{str(address).lstrip('@').lower()}"


def is_mine(record: dict, seat: str) -> bool:
    """True when this completion belongs to a dispatch THIS seat sent.

    A record with no ``sender`` is NOT mine. It cannot be attributed, and
    treating an unattributable completion as mine restores the fleet-wide wake
    this function exists to end — so the unknown case fails closed.
    """
    sender = record.get("sender")
    if not isinstance(sender, str) or not sender:
        return False
    return _normalise(sender) == _normalise(seat)


def outstanding(repo_root: Path | None = None) -> list[dict]:
    """Every dispatch still open, newest first, each carrying an ``overdue`` bool.

    Delegates to @ai_mail's ``outstanding_dispatches``. The append-only
    reconstruction rule has exactly one owner and this is not it.

    Raises:
        RuntimeError: from their door, when the register cannot be located or
            re-rooted. Never silently empty — see RegisterUnavailable.
    """
    return list(_ai_mail.outstanding_dispatches(repo_root))


def overdue(repo_root: Path | None = None) -> list[dict]:
    """The outstanding dispatches that are past their expected_by.

    Costs nothing at idle: staleness is a property of the file, so it becomes
    true on its own and is read by whoever next looks. Nothing polls, nothing is
    armed, no process has to survive for it to be noticed.

    An overdue entry is not a slow agent — ``expected_by`` is dispatch_monitor's
    own hard timeout, which a live monitor kills the run at. Overdue means the
    monitor died.
    """
    late = [entry for entry in outstanding(repo_root) if entry.get("overdue")]
    if late:
        logger.info("[watchdog.dispatches] %s dispatch(es) overdue — their monitors died", len(late))
        json_handler.log_operation("dispatches_overdue", {"count": len(late)})
    return late
