# =================== AIPass ====================
# Name: test_wake_blocklist.py
# Description: Tests for FPLAN-0190 Task B — manual wake blocklist
# Version: 1.0.1
# Created: 2026-04-20
# Modified: 2026-09-29
# =============================================

"""Tests for apps/handlers/dispatch/wake.py -- manual wake blocklist (FPLAN-0190 Task B)."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — DAEMON_SESSION_PREFIX, unrelated to the blocklist

import inspect
from unittest.mock import MagicMock, patch

from aipass.ai_mail.apps.handlers.dispatch.wake import WAKE_BLOCKLIST, is_wake_blocked
from aipass.ai_mail.apps.modules import dispatch as dispatch_mod


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

        ``isinstance`` alone said nothing about WHO is blocked — an empty
        frozenset passed it, and so did one that had quietly grown to cover half
        the fleet. The membership is the thing worth knowing: exactly one
        address is blocked from being woken, measured 2026-09-08, and widening
        that set is a decision that should have to edit this line.
        """
        assert isinstance(WAKE_BLOCKLIST, frozenset)
        assert WAKE_BLOCKLIST == frozenset({"@devpulse"}), sorted(WAKE_BLOCKLIST)

    def test_devpulse_in_blocklist(self):
        """@devpulse is present in WAKE_BLOCKLIST."""
        assert "@devpulse" in WAKE_BLOCKLIST


class TestOrchestrateWakeBlocklist:
    """Tests that _orchestrate_wake enforces the blocklist."""

    def _call_orchestrate_wake(self, args):
        """Call _orchestrate_wake with mocked wake_branch and console.

        wake_branch is lazily imported inside _orchestrate_wake, so we patch it
        at the source module rather than as a dispatch module attribute.
        """
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
            result = dispatch_mod._orchestrate_wake(args)
            return result, mock_error

    def test_blocked_returns_true(self):
        """Blocked wake returns True — command was recognized, just refused."""
        result, _ = self._call_orchestrate_wake(["@devpulse"])
        assert result is True

    def test_blocked_calls_error(self):
        """Blocked wake prints a directive error naming the target and the dispatch route.

        The whole message is pinned, so the target and the command it hands back are
        read in place. Killed by the mutant that drops the target from the dispatch
        command (leg 5).
        """
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
        """_orchestrate_dispatch_send must not call is_wake_blocked (internal path)."""
        src = inspect.getsource(dispatch_mod._orchestrate_dispatch_send)
        assert "is_wake_blocked" not in src
