"""Tests for the json handler directory (json_handler)."""

# =================== META ====================
# Name: test_json.py
# Description: Unit tests for handlers/json/
# Version: 1.0.0
# Created: 2026-03-24
# Modified: 2026-03-24
# =============================================

import pytest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch):
    """Mock heavy infrastructure imports for json handler."""
    import sys

    mock_logger = MagicMock()

    # -- prax ---------------------------------------------------------------
    prax_mod = MagicMock()
    prax_mod.logger = mock_logger
    monkeypatch.setitem(sys.modules, "aipass.prax", prax_mod)

    # Force re-import
    monkeypatch.delitem(sys.modules, "aipass.seedgo.apps.handlers.json.json_handler", raising=False)


# ---------------------------------------------------------------------------
# Tests -- validate_json_structure
# ---------------------------------------------------------------------------


def test_validate_config_structure():
    """validate_json_structure accepts valid config dict."""
    from aipass.seedgo.apps.handlers.json.json_handler import validate_json_structure

    data = {"module_name": "test", "version": "1.0.0", "config": {"enabled": True}}
    assert validate_json_structure(data, "config") is True


def test_validate_config_missing_keys():
    """validate_json_structure rejects config dict missing required keys."""
    from aipass.seedgo.apps.handlers.json.json_handler import validate_json_structure

    assert validate_json_structure({"module_name": "test"}, "config") is False


def test_validate_config_wrong_type():
    """validate_json_structure rejects non-dict for config type."""
    from aipass.seedgo.apps.handlers.json.json_handler import validate_json_structure

    assert validate_json_structure([1, 2, 3], "config") is False


def test_validate_data_structure():
    """validate_json_structure accepts valid data dict."""
    from aipass.seedgo.apps.handlers.json.json_handler import validate_json_structure

    data = {"created": "2026-01-01", "last_updated": "2026-01-01"}
    assert validate_json_structure(data, "data") is True


def test_validate_data_missing_keys():
    """validate_json_structure rejects data dict missing required keys."""
    from aipass.seedgo.apps.handlers.json.json_handler import validate_json_structure

    assert validate_json_structure({"created": "2026-01-01"}, "data") is False


def test_validate_log_structure():
    """validate_json_structure accepts list for log type."""
    from aipass.seedgo.apps.handlers.json.json_handler import validate_json_structure

    assert validate_json_structure([], "log") is True
    assert validate_json_structure([{"op": "test"}], "log") is True


def test_validate_log_wrong_type():
    """validate_json_structure rejects non-list for log type."""
    from aipass.seedgo.apps.handlers.json.json_handler import validate_json_structure

    assert validate_json_structure({"not": "a list"}, "log") is False


def test_validate_unknown_type():
    """validate_json_structure returns False for unknown json_type."""
    from aipass.seedgo.apps.handlers.json.json_handler import validate_json_structure

    assert validate_json_structure({}, "unknown_type") is False


# ---------------------------------------------------------------------------
# Tests -- get_json_path
# ---------------------------------------------------------------------------


def test_get_json_path_format():
    """get_json_path builds correct filename from module name and type."""
    from aipass.seedgo.apps.handlers.json.json_handler import get_json_path

    result = get_json_path("my_module", "config")
    assert result.name == "my_module_config.json"


def test_get_json_path_different_types():
    """get_json_path works for all three json types."""
    from aipass.seedgo.apps.handlers.json.json_handler import get_json_path

    for json_type in ("config", "data", "log"):
        result = get_json_path("mod", json_type)
        assert json_type in result.name


# ---------------------------------------------------------------------------
# Tests -- _create_default
# ---------------------------------------------------------------------------


def test_create_default_config():
    """_create_default returns valid config template."""
    from aipass.seedgo.apps.handlers.json.json_handler import _create_default

    result = _create_default("config", "test_mod")
    assert result["module_name"] == "test_mod"
    assert "version" in result
    assert "config" in result


def test_create_default_data():
    """_create_default returns valid data template."""
    from aipass.seedgo.apps.handlers.json.json_handler import _create_default

    result = _create_default("data", "test_mod")
    assert "created" in result
    assert "last_updated" in result
    assert result["module_name"] == "test_mod"


def test_create_default_log():
    """_create_default returns empty list for log type."""
    from aipass.seedgo.apps.handlers.json.json_handler import _create_default

    result = _create_default("log", "test_mod")
    assert result == []


def test_create_default_unknown_raises():
    """_create_default raises ValueError for unknown type."""
    from aipass.seedgo.apps.handlers.json.json_handler import _create_default

    with pytest.raises(ValueError, match="Unknown json_type"):
        _create_default("bogus", "test_mod")
