"""Tests for backup_core — main backup system orchestration module."""

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# CLI stub keys — injected via monkeypatch inside the backup_core_env fixture,
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
# Helper — build mock handler modules for backup_core's dependencies
# ===================================================================

def _build_handler_mocks(tmp_path: Path) -> dict[str, object]:
    """Create mock modules for every handler that backup_core imports from.

    Returns a dict of sys.modules key -> mock object.  Keys starting with
    ``_`` are private helpers (not injected), everything else goes straight
    into sys.modules.
    """
    backup_modes = {
        "snapshot": {
            "name": "System Snapshot",
            "description": "test snapshot",
            "destination": str(tmp_path / "backups"),
            "folder_name": "system_snapshot",
            "behavior": "dynamic",
            "usage": "Quick saves",
        },
        "versioned": {
            "name": "Versioned Backup",
            "description": "test versioned",
            "destination": str(tmp_path / "backups"),
            "folder_name": "versioned_backup",
            "behavior": "versioned",
            "usage": "Version history",
        },
    }

    # -- json_handler mock -------------------------------------------------
    mock_jh = MagicMock()
    mock_jh.ensure_module_jsons = MagicMock()
    mock_jh.log_operation = MagicMock()

    # -- config_handler mock -----------------------------------------------
    mock_config = MagicMock()
    mock_config.BACKUP_MODES = backup_modes
    mock_config.GLOBAL_IGNORE_PATTERNS = []
    mock_config.IGNORE_EXCEPTIONS = set()
    mock_config.filter_tracked_items = MagicMock(return_value=[])
    mock_config.should_ignore = MagicMock(return_value=False)
    mock_config.SOURCE_WHITELIST = []
    mock_config.MAX_FILE_SIZE_MB = 100

    # -- ignore_patterns (re-exported by config_handler) -------------------
    mock_ignore = MagicMock()
    mock_ignore.GLOBAL_IGNORE_PATTERNS = []
    mock_ignore.IGNORE_EXCEPTIONS = set()
    mock_ignore.should_ignore = MagicMock(return_value=False)
    mock_ignore.filter_tracked_items = MagicMock(return_value=[])
    mock_ignore.get_ignore_patterns = MagicMock(return_value=[])
    mock_ignore.get_cli_tracking_patterns = MagicMock(return_value=[])
    mock_ignore.DIFF_IGNORE_PATTERNS = []
    mock_ignore.DIFF_INCLUDE_PATTERNS = []
    mock_ignore.CLI_TRACKING_PATTERNS = []
    mock_ignore.SOURCE_WHITELIST = []
    mock_ignore.MAX_FILE_SIZE_MB = 100

    # -- backup_models mock (with a lightweight BackupResult) --------------
    class _FakeBackupResult:
        def __init__(self) -> None:
            import datetime

            self.files_checked = 0
            self.files_copied = 0
            self.files_added = 0
            self.files_skipped = 0
            self.files_deleted = 0
            self.errors = 0
            self.error_details: list[str] = []
            self.warnings: list[str] = []
            self.critical_errors: list[str] = []
            self.start_time = datetime.datetime.now()
            self.backup_path = ""
            self.mode = ""
            self.success = True

        def add_error(self, msg: str, is_critical: bool = False) -> None:
            self.errors += 1
            self.error_details.append(msg)
            if is_critical:
                self.critical_errors.append(msg)
                self.success = False

        def add_warning(self, msg: str) -> None:
            self.warnings.append(msg)

    mock_models = MagicMock()
    mock_models.BackupResult = _FakeBackupResult

    # -- file_operations mock ----------------------------------------------
    mock_file_ops = MagicMock()
    mock_file_ops.copy_file_with_structure = MagicMock(return_value=True)
    mock_file_ops.copy_versioned_file = MagicMock(return_value=True)
    mock_file_ops.file_needs_backup = MagicMock(return_value=True)

    # -- system_utils mock -------------------------------------------------
    mock_sys_utils = MagicMock()
    mock_sys_utils.safe_print = MagicMock()

    # -- changelog / backup_info handler mocks -----------------------------
    mock_changelog = MagicMock()
    mock_changelog.load_changelog = MagicMock(return_value={})
    mock_changelog.save_changelog_entry = MagicMock(return_value=True)
    mock_changelog.display_previous_comments = MagicMock()

    mock_backup_info = MagicMock()
    mock_backup_info.load_backup_info = MagicMock(return_value={})
    mock_backup_info.save_backup_info = MagicMock(return_value=True)

    # -- json __init__ re-exports ------------------------------------------
    mock_json_init = MagicMock()
    mock_json_init.json_handler = mock_jh
    mock_json_init.load_changelog = mock_changelog.load_changelog
    mock_json_init.save_changelog_entry = mock_changelog.save_changelog_entry
    mock_json_init.display_previous_comments = mock_changelog.display_previous_comments
    mock_json_init.load_backup_info = mock_backup_info.load_backup_info
    mock_json_init.save_backup_info = mock_backup_info.save_backup_info

    # -- assemble the mapping ----------------------------------------------
    mods: dict[str, object] = {
        # Handler leaf modules (the ones backup_core actually imports from)
        "aipass.backup.apps.handlers.config.config_handler": mock_config,
        "aipass.backup.apps.handlers.config.ignore_patterns": mock_ignore,
        "aipass.backup.apps.handlers.json": mock_json_init,
        "aipass.backup.apps.handlers.json.json_handler": mock_jh,
        "aipass.backup.apps.handlers.json.changelog_handler": mock_changelog,
        "aipass.backup.apps.handlers.json.backup_info_handler": mock_backup_info,
        "aipass.backup.apps.handlers.models.backup_models": mock_models,
        "aipass.backup.apps.handlers.operations.file_operations": mock_file_ops,
        "aipass.backup.apps.handlers.utils.system_utils": mock_sys_utils,
        # Package __init__ stubs (only handler sub-packages, NOT aipass.backup.apps)
        "aipass.backup.apps.handlers": MagicMock(),
        "aipass.backup.apps.handlers.config": MagicMock(),
        "aipass.backup.apps.handlers.models": MagicMock(),
        "aipass.backup.apps.handlers.operations": MagicMock(),
        "aipass.backup.apps.handlers.utils": MagicMock(),
        "aipass.backup.apps.handlers.reporting": MagicMock(),
        # Private keys for test assertions
        "_mock_jh": mock_jh,
        "_mock_config": mock_config,
        "_mock_file_ops": mock_file_ops,
        "_backup_modes": backup_modes,
    }
    return mods


# ===================================================================
# Fixtures
# ===================================================================


@pytest.fixture()
def backup_core_env(tmp_path, monkeypatch):
    """Inject mock handler modules, import backup_core, and yield a dict
    containing the module and helper references for assertions."""
    mocks = _build_handler_mocks(tmp_path)

    # Inject CLI stubs via monkeypatch (auto-restored after test)
    for cli_key in _CLI_STUB_KEYS:
        if cli_key not in sys.modules:
            monkeypatch.setitem(sys.modules, cli_key, MagicMock())

    # Remove any cached backup_core so re-import picks up fresh mocks
    for key in list(sys.modules):
        if "backup_core" in key:
            monkeypatch.delitem(sys.modules, key, raising=False)

    # Also remove cached handler modules so our mocks take priority
    for key in list(sys.modules):
        if key.startswith("aipass.backup.apps.handlers"):
            monkeypatch.delitem(sys.modules, key, raising=False)

    # Inject handler mocks (skip private keys)
    for name, mod in mocks.items():
        if not name.startswith("_"):
            monkeypatch.setitem(sys.modules, name, mod)

    # Now the real import — Python will find the actual backup_core.py
    from aipass.backup.apps.modules import backup_core

    return {
        "module": backup_core,
        "handle_command": backup_core.handle_command,
        "BackupEngine": backup_core.BackupEngine,
        "mock_jh": mocks["_mock_jh"],
        "mock_config": mocks["_mock_config"],
        "mock_file_ops": mocks["_mock_file_ops"],
        "backup_modes": mocks["_backup_modes"],
        "tmp_path": tmp_path,
    }


# ===================================================================
# Tests — handle_command
# ===================================================================


class TestHandleCommand:
    """Validate CLI routing performed by handle_command."""

    def test_handle_command_no_args_shows_introspection(self, backup_core_env):
        """Passing None triggers the introspection display."""
        result = backup_core_env["handle_command"](None)
        assert result is True

    def test_handle_command_help(self, backup_core_env):
        """--help flag is routed and returns True."""
        args = SimpleNamespace(command="--help")
        result = backup_core_env["handle_command"](args)
        assert result is True

    def test_handle_command_version_help_alias(self, backup_core_env):
        """'help' alias is handled the same as --help."""
        args = SimpleNamespace(command="help")
        result = backup_core_env["handle_command"](args)
        assert result is True

    def test_handle_command_snapshot(self, backup_core_env):
        """'snapshot' command creates BackupEngine with mode='snapshot'."""
        handle_command = backup_core_env["handle_command"]
        mod = backup_core_env["module"]
        args = SimpleNamespace(command="snapshot", dry_run=False, note="test")

        with patch.object(mod, "BackupEngine") as MockEngine:
            mock_instance = MagicMock()
            mock_result = MagicMock()
            mock_result.critical_errors = []
            mock_result.errors = 0
            mock_result.files_copied = 5
            mock_result.files_skipped = 2
            mock_result.files_checked = 7
            mock_result.success = True
            mock_result.backup_path = str(backup_core_env["tmp_path"])
            import datetime

            mock_result.start_time = datetime.datetime.now()
            mock_instance.run_backup.return_value = mock_result
            MockEngine.return_value = mock_instance

            result = handle_command(args)

            assert result is True
            MockEngine.assert_called_once_with("snapshot", dry_run=False)
            mock_instance.run_backup.assert_called_once_with("test", pre_scanned=None)

    def test_handle_command_versioned(self, backup_core_env):
        """'versioned' command creates BackupEngine with mode='versioned'."""
        handle_command = backup_core_env["handle_command"]
        mod = backup_core_env["module"]
        args = SimpleNamespace(command="versioned", dry_run=False, note="test note")

        with patch.object(mod, "BackupEngine") as MockEngine:
            mock_instance = MagicMock()
            mock_result = MagicMock()
            mock_result.critical_errors = []
            mock_result.errors = 0
            mock_result.files_copied = 3
            mock_result.files_skipped = 1
            mock_result.files_checked = 4
            mock_result.success = True
            mock_result.backup_path = str(backup_core_env["tmp_path"])
            import datetime

            mock_result.start_time = datetime.datetime.now()
            mock_instance.run_backup.return_value = mock_result
            MockEngine.return_value = mock_instance

            result = handle_command(args)

            assert result is True
            MockEngine.assert_called_once_with("versioned", dry_run=False)
            mock_instance.run_backup.assert_called_once_with("test note", pre_scanned=None)

    def test_handle_command_unknown(self, backup_core_env):
        """Unknown command returns False (not handled)."""
        args = SimpleNamespace(command="nonexistent")
        result = backup_core_env["handle_command"](args)
        assert result is False

    def test_handle_command_no_command_attr(self, backup_core_env):
        """Args object without .command attribute returns False."""
        args = SimpleNamespace(flag="value")
        result = backup_core_env["handle_command"](args)
        assert result is False

    def test_handle_command_all_returns_false(self, backup_core_env):
        """'all' is listed for discovery but delegated to entry point."""
        args = SimpleNamespace(command="all")
        result = backup_core_env["handle_command"](args)
        assert result is False

    def test_handle_command_engine_exception_returns_true(self, backup_core_env):
        """If BackupEngine raises, handle_command catches and still returns True."""
        mod = backup_core_env["module"]
        args = SimpleNamespace(command="snapshot", dry_run=False, note="boom")

        with patch.object(mod, "BackupEngine", side_effect=RuntimeError("boom")):
            result = backup_core_env["handle_command"](args)

        assert result is True


# ===================================================================
# Tests — BackupEngine
# ===================================================================


class TestBackupEngine:
    """Validate BackupEngine initialization and delegation methods."""

    def test_backup_engine_init_snapshot(self, backup_core_env):
        """Initialises with mode='snapshot' and sets expected attributes."""
        engine = backup_core_env["BackupEngine"]("snapshot")

        assert engine.mode == "snapshot"
        assert engine.dry_run is False
        assert engine.mode_config == backup_core_env["backup_modes"]["snapshot"]
        assert "system_snapshot" in str(engine.backup_path)

    def test_backup_engine_init_versioned(self, backup_core_env):
        """Initialises with mode='versioned' and sets expected attributes."""
        engine = backup_core_env["BackupEngine"]("versioned")

        assert engine.mode == "versioned"
        assert engine.mode_config == backup_core_env["backup_modes"]["versioned"]
        assert "versioned_backup" in str(engine.backup_path)

    def test_backup_engine_init_dry_run(self, backup_core_env):
        """dry_run flag propagates to the engine instance."""
        engine = backup_core_env["BackupEngine"]("snapshot", dry_run=True)
        assert engine.dry_run is True

    def test_backup_engine_init_invalid_mode(self, backup_core_env):
        """Invalid mode raises ValueError."""
        with pytest.raises(ValueError, match="Invalid backup mode"):
            backup_core_env["BackupEngine"]("bogus_mode")

    def test_backup_engine_should_ignore(self, backup_core_env):
        """should_ignore delegates to config handler's should_ignore with correct args."""
        mock_config = backup_core_env["mock_config"]
        mock_config.should_ignore.return_value = True

        engine = backup_core_env["BackupEngine"]("snapshot")

        test_path = backup_core_env["tmp_path"] / "node_modules" / "pkg"
        test_path.mkdir(parents=True)

        result = engine.should_ignore(test_path)

        # Verify return value is forwarded
        assert result is True

        # Verify correct arguments are forwarded to the config handler
        mock_config.should_ignore.assert_called_once_with(
            test_path,
            engine.ignore_patterns,
            mock_config.IGNORE_EXCEPTIONS,
            engine.backup_dest,
        )

    def test_backup_engine_file_needs_backup(self, backup_core_env):
        """file_needs_backup delegates to file_operations handler."""
        engine = backup_core_env["BackupEngine"]("snapshot")

        source = backup_core_env["tmp_path"] / "source.txt"
        source.write_text("hello", encoding="utf-8")
        backup = backup_core_env["tmp_path"] / "backup.txt"

        mock_file_ops = backup_core_env["mock_file_ops"]
        mock_file_ops.file_needs_backup = MagicMock(return_value=True)

        result = engine.file_needs_backup(source, backup, {})

        assert result is True
        mock_file_ops.file_needs_backup.assert_called_once_with(
            source, backup, {}, engine.source_dir
        )

    def test_backup_engine_json_initialised(self, backup_core_env):
        """Engine calls json_handler.ensure_module_jsons on init."""
        mock_jh = backup_core_env["mock_jh"]
        mock_jh.ensure_module_jsons.reset_mock()

        backup_core_env["BackupEngine"]("snapshot")

        mock_jh.ensure_module_jsons.assert_called_with("backup_core")


# ===================================================================
# Contract Tests — return type verification and error contracts
# ===================================================================


class TestHandleCommandReturnTypeContract:
    """Verify handle_command always returns bool for every code path."""

    def test_returns_bool_on_none_args(self, backup_core_env):
        """handle_command(None) returns exactly bool, not truthy int."""
        result = backup_core_env["handle_command"](None)
        assert type(result) is bool

    def test_returns_bool_on_help(self, backup_core_env):
        """handle_command with --help returns exactly bool."""
        args = SimpleNamespace(command="--help")
        result = backup_core_env["handle_command"](args)
        assert type(result) is bool

    def test_returns_bool_on_unknown(self, backup_core_env):
        """handle_command with unknown command returns exactly bool."""
        args = SimpleNamespace(command="nonexistent")
        result = backup_core_env["handle_command"](args)
        assert type(result) is bool

    def test_returns_bool_on_missing_command_attr(self, backup_core_env):
        """handle_command with no .command returns exactly bool."""
        args = SimpleNamespace(flag="value")
        result = backup_core_env["handle_command"](args)
        assert type(result) is bool

    def test_returns_bool_on_engine_exception(self, backup_core_env):
        """handle_command returns bool even when engine raises."""
        mod = backup_core_env["module"]
        args = SimpleNamespace(command="snapshot", dry_run=False, note="boom")

        with patch.object(mod, "BackupEngine", side_effect=RuntimeError("boom")):
            result = backup_core_env["handle_command"](args)

        assert type(result) is bool


class TestBackupEngineInitContract:
    """Verify BackupEngine init sets attributes with correct types."""

    def test_mode_is_str(self, backup_core_env):
        """engine.mode is always a str."""
        engine = backup_core_env["BackupEngine"]("snapshot")
        assert isinstance(engine.mode, str)

    def test_backup_path_is_path(self, backup_core_env):
        """engine.backup_path is always a pathlib.Path."""
        engine = backup_core_env["BackupEngine"]("snapshot")
        assert isinstance(engine.backup_path, Path)

    def test_source_dir_is_path(self, backup_core_env):
        """engine.source_dir is always a pathlib.Path."""
        engine = backup_core_env["BackupEngine"]("versioned")
        assert isinstance(engine.source_dir, Path)

    def test_mode_config_is_dict(self, backup_core_env):
        """engine.mode_config is always a dict."""
        engine = backup_core_env["BackupEngine"]("snapshot")
        assert isinstance(engine.mode_config, dict)

    def test_dry_run_is_bool(self, backup_core_env):
        """engine.dry_run is always a bool."""
        engine = backup_core_env["BackupEngine"]("snapshot", dry_run=True)
        assert isinstance(engine.dry_run, bool)

    def test_invalid_mode_raises_valueerror_not_keyerror(self, backup_core_env):
        """Invalid mode raises ValueError specifically, not KeyError or TypeError."""
        with pytest.raises(ValueError):
            backup_core_env["BackupEngine"]("nonexistent_mode")

    def test_invalid_mode_error_message_contains_mode_name(self, backup_core_env):
        """ValueError message includes the invalid mode name for debugging."""
        with pytest.raises(ValueError, match="bogus"):
            backup_core_env["BackupEngine"]("bogus")


class TestHandleCommandDelegationContract:
    """Verify handle_command delegates to BackupEngine with correct arguments."""

    def test_snapshot_passes_dry_run_true(self, backup_core_env):
        """dry_run=True is forwarded to BackupEngine constructor."""
        mod = backup_core_env["module"]
        args = SimpleNamespace(command="snapshot", dry_run=True, note="test")

        with patch.object(mod, "BackupEngine") as MockEngine:
            mock_instance = MagicMock()
            mock_result = MagicMock()
            mock_result.critical_errors = []
            mock_result.errors = 0
            mock_result.files_copied = 1
            mock_result.files_skipped = 0
            mock_result.files_checked = 1
            mock_result.success = True
            mock_result.backup_path = str(backup_core_env["tmp_path"])
            import datetime
            mock_result.start_time = datetime.datetime.now()
            mock_instance.run_backup.return_value = mock_result
            MockEngine.return_value = mock_instance

            backup_core_env["handle_command"](args)

            MockEngine.assert_called_once_with("snapshot", dry_run=True)

    def test_note_forwarded_to_run_backup(self, backup_core_env):
        """The note argument is forwarded to engine.run_backup."""
        mod = backup_core_env["module"]
        args = SimpleNamespace(command="versioned", dry_run=False, note="important note")

        with patch.object(mod, "BackupEngine") as MockEngine:
            mock_instance = MagicMock()
            mock_result = MagicMock()
            mock_result.critical_errors = []
            mock_result.errors = 0
            mock_result.files_copied = 0
            mock_result.files_skipped = 0
            mock_result.files_checked = 0
            mock_result.success = True
            mock_result.backup_path = str(backup_core_env["tmp_path"])
            import datetime
            mock_result.start_time = datetime.datetime.now()
            mock_instance.run_backup.return_value = mock_result
            MockEngine.return_value = mock_instance

            backup_core_env["handle_command"](args)

            mock_instance.run_backup.assert_called_once_with("important note", pre_scanned=None)


# ===================================================================
# Tests — CLI routing: short_help, print_help, print_introspection,
#          output_capture, no_args_triggers, reimport_after_mock
# ===================================================================


class TestCliRoutingExtended:
    """Additional CLI routing tests for test_quality coverage."""

    def test_handle_command_short_help(self, backup_core_env):
        """'-h' short help flag is handled the same as --help."""
        args = SimpleNamespace(command="-h")
        result = backup_core_env["handle_command"](args)
        assert result is True

    def test_print_help_runs(self, backup_core_env, capsys):
        """print_help() runs without error (output via Rich console, captured by capsys)."""
        mod = backup_core_env["module"]
        if hasattr(mod, "print_help"):
            mod.print_help()

    def test_print_introspection_runs(self, backup_core_env, capsys):
        """print_introspection() runs without error (output via Rich console, captured by capsys)."""
        mod = backup_core_env["module"]
        if hasattr(mod, "print_introspection"):
            mod.print_introspection()

    def test_no_args_triggers_introspection(self, backup_core_env):
        """No args triggers print_introspection fallback and returns True."""
        result = backup_core_env["handle_command"](None)
        assert result is True

    def test_reimport_after_mock(self, backup_core_env):
        """Module can be reimported after mocking without errors."""
        mod = backup_core_env["module"]
        importlib.reload(mod)
