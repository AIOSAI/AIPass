# =================== AIPass ====================
# Name: test_wake_blocklist.py
# Description: Tests for FPLAN-0190 Task B — manual wake blocklist
# Version: 1.0.2
# Created: 2026-04-20
# Modified: 2026-10-23
# =============================================

"""Tests for apps/handlers/dispatch/wake.py -- manual wake blocklist (FPLAN-0190 Task B)."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — DAEMON_SESSION_PREFIX, unrelated to the blocklist

from contextlib import ExitStack
from unittest.mock import MagicMock, patch

from aipass.ai_mail.apps.handlers.dispatch.wake import WAKE_BLOCKLIST, is_wake_blocked
from aipass.ai_mail.apps.modules import dispatch as dispatch_mod

_H = "aipass.ai_mail.apps.handlers"
# The dispatch send half runs through email_send._send_direct, which binds these names at import.
_ES = "aipass.ai_mail.apps.modules.email_send"


def _send_defaults() -> dict:
    """The send patch set test_dispatch_module uses: nothing is mailed, written, woken or fired."""
    return {
        f"{_H}.email.send.resolve_sender_info": MagicMock(return_value={"email_address": "@ai_mail"}),
        f"{_ES}.prepend_dispatch_header": MagicMock(return_value="[DISPATCH] Body"),
        f"{_ES}.send_to_single": MagicMock(return_value=(True, None)),
        f"{_ES}.on_email_delivered": MagicMock(),
        f"{_H}.users.user.get_current_user": MagicMock(return_value={"name": "test"}),
        f"{_H}.registry.read.get_branch_by_email": MagicMock(return_value={"email": "@target"}),
        f"{_ES}.update_central": MagicMock(),
        f"{_ES}.create_email_file": MagicMock(),
        f"{_ES}.load_email_file": MagicMock(),
        f"{_ES}.deliver_email_to_branch": MagicMock(),
        f"{_ES}.dispatch_send_error": MagicMock(),
        f"{_ES}.trigger": MagicMock(),
    }


class TestIsWakeBlocked:
    """Unit tests for is_wake_blocked() and WAKE_BLOCKLIST constant."""

    def test_devpulse_with_at_is_blocked(self):
        """@devpulse with @ prefix is on the blocklist."""
        assert is_wake_blocked("@devpulse") is True

    def test_devpulse_bare_is_blocked(self):
        """devpulse without @ prefix is normalized and blocked."""
        assert is_wake_blocked("devpulse") is True

    def test_devpulse_uppercase_is_blocked(self):
        """Case-insensitive: @DEVPULSE is blocked."""
        assert is_wake_blocked("@DEVPULSE") is True

    def test_drone_is_not_blocked(self):
        """@drone is not on the blocklist."""
        assert is_wake_blocked("@drone") is False

    def test_ai_mail_is_not_blocked(self):
        """@ai_mail is not on the blocklist."""
        assert is_wake_blocked("@ai_mail") is False

    def test_blocklist_is_frozenset(self):
        """WAKE_BLOCKLIST is a frozenset, and these are the addresses in it.

        Widening the blocked set is a decision that should have to edit this line.
        """
        assert isinstance(WAKE_BLOCKLIST, frozenset)
        assert WAKE_BLOCKLIST == frozenset({"@devpulse"}), sorted(WAKE_BLOCKLIST)

    def test_devpulse_in_blocklist(self):
        """@devpulse is present in WAKE_BLOCKLIST."""
        assert "@devpulse" in WAKE_BLOCKLIST


class TestOrchestrateWakeBlocklist:
    """Tests that _orchestrate_wake enforces the blocklist."""

    def _call_orchestrate_wake(self, args):
        """Run `dispatch wake <args>` through handle_command with mocked wake_branch and console."""
        # wake_branch is imported lazily inside _orchestrate_wake: patch it at the source module.
        status_mock = MagicMock()
        status_mock.format.return_value = ""
        wake_return = (status_mock, True)

        with (
            patch(
                "aipass.ai_mail.apps.handlers.dispatch.wake.wake_branch",
                return_value=wake_return,
            ),
            patch("aipass.ai_mail.apps.modules.dispatch.error") as mock_error,
        ):
            result = dispatch_mod.handle_command("dispatch", ["wake", *args])
            return result, mock_error

    def test_blocked_returns_true(self):
        """Blocked wake returns True — command was recognized, just refused."""
        result, _ = self._call_orchestrate_wake(["@devpulse"])
        assert result is True

    def test_blocked_calls_error(self):
        """Blocked wake prints a directive error naming the target and the dispatch route."""
        result, mock_error = self._call_orchestrate_wake(["@devpulse"])
        mock_error.assert_called_once_with(
            "target @devpulse is protected from manual wake. "
            'Use \'drone @ai_mail dispatch @devpulse "Subject" "Body"\' to send work instead.'
        )

    def test_allowed_target_does_not_error(self):
        """Non-blocked target proceeds without an error message."""
        result, mock_error = self._call_orchestrate_wake(["@drone"])
        mock_error.assert_not_called()

    def test_fresh_flag_still_blocked(self):
        """--fresh flag does not bypass the blocklist."""
        result, mock_error = self._call_orchestrate_wake(["@devpulse", "--fresh"])
        assert result is True
        mock_error.assert_called_once()

    def test_dispatch_send_does_not_check_blocklist(self):
        """`dispatch @devpulse` sends and wakes without asking the blocklist (internal path)."""
        blocked = MagicMock(return_value=True)
        status_mock = MagicMock()
        status_mock.format.return_value = ""
        wake = MagicMock(return_value=(status_mock, True))
        overrides = {
            "aipass.ai_mail.apps.handlers.dispatch.wake.is_wake_blocked": blocked,
            "aipass.ai_mail.apps.handlers.dispatch.wake.wake_branch": wake,
        }
        with ExitStack() as stack:
            for target, mock_obj in {**_send_defaults(), **overrides}.items():
                stack.enter_context(patch(target, mock_obj))
            assert dispatch_mod.handle_command("dispatch", ["@devpulse", "Subject", "Body"]) is True
        blocked.assert_not_called()
        assert wake.call_args.args == ("@devpulse",)
