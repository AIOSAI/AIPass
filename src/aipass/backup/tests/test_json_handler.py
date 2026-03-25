"""Tests for json_handler — JSON auto-creating handler with FIFO rotation."""

import json
from pathlib import Path
from unittest.mock import patch


class TestGetDefaultTemplate:
    """_get_default_template returns inline default structures by json_type."""

    def test_get_default_template_config(self):
        """Config template returns dict with version key."""
        from aipass.backup.apps.handlers.json.json_handler import _get_default_template

        result = _get_default_template("config", "test_module")

        assert isinstance(result, dict)
        assert "version" in result
        assert result["module_name"] == "test_module"
        assert "config" in result

    def test_get_default_template_data(self):
        """Data template returns dict with created and last_updated keys."""
        from aipass.backup.apps.handlers.json.json_handler import _get_default_template

        result = _get_default_template("data", "test_module")

        assert isinstance(result, dict)
        assert "created" in result
        assert "last_updated" in result

    def test_get_default_template_log(self):
        """Log template returns an empty list."""
        from aipass.backup.apps.handlers.json.json_handler import _get_default_template

        result = _get_default_template("log", "test_module")

        assert isinstance(result, list)
        assert len(result) == 0

    def test_get_default_template_unknown(self):
        """Unknown json_type raises ValueError."""
        import pytest
        from aipass.backup.apps.handlers.json.json_handler import _get_default_template

        with pytest.raises(ValueError, match="Unknown json_type"):
            _get_default_template("unknown_type", "test_module")


class TestValidateJsonStructure:
    """validate_json_structure checks data matches expected type schema."""

    def test_validate_json_structure_config_valid(self):
        """Valid config with all required keys passes validation."""
        from aipass.backup.apps.handlers.json.json_handler import validate_json_structure

        data = {
            "module_name": "test",
            "version": "1.0.0",
            "config": {"enabled": True}
        }

        assert validate_json_structure(data, "config") is True

    def test_validate_json_structure_config_invalid(self):
        """Config missing required keys fails validation."""
        from aipass.backup.apps.handlers.json.json_handler import validate_json_structure

        data = {"module_name": "test"}  # missing version, config

        assert validate_json_structure(data, "config") is False

    def test_validate_json_structure_config_not_dict(self):
        """Config that is not a dict fails validation."""
        from aipass.backup.apps.handlers.json.json_handler import validate_json_structure

        assert validate_json_structure(["not", "a", "dict"], "config") is False

    def test_validate_json_structure_data_valid(self):
        """Valid data with created and last_updated passes."""
        from aipass.backup.apps.handlers.json.json_handler import validate_json_structure

        data = {"created": "2026-01-01", "last_updated": "2026-01-01"}

        assert validate_json_structure(data, "data") is True

    def test_validate_json_structure_data_invalid(self):
        """Data missing required keys fails."""
        from aipass.backup.apps.handlers.json.json_handler import validate_json_structure

        assert validate_json_structure({"created": "2026-01-01"}, "data") is False

    def test_validate_json_structure_log_valid(self):
        """Valid log (a list) passes validation."""
        from aipass.backup.apps.handlers.json.json_handler import validate_json_structure

        assert validate_json_structure([], "log") is True
        assert validate_json_structure([{"entry": 1}], "log") is True

    def test_validate_json_structure_log_invalid(self):
        """Log that is not a list fails validation."""
        from aipass.backup.apps.handlers.json.json_handler import validate_json_structure

        assert validate_json_structure({"not": "a list"}, "log") is False

    def test_validate_json_structure_unknown_type(self):
        """Unknown json_type always returns False."""
        from aipass.backup.apps.handlers.json.json_handler import validate_json_structure

        assert validate_json_structure({}, "nonexistent") is False


class TestGetJsonPath:
    """get_json_path constructs correct file paths."""

    def test_get_json_path_format(self):
        """Path uses {module_name}_{json_type}.json naming under BACKUP_JSON_DIR."""
        from aipass.backup.apps.handlers.json.json_handler import (
            get_json_path, BACKUP_JSON_DIR
        )

        result = get_json_path("my_module", "config")

        assert result == BACKUP_JSON_DIR / "my_module_config.json"
        assert result.name == "my_module_config.json"

    def test_get_json_path_returns_path_object(self):
        """Return type is always a pathlib.Path."""
        from aipass.backup.apps.handlers.json.json_handler import get_json_path

        result = get_json_path("test", "log")

        assert isinstance(result, Path)


class TestEnsureJsonExists:
    """ensure_json_exists creates JSON files from templates when missing."""

    def test_ensure_json_exists_creates_file(self, tmp_path, monkeypatch):
        """Creates file from default template when file does not exist."""
        import aipass.backup.apps.handlers.json.json_handler as jh

        json_dir = tmp_path / "backup_json"
        monkeypatch.setattr(jh, "BACKUP_JSON_DIR", json_dir)

        result = jh.ensure_json_exists("test_mod", "config")

        assert result is True
        created_file = json_dir / "test_mod_config.json"
        assert created_file.exists()

        with open(created_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["module_name"] == "test_mod"
        assert "version" in data

    def test_ensure_json_exists_leaves_existing(self, tmp_path, monkeypatch):
        """Does not overwrite an existing valid JSON file."""
        import aipass.backup.apps.handlers.json.json_handler as jh

        json_dir = tmp_path / "backup_json"
        json_dir.mkdir(parents=True)

        existing_data = {
            "module_name": "existing",
            "version": "2.0.0",
            "config": {"custom": True}
        }
        file_path = json_dir / "existing_config.json"
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(existing_data, f)

        monkeypatch.setattr(jh, "BACKUP_JSON_DIR", json_dir)

        result = jh.ensure_json_exists("existing", "config")

        assert result is True
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["version"] == "2.0.0"
        assert data["config"]["custom"] is True

    def test_ensure_json_exists_regenerates_corrupted(self, tmp_path, monkeypatch):
        """Regenerates file when existing JSON is structurally invalid."""
        import aipass.backup.apps.handlers.json.json_handler as jh

        json_dir = tmp_path / "backup_json"
        json_dir.mkdir(parents=True)

        # Write a valid JSON file but with wrong structure for config type
        file_path = json_dir / "broken_config.json"
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump({"wrong_keys": True}, f)

        monkeypatch.setattr(jh, "BACKUP_JSON_DIR", json_dir)

        result = jh.ensure_json_exists("broken", "config")

        assert result is True
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Should have been regenerated with default template
        assert "module_name" in data
        assert "version" in data


class TestLoadJson:
    """load_json loads existing files or auto-creates missing ones."""

    def test_load_json_returns_data(self, tmp_path, monkeypatch):
        """Loads and returns data from an existing JSON file."""
        import aipass.backup.apps.handlers.json.json_handler as jh

        json_dir = tmp_path / "backup_json"
        json_dir.mkdir(parents=True)

        test_data = {"created": "2026-01-01", "last_updated": "2026-03-24"}
        file_path = json_dir / "mymod_data.json"
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(test_data, f)

        monkeypatch.setattr(jh, "BACKUP_JSON_DIR", json_dir)

        result = jh.load_json("mymod", "data")

        assert result is not None
        assert result["created"] == "2026-01-01"
        assert result["last_updated"] == "2026-03-24"

    def test_load_json_missing_creates(self, tmp_path, monkeypatch):
        """Auto-creates file from template when it does not exist."""
        import aipass.backup.apps.handlers.json.json_handler as jh

        json_dir = tmp_path / "backup_json"
        monkeypatch.setattr(jh, "BACKUP_JSON_DIR", json_dir)

        result = jh.load_json("newmod", "log")

        assert result is not None
        assert isinstance(result, list)
        assert len(result) == 0


class TestSaveJson:
    """save_json writes validated data to disk."""

    def test_save_json_writes_data(self, tmp_path, monkeypatch):
        """Saves data to file and it can be read back."""
        import aipass.backup.apps.handlers.json.json_handler as jh

        json_dir = tmp_path / "backup_json"
        json_dir.mkdir(parents=True)

        data = {
            "module_name": "saver",
            "version": "1.0.0",
            "config": {"enabled": True, "max_log_entries": 50}
        }

        monkeypatch.setattr(jh, "BACKUP_JSON_DIR", json_dir)

        result = jh.save_json("saver", "config", data)

        assert result is True
        file_path = json_dir / "saver_config.json"
        assert file_path.exists()

        with open(file_path, "r", encoding="utf-8") as f:
            written = json.load(f)
        assert written["version"] == "1.0.0"

    def test_save_json_rejects_invalid_structure(self, tmp_path, monkeypatch):
        """Raises ValueError when data does not match json_type schema."""
        import pytest
        import aipass.backup.apps.handlers.json.json_handler as jh

        json_dir = tmp_path / "backup_json"
        json_dir.mkdir(parents=True)

        monkeypatch.setattr(jh, "BACKUP_JSON_DIR", json_dir)

        with pytest.raises(ValueError, match="Invalid structure"):
            jh.save_json("test", "config", {"bad": "data"})

    def test_save_json_updates_last_updated_for_data(self, tmp_path, monkeypatch):
        """Saving data type auto-updates the last_updated field."""
        import aipass.backup.apps.handlers.json.json_handler as jh

        json_dir = tmp_path / "backup_json"
        json_dir.mkdir(parents=True)

        data = {"created": "2025-01-01", "last_updated": "2025-01-01"}

        monkeypatch.setattr(jh, "BACKUP_JSON_DIR", json_dir)

        jh.save_json("ts_mod", "data", data)

        file_path = json_dir / "ts_mod_data.json"
        with open(file_path, "r", encoding="utf-8") as f:
            written = json.load(f)
        # last_updated should have been refreshed to today
        assert written["last_updated"] != "2025-01-01"


class TestLogOperation:
    """log_operation adds entries and implements FIFO rotation."""

    def test_log_operation_adds_entry(self, tmp_path, monkeypatch):
        """New entry is appended to the log file."""
        import aipass.backup.apps.handlers.json.json_handler as jh

        json_dir = tmp_path / "backup_json"
        json_dir.mkdir(parents=True)

        # Pre-create config with max_log_entries
        config = {
            "module_name": "logger",
            "version": "1.0.0",
            "config": {"enabled": True, "max_log_entries": 100}
        }
        with open(json_dir / "logger_config.json", "w", encoding="utf-8") as f:
            json.dump(config, f)

        # Pre-create empty log
        with open(json_dir / "logger_log.json", "w", encoding="utf-8") as f:
            json.dump([], f)

        # Pre-create data
        data = {"created": "2026-01-01", "last_updated": "2026-01-01"}
        with open(json_dir / "logger_data.json", "w", encoding="utf-8") as f:
            json.dump(data, f)

        monkeypatch.setattr(jh, "BACKUP_JSON_DIR", json_dir)

        result = jh.log_operation("test_op", {"key": "value"}, module_name="logger")

        assert result is True
        with open(json_dir / "logger_log.json", "r", encoding="utf-8") as f:
            log = json.load(f)
        assert len(log) == 1
        assert log[0]["operation"] == "test_op"
        assert log[0]["data"]["key"] == "value"
        assert "timestamp" in log[0]

    def test_log_operation_fifo_rotation(self, tmp_path, monkeypatch):
        """Old entries are removed when max_log_entries is exceeded."""
        import aipass.backup.apps.handlers.json.json_handler as jh

        json_dir = tmp_path / "backup_json"
        json_dir.mkdir(parents=True)

        max_entries = 3

        # Config with a small max_log_entries
        config = {
            "module_name": "rotator",
            "version": "1.0.0",
            "config": {"enabled": True, "max_log_entries": max_entries}
        }
        with open(json_dir / "rotator_config.json", "w", encoding="utf-8") as f:
            json.dump(config, f)

        # Pre-fill log with max_entries entries
        existing_log = [
            {"timestamp": f"2026-01-0{i}", "operation": f"old_op_{i}"}
            for i in range(1, max_entries + 1)
        ]
        with open(json_dir / "rotator_log.json", "w", encoding="utf-8") as f:
            json.dump(existing_log, f)

        # Pre-create data
        data = {"created": "2026-01-01", "last_updated": "2026-01-01"}
        with open(json_dir / "rotator_data.json", "w", encoding="utf-8") as f:
            json.dump(data, f)

        monkeypatch.setattr(jh, "BACKUP_JSON_DIR", json_dir)

        # Add one more entry to trigger rotation
        result = jh.log_operation("new_op", module_name="rotator")

        assert result is True
        with open(json_dir / "rotator_log.json", "r", encoding="utf-8") as f:
            log = json.load(f)
        # Should still be at max_entries (oldest removed)
        assert len(log) == max_entries
        # Oldest entry should have been dropped
        assert log[0]["operation"] == "old_op_2"
        # Newest entry should be last
        assert log[-1]["operation"] == "new_op"


# --- Contract: return type verification ---


class TestReturnTypeContracts:
    """Every public function returns the documented type."""

    def test_get_json_path_returns_path(self):
        """get_json_path always returns pathlib.Path."""
        from aipass.backup.apps.handlers.json.json_handler import get_json_path

        result = get_json_path("mod", "config")
        assert isinstance(result, Path)

    def test_get_json_path_child_of_backup_json_dir(self):
        """Returned path is always under BACKUP_JSON_DIR."""
        from aipass.backup.apps.handlers.json.json_handler import get_json_path, BACKUP_JSON_DIR

        result = get_json_path("any_module", "log")
        assert result.parent == BACKUP_JSON_DIR

    def test_ensure_json_exists_returns_bool(self, tmp_path, monkeypatch):
        """ensure_json_exists returns exactly bool."""
        import aipass.backup.apps.handlers.json.json_handler as jh

        json_dir = tmp_path / "bj"
        monkeypatch.setattr(jh, "BACKUP_JSON_DIR", json_dir)

        result = jh.ensure_json_exists("test", "config")
        assert type(result) is bool

    def test_ensure_module_jsons_returns_bool(self, tmp_path, monkeypatch):
        """ensure_module_jsons returns exactly bool True."""
        import aipass.backup.apps.handlers.json.json_handler as jh

        json_dir = tmp_path / "bj"
        monkeypatch.setattr(jh, "BACKUP_JSON_DIR", json_dir)

        result = jh.ensure_module_jsons("test_mod")
        assert type(result) is bool
        assert result is True

    def test_load_json_returns_dict_for_config(self, tmp_path, monkeypatch):
        """load_json for config type returns a dict."""
        import aipass.backup.apps.handlers.json.json_handler as jh

        json_dir = tmp_path / "bj"
        monkeypatch.setattr(jh, "BACKUP_JSON_DIR", json_dir)

        result = jh.load_json("mod", "config")
        assert isinstance(result, dict)

    def test_load_json_returns_list_for_log(self, tmp_path, monkeypatch):
        """load_json for log type returns a list."""
        import aipass.backup.apps.handlers.json.json_handler as jh

        json_dir = tmp_path / "bj"
        monkeypatch.setattr(jh, "BACKUP_JSON_DIR", json_dir)

        result = jh.load_json("mod", "log")
        assert isinstance(result, list)

    def test_save_json_returns_bool(self, tmp_path, monkeypatch):
        """save_json returns exactly bool True on success."""
        import aipass.backup.apps.handlers.json.json_handler as jh

        json_dir = tmp_path / "bj"
        json_dir.mkdir(parents=True)
        monkeypatch.setattr(jh, "BACKUP_JSON_DIR", json_dir)

        data = {"module_name": "t", "version": "1.0.0", "config": {}}
        result = jh.save_json("t", "config", data)
        assert type(result) is bool
        assert result is True

    def test_log_operation_returns_bool(self, tmp_path, monkeypatch):
        """log_operation returns exactly bool."""
        import aipass.backup.apps.handlers.json.json_handler as jh

        json_dir = tmp_path / "bj"
        monkeypatch.setattr(jh, "BACKUP_JSON_DIR", json_dir)

        result = jh.log_operation("test", module_name="rt_mod")
        assert type(result) is bool

    def test_validate_json_structure_returns_bool(self):
        """validate_json_structure always returns exactly bool."""
        from aipass.backup.apps.handlers.json.json_handler import validate_json_structure

        assert type(validate_json_structure({}, "config")) is bool
        assert type(validate_json_structure([], "log")) is bool
        assert type(validate_json_structure({}, "unknown")) is bool


class TestErrorContracts:
    """Error contracts for json_handler functions."""

    def test_get_default_template_unknown_raises_valueerror(self):
        """_get_default_template raises ValueError (not KeyError) for unknown types."""
        import pytest
        from aipass.backup.apps.handlers.json.json_handler import _get_default_template

        with pytest.raises(ValueError):
            _get_default_template("bogus", "mod")

    def test_save_json_invalid_raises_valueerror(self, tmp_path, monkeypatch):
        """save_json raises ValueError (not TypeError) for invalid structure."""
        import pytest
        import aipass.backup.apps.handlers.json.json_handler as jh

        json_dir = tmp_path / "bj"
        json_dir.mkdir(parents=True)
        monkeypatch.setattr(jh, "BACKUP_JSON_DIR", json_dir)

        with pytest.raises(ValueError):
            jh.save_json("t", "config", [])  # list is wrong for config

    def test_save_json_error_message_mentions_type(self, tmp_path, monkeypatch):
        """ValueError from save_json includes the json_type for debugging."""
        import pytest
        import aipass.backup.apps.handlers.json.json_handler as jh

        json_dir = tmp_path / "bj"
        json_dir.mkdir(parents=True)
        monkeypatch.setattr(jh, "BACKUP_JSON_DIR", json_dir)

        with pytest.raises(ValueError, match="config"):
            jh.save_json("t", "config", {"wrong": True})


class TestEnsureModuleJsonsContract:
    """ensure_module_jsons creates exactly 3 files."""

    def test_creates_three_files(self, tmp_path, monkeypatch):
        """Creates config, data, and log JSON files."""
        import aipass.backup.apps.handlers.json.json_handler as jh

        json_dir = tmp_path / "bj"
        monkeypatch.setattr(jh, "BACKUP_JSON_DIR", json_dir)

        jh.ensure_module_jsons("triple")

        assert (json_dir / "triple_config.json").exists()
        assert (json_dir / "triple_data.json").exists()
        assert (json_dir / "triple_log.json").exists()

    def test_config_file_is_valid_structure(self, tmp_path, monkeypatch):
        """Config file created by ensure_module_jsons passes validation."""
        import aipass.backup.apps.handlers.json.json_handler as jh

        json_dir = tmp_path / "bj"
        monkeypatch.setattr(jh, "BACKUP_JSON_DIR", json_dir)

        jh.ensure_module_jsons("valid_mod")

        with open(json_dir / "valid_mod_config.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        assert jh.validate_json_structure(data, "config") is True
