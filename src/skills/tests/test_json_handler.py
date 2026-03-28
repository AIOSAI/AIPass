# =================== AIPass ====================
# Name: test_json_handler.py
# Description: Tests for skills JSON handler
# Version: 1.0.0
# Created: 2026-03-28
# Modified: 2026-03-28
# =============================================

"""
Tests for skills JSON handler -- auto-creating JSON system.

Covers json_handler.py functions: validate_json_structure, get_json_path,
ensure_json_exists, load_json, save_json, _get_default, ensure_module_jsons,
log_operation.
"""

import importlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Import helper
# ---------------------------------------------------------------------------

BRANCH_MODULE = "skills"
_json_mod_path = f"{BRANCH_MODULE}.apps.handlers.json.json_handler"


def _import_handler():
    """Import json_handler inside test so autouse mocks are active."""
    return importlib.import_module(_json_mod_path)


@pytest.fixture()
def sample_data():
    """Sample test data for JSON operations."""
    return {
        "config": {
            "module_name": "test_module",
            "version": "1.0.0",
            "config": {"max_log_entries": 50},
            "timestamp": "2026-03-28",
        },
        "data": {
            "module_name": "test_module",
            "created": "2026-03-28",
            "last_updated": "2026-03-28",
            "operations_total": 0,
            "operations_successful": 0,
            "operations_failed": 0,
        },
        "log": [
            {"timestamp": "2026-03-28T10:00:00", "operation": "test"}
        ],
    }


# ===================================================================
# 1. _get_default -- default factory for JSON types
# ===================================================================

class TestDefaultFactory:
    """Tests for _get_default template default_factory."""

    def test_config_default_factory_has_module_name(self):
        handler = _import_handler()
        result = handler._get_default("config", "test_mod")
        assert result["module_name"] == "test_mod"

    def test_config_default_factory_has_required_keys(self):
        handler = _import_handler()
        result = handler._get_default("config", "test_mod")
        assert "module_name" in result
        assert "version" in result
        assert "config" in result

    def test_data_default_factory_has_dates(self):
        handler = _import_handler()
        result = handler._get_default("data", "test_mod")
        assert "created" in result
        assert "last_updated" in result

    def test_log_default_factory_is_list(self):
        handler = _import_handler()
        result = handler._get_default("log", "test_mod")
        assert isinstance(result, list)
        assert len(result) == 0

    def test_unknown_type_default_factory_returns_none(self):
        handler = _import_handler()
        result = handler._get_default("nonexistent", "test_mod")
        assert result is None


# ===================================================================
# 2. validate_json_structure
# ===================================================================

class TestValidate:
    """Tests for validate_json_structure -- validate."""

    def test_validate_valid_config(self, sample_data):
        handler = _import_handler()
        assert handler.validate_json_structure(sample_data["config"], "config") is True

    def test_validate_valid_data(self, sample_data):
        handler = _import_handler()
        assert handler.validate_json_structure(sample_data["data"], "data") is True

    def test_validate_valid_log(self, sample_data):
        handler = _import_handler()
        assert handler.validate_json_structure(sample_data["log"], "log") is True

    def test_validate_invalid_config_missing_keys(self):
        handler = _import_handler()
        assert handler.validate_json_structure({"only": "partial"}, "config") is False

    def test_validate_config_non_dict_fails(self):
        handler = _import_handler()
        assert handler.validate_json_structure("not a dict", "config") is False

    def test_validate_unknown_type_fails(self):
        handler = _import_handler()
        assert handler.validate_json_structure({}, "unknown_type") is False

    def test_validate_log_non_list_fails(self):
        handler = _import_handler()
        assert handler.validate_json_structure({"not": "a list"}, "log") is False


# ===================================================================
# 3. get_json_path -- get_path
# ===================================================================

class TestGetPath:
    """Tests for get_json_path -- get_path."""

    def test_get_path_returns_path_type(self):
        handler = _import_handler()
        result = handler.get_json_path("test_mod", "config")
        assert isinstance(result, Path)

    def test_get_path_contains_module_and_type(self):
        handler = _import_handler()
        result = handler.get_json_path("my_module", "data")
        assert result.name == "my_module_data.json"

    def test_get_path_in_skills_json_dir(self):
        handler = _import_handler()
        result = handler.get_json_path("mod", "log")
        assert "skills_json" in str(result) or result.parent == handler.SKILLS_JSON_DIR


# ===================================================================
# 4. ensure_json_exists -- ensure_exists
# ===================================================================

class TestEnsureExists:
    """Tests for ensure_json_exists -- ensure_exists."""

    def test_ensure_exists_creates_new_file(self):
        handler = _import_handler()
        result = handler.ensure_json_exists("test", "config")
        assert result is True

    def test_ensure_exists_auto_creates_dir(self, tmp_path):
        handler = _import_handler()
        new_dir = tmp_path / "new_subdir"
        with patch.object(handler, "SKILLS_JSON_DIR", new_dir):
            result = handler.ensure_json_exists("test", "config")
            assert result is True
            assert new_dir.exists()

    def test_ensure_exists_returns_false_for_unknown_type(self):
        handler = _import_handler()
        result = handler.ensure_json_exists("test", "nonexistent")
        assert result is False


# ===================================================================
# 5. load_json -- load
# ===================================================================

class TestLoad:
    """Tests for load_json -- load."""

    def test_load_config_returns_dict(self):
        handler = _import_handler()
        result = handler.load_json("t", "config")
        assert isinstance(result, dict)

    def test_load_log_returns_list(self):
        handler = _import_handler()
        result = handler.load_json("t", "log")
        assert isinstance(result, list)

    def test_load_returns_none_for_bad_type(self):
        handler = _import_handler()
        result = handler.load_json("t", "nonexistent")
        assert result is None


# ===================================================================
# 6. save_json -- save
# ===================================================================

class TestSave:
    """Tests for save_json -- save."""

    def test_save_valid_config(self, sample_data):
        handler = _import_handler()
        handler.ensure_json_exists("test", "config")
        result = handler.save_json("test", "config", sample_data["config"])
        assert result is True

    def test_save_invalid_structure_returns_false(self):
        """save_json rejects invalid data."""
        handler = _import_handler()
        result = handler.save_json("test", "config", {"bad": "structure"})
        assert result is False

    def test_save_updates_last_updated_for_data(self, sample_data):
        handler = _import_handler()
        handler.ensure_json_exists("test", "data")
        handler.save_json("test", "data", sample_data["data"])
        json_path = handler.get_json_path("test", "data")
        saved = json.loads(json_path.read_text(encoding="utf-8"))
        assert "last_updated" in saved


# ===================================================================
# 7. log_operation
# ===================================================================

class TestLogOperation:
    """Tests for log_operation."""

    def test_log_operation_creates_entry(self):
        handler = _import_handler()
        result = handler.log_operation("test_op", module_name="test_mod")
        assert result is True

    def test_log_operation_entry_has_operation_field(self):
        handler = _import_handler()
        handler.log_operation("my_op", module_name="log_mod")
        log = handler.load_json("log_mod", "log")
        assert len(log) >= 1
        assert "operation" in log[-1]
        assert log[-1]["operation"] == "my_op"

    def test_log_operation_with_data(self):
        handler = _import_handler()
        handler.log_operation("data_op", data={"key": "value"}, module_name="log_mod2")
        log = handler.load_json("log_mod2", "log")
        assert log[-1]["data"]["key"] == "value"


# ===================================================================
# 8. ensure_module_jsons -- ensure_module
# ===================================================================

class TestEnsureModule:
    """Tests for ensure_module_jsons -- ensure_module."""

    def test_ensure_module_returns_true(self):
        handler = _import_handler()
        result = handler.ensure_module_jsons("test_mod")
        assert result is True

    def test_ensure_module_creates_all_three(self):
        handler = _import_handler()
        handler.ensure_module_jsons("full_mod")
        for json_type in ("config", "data", "log"):
            path = handler.get_json_path("full_mod", json_type)
            assert path.exists()
