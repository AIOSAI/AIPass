# ===================AIPASS====================
# META DATA HEADER
# Name: test_json_handler.py - JSON Handler Unit Tests
# Date: 2026-03-24
# Version: 1.0.0
# Category: commons/tests
#
# CHANGELOG (Max 5 entries):
#   - v1.0.0 (2026-03-24): Initial creation — 18 unit tests
#
# CODE STANDARDS:
#   - Pytest function style (no unittest classes)
#   - tmp_path + monkeypatch for file isolation
#   - Mock heavy deps (prax logger)
# =============================================

"""
Unit tests for the commons JSON handler.

Tests _get_default, validate_json_structure, get_json_path,
ensure_json_exists, load_json, and save_json.
"""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Mock the prax logger before importing the module under test
import sys

_mock_logger = MagicMock()
_mock_logger_module = MagicMock()
_mock_logger_module.system_logger = _mock_logger

try:
    from aipass.prax.apps.modules.logger import system_logger  # noqa: F401
except ImportError:
    sys.modules.setdefault("aipass.prax", MagicMock())
    sys.modules.setdefault("aipass.prax.apps", MagicMock())
    sys.modules.setdefault("aipass.prax.apps.modules", MagicMock())
    sys.modules.setdefault("aipass.prax.apps.modules.logger", _mock_logger_module)

from commons.apps.handlers.json.json_handler import (
    _get_default,
    validate_json_structure,
    get_json_path,
    ensure_json_exists,
    load_json,
    save_json,
)
import commons.apps.handlers.json.json_handler as json_handler_mod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _isolate_json_dir(tmp_path, monkeypatch):
    """Redirect BRANCH_JSON_DIR to a temp directory for every test."""
    json_dir = str(tmp_path / "commons_json")
    monkeypatch.setattr(json_handler_mod, "BRANCH_JSON_DIR", json_dir)


# ===========================================================================
# _get_default
# ===========================================================================

def test_get_default_config_returns_dict():
    """Config type returns a dict with expected keys."""
    result = _get_default("config", "mymod")
    assert isinstance(result, dict)
    assert result["module_name"] == "mymod"
    assert result["version"] == "1.0.0"
    assert "config" in result
    assert result["config"]["enabled"] is True


def test_get_default_data_returns_dict():
    """Data type returns a dict with date fields and zero counters."""
    result = _get_default("data", "mymod")
    assert isinstance(result, dict)
    assert result["module_name"] == "mymod"
    assert result["operations_total"] == 0
    assert result["operations_successful"] == 0
    assert result["operations_failed"] == 0
    today = datetime.now().date().isoformat()
    assert result["created"] == today


def test_get_default_log_returns_list():
    """Log type returns an empty list."""
    result = _get_default("log", "mymod")
    assert result == []


def test_get_default_unknown_raises():
    """Unknown json_type raises ValueError."""
    with pytest.raises(ValueError, match="Unknown json_type"):
        _get_default("invalid_type", "mymod")


# ===========================================================================
# validate_json_structure
# ===========================================================================

def test_validate_config_valid():
    """Valid config dict passes validation."""
    data = {"module_name": "x", "version": "1.0.0", "config": {}}
    assert validate_json_structure(data, "config") is True


def test_validate_config_missing_key():
    """Config dict missing required key fails validation."""
    data = {"module_name": "x", "version": "1.0.0"}
    assert validate_json_structure(data, "config") is False


def test_validate_config_not_dict():
    """Config that is not a dict fails validation."""
    assert validate_json_structure([], "config") is False


def test_validate_data_valid():
    """Valid data dict passes validation."""
    data = {"created": "2026-01-01", "last_updated": "2026-01-01"}
    assert validate_json_structure(data, "data") is True


def test_validate_data_missing_key():
    """Data dict missing a required key fails validation."""
    data = {"created": "2026-01-01"}
    assert validate_json_structure(data, "data") is False


def test_validate_log_valid():
    """A list passes log validation."""
    assert validate_json_structure([], "log") is True
    assert validate_json_structure([{"entry": 1}], "log") is True


def test_validate_log_not_list():
    """A non-list fails log validation."""
    assert validate_json_structure({}, "log") is False


def test_validate_unknown_type():
    """Unknown json_type always returns False."""
    assert validate_json_structure({}, "bogus") is False


# ===========================================================================
# get_json_path
# ===========================================================================

def test_get_json_path_format(tmp_path):
    """Path follows {BRANCH_JSON_DIR}/{module}_{type}.json pattern."""
    path = get_json_path("dashboard", "config")
    assert path.endswith("dashboard_config.json")
    assert "commons_json" in path


# ===========================================================================
# ensure_json_exists
# ===========================================================================

def test_ensure_json_exists_creates_file(tmp_path):
    """Creates the JSON file when it does not exist."""
    result = ensure_json_exists("testmod", "config")
    assert result is True

    path = Path(get_json_path("testmod", "config"))
    assert path.exists()

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["module_name"] == "testmod"


def test_ensure_json_exists_preserves_valid(tmp_path):
    """Does not overwrite a valid existing file."""
    ensure_json_exists("testmod", "data")
    path = Path(get_json_path("testmod", "data"))

    # Modify a value so we can detect an overwrite
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    data["operations_total"] = 42
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)

    ensure_json_exists("testmod", "data")

    with open(path, "r", encoding="utf-8") as f:
        reloaded = json.load(f)
    assert reloaded["operations_total"] == 42


def test_ensure_json_exists_overwrites_corrupt(tmp_path):
    """Overwrites a corrupt (non-parseable) JSON file."""
    ensure_json_exists("testmod", "log")
    path = Path(get_json_path("testmod", "log"))

    # Write garbage
    with open(path, "w", encoding="utf-8") as f:
        f.write("{{{not valid json")

    result = ensure_json_exists("testmod", "log")
    assert result is True

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data == []


# ===========================================================================
# load_json
# ===========================================================================

def test_load_json_auto_creates(tmp_path):
    """Loading a non-existent file auto-creates and returns default."""
    data = load_json("fresh", "config")
    assert isinstance(data, dict)
    assert data["module_name"] == "fresh"


def test_load_json_returns_saved_data(tmp_path):
    """Loading returns previously saved data."""
    ensure_json_exists("keeper", "data")
    path = Path(get_json_path("keeper", "data"))

    with open(path, "r", encoding="utf-8") as f:
        original = json.load(f)
    original["operations_total"] = 99
    with open(path, "w", encoding="utf-8") as f:
        json.dump(original, f)

    loaded = load_json("keeper", "data")
    assert isinstance(loaded, dict)
    assert loaded["operations_total"] == 99


# ===========================================================================
# save_json
# ===========================================================================

def test_save_json_writes_valid_data(tmp_path):
    """save_json writes data that can be loaded back."""
    ensure_json_exists("saver", "data")
    data = {
        "module_name": "saver",
        "created": "2026-01-01",
        "last_updated": "2026-01-01",
        "operations_total": 7,
        "operations_successful": 5,
        "operations_failed": 2,
    }
    result = save_json("saver", "data", data)
    assert result is True

    loaded = load_json("saver", "data")
    assert isinstance(loaded, dict)
    assert loaded["operations_total"] == 7
    # last_updated should be refreshed to today
    assert loaded["last_updated"] == datetime.now().date().isoformat()


def test_save_json_rejects_invalid_structure(tmp_path):
    """save_json raises ValueError for structurally invalid data."""
    ensure_json_exists("bad", "config")
    with pytest.raises(ValueError, match="Invalid structure"):
        save_json("bad", "config", {"wrong": "shape"})


def test_save_json_log_accepts_list(tmp_path):
    """save_json accepts a list for log type."""
    ensure_json_exists("logmod", "log")
    entries = [{"timestamp": "2026-01-01T00:00:00", "operation": "test"}]
    result = save_json("logmod", "log", entries)
    assert result is True

    loaded = load_json("logmod", "log")
    assert isinstance(loaded, list)
    assert len(loaded) == 1
    assert loaded[0]["operation"] == "test"
