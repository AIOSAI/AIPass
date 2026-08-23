# =================== AIPass ====================
# Name: test_watchdog_dispatches.py
# Description: Tests for watchdog seat attribution (FPLAN-0452 P2 — only MY dispatches reach me)
# Version: 2.0.0
# Created: 2026-08-22
# Modified: 2026-08-22
# =============================================

"""Tests for dispatches.py — whose completion was that, and what is still out.

The defect this module exists to kill: the wire woke @devpulse for EVERY
citizen's completion, fleet-wide, because the notification feed named the branch
that FINISHED and never the branch that SENT the work.

Three things are pinned here, and all three are refusals or fail-closed rules —
the happy path is a single field comparison and cannot really go wrong on its
own:

``test_a_record_without_a_sender_is_not_mine`` — unattributable must fail
CLOSED. Failing open restores the fleet-wide wake exactly.

``test_seat_email_reads_the_owner_entrys_email_not_the_dict`` — get_owner
returns a registry ENTRY DICT. Stringifying it yields a plausible-looking
address that matches nothing, which is a filter that silently excludes
everything: a wire that looks armed and delivers nothing.

``test_outstanding_refuses_rather_than_returning_the_live_register`` — the
re-root refusal is @ai_mail's, and this asserts we inherit it rather than
swallowing it into an empty list.

Nothing here folds the register: that reconstruction has one owner (@ai_mail's
``outstanding_dispatches``) and a second implementation of an append-only rule
is a duplicated LOGIC path — it fails silently and plausibly rather than loudly.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from aipass.devpulse.apps.handlers.watchdog import dispatches


SEAT = "@devpulse"


# --------------------------------------------------------------------------
# Attribution — rule 5, one field, fails closed
# --------------------------------------------------------------------------


def test_my_own_dispatch_is_mine():
    assert dispatches.is_mine({"sender": SEAT, "kind": "dispatch"}, SEAT) is True


def test_another_citizens_dispatch_is_not_mine():
    """@flow dispatching @seedgo is @flow's wake, not this seat's."""
    assert dispatches.is_mine({"sender": "@flow"}, SEAT) is False


def test_a_record_without_a_sender_is_not_mine():
    """Unattributable fails CLOSED.

    Failing open here is not a smaller version of the bug — it IS the bug: every
    completion in the fleet arrives without a sender under an older producer,
    and treating those as mine restores the fleet-wide wake exactly.
    """
    assert dispatches.is_mine({"kind": "dispatch", "source": "flow"}, SEAT) is False
    assert dispatches.is_mine({"sender": ""}, SEAT) is False
    assert dispatches.is_mine({"sender": None}, SEAT) is False


def test_attribution_tolerates_the_at_sign_and_case():
    """A feed written 'devpulse' and a seat called '@DevPulse' are the same seat."""
    assert dispatches.is_mine({"sender": "devpulse"}, "@DevPulse") is True
    assert dispatches.is_mine({"sender": "@DEVPULSE"}, "devpulse") is True


# --------------------------------------------------------------------------
# Identity — the $1.41 lesson
# --------------------------------------------------------------------------


def test_seat_email_reads_the_owner_entrys_email_not_the_dict(monkeypatch):
    """get_owner returns a registry ENTRY DICT, not a name.

    Stringifying it would produce a plausible-looking address that matches
    nothing — a filter that silently excludes every dispatch.
    """
    import aipass.spawn.apps.handlers.registry as spawn_registry

    monkeypatch.setattr(
        spawn_registry,
        "get_owner",
        lambda start_path=None: {"email": "@vera", "owner": True, "name": "vera"},
    )
    assert dispatches.seat_email() == "@vera"


def test_seat_email_is_portable_across_projects(monkeypatch):
    """@devpulse owns AIPass, @vera owns Vera Studio — never a directory name."""
    import aipass.spawn.apps.handlers.registry as spawn_registry

    monkeypatch.setattr(spawn_registry, "get_owner", lambda start_path=None: {"email": "wren", "owner": True})
    assert dispatches.seat_email() == "@wren"


def test_seat_email_refuses_when_no_owner_is_sealed(monkeypatch):
    """Without an identity there is no 'mine', and guessing one is the 2026-08-21 bug."""
    import aipass.spawn.apps.handlers.registry as spawn_registry

    monkeypatch.setattr(spawn_registry, "get_owner", lambda start_path=None: None)
    with pytest.raises(dispatches.RegisterUnavailable) as exc:
        dispatches.seat_email()
    assert "no sealed owner" in str(exc.value)


def test_seat_email_refuses_an_owner_entry_with_no_email(monkeypatch):
    """An entry with no email cannot name a seat, so arming must refuse.

    It collapses into the same refusal as 'no owner sealed' on purpose: both
    mean "I cannot name the owner" and both have the same remedy. The
    distinction survives in ``owner_address``'s log, which is where a
    diagnostic belongs — the message a caller reads should say what to DO.
    """
    import aipass.spawn.apps.handlers.registry as spawn_registry

    monkeypatch.setattr(spawn_registry, "get_owner", lambda start_path=None: {"owner": True, "name": "vera"})
    with pytest.raises(dispatches.RegisterUnavailable) as exc:
        dispatches.seat_email()
    assert "aipass doctor" in str(exc.value)


def test_the_owner_lookup_has_exactly_one_implementation():
    """seat_email must not re-derive the owner — two answers to one question is
    the 2026-08-21 bug in miniature. It delegates to the guard handler."""
    from aipass.devpulse.apps.handlers.owner import guard

    assert dispatches._owner_address is guard.owner_address


def test_register_unavailable_catches_as_a_runtime_error():
    """The seat refusal and @ai_mail's re-root refusal must catch uniformly."""
    assert issubclass(dispatches.RegisterUnavailable, RuntimeError)


# --------------------------------------------------------------------------
# Crash coverage — read through @ai_mail's door, never re-folded here
# --------------------------------------------------------------------------


def _repo_with_register(tmp_path: Path, entries: list[dict]) -> Path:
    """A repo root carrying a register, written where @ai_mail's door will look."""
    root = tmp_path / "repo"
    root.mkdir(exist_ok=True)
    (root / "AIPASS_REGISTRY.json").write_text(json.dumps({"branches": []}), encoding="utf-8")
    path = root / ".aipass" / "dispatch_register.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")
    return root


def _sent(dispatch_id: str, target: str = "@flow", minutes_ahead: int = 10) -> dict:
    now = datetime.now(timezone.utc)
    return {
        "dispatch_id": dispatch_id,
        "ts": now.isoformat(),
        "sender": SEAT,
        "target": target,
        "subject": "do the thing",
        "expected_by": (now + timedelta(minutes=minutes_ahead)).isoformat(),
        "status": "outstanding",
    }


def test_outstanding_reports_open_dispatches(tmp_path):
    root = _repo_with_register(tmp_path, [_sent("d1"), _sent("d2", target="@baud")])
    ids = {e["dispatch_id"] for e in dispatches.outstanding(root)}
    assert ids == {"d1", "d2"}


def test_a_closed_dispatch_is_not_outstanding(tmp_path):
    """The close is a SECOND record — the register is append-only."""
    root = _repo_with_register(
        tmp_path,
        [_sent("d1"), {"dispatch_id": "d1", "status": "completed"}],
    )
    assert dispatches.outstanding(root) == []


def test_overdue_is_true_on_its_own_with_nothing_running(tmp_path):
    """The whole of r4's crash coverage: a fact about a file, not a poll result.

    An overdue entry is not a slow agent — expected_by is dispatch_monitor's own
    hard timeout, which a live monitor kills the run at. Overdue means the
    monitor died.
    """
    root = _repo_with_register(tmp_path, [_sent("late", minutes_ahead=-30), _sent("fine", minutes_ahead=30)])
    late = dispatches.overdue(root)
    assert [e["dispatch_id"] for e in late] == ["late"]


def test_a_completed_dispatch_is_never_overdue(tmp_path):
    root = _repo_with_register(
        tmp_path,
        [_sent("d1", minutes_ahead=-90), {"dispatch_id": "d1", "status": "completed"}],
    )
    assert dispatches.overdue(root) == []


def test_outstanding_refuses_rather_than_returning_the_live_register(tmp_path, monkeypatch):
    """@ai_mail's re-root refusal must reach us, not be swallowed into [].

    Handing a caller who explicitly asked for a repo_root the PRODUCTION
    register is the defect feed.py was fixed for the same evening. The refusal
    is theirs; this asserts we inherit it instead of reporting "none
    outstanding" — which would read as coverage.
    """
    import aipass.ai_mail.apps.handlers.dispatch.register as ai_register

    orphan = tmp_path / "no-repo-above-me" / "dispatch_register.jsonl"
    orphan.parent.mkdir(parents=True)
    monkeypatch.setattr(ai_register, "find_repo_root", lambda: orphan.parent)

    with pytest.raises(RuntimeError):
        dispatches.outstanding(tmp_path / "elsewhere")
