# META
# module: devpulse.feedback
# description: Tests for feedback module command routing
# END META

"""Tests for feedback module — command routing via handle_command()."""

from unittest.mock import patch

import pytest

from aipass.devpulse.apps.handlers.feedback import storage
from aipass.devpulse.apps.modules import feedback as feedback_module


@pytest.fixture
def mock_feedback_dir(tmp_path):
    """Patch FEEDBACK_DIR to use tmp_path for isolation."""
    feedback_dir = tmp_path / ".feedback.local"
    with patch.object(storage, "FEEDBACK_DIR", feedback_dir):
        yield feedback_dir


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


@pytest.fixture
def populated_inbox(mock_feedback_dir):
    """Create an inbox with sample messages."""
    storage.save_inbox(
        {
            "mailbox": "feedback",
            "total_messages": 2,
            "unread_count": 1,
            "messages": [
                {
                    "id": "aaa11111",
                    "from": "seedgo",
                    "subject": "Test",
                    "body": "Body text.",
                    "timestamp": "2026-04-11T10:00:00",
                    "read": False,
                    "thread": [],
                },
                {
                    "id": "bbb22222",
                    "from": "prax",
                    "subject": "Already read",
                    "body": "Old message.",
                    "timestamp": "2026-04-11T09:00:00",
                    "read": True,
                    "thread": [],
                },
            ],
        }
    )


class TestCommandRouting:
    """Tests for handle_command() routing."""

    def test_ignores_non_feedback_commands(self):
        """Should return False for non-feedback commands."""
        assert feedback_module.handle_command("status", []) is False
        assert feedback_module.handle_command("help", []) is False
        assert feedback_module.handle_command("mail", []) is False

    def test_bare_feedback_shows_summary(self, empty_inbox):
        """Should show summary for bare 'feedback' command."""
        result = feedback_module.handle_command("feedback", [])
        assert result is True

    def test_feedback_help(self, empty_inbox):
        """Should show help text."""
        result = feedback_module.handle_command("feedback", ["--help"])
        assert result is True

    def test_feedback_help_alias(self, empty_inbox):
        """Should accept 'help' as alias for --help."""
        result = feedback_module.handle_command("feedback", ["help"])
        assert result is True

    def test_feedback_inbox(self, populated_inbox):
        """Should list messages."""
        result = feedback_module.handle_command("feedback", ["inbox"])
        assert result is True

    def test_feedback_view(self, populated_inbox):
        """Should view a specific message."""
        result = feedback_module.handle_command("feedback", ["view", "aaa11111"])
        assert result is True

        # Verify message was marked as read
        data = storage.load_inbox()
        msg = next(m for m in data["messages"] if m["id"] == "aaa11111")
        assert msg["read"] is True

    def test_feedback_view_no_id(self, populated_inbox):
        """Should handle view without ID gracefully."""
        result = feedback_module.handle_command("feedback", ["view"])
        assert result is True

    def test_feedback_clear(self, populated_inbox):
        """Should clear a specific message."""
        result = feedback_module.handle_command("feedback", ["clear", "bbb22222"])
        assert result is True

        data = storage.load_inbox()
        ids = [m["id"] for m in data["messages"]]
        assert "bbb22222" not in ids

    def test_feedback_clear_all(self, populated_inbox):
        """Should clear all read messages."""
        result = feedback_module.handle_command("feedback", ["clear", "--all"])
        assert result is True

        data = storage.load_inbox()
        assert all(not m["read"] for m in data["messages"])

    def test_feedback_clear_no_args(self, populated_inbox):
        """Should handle clear without args gracefully."""
        result = feedback_module.handle_command("feedback", ["clear"])
        assert result is True

    def test_feedback_send(self, empty_inbox):
        """Should accept feedback from an agent."""
        result = feedback_module.handle_command("feedback", ["send", "seedgo", "Bug report", "Found an issue"])
        assert result is True

        data = storage.load_inbox()
        assert data["total_messages"] == 1
        assert data["messages"][0]["from"] == "seedgo"
        assert data["messages"][0]["subject"] == "Bug report"

    def test_feedback_send_without_from(self, empty_inbox):
        """Should handle send with just subject and body."""
        # When args start with a quoted-looking string, from defaults to 'unknown'
        result = feedback_module.handle_command("feedback", ["send", "Subject here", "Body text"])
        assert result is True

        data = storage.load_inbox()
        assert data["total_messages"] == 1

    def test_feedback_send_too_few_args(self, empty_inbox):
        """Should handle send with insufficient args."""
        result = feedback_module.handle_command("feedback", ["send"])
        assert result is True  # Handled (shows usage)

        data = storage.load_inbox()
        assert data["total_messages"] == 0

    @patch.object(feedback_module, "reply_to")
    def test_feedback_reply(self, mock_reply, populated_inbox):
        """Should route reply command correctly."""
        mock_reply.return_value = True
        result = feedback_module.handle_command("feedback", ["reply", "aaa11111", "Good point!"])
        assert result is True
        mock_reply.assert_called_once_with("aaa11111", "Good point!")

    def test_feedback_reply_no_args(self, populated_inbox):
        """Should handle reply with insufficient args."""
        result = feedback_module.handle_command("feedback", ["reply"])
        assert result is True  # Handled (shows usage)

    def test_feedback_reply_no_body(self, populated_inbox):
        """Should handle reply with ID but no body."""
        result = feedback_module.handle_command("feedback", ["reply", "aaa11111"])
        assert result is True  # Handled (shows usage)

    def test_unknown_subcommand(self, empty_inbox):
        """Should handle unknown subcommands gracefully."""
        result = feedback_module.handle_command("feedback", ["nonexistent"])
        assert result is True  # Handled (shows error + hint)


class TestHandleCommandHasCorrectSignature:
    """Verify handle_command meets auto-discovery requirements."""

    def test_handle_command_exists(self):
        """Module must have handle_command function."""
        assert hasattr(feedback_module, "handle_command")
        assert callable(feedback_module.handle_command)

    def test_handle_command_takes_two_args(self):
        """handle_command must accept (command, args) signature."""
        import inspect

        sig = inspect.signature(feedback_module.handle_command)
        assert len(sig.parameters) == 2
