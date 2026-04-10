# =================== AIPass ====================
# Name: test_provision.py
# Description: Tests for caller auto-provisioning handler
# Version: 1.0.0
# Created: 2026-03-20
# Modified: 2026-03-20
# =============================================

"""
Tests for provision.py — caller auto-provisioning.

Tests:
- create_caller_config() creates 3 JSON files with correct defaults
- ensure_caller_config() provisions on first call, returns existing on second
- Idempotency: second call doesn't overwrite existing config
- Config defaults match expected values
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from aipass.api.apps.handlers.openrouter.provision import (
    create_caller_config,
    ensure_caller_config,
    get_default_caller_config,
    get_default_caller_data,
    get_default_caller_log,
    provision_json_folder,
    read_json,
    write_json,
)


# =============================================
# create_caller_config tests
# =============================================


def test_create_caller_config_creates_three_files(tmp_path: Path):
    """create_caller_config() should create config, data, and log JSON files."""
    json_folder = tmp_path / "test_json"

    result = create_caller_config("test_caller", json_folder)

    assert result != {}
    assert (json_folder / "openrouter_skill_config.json").exists()
    assert (json_folder / "openrouter_skill_data.json").exists()
    assert (json_folder / "openrouter_skill_log.json").exists()


def test_create_caller_config_defaults(tmp_path: Path):
    """Config defaults should match: ai_temperature=0.7, ai_max_tokens=4000, enabled=True."""
    json_folder = tmp_path / "test_json"

    create_caller_config("test_caller", json_folder)

    config = read_json(json_folder / "openrouter_skill_config.json")
    assert config is not None
    assert config["config"]["ai_temperature"] == 0.7
    assert config["config"]["ai_max_tokens"] == 4000
    assert config["config"]["enabled"] is True
    assert config["config"]["ai_model"] == ""
    assert config["module_name"] == "openrouter"


def test_create_caller_config_data_defaults(tmp_path: Path):
    """Data file should have zeroed counters."""
    json_folder = tmp_path / "test_json"

    create_caller_config("test_caller", json_folder)

    data = read_json(json_folder / "openrouter_skill_data.json")
    assert data is not None
    assert data["data"]["total_requests"] == 0
    assert data["data"]["successful_requests"] == 0
    assert data["data"]["failed_requests"] == 0
    assert data["data"]["models_used"] == {}
    assert data["data"]["last_request"] is None


def test_create_caller_config_log_defaults(tmp_path: Path):
    """Log file should have empty logs list."""
    json_folder = tmp_path / "test_json"

    create_caller_config("test_caller", json_folder)

    log = read_json(json_folder / "openrouter_skill_log.json")
    assert log is not None
    assert log["logs"] == []
    assert log["module_name"] == "openrouter"


def test_create_caller_config_creates_folder(tmp_path: Path):
    """Should create the json_folder if it doesn't exist."""
    json_folder = tmp_path / "nested" / "deep" / "test_json"
    assert not json_folder.exists()

    create_caller_config("test_caller", json_folder)

    assert json_folder.exists()


# =============================================
# provision_json_folder tests
# =============================================


def test_provision_json_folder_creates(tmp_path: Path):
    """Should create folder when it doesn't exist."""
    folder = tmp_path / "new_folder"
    assert not folder.exists()

    result = provision_json_folder(folder)

    assert result is True
    assert folder.exists()


def test_provision_json_folder_existing(tmp_path: Path):
    """Should return True for already-existing folder."""
    folder = tmp_path / "existing"
    folder.mkdir()

    result = provision_json_folder(folder)

    assert result is True


# =============================================
# ensure_caller_config tests (mocked stack detection)
# =============================================


@patch("aipass.api.apps.handlers.openrouter.provision.detect_caller_from_stack")
def test_ensure_caller_config_provisions_new(mock_detect, tmp_path: Path):
    """ensure_caller_config() should create config when none exists."""
    json_folder = tmp_path / "caller_json"
    mock_detect.return_value = ("test_caller", json_folder)

    result = ensure_caller_config("test_caller")

    assert result != {}
    assert (json_folder / "openrouter_skill_config.json").exists()
    assert (json_folder / "openrouter_skill_data.json").exists()
    assert (json_folder / "openrouter_skill_log.json").exists()


@patch("aipass.api.apps.handlers.openrouter.provision.detect_caller_from_stack")
def test_ensure_caller_config_returns_existing(mock_detect, tmp_path: Path):
    """Second call should return existing config without overwriting."""
    json_folder = tmp_path / "caller_json"
    mock_detect.return_value = ("test_caller", json_folder)

    # First call — creates config
    first_result = ensure_caller_config("test_caller")
    assert first_result != {}

    # Read the created config and modify it to detect overwrites
    config_path = json_folder / "openrouter_skill_config.json"
    config = read_json(config_path)
    assert config is not None
    config["config"]["ai_model"] = "test/modified-model"
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)

    # Second call — should return existing (modified) config, not overwrite
    second_result = ensure_caller_config("test_caller")
    assert second_result["config"]["ai_model"] == "test/modified-model"


@patch("aipass.api.apps.handlers.openrouter.provision.detect_caller_from_stack")
def test_ensure_caller_config_no_folder_detected(mock_detect):
    """Should return empty dict when stack detection fails to find json_folder."""
    mock_detect.return_value = (None, None)

    result = ensure_caller_config()

    assert result == {}


# =============================================
# get_default_caller_config tests
# =============================================


def test_get_default_caller_config_structure():
    """Default config should have expected structure."""
    config = get_default_caller_config()

    assert "module_name" in config
    assert "timestamp" in config
    assert "config" in config
    assert isinstance(config["config"], dict)
    assert set(config["config"].keys()) == {"ai_model", "ai_temperature", "ai_max_tokens", "enabled"}


# =============================================
# write_json tests
# =============================================


def test_write_json_creates_file(tmp_path: Path):
    """write_json writes valid JSON and returns True."""
    target = tmp_path / "output.json"
    data = {"key": "value", "number": 42}

    result = write_json(target, data)

    assert result is True
    assert target.exists()
    with open(target, "r", encoding="utf-8") as f:
        loaded = json.load(f)
    assert loaded == data


def test_write_json_creates_parent_dirs(tmp_path: Path):
    """write_json creates parent directories when they don't exist."""
    target = tmp_path / "nested" / "deep" / "data.json"
    data = {"created": True}

    result = write_json(target, data)

    assert result is True
    assert target.exists()
    with open(target, "r", encoding="utf-8") as f:
        loaded = json.load(f)
    assert loaded == data


def test_write_json_uses_indent_and_ensure_ascii(tmp_path: Path):
    """write_json formats with indent=2 and preserves unicode."""
    target = tmp_path / "unicode.json"
    data = {"name": "caf\u00e9"}

    write_json(target, data)

    raw = target.read_text(encoding="utf-8")
    # indent=2 means keys are indented
    assert '  "name"' in raw
    # ensure_ascii=False means unicode is preserved literally
    assert "caf\u00e9" in raw


def test_write_json_overwrites_existing(tmp_path: Path):
    """write_json overwrites an existing file."""
    target = tmp_path / "overwrite.json"
    write_json(target, {"version": 1})
    write_json(target, {"version": 2})

    with open(target, "r", encoding="utf-8") as f:
        loaded = json.load(f)
    assert loaded["version"] == 2


def test_write_json_returns_false_on_error(tmp_path: Path):
    """write_json returns False when writing fails."""
    # Use a path where the parent is a file, not a directory
    blocker = tmp_path / "blocker"
    blocker.write_text("not a dir", encoding="utf-8")
    target = blocker / "sub" / "data.json"

    result = write_json(target, {"key": "value"})

    assert result is False


# =============================================
# get_default_caller_data tests
# =============================================


def test_get_default_caller_data_structure():
    """get_default_caller_data returns dict with expected keys and zeroed counters."""
    data = get_default_caller_data()

    assert data["module_name"] == "openrouter"
    assert "timestamp" in data
    assert isinstance(data["data"], dict)

    counters = data["data"]
    assert counters["total_requests"] == 0
    assert counters["successful_requests"] == 0
    assert counters["failed_requests"] == 0
    assert counters["models_used"] == {}
    assert counters["last_request"] is None


def test_get_default_caller_data_timestamp_is_iso():
    """Timestamp should be a valid ISO-format string."""
    from datetime import datetime

    data = get_default_caller_data()
    # Should not raise
    datetime.fromisoformat(data["timestamp"])


# =============================================
# get_default_caller_log tests
# =============================================


def test_get_default_caller_log_structure():
    """get_default_caller_log returns dict with module_name, timestamp, and empty logs."""
    log = get_default_caller_log()

    assert log["module_name"] == "openrouter"
    assert "timestamp" in log
    assert log["logs"] == []
    assert isinstance(log["logs"], list)


def test_get_default_caller_log_timestamp_is_iso():
    """Timestamp should be a valid ISO-format string."""
    from datetime import datetime

    log = get_default_caller_log()
    # Should not raise
    datetime.fromisoformat(log["timestamp"])
