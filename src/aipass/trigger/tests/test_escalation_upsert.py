# =================== AIPass ====================
# Name: test_escalation_upsert.py
# Description: Tests that escalation digests upsert in place instead of stacking
# Version: 1.0.0
# Created: 2026-08-10
# Modified: 2026-08-10
# =============================================

"""Tests for the escalation digest upsert lane (FPLAN-0389 phase 2).

Three things have to hold, and only the first is obvious:

1. The escalation send carries ``escalation:<signature>``.
2. The adapter FORWARDS that key to ai_mail. Its signature ends in ``**kwargs``,
   so a key threaded by the wrong name is swallowed with no error and no upsert —
   delivery still returns True and the inbox keeps stacking. That is the
   regression this file exists to catch.
3. The medic and runaway paths carry NO key. They are unrelated errors that must
   stay one message each; sharing a key would collapse them into one.
"""

import json
import sys
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest
from aipass.trigger.apps.config import trail_logger


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def cfg() -> Dict[str, Any]:
    """Operator settings with the cooldown OFF — repeats send instead of muting."""
    return {
        "enabled": True,
        "digest_recipient": "@digest-inbox",
        "warning_threshold": 2,
        "error_threshold": 2,
        "window_minutes": 60,
        "cooldown_minutes": 0,
        "sample_lines": 3,
        "max_signatures": 500,
        "escalate_suppressed": False,
        "watch_branch_log_warnings": True,
        "ignore_branches": [],
    }


@pytest.fixture
def lane(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, cfg: Dict[str, Any]):
    """The escalation module pointed at tmp state and a tmp trail."""
    from aipass.trigger.apps.handlers import escalation

    monkeypatch.setattr(escalation, "STATE_FILE", tmp_path / "escalation_state.json")
    monkeypatch.setattr(escalation, "logger", trail_logger(tmp_path / "escalation.jsonl"))
    monkeypatch.setattr(escalation, "get_config", lambda: cfg)
    monkeypatch.setattr(escalation, "_send_email", None)
    escalation._config_cache = (0.0, None)
    yield escalation
    escalation._config_cache = (0.0, None)


@pytest.fixture
def mailbox(monkeypatch: pytest.MonkeyPatch) -> List[Dict[str, Any]]:
    """A fake ai_mail that records every (to_branch, email_data, upsert_key) call.

    This stands in for the real deliver_email_to_branch at the sys.modules level,
    which is where setup_handlers resolves it — so the adapter under test is the
    real closure, not a re-implementation of it.
    """
    calls: List[Dict[str, Any]] = []

    def _deliver(to_branch, email_data, on_delivered=None, upsert_key=None):
        calls.append({"to_branch": to_branch, "email_data": email_data, "upsert_key": upsert_key})
        # ai_mail reports the outcome back on the caller's dict.
        email_data["upsert_action"] = "updated" if upsert_key else "created"
        return True, "delivered"

    mock_mail = MagicMock()
    mock_mail.deliver_email_to_branch = _deliver
    monkeypatch.setitem(sys.modules, "aipass.ai_mail.apps.modules.email_send", mock_mail)
    return calls


@pytest.fixture
def adapter(monkeypatch: pytest.MonkeyPatch, mailbox):
    """The real _send_email_adapter closure, captured off the escalation wiring."""
    from aipass.trigger.apps.handlers import escalation

    core_mod = MagicMock()
    core_mod.trigger = MagicMock()
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps.modules.core", core_mod)

    from aipass.trigger.apps.handlers.events.registry import setup_handlers

    setup_handlers()

    captured = escalation._send_email
    assert captured is not None, "setup_handlers did not wire the escalation email callback"
    return captured


WARNING_EVENT = {
    "branch": "backup",
    "module": "drive",
    "message": "disk usage above 90%",
    "log_file": "backup.log",
    "raw_line": "2026-08-10 10:00:00.000 | drive | WARNING | disk usage above 90%",
}


def _fire(lane, times: int = 1) -> Any:
    decision = None
    for _ in range(times):
        decision = lane.record_warning(**WARNING_EVENT)
    return decision


def _trail(lane) -> List[Dict[str, Any]]:
    """Every JSON line the lane wrote to its trail."""
    path = Path(lane.logger.path) if hasattr(lane.logger, "path") else None
    if path is None or not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# The adapter — the kwargs-swallow guard
# ---------------------------------------------------------------------------


class TestAdapterForwardsTheKey:
    """The adapter's **kwargs is a trapdoor. These tests stand under it."""

    def test_key_reaches_ai_mail(self, adapter, mailbox) -> None:
        """upsert_key arrives at deliver_email_to_branch, not in **kwargs limbo."""
        adapter(
            to_branch="@digest-inbox",
            subject="repeat",
            message="body",
            upsert_key="escalation:abc123",
        )

        assert mailbox[0]["upsert_key"] == "escalation:abc123"

    def test_no_key_stays_none(self, adapter, mailbox) -> None:
        """A caller that passes nothing gets the untouched one-message-per-send path."""
        adapter(to_branch="@some-branch", subject="error", message="body")

        assert mailbox[0]["upsert_key"] is None

    def test_key_is_not_smuggled_into_email_data(self, adapter, mailbox) -> None:
        """The key travels as an argument, never as a field the recipient would render."""
        adapter(to_branch="@digest-inbox", subject="repeat", message="body", upsert_key="escalation:abc123")

        assert "upsert_key" not in mailbox[0]["email_data"]

    def test_result_sink_receives_the_outcome(self, adapter, mailbox) -> None:
        """The callback contract is -> bool, so the sink is how a caller learns what happened."""
        sink: Dict[str, Any] = {}

        adapter(
            to_branch="@digest-inbox",
            subject="repeat",
            message="body",
            upsert_key="escalation:abc123",
            upsert_result=sink,
        )

        assert sink["upsert_action"] == "updated"

    def test_sink_is_optional(self, adapter, mailbox) -> None:
        """Callers that do not care pass no sink and nothing raises."""
        assert adapter(to_branch="@b", subject="s", message="m") is True

    def test_unknown_kwargs_still_tolerated(self, adapter, mailbox) -> None:
        """**kwargs stays — old callers pass reply_to and friends without breaking."""
        assert adapter(to_branch="@b", subject="s", message="m", something_new="x") is True


# ---------------------------------------------------------------------------
# The escalation lane
# ---------------------------------------------------------------------------


class TestEscalationCarriesTheKey:
    """One signature, one key, forever — regardless of what the subject says."""

    def test_digest_send_carries_the_signature_key(self, monkeypatch, lane) -> None:
        box: List[Dict[str, Any]] = []
        monkeypatch.setattr(lane, "_send_email", lambda **kw: bool(box.append(kw)) or True)

        decision = _fire(lane, times=2)

        assert box[0]["upsert_key"] == f"escalation:{decision['signature']}"

    def test_key_is_stable_across_repeats(self, monkeypatch, lane) -> None:
        """The subject carries the repeat count and changes; the key must not."""
        box: List[Dict[str, Any]] = []
        monkeypatch.setattr(lane, "_send_email", lambda **kw: bool(box.append(kw)) or True)

        _fire(lane, times=2)
        _fire(lane, times=2)

        assert len(box) == 2
        assert box[0]["upsert_key"] == box[1]["upsert_key"]

    def test_key_is_not_the_subject(self, monkeypatch, lane) -> None:
        """Guard against the tempting shortcut of keying on the rendered subject."""
        box: List[Dict[str, Any]] = []
        monkeypatch.setattr(lane, "_send_email", lambda **kw: bool(box.append(kw)) or True)

        _fire(lane, times=2)

        assert box[0]["upsert_key"] != box[0]["subject"]

    def test_distinct_signatures_get_distinct_keys(self, monkeypatch, lane) -> None:
        """Two different conditions must not collapse into one message."""
        box: List[Dict[str, Any]] = []
        monkeypatch.setattr(lane, "_send_email", lambda **kw: bool(box.append(kw)) or True)

        _fire(lane, times=2)
        for _ in range(2):
            lane.record_warning(**{**WARNING_EVENT, "message": "a completely different warning"})

        assert len({call["upsert_key"] for call in box}) == 2

    def test_upsert_action_lands_in_the_trail(self, monkeypatch, lane) -> None:
        """An in-place update must be auditable — otherwise it looks like a lost digest."""

        def _send(**kwargs: Any) -> bool:
            sink = kwargs.get("upsert_result")
            if sink is not None:
                sink["upsert_action"] = "updated"
            return True

        monkeypatch.setattr(lane, "_send_email", _send)

        _fire(lane, times=2)

        sent = [line for line in _trail(lane) if line.get("outcome") == "sent"]
        assert sent and sent[-1]["upsert_action"] == "updated"

    def test_missing_outcome_is_recorded_as_none(self, monkeypatch, lane) -> None:
        """A callback that ignores the sink logs None, never a crash or a fake 'created'."""
        monkeypatch.setattr(lane, "_send_email", lambda **kw: True)

        _fire(lane, times=2)

        sent = [line for line in _trail(lane) if line.get("outcome") == "sent"]
        assert sent and sent[-1]["upsert_action"] is None

    def test_digests_sent_counter_still_counts_updates(self, monkeypatch, lane) -> None:
        """An update is a digest. The counter stays truthful about what left the branch."""
        monkeypatch.setattr(lane, "_send_email", lambda **kw: True)

        signature = _fire(lane, times=2)["signature"]
        _fire(lane, times=2)

        state = json.loads(lane.STATE_FILE.read_text(encoding="utf-8"))
        assert state["signatures"][signature]["digests_sent"] == 2


# ---------------------------------------------------------------------------
# The paths that must NOT change
# ---------------------------------------------------------------------------


class TestOtherLanesUnkeyed:
    """Medic and runaway emails are one-per-error. A key here would merge them."""

    def test_medic_error_path_sends_no_key(self, monkeypatch, mailbox) -> None:
        from aipass.trigger.apps.handlers.events import error_detected

        core_mod = MagicMock()
        core_mod.trigger = MagicMock()
        monkeypatch.setitem(sys.modules, "aipass.trigger.apps.modules.core", core_mod)

        from aipass.trigger.apps.handlers.events.registry import setup_handlers

        setup_handlers()

        send = error_detected._send_email
        assert send is not None, "setup_handlers did not wire the medic email callback"
        send(
            to_branch="@backup",
            subject="Error in drive.py",
            message="traceback",
            auto_execute=True,
        )

        assert mailbox[-1]["upsert_key"] is None

    def test_runaway_path_sends_no_key(self, monkeypatch, mailbox) -> None:
        from aipass.trigger.apps.handlers.events import runaway_handler

        core_mod = MagicMock()
        core_mod.trigger = MagicMock()
        monkeypatch.setitem(sys.modules, "aipass.trigger.apps.modules.core", core_mod)

        from aipass.trigger.apps.handlers.events.registry import setup_handlers

        setup_handlers()

        send = runaway_handler._send_email
        assert send is not None, "setup_handlers did not wire the runaway email callback"
        send(
            to_branch="@backup",
            subject="Runaway log",
            message="growing fast",
        )

        assert mailbox[-1]["upsert_key"] is None

    def test_dispatch_banner_survives_the_new_signature(self, adapter, mailbox) -> None:
        """auto_execute still rewrites the body — the untouched path is byte-identical."""
        adapter(to_branch="@backup", subject="s", message="body", auto_execute=True)

        assert mailbox[-1]["email_data"]["message"].startswith("⚡ DISPATCH TASK")
