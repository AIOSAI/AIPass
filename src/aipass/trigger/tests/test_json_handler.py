# =================== AIPass ====================
# Name: test_json_handler.py
# Description: Unit tests for trigger json_handler
# Version: 1.0.0
# Created: 2026-03-27
# Modified: 2026-03-27
# =============================================

"""Unit tests for aipass.trigger.apps.handlers.json.json_handler."""

import json
import pytest
from pathlib import Path


@pytest.fixture
def json_handler(tmp_path, monkeypatch):
    """Import json_handler with TRIGGER_JSON_DIR pointed at tmp_path."""
    import importlib
    import aipass.trigger.apps.handlers.json.json_handler as mod

    monkeypatch.setattr(mod, "TRIGGER_JSON_DIR", tmp_path)
    monkeypatch.setattr(mod, "TRIGGER_ROOT", tmp_path.parent)
    importlib.reload(mod)
    monkeypatch.setattr(mod, "TRIGGER_JSON_DIR", tmp_path)
    monkeypatch.setattr(mod, "TRIGGER_ROOT", tmp_path.parent)
    return mod


# ---------------------------------------------------------------------------
# default_factory: _get_default_template returns correct structures
# ---------------------------------------------------------------------------


class TestDefaultFactory:
    def test_config_template_has_required_keys(self, json_handler):
        result = json_handler._get_default_template("config", "test_mod")
        assert isinstance(result, dict)
        assert "module_name" in result
        assert "version" in result
        assert "config" in result
        assert result["module_name"] == "test_mod"

    def test_data_template_has_required_keys(self, json_handler):
        result = json_handler._get_default_template("data", "test_mod")
        assert isinstance(result, dict)
        assert "created" in result
        assert "last_updated" in result

    def test_log_template_returns_list(self, json_handler):
        result = json_handler._get_default_template("log", "test_mod")
        assert isinstance(result, list)
        assert len(result) == 0

    def test_unknown_type_raises(self, json_handler):
        with pytest.raises(ValueError, match="Unknown json_type"):
            json_handler._get_default_template("bogus", "test_mod")


# ---------------------------------------------------------------------------
# validate: validate_json_structure
# ---------------------------------------------------------------------------


class TestValidate:
    def test_valid_config(self, json_handler):
        data = {"module_name": "x", "version": "1.0", "config": {}}
        assert json_handler.validate_json_structure(data, "config") is True

    def test_invalid_config_missing_key(self, json_handler):
        assert json_handler.validate_json_structure({"module_name": "x"}, "config") is False

    def test_config_non_dict(self, json_handler):
        assert json_handler.validate_json_structure([], "config") is False

    def test_valid_data(self, json_handler):
        assert json_handler.validate_json_structure({"created": "x", "last_updated": "y"}, "data") is True

    def test_valid_log(self, json_handler):
        assert json_handler.validate_json_structure([], "log") is True

    def test_unknown_type(self, json_handler):
        assert json_handler.validate_json_structure({}, "bogus") is False


# ---------------------------------------------------------------------------
# get_path: get_json_path returns correct Path
# ---------------------------------------------------------------------------


class TestGetPath:
    def test_returns_path_object(self, json_handler):
        result = json_handler.get_json_path("mymod", "config")
        assert isinstance(result, Path)

    def test_path_contains_module_and_type(self, json_handler):
        result = json_handler.get_json_path("mymod", "data")
        assert result.name == "mymod_data.json"

    def test_paths_return_path(self, json_handler):
        """Return type contract: get_json_path always returns a Path."""
        for jtype in ("config", "data", "log"):
            assert isinstance(json_handler.get_json_path("mod", jtype), Path)


# ---------------------------------------------------------------------------
# ensure_exists: ensure_json_exists creates files
# ---------------------------------------------------------------------------


class TestEnsureExists:
    def test_creates_config_file(self, json_handler, tmp_path):
        assert json_handler.ensure_json_exists("newmod", "config") is True
        path = tmp_path / "newmod_config.json"
        assert path.exists()

    def test_does_not_overwrite_valid(self, json_handler, tmp_path):
        """no_overwrite: existing valid file is preserved."""
        path = tmp_path / "keep_config.json"
        original = {"module_name": "keep", "version": "9.9.9", "config": {"custom": True}}
        path.write_text(json.dumps(original))
        json_handler.ensure_json_exists("keep", "config")
        reloaded = json.loads(path.read_text())
        assert reloaded["version"] == "9.9.9"

    def test_regenerates_corrupt_file(self, json_handler, tmp_path):
        """corrupt_json: corrupted file gets regenerated."""
        path = tmp_path / "bad_config.json"
        path.write_text("{{{not json")
        json_handler.ensure_json_exists("bad", "config")
        reloaded = json.loads(path.read_text())
        assert "module_name" in reloaded

    def test_regenerates_empty_file(self, json_handler, tmp_path):
        """empty_file: empty file gets regenerated."""
        path = tmp_path / "empty_config.json"
        path.write_text("")
        json_handler.ensure_json_exists("empty", "config")
        reloaded = json.loads(path.read_text())
        assert "module_name" in reloaded


# ---------------------------------------------------------------------------
# load: load_json
# ---------------------------------------------------------------------------


class TestLoad:
    def test_load_auto_creates_and_returns(self, json_handler):
        result = json_handler.load_json("loadtest", "config")
        assert isinstance(result, dict)
        assert result["module_name"] == "loadtest"

    def test_load_log_returns_list(self, json_handler):
        result = json_handler.load_json("loadtest", "log")
        assert isinstance(result, list)

    def test_load_missing_file_creates(self, json_handler, tmp_path):
        """missing_file: load_json creates file if missing."""
        path = tmp_path / "fresh_data.json"
        assert not path.exists()
        result = json_handler.load_json("fresh", "data")
        assert result is not None
        assert path.exists()


# ---------------------------------------------------------------------------
# save: save_json
# ---------------------------------------------------------------------------


class TestSave:
    def test_save_valid_data(self, json_handler, tmp_path):
        json_handler.ensure_json_exists("smod", "data")
        data = {"created": "2026-01-01", "last_updated": "2026-01-01", "extra": 42}
        assert json_handler.save_json("smod", "data", data) is True
        reloaded = json.loads((tmp_path / "smod_data.json").read_text())
        assert reloaded["extra"] == 42

    def test_save_invalid_raises(self, json_handler):
        """exception_contract: save_json raises ValueError for invalid structure."""
        with pytest.raises(ValueError, match="Invalid structure"):
            json_handler.save_json("smod", "config", {"wrong": True})

    def test_save_invalid_mode_raises(self, json_handler):
        """exception_contract: save with bad log type raises ValueError."""
        with pytest.raises(ValueError, match="Invalid structure"):
            json_handler.save_json("smod", "log", {"not": "a list"})


# ---------------------------------------------------------------------------
# ensure_module: ensure_module_jsons creates all 3 files
# ---------------------------------------------------------------------------


class TestEnsureModule:
    def test_creates_all_three(self, json_handler, tmp_path):
        json_handler.ensure_module_jsons("trio")
        assert (tmp_path / "trio_config.json").exists()
        assert (tmp_path / "trio_data.json").exists()
        assert (tmp_path / "trio_log.json").exists()

    def test_returns_true(self, json_handler):
        assert json_handler.ensure_module_jsons("rt") is True


# ---------------------------------------------------------------------------
# log_operation + infrastructure
# ---------------------------------------------------------------------------


class TestLogOperation:
    def test_log_operation_appends_entry(self, json_handler, tmp_path):
        json_handler.log_operation("test_op", {"key": "val"}, module_name="logmod")
        log = json.loads((tmp_path / "logmod_log.json").read_text())
        assert len(log) >= 1
        assert log[-1]["operation"] == "test_op"

    def test_log_operation_rotates(self, json_handler, tmp_path):
        """Rotation: log entries beyond max_entries are trimmed."""
        # Set max to 5 via config
        json_handler.ensure_module_jsons("rotmod")
        config = json_handler.load_json("rotmod", "config")
        config["config"]["max_log_entries"] = 5
        json_handler.save_json("rotmod", "config", config)
        for i in range(10):
            json_handler.log_operation(f"op_{i}", module_name="rotmod")
        log = json.loads((tmp_path / "rotmod_log.json").read_text())
        assert len(log) == 5

    def test_reimport_after_mock(self, json_handler, tmp_path, monkeypatch):
        """infrastructure_mocking: module works after reimport with mocked paths."""
        import importlib
        import aipass.trigger.apps.handlers.json.json_handler as mod

        new_dir = tmp_path / "reimport_test"
        new_dir.mkdir()
        monkeypatch.setattr(mod, "TRIGGER_JSON_DIR", new_dir)
        importlib.reload(mod)
        monkeypatch.setattr(mod, "TRIGGER_JSON_DIR", new_dir)
        mod.ensure_json_exists("reimp", "config")
        assert (new_dir / "reimp_config.json").exists()
