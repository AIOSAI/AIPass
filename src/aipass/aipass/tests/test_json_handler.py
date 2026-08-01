# =================== AIPass ====================
# Name: test_json_handler.py
# Description: Tests for json_handler module
# Version: 1.0.0
# Created: 2026-05-16
# Modified: 2026-05-16
# =============================================

"""Tests for json_handler — default_factory, validate, get_path, ensure_exists, load, save, ensure_module."""

import importlib
import json
import sys

import pytest
from unittest.mock import patch

import aipass.aipass.apps.handlers.json.json_handler as jh_mod

# Every test patches AND calls through this single module object.  Under
# pytest-xdist another test on the same worker can evict the handler from
# sys.modules; a string patch target ("pkg.mod.ATTR") would then re-import it
# and patch a *second*, divergent module instance while the functions under
# test still live on the first one -- writes land in the real json dir and the
# tmp_path assertions fail.  Binding both sides to ``jh_mod`` removes that
# window entirely.
_MODULE_KEY = jh_mod.__name__


def _module_chain(module) -> dict:
    """Map the module *and every ancestor package* to the objects imported here.

    importlib.reload() needs both ``sys.modules[module.__name__] is module`` and
    ``sys.modules[parent_package]`` (it reads ``parent.__path__``), so pinning
    only the leaf is not enough.
    """
    parts = module.__name__.split(".")
    chain = {".".join(parts[:i]): sys.modules[".".join(parts[:i])] for i in range(1, len(parts))}
    chain[module.__name__] = module
    return chain


_MODULE_CHAIN = _module_chain(jh_mod)


@pytest.fixture(autouse=True)
def _pin_module_identity():
    """Keep sys.modules pointing at the module objects this file imported."""
    sys.modules.update(_MODULE_CHAIN)
    yield
    sys.modules.update(_MODULE_CHAIN)


# =============================================================================
# default_factory (_default_template)
# =============================================================================


class TestDefaultFactory:
    """Tests for default JSON creation via ensure_json_exists."""

    def test_config_template(self, tmp_path):
        """Config template includes module_name, version, config, created."""
        with patch.object(jh_mod, "AIPASS_JSON_DIR", tmp_path):
            jh_mod.ensure_json_exists("test_mod", "config")
            result = json.loads((tmp_path / "test_mod_config.json").read_text())
        assert result["module_name"] == "test_mod"
        assert result["version"] == "1.0.0"
        assert "config" in result
        assert "created" in result

    def test_data_template(self, tmp_path):
        """Data template includes created and last_updated."""
        with patch.object(jh_mod, "AIPASS_JSON_DIR", tmp_path):
            jh_mod.ensure_json_exists("test_mod", "data")
            result = json.loads((tmp_path / "test_mod_data.json").read_text())
        assert "created" in result
        assert "last_updated" in result

    def test_log_template(self, tmp_path):
        """Log template is an empty list."""
        with patch.object(jh_mod, "AIPASS_JSON_DIR", tmp_path):
            jh_mod.ensure_json_exists("test_mod", "log")
            result = json.loads((tmp_path / "test_mod_log.json").read_text())
        assert result == []

    def test_unknown_type_raises(self):
        """Unknown json_type raises ValueError."""
        with pytest.raises(ValueError):
            jh_mod.JsonHandler._create_default("unknown_type", "test_mod")


# =============================================================================
# validate
# =============================================================================


class TestValidate:
    """Tests for validate_json_structure."""

    def test_valid_config(self):
        """Valid config structure passes validation."""
        data = {"module_name": "x", "version": "1.0.0", "config": {}}
        assert jh_mod.validate_json_structure(data, "config") is True

    def test_invalid_config_missing_key(self):
        """Config missing required keys fails validation."""
        data = {"module_name": "x"}
        assert jh_mod.validate_json_structure(data, "config") is False

    def test_config_not_dict(self):
        """Non-dict config fails validation."""
        assert jh_mod.validate_json_structure([], "config") is False

    def test_valid_data(self):
        """Valid data structure passes validation."""
        data = {"created": "2026-01-01", "last_updated": "2026-01-01"}
        assert jh_mod.validate_json_structure(data, "data") is True

    def test_invalid_data(self):
        """Data missing last_updated fails validation."""
        assert jh_mod.validate_json_structure({"created": "x"}, "data") is False

    def test_valid_log(self):
        """Empty list is valid log structure."""
        assert jh_mod.validate_json_structure([], "log") is True

    def test_invalid_log(self):
        """Non-list log fails validation."""
        assert jh_mod.validate_json_structure({}, "log") is False

    def test_unknown_type(self):
        """Unknown json_type fails validation."""
        assert jh_mod.validate_json_structure({}, "bogus") is False


# =============================================================================
# get_path
# =============================================================================


class TestGetPath:
    """Tests for get_json_path."""

    def test_returns_correct_path(self):
        """Path resolves to AIPASS_JSON_DIR/module_type.json."""
        path = jh_mod.get_json_path("doctor", "config")
        assert path == jh_mod.AIPASS_JSON_DIR / "doctor_config.json"

    def test_different_types(self):
        """All json_types produce correctly named paths."""
        for json_type in ("config", "data", "log"):
            path = jh_mod.get_json_path("mymod", json_type)
            assert path.name == f"mymod_{json_type}.json"


# =============================================================================
# ensure_exists
# =============================================================================


class TestEnsureExists:
    """Tests for ensure_json_exists."""

    def test_creates_missing_file(self, tmp_path):
        """Missing file is created from template."""
        with patch.object(jh_mod, "AIPASS_JSON_DIR", tmp_path):
            result = jh_mod.ensure_json_exists("newmod", "config")
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
        with patch.object(jh_mod, "AIPASS_JSON_DIR", tmp_path):
            result = jh_mod.ensure_json_exists("existing", "config")
            assert result is True

    def test_corrupted_file_regenerated(self, tmp_path):
        """Corrupted file is regenerated from template."""
        target = tmp_path / "bad_config.json"
        target.write_text("not json at all")
        with patch.object(jh_mod, "AIPASS_JSON_DIR", tmp_path):
            result = jh_mod.ensure_json_exists("bad", "config")
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
        with patch.object(jh_mod, "AIPASS_JSON_DIR", tmp_path):
            result = jh_mod.load_json("mod", "log")
            assert result == [{"op": "test"}]

    def test_load_missing_creates(self, tmp_path):
        """Missing file is auto-created then loaded."""
        with patch.object(jh_mod, "AIPASS_JSON_DIR", tmp_path):
            result = jh_mod.load_json("fresh", "log")
            assert result == []


# =============================================================================
# save
# =============================================================================


class TestSave:
    """Tests for save_json."""

    def test_save_valid(self, tmp_path):
        """Valid structure saves successfully."""
        with patch.object(jh_mod, "AIPASS_JSON_DIR", tmp_path):
            data = {"module_name": "s", "version": "1.0.0", "config": {}, "created": "2026-01-01"}
            result = jh_mod.save_json("s", "config", data)
            assert result is True
            saved = json.loads((tmp_path / "s_config.json").read_text())
            assert saved["module_name"] == "s"

    def test_save_invalid_structure_rejected(self, tmp_path):
        """Invalid structure raises ValueError."""
        with patch.object(jh_mod, "AIPASS_JSON_DIR", tmp_path):
            with pytest.raises(ValueError):
                jh_mod.save_json("s", "config", {"bad": True})

    def test_save_unknown_returns_false(self, tmp_path):
        """save_json returns False when write fails (e.g. read-only dir)."""
        ro_dir = tmp_path / "readonly"
        ro_dir.mkdir()
        with patch.object(jh_mod, "AIPASS_JSON_DIR", ro_dir):
            data = {"module_name": "s", "version": "1.0.0", "config": {}, "created": "2026-01-01"}
            with patch.object(jh_mod.JsonHandler, "write_json", return_value=False):
                result = jh_mod.save_json("s", "config", data)
                assert result is False


# =============================================================================
# ensure_module
# =============================================================================


class TestEnsureModule:
    """Tests for ensure_module_jsons."""

    def test_creates_all_three(self, tmp_path):
        """All three json types (config, data, log) are created."""
        with patch.object(jh_mod, "AIPASS_JSON_DIR", tmp_path):
            result = jh_mod.ensure_module_jsons("trio")
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
        result = jh_mod.load_path(f)
        assert result == {"key": "value"}

    def test_unknown_file_returns_none(self, tmp_path):
        """Missing file returns None."""
        result = jh_mod.load_path(tmp_path / "nope.json")
        assert result is None

    def test_load_invalid_json(self, tmp_path):
        """Invalid JSON content returns None."""
        f = tmp_path / "bad.json"
        f.write_text("not json")
        result = jh_mod.load_path(f)
        assert result is None

    def test_load_empty_file(self, tmp_path):
        """Empty file returns None."""
        f = tmp_path / "empty.json"
        f.write_text("")
        result = jh_mod.load_path(f)
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
        with patch.object(jh_mod, "AIPASS_JSON_DIR", tmp_path):
            result = jh_mod.ensure_json_exists("empty", "config")
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

        with patch("aipass.aipass.apps.modules.doctor.run_doctor", return_value=0):
            with patch("aipass.aipass.apps.modules.doctor.json_handler"):
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
        from aipass.aipass.apps.modules._doctor_wire import handle_command as wire_cmd

        assert wire_cmd("doctor_wire", []) is True
        assert wire_cmd("not_wire", []) is False


# =============================================================================
# exception_contracts: invalid_mode_raises
# =============================================================================


class TestExceptionContracts:
    """Tests that invalid inputs raise appropriate exceptions."""

    def test_invalid_mode_raises(self, tmp_path):
        """save_json with invalid structure raises ValueError."""
        with patch.object(jh_mod, "AIPASS_JSON_DIR", tmp_path):
            with pytest.raises(ValueError):
                jh_mod.save_json("x", "config", [])
            with pytest.raises(ValueError):
                jh_mod.save_json("x", "data", "string")
            with pytest.raises(ValueError):
                jh_mod.save_json("x", "log", {"not": "a list"})


# =============================================================================
# infrastructure_mocking: reimport_after_mock
# =============================================================================


class TestInfrastructureMocking:
    """Tests that module reimport after mocking works correctly."""

    def test_reimport_after_mock(self, tmp_path):
        """json_handler functions work after mock is torn down."""
        with patch.object(jh_mod, "AIPASS_JSON_DIR", tmp_path):
            jh_mod.ensure_module_jsons("reimport_test")
            assert (tmp_path / "reimport_test_config.json").exists()

        # Reload the *pinned* module object (never a fresh import): reload
        # re-executes in place, so every reference held by this and any other
        # test module stays valid instead of going stale against a new
        # instance.  _pin_module_identity guarantees sys.modules[name] is
        # jh_mod, which is what importlib.reload requires.
        assert sys.modules[_MODULE_KEY] is jh_mod
        reloaded = importlib.reload(jh_mod)
        assert reloaded is jh_mod
        assert callable(jh_mod.load_json)
        assert callable(jh_mod.save_json)
        assert callable(jh_mod.load_path)


# =============================================================================
# success_failure_paths: unknown_returns_false
# =============================================================================


def test_unknown_returns_false():
    """validate_json_structure returns False for unrecognized json_type."""
    assert jh_mod.validate_json_structure({}, "bogus") is False
