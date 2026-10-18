# =================== AIPass ====================
# Name: test_message_correlation.py
# Description: Tests that a delivered message can be traced back to the sender's sent record
# Version: 1.0.1
# Created: 2026-08-16
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/email/delivery.py and the reply/inbox_ops/inbox_cleanup correlation it enables."""

# Delivery mints a fresh id for the recipient's copy; the sender's id rides along
# as ``sent_id`` so either side can find the other. The recipient's id stays authoritative.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(notify) — delivery.py's _emit_notification_event call, silenced here; see tests/test_notify.py

import json
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

import aipass.ai_mail.apps.handlers.email.delivery as delivery_mod
from aipass.ai_mail.apps.handlers.email.delivery import (
    deliver_email_to_branch,
    deliver_to_inbox_file,
)
from aipass.ai_mail.apps.handlers.email.inbox_cleanup import mark_as_opened
from aipass.ai_mail.apps.handlers.email.inbox_ops import find_message
from aipass.ai_mail.apps.handlers.email.reply import send_reply


@pytest.fixture(autouse=True)
def _silence_json_handler():
    with patch("aipass.ai_mail.apps.handlers.email.delivery.json_handler") as mock_jh:
        mock_jh.log_operation.return_value = True
        yield mock_jh


@pytest.fixture(autouse=True)
def _silence_notifications():
    with patch.object(delivery_mod, "_emit_notification_event"):
        yield


@pytest.fixture
def repo_root(tmp_path, monkeypatch):
    monkeypatch.setattr(delivery_mod, "_REPO_ROOT", tmp_path)
    return tmp_path


@pytest.fixture
def noop_inbox_lock(monkeypatch):
    @contextmanager
    def _noop_lock(path):
        yield

    monkeypatch.setattr(delivery_mod, "_get_inbox_lock", lambda: _noop_lock)


def _setup_branch(tmp_path, email: str = "@target", name: str = "TARGET"):
    branch_path = tmp_path / "branches" / name.lower()
    mailbox_dir = branch_path / ".ai_mail.local"
    mailbox_dir.mkdir(parents=True, exist_ok=True)
    inbox_file = mailbox_dir / "inbox.json"
    inbox_file.write_text(
        json.dumps({"mailbox": "inbox", "total_messages": 0, "unread_count": 0, "messages": []}),
        encoding="utf-8",
    )
    return [{"name": name, "path": str(branch_path), "email": email}]


def _email_data(**extra) -> dict:
    data = {
        "from": "@seedgo",
        "from_name": "SEEDGO",
        "to": "@target",
        "subject": "RE: Fix torn-write json_handler",
        "message": "final sweep leg SHIPPED",
        "timestamp": "2026-08-16 10:03:15",
    }
    data.update(extra)
    return data


def _delivered(branches) -> dict:
    inbox_file = Path(branches[0]["path"]) / ".ai_mail.local" / "inbox.json"
    return json.loads(inbox_file.read_text(encoding="utf-8"))["messages"][0]


class TestSentIdRidesAlong:
    """The sender's id must survive delivery."""

    def test_delivered_message_carries_the_senders_id(self, tmp_path, repo_root, noop_inbox_lock):
        """The exact @seedgo/@devpulse failure: sent-side id must be findable."""
        branches = _setup_branch(tmp_path)

        with patch.object(delivery_mod, "get_all_branches", return_value=branches):
            success, error = deliver_email_to_branch("@target", _email_data(id="de0cef3e"))

        assert success is True, error
        assert _delivered(branches)["sent_id"] == "de0cef3e"

    def test_grepping_the_mailbox_for_the_sent_id_finds_the_message(self, tmp_path, repo_root, noop_inbox_lock):
        """What @devpulse actually did — search the mailbox for the sender's id.

        Asserted at the file level because the operator's tool is grep over inbox.json.
        """
        branches = _setup_branch(tmp_path)

        with patch.object(delivery_mod, "get_all_branches", return_value=branches):
            deliver_email_to_branch("@target", _email_data(id="de0cef3e"))

        raw = (Path(branches[0]["path"]) / ".ai_mail.local" / "inbox.json").read_text(encoding="utf-8")
        assert "de0cef3e" in raw

    def test_recipient_id_stays_distinct_and_authoritative(self, tmp_path, repo_root, noop_inbox_lock):
        """sent_id is a back-reference, NOT a replacement.

        The inbox id keys view/reply/close and must stay unique whatever id a sender chose.
        """
        branches = _setup_branch(tmp_path)

        with patch.object(delivery_mod, "get_all_branches", return_value=branches):
            deliver_email_to_branch("@target", _email_data(id="de0cef3e"))

        msg = _delivered(branches)
        assert msg["id"] != "de0cef3e"
        assert len(msg["id"]) == 8

    def test_delivery_without_a_sender_id_omits_the_field(self, tmp_path, repo_root, noop_inbox_lock):
        """No invented correlation.

        A placeholder would look like a real sent record that no ``sent/`` folder contains.
        """
        branches = _setup_branch(tmp_path)

        with patch.object(delivery_mod, "get_all_branches", return_value=branches):
            deliver_email_to_branch("@target", _email_data())

        assert "sent_id" not in _delivered(branches)

    def test_both_lanes_agree_on_correlation(self, tmp_path, noop_inbox_lock):
        """The cross-project reply lane must correlate the same way."""
        mailbox = tmp_path / ".ai_mail.local"
        mailbox.mkdir(parents=True)
        inbox_file = mailbox / "inbox.json"
        inbox_file.write_text(
            json.dumps({"mailbox": "inbox", "total_messages": 0, "unread_count": 0, "messages": []}),
            encoding="utf-8",
        )

        success, error, _ = deliver_to_inbox_file(inbox_file, _email_data(id="de0cef3e"))

        assert success is True, error
        msg = json.loads(inbox_file.read_text(encoding="utf-8"))["messages"][0]
        assert msg["sent_id"] == "de0cef3e"


class TestReplyLaneCorrelates:
    """The reply lane is the one that actually failed.

    The reply id must be minted before delivery, or the delivered copy carries no id to copy.
    """

    def test_reply_sent_id_matches_the_senders_sent_record(self, tmp_path, repo_root, noop_inbox_lock):
        """The @seedgo -> @devpulse path, end to end."""

        branches = _setup_branch(tmp_path, email="@devpulse", name="DEVPULSE")
        sender_path = tmp_path / "branches" / "seedgo"
        (sender_path / ".ai_mail.local").mkdir(parents=True)
        (sender_path / ".ai_mail.local" / "inbox.json").write_text(
            json.dumps({"mailbox": "inbox", "total_messages": 0, "unread_count": 0, "messages": []}),
            encoding="utf-8",
        )
        original = {"id": "orig1234", "from": "@devpulse", "subject": "Fix torn-write json_handler"}

        # send_reply imports these inside the function body (circular-import
        # dodge), so they must be patched at their source modules.
        with (
            patch.object(delivery_mod, "get_all_branches", return_value=branches),
            patch(
                "aipass.ai_mail.apps.handlers.registry.read.get_all_branches",
                return_value=branches,
            ),
            patch(
                "aipass.ai_mail.apps.handlers.users.branch_detection.get_branch_info_from_registry",
                return_value={"email": "@seedgo", "name": "SEEDGO"},
            ),
        ):
            success, message, reply_id = send_reply(sender_path, original, "final sweep leg SHIPPED")

        assert success is True, message
        assert reply_id is not None

        delivered = _delivered(branches)
        assert delivered["sent_id"] == reply_id, "recipient's copy must point back at the sender's sent record"

        sent_file = sender_path / ".ai_mail.local" / "sent" / f"{reply_id}.json"
        assert sent_file.exists(), "the sent record must use that same id"
        assert json.loads(sent_file.read_text(encoding="utf-8"))["id"] == reply_id


class TestFindMessage:
    """One resolver for "which message did the operator mean".

    One shared function for all lookup sites, so two resolvers never answer differently.
    """

    def test_finds_by_inbox_id(self):

        messages = [{"id": "361cefd6", "sent_id": "de0cef3e"}]

        assert find_message(messages, "361cefd6") is messages[0]

    def test_finds_by_sent_id(self):
        """The sender's id resolves to the recipient's copy."""

        messages = [{"id": "361cefd6", "sent_id": "de0cef3e"}]

        assert find_message(messages, "de0cef3e") is messages[0]

    def test_inbox_id_wins_over_a_sent_id_collision(self):
        """Precedence must be total, not positional.

        The inbox id wins over another message's equal sent_id; the decoy is placed FIRST.
        """

        decoy = {"id": "aaaaaaaa", "sent_id": "shared01"}
        real = {"id": "shared01", "sent_id": "bbbbbbbb"}

        assert find_message([decoy, real], "shared01") is real

    def test_returns_none_when_nothing_matches(self):

        assert find_message([{"id": "361cefd6"}], "nosuchid") is None

    def test_tolerates_messages_without_ids(self):
        """A malformed entry must not break lookup for every other message."""

        messages = [{"no_id_here": True}, {"id": "361cefd6"}]

        assert find_message(messages, "361cefd6") is messages[1]

    def test_view_accepts_the_senders_id(self, tmp_path):
        """End to end: what @devpulse would have run."""

        mailbox = tmp_path / ".ai_mail.local"
        mailbox.mkdir(parents=True)
        (mailbox / "inbox.json").write_text(
            json.dumps(
                {
                    "mailbox": "inbox",
                    "total_messages": 1,
                    "unread_count": 1,
                    "messages": [{"id": "361cefd6", "sent_id": "de0cef3e", "status": "new"}],
                }
            ),
            encoding="utf-8",
        )

        success, message, email_data = mark_as_opened(tmp_path, "de0cef3e")

        assert success is True, message
        assert email_data is not None
        assert email_data["id"] == "361cefd6"
