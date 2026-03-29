"""Tests for google_drive_sync — Google Drive integration orchestration."""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# CLI stub keys — injected via monkeypatch inside the drive_sync_env fixture,
# NOT at module level, to avoid polluting sys.modules for other test files.
# ---------------------------------------------------------------------------

_CLI_STUB_KEYS = (
    "aipass.cli",
    "aipass.cli.apps",
    "aipass.cli.apps.modules",
    "aipass.cli.apps.modules.console",
    "aipass.cli.apps.modules.display",
    "aipass.cli.apps.modules.header",
    "aipass.cli.apps.modules.success",
    "aipass.cli.apps.modules.error",
)


# ===================================================================
# Helper — build mock handler modules
# ===================================================================

def _build_handler_mocks() -> dict[str, object]:
    """Create mock modules for google_drive_sync's handler dependencies."""

    mock_jh = MagicMock()
    mock_jh.ensure_module_jsons = MagicMock()
    mock_jh.log_operation = MagicMock()

    mock_drive_client = MagicMock()
    mock_drive_client.GoogleDriveSync = MagicMock

    mock_drive_json = MagicMock()
    mock_drive_json.load_config = MagicMock(return_value={})
    mock_drive_json.load_data = MagicMock(return_value={})

    mock_drive_ops = MagicMock()
    mock_drive_ops.clear_file_tracker = MagicMock(return_value=True)
    mock_drive_ops.get_file_tracker_stats = MagicMock(
        return_value={"total": 0, "sample": [], "truncated": False}
    )
    mock_drive_ops.test_drive_connection = MagicMock(return_value=True)

    mock_sync_test_ops = MagicMock()
    mock_sync_test_ops.create_sync_test_files = MagicMock(
        return_value={"success": True, "test_dir": "/tmp/test", "file_count": 3}
    )
    mock_sync_test_ops.cleanup_sync_test_dir = MagicMock()

    mock_json_init = MagicMock()
    mock_json_init.json_handler = mock_jh

    mods: dict[str, object] = {
        # Handler leaf modules
        "aipass.backup.apps.handlers.json": mock_json_init,
        "aipass.backup.apps.handlers.json.json_handler": mock_jh,
        "aipass.backup.apps.handlers.json.drive_sync_json": mock_drive_json,
        "aipass.backup.apps.handlers.operations.drive_sync_client": mock_drive_client,
        "aipass.backup.apps.handlers.operations.drive_sync_ops": mock_drive_ops,
        "aipass.backup.apps.handlers.operations.sync_test_ops": mock_sync_test_ops,
        # Package __init__ stubs (handler sub-packages only)
        "aipass.backup.apps.handlers": MagicMock(),
        "aipass.backup.apps.handlers.operations": MagicMock(),
        "aipass.backup.apps.handlers.utils": MagicMock(),
        # Private — for test assertions
        "_mock_jh": mock_jh,
    }
    return mods


# ===================================================================
# Fixtures
# ===================================================================


@pytest.fixture()
def drive_sync_env(monkeypatch):
    """Inject mock handler modules, import google_drive_sync, yield helpers."""
    mocks = _build_handler_mocks()

    # Inject CLI stubs via monkeypatch (auto-restored after test)
    for cli_key in _CLI_STUB_KEYS:
        if cli_key not in sys.modules:
            monkeypatch.setitem(sys.modules, cli_key, MagicMock())

    # Remove cached google_drive_sync and handler modules
    for key in list(sys.modules):
        if "google_drive_sync" in key:
            monkeypatch.delitem(sys.modules, key, raising=False)
    for key in list(sys.modules):
        if key.startswith("aipass.backup.apps.handlers"):
            monkeypatch.delitem(sys.modules, key, raising=False)

    # Inject handler mocks (skip private keys)
    for name, mod in mocks.items():
        if not name.startswith("_"):
            monkeypatch.setitem(sys.modules, name, mod)

    from aipass.backup.apps.modules import google_drive_sync

    return {
        "module": google_drive_sync,
        "handle_command": google_drive_sync.handle_command,
        "mock_jh": mocks["_mock_jh"],
    }


# ===================================================================
# Tests — handle_command
# ===================================================================


class TestHandleCommand:
    """Validate CLI routing performed by google_drive_sync.handle_command."""

    def test_handle_command_no_args_shows_introspection(self, drive_sync_env):
        """Passing None triggers the introspection display."""
        result = drive_sync_env["handle_command"](None)
        assert result is True

    def test_handle_command_help(self, drive_sync_env):
        """--help flag is routed and returns True."""
        args = SimpleNamespace(command="--help")
        result = drive_sync_env["handle_command"](args)
        assert result is True

    def test_handle_command_help_alias(self, drive_sync_env):
        """'help' alias is handled the same as --help."""
        args = SimpleNamespace(command="help")
        result = drive_sync_env["handle_command"](args)
        assert result is True

    def test_handle_command_drive_test(self, drive_sync_env):
        """'drive-test' routes to _test_drive_sync function."""
        mod = drive_sync_env["module"]
        args = SimpleNamespace(command="drive-test")

        with patch.object(mod, "_test_drive_sync", return_value=True) as mock_fn:
            result = drive_sync_env["handle_command"](args)

            assert result is True
            mock_fn.assert_called_once()

    def test_handle_command_drive_stats(self, drive_sync_env):
        """'drive-stats' routes to _show_file_tracker_stats function."""
        mod = drive_sync_env["module"]
        args = SimpleNamespace(command="drive-stats")

        with patch.object(
            mod, "_show_file_tracker_stats", return_value=True
        ) as mock_fn:
            result = drive_sync_env["handle_command"](args)

            assert result is True
            mock_fn.assert_called_once()

    def test_handle_command_drive_clear_tracker(self, drive_sync_env):
        """'drive-clear-tracker' routes to _clear_file_tracker function."""
        mod = drive_sync_env["module"]
        args = SimpleNamespace(command="drive-clear-tracker")

        with patch.object(
            mod, "_clear_file_tracker", return_value=True
        ) as mock_fn:
            result = drive_sync_env["handle_command"](args)

            assert result is True
            mock_fn.assert_called_once()

    def test_handle_command_no_command_attr(self, drive_sync_env):
        """Args object without .command attribute returns False."""
        args = SimpleNamespace(flag="value")
        result = drive_sync_env["handle_command"](args)
        assert result is False

    def test_handle_command_unknown_command(self, drive_sync_env):
        """Unrecognised command falls through and returns False."""
        args = SimpleNamespace(command="nonexistent")
        result = drive_sync_env["handle_command"](args)
        assert result is False

    def test_handle_command_drive_sync_with_test_flag(self, drive_sync_env):
        """'drive-sync --test' routes to _run_sync_test."""
        mod = drive_sync_env["module"]
        args = SimpleNamespace(command="drive-sync", test=True)

        with patch.object(mod, "_run_sync_test", return_value=True) as mock_fn:
            result = drive_sync_env["handle_command"](args)

            assert result is True
            mock_fn.assert_called_once()


# ===================================================================
# Tests — helper functions
# ===================================================================


class TestShowFileTrackerStats:
    """Validate _show_file_tracker_stats display logic."""

    def test_returns_true_on_success(self, drive_sync_env):
        """Returns True when stats are retrieved successfully."""
        mod = drive_sync_env["module"]
        mock_stats = {
            "total": 42,
            "sample": [{"file": "a.txt", "last_sync": "2026-01-01"}],
            "truncated": False,
        }

        with patch.object(
            mod, "get_file_tracker_stats", return_value=mock_stats
        ):
            result = mod._show_file_tracker_stats()

        assert result is True

    def test_returns_false_when_deps_unavailable(self, drive_sync_env):
        """Returns False when drive sync dependencies are None."""
        mod = drive_sync_env["module"]

        with patch.object(mod, "get_file_tracker_stats", None):
            result = mod._show_file_tracker_stats()

        assert result is False


class TestClearFileTracker:
    """Validate _clear_file_tracker delegation logic."""

    def test_returns_true_on_success(self, drive_sync_env):
        """Returns True when tracker is cleared successfully."""
        mod = drive_sync_env["module"]

        with (
            patch.object(
                mod,
                "_load_data",
                return_value={"runtime_state": {"file_tracker": {"a": 1}}},
            ),
            patch.object(
                mod, "_clear_file_tracker_handler", return_value=True
            ),
        ):
            result = mod._clear_file_tracker()

        assert result is True

    def test_returns_false_when_handler_unavailable(self, drive_sync_env):
        """Returns False when handler is None."""
        mod = drive_sync_env["module"]

        with (
            patch.object(
                mod,
                "_load_data",
                return_value={"runtime_state": {"file_tracker": {}}},
            ),
            patch.object(mod, "_clear_file_tracker_handler", None),
        ):
            result = mod._clear_file_tracker()

        assert result is False
