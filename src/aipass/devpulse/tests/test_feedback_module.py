# =================== AIPass ====================
# Name: test_feedback_module.py
# Description: Tests for feedback module command routing
# Version: 1.0.0
# Created: 2026-04-11
# Modified: 2026-09-27
# =============================================

"""Tests for apps/modules/feedback.py, driven through handle_command()."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(help_flag_safety) — that handle_command calls _wants_help before acting
# seedgo: no-test-needed(constant) — the Rich colour tags in HELP_TEXT and print_introspection()

from unittest.mock import patch

import pytest

from aipass.devpulse.apps.handlers.feedback import storage
from aipass.devpulse.apps.modules import feedback as feedback_module


@pytest.fixture(autouse=True)
def _bypass_caller_guard():
    """Force _guard_caller to pass so routing tests don't depend on owner env."""
    with patch.object(feedback_module, "_guard_caller", return_value=True):
        yield


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

    def test_bare_feedback_shows_summary(self, empty_inbox, capsys):
        """Bare 'feedback' prints the inbox summary (mutant: the summary line dropped)."""
        assert feedback_module.handle_command("feedback", []) is True
        assert "Feedback: No feedback messages." in capsys.readouterr().err

    def test_feedback_help(self, empty_inbox, capsys):
        """--help prints the usage table (mutant: the help print dropped)."""
        assert feedback_module.handle_command("feedback", ["--help"]) is True
        assert "feedback clear --all            Remove all read messages" in capsys.readouterr().out

    def test_feedback_help_alias(self, empty_inbox, capsys):
        """'help' is an alias for --help (mutant: 'help' dropped from _wants_help)."""
        assert feedback_module.handle_command("feedback", ["help"]) is True
        assert "feedback clear --all            Remove all read messages" in capsys.readouterr().out

    def test_feedback_inbox(self, populated_inbox, capsys):
        """'inbox' lists every message by id (mutant: inbox prints the summary instead)."""
        assert feedback_module.handle_command("feedback", ["inbox"]) is True
        err = capsys.readouterr().err
        assert "aaa11111" in err
        assert "bbb22222" in err

    def test_feedback_view(self, populated_inbox):
        """Should view a specific message."""
        result = feedback_module.handle_command("feedback", ["view", "aaa11111"])
        assert result is True

        # Verify message was marked as read
        data = storage.load_inbox()
        msg = next(m for m in data["messages"] if m["id"] == "aaa11111")
        assert msg["read"] is True

    def test_feedback_view_no_id(self, populated_inbox, capsys):
        """view without an id prints its usage (mutant: the usage error dropped)."""
        assert feedback_module.handle_command("feedback", ["view"]) is True
        assert "Usage: feedback view <id>" in capsys.readouterr().err

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

    def test_feedback_clear_no_args(self, populated_inbox, capsys):
        """clear without args prints its usage and removes nothing (mutant: the usage error dropped)."""
        assert feedback_module.handle_command("feedback", ["clear"]) is True
        assert "Usage: feedback clear <id> | feedback clear --all" in capsys.readouterr().err
        assert [m["id"] for m in storage.load_inbox()["messages"]] == ["aaa11111", "bbb22222"]

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

    def test_feedback_reply_no_args(self, populated_inbox, capsys):
        """reply without args prints its usage (mutant: the usage error dropped)."""
        assert feedback_module.handle_command("feedback", ["reply"]) is True
        assert 'Usage: feedback reply <id> "message"' in capsys.readouterr().err

    def test_feedback_reply_no_body(self, populated_inbox, capsys):
        """reply with an id but no body prints its usage and adds no reply (mutant: `< 2` -> `< 1`)."""
        assert feedback_module.handle_command("feedback", ["reply", "aaa11111"]) is True
        assert 'Usage: feedback reply <id> "message"' in capsys.readouterr().err
        assert storage.load_inbox()["messages"][0]["thread"] == []

    def test_unknown_subcommand(self, empty_inbox, capsys):
        """An unknown subcommand is refused by name (mutant: the error dropped)."""
        assert feedback_module.handle_command("feedback", ["nonexistent"]) is True
        assert "Unknown feedback subcommand: nonexistent" in capsys.readouterr().err


class TestOwnerGate:
    """Owner gate wraps mailbox management; send + help stay open (#681)."""

    def test_management_blocked_for_non_owner(self, populated_inbox):
        """A denied guard blocks a management verb — view does not mark read."""
        with patch.object(feedback_module, "_guard_caller", return_value=False):
            result = feedback_module.handle_command("feedback", ["view", "aaa11111"])
        assert result is True  # command still "handled" (clean refusal)

        data = storage.load_inbox()
        msg = next(m for m in data["messages"] if m["id"] == "aaa11111")
        assert msg["read"] is False  # action was gated out

    def test_send_open_for_non_owner(self, empty_inbox):
        """send bypasses the owner gate — any agent can drop feedback."""
        with patch.object(feedback_module, "_guard_caller", return_value=False):
            result = feedback_module.handle_command("feedback", ["send", "seedgo", "Bug report", "Found an issue"])
        assert result is True

        data = storage.load_inbox()
        assert data["total_messages"] == 1  # send bypassed the gate

    def test_help_open_for_non_owner(self, empty_inbox, capsys):
        """--help bypasses the owner gate (mutant: the gate moved above the help check)."""
        with patch.object(feedback_module, "_guard_caller", return_value=False):
            result = feedback_module.handle_command("feedback", ["--help"])
        assert result is True
        assert "feedback --help                 Show this help" in capsys.readouterr().out

    def test_help_goes_to_stdout_so_a_redirect_captures_it(self, empty_inbox, capsys):
        """`feedback --help > usage.txt` used to write an EMPTY FILE.

        This module aliases `console = err_console` on purpose — mailbox chatter
        must not pollute a pipeline capturing something else. Help rode that
        alias and went to stderr with it. Help is documentation, not chatter,
        and documentation belongs on the stream a redirect captures. Measured by
        @canary 2026-08-22: watchdog's help 1861B on stdout, this module's 0B.
        """
        assert feedback_module.handle_command("feedback", ["--help"]) is True
        captured = capsys.readouterr()
        assert "feedback" in captured.out.lower(), "help must reach stdout"
        assert "usage" in captured.out.lower()

    def test_ordinary_feedback_output_stays_off_stdout(self, empty_inbox, capsys):
        """The alias itself must survive the help fix — only help moved."""
        assert feedback_module.handle_command("feedback", []) is True
        captured = capsys.readouterr()
        assert captured.out.strip() == "", "only help belongs on stdout in this module"


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
