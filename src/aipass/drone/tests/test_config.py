"""Tests for the config module — registry configuration management."""

from __future__ import annotations

from unittest.mock import patch

import pytest


MODULE = "aipass.drone.apps.modules.config"


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture(autouse=True)
def _isolate_config():
    """Patch all external dependencies so config.py never touches real state."""
    with (
        patch(f"{MODULE}.logger") as mock_logger,
        patch(f"{MODULE}.console") as mock_console,
        patch(f"{MODULE}.json_handler") as mock_jh,
        patch(f"{MODULE}.get_registry_path") as mock_get,
        patch(f"{MODULE}.set_registry_path") as mock_set,
        patch(f"{MODULE}.reset_registry_path") as mock_reset,
    ):
        mock_get.return_value = "/fake/registry.json"
        yield {
            "logger": mock_logger,
            "console": mock_console,
            "json_handler": mock_jh,
            "get_registry_path": mock_get,
            "set_registry_path": mock_set,
            "reset_registry_path": mock_reset,
        }


@pytest.fixture()
def mocks(_isolate_config):
    """Expose the patched mocks dict for tests that inspect calls."""
    return _isolate_config


# ===========================================================================
# 1. handle_command — None / introspection
# ===========================================================================


class TestIntrospection:
    """command=None triggers introspection display."""

    def test_none_command_returns_true(self, mocks):
        from aipass.drone.apps.modules.config import handle_command

        result = handle_command(command=None)
        assert result is True

    def test_none_command_calls_print_introspection(self, mocks):
        from aipass.drone.apps.modules.config import handle_command

        with patch(f"{MODULE}.print_introspection") as mock_intro:
            handle_command(command=None)
            mock_intro.assert_called_once()

    def test_none_command_no_args_triggers_introspection(self, mocks):
        from aipass.drone.apps.modules.config import handle_command

        result = handle_command(command=None, args=None)
        assert result is True

    def test_none_command_empty_args_triggers_introspection(self, mocks):
        from aipass.drone.apps.modules.config import handle_command

        result = handle_command(command=None, args=[])
        assert result is True


# ===========================================================================
# 2. handle_command — help
# ===========================================================================


class TestHelp:
    """--help and -h flags route to print_help."""

    def test_help_flag_as_command_returns_true(self, mocks):
        from aipass.drone.apps.modules.config import handle_command

        result = handle_command(command="--help")
        assert result is True

    def test_h_flag_as_command_returns_true(self, mocks):
        from aipass.drone.apps.modules.config import handle_command

        result = handle_command(command="-h")
        assert result is True

    def test_help_flag_in_args_returns_true(self, mocks):
        from aipass.drone.apps.modules.config import handle_command

        result = handle_command(command="path", args=["--help"])
        assert result is True

    def test_h_flag_in_args_returns_true(self, mocks):
        from aipass.drone.apps.modules.config import handle_command

        result = handle_command(command="set", args=["-h"])
        assert result is True

    def test_help_does_not_log_operation(self, mocks):
        from aipass.drone.apps.modules.config import handle_command

        handle_command(command="--help")
        mocks["json_handler"].log_operation.assert_not_called()


# ===========================================================================
# 3. handle_command — path
# ===========================================================================


class TestPathCommand:
    """'path' command shows the current registry path."""

    def test_path_returns_true(self, mocks):
        from aipass.drone.apps.modules.config import handle_command

        result = handle_command(command="path")
        assert result is True

    def test_path_prints_registry_location(self, mocks):
        # The once-ness was a test of its own until FPLAN-0492. Printing the
        # handler's value already proves the handler was asked; only "exactly
        # once" was extra, and reading the registry path twice per 'path' is
        # still a defect worth catching. So it stays — as a second assertion
        # about this call, not as a second test claiming a second behaviour.
        from aipass.drone.apps.modules.config import handle_command

        handle_command(command="path")
        printed = mocks["console"].print.call_args[0][0]
        assert "/fake/registry.json" in printed
        mocks["get_registry_path"].assert_called_once()

    def test_path_logs_operation(self, mocks):
        from aipass.drone.apps.modules.config import handle_command

        handle_command(command="path")
        mocks["json_handler"].log_operation.assert_called_once_with(
            "handle_command", {"module": "config", "command": "path"}
        )


# ===========================================================================
# 4. handle_command — set
# ===========================================================================


class TestSetCommand:
    """'set' command overrides the registry path."""

    def test_set_with_arg_returns_true(self, mocks):
        from aipass.drone.apps.modules.config import handle_command

        result = handle_command(command="set", args=["/new/path.json"])
        assert result is True

    def test_set_calls_set_registry_path_with_correct_arg(self, mocks):
        from aipass.drone.apps.modules.config import handle_command

        handle_command(command="set", args=["/custom/registry.json"])
        mocks["set_registry_path"].assert_called_once_with("/custom/registry.json")

    def test_set_prints_new_path(self, mocks):
        from aipass.drone.apps.modules.config import handle_command

        handle_command(command="set", args=["/new/path.json"])
        printed = mocks["console"].print.call_args[0][0]
        assert "/new/path.json" in printed

    def test_set_without_args_returns_false(self, mocks):
        from aipass.drone.apps.modules.config import handle_command

        result = handle_command(command="set")
        assert result is False

    def test_set_without_args_logs_warning(self, mocks):
        from aipass.drone.apps.modules.config import handle_command

        handle_command(command="set")
        mocks["logger"].warning.assert_called()

    def test_set_without_args_does_not_call_set_registry_path(self, mocks):
        from aipass.drone.apps.modules.config import handle_command

        handle_command(command="set")
        mocks["set_registry_path"].assert_not_called()


# ===========================================================================
# 5. handle_command — reset
# ===========================================================================


class TestResetCommand:
    """'reset' command restores the default registry path."""

    def test_reset_returns_true(self, mocks):
        from aipass.drone.apps.modules.config import handle_command

        result = handle_command(command="reset")
        assert result is True

    def test_reset_calls_reset_registry_path(self, mocks):
        from aipass.drone.apps.modules.config import handle_command

        handle_command(command="reset")
        mocks["reset_registry_path"].assert_called_once()

    def test_reset_prints_confirmation(self, mocks):
        from aipass.drone.apps.modules.config import handle_command

        handle_command(command="reset")
        printed = mocks["console"].print.call_args[0][0]
        # The one string the module prints, measured by running it. The two
        # `or` clauses this replaces both held, so neither was load-bearing:
        # any confirmation mentioning either word passed.
        assert printed == "Registry path reset to default"


# ===========================================================================
# 6. handle_command — unknown command
# ===========================================================================


class TestUnknownCommand:
    """Unrecognized commands return False and log a warning."""

    def test_unknown_command_returns_false(self, mocks):
        from aipass.drone.apps.modules.config import handle_command

        result = handle_command(command="bogus")
        assert result is False

    def test_unknown_command_logs_warning(self, mocks):
        from aipass.drone.apps.modules.config import handle_command

        handle_command(command="destroy")
        mocks["logger"].warning.assert_called()
        # The format string and the lazy argument, separately. Both clauses of
        # the `or` this replaces held — the second one read the repr of the whole
        # call, so it passed on the format string alone.
        assert mocks["logger"].warning.call_args[0][0] == "config: unknown command '%s'"
        assert mocks["logger"].warning.call_args[0][1] == "destroy"
