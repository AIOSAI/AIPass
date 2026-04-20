# =================== AIPass ====================
# Name: test_wake_blocklist.py
# Description: Tests for FPLAN-0190 Task B — manual wake blocklist
# Version: 1.0.0
# Created: 2026-04-20
# Modified: 2026-04-20
# =============================================

"""Tests for manual wake blocklist (FPLAN-0190 Task B)."""

import inspect
from unittest.mock import MagicMock, patch

import pytest


class TestIsWakeBlocked:
    """Unit tests for is_wake_blocked() and WAKE_BLOCKLIST constant."""

    def test_devpulse_with_at_is_blocked(self):
        """@devpulse with @ prefix is on the blocklist."""
        from aipass.ai_mail.apps.handlers.dispatch.wake import is_wake_blocked

        assert is_wake_blocked("@devpulse") is True

    def test_devpulse_bare_is_blocked(self):
        """devpulse without @ prefix is normalized and blocked."""
        from aipass.ai_mail.apps.handlers.dispatch.wake import is_wake_blocked

        assert is_wake_blocked("devpulse") is True

    def test_devpulse_uppercase_is_blocked(self):
        """Case-insensitive: @DEVPULSE is blocked."""
        from aipass.ai_mail.apps.handlers.dispatch.wake import is_wake_blocked

        assert is_wake_blocked("@DEVPULSE") is True

    def test_drone_is_not_blocked(self):
        """@drone is not on the blocklist."""
        from aipass.ai_mail.apps.handlers.dispatch.wake import is_wake_blocked

        assert is_wake_blocked("@drone") is False

    def test_ai_mail_is_not_blocked(self):
        """@ai_mail is not on the blocklist."""
        from aipass.ai_mail.apps.handlers.dispatch.wake import is_wake_blocked

        assert is_wake_blocked("@ai_mail") is False

    def test_blocklist_is_frozenset(self):
        """WAKE_BLOCKLIST is a frozenset (immutable, extensible by code change)."""
        from aipass.ai_mail.apps.handlers.dispatch.wake import WAKE_BLOCKLIST

        assert isinstance(WAKE_BLOCKLIST, frozenset)

    def test_devpulse_in_blocklist(self):
        """@devpulse is present in WAKE_BLOCKLIST."""
        from aipass.ai_mail.apps.handlers.dispatch.wake import WAKE_BLOCKLIST

        assert "@devpulse" in WAKE_BLOCKLIST


class TestOrchestrateWakeBlocklist:
    """Tests that _orchestrate_wake enforces the blocklist."""

    def _call_orchestrate_wake(self, args):
        """Call _orchestrate_wake with mocked wake_branch and console.

        wake_branch is lazily imported inside _orchestrate_wake, so we patch it
        at the source module rather than as a dispatch module attribute.
        """
        from aipass.ai_mail.apps.modules import dispatch as dispatch_mod

        status_mock = MagicMock()
        status_mock.format.return_value = ""
        wake_return = (status_mock, True)

        with (
            patch(
                "aipass.ai_mail.apps.handlers.dispatch.wake.wake_branch",
                return_value=wake_return,
            ),
            patch("aipass.ai_mail.apps.modules.dispatch.console"),
            patch("aipass.ai_mail.apps.modules.dispatch.error") as mock_error,
        ):
            result = dispatch_mod._orchestrate_wake(args)
            return result, mock_error

    def test_blocked_returns_true(self):
        """Blocked wake returns True — command was recognized, just refused."""
        result, _ = self._call_orchestrate_wake(["@devpulse"])
        assert result is True

    def test_blocked_calls_error(self):
        """Blocked wake prints a directive error mentioning 'protected' and 'dispatch'."""
        result, mock_error = self._call_orchestrate_wake(["@devpulse"])
        mock_error.assert_called_once()
        msg = mock_error.call_args[0][0]
        assert "protected" in msg
        assert "dispatch" in msg

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
        from aipass.ai_mail.apps.modules import dispatch as dispatch_mod

        src = inspect.getsource(dispatch_mod._orchestrate_dispatch_send)
        assert "is_wake_blocked" not in src
