# =================== AIPass ====================
# Name: test_json_handler.py
# Description: Tests for json_handler module
# Version: 1.0.0
# Created: 2026-05-16
# Modified: 2026-05-16
# =============================================

"""Tests for json_handler — default_factory, validate, get_path, ensure_exists, load, save, ensure_module."""

import json
from unittest.mock import patch

from aipass.aipass.apps.handlers.json.json_handler import (
    AIPASS_JSON_DIR,
    _default_template,
    ensure_json_exists,
    ensure_module_jsons,
    get_json_path,
    load_json,
    load_path,
    save_json,
    validate_json_structure,
)


# =============================================================================
# default_factory (_default_template)
# =============================================================================


class TestDefaultFactory:
    """Tests for _default_template factory function."""

    def test_config_template(self):
        """Config template includes module_name, version, config, created."""
        result = _default_template("config", "test_mod")
        assert result["module_name"] == "test_mod"
        assert result["version"] == "1.0.0"
        assert "config" in result
        assert "created" in result

    def test_data_template(self):
        """Data template includes created and last_updated."""
        result = _default_template("data", "test_mod")
        assert "created" in result
        assert "last_updated" in result

    def test_log_template(self):
        """Log template is an empty list."""
        result = _default_template("log", "test_mod")
        assert result == []

    def test_unknown_type_returns_none(self):
        """Unknown json_type returns None."""
        result = _default_template("unknown_type", "test_mod")
        assert result is None


# =============================================================================
# validate
# =============================================================================


class TestValidate:
    """Tests for validate_json_structure."""

    def test_valid_config(self):
        """Valid config structure passes validation."""
        data = {"module_name": "x", "version": "1.0.0", "config": {}}
        assert validate_json_structure(data, "config") is True

    def test_invalid_config_missing_key(self):
        """Config missing required keys fails validation."""
        data = {"module_name": "x"}
        assert validate_json_structure(data, "config") is False

    def test_config_not_dict(self):
        """Non-dict config fails validation."""
        assert validate_json_structure([], "config") is False

    def test_valid_data(self):
        """Valid data structure passes validation."""
        data = {"created": "2026-01-01", "last_updated": "2026-01-01"}
        assert validate_json_structure(data, "data") is True

    def test_invalid_data(self):
        """Data missing last_updated fails validation."""
        assert validate_json_structure({"created": "x"}, "data") is False

    def test_valid_log(self):
        """Empty list is valid log structure."""
        assert validate_json_structure([], "log") is True

    def test_invalid_log(self):
        """Non-list log fails validation."""
        assert validate_json_structure({}, "log") is False

    def test_unknown_type(self):
        """Unknown json_type fails validation."""
        assert validate_json_structure({}, "bogus") is False


# =============================================================================
# get_path
# =============================================================================


class TestGetPath:
    """Tests for get_json_path."""

    def test_returns_correct_path(self):
        """Path resolves to AIPASS_JSON_DIR/module_type.json."""
        path = get_json_path("doctor", "config")
        assert path == AIPASS_JSON_DIR / "doctor_config.json"

    def test_different_types(self):
        """All json_types produce correctly named paths."""
        for json_type in ("config", "data", "log"):
            path = get_json_path("mymod", json_type)
            assert path.name == f"mymod_{json_type}.json"


# =============================================================================
# ensure_exists
# =============================================================================


class TestEnsureExists:
    """Tests for ensure_json_exists."""

    def test_creates_missing_file(self, tmp_path):
        """Missing file is created from template."""
        with patch("aipass.aipass.apps.handlers.json.json_handler.AIPASS_JSON_DIR", tmp_path):
            result = ensure_json_exists("newmod", "config")
            assert result is True
            created = tmp_path / "newmod_config.json"
            assert created.exists()
            data = json.loads(created.read_text())
            assert data["module_name"] == "newmod"

    def test_existing_valid_file_untouched(self, tmp_path):
        """Valid existing file returns True without rewriting."""
        target = tmp_path / "existing_config.json"
        content = {"module_name": "existing", "version": "1.0.0", "config": {}, "created": "2026-01-01"}
        target.write_text(json.dumps(content))
        with patch("aipass.aipass.apps.handlers.json.json_handler.AIPASS_JSON_DIR", tmp_path):
            result = ensure_json_exists("existing", "config")
            assert result is True

    def test_corrupted_file_regenerated(self, tmp_path):
        """Corrupted file is regenerated from template."""
        target = tmp_path / "bad_config.json"
        target.write_text("not json at all")
        with patch("aipass.aipass.apps.handlers.json.json_handler.AIPASS_JSON_DIR", tmp_path):
            result = ensure_json_exists("bad", "config")
            assert result is True
            data = json.loads(target.read_text())
            assert data["module_name"] == "bad"


# =============================================================================
# load
# =============================================================================


class TestLoad:
    """Tests for load_json."""

    def test_load_existing(self, tmp_path):
        """Existing valid file loads correctly."""
        target = tmp_path / "mod_log.json"
        target.write_text(json.dumps([{"op": "test"}]))
        with patch("aipass.aipass.apps.handlers.json.json_handler.AIPASS_JSON_DIR", tmp_path):
            result = load_json("mod", "log")
            assert result == [{"op": "test"}]

    def test_load_missing_creates(self, tmp_path):
        """Missing file is auto-created then loaded."""
        with patch("aipass.aipass.apps.handlers.json.json_handler.AIPASS_JSON_DIR", tmp_path):
            result = load_json("fresh", "log")
            assert result == []


# =============================================================================
# save
# =============================================================================


class TestSave:
    """Tests for save_json."""

    def test_save_valid(self, tmp_path):
        """Valid structure saves successfully."""
        with patch("aipass.aipass.apps.handlers.json.json_handler.AIPASS_JSON_DIR", tmp_path):
            data = {"module_name": "s", "version": "1.0.0", "config": {}, "created": "2026-01-01"}
            result = save_json("s", "config", data)
            assert result is True
            saved = json.loads((tmp_path / "s_config.json").read_text())
            assert saved["module_name"] == "s"

    def test_save_invalid_structure_rejected(self, tmp_path):
        """Invalid structure is rejected with False."""
        with patch("aipass.aipass.apps.handlers.json.json_handler.AIPASS_JSON_DIR", tmp_path):
            result = save_json("s", "config", {"bad": True})
            assert result is False


# =============================================================================
# ensure_module
# =============================================================================


class TestEnsureModule:
    """Tests for ensure_module_jsons."""

    def test_creates_all_three(self, tmp_path):
        """All three json types (config, data, log) are created."""
        with patch("aipass.aipass.apps.handlers.json.json_handler.AIPASS_JSON_DIR", tmp_path):
            result = ensure_module_jsons("trio")
            assert result is True
            assert (tmp_path / "trio_config.json").exists()
            assert (tmp_path / "trio_data.json").exists()
            assert (tmp_path / "trio_log.json").exists()


# =============================================================================
# load_path
# =============================================================================


class TestLoadPath:
    """Tests for load_path arbitrary file reader."""

    def test_load_valid_file(self, tmp_path):
        """Valid JSON file loads as dict."""
        f = tmp_path / "test.json"
        f.write_text(json.dumps({"key": "value"}))
        result = load_path(f)
        assert result == {"key": "value"}

    def test_load_missing_file(self, tmp_path):
        """Missing file returns None."""
        result = load_path(tmp_path / "nope.json")
        assert result is None

    def test_load_invalid_json(self, tmp_path):
        """Invalid JSON content returns None."""
        f = tmp_path / "bad.json"
        f.write_text("not json")
        result = load_path(f)
        assert result is None

    def test_load_empty_file(self, tmp_path):
        """Empty file returns None."""
        f = tmp_path / "empty.json"
        f.write_text("")
        result = load_path(f)
        assert result is None


# =============================================================================
# error_resilience: empty_file
# =============================================================================


class TestErrorResilience:
    """Tests for error resilience with empty/corrupt files."""

    def test_empty_file_handled(self, tmp_path):
        """Empty JSON file is regenerated from template."""
        target = tmp_path / "empty_config.json"
        target.write_text("")
        with patch("aipass.aipass.apps.handlers.json.json_handler.AIPASS_JSON_DIR", tmp_path):
            result = ensure_json_exists("empty", "config")
            assert result is True
            data = json.loads(target.read_text())
            assert data["module_name"] == "empty"


# =============================================================================
# return_type_contracts: command_returns_bool
# =============================================================================


class TestReturnTypeContracts:
    """Tests that handle_command always returns bool."""

    def test_doctor_handle_command_returns_bool(self):
        """Doctor handle_command returns True for match, False otherwise."""
        from aipass.aipass.apps.modules.doctor import handle_command as doctor_cmd

        assert doctor_cmd("doctor", []) is True
        assert doctor_cmd("not_doctor", []) is False

    def test_help_chat_handle_command_returns_bool(self):
        """Help chat handle_command returns True for match, False otherwise."""
        from aipass.aipass.apps.modules.help_chat import handle_command as help_cmd

        assert help_cmd("help", []) is True
        assert help_cmd("not_help", []) is False

    def test_profile_handle_command_returns_bool(self):
        """Profile handle_command returns True for match, False otherwise."""
        from aipass.aipass.apps.modules.profile import handle_command as profile_cmd

        assert profile_cmd("profile", []) is True
        assert profile_cmd("not_profile", []) is False

    def test_doctor_wire_handle_command_returns_bool(self):
        """Doctor wire handle_command returns True for match, False otherwise."""
        from aipass.aipass.apps.modules.doctor_wire import handle_command as wire_cmd

        assert wire_cmd("doctor_wire", []) is True
        assert wire_cmd("not_wire", []) is False


# =============================================================================
# exception_contracts: invalid_mode_raises
# =============================================================================


class TestExceptionContracts:
    """Tests that invalid inputs raise appropriate exceptions."""

    def test_invalid_mode_raises(self, tmp_path):
        """save_json with invalid structure returns False (not silent pass)."""
        with patch("aipass.aipass.apps.handlers.json.json_handler.AIPASS_JSON_DIR", tmp_path):
            result = save_json("x", "config", [])
            assert result is False
            result = save_json("x", "data", "string")
            assert result is False
            result = save_json("x", "log", {"not": "a list"})
            assert result is False


# =============================================================================
# infrastructure_mocking: reimport_after_mock
# =============================================================================


class TestInfrastructureMocking:
    """Tests that module reimport after mocking works correctly."""

    def test_reimport_after_mock(self, tmp_path):
        """json_handler functions work after mock is torn down."""
        with patch("aipass.aipass.apps.handlers.json.json_handler.AIPASS_JSON_DIR", tmp_path):
            ensure_module_jsons("reimport_test")
            assert (tmp_path / "reimport_test_config.json").exists()

        import importlib
        import aipass.aipass.apps.handlers.json.json_handler as jh_mod

        importlib.reload(jh_mod)
        assert callable(jh_mod.load_json)
        assert callable(jh_mod.save_json)
        assert callable(jh_mod.load_path)
