# =================== AIPass ====================
# Name: test_feedback.py
# Description: Tests for aipass feedback — toggle alias for @hooks feedback pulse
# Version: 1.0.0
# Created: 2026-07-18
# Modified: 2026-07-18
# =============================================

"""Tests for the aipass feedback module."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from aipass.aipass.apps.modules.feedback import handle_command, print_help, print_introspection

_MOD = "aipass.aipass.apps.modules.feedback"


class TestHandleCommand:
    """Command routing for aipass feedback."""

    def test_ignores_other_commands(self) -> None:
        """A non-feedback command is not handled."""
        assert handle_command("doctor", []) is False

    def test_help(self) -> None:
        """--help is handled."""
        assert handle_command("feedback", ["--help"]) is True

    def test_info(self) -> None:
        """--info is handled."""
        assert handle_command("feedback", ["--info"]) is True

    def test_unknown_arg_shows_error(self) -> None:
        """An unknown argument shows an error and help."""
        with patch(f"{_MOD}.error") as mock_err:
            assert handle_command("feedback", ["banana"]) is True
        mock_err.assert_called_once()

    def test_on_delegates_to_hooks(self) -> None:
        """'on' delegates to drone @hooks feedback on."""
        with patch(f"{_MOD}.subprocess.run", return_value=MagicMock(returncode=0)) as run:
            handle_command("feedback", ["on"])
        cmd = run.call_args[0][0]
        assert cmd == ["drone", "@hooks", "feedback", "on"]

    def test_off_delegates_to_hooks(self) -> None:
        """'off' delegates to drone @hooks feedback off."""
        with patch(f"{_MOD}.subprocess.run", return_value=MagicMock(returncode=0)) as run:
            handle_command("feedback", ["off"])
        cmd = run.call_args[0][0]
        assert cmd == ["drone", "@hooks", "feedback", "off"]

    def test_no_args_shows_introspection(self) -> None:
        """No args shows module introspection."""
        with patch(f"{_MOD}.subprocess.run") as run:
            assert handle_command("feedback", []) is True
        run.assert_not_called()

    def test_drone_not_found_refuses_non_zero(self) -> None:
        """An unreachable drone is a refusal: it names the reason and exits non-zero.

        Rewritten 2026-09-07 (FPLAN-0492 wave 6, Patrick's standing ruling that a
        refusal exits non-zero and names its reason). This test previously
        asserted only that warning() was called and nothing raised -- which is
        exactly what PINNED the exit-0 defect: the code computed 1, and
        handle_command discarded it, so a missing drone reported success.
        """
        with (
            patch(f"{_MOD}.subprocess.run", side_effect=FileNotFoundError("drone")),
            patch(f"{_MOD}.error") as err,
        ):
            with pytest.raises(SystemExit) as exc:
                handle_command("feedback", ["on"])

        assert exc.value.code == 1
        err.assert_called_once()
        assert "drone not found" in err.call_args[0][0]

    def test_hooks_timeout_refuses_non_zero(self) -> None:
        """A timed-out delegate is a refusal too, on the same seam."""
        with (
            patch(
                f"{_MOD}.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="drone", timeout=1),
            ),
            patch(f"{_MOD}.error") as err,
        ):
            with pytest.raises(SystemExit) as exc:
                handle_command("feedback", ["on"])

        assert exc.value.code == 1
        err.assert_called_once()

    def test_hooks_own_non_zero_is_propagated(self) -> None:
        """A non-zero from @hooks itself reaches the caller, not just our two raises."""
        with patch(f"{_MOD}.subprocess.run", return_value=MagicMock(returncode=3)):
            with pytest.raises(SystemExit) as exc:
                handle_command("feedback", ["on"])

        assert exc.value.code == 3

    def test_success_does_not_raise(self) -> None:
        """The counterfactual: a clean run still returns True and exits 0."""
        with patch(f"{_MOD}.subprocess.run", return_value=MagicMock(returncode=0)):
            assert handle_command("feedback", ["on"]) is True


class TestSmoke:
    """Help/introspection render without error."""

    def test_print_help_runs(self) -> None:
        print_help()

    def test_print_introspection_runs(self) -> None:
        print_introspection()
