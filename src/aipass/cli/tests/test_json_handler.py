"""Unit tests for CLI json_handler -- file I/O, validation, rotation."""

import json
import pytest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from aipass.cli.apps.handlers.json import json_handler
from aipass.cli.apps.handlers.json.json_handler import (
    _create_default,
    ensure_module_jsons,
    validate_json_structure,
    get_json_path,
)


# =============================================================================
# _create_default tests
# =============================================================================


class TestCreateDefault:
    """Tests for _create_default()."""

    def test_config_returns_dict_with_required_keys(self):
        """Config default must include module_name, version, config, created."""
        result = _create_default("config", "mymod")

        assert isinstance(result, dict)
        assert result["module_name"] == "mymod"
        assert result["version"] == "1.0.0"
        assert "config" in result
        assert result["config"]["max_log_entries"] == 100
        assert result["created"] == datetime.now().date().isoformat()

    def test_data_returns_dict_with_dates(self):
        """Data default must include created and last_updated."""
        result = _create_default("data", "mymod")
        today = datetime.now().date().isoformat()

        assert isinstance(result, dict)
        assert result["module_name"] == "mymod"
        assert result["created"] == today
        assert result["last_updated"] == today

    def test_log_returns_empty_list(self):
        """Log default must be an empty list."""
        result = _create_default("log", "mymod")

        assert result == []

    def test_unknown_type_raises_value_error(self):
        """Unknown json_type must raise ValueError."""
        with pytest.raises(ValueError, match="Unknown json_type"):
            _create_default("banana", "mymod")


# =============================================================================
# validate_json_structure tests
# =============================================================================


class TestValidateJsonStructure:
    """Tests for validate_json_structure()."""

    def test_valid_config(self):
        """Valid config dict returns True."""
        data = {"module_name": "x", "version": "1.0.0", "config": {}}
        assert validate_json_structure(data, "config") is True

    def test_config_missing_key(self):
        """Config missing a required key returns False."""
        data = {"module_name": "x", "version": "1.0.0"}
        assert validate_json_structure(data, "config") is False

    def test_config_not_dict(self):
        """Non-dict config returns False."""
        assert validate_json_structure([1, 2], "config") is False

    def test_valid_data(self):
        """Valid data dict returns True."""
        data = {"created": "2026-01-01", "last_updated": "2026-01-01"}
        assert validate_json_structure(data, "data") is True

    def test_data_missing_key(self):
        """Data missing last_updated returns False."""
        data = {"created": "2026-01-01"}
        assert validate_json_structure(data, "data") is False

    def test_data_not_dict(self):
        """Non-dict data returns False."""
        assert validate_json_structure("nope", "data") is False

    def test_valid_log(self):
        """List validates as log."""
        assert validate_json_structure([], "log") is True
        assert validate_json_structure([{"a": 1}], "log") is True

    def test_log_not_list(self):
        """Non-list log returns False."""
        assert validate_json_structure({}, "log") is False

    def test_unknown_type_returns_false(self):
        """Unknown json_type returns False (never raises)."""
        assert validate_json_structure({}, "mystery") is False


# =============================================================================
# get_json_path tests
# =============================================================================


class TestGetJsonPath:
    """Tests for get_json_path()."""

    def test_returns_correct_path(self):
        """Path is JSON_DIR / '{module}_{type}.json'."""
        result = get_json_path("cli", "config")

        assert result == json_handler.JSON_DIR / "cli_config.json"
        assert isinstance(result, Path)

    def test_path_uses_module_and_type(self):
        """Different module/type combos produce different filenames."""
        a = get_json_path("alpha", "log")
        b = get_json_path("beta", "data")

        assert a.name == "alpha_log.json"
        assert b.name == "beta_data.json"


# =============================================================================
# ensure_json_exists tests
# =============================================================================


class TestEnsureJsonExists:
    """Tests for ensure_json_exists()."""

    def test_creates_file_when_missing(self, tmp_path):
        """File should be created with default content when it does not exist."""
        with patch.object(json_handler, "JSON_DIR", tmp_path):
            result = json_handler.ensure_json_exists("cli", "config")

        assert result is True

        created = tmp_path / "cli_config.json"
        assert created.exists()

        data = json.loads(created.read_text(encoding="utf-8"))
        assert data["module_name"] == "cli"
        assert data["version"] == "1.0.0"

    def test_preserves_valid_existing_file(self, tmp_path):
        """Valid existing file should not be overwritten."""
        target = tmp_path / "cli_data.json"
        original = {
            "created": "2025-01-01",
            "last_updated": "2025-06-01",
            "custom_key": "preserve_me",
        }
        target.write_text(json.dumps(original), encoding="utf-8")

        with patch.object(json_handler, "JSON_DIR", tmp_path):
            json_handler.ensure_json_exists("cli", "data")

        data = json.loads(target.read_text(encoding="utf-8"))
        assert data["custom_key"] == "preserve_me"

    def test_regenerates_corrupted_file(self, tmp_path):
        """Corrupted (invalid JSON) file should be regenerated."""
        target = tmp_path / "cli_log.json"
        target.write_text("NOT VALID JSON{{{", encoding="utf-8")

        with patch.object(json_handler, "JSON_DIR", tmp_path):
            json_handler.ensure_json_exists("cli", "log")

        data = json.loads(target.read_text(encoding="utf-8"))
        assert data == []

    def test_regenerates_structurally_invalid_file(self, tmp_path):
        """File with valid JSON but wrong structure should be regenerated."""
        target = tmp_path / "cli_config.json"
        target.write_text(json.dumps({"wrong": "structure"}), encoding="utf-8")

        with patch.object(json_handler, "JSON_DIR", tmp_path):
            json_handler.ensure_json_exists("cli", "config")

        data = json.loads(target.read_text(encoding="utf-8"))
        assert data["module_name"] == "cli"
        assert data["version"] == "1.0.0"
        assert "config" in data


# =============================================================================
# load_json tests
# =============================================================================


class TestLoadJson:
    """Tests for load_json()."""

    def test_load_creates_and_returns_default(self, tmp_path):
        """Loading a missing file should auto-create it and return content."""
        with patch.object(json_handler, "JSON_DIR", tmp_path):
            result = json_handler.load_json("cli", "log")

        assert result == []

    def test_load_returns_existing_content(self, tmp_path):
        """Loading an existing valid file returns its content."""
        target = tmp_path / "cli_data.json"
        payload = {"created": "2025-01-01", "last_updated": "2025-06-15", "x": 42}
        target.write_text(json.dumps(payload), encoding="utf-8")

        with patch.object(json_handler, "JSON_DIR", tmp_path):
            result = json_handler.load_json("cli", "data")

        assert isinstance(result, dict)
        assert result["x"] == 42


# =============================================================================
# save_json tests
# =============================================================================


class TestSaveJson:
    """Tests for save_json()."""

    def test_saves_valid_data(self, tmp_path):
        """Valid data should be written to disk."""
        with patch.object(json_handler, "JSON_DIR", tmp_path):
            data = {"created": "2026-01-01", "last_updated": "2026-01-01", "items": []}
            result = json_handler.save_json("cli", "data", data)

        assert result is True

        on_disk = json.loads((tmp_path / "cli_data.json").read_text(encoding="utf-8"))
        assert on_disk["items"] == []

    def test_rejects_invalid_structure(self, tmp_path):
        """Invalid structure should raise ValueError."""
        with patch.object(json_handler, "JSON_DIR", tmp_path):
            with pytest.raises(ValueError, match="Invalid structure"):
                json_handler.save_json("cli", "config", {"bad": "data"})

    def test_auto_updates_last_updated_for_data_type(self, tmp_path):
        """Saving data type should auto-stamp last_updated to today."""
        today = datetime.now().date().isoformat()

        with patch.object(json_handler, "JSON_DIR", tmp_path):
            data = {"created": "2025-01-01", "last_updated": "2025-01-01"}
            json_handler.save_json("cli", "data", data)

        on_disk = json.loads((tmp_path / "cli_data.json").read_text(encoding="utf-8"))
        assert on_disk["last_updated"] == today

    def test_saves_valid_log_list(self, tmp_path):
        """Log type accepts a list and writes it."""
        entries = [{"timestamp": "t1", "operation": "test"}]

        with patch.object(json_handler, "JSON_DIR", tmp_path):
            result = json_handler.save_json("cli", "log", entries)

        assert result is True

        on_disk = json.loads((tmp_path / "cli_log.json").read_text(encoding="utf-8"))
        assert len(on_disk) == 1
        assert on_disk[0]["operation"] == "test"


# =============================================================================
# log_operation tests
# =============================================================================


class TestLogOperation:
    """Tests for log_operation()."""

    def test_logs_entry_to_file(self, tmp_path):
        """A single log_operation call should produce one entry on disk."""
        with patch.object(json_handler, "JSON_DIR", tmp_path):
            json_handler.log_operation("deploy", module_name="cli")

        log = json.loads(
            (tmp_path / "cli_log.json").read_text(encoding="utf-8")
        )
        assert len(log) == 1
        assert log[0]["operation"] == "deploy"
        assert "timestamp" in log[0]

    def test_logs_entry_with_data(self, tmp_path):
        """Data dict should be nested inside the log entry."""
        with patch.object(json_handler, "JSON_DIR", tmp_path):
            json_handler.log_operation(
                "sync", data={"count": 5}, module_name="cli"
            )

        log = json.loads(
            (tmp_path / "cli_log.json").read_text(encoding="utf-8")
        )
        assert log[0]["data"]["count"] == 5

    def test_rotation_trims_to_max_entries(self, tmp_path):
        """When log exceeds max_log_entries, oldest entries are dropped."""
        # Pre-seed a config with max_log_entries=3
        config = {
            "module_name": "cli",
            "version": "1.0.0",
            "config": {"max_log_entries": 3},
            "created": "2026-01-01",
        }
        (tmp_path / "cli_config.json").write_text(
            json.dumps(config), encoding="utf-8"
        )

        with patch.object(json_handler, "JSON_DIR", tmp_path):
            for i in range(5):
                json_handler.log_operation(
                    f"op_{i}", module_name="cli"
                )

        log = json.loads(
            (tmp_path / "cli_log.json").read_text(encoding="utf-8")
        )
        assert len(log) == 3
        # Oldest two (op_0, op_1) should be gone; newest three remain
        operations = [entry["operation"] for entry in log]
        assert operations == ["op_2", "op_3", "op_4"]

    def test_accumulates_entries(self, tmp_path):
        """Multiple calls should accumulate entries in the log."""
        with patch.object(json_handler, "JSON_DIR", tmp_path):
            json_handler.log_operation("first", module_name="cli")
            json_handler.log_operation("second", module_name="cli")

        log = json.loads(
            (tmp_path / "cli_log.json").read_text(encoding="utf-8")
        )
        assert len(log) == 2
        assert log[0]["operation"] == "first"
        assert log[1]["operation"] == "second"


# =============================================================================
# ensure_module_jsons tests
# =============================================================================


class TestEnsureModuleJsons:
    """Tests for ensure_module_jsons()."""

    def test_creates_all_three_json_types(self, tmp_path):
        """All 3 JSON files should be created with valid structure."""
        with patch.object(json_handler, "JSON_DIR", tmp_path):
            ensure_module_jsons("test_mod")

        config_path = tmp_path / "test_mod_config.json"
        data_path = tmp_path / "test_mod_data.json"
        log_path = tmp_path / "test_mod_log.json"

        assert config_path.exists()
        assert data_path.exists()
        assert log_path.exists()

        config = json.loads(config_path.read_text(encoding="utf-8"))
        assert config["module_name"] == "test_mod"
        assert config["version"] == "1.0.0"
        assert "config" in config

        data = json.loads(data_path.read_text(encoding="utf-8"))
        assert data["module_name"] == "test_mod"
        assert "created" in data
        assert "last_updated" in data

        log = json.loads(log_path.read_text(encoding="utf-8"))
        assert log == []

    def test_returns_true(self, tmp_path):
        """Return value should be True."""
        with patch.object(json_handler, "JSON_DIR", tmp_path):
            result = ensure_module_jsons("test_mod")

        assert result is True


# =============================================================================
# Edge case tests
# =============================================================================


class TestEdgeCases:
    """Edge case and boundary tests."""

    def test_validate_json_structure_none_config(self):
        """validate_json_structure(None, 'config') returns False."""
        assert validate_json_structure(None, "config") is False

    def test_validate_json_structure_none_data(self):
        """validate_json_structure(None, 'data') returns False."""
        assert validate_json_structure(None, "data") is False

    def test_log_operation_returns_true(self, tmp_path):
        """log_operation should return True on success."""
        with patch.object(json_handler, "JSON_DIR", tmp_path):
            result = json_handler.log_operation("test_op", module_name="mod")

        assert result is True

    def test_log_operation_empty_dict_data(self, tmp_path):
        """Empty dict data should NOT produce a 'data' key in the log entry.

        Because ``if data:`` is False for ``{}``, the handler skips
        attaching it.  This documents the existing behavior.
        """
        with patch.object(json_handler, "JSON_DIR", tmp_path):
            json_handler.log_operation("op", data={}, module_name="mod")

        log = json.loads(
            (tmp_path / "mod_log.json").read_text(encoding="utf-8")
        )
        assert len(log) == 1
        assert "data" not in log[0]
