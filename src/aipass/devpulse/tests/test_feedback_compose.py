# META
# module: devpulse.feedback
# description: Tests for feedback compose operations
# END META

"""Tests for feedback compose — send, reply, ai_mail delivery."""

import json
from datetime import datetime
from unittest.mock import patch

import pytest

from aipass.devpulse.apps.handlers.feedback import storage, compose


@pytest.fixture
def mock_feedback_dir(tmp_path):
    """Patch FEEDBACK_DIR to use tmp_path for isolation."""
    feedback_dir = tmp_path / ".feedback.local"
    with patch.object(storage, "FEEDBACK_DIR", feedback_dir):
        yield feedback_dir


@pytest.fixture
def mock_aipass_root(tmp_path):
    """Patch _AIPASS_ROOT to use tmp_path for ai_mail delivery tests."""
    with patch.object(compose, "_AIPASS_ROOT", tmp_path):
        yield tmp_path


@pytest.fixture
def empty_inbox(mock_feedback_dir):
    """Start with an empty feedback inbox."""
    storage.save_inbox(
        {
            "mailbox": "feedback",
            "total_messages": 0,
            "unread_count": 0,
            "messages": [],
        }
    )


class TestSendFeedback:
    """Tests for send_feedback()."""

    def test_creates_message(self, empty_inbox, mock_feedback_dir):
        """Should add a message to the inbox."""
        msg_id = compose.send_feedback("seedgo", "Test subject", "Test body")

        data = storage.load_inbox()
        assert data["total_messages"] == 1
        assert data["unread_count"] == 1
        assert len(data["messages"]) == 1

        msg = data["messages"][0]
        assert msg["id"] == msg_id
        assert msg["from"] == "seedgo"
        assert msg["subject"] == "Test subject"
        assert msg["body"] == "Test body"
        assert msg["read"] is False
        assert msg["thread"] == []

    def test_returns_message_id(self, empty_inbox, mock_feedback_dir):
        """Should return a valid 8-char hex ID."""
        msg_id = compose.send_feedback("prax", "Subject", "Body")
        assert isinstance(msg_id, str)
        assert len(msg_id) == 8

    def test_increments_counts(self, empty_inbox, mock_feedback_dir):
        """Should increment total_messages and unread_count."""
        compose.send_feedback("a", "s1", "b1")
        compose.send_feedback("b", "s2", "b2")

        data = storage.load_inbox()
        assert data["total_messages"] == 2
        assert data["unread_count"] == 2

    def test_timestamp_format(self, empty_inbox, mock_feedback_dir):
        """Should set an ISO-format timestamp."""
        compose.send_feedback("flow", "Subject", "Body")

        data = storage.load_inbox()
        ts = data["messages"][0]["timestamp"]
        # Should be ISO format: YYYY-MM-DDTHH:MM:SS
        assert "T" in ts
        assert len(ts) == 19


class TestReplyTo:
    """Tests for reply_to()."""

    @pytest.fixture
    def inbox_with_message(self, mock_feedback_dir):
        """Create inbox with a single message to reply to."""
        storage.save_inbox(
            {
                "mailbox": "feedback",
                "total_messages": 1,
                "unread_count": 1,
                "messages": [
                    {
                        "id": "aaa11111",
                        "from": "seedgo",
                        "subject": "Test feedback",
                        "body": "Original message.",
                        "timestamp": "2026-04-11T10:00:00",
                        "read": True,
                        "thread": [],
                    },
                ],
            }
        )

    def test_adds_reply_to_thread(self, inbox_with_message, mock_aipass_root):
        """Should append reply to the message thread."""
        result = compose.reply_to("aaa11111", "Great point, thanks!")

        assert result is True
        data = storage.load_inbox()
        msg = data["messages"][0]
        assert len(msg["thread"]) == 1
        assert msg["thread"][0]["from"] == "devpulse"
        assert msg["thread"][0]["body"] == "Great point, thanks!"

    def test_reply_to_nonexistent(self, inbox_with_message, mock_aipass_root):
        """Should return False for nonexistent message."""
        result = compose.reply_to("zzz99999", "Reply")
        assert result is False

    def test_multiple_replies_build_thread(self, inbox_with_message, mock_aipass_root):
        """Should accumulate replies in thread order."""
        compose.reply_to("aaa11111", "Reply 1")
        compose.reply_to("aaa11111", "Reply 2")

        data = storage.load_inbox()
        thread = data["messages"][0]["thread"]
        assert len(thread) == 2
        assert thread[0]["body"] == "Reply 1"
        assert thread[1]["body"] == "Reply 2"


class TestAiMailDelivery:
    """Tests for ai_mail delivery on reply."""

    @pytest.fixture
    def inbox_with_message(self, mock_feedback_dir):
        """Create inbox with a message from seedgo."""
        storage.save_inbox(
            {
                "mailbox": "feedback",
                "total_messages": 1,
                "unread_count": 0,
                "messages": [
                    {
                        "id": "aaa11111",
                        "from": "seedgo",
                        "subject": "Test feedback",
                        "body": "Original.",
                        "timestamp": "2026-04-11T10:00:00",
                        "read": True,
                        "thread": [],
                    },
                ],
            }
        )

    def test_delivers_to_ai_mail(self, inbox_with_message, mock_aipass_root):
        """Should write reply to sender's ai_mail inbox."""
        # Create sender's ai_mail directory and inbox
        ai_mail_dir = mock_aipass_root / "seedgo" / ".ai_mail.local"
        ai_mail_dir.mkdir(parents=True)
        ai_mail_inbox = ai_mail_dir / "inbox.json"
        with open(ai_mail_inbox, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "mailbox": "inbox",
                    "total_messages": 0,
                    "unread_count": 0,
                    "messages": [],
                },
                f,
            )

        compose.reply_to("aaa11111", "Thanks for the feedback!")

        with open(ai_mail_inbox, encoding="utf-8") as f:
            mail_data = json.load(f)

        assert mail_data["total_messages"] == 1
        assert mail_data["unread_count"] == 1

        mail_msg = mail_data["messages"][0]
        # '@'-prefixed from + reply_path are what make the message REPLYABLE:
        # ai_mail's reply verb matches from against branch emails, then falls
        # back to the stored reply_path for cross-project delivery (wall-2,
        # 2026-08-07).
        assert mail_msg["from"] == "@devpulse"
        assert mail_msg["reply_path"].endswith("inbox.json")
        # reply_to must NOT be a registry branch email: ai_mail's reply verb
        # resolves reply_to before from, and a registry MATCH routes through
        # normal delivery which refuses cross-project mail (#134). The
        # non-registry address forces the registry MISS that activates the
        # stored reply_path route (wall-3, Patrick ruling 2026-08-07: the
        # feedback loop is cross-project by design, no boundary protection).
        assert mail_msg["reply_to"] == "@devpulse:feedback"
        assert mail_msg["reply_to"] != mail_msg["from"]
        assert mail_msg["subject"] == "Re: Test feedback"
        # v2 schema: the ai_mail viewer reads 'message' and 'status' — writing
        # 'body'/'read' rendered delivered replies as empty (VERA 2026-08-05).
        assert mail_msg["message"] == "Thanks for the feedback!"
        assert mail_msg["status"] == "new"
        assert "body" not in mail_msg
        assert mail_msg["metadata"]["source"] == "feedback"
        assert mail_msg["metadata"]["thread_id"] == "aaa11111"

    def test_delivered_timestamp_matches_ai_mail_store_format(self, inbox_with_message, mock_aipass_root):
        """Delivered timestamp must use ai_mail's canonical store format.

        ai_mail stamps its store with local '%Y-%m-%d %H:%M:%S' (create.py,
        reply.py). This module wrote UTC ISO-T into that same store, leaving
        two timestamp shapes in one file (BAUD report e8c235f8, 2026-08-24).
        One store, one format — and local wall-clock, not UTC wearing it.
        """
        ai_mail_dir = mock_aipass_root / "seedgo" / ".ai_mail.local"
        ai_mail_dir.mkdir(parents=True)
        ai_mail_inbox = ai_mail_dir / "inbox.json"
        with open(ai_mail_inbox, "w", encoding="utf-8") as f:
            json.dump(
                {"mailbox": "inbox", "total_messages": 0, "unread_count": 0, "messages": []},
                f,
            )

        compose.reply_to("aaa11111", "format check")

        with open(ai_mail_inbox, encoding="utf-8") as f:
            ts = json.load(f)["messages"][0]["timestamp"]

        # Parses in ai_mail's canonical shape (raises on ISO-T)...
        parsed = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        # ...and reads as local wall-clock — a UTC stamp in local clothes
        # would sit a whole UTC-offset away from now.
        assert abs((parsed - datetime.now()).total_seconds()) < 60

    def test_skips_delivery_when_no_ai_mail(self, inbox_with_message, mock_aipass_root):
        """Should log warning and skip when sender has no ai_mail inbox."""
        # Don't create sender's ai_mail directory
        result = compose.reply_to("aaa11111", "Reply without delivery")

        # Reply should still succeed locally
        assert result is True
        data = storage.load_inbox()
        assert len(data["messages"][0]["thread"]) == 1

    def test_skips_delivery_on_corrupt_ai_mail(self, inbox_with_message, mock_aipass_root):
        """Should skip delivery when sender's ai_mail inbox is corrupt."""
        ai_mail_dir = mock_aipass_root / "seedgo" / ".ai_mail.local"
        ai_mail_dir.mkdir(parents=True)
        ai_mail_inbox = ai_mail_dir / "inbox.json"
        with open(ai_mail_inbox, "w", encoding="utf-8") as f:
            f.write("{corrupt json!!!")

        result = compose.reply_to("aaa11111", "Reply with corrupt ai_mail")

        # Reply should still succeed locally
        assert result is True
        data = storage.load_inbox()
        assert len(data["messages"][0]["thread"]) == 1


class TestHonestDeliveryReporting:
    """Delivery outcomes must be surfaced, never silently skipped (2026-08-04 live failure)."""

    @pytest.fixture
    def inbox_with_message(self, mock_feedback_dir):
        """Inbox seeded with one message from seedgo."""
        storage.save_inbox(
            {
                "mailbox": "feedback",
                "total_messages": 1,
                "unread_count": 1,
                "messages": [
                    {
                        "id": "aaa11111",
                        "from": "seedgo",
                        "subject": "Test feedback",
                        "body": "Original message.",
                        "timestamp": "2026-04-11T10:00:00",
                        "read": True,
                        "thread": [],
                        "reply_path": "",
                    },
                ],
            }
        )

    def test_deliver_returns_success_tuple(self, tmp_path):
        """_deliver_to_ai_mail returns (True, 'delivered') on success."""
        ai_mail_dir = tmp_path / "seedgo" / ".ai_mail.local"
        ai_mail_dir.mkdir(parents=True)
        inbox_path = ai_mail_dir / "inbox.json"
        with open(inbox_path, "w", encoding="utf-8") as f:
            json.dump({"messages": []}, f)

        delivered, reason = compose._deliver_to_ai_mail("seedgo", "Subj", "Body", "aaa11111", str(inbox_path))
        assert delivered is True
        assert reason == "delivered"

    def test_deliver_returns_failure_reason_when_inbox_missing(self, tmp_path):
        """_deliver_to_ai_mail returns (False, reason) naming the missing path."""
        missing = tmp_path / "nowhere" / "inbox.json"
        delivered, reason = compose._deliver_to_ai_mail("ghost", "Subj", "Body", "aaa11111", str(missing))
        assert delivered is False
        assert str(missing) in reason

    def test_send_warns_when_sender_unknown(self, empty_inbox):
        """send_feedback tells an anonymous sender that replies cannot reach them."""
        with patch.object(compose, "warning") as mock_warning:
            compose.send_feedback("unknown", "Subj", "Body", "")
        printed = " ".join(str(c) for c in mock_warning.call_args_list)
        assert "CANNOT reach you" in printed

    def test_send_no_warning_when_sender_resolved(self, empty_inbox, tmp_path):
        """send_feedback stays quiet when the sender has a return address."""
        inbox_path = tmp_path / ".ai_mail.local" / "inbox.json"
        inbox_path.parent.mkdir(parents=True)
        inbox_path.write_text("{}", encoding="utf-8")
        with patch.object(compose, "warning") as mock_warning:
            compose.send_feedback("seedgo", "Subj", "Body", str(inbox_path))
        mock_warning.assert_not_called()

    def test_reply_reports_undelivered(self, inbox_with_message, mock_aipass_root):
        """reply_to raises a real error() when the sender inbox is unreachable."""
        with patch.object(compose, "error") as mock_error:
            result = compose.reply_to("aaa11111", "Reply into the void")
        assert result is True
        printed = " ".join(str(c) for c in mock_error.call_args_list)
        assert "NOT delivered" in printed
