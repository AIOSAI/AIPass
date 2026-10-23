# =================== AIPass ====================
# Name: test_watchdog_dispatches.py
# Description: Tests for watchdog seat attribution (FPLAN-0452 P2 — only MY dispatches reach me)
# Version: 2.0.2
# Created: 2026-08-22
# Modified: 2026-10-22
# =============================================

"""Tests for apps/handlers/watchdog/dispatches.py: whose completion was that, and what is still out."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that handlers/watchdog/dispatches.py parses and imports
# seedgo: no-test-needed(documentation) — that seat_email, is_mine and outstanding carry docstrings

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from aipass.spawn.apps.modules import door_owner as spawn_registry
import pytest

from aipass.devpulse.apps.handlers.owner import guard
from aipass.devpulse.apps.handlers.watchdog import dispatches


SEAT = "@devpulse"


@pytest.fixture(autouse=True)
def _mail_doors(hermetic_mail_doors):
    """outstanding() re-roots @ai_mail's register; never on this machine's live registry marker."""
    return hermetic_mail_doors


def test_my_own_dispatch_is_mine():
    assert dispatches.is_mine({"sender": SEAT, "kind": "dispatch"}, SEAT) is True


def test_another_citizens_dispatch_is_not_mine():
    """@flow dispatching @seedgo is @flow's wake, not this seat's."""
    assert dispatches.is_mine({"sender": "@flow"}, SEAT) is False


def test_a_record_without_a_sender_is_not_mine():
    """Unattributable fails CLOSED: failing open restores the fleet-wide wake."""
    assert dispatches.is_mine({"kind": "dispatch", "source": "flow"}, SEAT) is False
    assert dispatches.is_mine({"sender": ""}, SEAT) is False
    assert dispatches.is_mine({"sender": None}, SEAT) is False


def test_attribution_tolerates_the_at_sign_and_case():
    """A feed written 'devpulse' and a seat called '@DevPulse' are the same seat."""
    assert dispatches.is_mine({"sender": "devpulse"}, "@DevPulse") is True
    assert dispatches.is_mine({"sender": "@DEVPULSE"}, "devpulse") is True


def test_seat_email_reads_the_owner_entrys_email_not_the_dict(monkeypatch):
    """get_owner returns an ENTRY DICT: stringified, it matches nothing and silently excludes every dispatch."""
    monkeypatch.setattr(
        spawn_registry,
        "get_owner",
        lambda start_path=None: {"email": "@vera", "owner": True, "name": "vera"},
    )
    assert dispatches.seat_email() == "@vera"


def test_seat_email_is_portable_across_projects(monkeypatch):
    """@devpulse owns AIPass, @vera owns Vera Studio — never a directory name."""
    monkeypatch.setattr(spawn_registry, "get_owner", lambda start_path=None: {"email": "wren", "owner": True})
    assert dispatches.seat_email() == "@wren"


def test_seat_email_refuses_when_no_owner_is_sealed(monkeypatch):
    """Without an identity there is no 'mine', and it is never guessed."""
    monkeypatch.setattr(spawn_registry, "get_owner", lambda start_path=None: None)
    with pytest.raises(dispatches.RegisterUnavailable) as exc:
        dispatches.seat_email()
    assert "no sealed owner" in str(exc.value)


def test_seat_email_refuses_an_owner_entry_with_no_email(monkeypatch):
    """An entry with no email cannot name a seat: the same refusal and remedy as 'no owner sealed'."""
    monkeypatch.setattr(spawn_registry, "get_owner", lambda start_path=None: {"owner": True, "name": "vera"})
    with pytest.raises(dispatches.RegisterUnavailable) as exc:
        dispatches.seat_email()
    assert "aipass doctor" in str(exc.value)


def test_the_owner_lookup_has_exactly_one_implementation():
    """seat_email delegates to the guard handler: two answers to one question drift."""
    assert dispatches._owner_address is guard.owner_address


def test_register_unavailable_catches_as_a_runtime_error():
    """The seat refusal and @ai_mail's re-root refusal must catch uniformly."""
    assert issubclass(dispatches.RegisterUnavailable, RuntimeError)


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
    """Overdue is a fact about a file, not a poll result: expected_by is the monitor's own hard timeout."""
    root = _repo_with_register(tmp_path, [_sent("late", minutes_ahead=-30), _sent("fine", minutes_ahead=30)])
    late = [e for e in dispatches.outstanding(root) if e["overdue"]]
    assert [e["dispatch_id"] for e in late] == ["late"]


def test_a_completed_dispatch_is_never_overdue(tmp_path):
    root = _repo_with_register(
        tmp_path,
        [_sent("d1", minutes_ahead=-90), {"dispatch_id": "d1", "status": "completed"}],
    )
    assert [e for e in dispatches.outstanding(root) if e["overdue"]] == []


def test_outstanding_refuses_rather_than_returning_the_live_register(tmp_path):
    """ "None outstanding" and "I cannot tell" must never render the same.

    An EXISTING unreadable register raises; a MISSING one stays []. Staged as a
    directory, which fails the same under any user (a permissions stage passes as root).
    """
    register = tmp_path / ".aipass" / "dispatch_register.jsonl"
    register.mkdir(parents=True)

    with pytest.raises(OSError):
        dispatches.outstanding(tmp_path)
