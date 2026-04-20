"""Tests for FPLAN-0190 Task B: manual wake blocklist."""

import inspect
from unittest.mock import MagicMock, patch


class TestIsWakeBlocked:
    def test_devpulse_with_at_is_blocked(self):
        from aipass.ai_mail.apps.handlers.dispatch.wake import is_wake_blocked

        assert is_wake_blocked("@devpulse") is True

    def test_devpulse_bare_is_blocked(self):
        from aipass.ai_mail.apps.handlers.dispatch.wake import is_wake_blocked

        assert is_wake_blocked("devpulse") is True

    def test_devpulse_uppercase_is_blocked(self):
        from aipass.ai_mail.apps.handlers.dispatch.wake import is_wake_blocked

        assert is_wake_blocked("@DEVPULSE") is True

    def test_drone_is_not_blocked(self):
        from aipass.ai_mail.apps.handlers.dispatch.wake import is_wake_blocked

        assert is_wake_blocked("@drone") is False

    def test_ai_mail_is_not_blocked(self):
        from aipass.ai_mail.apps.handlers.dispatch.wake import is_wake_blocked

        assert is_wake_blocked("@ai_mail") is False

    def test_blocklist_is_frozenset(self):
        from aipass.ai_mail.apps.handlers.dispatch.wake import WAKE_BLOCKLIST

        assert isinstance(WAKE_BLOCKLIST, frozenset)

    def test_devpulse_in_blocklist(self):
        from aipass.ai_mail.apps.handlers.dispatch.wake import WAKE_BLOCKLIST

        assert "@devpulse" in WAKE_BLOCKLIST


class TestOrchestrateWakeBlocklist:
    """Tests that _orchestrate_wake enforces the blocklist."""

    def _call_orchestrate_wake(self, args):
        from aipass.ai_mail.apps.modules import dispatch as dispatch_mod

        status_mock = MagicMock()
        status_mock.format.return_value = ""
        wake_return = (status_mock, True)

        # wake_branch is lazily imported inside _orchestrate_wake, so patch it
        # at the handler module where it is defined (the lazy import resolves there).
        with (
            patch(
                "aipass.ai_mail.apps.handlers.dispatch.wake.wake_branch",
                return_value=wake_return,
            ),
            patch("aipass.ai_mail.apps.modules.dispatch.console") as mock_console,
            patch("aipass.ai_mail.apps.modules.dispatch.error") as mock_error,
        ):
            result = dispatch_mod._orchestrate_wake(args)
            return result, mock_error, mock_console

    def test_blocked_returns_true(self):
        result, mock_error, _ = self._call_orchestrate_wake(["@devpulse"])
        assert result is True

    def test_blocked_calls_error(self):
        result, mock_error, _ = self._call_orchestrate_wake(["@devpulse"])
        mock_error.assert_called_once()
        msg = mock_error.call_args[0][0]
        assert "protected" in msg
        assert "dispatch" in msg

    def test_allowed_target_does_not_error(self):
        result, mock_error, _ = self._call_orchestrate_wake(["@drone"])
        mock_error.assert_not_called()

    def test_fresh_flag_still_blocked(self):
        result, mock_error, _ = self._call_orchestrate_wake(["@devpulse", "--fresh"])
        assert result is True
        mock_error.assert_called_once()

    def test_dispatch_send_does_not_check_blocklist(self):
        from aipass.ai_mail.apps.modules import dispatch as dispatch_mod

        src = inspect.getsource(dispatch_mod._orchestrate_dispatch_send)
        assert "is_wake_blocked" not in src
