# =================== AIPass ====================
# Name: test_update_and_errors.py
# Description: Tests for update command and error message formatting
# Version: 1.1.0
# Created: 2026-03-30
# Modified: 2026-10-17
# =============================================

"""Tests for apps/modules/update.py, the actions refusal and branch-health's bare summary."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that update.py, actions.py and activity_report.py parse and import
# seedgo: no-test-needed(generated) — the digest's section layout; handlers/update/ builds its data

from unittest.mock import patch, MagicMock

import pytest

from aipass.daemon.apps.handlers.cli.arg_gate import UnknownArgument
from aipass.daemon.apps import daemon as _daemon_mod
from aipass.daemon.apps.modules import update as _update_mod
from aipass.daemon.apps.modules import actions as _actions_mod
from aipass.daemon.apps.modules import activity_report as _activity_mod


@pytest.fixture(autouse=True)
def _mock_log_operations():
    """Prevent json_handler.log_operation from touching real files."""
    with (
        patch.object(_daemon_mod.json_handler, "log_operation", return_value=True),
        patch.object(_update_mod.json_handler, "log_operation", return_value=True),
        patch.object(_actions_mod.json_handler, "log_operation", return_value=True),
        patch.object(_activity_mod.json_handler, "log_operation", return_value=True),
    ):
        yield


class TestUpdateCommand:
    """Tests for the update module — no longer a dead end."""

    def test_update_no_args_runs_digest(self, capsys: pytest.CaptureFixture[str]) -> None:
        """update with no args should run the digest, not show introspection. Mutant killed: digest not printed."""
        with (
            patch.object(_update_mod, "load_inbox", return_value={"messages": [], "total_messages": 0}),
            patch.object(_update_mod, "load_local", return_value={}),
        ):
            result = _update_mod.handle_command("update", [])
        assert result is True
        out = capsys.readouterr().out
        assert "INBOX STATUS" in out
        assert "update Module" not in out, "bare update must run the digest, not introspection"

    def test_update_no_args_calls_load_inbox(self, capsys: pytest.CaptureFixture[str]) -> None:
        """update with no args should call load_inbox (proving it runs the digest). Mutant killed: total pinned to 0."""
        mock_inbox = MagicMock(return_value={"messages": [], "total_messages": 7})
        with (
            patch.object(_update_mod, "load_inbox", mock_inbox),
            patch.object(_update_mod, "load_local", return_value={}),
        ):
            _update_mod.handle_command("update", [])
        mock_inbox.assert_called_once_with()
        assert "Total messages: 7" in capsys.readouterr().out, "load_inbox's answer must reach the digest"

    def test_update_help_flag(self, capsys: pytest.CaptureFixture[str]) -> None:
        """update --help should show help and return True. Mutant killed: the --help branch removed."""
        with patch.object(_update_mod, "load_inbox") as mock_inbox:
            result = _update_mod.handle_command("update", ["--help"])
        assert result is True
        mock_inbox.assert_not_called()
        assert "drone @daemon update" in capsys.readouterr().out

    def test_update_wrong_command(self) -> None:
        """update module should not handle other commands."""
        result = _update_mod.handle_command("schedule", [])
        assert result is False

    def test_update_error_exits_1(self, capsys: pytest.CaptureFixture[str]) -> None:
        """A failed digest exits 1, never the success answer.

        Mutants killed: error() not called; `return True` after the failure (exit 0).
        """
        with patch.object(_update_mod, "load_inbox", side_effect=Exception("test error")):
            with pytest.raises(SystemExit) as exited:
                _update_mod.handle_command("update", [])
        assert exited.value.code == 1, "a failed digest must not exit 0"
        assert "test error" in capsys.readouterr().err, "the failure must be reported once, on stderr"

    def test_no_escalation_warning_when_nothing_to_escalate(self, capsys: pytest.CaptureFixture[str]) -> None:
        """A clean digest must not emit a stderr warning.

        Anything capturing stderr (cron, logs) reads 'ESCALATIONS NEEDED' there as a standing alarm.
        """
        with (
            patch.object(_update_mod, "load_inbox", return_value={"messages": [], "total_messages": 0}),
            patch.object(_update_mod, "load_local", return_value={}),
            patch.object(_update_mod, "get_escalations", return_value=[]),
        ):
            _update_mod.handle_command("update", [])
        captured = capsys.readouterr()
        assert "ESCALATIONS NEEDED" not in captured.err, "clean digest must not warn on stderr"
        assert "all clear" in captured.out, "the escalations section must still render"

    def test_escalation_warning_when_escalations_exist(self, capsys: pytest.CaptureFixture[str]) -> None:
        """A real escalation must still warn on stderr."""
        with (
            patch.object(_update_mod, "load_inbox", return_value={"messages": [], "total_messages": 0}),
            patch.object(_update_mod, "load_local", return_value={}),
            patch.object(_update_mod, "get_escalations", return_value=[{"from": "@devpulse", "subject": "urgent"}]),
        ):
            _update_mod.handle_command("update", [])
        captured = capsys.readouterr()
        assert "ESCALATIONS NEEDED" in captured.err, "a real escalation must warn on stderr"


ROUTER = "aipass.daemon.apps.daemon"


class TestErrorCascade:
    """A handled-but-refused command must not cascade to another module.

    `actions` is a retired verb, so each subcommand is an unknown argument and exits non-zero naming the token.
    Falling THROUGH to another module is the defect each of these pins.
    """

    @pytest.mark.parametrize(
        "args",
        [
            pytest.param(["nonexistent_xyz"], id="unknown-subcommand"),
            pytest.param(["9999", "info"], id="invalid-id"),
            pytest.param(["delete"], id="delete-without-id"),
            pytest.param(["set"], id="set-without-args"),
            pytest.param(["set", "badtype"], id="set-bad-type"),
        ],
    )
    def test_actions_refuses_every_retired_subcommand(self, args) -> None:
        """Called DIRECTLY, a verb raises; the router turns that into exit 1.

        The module decides the argument is unknown; apps/daemon.py renders and exits.
        """
        with pytest.raises(UnknownArgument) as exc:
            _actions_mod.handle_command("actions", args)
        assert exc.value.token == args[0]
        assert exc.value.verb == "actions"

    def test_the_refusal_names_the_offending_token(self) -> None:
        """A refusal that does not name the token leaves the caller guessing."""
        modules = _daemon_mod.get_modules()
        with patch(f"{ROUTER}.error") as mock_err:
            with pytest.raises(SystemExit):
                _daemon_mod.route_command("actions", ["nonexistent_xyz"], modules)
        assert "nonexistent_xyz" in str(mock_err.call_args)

    def test_route_command_does_not_fall_through_on_a_refusal(self) -> None:
        """The router must not try the next module after a verb refuses.

        UnknownArgument is caught BEFORE route_command's broad except, or the refusal reads "unknown command".
        """
        modules = _daemon_mod.get_modules()
        with pytest.raises(SystemExit) as exc:
            _daemon_mod.route_command("actions", ["nonexistent_xyz"], modules)
        assert exc.value.code == 1


class TestBranchHealthFallback:
    """Tests that branch-health with no args shows all-branches summary."""

    def test_branch_health_no_args_returns_true(self, capsys: pytest.CaptureFixture[str]) -> None:
        """branch-health with no args should return True (shows summary). Mutant killed: summary not printed."""
        with patch.object(_activity_mod, "generate_activity_report", return_value="ALL-BRANCHES-SUMMARY") as mock_gen:
            result = _activity_mod.handle_command("branch-health", [])
        assert result is True
        mock_gen.assert_called_once_with(since_hours=24, verbosity="normal")
        assert "ALL-BRANCHES-SUMMARY" in capsys.readouterr().out

    def test_branch_health_no_args_not_introspection(self) -> None:
        """branch-health with no args should NOT call print_introspection."""
        with (
            patch.object(_activity_mod, "print_introspection") as mock_intro,
            patch.object(_activity_mod, "generate_activity_report", return_value="summary"),
        ):
            _activity_mod.handle_command("branch-health", [])
        mock_intro.assert_not_called()

    def test_branch_health_help_flag(self, capsys: pytest.CaptureFixture[str]) -> None:
        """branch-health --help should return True. Mutant killed: help heading dropped."""
        result = _activity_mod.handle_command("branch-health", ["--help"])
        assert result is True
        assert "BRANCH-HEALTH - Single Branch Deep Dive" in capsys.readouterr().out
