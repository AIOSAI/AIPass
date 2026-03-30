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
        with patch.object(_update_mod, "load_inbox", return_value={"messages": [], "total_messages": 0}), \
             patch.object(_update_mod, "load_local", return_value={}):
            result = _update_mod.handle_command("update", [])
        assert result is True

    def test_update_no_args_calls_load_inbox(self) -> None:
        """update with no args should call load_inbox (proving it runs the digest)."""
        mock_inbox = MagicMock(return_value={"messages": [], "total_messages": 0})
        with patch.object(_update_mod, "load_inbox", mock_inbox), \
             patch.object(_update_mod, "load_local", return_value={}):
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


# ============================================================================
# Error cascade tests — single error message, no double-error
# ============================================================================


class TestErrorCascade:
    """Tests that error paths return True (command handled) to prevent cascade."""

    def test_actions_unknown_subcommand_returns_true(self) -> None:
        """Unknown subcommand should return True (error displayed, not cascaded)."""
        result = _actions_mod.handle_command("actions", ["nonexistent_xyz"])
        assert result is True, "Unknown subcommand must return True to prevent cascade"

    def test_actions_invalid_id_returns_true(self) -> None:
        """Invalid action ID should return True (error displayed, not cascaded)."""
        result = _actions_mod.handle_command("actions", ["9999", "info"])
        assert result is True, "Invalid ID must return True to prevent cascade"

    def test_actions_delete_no_id_returns_true(self) -> None:
        """actions delete with no ID should return True (error displayed)."""
        result = _actions_mod.handle_command("actions", ["delete"])
        assert result is True

    def test_actions_set_no_args_returns_true(self) -> None:
        """actions set with insufficient args should return True (error displayed)."""
        result = _actions_mod.handle_command("actions", ["set"])
        assert result is True

    def test_actions_set_bad_type_returns_true(self) -> None:
        """actions set with unknown type should return True (error displayed)."""
        result = _actions_mod.handle_command("actions", ["set", "badtype"])
        assert result is True

    def test_route_command_no_cascade(self) -> None:
        """route_command should return True for handled-but-failed actions commands."""
        modules = _daemon_mod.get_modules()
        result = _daemon_mod.route_command("actions", ["nonexistent_xyz"], modules)
        assert result is True, "route_command must not fall through on handled errors"


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
