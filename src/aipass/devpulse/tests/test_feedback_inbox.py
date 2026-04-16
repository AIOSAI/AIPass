# META
# module: devpulse.feedback
# description: Tests for feedback inbox operations
# END META

"""Tests for feedback inbox — list, view, clear, summary."""

from unittest.mock import patch

import pytest

from aipass.devpulse.apps.handlers.feedback import storage, inbox


@pytest.fixture
def mock_feedback_dir(tmp_path):
    """Patch FEEDBACK_DIR to use tmp_path for isolation."""
    feedback_dir = tmp_path / ".feedback.local"
    with patch.object(storage, "FEEDBACK_DIR", feedback_dir):
        yield feedback_dir


@pytest.fixture
def populated_inbox(mock_feedback_dir):
    """Create an inbox with sample messages."""
    data = {
        "mailbox": "feedback",
        "total_messages": 3,
        "unread_count": 2,
        "messages": [
            {
                "id": "aaa11111",
                "from": "seedgo",
                "subject": "Audit suggestion",
                "body": "Consider adding a new checker.",
                "timestamp": "2026-04-11T10:00:00",
                "read": False,
                "thread": [],
            },
            {
                "id": "bbb22222",
                "from": "prax",
                "subject": "Logger update",
                "body": "New log format available.",
                "timestamp": "2026-04-11T11:00:00",
                "read": True,
                "thread": [
                    {
                        "from": "devpulse",
                        "body": "Thanks, will review.",
                        "timestamp": "2026-04-11T11:30:00",
                    }
                ],
            },
            {
                "id": "ccc33333",
                "from": "flow",
                "subject": "Plan status",
                "body": "FPLAN-042 completed.",
                "timestamp": "2026-04-11T12:00:00",
                "read": False,
                "thread": [],
            },
        ],
    }
    storage.save_inbox(data)
    return data


class TestListMessages:
    """Tests for list_messages()."""

    def test_empty_inbox(self, mock_feedback_dir, capsys):
        """Should print 'no messages' for empty inbox."""
        storage.save_inbox({
            "mailbox": "feedback",
            "total_messages": 0,
            "unread_count": 0,
            "messages": [],
        })
        inbox.list_messages()
        # list_messages prints to stderr via Rich Console
        # We just verify it doesn't raise

    def test_lists_all_messages(self, populated_inbox):
        """Should not raise when listing populated inbox."""
        # list_messages outputs to stderr via Rich Console; no assertion on output
        # Just verify it runs without error
        inbox.list_messages()


class TestViewMessage:
    """Tests for view_message()."""

    def test_view_marks_as_read(self, populated_inbox):
        """Should mark an unread message as read."""
        inbox.view_message("aaa11111")

        data = storage.load_inbox()
        msg = next(m for m in data["messages"] if m["id"] == "aaa11111")
        assert msg["read"] is True

    def test_view_decrements_unread_count(self, populated_inbox):
        """Should decrement unread_count when marking as read."""
        inbox.view_message("aaa11111")

        data = storage.load_inbox()
        assert data["unread_count"] == 1  # Was 2, now 1

    def test_view_already_read_no_change(self, populated_inbox):
        """Should not change unread_count for already-read messages."""
        inbox.view_message("bbb22222")

        data = storage.load_inbox()
        assert data["unread_count"] == 2  # Unchanged

    def test_view_nonexistent_message(self, populated_inbox):
        """Should handle nonexistent message ID gracefully."""
        # Should not raise
        inbox.view_message("zzz99999")

    def test_view_message_with_thread(self, populated_inbox):
        """Should display thread replies without error."""
        inbox.view_message("bbb22222")


class TestClearMessage:
    """Tests for clear_message()."""

    def test_clear_removes_message(self, populated_inbox):
        """Should remove the specified message."""
        inbox.clear_message("aaa11111")

        data = storage.load_inbox()
        ids = [m["id"] for m in data["messages"]]
        assert "aaa11111" not in ids
        assert data["total_messages"] == 2

    def test_clear_unread_decrements_count(self, populated_inbox):
        """Should decrement unread_count when clearing an unread message."""
        inbox.clear_message("aaa11111")

        data = storage.load_inbox()
        assert data["unread_count"] == 1

    def test_clear_read_message_no_unread_change(self, populated_inbox):
        """Should not change unread_count when clearing a read message."""
        inbox.clear_message("bbb22222")

        data = storage.load_inbox()
        assert data["unread_count"] == 2  # Was unread=2, cleared a read msg

    def test_clear_nonexistent_message(self, populated_inbox):
        """Should handle nonexistent message ID gracefully."""
        inbox.clear_message("zzz99999")

        data = storage.load_inbox()
        assert data["total_messages"] == 3  # Unchanged


class TestClearAllRead:
    """Tests for clear_all_read()."""

    def test_removes_read_messages(self, populated_inbox):
        """Should remove all messages with read=True."""
        inbox.clear_all_read()

        data = storage.load_inbox()
        assert data["total_messages"] == 2
        ids = [m["id"] for m in data["messages"]]
        assert "bbb22222" not in ids  # Was read
        assert "aaa11111" in ids  # Was unread
        assert "ccc33333" in ids  # Was unread

    def test_no_read_messages(self, mock_feedback_dir):
        """Should handle inbox with no read messages."""
        storage.save_inbox({
            "mailbox": "feedback",
            "total_messages": 1,
            "unread_count": 1,
            "messages": [
                {"id": "x", "from": "a", "subject": "b", "body": "c",
                 "timestamp": "2026-04-11T10:00:00", "read": False, "thread": []},
            ],
        })
        inbox.clear_all_read()

        data = storage.load_inbox()
        assert data["total_messages"] == 1

    def test_empty_inbox_clear_all(self, mock_feedback_dir):
        """Should handle empty inbox gracefully."""
        storage.save_inbox({
            "mailbox": "feedback",
            "total_messages": 0,
            "unread_count": 0,
            "messages": [],
        })
        inbox.clear_all_read()


class TestGetSummary:
    """Tests for get_summary()."""

    def test_empty_inbox_summary(self, mock_feedback_dir):
        """Should return 'No feedback messages.' for empty inbox."""
        storage.save_inbox({
            "mailbox": "feedback",
            "total_messages": 0,
            "unread_count": 0,
            "messages": [],
        })
        result = inbox.get_summary()
        assert result == "No feedback messages."

    def test_populated_summary(self, populated_inbox):
        """Should return correct count string."""
        result = inbox.get_summary()
        assert result == "3 messages, 2 unread"

    def test_single_message_summary(self, mock_feedback_dir):
        """Should use singular 'message' for count of 1."""
        storage.save_inbox({
            "mailbox": "feedback",
            "total_messages": 1,
            "unread_count": 0,
            "messages": [
                {"id": "x", "from": "a", "subject": "b", "body": "c",
                 "timestamp": "2026-04-11T10:00:00", "read": True, "thread": []},
            ],
        })
        result = inbox.get_summary()
        assert result == "1 message, 0 unread"
