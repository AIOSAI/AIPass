# =================== AIPass ====================
# Name: test_config.py
# Description: The registry-path configuration commands
# Version: 1.0.1
# Created: 2026-04-05
# Modified: 2026-10-23
# =============================================

"""Tests for apps/modules/config.py: the registry-path configuration commands."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that the module under test parses and imports

from __future__ import annotations

from unittest.mock import call, patch

import pytest
from aipass.drone.apps.modules.config import handle_command


MODULE = "aipass.drone.apps.modules.config"


@pytest.fixture(autouse=True)
def _isolate_config():
    """Patch all external dependencies so config.py never touches real state."""
    with (
        patch(f"{MODULE}.logger") as mock_logger,
        patch(f"{MODULE}.json_handler") as mock_jh,
        patch(f"{MODULE}.get_registry_path") as mock_get,
        patch(f"{MODULE}.set_registry_path") as mock_set,
        patch(f"{MODULE}.reset_registry_path") as mock_reset,
    ):
        mock_get.return_value = "/fake/registry.json"
        yield {
            "logger": mock_logger,
            "json_handler": mock_jh,
            "get_registry_path": mock_get,
            "set_registry_path": mock_set,
            "reset_registry_path": mock_reset,
        }


@pytest.fixture()
def mocks(_isolate_config):
    """Expose the patched mocks dict for tests that inspect calls."""
    return _isolate_config


class TestIntrospection:
    """command=None triggers introspection display."""

    def test_none_command_returns_true(self, mocks, capsys):
        """Mutant killed: handle_command(None) returning True without introspecting."""
        result = handle_command(command=None)
        assert result is True
        assert "config Module" in capsys.readouterr().out

    def test_none_command_calls_print_introspection(self, mocks, capsys):
        """Mutant killed: handle_command(None) returning True without introspecting."""
        handle_command(command=None)
        out = capsys.readouterr().out
        assert "Connected Handlers:" in out
        assert "reset_registry_path" in out

    def test_none_command_no_args_triggers_introspection(self, mocks, capsys):
        """Mutant killed: handle_command(None) returning True without introspecting."""
        result = handle_command(command=None, args=None)
        assert result is True
        assert "config Module" in capsys.readouterr().out

    def test_none_command_empty_args_triggers_introspection(self, mocks, capsys):
        """Mutant killed: handle_command(None) returning True without introspecting."""
        result = handle_command(command=None, args=[])
        assert result is True
        assert "config Module" in capsys.readouterr().out


class TestHelp:
    """--help and -h flags route to print_help."""

    def test_help_flag_as_command_returns_true(self, mocks, capsys):
        """Mutant killed: a help request returning True without printing help."""
        result = handle_command(command="--help")
        assert result is True
        assert "config — Registry configuration management" in capsys.readouterr().out

    def test_h_flag_as_command_returns_true(self, mocks, capsys):
        """Mutant killed: a help request returning True without printing help."""
        result = handle_command(command="-h")
        assert result is True
        assert "config — Registry configuration management" in capsys.readouterr().out

    def test_help_flag_in_args_returns_true(self, mocks, capsys):
        """Mutant killed: a help request returning True without printing help."""
        result = handle_command(command="path", args=["--help"])
        assert result is True
        assert "config — Registry configuration management" in capsys.readouterr().out

    def test_h_flag_in_args_returns_true(self, mocks, capsys):
        """Mutant killed: a help request returning True without printing help."""
        result = handle_command(command="set", args=["-h"])
        assert result is True
        assert "config — Registry configuration management" in capsys.readouterr().out

    def test_help_does_not_log_operation(self, mocks):

        handle_command(command="--help")
        mocks["json_handler"].log_operation.assert_not_called()


class TestPathCommand:
    """'path' command shows the current registry path."""

    def test_path_returns_true(self, mocks, capsys):
        """Mutant killed: path printing its label without the path."""
        result = handle_command(command="path")
        assert result is True
        assert "Registry path: /fake/registry.json" in capsys.readouterr().out

    def test_path_prints_registry_location(self, mocks, capsys):
        """Mutant killed: the registry path read twice for one 'path'."""

        handle_command(command="path")
        assert "/fake/registry.json" in capsys.readouterr().out
        assert mocks["get_registry_path"].call_args_list == [call()]

    def test_path_logs_operation(self, mocks):

        handle_command(command="path")
        mocks["json_handler"].log_operation.assert_called_once_with(
            "handle_command", {"module": "config", "command": "path"}
        )


class TestSetCommand:
    """'set' cannot persist past this process, so it prints the export to use and fails."""

    def test_set_prints_the_export_and_fails(self, mocks, capsys):
        """Mutant killed: set changing the in-process path and reporting success."""
        result = handle_command(command="set", args=["/new/path.json"])
        assert result is False
        assert "export AIPASS_REGISTRY=/new/path.json" in capsys.readouterr().out
        mocks["set_registry_path"].assert_not_called()

    def test_set_quotes_a_path_with_spaces(self, mocks, capsys):
        handle_command(command="set", args=["/my dir/registry.json"])
        assert "export AIPASS_REGISTRY='/my dir/registry.json'" in capsys.readouterr().out

    def test_set_without_args_returns_false(self, mocks):

        result = handle_command(command="set")
        assert result is False

    def test_set_without_args_logs_warning(self, mocks):
        """Mutant killed: the missing-path warning replaced by another message."""
        handle_command(command="set")
        mocks["logger"].warning.assert_called_once_with("config set requires a path argument")


class TestResetCommand:
    """'reset' cannot persist either: it prints the unset to use and fails."""

    def test_reset_prints_the_unset_and_fails(self, mocks, capsys):
        """Mutant killed: reset resetting the in-process path and reporting success."""
        result = handle_command(command="reset")
        assert result is False
        assert "unset AIPASS_REGISTRY" in capsys.readouterr().out
        mocks["reset_registry_path"].assert_not_called()


class TestUnknownCommand:
    """Unrecognized commands return False and log a warning."""

    def test_unknown_command_returns_false(self, mocks):

        result = handle_command(command="bogus")
        assert result is False

    def test_unknown_command_logs_warning(self, mocks):

        handle_command(command="destroy")
        mocks["logger"].warning.assert_called()
        # Format string and lazy argument checked separately: the call repr alone passes on the format.
        assert mocks["logger"].warning.call_args[0][0] == "config: unknown command '%s'"
        assert mocks["logger"].warning.call_args[0][1] == "destroy"
