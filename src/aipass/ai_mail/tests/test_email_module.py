# =================== AIPass ====================
# Name: test_email_module.py
# Description: Tests for email.py's mailbox handlers - inbox, view, close, reply, sent
# Version: 1.1.0
# Created: 2026-04-25
# Modified: 2026-10-08
# =============================================

"""Tests for apps/modules/email.py's mailbox handlers: inbox, view, close, reply, sent."""

# Covers: handle_inbox, handle_view, handle_close, handle_reply,
# handle_sent (email.py).
#
# All handler dependencies are mocked -- these tests verify orchestration
# logic, not business logic.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that print_help, caller_refusal and resolve_broadcast_targets parse and import
# seedgo: no-test-needed(shared) — handle_send() and handle_command(): tests/test_email_module_send.py
# seedgo: no-test-needed(shared) — handle_contacts() and handle_register(): tests/test_email_module_contacts.py

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock

# Bind the REAL module objects once, at collection time, before any test can
# replace them in sys.modules. Other test modules in the suite install
# MagicMock stand-ins under these sys.modules keys (e.g.
# trigger/tests/test_memory_pool_handler.py) and never restore them, so any
# string-path patch or in-test `from ... import x` would otherwise resolve to
# a mock on an xdist worker that ran the polluter first.
from aipass.ai_mail.apps.modules import email as email_mod
from aipass.ai_mail.apps.modules.email import (
    handle_close,
    handle_inbox,
    handle_reply,
    handle_sent,
    handle_view,
)
from aipass.ai_mail.tests.support_email_module import _StdoutLines

pytestmark = pytest.mark.usefixtures("email_modules_pinned", "email_json_silenced")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _write_inbox(tmp_path: Path, messages: list | None = None) -> Path:
    """Create a minimal .ai_mail.local/inbox.json under tmp_path."""
    mailbox = tmp_path / ".ai_mail.local"
    mailbox.mkdir(parents=True, exist_ok=True)
    inbox_file = mailbox / "inbox.json"
    data = {"messages": messages or []}
    inbox_file.write_text(json.dumps(data), encoding="utf-8")
    return inbox_file


# ===========================================================================
# handle_inbox
# ===========================================================================


class TestHandleInbox:
    """Tests for email.handle_inbox orchestrator."""

    def test_inbox_empty_messages(self, tmp_path, monkeypatch, capsys: pytest.CaptureFixture[str]):
        """Empty inbox prints 'is empty' message."""
        _write_inbox(tmp_path, messages=[])

        printed = _StdoutLines(capsys)
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.resolve_inbox_target",
            lambda first_arg, repo_root, get_branch_fn, get_user_fn: (
                True,
                {
                    "inbox_file": tmp_path / ".ai_mail.local" / "inbox.json",
                    "display_name": "TEST",
                    "target_branch": None,
                    "error": None,
                },
            ),
        )
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.load_inbox",
            lambda f: {"messages": []},
        )

        result = handle_inbox([])
        assert result is True
        assert any("empty" in p.lower() for p in printed)

    def test_inbox_with_messages(self, tmp_path, monkeypatch, capsys: pytest.CaptureFixture[str]):
        """Inbox with messages formats and displays them."""
        messages = [
            {"id": "m1", "status": "new", "subject": "Hello"},
            {"id": "m2", "status": "opened", "subject": "World"},
        ]
        _write_inbox(tmp_path, messages=messages)

        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.resolve_inbox_target",
            lambda first_arg, repo_root, get_branch_fn, get_user_fn: (
                True,
                {
                    "inbox_file": tmp_path / ".ai_mail.local" / "inbox.json",
                    "display_name": "TEST",
                    "target_branch": None,
                    "error": None,
                },
            ),
        )
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.load_inbox",
            lambda f: {"messages": messages},
        )
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.format_email_list_item",
            lambda i, msg, show_unread=True: f"[{i}] {msg['subject']}",
        )
        printed = _StdoutLines(capsys)

        result = handle_inbox([])
        assert result is True
        assert any("Inbox" in p for p in printed)
        assert any("[1]" in p for p in printed)

    def test_inbox_resolve_failure(self, monkeypatch):
        """A failed inbox resolve reports the error and stays handled.

        "inbox" was recognised — returning False made the router print
        "Unknown command: inbox" underneath the real reason.
        """
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.resolve_inbox_target",
            lambda first_arg, repo_root, get_branch_fn, get_user_fn: (
                False,
                {"error": "Unknown branch: @fake"},
            ),
        )
        errors: list[str] = []
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.error",
            lambda msg: errors.append(msg),
        )

        result = handle_inbox(["@fake"])
        assert result is True
        assert any("Unknown branch: @fake" in e for e in errors)


# ===========================================================================
# handle_view
# ===========================================================================


class TestHandleView:
    """Tests for email.handle_view orchestrator."""

    def test_view_no_args_shows_usage(self, monkeypatch):
        """Calling view with no args prints usage error."""
        errors: list[str] = []
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.error",
            lambda msg: errors.append(msg),
        )

        result = handle_view([])
        assert result is True
        assert any("Usage" in e for e in errors)

    def test_view_marks_opened_and_prints(self, tmp_path, monkeypatch, capsys: pytest.CaptureFixture[str]):
        """View with valid ID marks as opened and prints header + message."""
        email_data = {
            "id": "abc123",
            "from": "@sender",
            "subject": "Test Subject",
            "message": "Test body content",
            "status": "opened",
        }
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email._resolve_branch_path",
            lambda: tmp_path,
        )
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.mark_as_opened",
            lambda bp, mid: (True, "Marked as opened", email_data),
        )
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.format_email_header",
            lambda ed: "FROM: @sender | SUBJECT: Test Subject",
        )
        printed = _StdoutLines(capsys)

        result = handle_view(["abc123"])
        assert result is True
        assert any("FROM: @sender" in p for p in printed)
        assert any("Test body content" in p for p in printed)

    def test_view_mark_opened_failure(self, tmp_path, monkeypatch):
        """When mark_as_opened fails, error is printed."""
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email._resolve_branch_path",
            lambda: tmp_path,
        )
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.mark_as_opened",
            lambda bp, mid: (False, "Message not found", None),
        )
        errors: list[str] = []
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.error",
            lambda msg: errors.append(msg),
        )

        result = handle_view(["missing_id"])
        assert result is True
        assert any("not found" in e.lower() for e in errors)

    def test_view_latest_shortcut(self, tmp_path, monkeypatch):
        """'latest' arg resolves to most recent message ID.

        The fixture is ordered newest-first because that is what
        delivery.py writes (it inserts at index 0). It previously listed
        the newest entry LAST, which matched the old messages[-1] read
        rather than the store — fixture and code shared one wrong
        assumption, so the test stayed green while 'latest' returned the
        oldest mail in the inbox.
        """
        inbox_data = {
            "messages": [
                {"id": "newest", "subject": "Latest"},
                {"id": "old1", "subject": "Old"},
            ]
        }
        email_data = {"id": "newest", "subject": "Latest", "message": "Latest body", "from": "@x"}

        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email._resolve_branch_path",
            lambda: tmp_path,
        )
        _write_inbox(tmp_path, messages=inbox_data["messages"])
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.load_inbox",
            lambda f: inbox_data,
        )

        opened_ids: list[str] = []

        def _mock_mark_opened(bp, mid):
            """Track which message IDs were passed to mark_as_opened."""
            opened_ids.append(mid)
            return (True, "Opened", email_data)

        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.mark_as_opened",
            _mock_mark_opened,
        )
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.format_email_header",
            lambda ed: "HEADER",
        )

        result = handle_view(["latest"])
        assert result is True
        assert opened_ids == ["newest"]


# ===========================================================================
# handle_close
# ===========================================================================


class TestHandleClose:
    """Tests for email.handle_close orchestrator."""

    def test_close_no_args_shows_usage(self, monkeypatch):
        """Close with no args prints usage error."""
        errors: list[str] = []
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.error",
            lambda msg: errors.append(msg),
        )

        result = handle_close([])
        assert result is True
        assert any("Usage" in e for e in errors)

    def test_close_single_id(self, tmp_path, monkeypatch, capsys: pytest.CaptureFixture[str]):
        """Close a single message ID via batch_close."""
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email._resolve_branch_path",
            lambda: tmp_path,
        )
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.batch_close",
            lambda bp, ids, fn: ([("msg1", True, "Closed msg1")], 1, 0),
        )
        printed = _StdoutLines(capsys)
        error_mock = MagicMock()
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email.error", error_mock)

        result = handle_close(["msg1"])
        assert result is True
        assert any("Closed" in p for p in printed)
        # error() raises cli's process-wide failure flag; a success path never calls it (ai_mail, leg 6)
        error_mock.assert_not_called()

    def test_close_all(self, tmp_path, monkeypatch, capsys: pytest.CaptureFixture[str]):
        """Close 'all' delegates to mark_all_read_and_archive."""
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email._resolve_branch_path",
            lambda: tmp_path,
        )
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.mark_all_read_and_archive",
            lambda bp: (True, "Archived 5 messages", 5),
        )
        printed = _StdoutLines(capsys)

        result = handle_close(["all"])
        assert result is True
        assert any("Archived 5" in p for p in printed)

    def test_close_all_failure(self, tmp_path, monkeypatch):
        """Close 'all' failure shows error."""
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email._resolve_branch_path",
            lambda: tmp_path,
        )
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.mark_all_read_and_archive",
            lambda bp: (False, "Nothing to close", 0),
        )
        errors: list[str] = []
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.error",
            lambda msg: errors.append(msg),
        )

        result = handle_close(["all"])
        assert result is True
        assert any("Nothing" in e for e in errors)

    def test_close_multiple_ids_triggers_post_ops(self, tmp_path, monkeypatch):
        """Batch close of 2+ IDs triggers batch_close_post_ops."""
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email._resolve_branch_path",
            lambda: tmp_path,
        )
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.batch_close",
            lambda bp, ids, fn: (
                [("m1", True, "Closed m1"), ("m2", True, "Closed m2")],
                2,
                0,
            ),
        )
        post_ops_called = []
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.batch_close_post_ops",
            lambda bp, central_fn, purge_fn: post_ops_called.append(True),
        )
        error_mock = MagicMock()
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email.error", error_mock)

        result = handle_close(["m1", "m2"])
        assert result is True
        assert len(post_ops_called) == 1
        error_mock.assert_not_called()


# ===========================================================================
# handle_reply
# ===========================================================================


class TestHandleReply:
    """Tests for email.handle_reply orchestrator."""

    def test_reply_too_few_args(self, monkeypatch):
        """Reply with < 2 args prints usage error."""
        errors: list[str] = []
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.error",
            lambda msg: errors.append(msg),
        )

        result = handle_reply(["only_id"])
        assert result is True
        assert any("Usage" in e for e in errors)

    def test_reply_message_not_found(self, tmp_path, monkeypatch):
        """Reply to nonexistent message shows error."""
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email._resolve_branch_path",
            lambda: tmp_path,
        )
        # A stub that sets the world (no such message); asserted so it is also a check of the lookup (ai_mail, leg 6)
        lookup = MagicMock(return_value=None)
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email.get_email_by_id", lookup)
        errors: list[str] = []
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.error",
            lambda msg: errors.append(msg),
        )
        _write_inbox(tmp_path)

        result = handle_reply(["missing_id", "my reply"])
        assert result is True
        assert any("not found" in e.lower() for e in errors)
        lookup.assert_called_once()
        assert lookup.call_args.args[1] == "missing_id"

    def test_reply_success(self, tmp_path, monkeypatch, capsys: pytest.CaptureFixture[str]):
        """Successful reply prints success message."""
        original = {"id": "msg1", "from": "@sender", "subject": "Re: test"}
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email._resolve_branch_path",
            lambda: tmp_path,
        )
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.get_email_by_id",
            lambda inbox_file, msg_id: original,
        )
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.send_reply",
            lambda bp, orig, msg: (True, "Reply sent to @sender", "reply_001"),
        )
        printed = _StdoutLines(capsys)
        _write_inbox(tmp_path)

        result = handle_reply(["msg1", "Thanks!"])
        assert result is True
        assert any("Reply sent" in p for p in printed)

    def test_reply_send_failure(self, tmp_path, monkeypatch):
        """Failed reply shows error message."""
        original = {"id": "msg1", "from": "@sender", "subject": "test"}
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email._resolve_branch_path",
            lambda: tmp_path,
        )
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.get_email_by_id",
            lambda inbox_file, msg_id: original,
        )
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.send_reply",
            lambda bp, orig, msg: (False, "Delivery failed", None),
        )
        errors: list[str] = []
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.error",
            lambda msg: errors.append(msg),
        )
        _write_inbox(tmp_path)

        result = handle_reply(["msg1", "reply text"])
        assert result is True
        assert any("Delivery failed" in e for e in errors)

    def test_reply_unrecognized_flag_warns_not_silent(self, tmp_path, monkeypatch):
        """An unconsumed --flag in the message args warns instead of vanishing
        silently into the literal body (@cli, ef49d937: --body-file was sent
        as text with no signal it wasn't a real flag)."""
        original = {"id": "msg1", "from": "@sender", "subject": "test"}
        sent_message = {}
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email._resolve_branch_path",
            lambda: tmp_path,
        )
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.get_email_by_id",
            lambda inbox_file, msg_id: original,
        )

        def _fake_send_reply(bp, orig, msg):
            sent_message["body"] = msg
            return (True, "Reply sent to @sender", "reply_001")

        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.send_reply",
            _fake_send_reply,
        )
        warnings: list[str] = []
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.warning",
            lambda msg, *a, **kw: warnings.append(msg),
        )
        _write_inbox(tmp_path)

        body_file_arg = str(tmp_path / "reply.txt")
        result = handle_reply(["msg1", "--body-file", body_file_arg])
        assert result is True
        assert any("--body-file" in w for w in warnings)
        # The literal-text behavior is unchanged — only the silence is fixed.
        assert sent_message["body"] == f"--body-file {body_file_arg}"

    def test_reply_ordinary_message_no_warning(self, tmp_path, monkeypatch):
        """A normal reply with no '--' tokens triggers no warning."""
        original = {"id": "msg1", "from": "@sender", "subject": "test"}
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email._resolve_branch_path",
            lambda: tmp_path,
        )
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.get_email_by_id",
            lambda inbox_file, msg_id: original,
        )
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.send_reply",
            lambda bp, orig, msg: (True, "Reply sent to @sender", "reply_001"),
        )
        warnings: list[str] = []
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.warning",
            lambda msg, *a, **kw: warnings.append(msg),
        )
        _write_inbox(tmp_path)

        result = handle_reply(["msg1", "Thanks, all good."])
        assert result is True
        assert warnings == []


# ===========================================================================
# handle_sent
# ===========================================================================


class TestHandleSent:
    """Tests for email.handle_sent orchestrator."""

    def test_sent_no_folder(self, tmp_path, monkeypatch, capsys: pytest.CaptureFixture[str]):
        """No sent folder prints 'No sent messages'."""
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email._resolve_branch_path",
            lambda: tmp_path,
        )
        printed = _StdoutLines(capsys)

        result = handle_sent([])
        assert result is True
        assert any("No sent" in p for p in printed)

    def test_sent_with_files(self, tmp_path, monkeypatch, capsys: pytest.CaptureFixture[str]):
        """Sent folder with files loads and displays them."""
        sent_folder = tmp_path / ".ai_mail.local" / "sent"
        sent_folder.mkdir(parents=True)
        email_data = {"id": "s1", "to": "@target", "subject": "Sent test"}
        (sent_folder / "email_001.json").write_text(json.dumps(email_data), encoding="utf-8")

        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email._resolve_branch_path",
            lambda: tmp_path,
        )
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.load_email_file",
            lambda f: email_data,
        )
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.format_email_list_item",
            lambda i, data, show_unread=True: f"[{i}] {data['subject']}",
        )
        printed = _StdoutLines(capsys)

        result = handle_sent([])
        assert result is True
        assert any("Sent Messages" in p for p in printed)
        assert any("[1]" in p for p in printed)

    def test_sent_empty_folder(self, tmp_path, monkeypatch, capsys: pytest.CaptureFixture[str]):
        """Sent folder exists but has no JSON files."""
        sent_folder = tmp_path / ".ai_mail.local" / "sent"
        sent_folder.mkdir(parents=True)

        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email._resolve_branch_path",
            lambda: tmp_path,
        )
        printed = _StdoutLines(capsys)

        result = handle_sent([])
        assert result is True
        assert any("No sent" in p for p in printed)


# ===========================================================================
# handle_inbox additional paths
# ===========================================================================


class TestHandleInboxExtended:
    """Extended tests for handle_inbox edge cases."""

    def test_inbox_nonexistent_file(self, tmp_path, monkeypatch, capsys: pytest.CaptureFixture[str]):
        """When inbox_file does not exist, prints 'empty' (line 156-158)."""
        non_existent = tmp_path / ".ai_mail.local" / "inbox.json"

        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.resolve_inbox_target",
            lambda first_arg, repo_root, get_branch_fn, get_user_fn: (
                True,
                {
                    "inbox_file": non_existent,
                    "display_name": "TEST",
                    "target_branch": None,
                    "error": None,
                },
            ),
        )
        printed = _StdoutLines(capsys)

        result = handle_inbox([])
        assert result is True
        assert any("empty" in p.lower() for p in printed)

    def test_inbox_with_target_branch_label(self, tmp_path, monkeypatch, capsys: pytest.CaptureFixture[str]):
        """When resolve returns target_branch, label shows 'for @target (NAME)'."""
        messages = [{"id": "m1", "status": "new", "subject": "Hello"}]
        _write_inbox(tmp_path, messages=messages)

        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.resolve_inbox_target",
            lambda first_arg, repo_root, get_branch_fn, get_user_fn: (
                True,
                {
                    "inbox_file": tmp_path / ".ai_mail.local" / "inbox.json",
                    "display_name": "ALPHA",
                    "target_branch": "@alpha",
                    "error": None,
                },
            ),
        )
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.load_inbox",
            lambda f: {"messages": messages},
        )
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.format_email_list_item",
            lambda i, msg, show_unread=True: f"[{i}] {msg['subject']}",
        )
        printed = _StdoutLines(capsys)

        result = handle_inbox(["@alpha"])
        assert result is True
        assert any("for @alpha (ALPHA)" in p for p in printed)

    def test_inbox_broken_pipe(self, monkeypatch):
        """BrokenPipeError is caught and returns True (line 173-175)."""
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.resolve_inbox_target",
            lambda first_arg, repo_root, get_branch_fn, get_user_fn: (_ for _ in ()).throw(
                BrokenPipeError("pipe closed")
            ),
        )

        result = handle_inbox([])
        assert result is True

    def test_inbox_generic_exception(self, monkeypatch):
        """A generic exception is caught, reported, and stays handled."""
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.resolve_inbox_target",
            lambda first_arg, repo_root, get_branch_fn, get_user_fn: (_ for _ in ()).throw(ValueError("corrupt inbox")),
        )
        errors: list[str] = []
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.error",
            lambda msg: errors.append(msg),
        )

        result = handle_inbox([])
        assert result is True
        assert any("corrupt inbox" in e for e in errors)


# ===========================================================================
# handle_view additional paths
# ===========================================================================


class TestHandleViewExtended:
    """Extended tests for handle_view edge cases."""

    def test_view_broken_pipe(self, tmp_path, monkeypatch):
        """BrokenPipeError is caught and returns True (line 217-219)."""
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email._resolve_branch_path",
            lambda: tmp_path,
        )
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.mark_as_opened",
            lambda bp, mid: (_ for _ in ()).throw(BrokenPipeError("pipe")),
        )

        result = handle_view(["some_id"])
        assert result is True

    def test_view_generic_exception(self, tmp_path, monkeypatch):
        """Generic exception is caught and returns True (lines 220-223)."""
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email._resolve_branch_path",
            lambda: tmp_path,
        )
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.mark_as_opened",
            lambda bp, mid: (_ for _ in ()).throw(RuntimeError("db error")),
        )
        errors: list[str] = []
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.error",
            lambda msg: errors.append(msg),
        )

        result = handle_view(["some_id"])
        assert result is True
        assert any("db error" in e for e in errors)

    def test_view_latest_empty_inbox(self, tmp_path, monkeypatch):
        """'latest' with empty inbox returns True and prints error."""
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email._resolve_branch_path",
            lambda: tmp_path,
        )
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.load_inbox",
            lambda f: {"messages": []},
        )
        errors: list[str] = []
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.error",
            lambda msg: errors.append(msg),
        )

        result = handle_view(["latest"])
        assert result is True
        assert any("empty" in e.lower() for e in errors)

    def test_view_latest_no_id_on_message(self, tmp_path, monkeypatch):
        """'latest' with message missing 'id' key returns True, prints error."""
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email._resolve_branch_path",
            lambda: tmp_path,
        )
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.load_inbox",
            lambda f: {"messages": [{"subject": "no id here"}]},
        )
        errors: list[str] = []
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.error",
            lambda msg: errors.append(msg),
        )

        result = handle_view(["latest"])
        assert result is True
        assert any("latest" in e.lower() or "could not" in e.lower() for e in errors)


# ===========================================================================
# handle_close additional paths
# ===========================================================================


class TestHandleCloseExtended:
    """Extended tests for handle_close edge cases."""

    def test_close_batch_mixed_success_failure(self, tmp_path, monkeypatch, capsys: pytest.CaptureFixture[str]):
        """Batch close with mixed results prints both success and error."""
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email._resolve_branch_path",
            lambda: tmp_path,
        )
        results = [
            ("m1", True, "Closed m1"),
            ("m2", False, "Not found: m2"),
            ("m3", True, "Closed m3"),
        ]
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.batch_close",
            lambda bp, ids, fn: (results, 2, 1),
        )
        # post_ops writes the live central file and runs purge, so it stays patched and is asserted (ai_mail, leg 6)
        post_ops = MagicMock()
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email.batch_close_post_ops", post_ops)
        printed = _StdoutLines(capsys)
        errors: list[str] = []
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.error",
            lambda msg: errors.append(msg),
        )

        result = handle_close(["m1", "m2", "m3"])
        assert result is True
        assert any("Closed m1" in p for p in printed)
        assert any("Not found: m2" in e for e in errors)
        post_ops.assert_called_once()
        assert post_ops.call_args.args[0] == tmp_path
        assert any("Closed m3" in p for p in printed)
        assert any("Closed 2" in p and "failed 1" in p for p in printed)

    def test_close_generic_exception(self, tmp_path, monkeypatch):
        """Generic exception is caught and returns True (lines 261-264)."""
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email._resolve_branch_path",
            lambda: (_ for _ in ()).throw(RuntimeError("branch error")),
        )
        errors: list[str] = []
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.error",
            lambda msg: errors.append(msg),
        )

        result = handle_close(["m1"])
        assert result is True
        assert any("branch error" in e for e in errors)

    def test_close_single_id_no_post_ops(self, tmp_path, monkeypatch):
        """Single ID close does NOT trigger post_ops."""
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email._resolve_branch_path",
            lambda: tmp_path,
        )
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.batch_close",
            lambda bp, ids, fn: ([("m1", True, "Closed m1")], 1, 0),
        )
        post_ops_called: list[bool] = []
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.batch_close_post_ops",
            lambda bp, central_fn, purge_fn: post_ops_called.append(True),
        )
        error_mock = MagicMock()
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email.error", error_mock)

        result = handle_close(["m1"])
        assert result is True
        assert len(post_ops_called) == 0
        error_mock.assert_not_called()


# ===========================================================================
# handle_reply generic exception (email.py lines 288-291)
# ===========================================================================


class TestHandleReplyExtended:
    """Extended tests for handle_reply edge cases."""

    def test_reply_generic_exception(self, tmp_path, monkeypatch):
        """Generic exception is caught and returns True (lines 288-291)."""
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email._resolve_branch_path",
            lambda: (_ for _ in ()).throw(OSError("disk fail")),
        )
        errors: list[str] = []
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.error",
            lambda msg: errors.append(msg),
        )

        result = handle_reply(["msg1", "my reply"])
        assert result is True
        assert any("disk fail" in e for e in errors)


# ===========================================================================
# handle_sent generic exception (email.py lines 312-316)
# ===========================================================================


class TestHandleSentExtended:
    """Extended tests for handle_sent edge cases."""

    def test_sent_generic_exception(self, monkeypatch):
        """Generic exception is caught and returns True (lines 312-316)."""
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email._resolve_branch_path",
            lambda: (_ for _ in ()).throw(RuntimeError("path error")),
        )
        errors: list[str] = []
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.error",
            lambda msg: errors.append(msg),
        )

        result = handle_sent([])
        assert result is True
        assert any("path error" in e for e in errors)


class TestHandleReplyMultiArg:
    """Regression tests for multi-line reply body truncation (S84 fix)."""

    def test_reply_joins_split_args_into_body(self, tmp_path, monkeypatch):
        """When shell splits body into multiple args, all are joined into message."""
        original = {"id": "msg1", "from": "@devpulse", "subject": "test dispatch"}
        captured_msg = []

        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email._resolve_branch_path",
            lambda: tmp_path,
        )
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.get_email_by_id",
            lambda inbox_file, msg_id: original,
        )
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.send_reply",
            lambda bp, orig, msg: (captured_msg.append(msg), "Reply sent", "r1")[1:],
        )
        _write_inbox(tmp_path)

        result = handle_reply(["msg1", "Line one", "Line two", "Line three"])
        assert result is True
        assert len(captured_msg) == 1
        assert captured_msg[0] == "Line one Line two Line three"

    def test_reply_single_arg_unchanged(self, tmp_path, monkeypatch):
        """Single-arg reply body remains unchanged (no extra spaces)."""
        original = {"id": "msg1", "from": "@devpulse", "subject": "test"}
        captured_msg = []

        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email._resolve_branch_path",
            lambda: tmp_path,
        )
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.get_email_by_id",
            lambda inbox_file, msg_id: original,
        )
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.send_reply",
            lambda bp, orig, msg: (captured_msg.append(msg), "Reply sent", "r1")[1:],
        )
        _write_inbox(tmp_path)

        result = handle_reply(["msg1", "Complete single-line reply"])
        assert result is True
        assert captured_msg[0] == "Complete single-line reply"


class TestListingNeverHidesMail:
    """The listing surfaces must never silently drop a message.

    delivery.py inserts new mail at index 0, so messages[0] is the NEWEST.
    The old listing did reversed(messages)[:20], which kept the OLDEST 20 —
    in any inbox holding more than 20 messages every new arrival was
    invisible with no error anywhere. Fixtures here are ordered
    newest-first to match what delivery actually writes; an oldest-first
    fixture would share the bug's assumption and pass either way.
    """

    def _run_inbox(self, monkeypatch, tmp_path, messages, capsys: pytest.CaptureFixture[str]):
        """Run handle_inbox over the given store, return printed lines."""
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.resolve_inbox_target",
            lambda first_arg, repo_root, get_branch_fn, get_user_fn: (
                True,
                {
                    "inbox_file": tmp_path / ".ai_mail.local" / "inbox.json",
                    "display_name": "TEST",
                    "target_branch": None,
                    "error": None,
                },
            ),
        )
        inbox_file = tmp_path / ".ai_mail.local" / "inbox.json"
        inbox_file.parent.mkdir(parents=True, exist_ok=True)
        inbox_file.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.load_inbox",
            lambda f: {"messages": messages},
        )
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.format_email_list_item",
            lambda i, msg, show_unread=True: f"{i}. {msg['subject']}",
        )
        printed = _StdoutLines(capsys)

        assert handle_inbox([]) is True
        return printed

    def test_newest_message_listed_when_store_exceeds_limit(
        self, monkeypatch, tmp_path, capsys: pytest.CaptureFixture[str]
    ):
        """CANARY: the newest arrival must be visible in an over-limit inbox."""
        # Newest first, exactly as delivery.py writes it.
        messages = [{"id": f"m{i:03d}", "subject": f"subject-{i:03d}", "status": "new"} for i in range(25)]
        printed = self._run_inbox(monkeypatch, tmp_path, messages, capsys)
        blob = "\n".join(printed)

        assert "subject-000" in blob, "newest message was dropped from the listing"
        assert "subject-019" in blob, "20th-newest message should still list"
        assert "subject-024" not in blob, "oldest message should fall off, not the newest"

    def test_over_limit_listing_says_it_truncated(self, monkeypatch, tmp_path, capsys: pytest.CaptureFixture[str]):
        """Truncation is reported as 'most recent of N', not a bare count."""
        messages = [{"id": f"m{i:03d}", "subject": f"subject-{i:03d}", "status": "new"} for i in range(25)]
        printed = self._run_inbox(monkeypatch, tmp_path, messages, capsys)
        assert any("20 most recent of 25 messages" in p for p in printed)

    def test_under_limit_lists_every_message_oldest_first(
        self, monkeypatch, tmp_path, capsys: pytest.CaptureFixture[str]
    ):
        """Nothing is dropped under the limit; display order stays oldest-first."""
        messages = [{"id": f"m{i}", "subject": f"subject-{i}", "status": "new"} for i in range(3)]
        printed = self._run_inbox(monkeypatch, tmp_path, messages, capsys)
        rows = [p for p in printed if p.strip().startswith(("1.", "2.", "3."))]
        assert [r.strip() for r in rows] == ["1. subject-2", "2. subject-1", "3. subject-0"]
        assert any("Showing 3 of 3 messages" in p for p in printed)

    def test_row_that_fails_to_render_is_shown_raw_not_hidden(
        self, monkeypatch, tmp_path, capsys: pytest.CaptureFixture[str]
    ):
        """CANARY: a row the console rejects degrades visibly instead of vanishing.

        The real console rejects the stray closing tag itself (leg 5 took out the
        fake console that raised on cue), so the failure is Rich's own. The logger
        is replaced so the degraded path writes no live log, and asserted. The row
        is printed by `inbox` itself, not by the row helper (ai_mail, leg 14).
        """
        log = MagicMock()
        monkeypatch.setattr(email_mod, "logger", log)

        messages = [{"id": "m0", "subject": "Subject: RE: [/rc] recovered", "status": "new"}]
        blob = "\n".join(self._run_inbox(monkeypatch, tmp_path, messages, capsys))
        assert "RE: [/rc] recovered" in blob, "unrenderable row vanished instead of degrading"
        assert "RAW" in blob, "degraded row must carry a visible marker"
        log.warning.assert_called_once()
        assert log.warning.call_args.args[0] == "[email] row render failed, printing raw: %s"

    def test_unreadable_sent_file_still_gets_a_row(self, monkeypatch, tmp_path, capsys: pytest.CaptureFixture[str]):
        """CANARY: a sent file that will not load is listed as a placeholder."""
        sent_folder = tmp_path / ".ai_mail.local" / "sent"
        sent_folder.mkdir(parents=True)
        (sent_folder / "aaaa1111.json").write_text("{}", encoding="utf-8")

        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email._resolve_branch_path",
            lambda: tmp_path,
        )
        # The stub stands for a file that will not load ("{}" would load); asserted on the file it was handed
        load = MagicMock(return_value=None)
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email.load_email_file", load)
        printed = _StdoutLines(capsys)

        assert handle_sent([]) is True
        load.assert_called_once_with(sent_folder / "aaaa1111.json")
        blob = "\n".join(printed)
        assert "aaaa1111.json" in blob, "unreadable sent file was silently skipped"
        assert "UNREADABLE FILE" in blob


class TestViewLatestResolvesNewest:
    """'latest' must mean newest. delivery.py inserts at index 0, so reading
    messages[-1] served the OLDEST mail in the inbox under that name."""

    def test_view_latest_picks_index_zero(self, monkeypatch, tmp_path):
        """CANARY: 'latest' resolves the newest message, not the oldest."""
        # Newest first, as delivery writes it.
        messages = [
            {"id": "newest01", "subject": "arrived 17:31"},
            {"id": "middle01", "subject": "arrived 15:18"},
            {"id": "oldest01", "subject": "arrived 12:31"},
        ]
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email._resolve_branch_path",
            lambda: tmp_path,
        )
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.load_inbox",
            lambda f: {"messages": messages},
        )
        opened: list[str] = []

        def fake_mark_as_opened(branch_path, message_id):
            opened.append(message_id)
            return True, "ok", {"subject": "s", "message": "m", "from_name": "X", "from": "@x"}

        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.mark_as_opened",
            fake_mark_as_opened,
        )
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.format_email_header",
            lambda data: "HEADER",
        )
        assert handle_view(["latest"]) is True
        assert opened == ["newest01"], f"'latest' opened {opened}, expected the newest message"


class TestBodyRendersWhateverTheSenderTyped:
    """The view body is the primary read surface and carries raw sender text.

    Escaping the listing but rendering the body as markup only moved the
    failure: a body containing "[/rc]" raised MarkupError and the message
    could not be read at all. Bodies never carry styling of their own, so
    they render with markup disabled — which cannot raise rather than
    merely being escaped correctly.
    """

    def _view_message(self, monkeypatch, tmp_path, body, capsys: pytest.CaptureFixture[str]):
        """Run handle_view over a message with the given body; return what stdout received.

        The product's own console prints; leg 5 took out the Rich console on a
        buffer that stood in its place (mock_console).
        """
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email._resolve_branch_path",
            lambda: tmp_path,
        )
        email_data = {
            "id": "body0001",
            "subject": "RE: /rc <target>",
            "message": body,
            "from_name": "SKILLS",
            "from": "@skills",
            "timestamp": "2026-08-07 17:40:20",
        }
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.mark_as_opened",
            lambda bp, mid: (True, "Opened", email_data),
        )
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.format_email_header",
            lambda ed: "HEADER",
        )

        assert handle_view(["body0001"]) is True
        return " ".join(capsys.readouterr().out.split())

    def test_body_with_closing_tag_renders_instead_of_raising(
        self, monkeypatch, tmp_path, capsys: pytest.CaptureFixture[str]
    ):
        """CANARY: a body containing [/rc] must render, not abort the view."""
        body = "SHIPPED — [/rc] is live on the control bot. Re-verified this session."
        out = self._view_message(monkeypatch, tmp_path, body, capsys)
        assert "[/rc] is live on the control bot" in out

    def test_body_with_style_tag_keeps_its_text(self, monkeypatch, tmp_path, capsys: pytest.CaptureFixture[str]):
        """A body containing [dim] renders the tag literally, text intact."""
        body = "Line one [dim]note kept[/dim] and [skills] tag kept."
        out = self._view_message(monkeypatch, tmp_path, body, capsys)
        assert "[dim]note kept[/dim]" in out
        assert "[skills] tag kept" in out

    def test_body_renders_with_markup_disabled(self, monkeypatch, tmp_path, capsys: pytest.CaptureFixture[str]):
        """A body's style tags reach stdout as written, never consumed as markup.

        Read through the product's own console (ai_mail, leg 7). What the console
        stand-in could see and stdout cannot: the markup=False keyword itself. A
        body escaped by hand prints the same text, so this pins what the reader
        sees, not which of the two routes produced it.
        """
        out = self._view_message(monkeypatch, tmp_path, "raw [bold]body[/bold] kept", capsys)
        assert "raw [bold]body[/bold] kept" in out, "body printed as markup — its tags were consumed"
