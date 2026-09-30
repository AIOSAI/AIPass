# =================== AIPass ====================
# Name: test_feedback.py
# Description: Tests for aipass feedback — toggle alias for @hooks feedback pulse
# Version: 1.1.3
# Created: 2026-07-18
# Modified: 2026-09-27
# =============================================

"""Tests for apps/modules/feedback.py and the feedback toggle command it drives."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that every module this file imports parses and imports

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

    def test_help(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Mutant: help branch skips print_help -> red."""
        assert handle_command("feedback", ["--help"]) is True
        out, _err = capsys.readouterr()
        assert "toggle the feedback reminder" in out

    def test_info(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Mutant: --info branch skips print_introspection -> red."""
        assert handle_command("feedback", ["--info"]) is True
        out, _err = capsys.readouterr()
        assert "feedback Module" in out

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

        Rewritten 2026-09-07 (FPLAN-0492 wave 6, the owner's standing ruling that a
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

    def test_success_does_not_raise(self, capsys: pytest.CaptureFixture[str]) -> None:
        """The counterfactual: a clean run still returns True and exits 0.

        Mutant: 'on' returns True without delegating -> red.
        """
        with patch(f"{_MOD}.subprocess.run", return_value=MagicMock(returncode=0)) as run:
            assert handle_command("feedback", ["on"]) is True
        run.assert_called_once()
        _out, err = capsys.readouterr()
        assert err == ""


class TestSmoke:
    """Help/introspection print the lines they advertise."""

    def test_print_help_runs(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Mutant: help line for 'on' dropped -> red."""
        print_help()
        out, _err = capsys.readouterr()
        assert "aipass feedback \u2014 toggle the feedback reminder" in out
        assert "aipass feedback on" in out
        assert "aipass feedback off" in out

    def test_print_introspection_runs(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Mutant: delegate line dropped -> red."""
        print_introspection()
        out, _err = capsys.readouterr()
        assert "feedback Module" in out
        assert "drone @hooks feedback on/off" in out
