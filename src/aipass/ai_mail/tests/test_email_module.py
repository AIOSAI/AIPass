# =================== AIPass ====================
# Name: test_email_module.py
# Description: Tests for email.py and email_send.py orchestrator functions
# Version: 1.0.0
# Created: 2026-04-25
# Modified: 2026-04-25
# =============================================

"""Tests for email.py and email_send.py orchestrator functions.

Covers: handle_inbox, handle_view, handle_close, handle_reply,
handle_sent, handle_contacts, handle_register (email.py),
and handle_send (email_send.py).

All handler dependencies are mocked -- these tests verify orchestration
logic, not business logic.
"""

import io
import json
import sys
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Bind the REAL module objects once, at collection time, before any test can
# replace them in sys.modules. Other test modules in the suite install
# MagicMock stand-ins under these sys.modules keys (e.g.
# trigger/tests/test_memory_pool_handler.py) and never restore them, so any
# string-path patch or in-test `from ... import x` would otherwise resolve to
# a mock on an xdist worker that ran the polluter first.
from aipass.ai_mail.apps.modules import email as email_mod
from aipass.ai_mail.apps.modules import email_send as email_send_mod


# ---------------------------------------------------------------------------
# Autouse fixture: pin the real modules into sys.modules for the test duration
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _pin_real_modules(monkeypatch):
    """Guarantee string-path patches resolve to the real modules, not stubs.

    monkeypatch.setitem restores the previous sys.modules value exactly on
    teardown, so this never leaks in either direction.
    """
    monkeypatch.setitem(sys.modules, "aipass.ai_mail.apps.modules.email", email_mod)
    monkeypatch.setitem(sys.modules, "aipass.ai_mail.apps.modules.email_send", email_send_mod)


# ---------------------------------------------------------------------------
# Autouse fixture: suppress json_handler.log_operation across both modules
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _silence_json_handler():
    """Prevent log_operation from writing real JSON files during tests."""
    with (
        patch.object(email_mod, "json_handler") as mock_email_jh,
        patch.object(email_send_mod, "json_handler") as mock_send_jh,
    ):
        mock_email_jh.log_operation.return_value = True
        mock_send_jh.log_operation.return_value = True
        yield


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

    def test_inbox_empty_messages(self, tmp_path, monkeypatch):
        """Empty inbox prints 'is empty' message."""
        _write_inbox(tmp_path, messages=[])

        printed: list[str] = []
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
        mock_console = MagicMock()
        mock_console.print = lambda msg, **kw: printed.append(str(msg))
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email.console", mock_console)

        from aipass.ai_mail.apps.modules.email import handle_inbox

        result = handle_inbox([])
        assert result is True
        assert any("empty" in p.lower() for p in printed)

    def test_inbox_with_messages(self, tmp_path, monkeypatch):
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
        printed: list[str] = []
        mock_console = MagicMock()
        mock_console.print = lambda msg, **kw: printed.append(str(msg))
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email.console", mock_console)

        from aipass.ai_mail.apps.modules.email import handle_inbox

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

        from aipass.ai_mail.apps.modules.email import handle_inbox

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

        from aipass.ai_mail.apps.modules.email import handle_view

        result = handle_view([])
        assert result is True
        assert any("Usage" in e for e in errors)

    def test_view_marks_opened_and_prints(self, tmp_path, monkeypatch):
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
        printed: list[str] = []
        mock_console = MagicMock()
        mock_console.print = lambda msg, **kw: printed.append(str(msg))
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email.console", mock_console)

        from aipass.ai_mail.apps.modules.email import handle_view

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

        from aipass.ai_mail.apps.modules.email import handle_view

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
        mock_console = MagicMock()
        mock_console.print = lambda msg, **kw: None
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email.console", mock_console)

        from aipass.ai_mail.apps.modules.email import handle_view

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

        from aipass.ai_mail.apps.modules.email import handle_close

        result = handle_close([])
        assert result is True
        assert any("Usage" in e for e in errors)

    def test_close_single_id(self, tmp_path, monkeypatch):
        """Close a single message ID via batch_close."""
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email._resolve_branch_path",
            lambda: tmp_path,
        )
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.batch_close",
            lambda bp, ids, fn: ([("msg1", True, "Closed msg1")], 1, 0),
        )
        printed: list[str] = []
        mock_console = MagicMock()
        mock_console.print = lambda msg, **kw: printed.append(str(msg))
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email.console", mock_console)
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email.error", lambda msg: None)

        from aipass.ai_mail.apps.modules.email import handle_close

        result = handle_close(["msg1"])
        assert result is True
        assert any("Closed" in p for p in printed)

    def test_close_all(self, tmp_path, monkeypatch):
        """Close 'all' delegates to mark_all_read_and_archive."""
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email._resolve_branch_path",
            lambda: tmp_path,
        )
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.mark_all_read_and_archive",
            lambda bp: (True, "Archived 5 messages", 5),
        )
        printed: list[str] = []
        mock_console = MagicMock()
        mock_console.print = lambda msg, **kw: printed.append(str(msg))
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email.console", mock_console)

        from aipass.ai_mail.apps.modules.email import handle_close

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
        mock_console = MagicMock()
        mock_console.print = lambda msg, **kw: None
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email.console", mock_console)

        from aipass.ai_mail.apps.modules.email import handle_close

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
        mock_console = MagicMock()
        mock_console.print = lambda msg, **kw: None
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email.console", mock_console)
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email.error", lambda msg: None)

        from aipass.ai_mail.apps.modules.email import handle_close

        result = handle_close(["m1", "m2"])
        assert result is True
        assert len(post_ops_called) == 1


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

        from aipass.ai_mail.apps.modules.email import handle_reply

        result = handle_reply(["only_id"])
        assert result is True
        assert any("Usage" in e for e in errors)

    def test_reply_message_not_found(self, tmp_path, monkeypatch):
        """Reply to nonexistent message shows error."""
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email._resolve_branch_path",
            lambda: tmp_path,
        )
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.get_email_by_id",
            lambda inbox_file, msg_id: None,
        )
        errors: list[str] = []
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.error",
            lambda msg: errors.append(msg),
        )
        _write_inbox(tmp_path)

        from aipass.ai_mail.apps.modules.email import handle_reply

        result = handle_reply(["missing_id", "my reply"])
        assert result is True
        assert any("not found" in e.lower() for e in errors)

    def test_reply_success(self, tmp_path, monkeypatch):
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
        printed: list[str] = []
        mock_console = MagicMock()
        mock_console.print = lambda msg, **kw: printed.append(str(msg))
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email.console", mock_console)
        _write_inbox(tmp_path)

        from aipass.ai_mail.apps.modules.email import handle_reply

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

        from aipass.ai_mail.apps.modules.email import handle_reply

        result = handle_reply(["msg1", "reply text"])
        assert result is True
        assert any("Delivery failed" in e for e in errors)


# ===========================================================================
# handle_sent
# ===========================================================================


class TestHandleSent:
    """Tests for email.handle_sent orchestrator."""

    def test_sent_no_folder(self, tmp_path, monkeypatch):
        """No sent folder prints 'No sent messages'."""
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email._resolve_branch_path",
            lambda: tmp_path,
        )
        printed: list[str] = []
        mock_console = MagicMock()
        mock_console.print = lambda msg, **kw: printed.append(str(msg))
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email.console", mock_console)

        from aipass.ai_mail.apps.modules.email import handle_sent

        result = handle_sent([])
        assert result is True
        assert any("No sent" in p for p in printed)

    def test_sent_with_files(self, tmp_path, monkeypatch):
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
        printed: list[str] = []
        mock_console = MagicMock()
        mock_console.print = lambda msg, **kw: printed.append(str(msg))
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email.console", mock_console)

        from aipass.ai_mail.apps.modules.email import handle_sent

        result = handle_sent([])
        assert result is True
        assert any("Sent Messages" in p for p in printed)
        assert any("[1]" in p for p in printed)

    def test_sent_empty_folder(self, tmp_path, monkeypatch):
        """Sent folder exists but has no JSON files."""
        sent_folder = tmp_path / ".ai_mail.local" / "sent"
        sent_folder.mkdir(parents=True)

        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email._resolve_branch_path",
            lambda: tmp_path,
        )
        printed: list[str] = []
        mock_console = MagicMock()
        mock_console.print = lambda msg, **kw: printed.append(str(msg))
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email.console", mock_console)

        from aipass.ai_mail.apps.modules.email import handle_sent

        result = handle_sent([])
        assert result is True
        assert any("No sent" in p for p in printed)


# ===========================================================================
# handle_contacts
# ===========================================================================


class TestHandleContacts:
    """Tests for email.handle_contacts orchestrator."""

    def test_contacts_displays_branches(self, monkeypatch):
        """Contacts lists all registered branches."""
        branches = [
            {"email": "@alpha", "name": "ALPHA", "path": "/src/alpha"},
            {"email": "@beta", "name": "BETA", "path": "/src/beta"},
        ]
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.get_all_branches",
            lambda: branches,
        )
        printed: list[str] = []
        mock_console = MagicMock()
        mock_console.print = lambda msg, **kw: printed.append(str(msg))
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email.console", mock_console)

        from aipass.ai_mail.apps.modules.email import handle_contacts

        result = handle_contacts([])
        assert result is True
        assert any("2 branches" in p for p in printed)
        # Branches should appear sorted by email
        alpha_lines = [p for p in printed if "@alpha" in p]
        assert len(alpha_lines) > 0

    def test_contacts_empty(self, monkeypatch):
        """No contacts found prints error."""
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.get_all_branches",
            lambda: [],
        )
        errors: list[str] = []
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.error",
            lambda msg: errors.append(msg),
        )

        from aipass.ai_mail.apps.modules.email import handle_contacts

        result = handle_contacts([])
        assert result is True
        assert any("No contacts" in e for e in errors)

    def test_contacts_exception_handled(self, monkeypatch):
        """Exception in get_all_branches is caught and error is shown."""
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.get_all_branches",
            lambda: (_ for _ in ()).throw(RuntimeError("Registry unavailable")),
        )
        errors: list[str] = []
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.error",
            lambda msg: errors.append(msg),
        )

        from aipass.ai_mail.apps.modules.email import handle_contacts

        result = handle_contacts([])
        assert result is True
        assert any("Registry unavailable" in e for e in errors)


# ===========================================================================
# handle_register
# ===========================================================================


class TestHandleRegister:
    """Tests for email.handle_register orchestrator."""

    def test_register_too_few_args(self, monkeypatch):
        """Register with < 2 args prints usage error."""
        errors: list[str] = []
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.error",
            lambda msg: errors.append(msg),
        )

        from aipass.ai_mail.apps.modules.email import handle_register

        result = handle_register(["@branch"])
        assert result is True
        assert any("Usage" in e for e in errors)

    def test_register_success(self, monkeypatch):
        """Successful registration prints green confirmation."""
        printed: list[str] = []
        mock_console = MagicMock()
        mock_console.print = lambda msg, **kw: printed.append(str(msg))
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email.console", mock_console)

        # register_contact is imported locally inside handle_register,
        # so patch at the handler source module
        with patch(
            "aipass.ai_mail.apps.handlers.email.contacts.register_contact",
            return_value=True,
        ):
            from aipass.ai_mail.apps.modules.email import handle_register

            result = handle_register(["@devpulse", "/path/to/inbox"])
        assert result is True
        assert any("Registered" in p and "devpulse" in p for p in printed)

    def test_register_failure(self, monkeypatch):
        """Failed registration prints error."""
        errors: list[str] = []
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.error",
            lambda msg: errors.append(msg),
        )
        mock_console = MagicMock()
        mock_console.print = lambda msg, **kw: None
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email.console", mock_console)

        with patch(
            "aipass.ai_mail.apps.handlers.email.contacts.register_contact",
            return_value=False,
        ):
            from aipass.ai_mail.apps.modules.email import handle_register

            result = handle_register(["@badstuff", "/path/to/inbox"])
        assert result is True
        assert any("Failed" in e for e in errors)

    def test_register_with_project_arg(self, monkeypatch):
        """Third arg is passed as project name."""
        registered_args: list[tuple] = []

        def _mock_register(name, project, path):
            """Capture register_contact arguments for assertion."""
            registered_args.append((name, project, path))
            return True

        mock_console = MagicMock()
        mock_console.print = lambda msg, **kw: None
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email.console", mock_console)

        with patch(
            "aipass.ai_mail.apps.handlers.email.contacts.register_contact",
            side_effect=_mock_register,
        ):
            from aipass.ai_mail.apps.modules.email import handle_register

            result = handle_register(["@vera", "/path/to/inbox", "VeraStudio"])
        assert result is True
        assert registered_args[0] == ("vera", "VeraStudio", "/path/to/inbox")


# ===========================================================================
# handle_send (from email_send.py)
# ===========================================================================


class TestHandleSend:
    """Tests for email_send.handle_send orchestrator."""

    def test_send_direct_single_recipient(self, monkeypatch):
        """Direct send to a single recipient calls send_to_single."""
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email_send.parse_send_args",
            lambda args: {
                "mode": "direct",
                "recipients": ["@target"],
                "subject": "Hello",
                "message": "World",
                "auto_execute": False,
                "reply_to": None,
                "no_memory_save": False,
                "from_branch": None,
            },
        )
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email_send.resolve_dispatch_target",
            lambda branch, auto, fn: None,
        )
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email_send.resolve_sender_info",
            lambda fb, rr, amd, gbe, gcu: {
                "email_address": "@ai_mail",
                "display_name": "AI_MAIL",
                "mailbox_path": "/tmp/mailbox",
            },
        )
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email_send.send_to_single",
            lambda *a, **kw: (True, None),
        )
        printed: list[str] = []
        mock_console = MagicMock()
        mock_console.print = lambda msg, **kw: printed.append(str(msg))
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email_send.console", mock_console)
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email_send.error", lambda msg: None)

        from aipass.ai_mail.apps.modules.email_send import handle_send

        result = handle_send(["@target", "Hello", "World"])
        assert result is True
        assert any("sent" in p.lower() and "@target" in p for p in printed)

    def test_send_error_mode(self, monkeypatch):
        """A parse error prints usage and stays handled (exit 2, not 1)."""
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email_send.parse_send_args",
            lambda args: {
                "mode": "error",
                "error": "Usage: send @recipient [subject] [message]",
            },
        )
        errors: list[str] = []
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email_send.error",
            lambda msg: errors.append(msg),
        )
        mock_console = MagicMock()
        mock_console.print = lambda msg, **kw: None
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email_send.console", mock_console)

        from aipass.ai_mail.apps.modules.email_send import handle_send

        result = handle_send(["bad", "args"])
        assert result is True
        assert any("Usage" in e for e in errors)

    def test_send_delivery_failure(self, monkeypatch):
        """When send_to_single returns failure, error is printed."""
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email_send.parse_send_args",
            lambda args: {
                "mode": "direct",
                "recipients": ["@target"],
                "subject": "Sub",
                "message": "Msg",
                "auto_execute": False,
                "reply_to": None,
                "no_memory_save": False,
                "from_branch": None,
            },
        )
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email_send.resolve_dispatch_target",
            lambda branch, auto, fn: None,
        )
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email_send.resolve_sender_info",
            lambda fb, rr, amd, gbe, gcu: {
                "email_address": "@ai_mail",
                "display_name": "AI_MAIL",
                "mailbox_path": "/tmp/mailbox",
            },
        )
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email_send.send_to_single",
            lambda *a, **kw: (False, "Branch not found"),
        )
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email_send.dispatch_send_error",
            lambda *a, **kw: None,
        )
        errors: list[str] = []
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email_send.error",
            lambda msg: errors.append(msg),
        )
        mock_console = MagicMock()
        mock_console.print = lambda msg, **kw: None
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email_send.console", mock_console)

        from aipass.ai_mail.apps.modules.email_send import handle_send

        result = handle_send(["@target", "Sub", "Msg"])
        assert result is True
        assert any("Branch not found" in e for e in errors)

    def test_send_interactive_mode(self, monkeypatch):
        """A cancelled interactive send is still a handled command."""
        # pytest's stdin is not a terminal, so without this the no-TTY guard
        # answers first and this test would pass while never reaching the
        # cancel path it is named for.
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email_send.parse_send_args",
            lambda args: {"mode": "interactive"},
        )
        # _send_interactive calls get_all_branches and collect_interactive_input
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email_send.get_all_branches",
            lambda: [{"name": "A", "email": "@a"}],
        )
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email_send.collect_interactive_input",
            lambda branches: None,  # User cancelled
        )
        printed: list[str] = []
        mock_console = MagicMock()
        mock_console.print = lambda msg, **kw: printed.append(str(msg))
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email_send.console", mock_console)

        from aipass.ai_mail.apps.modules.email_send import handle_send

        result = handle_send([])
        assert result is True
        assert any("Cancelled" in p for p in printed)

    def test_send_dispatch_fires_trigger(self, monkeypatch):
        """With auto_execute, dispatch trigger is fired after successful send."""
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email_send.parse_send_args",
            lambda args: {
                "mode": "direct",
                "recipients": ["@target"],
                "subject": "Dispatch Task",
                "message": "Do the thing",
                "auto_execute": True,
                "reply_to": None,
                "no_memory_save": False,
                "from_branch": None,
            },
        )
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email_send.resolve_dispatch_target",
            lambda branch, auto, fn: "@target",
        )
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email_send.resolve_sender_info",
            lambda fb, rr, amd, gbe, gcu: {
                "email_address": "@ai_mail",
                "display_name": "AI_MAIL",
                "mailbox_path": "/tmp/mailbox",
            },
        )
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email_send.prepend_dispatch_header",
            lambda msg, no_memory_save=False: f"[DISPATCH] {msg}",
        )
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email_send.send_to_single",
            lambda *a, **kw: (True, None),
        )

        trigger_calls: list[tuple] = []
        mock_trigger = MagicMock()
        mock_trigger.fire = lambda event, **kw: trigger_calls.append((event, kw))
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email_send.trigger", mock_trigger)

        mock_console = MagicMock()
        mock_console.print = lambda msg, **kw: None
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email_send.console", mock_console)
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email_send.error", lambda msg: None)

        from aipass.ai_mail.apps.modules.email_send import handle_send

        result = handle_send(["@target", "Dispatch Task", "Do the thing", "--dispatch"])
        assert result is True
        assert len(trigger_calls) == 1
        assert trigger_calls[0][0] == "email_dispatched"
        assert trigger_calls[0][1]["to"] == "@target"

    def test_send_group_multiple_recipients(self, monkeypatch):
        """Group send to multiple recipients calls _send_direct for each."""
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email_send.parse_send_args",
            lambda args: {
                "mode": "direct",
                "recipients": ["@alpha", "@beta"],
                "subject": "Group msg",
                "message": "Hi all",
                "auto_execute": False,
                "reply_to": None,
                "no_memory_save": False,
                "from_branch": None,
            },
        )
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email_send.resolve_dispatch_target",
            lambda branch, auto, fn: None,
        )
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email_send.resolve_sender_info",
            lambda fb, rr, amd, gbe, gcu: {
                "email_address": "@ai_mail",
                "display_name": "AI_MAIL",
                "mailbox_path": "/tmp/mailbox",
            },
        )

        sent_to: list[str] = []

        def mock_send_single(*args, **kwargs):
            """Track which branches receive send_to_single calls."""
            sent_to.append(args[0])
            return (True, None)

        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email_send.send_to_single",
            mock_send_single,
        )
        printed: list[str] = []
        mock_console = MagicMock()
        mock_console.print = lambda msg, **kw: printed.append(str(msg))
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email_send.console", mock_console)
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email_send.error", lambda msg: None)

        from aipass.ai_mail.apps.modules.email_send import handle_send

        result = handle_send(["@alpha", "@beta", "Group msg", "Hi all"])
        assert result is True
        # Both recipients should have been sent to
        assert "@alpha" in sent_to
        assert "@beta" in sent_to
        assert any("Group send complete" in p for p in printed)


# ===========================================================================
# handle_command dispatch table
# ===========================================================================


class TestHandleCommand:
    """Tests for the top-level handle_command router."""

    def test_unknown_command_returns_false(self):
        """Unknown command returns False."""
        from aipass.ai_mail.apps.modules.email import handle_command

        result = handle_command("nonexistent", [])
        assert result is False

    def test_help_flag_prints_help(self, monkeypatch):
        """--help prints help text and returns True."""
        printed: list[str] = []
        mock_console = MagicMock()
        mock_console.print = lambda msg, **kw: printed.append(str(msg))
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email.console", mock_console)

        from aipass.ai_mail.apps.modules.email import handle_command

        result = handle_command("--help", [])
        assert result is True
        assert any("Email Module" in p for p in printed)

    def test_command_with_help_arg(self, monkeypatch):
        """Any valid command with 'help' as first arg prints help."""
        printed: list[str] = []
        mock_console = MagicMock()
        mock_console.print = lambda msg, **kw: printed.append(str(msg))
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email.console", mock_console)

        from aipass.ai_mail.apps.modules.email import handle_command

        result = handle_command("inbox", ["help"])
        assert result is True
        assert any("Email Module" in p for p in printed)


# ###########################################################################
# NEW COVERAGE TESTS — appended for untested paths in email.py & email_send.py
# ###########################################################################


# ===========================================================================
# _resolve_branch_path RuntimeError fallback (email.py line 67-69)
# ===========================================================================


class TestResolveBranchPath:
    """Tests for _resolve_branch_path fallback behaviour."""

    def test_runtime_error_fallback(self, monkeypatch):
        """When get_current_user raises RuntimeError, falls back to _AI_MAIL_DIR."""
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.get_current_user",
            lambda: (_ for _ in ()).throw(RuntimeError("no branch")),
        )

        from aipass.ai_mail.apps.modules.email import _resolve_branch_path, _AI_MAIL_DIR

        result = _resolve_branch_path()
        assert result == _AI_MAIL_DIR


# ===========================================================================
# handle_inbox additional paths
# ===========================================================================


class TestHandleInboxExtended:
    """Extended tests for handle_inbox edge cases."""

    def test_inbox_nonexistent_file(self, tmp_path, monkeypatch):
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
        printed: list[str] = []
        mock_console = MagicMock()
        mock_console.print = lambda msg, **kw: printed.append(str(msg))
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email.console", mock_console)

        from aipass.ai_mail.apps.modules.email import handle_inbox

        result = handle_inbox([])
        assert result is True
        assert any("empty" in p.lower() for p in printed)

    def test_inbox_with_target_branch_label(self, tmp_path, monkeypatch):
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
        printed: list[str] = []
        mock_console = MagicMock()
        mock_console.print = lambda msg, **kw: printed.append(str(msg))
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email.console", mock_console)

        from aipass.ai_mail.apps.modules.email import handle_inbox

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
        mock_console = MagicMock()
        mock_console.print = lambda msg, **kw: None
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email.console", mock_console)

        from aipass.ai_mail.apps.modules.email import handle_inbox

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
        mock_console = MagicMock()
        mock_console.print = lambda msg, **kw: None
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email.console", mock_console)

        from aipass.ai_mail.apps.modules.email import handle_inbox

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

        from aipass.ai_mail.apps.modules.email import handle_view

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

        from aipass.ai_mail.apps.modules.email import handle_view

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

        from aipass.ai_mail.apps.modules.email import handle_view

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

        from aipass.ai_mail.apps.modules.email import handle_view

        result = handle_view(["latest"])
        assert result is True
        assert any("latest" in e.lower() or "could not" in e.lower() for e in errors)


# ===========================================================================
# handle_close additional paths
# ===========================================================================


class TestHandleCloseExtended:
    """Extended tests for handle_close edge cases."""

    def test_close_batch_mixed_success_failure(self, tmp_path, monkeypatch):
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
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.batch_close_post_ops",
            lambda bp, central_fn, purge_fn: None,
        )
        printed: list[str] = []
        errors: list[str] = []
        mock_console = MagicMock()
        mock_console.print = lambda msg, **kw: printed.append(str(msg))
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email.console", mock_console)
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.error",
            lambda msg: errors.append(msg),
        )

        from aipass.ai_mail.apps.modules.email import handle_close

        result = handle_close(["m1", "m2", "m3"])
        assert result is True
        assert any("Closed m1" in p for p in printed)
        assert any("Not found: m2" in e for e in errors)
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

        from aipass.ai_mail.apps.modules.email import handle_close

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
        printed: list[str] = []
        mock_console = MagicMock()
        mock_console.print = lambda msg, **kw: printed.append(str(msg))
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email.console", mock_console)
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email.error", lambda msg: None)

        from aipass.ai_mail.apps.modules.email import handle_close

        result = handle_close(["m1"])
        assert result is True
        assert len(post_ops_called) == 0


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

        from aipass.ai_mail.apps.modules.email import handle_reply

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

        from aipass.ai_mail.apps.modules.email import handle_sent

        result = handle_sent([])
        assert result is True
        assert any("path error" in e for e in errors)


# ===========================================================================
# print_introspection (email.py lines 361-402)
# ===========================================================================


class TestPrintIntrospection:
    """Tests for email.print_introspection."""

    def test_print_introspection_outputs_module_info(self, monkeypatch):
        """print_introspection outputs module info including handler list."""
        printed: list[str] = []
        mock_console = MagicMock()
        mock_console.print = lambda msg="", **kw: printed.append(str(msg))
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email.console", mock_console)

        from aipass.ai_mail.apps.modules.email import print_introspection

        print_introspection()
        combined = "\n".join(printed)
        assert "email Module" in combined
        assert "Connected Handlers" in combined
        assert "send.py" in combined
        assert "inbox_ops.py" in combined
        assert "json_handler.py" in combined


# ===========================================================================
# email_send.py: _delivery_callback
# ===========================================================================


class TestDeliveryCallback:
    """Tests for email_send._delivery_callback."""

    def test_delivery_callback_calls_on_email_delivered(self, monkeypatch):
        """_delivery_callback delegates to on_email_delivered with only update_central_fn."""
        delivered_args: list[dict] = []

        def mock_on_delivered(update_central_fn=None):
            """Capture on_email_delivered arguments."""
            delivered_args.append({"update_central_fn": update_central_fn})

        monkeypatch.setattr(email_send_mod, "on_email_delivered", mock_on_delivered)

        email_send_mod._delivery_callback("/some/path", 3, 2, 5)
        assert len(delivered_args) == 1


# ===========================================================================
# email_send.py: _get_branch_info_fn
# ===========================================================================


class TestGetBranchInfoFn:
    """Tests for email_send._get_branch_info_fn."""

    def test_get_branch_info_fn_success(self):
        """Returns function on success."""
        from aipass.ai_mail.apps.modules.email_send import _get_branch_info_fn

        result = _get_branch_info_fn()
        assert result is None or callable(result)

    def test_get_branch_info_fn_import_error(self, monkeypatch):
        """Returns None on ImportError."""
        import builtins

        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            """Raise ImportError for branch_detection module."""
            if "branch_detection" in name:
                raise ImportError("no module")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)

        from aipass.ai_mail.apps.modules.email_send import _get_branch_info_fn

        result = _get_branch_info_fn()
        assert result is None


# ===========================================================================
# email_send.py: _send_direct BrokenPipeError & generic exception
# ===========================================================================


class TestSendDirectExtended:
    """Extended tests for email_send._send_direct edge cases."""

    def test_send_direct_broken_pipe(self, monkeypatch):
        """BrokenPipeError is caught and returns True (line 187-189)."""
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email_send.resolve_sender_info",
            lambda fb, rr, amd, gbe, gcu: (_ for _ in ()).throw(BrokenPipeError("stdout closed")),
        )
        mock_console = MagicMock()
        mock_console.print = lambda msg, **kw: None
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email_send.console", mock_console)
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email_send.error", lambda msg: None)

        from aipass.ai_mail.apps.modules.email_send import _send_direct

        result = _send_direct("@target", "Sub", "Msg")
        assert result is True

    def test_send_direct_generic_exception(self, monkeypatch):
        """Generic exception calls dispatch_send_error and returns False."""
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email_send.resolve_sender_info",
            lambda fb, rr, amd, gbe, gcu: (_ for _ in ()).throw(RuntimeError("send boom")),
        )
        dispatched_errors: list[tuple] = []
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email_send.dispatch_send_error",
            lambda to, subj, err_msg, deliver_fn: dispatched_errors.append((to, subj, err_msg)),
        )
        errors: list[str] = []
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email_send.error",
            lambda msg: errors.append(msg),
        )
        mock_console = MagicMock()
        mock_console.print = lambda msg, **kw: None
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email_send.console", mock_console)

        from aipass.ai_mail.apps.modules.email_send import _send_direct

        result = _send_direct("@target", "Sub", "Msg")
        assert result is False
        assert any("send boom" in e for e in errors)
        assert len(dispatched_errors) == 1
        assert dispatched_errors[0][0] == "@target"

    def test_send_direct_broadcast_target(self, monkeypatch):
        """When to_branch is '@all', delegates to _send_broadcast."""
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email_send.resolve_sender_info",
            lambda fb, rr, amd, gbe, gcu: {
                "email_address": "@ai_mail",
                "display_name": "AI_MAIL",
                "mailbox_path": "/tmp/mailbox",
            },
        )
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email_send.get_all_branches",
            lambda: [{"name": "A", "email": "@a"}],
        )
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email_send.send_to_broadcast",
            lambda *a, **kw: (True, 1, 1, [("A", True, None)]),
        )
        printed: list[str] = []
        mock_console = MagicMock()
        mock_console.print = lambda msg, **kw: printed.append(str(msg))
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email_send.console", mock_console)
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email_send.error", lambda msg: None)

        from aipass.ai_mail.apps.modules.email_send import _send_direct

        result = _send_direct("@all", "Hello", "World")
        assert result is True
        assert any("Broadcast" in p or "OK" in p for p in printed)


# ===========================================================================
# email_send.py: _fire_dispatch_trigger exception (line 201-202)
# ===========================================================================


class TestFireDispatchTrigger:
    """Tests for email_send._fire_dispatch_trigger exception handling."""

    def test_fire_dispatch_trigger_exception_logged(self, monkeypatch):
        """Exception in trigger.fire is logged but does not propagate."""
        mock_trigger = MagicMock()
        mock_trigger.fire.side_effect = RuntimeError("trigger broken")
        monkeypatch.setattr(email_send_mod, "trigger", mock_trigger)

        email_send_mod._fire_dispatch_trigger("@target", "Test Subject")
        mock_trigger.fire.assert_called_once_with("email_dispatched", to="@target", subject="Test Subject")


# ===========================================================================
# email_send.py: _send_broadcast happy path & failure path
# ===========================================================================


class TestSendBroadcast:
    """Tests for email_send._send_broadcast."""

    def test_send_broadcast_happy_path(self, monkeypatch):
        """Broadcast sends to all branches and reports success."""
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email_send.get_all_branches",
            lambda: [
                {"name": "A", "email": "@a"},
                {"name": "B", "email": "@b"},
            ],
        )
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email_send.send_to_broadcast",
            lambda *a, **kw: (True, 2, 2, [("A", True, None), ("B", True, None)]),
        )
        printed: list[str] = []
        mock_console = MagicMock()
        mock_console.print = lambda msg, **kw: printed.append(str(msg))
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email_send.console", mock_console)
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email_send.error", lambda msg: None)

        from aipass.ai_mail.apps.modules.email_send import _send_broadcast

        user_info = {
            "email_address": "@ai_mail",
            "display_name": "AI_MAIL",
            "mailbox_path": "/tmp",
        }
        result = _send_broadcast("Subj", "Msg", user_info, False, False, None, None)
        assert result is True
        assert any("Broadcasting" in p for p in printed)
        assert any("2/2" in p for p in printed)

    def test_send_broadcast_failure_path(self, monkeypatch):
        """When send_to_broadcast returns string results (error), prints error."""
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email_send.get_all_branches",
            lambda: [{"name": "A", "email": "@a"}],
        )
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email_send.send_to_broadcast",
            lambda *a, **kw: (False, 0, 1, "load failed"),
        )
        errors: list[str] = []
        mock_console = MagicMock()
        mock_console.print = lambda msg, **kw: None
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email_send.console", mock_console)
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email_send.error",
            lambda msg: errors.append(msg),
        )

        from aipass.ai_mail.apps.modules.email_send import _send_broadcast

        user_info = {
            "email_address": "@ai_mail",
            "display_name": "AI_MAIL",
            "mailbox_path": "/tmp",
        }
        result = _send_broadcast("Subj", "Msg", user_info, False, False, None, None)
        assert result is False
        assert any("Failed to load" in e for e in errors)


# ===========================================================================
# email_send.py: print_introspection
# ===========================================================================


class TestEmailSendIntrospection:
    """Tests for email_send.print_introspection."""

    def test_print_introspection_outputs_module_info(self, monkeypatch):
        """print_introspection prints function list and header."""
        printed: list[str] = []
        mock_console = MagicMock()
        mock_console.print = lambda msg="", **kw: printed.append(str(msg))
        monkeypatch.setattr(email_send_mod, "console", mock_console)

        email_send_mod.print_introspection()
        combined = "\n".join(printed)
        assert "email_send Module" in combined
        assert "handle_send" in combined
        assert "_send_direct" in combined
        assert "_send_broadcast" in combined
        assert "_delivery_callback" in combined


# ===========================================================================
# email_send.py: _send_interactive complete path (user provides input)
# ===========================================================================


class TestSendInteractiveExtended:
    """Extended tests for email_send._send_interactive."""

    def test_send_interactive_without_a_terminal_refuses_before_listing_branches(self, monkeypatch):
        """No TTY: refuse with usage, and do not print a branch list first.

        `drone @ai_mail email` with no args used to reach the prompts through a
        routed subprocess and block until drone's 30s timeout (measured live,
        APLAN-0006). The listing must not print either — output that precedes a
        certain refusal reads as progress toward a send that cannot happen.
        """
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)
        listed: list[str] = []
        monkeypatch.setattr(
            email_send_mod,
            "get_all_branches",
            lambda: listed.append("called") or [{"name": "ALPHA", "email": "@alpha"}],
        )
        errors: list[str] = []
        monkeypatch.setattr(email_send_mod, "error", lambda msg: errors.append(str(msg)))

        result = email_send_mod._send_interactive()

        assert result is False
        assert listed == []
        assert any("terminal" in e for e in errors)

    def test_send_interactive_complete_path(self, monkeypatch):
        """User provides input successfully, send proceeds."""
        # Same reason as test_send_interactive_mode: the no-TTY guard runs first
        # under pytest, so the terminal has to be pinned to reach the send path.
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.setattr(
            email_send_mod,
            "get_all_branches",
            lambda: [{"name": "ALPHA", "email": "@alpha"}],
        )
        monkeypatch.setattr(
            email_send_mod,
            "collect_interactive_input",
            lambda branches: {
                "to": "@alpha",
                "subject": "Hi",
                "message": "Hello there",
            },
        )
        monkeypatch.setattr(
            email_send_mod,
            "resolve_sender_info",
            lambda fb, rr, amd, gbe, gcu: {
                "email_address": "@ai_mail",
                "display_name": "AI_MAIL",
                "mailbox_path": "/tmp/mailbox",
            },
        )
        monkeypatch.setattr(email_send_mod, "send_to_single", lambda *a, **kw: (True, None))
        printed: list[str] = []
        mock_console = MagicMock()
        mock_console.print = lambda msg, **kw: printed.append(str(msg))
        monkeypatch.setattr(email_send_mod, "console", mock_console)
        monkeypatch.setattr(email_send_mod, "error", lambda msg: None)

        result = email_send_mod._send_interactive()
        assert result is True
        assert any("@alpha" in p for p in printed)
        assert any("sent" in p.lower() for p in printed)


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
        mock_console = MagicMock()
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email.console", mock_console)
        _write_inbox(tmp_path)

        from aipass.ai_mail.apps.modules.email import handle_reply

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
        mock_console = MagicMock()
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email.console", mock_console)
        _write_inbox(tmp_path)

        from aipass.ai_mail.apps.modules.email import handle_reply

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

    def _run_inbox(self, monkeypatch, tmp_path, messages):
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
        printed: list[str] = []
        mock_console = MagicMock()
        mock_console.print = lambda msg, **kw: printed.append(str(msg))
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email.console", mock_console)

        from aipass.ai_mail.apps.modules.email import handle_inbox

        assert handle_inbox([]) is True
        return printed

    def test_newest_message_listed_when_store_exceeds_limit(self, monkeypatch, tmp_path):
        """CANARY: the newest arrival must be visible in an over-limit inbox."""
        # Newest first, exactly as delivery.py writes it.
        messages = [{"id": f"m{i:03d}", "subject": f"subject-{i:03d}", "status": "new"} for i in range(25)]
        printed = self._run_inbox(monkeypatch, tmp_path, messages)
        blob = "\n".join(printed)

        assert "subject-000" in blob, "newest message was dropped from the listing"
        assert "subject-019" in blob, "20th-newest message should still list"
        assert "subject-024" not in blob, "oldest message should fall off, not the newest"

    def test_over_limit_listing_says_it_truncated(self, monkeypatch, tmp_path):
        """Truncation is reported as 'most recent of N', not a bare count."""
        messages = [{"id": f"m{i:03d}", "subject": f"subject-{i:03d}", "status": "new"} for i in range(25)]
        printed = self._run_inbox(monkeypatch, tmp_path, messages)
        assert any("20 most recent of 25 messages" in p for p in printed)

    def test_under_limit_lists_every_message_oldest_first(self, monkeypatch, tmp_path):
        """Nothing is dropped under the limit; display order stays oldest-first."""
        messages = [{"id": f"m{i}", "subject": f"subject-{i}", "status": "new"} for i in range(3)]
        printed = self._run_inbox(monkeypatch, tmp_path, messages)
        rows = [p for p in printed if p.strip().startswith(("1.", "2.", "3."))]
        assert [r.strip() for r in rows] == ["1. subject-2", "2. subject-1", "3. subject-0"]
        assert any("Showing 3 of 3 messages" in p for p in printed)

    def test_row_that_fails_to_render_is_shown_raw_not_hidden(self, monkeypatch):
        """CANARY: a row the console rejects degrades visibly instead of vanishing."""
        printed: list[str] = []

        def exploding_print(msg, **kw):
            if kw.get("markup") is False:
                printed.append(str(msg))
                return
            raise ValueError("closing tag '[/rc]' doesn't match any open tag")

        mock_console = MagicMock()
        mock_console.print = exploding_print
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email.console", mock_console)

        from aipass.ai_mail.apps.modules.email import _print_row

        _print_row("1. Subject: RE: [/rc] recovered")

        blob = "\n".join(printed)
        assert "RE: [/rc] recovered" in blob, "unrenderable row vanished instead of degrading"
        assert "RAW" in blob, "degraded row must carry a visible marker"

    def test_unreadable_sent_file_still_gets_a_row(self, monkeypatch, tmp_path):
        """CANARY: a sent file that will not load is listed as a placeholder."""
        sent_folder = tmp_path / ".ai_mail.local" / "sent"
        sent_folder.mkdir(parents=True)
        (sent_folder / "aaaa1111.json").write_text("{}", encoding="utf-8")

        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email._resolve_branch_path",
            lambda: tmp_path,
        )
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.load_email_file",
            lambda f: None,
        )
        printed: list[str] = []
        mock_console = MagicMock()
        mock_console.print = lambda msg, **kw: printed.append(str(msg))
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email.console", mock_console)

        from aipass.ai_mail.apps.modules.email import handle_sent

        assert handle_sent([]) is True
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
        mock_console = MagicMock()
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email.console", mock_console)

        from aipass.ai_mail.apps.modules.email import handle_view

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

    def _view_message(self, monkeypatch, tmp_path, body):
        """Run handle_view over a message with the given body."""
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

        from rich.console import Console

        buffer = io.StringIO()
        real_console = Console(file=buffer, width=200, no_color=True, highlight=False)
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email.console", real_console)

        from aipass.ai_mail.apps.modules.email import handle_view

        assert handle_view(["body0001"]) is True
        return buffer.getvalue()

    def test_body_with_closing_tag_renders_instead_of_raising(self, monkeypatch, tmp_path):
        """CANARY: a body containing [/rc] must render, not abort the view."""
        body = "SHIPPED — [/rc] is live on the control bot. Re-verified this session."
        out = self._view_message(monkeypatch, tmp_path, body)
        assert "[/rc] is live on the control bot" in out

    def test_body_with_style_tag_keeps_its_text(self, monkeypatch, tmp_path):
        """A body containing [dim] renders the tag literally, text intact."""
        body = "Line one [dim]note kept[/dim] and [skills] tag kept."
        out = self._view_message(monkeypatch, tmp_path, body)
        assert "[dim]note kept[/dim]" in out
        assert "[skills] tag kept" in out

    def test_body_renders_with_markup_disabled(self, monkeypatch, tmp_path):
        """The body print explicitly passes markup=False rather than escaping."""
        printed: list[tuple] = []
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email._resolve_branch_path",
            lambda: tmp_path,
        )
        email_data = {
            "id": "body0002",
            "subject": "s",
            "message": "raw [/rc] body",
            "from_name": "X",
            "from": "@x",
            "timestamp": "t",
        }
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.mark_as_opened",
            lambda bp, mid: (True, "Opened", email_data),
        )
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.format_email_header",
            lambda ed: "HEADER",
        )
        mock_console = MagicMock()
        mock_console.print = lambda msg, **kw: printed.append((str(msg), kw))
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email.console", mock_console)

        from aipass.ai_mail.apps.modules.email import handle_view

        assert handle_view(["body0002"]) is True
        body_calls = [(m, kw) for m, kw in printed if "raw [/rc] body" in m]
        assert body_calls, "body was never printed"
        assert body_calls[0][1].get("markup") is False, "body printed as markup — it can raise"
