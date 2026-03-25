"""Tests for config_handler and ignore_patterns — backup configuration and filtering."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


def _import_config_handler(monkeypatch):
    """Import config_handler after ensuring json_handler is mocked.

    The conftest autouse fixture clears aipass.backup.apps.* from sys.modules.
    ignore_patterns.py calls json_handler.log_operation() at module level,
    so we must inject a mock json_handler module before importing.

    Uses monkeypatch for cleanup-safe sys.modules mutation.
    """
    mock_jh = MagicMock()
    mock_jh.log_operation = MagicMock(return_value=True)
    monkeypatch.setitem(sys.modules, "aipass.backup.apps.handlers.json.json_handler", mock_jh)
    monkeypatch.setitem(sys.modules, "aipass.backup.apps.handlers.json", MagicMock())

    from aipass.backup.apps.handlers.config import config_handler
    return config_handler


def _import_ignore_patterns(monkeypatch):
    """Import ignore_patterns after ensuring json_handler is mocked.

    Uses monkeypatch for cleanup-safe sys.modules mutation.
    """
    mock_jh = MagicMock()
    mock_jh.log_operation = MagicMock(return_value=True)
    monkeypatch.setitem(sys.modules, "aipass.backup.apps.handlers.json.json_handler", mock_jh)
    monkeypatch.setitem(sys.modules, "aipass.backup.apps.handlers.json", MagicMock())

    from aipass.backup.apps.handlers.config import ignore_patterns
    return ignore_patterns


class TestBackupModes:
    """BACKUP_MODES dictionary contains expected mode configurations."""

    def test_backup_modes_has_snapshot(self, monkeypatch):
        """BACKUP_MODES contains a 'snapshot' key."""
        ch = _import_config_handler(monkeypatch)
        assert "snapshot" in ch.BACKUP_MODES

    def test_backup_modes_has_versioned(self, monkeypatch):
        """BACKUP_MODES contains a 'versioned' key."""
        ch = _import_config_handler(monkeypatch)
        assert "versioned" in ch.BACKUP_MODES

    def test_backup_mode_snapshot_keys(self, monkeypatch):
        """Snapshot mode has all required configuration keys."""
        ch = _import_config_handler(monkeypatch)
        snapshot = ch.BACKUP_MODES["snapshot"]
        required_keys = ["name", "description", "destination", "folder_name", "behavior"]
        for key in required_keys:
            assert key in snapshot, f"Missing key: {key}"

    def test_backup_mode_snapshot_behavior(self, monkeypatch):
        """Snapshot mode behavior is 'dynamic'."""
        ch = _import_config_handler(monkeypatch)
        assert ch.BACKUP_MODES["snapshot"]["behavior"] == "dynamic"

    def test_backup_mode_versioned_behavior(self, monkeypatch):
        """Versioned mode behavior is 'versioned'."""
        ch = _import_config_handler(monkeypatch)
        assert ch.BACKUP_MODES["versioned"]["behavior"] == "versioned"


class TestShouldIgnore:
    """should_ignore pattern matching for backup file filtering."""

    def test_should_ignore_matches_pattern(self, monkeypatch):
        """Returns True for paths matching ignore patterns."""
        ip = _import_ignore_patterns(monkeypatch)
        result = ip.should_ignore(
            Path("/home/user/project/__pycache__"),
            ignore_patterns=["__pycache__"],
            exceptions=[]
        )
        assert result is True

    def test_should_ignore_matches_wildcard_pattern(self, monkeypatch):
        """Returns True for paths matching wildcard ignore patterns."""
        ip = _import_ignore_patterns(monkeypatch)
        result = ip.should_ignore(
            Path("/home/user/project/module.pyc"),
            ignore_patterns=["*.pyc"],
            exceptions=[]
        )
        assert result is True

    def test_should_ignore_allows_clean_path(self, monkeypatch):
        """Returns False for paths that do not match any ignore pattern."""
        ip = _import_ignore_patterns(monkeypatch)
        result = ip.should_ignore(
            Path("/home/user/project/main.py"),
            ignore_patterns=["__pycache__", "*.pyc", "node_modules"],
            exceptions=[]
        )
        assert result is False

    def test_should_ignore_respects_exceptions(self, monkeypatch):
        """Exception patterns override ignore patterns, preventing ignore."""
        ip = _import_ignore_patterns(monkeypatch)
        result = ip.should_ignore(
            Path("/home/user/project/.gitignore"),
            ignore_patterns=[".gitignore"],
            exceptions=[".gitignore"]
        )
        assert result is False

    def test_should_ignore_backup_destination(self, monkeypatch):
        """Always ignores paths inside the backup destination."""
        ip = _import_ignore_patterns(monkeypatch)
        backup_dest = Path("/home/user/backups")
        result = ip.should_ignore(
            Path("/home/user/backups/some_file.py"),
            ignore_patterns=[],
            exceptions=[],
            backup_dest=backup_dest
        )
        assert result is True


class TestIgnorePatternConstants:
    """Module-level pattern constants are loaded correctly from JSON.

    NOTE: These tests read the real ignore_patterns.json from the source tree.
    This is intentional — they verify that the JSON file ships with correct
    content. The json_handler dependency is still mocked to avoid side effects.
    """

    def test_global_ignore_patterns_not_empty(self, monkeypatch):
        """GLOBAL_IGNORE_PATTERNS has at least one entry."""
        ip = _import_ignore_patterns(monkeypatch)
        assert isinstance(ip.GLOBAL_IGNORE_PATTERNS, list)
        assert len(ip.GLOBAL_IGNORE_PATTERNS) > 0

    def test_global_ignore_patterns_contains_pycache(self, monkeypatch):
        """GLOBAL_IGNORE_PATTERNS includes __pycache__ as a basic sanity check."""
        ip = _import_ignore_patterns(monkeypatch)
        assert "__pycache__" in ip.GLOBAL_IGNORE_PATTERNS

    def test_source_whitelist_is_list(self, monkeypatch):
        """SOURCE_WHITELIST is a list."""
        ip = _import_ignore_patterns(monkeypatch)
        assert isinstance(ip.SOURCE_WHITELIST, list)

    def test_max_file_size_is_positive(self, monkeypatch):
        """MAX_FILE_SIZE_MB is a positive number."""
        ip = _import_ignore_patterns(monkeypatch)
        assert isinstance(ip.MAX_FILE_SIZE_MB, (int, float))
        assert ip.MAX_FILE_SIZE_MB > 0


# ─── Contract: BACKUP_MODES structure ────────────────────


class TestBackupModesStructureContract:
    """BACKUP_MODES has the correct type and complete structure for every mode."""

    def test_backup_modes_is_dict(self, monkeypatch):
        """BACKUP_MODES is a dict."""
        ch = _import_config_handler(monkeypatch)
        assert isinstance(ch.BACKUP_MODES, dict)

    def test_every_mode_has_usage_key(self, monkeypatch):
        """Every mode entry has a 'usage' key."""
        ch = _import_config_handler(monkeypatch)
        for mode_name, mode_config in ch.BACKUP_MODES.items():
            assert "usage" in mode_config, f"Mode '{mode_name}' missing 'usage' key"

    def test_every_mode_has_all_required_keys(self, monkeypatch):
        """Every mode entry has all 6 required configuration keys."""
        ch = _import_config_handler(monkeypatch)
        required = ["name", "description", "destination", "folder_name", "behavior", "usage"]
        for mode_name, mode_config in ch.BACKUP_MODES.items():
            for key in required:
                assert key in mode_config, f"Mode '{mode_name}' missing key: {key}"

    def test_versioned_mode_has_all_required_keys(self, monkeypatch):
        """Versioned mode specifically has all required keys."""
        ch = _import_config_handler(monkeypatch)
        versioned = ch.BACKUP_MODES["versioned"]
        required = ["name", "description", "destination", "folder_name", "behavior", "usage"]
        for key in required:
            assert key in versioned, f"Versioned mode missing key: {key}"

    def test_mode_values_are_strings(self, monkeypatch):
        """All mode configuration values are strings."""
        ch = _import_config_handler(monkeypatch)
        for mode_name, mode_config in ch.BACKUP_MODES.items():
            for key, value in mode_config.items():
                assert isinstance(value, str), (
                    f"Mode '{mode_name}', key '{key}' is {type(value).__name__}, expected str"
                )

    def test_destinations_are_absolute_paths(self, monkeypatch):
        """Destination values are absolute paths (start with /)."""
        ch = _import_config_handler(monkeypatch)
        for mode_name, mode_config in ch.BACKUP_MODES.items():
            dest = mode_config["destination"]
            assert Path(dest).is_absolute(), (
                f"Mode '{mode_name}' destination is not absolute: {dest}"
            )


class TestShouldIgnoreReturnTypeContract:
    """should_ignore always returns exactly bool."""

    def test_returns_bool_true_type(self, monkeypatch):
        """Returns exactly bool True, not truthy value."""
        ip = _import_ignore_patterns(monkeypatch)
        result = ip.should_ignore(
            Path("/project/__pycache__"),
            ignore_patterns=["__pycache__"],
            exceptions=[]
        )
        assert type(result) is bool

    def test_returns_bool_false_type(self, monkeypatch):
        """Returns exactly bool False, not falsy value."""
        ip = _import_ignore_patterns(monkeypatch)
        result = ip.should_ignore(
            Path("/project/main.py"),
            ignore_patterns=["__pycache__"],
            exceptions=[]
        )
        assert type(result) is bool


class TestGetBackupDestinationContract:
    """get_backup_destination returns str and falls back correctly."""

    def test_returns_str(self, monkeypatch):
        """Return value is always a str."""
        ch = _import_config_handler(monkeypatch)
        # Mock json_handler.log_operation to avoid real I/O
        with patch.object(ch, "json_handler"):
            result = ch.get_backup_destination("system_snapshot")
        assert isinstance(result, str)

    def test_known_system_returns_destination(self, monkeypatch):
        """Known system name returns matching destination."""
        ch = _import_config_handler(monkeypatch)
        with patch.object(ch, "json_handler"):
            result = ch.get_backup_destination("system_snapshot")
        assert result == ch.BACKUP_DESTINATIONS["system_snapshot"]

    def test_unknown_system_falls_back_to_base(self, monkeypatch):
        """Unknown system name falls back to BASE_BACKUP_DIR."""
        ch = _import_config_handler(monkeypatch)
        with patch.object(ch, "json_handler"):
            result = ch.get_backup_destination("nonexistent_system")
        assert result == ch.BASE_BACKUP_DIR
