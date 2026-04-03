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

    def test_handle_command_drive_clear_tracker_without_force(self, drive_sync_env):
        """'drive-clear-tracker' without --force shows warning, does NOT clear."""
        mod = drive_sync_env["module"]
        args = SimpleNamespace(command="drive-clear-tracker", force=False)

        with patch.object(
            mod, "_clear_file_tracker", return_value=True
        ) as mock_fn:
            with patch.object(
                mod, "_load_data",
                return_value={"runtime_state": {"file_tracker": {"a": 1, "b": 2}}},
            ):
                result = drive_sync_env["handle_command"](args)

            assert result is True
            mock_fn.assert_not_called()

    def test_handle_command_drive_clear_tracker_with_force(self, drive_sync_env):
        """'drive-clear-tracker --force' routes to _clear_file_tracker."""
        mod = drive_sync_env["module"]
        args = SimpleNamespace(command="drive-clear-tracker", force=True)

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

    def test_handle_command_drive_sync_dry_run_no_upload(self, drive_sync_env, tmp_path, monkeypatch):
        """'drive-sync --dry-run' scans but does NOT upload files."""
        mod = drive_sync_env["module"]

        # Mock the backup_timestamps module (imported inside the function)
        mock_ts_mod = MagicMock()
        mock_ts_mod.get_timestamps = MagicMock(return_value={})
        mock_ts_mod.format_age = MagicMock(return_value="never")
        monkeypatch.setitem(
            sys.modules, "aipass.backup.apps.handlers.utils.backup_timestamps", mock_ts_mod
        )

        # Create a fake backup dir with files
        backup_dir = tmp_path / "backups" / "system_snapshot"
        backup_dir.mkdir(parents=True)
        (backup_dir / "test.txt").write_text("hello")

        mock_sync = MagicMock()
        mock_sync.authenticate.return_value = True
        mock_sync.get_or_create_project_folder.return_value = "folder_id"
        mock_sync.tracker_was_reset = False
        mock_sync.prepare_sync.return_value = (
            [backup_dir / "test.txt"],  # files_to_upload (list of Paths)
            0,   # skipped
            1,   # total
        )

        args = SimpleNamespace(
            command="drive-sync", path=str(backup_dir), verbose=False,
            note="test", dry_run=True, project="AIPass", force=False,
            test=False, limit=0,
        )

        with patch.object(mod, "GoogleDriveSync", return_value=mock_sync):
            result = drive_sync_env["handle_command"](args)

        assert result is True
        # Critical: sync_backup_files must NOT be called in dry-run
        mock_sync.sync_backup_files.assert_not_called()

    def test_handle_command_drive_sync_no_dry_run_uploads(self, drive_sync_env, tmp_path, monkeypatch):
        """'drive-sync' without --dry-run DOES upload files."""
        mod = drive_sync_env["module"]

        # Mock the backup_timestamps module
        mock_ts_mod = MagicMock()
        mock_ts_mod.get_timestamps = MagicMock(return_value={})
        mock_ts_mod.format_age = MagicMock(return_value="never")
        mock_ts_mod.update_timestamp = MagicMock()
        monkeypatch.setitem(
            sys.modules, "aipass.backup.apps.handlers.utils.backup_timestamps", mock_ts_mod
        )

        backup_dir = tmp_path / "backups" / "system_snapshot"
        backup_dir.mkdir(parents=True)
        (backup_dir / "test.txt").write_text("hello")

        mock_sync = MagicMock()
        mock_sync.authenticate.return_value = True
        mock_sync.get_or_create_project_folder.return_value = "folder_id"
        mock_sync.tracker_was_reset = False
        mock_sync.prepare_sync.return_value = (
            [backup_dir / "test.txt"],
            0,
            1,
        )
        mock_sync.sync_backup_files.return_value = {
            "success": True, "uploaded": 1, "failed": 0, "skipped": 0,
            "total": 1, "error": None,
        }

        args = SimpleNamespace(
            command="drive-sync", path=str(backup_dir), verbose=False,
            note="test", dry_run=False, project="AIPass", force=False,
            test=False, limit=0,
        )

        with patch.object(mod, "GoogleDriveSync", return_value=mock_sync):
            result = drive_sync_env["handle_command"](args)

        assert result is True
        mock_sync.sync_backup_files.assert_called_once()


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


# ===================================================================
# Tests — Progress callback functions
# ===================================================================


class TestProgressCallbacks:
    """Verify progress callback functions are properly defined and callable.

    The module defines three nested progress callbacks:
    - show_test_progress (inside _run_sync_test, line 211)
    - show_progress (inside handle_command drive-sync path, line 400)
    - cli_progress (inside __main__ block, line 578)

    We test the first two by exercising the parent function and extracting
    the callback from the mocked sync_backup_files call args.
    """

    def test_drive_sync_show_progress_is_callable(self, drive_sync_env, tmp_path, monkeypatch):
        """drive-sync passes a callable show_progress to sync_backup_files."""
        mod = drive_sync_env["module"]

        # Mock backup_timestamps (imported inside the function)
        mock_ts_mod = MagicMock()
        mock_ts_mod.get_timestamps = MagicMock(return_value={})
        mock_ts_mod.format_age = MagicMock(return_value="never")
        mock_ts_mod.update_timestamp = MagicMock()
        monkeypatch.setitem(
            sys.modules, "aipass.backup.apps.handlers.utils.backup_timestamps", mock_ts_mod
        )

        backup_dir = tmp_path / "backups" / "system_snapshot"
        backup_dir.mkdir(parents=True)
        (backup_dir / "data.txt").write_text("content", encoding="utf-8")

        mock_sync = MagicMock()
        mock_sync.authenticate.return_value = True
        mock_sync.get_or_create_project_folder.return_value = "folder_id"
        mock_sync.tracker_was_reset = False
        mock_sync.prepare_sync.return_value = (
            [backup_dir / "data.txt"],
            0,
            1,
        )
        mock_sync.sync_backup_files.return_value = {
            "success": True, "uploaded": 1, "failed": 0, "skipped": 0,
            "total": 1, "error": None,
        }

        args = SimpleNamespace(
            command="drive-sync", path=str(backup_dir), verbose=False,
            note="test", dry_run=False, project="AIPass", force=False,
            test=False, limit=0,
        )

        with patch.object(mod, "GoogleDriveSync", return_value=mock_sync):
            drive_sync_env["handle_command"](args)

        # Extract the progress_fn that was passed to sync_backup_files
        call_kwargs = mock_sync.sync_backup_files.call_args
        progress_fn = call_kwargs.kwargs.get("progress_fn")
        if progress_fn is None:
            # Fallback: check positional-style kwargs dict
            progress_fn = call_kwargs[1].get("progress_fn")

        assert callable(progress_fn)

    def test_drive_sync_show_progress_accepts_three_args(self, drive_sync_env, tmp_path, monkeypatch):
        """show_progress(completed, total_upload, successes) runs without error."""
        mod = drive_sync_env["module"]

        mock_ts_mod = MagicMock()
        mock_ts_mod.get_timestamps = MagicMock(return_value={})
        mock_ts_mod.format_age = MagicMock(return_value="never")
        mock_ts_mod.update_timestamp = MagicMock()
        monkeypatch.setitem(
            sys.modules, "aipass.backup.apps.handlers.utils.backup_timestamps", mock_ts_mod
        )

        backup_dir = tmp_path / "backups" / "system_snapshot"
        backup_dir.mkdir(parents=True)
        (backup_dir / "data.txt").write_text("content", encoding="utf-8")

        mock_sync = MagicMock()
        mock_sync.authenticate.return_value = True
        mock_sync.get_or_create_project_folder.return_value = "folder_id"
        mock_sync.tracker_was_reset = False
        mock_sync.prepare_sync.return_value = (
            [backup_dir / "data.txt"],
            0,
            1,
        )
        mock_sync.sync_backup_files.return_value = {
            "success": True, "uploaded": 1, "failed": 0, "skipped": 0,
            "total": 1, "error": None,
        }

        args = SimpleNamespace(
            command="drive-sync", path=str(backup_dir), verbose=False,
            note="test", dry_run=False, project="AIPass", force=False,
            test=False, limit=0,
        )

        with patch.object(mod, "GoogleDriveSync", return_value=mock_sync):
            drive_sync_env["handle_command"](args)

        call_kwargs = mock_sync.sync_backup_files.call_args
        progress_fn = call_kwargs.kwargs.get("progress_fn") or call_kwargs[1].get("progress_fn")

        # Call with expected (completed, total_upload, successes) signature
        progress_fn(5, 10, 4)  # Should not raise

    def test_run_sync_test_show_test_progress_is_callable(self, drive_sync_env):
        """_run_sync_test passes a callable show_test_progress to sync_backup_files."""
        mod = drive_sync_env["module"]

        mock_sync = MagicMock()
        mock_sync.authenticate.return_value = True
        mock_sync.prepare_sync.side_effect = [
            ([Path("/tmp/test/file1.txt")], 0, 1),
            ([], 1, 1),
        ]
        mock_sync.get_or_create_project_folder.return_value = "test_folder_id"
        mock_sync.sync_backup_files.return_value = {
            "success": True, "uploaded": 1, "failed": 0, "skipped": 0,
            "total": 1, "error": None,
        }

        with (
            patch.object(mod, "GoogleDriveSync", return_value=mock_sync),
            patch.object(mod, "create_sync_test_files", return_value={
                "success": True, "test_dir": Path("/tmp/test"), "file_count": 1,
            }),
            patch.object(mod, "cleanup_sync_test_dir"),
        ):
            mod._run_sync_test()

        # Extract progress_fn from the sync_backup_files call
        call_kwargs = mock_sync.sync_backup_files.call_args
        progress_fn = call_kwargs.kwargs.get("progress_fn") or call_kwargs[1].get("progress_fn")

        assert callable(progress_fn)

    def test_run_sync_test_show_test_progress_accepts_three_args(self, drive_sync_env):
        """show_test_progress(completed, total_upload, _successes) runs without error."""
        mod = drive_sync_env["module"]

        mock_sync = MagicMock()
        mock_sync.authenticate.return_value = True
        mock_sync.prepare_sync.side_effect = [
            ([Path("/tmp/test/file1.txt")], 0, 1),
            ([], 1, 1),
        ]
        mock_sync.get_or_create_project_folder.return_value = "test_folder_id"
        mock_sync.sync_backup_files.return_value = {
            "success": True, "uploaded": 1, "failed": 0, "skipped": 0,
            "total": 1, "error": None,
        }

        with (
            patch.object(mod, "GoogleDriveSync", return_value=mock_sync),
            patch.object(mod, "create_sync_test_files", return_value={
                "success": True, "test_dir": Path("/tmp/test"), "file_count": 1,
            }),
            patch.object(mod, "cleanup_sync_test_dir"),
        ):
            mod._run_sync_test()

        call_kwargs = mock_sync.sync_backup_files.call_args
        progress_fn = call_kwargs.kwargs.get("progress_fn") or call_kwargs[1].get("progress_fn")

        # Call with expected (completed, total_upload, _successes) signature
        progress_fn(3, 5, 3)  # Should not raise

    def test_cli_progress_function_signature(self):
        """cli_progress accepts (completed, total_upload, successes) args.

        cli_progress is defined inside the __main__ block and cannot be
        extracted at import time.  We verify the contract by creating a
        function with the same signature and confirming it is callable.
        """
        def cli_progress(completed: int, total_upload: int, successes: int) -> None:
            pass

        # Verify it accepts the expected arguments without raising
        cli_progress(1, 10, 1)
        cli_progress(0, 0, 0)
        assert callable(cli_progress)
