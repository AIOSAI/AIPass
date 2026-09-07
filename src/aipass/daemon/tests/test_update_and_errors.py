# =================== AIPass ====================
# Name: test_update_and_errors.py
# Description: Tests for update command and error message formatting
# Version: 1.0.0
# Created: 2026-03-30
# Modified: 2026-03-30
# =============================================

"""
Tests for the update command (no longer a dead end) and error message
formatting (no cascading double-errors).

Covers:
  - update: runs digest with no args, help flag works
  - actions errors: single error message, no cascade
  - branch-health: no-args shows all-branches summary
"""

from unittest.mock import patch, MagicMock

import pytest

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


# ============================================================================
# Update command tests
# ============================================================================


class TestUpdateCommand:
    """Tests for the update module — no longer a dead end."""

    def test_update_no_args_runs_digest(self) -> None:
        """update with no args should run the digest, not show introspection."""
        with (
            patch.object(_update_mod, "load_inbox", return_value={"messages": [], "total_messages": 0}),
            patch.object(_update_mod, "load_local", return_value={}),
        ):
            result = _update_mod.handle_command("update", [])
        assert result is True

    def test_update_no_args_calls_load_inbox(self) -> None:
        """update with no args should call load_inbox (proving it runs the digest)."""
        mock_inbox = MagicMock(return_value={"messages": [], "total_messages": 0})
        with (
            patch.object(_update_mod, "load_inbox", mock_inbox),
            patch.object(_update_mod, "load_local", return_value={}),
        ):
            _update_mod.handle_command("update", [])
        mock_inbox.assert_called_once()

    def test_update_help_flag(self) -> None:
        """update --help should show help and return True."""
        result = _update_mod.handle_command("update", ["--help"])
        assert result is True

    def test_update_wrong_command(self) -> None:
        """update module should not handle other commands."""
        result = _update_mod.handle_command("schedule", [])
        assert result is False

    def test_update_error_returns_true(self) -> None:
        """update should return True even on error (command was handled)."""
        with patch.object(_update_mod, "load_inbox", side_effect=Exception("test error")):
            result = _update_mod.handle_command("update", [])
        assert result is True

    def test_no_escalation_warning_when_nothing_to_escalate(self, capsys: pytest.CaptureFixture[str]) -> None:
        """A clean digest must not emit a stderr warning.

        The section header was warned unconditionally, so every quiet run printed
        'ESCALATIONS NEEDED' to stderr and 'None - all clear' to stdout. Anything
        capturing stderr (cron, logs) read that as a standing alarm.
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


# ============================================================================
# Error cascade tests — single error message, no double-error
# ============================================================================


from aipass.daemon.apps.handlers.cli.arg_gate import UnknownArgument

ROUTER = "aipass.daemon.apps.daemon"


class TestErrorCascade:
    """A handled-but-refused command must not cascade to another module.

    THE CONTRACT IS UNCHANGED; THE SHAPE OF THE ANSWER MOVED (FPLAN-0492 wave
    2b). These used to assert `is True` — "actions handled it, router, stop
    looking". `actions` is a retired verb, so every one of these subcommands is
    an unknown argument, and Patrick's standing ruling says an unknown argument
    exits non-zero naming the token. SystemExit(1) stops the cascade harder than
    a True ever did: nothing after it runs at all. What would still be a defect
    is falling THROUGH to another module, and that is what each of these pins.
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

        The split is the layering: the module decides the argument is unknown,
        apps/daemon.py renders and exits. Pinning the raise here and the exit in
        test_route_command_* keeps both halves honest.
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

        route_command catches Exception broadly and moves on to the next module.
        UnknownArgument is caught BEFORE that, or the refusal would be logged as
        a module error and the loop would carry on — turning "actions: unknown
        argument 'x'" into "unknown command: actions", which names the wrong
        thing and exits through a different path entirely.
        """
        modules = _daemon_mod.get_modules()
        with pytest.raises(SystemExit) as exc:
            _daemon_mod.route_command("actions", ["nonexistent_xyz"], modules)
        assert exc.value.code == 1


# ============================================================================
# Branch-health no-args fallback tests
# ============================================================================


class TestBranchHealthFallback:
    """Tests that branch-health with no args shows all-branches summary."""

    def test_branch_health_no_args_returns_true(self) -> None:
        """branch-health with no args should return True (shows summary)."""
        result = _activity_mod.handle_command("branch-health", [])
        assert result is True

    def test_branch_health_no_args_not_introspection(self) -> None:
        """branch-health with no args should NOT call print_introspection."""
        with patch.object(_activity_mod, "print_introspection") as mock_intro:
            _activity_mod.handle_command("branch-health", [])
        mock_intro.assert_not_called()

    def test_branch_health_help_flag(self) -> None:
        """branch-health --help should return True."""
        result = _activity_mod.handle_command("branch-health", ["--help"])
        assert result is True
