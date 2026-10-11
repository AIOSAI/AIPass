# =================== AIPass ====================
# Name: test_email_module_send.py
# Description: Tests for email_send.py's send lane and email.py's command routing
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Tests for apps/modules/email_send.py's handle_send and the routing of apps/modules/email.py."""

# Covers: handle_send and its lanes (direct, group, broadcast, interactive,
# dispatch) in email_send.py, and handle_command, the caller-path resolution
# and print_introspection in email.py.
#
# All handler dependencies are mocked -- these tests verify orchestration
# logic, not business logic.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that print_help, caller_refusal and resolve_broadcast_targets parse and import
# seedgo: no-test-needed(shared) — handle_inbox() and the other reading handlers: tests/test_email_module.py

import pytest
from unittest.mock import MagicMock

from aipass.ai_mail.apps.modules import email_send as email_send_mod
from aipass.ai_mail.apps.modules.email import (
    handle_command,
    print_introspection,
)
from aipass.ai_mail.apps.modules.email_send import (
    handle_send,
)
from aipass.ai_mail.tests.support_email_module import _StdoutLines

pytestmark = pytest.mark.usefixtures("email_modules_pinned", "email_json_silenced")


# ===========================================================================
# handle_send (from email_send.py)
# ===========================================================================


class TestHandleSend:
    """Tests for email_send.handle_send orchestrator."""

    def test_send_direct_single_recipient(self, monkeypatch, tmp_path, capsys: pytest.CaptureFixture[str]):
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
            "aipass.ai_mail.apps.modules.email_send.resolve_sender_info",
            lambda fb, rr, amd, gbe, gcu: {
                "email_address": "@ai_mail",
                "display_name": "AI_MAIL",
                "mailbox_path": str(tmp_path / "mailbox"),
            },
        )
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email_send.send_to_single",
            lambda *a, **kw: (True, None),
        )
        printed = _StdoutLines(capsys)
        error_mock = MagicMock()
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email_send.error", error_mock)

        result = handle_send(["@target", "Hello", "World"])
        assert result is True
        assert any("sent" in p.lower() and "@target" in p for p in printed)
        error_mock.assert_not_called()

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

        result = handle_send(["bad", "args"])
        assert result is True
        assert any("Usage" in e for e in errors)

    def test_send_delivery_failure(self, monkeypatch, tmp_path):
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
            "aipass.ai_mail.apps.modules.email_send.resolve_sender_info",
            lambda fb, rr, amd, gbe, gcu: {
                "email_address": "@ai_mail",
                "display_name": "AI_MAIL",
                "mailbox_path": str(tmp_path / "mailbox"),
            },
        )
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email_send.send_to_single",
            lambda *a, **kw: (False, "Branch not found"),
        )
        # dispatch_send_error delivers a real error mail, so it stays patched and is asserted (ai_mail, leg 6)
        send_error = MagicMock()
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email_send.dispatch_send_error", send_error)
        errors: list[str] = []
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email_send.error",
            lambda msg: errors.append(msg),
        )

        result = handle_send(["@target", "Sub", "Msg"])
        assert result is True
        assert any("Branch not found" in e for e in errors)
        send_error.assert_called_once()
        assert send_error.call_args.args[:3] == ("@target", "Sub", "Branch not found")

    def test_send_interactive_mode(self, monkeypatch, capsys: pytest.CaptureFixture[str]):
        """A cancelled interactive send is still a handled command."""
        # pytest's stdin is not a terminal, so without this the no-TTY guard
        # answers first and this test would pass while never reaching the
        # cancel path it is named for.
        tty = MagicMock(return_value=True)
        monkeypatch.setattr("sys.stdin.isatty", tty)
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email_send.parse_send_args",
            lambda args: {"mode": "interactive"},
        )
        # _send_interactive calls get_all_branches and collect_interactive_input
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email_send.get_all_branches",
            lambda: [{"name": "A", "email": "@a"}],
        )
        # The prompt reads the real stdin; the stub answers as a cancelling user and is asserted
        collect = MagicMock(return_value=None)
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email_send.collect_interactive_input", collect)
        printed = _StdoutLines(capsys)

        result = handle_send([])
        assert result is True
        assert any("Cancelled" in p for p in printed)
        tty.assert_called_once_with()
        collect.assert_called_once_with([{"name": "A", "email": "@a"}])

    def test_send_dispatch_fires_trigger(self, monkeypatch, tmp_path):
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
                "mailbox_path": str(tmp_path / "mailbox"),
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

        error_mock = MagicMock()
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email_send.error", error_mock)

        result = handle_send(["@target", "Dispatch Task", "Do the thing", "--dispatch"])
        assert result is True
        assert len(trigger_calls) == 1
        assert trigger_calls[0][0] == "email_dispatched"
        assert trigger_calls[0][1]["to"] == "@target"
        error_mock.assert_not_called()

    def test_send_group_multiple_recipients(self, monkeypatch, tmp_path, capsys: pytest.CaptureFixture[str]):
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
            "aipass.ai_mail.apps.modules.email_send.resolve_sender_info",
            lambda fb, rr, amd, gbe, gcu: {
                "email_address": "@ai_mail",
                "display_name": "AI_MAIL",
                "mailbox_path": str(tmp_path / "mailbox"),
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
        printed = _StdoutLines(capsys)
        error_mock = MagicMock()
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email_send.error", error_mock)

        result = handle_send(["@alpha", "@beta", "Group msg", "Hi all"])
        assert result is True
        # Both recipients should have been sent to
        assert "@alpha" in sent_to
        assert "@beta" in sent_to
        assert any("Group send complete" in p for p in printed)
        error_mock.assert_not_called()


# ===========================================================================
# handle_command dispatch table
# ===========================================================================


class TestHandleCommand:
    """Tests for the top-level handle_command router."""

    def test_unknown_command_returns_false(self):
        """Unknown command returns False."""
        result = handle_command("nonexistent", [])
        assert result is False

    def test_help_flag_prints_help(self, monkeypatch, capsys: pytest.CaptureFixture[str]):
        """--help prints help text and returns True."""
        printed = _StdoutLines(capsys)

        result = handle_command("--help", [])
        assert result is True
        assert any("Email Module" in p for p in printed)

    def test_command_with_help_arg(self, monkeypatch, capsys: pytest.CaptureFixture[str]):
        """Any valid command with 'help' as first arg prints help."""
        printed = _StdoutLines(capsys)

        result = handle_command("inbox", ["help"])
        assert result is True
        assert any("Email Module" in p for p in printed)


# ###########################################################################
# NEW COVERAGE TESTS — appended for untested paths in email.py & email_send.py
# ###########################################################################


# ===========================================================================
# _resolve_branch_path — identity propagates, never substitutes
# ===========================================================================


class TestResolveBranchPath:
    """Tests for _resolve_branch_path identity behaviour."""

    def test_runtime_error_propagates_no_substitution(self, monkeypatch, capsys: pytest.CaptureFixture[str]):
        """POLICY CHANGE 2026-08-21: an unresolvable caller no longer collapses to
        _AI_MAIL_DIR. That substitution pointed view/close/reply at @ai_mail's own
        mailbox, so a caller standing outside any branch read and archived another
        citizen's mail with no signal (the owner's ruling via @devpulse, 096c9a42).

        Reached through the `sent` command (ai_mail, leg 14): the identity error is
        the answer, and no mailbox, @ai_mail's included, is listed in its place."""
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.get_current_user",
            lambda: (_ for _ in ()).throw(RuntimeError("no branch")),
        )
        errors: list[str] = []
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email.error", errors.append)
        printed = _StdoutLines(capsys)

        assert handle_command("sent", []) is True
        assert errors == ["Error: no branch"]
        assert not any("sent messages" in p.lower() for p in printed)


# ===========================================================================
# print_introspection (email.py lines 361-402)
# ===========================================================================


class TestPrintIntrospection:
    """Tests for email.print_introspection."""

    def test_print_introspection_outputs_module_info(self, monkeypatch, capsys: pytest.CaptureFixture[str]):
        """print_introspection outputs module info including handler list."""
        printed = _StdoutLines(capsys)

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


def _no_error_dispatch(monkeypatch):
    """Fail the test, past send's `except Exception`, if a send reaches the error report.

    pytest.fail raises a BaseException, so the product's broad catch cannot swallow it.
    """
    monkeypatch.setattr(
        email_send_mod,
        "dispatch_send_error",
        lambda *a: pytest.fail(f"a send failed and reached the error report: {a!r}"),
    )


def _stub_single_send(monkeypatch, tmp_path, on_send=None):
    """Stub the sender, the dispatch target and the one-recipient send under handle_send.

    `on_send` sees the positional args send_to_single was handed; the send answers success.
    """
    monkeypatch.setattr(
        email_send_mod,
        "resolve_sender_info",
        lambda *a: {"email_address": "@ai_mail", "display_name": "AI_MAIL", "mailbox_path": str(tmp_path)},
    )
    monkeypatch.setattr(email_send_mod, "resolve_dispatch_target", lambda recipient, auto, info: recipient)
    # A failed send must stop here, never reach the real error report to @drone (ai_mail, leg 14).
    _no_error_dispatch(monkeypatch)

    def _send(*a, **kw):
        if on_send is not None:
            on_send(a)
        return True, None

    monkeypatch.setattr(email_send_mod, "send_to_single", _send)


class TestDeliveryCallback:
    """Tests for email_send._delivery_callback."""

    def test_delivery_callback_calls_on_email_delivered(self, monkeypatch, tmp_path):
        """_delivery_callback delegates to on_email_delivered with only update_central_fn."""
        delivered_args: list[dict] = []

        def mock_on_delivered(update_central_fn=None):
            """Capture on_email_delivered arguments."""
            delivered_args.append({"update_central_fn": update_central_fn})

        monkeypatch.setattr(email_send_mod, "on_email_delivered", mock_on_delivered)
        _stub_single_send(monkeypatch, tmp_path, on_send=lambda a: a[11](str(tmp_path), 3, 2, 5))

        # The callback is the one `send` hands the delivery (ai_mail, leg 14).
        assert handle_send(["@target", "Sub", "Msg"]) is True
        assert delivered_args == [{"update_central_fn": email_send_mod.update_central}]


# ===========================================================================
# email_send.py: _get_branch_info_fn
# ===========================================================================


class TestGetBranchInfoFn:
    """Tests for email_send._get_branch_info_fn."""

    def _lookup_handed_over(self, monkeypatch, tmp_path):
        """The branch-info lookup `send` hands dispatch-target resolution (ai_mail, leg 14)."""
        _stub_single_send(monkeypatch, tmp_path)
        handed: list = []
        monkeypatch.setattr(email_send_mod, "resolve_dispatch_target", lambda r, auto, info: handed.append(info) or r)
        assert handle_send(["@target", "Sub", "Msg"]) is True
        assert len(handed) == 1
        return handed[0]

    def test_get_branch_info_fn_success(self, monkeypatch, tmp_path):
        """Returns function on success."""
        result = self._lookup_handed_over(monkeypatch, tmp_path)
        # MEASURED 2026-09-08: the import succeeds here and a real function comes
        # back, so ``result is None`` never held — the ``or`` let the failure
        # this unit is named for pass as success.
        assert callable(result)
        assert result.__name__ == "get_branch_info_from_registry"

    def test_get_branch_info_fn_import_error(self, monkeypatch, tmp_path):
        """Returns None on ImportError."""
        import builtins

        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            """Raise ImportError for branch_detection module."""
            if "branch_detection" in name:
                raise ImportError("no module")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)

        result = self._lookup_handed_over(monkeypatch, tmp_path)
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
        error_mock = MagicMock()
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email_send.error", error_mock)
        _no_error_dispatch(monkeypatch)

        result = handle_send(["@target", "Sub", "Msg"])  # through the command (ai_mail, leg 14)
        assert result is True
        # A closed stdout is not a failed send: nothing is reported as an error
        error_mock.assert_not_called()

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

        result = handle_send(["@target", "Sub", "Msg"])  # through the command (ai_mail, leg 14)
        assert result is True  # recognised; the failure is what was reported
        assert errors == ["Error: send boom"]
        assert len(dispatched_errors) == 1
        assert dispatched_errors[0][0] == "@target"

    def test_send_direct_broadcast_target(self, monkeypatch, tmp_path, capsys: pytest.CaptureFixture[str]):
        """When to_branch is '@all', delegates to _send_broadcast."""
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email_send.resolve_sender_info",
            lambda fb, rr, amd, gbe, gcu: {
                "email_address": "@ai_mail",
                "display_name": "AI_MAIL",
                "mailbox_path": str(tmp_path / "mailbox"),
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
        printed = _StdoutLines(capsys)
        error_mock = MagicMock()
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email_send.error", error_mock)

        result = handle_send(["@all", "Hello", "World"])  # through the command (ai_mail, leg 14)
        assert result is True
        assert any("Broadcast" in p or "OK" in p for p in printed)
        error_mock.assert_not_called()


# ===========================================================================
# email_send.py: _fire_dispatch_trigger exception (line 201-202)
# ===========================================================================


class TestFireDispatchTrigger:
    """Tests for email_send._fire_dispatch_trigger exception handling."""

    def test_fire_dispatch_trigger_exception_logged(self, monkeypatch, tmp_path):
        """Exception in trigger.fire is logged but does not propagate: `send --dispatch` still answers.

        Reached through handle_send, not the helper (ai_mail, leg 14).
        """
        mock_trigger = MagicMock()
        mock_trigger.fire.side_effect = RuntimeError("trigger broken")
        monkeypatch.setattr(email_send_mod, "trigger", mock_trigger)
        log = MagicMock()
        monkeypatch.setattr(email_send_mod, "logger", log)
        _stub_single_send(monkeypatch, tmp_path)

        assert handle_send(["@target", "Test Subject", "Body", "--dispatch"]) is True
        mock_trigger.fire.assert_called_once_with("email_dispatched", to="@target", subject="Test Subject")
        assert log.warning.call_args.args[0] == "[email_send] trigger fire for email_dispatched failed: %s"


# ===========================================================================
# email_send.py: _send_broadcast happy path & failure path
# ===========================================================================


class TestSendBroadcast:
    """Tests for email_send._send_broadcast."""

    def test_send_broadcast_happy_path(self, monkeypatch, tmp_path, capsys: pytest.CaptureFixture[str]):
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
        printed = _StdoutLines(capsys)
        error_mock = MagicMock()
        monkeypatch.setattr("aipass.ai_mail.apps.modules.email_send.error", error_mock)

        user_info = {
            "email_address": "@ai_mail",
            "display_name": "AI_MAIL",
            "mailbox_path": str(tmp_path),
        }
        monkeypatch.setattr(email_send_mod, "resolve_sender_info", lambda *a: user_info)
        result = handle_send(["@all", "Subj", "Msg"])  # the broadcast, through the command (ai_mail, leg 14)
        assert result is True
        assert any("Broadcasting" in p for p in printed)
        assert any("2/2" in p for p in printed)
        error_mock.assert_not_called()

    def test_send_broadcast_failure_path(self, monkeypatch, tmp_path):
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
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email_send.error",
            lambda msg: errors.append(msg),
        )

        user_info = {
            "email_address": "@ai_mail",
            "display_name": "AI_MAIL",
            "mailbox_path": str(tmp_path),
        }
        monkeypatch.setattr(email_send_mod, "resolve_sender_info", lambda *a: user_info)
        result = handle_send(["@all", "Subj", "Msg"])  # the broadcast, through the command (ai_mail, leg 14)
        assert result is True  # recognised; the failure is what was reported
        assert errors == ["Failed to load email file for broadcast"]


# ===========================================================================
# email_send.py: print_introspection
# ===========================================================================


class TestEmailSendIntrospection:
    """Tests for email_send.print_introspection."""

    def test_print_introspection_outputs_module_info(self, monkeypatch, capsys: pytest.CaptureFixture[str]):
        """print_introspection prints function list and header."""
        printed = _StdoutLines(capsys)

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
        tty = MagicMock(return_value=False)
        monkeypatch.setattr("sys.stdin.isatty", tty)
        listed: list[str] = []
        monkeypatch.setattr(
            email_send_mod,
            "get_all_branches",
            lambda: listed.append("called") or [{"name": "ALPHA", "email": "@alpha"}],
        )
        errors: list[str] = []
        monkeypatch.setattr(email_send_mod, "error", lambda msg: errors.append(str(msg)))

        # `email` with no arguments is the interactive send (ai_mail, leg 14); the
        # command was recognised, and the refusal is what was said.
        result = handle_send([])

        assert result is True
        assert listed == []
        assert any("terminal" in e for e in errors)
        tty.assert_called_once_with()

    def test_send_interactive_complete_path(self, monkeypatch, tmp_path, capsys: pytest.CaptureFixture[str]):
        """User provides input successfully, send proceeds."""
        # Same reason as test_send_interactive_mode: the no-TTY guard runs first
        # under pytest, so the terminal has to be pinned to reach the send path.
        tty = MagicMock(return_value=True)
        monkeypatch.setattr("sys.stdin.isatty", tty)
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
                "mailbox_path": str(tmp_path / "mailbox"),
            },
        )
        sent_to: list[str] = []
        monkeypatch.setattr(email_send_mod, "send_to_single", lambda *a, **kw: sent_to.append(a[0]) or (True, None))
        printed = _StdoutLines(capsys)
        error_mock = MagicMock()
        monkeypatch.setattr(email_send_mod, "error", error_mock)

        result = handle_send([])  # the interactive send, through the command (ai_mail, leg 14)
        assert result is True
        assert sent_to == ["@alpha"]
        assert any("@alpha" in p for p in printed)
        assert any("sent" in p.lower() for p in printed)
        tty.assert_called_once_with()
        error_mock.assert_not_called()
