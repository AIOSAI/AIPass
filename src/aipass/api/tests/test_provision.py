# =================== AIPass ====================
# Name: test_provision.py
# Description: Tests for caller auto-provisioning handler
# Version: 1.0.1
# Created: 2026-03-20
# Modified: 2026-10-24
# =============================================

"""Tests for apps/handlers/openrouter/provision.py, caller auto-provisioning."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(covered_elsewhere) — detect_caller_from_stack, mocked here; tests/test_caller_detection.py
# seedgo: no-test-needed(stdlib) — json.dumps formatting beyond indent and ensure_ascii; the stdlib json module

import json
from pathlib import Path
from unittest.mock import patch

import pytest


from aipass.api.apps.handlers.openrouter.provision import (
    create_caller_config,
    ensure_caller_config,
    get_default_caller_config,
    provision_json_folder,
    read_json,
    write_json,
)


def test_create_caller_config_writes_only_the_config(tmp_path: Path):
    """create_caller_config() writes the config alone: no data or log file, nothing reads them."""
    json_folder = tmp_path / "test_json"

    result = create_caller_config("test_caller", json_folder)

    assert result != {}
    assert sorted(p.name for p in json_folder.iterdir()) == ["openrouter_config.json"]


def test_create_caller_config_defaults(tmp_path: Path):
    """Config defaults should match: ai_temperature=0.7, ai_max_tokens=4000, enabled=True."""
    json_folder = tmp_path / "test_json"

    create_caller_config("test_caller", json_folder)

    config = read_json(json_folder / "openrouter_config.json")
    assert config is not None
    assert config["config"]["ai_temperature"] == 0.7
    assert config["config"]["ai_max_tokens"] == 4000
    assert config["config"]["enabled"] is True
    assert config["config"]["ai_model"] == ""
    assert config["module_name"] == "openrouter"


def test_create_caller_config_creates_folder(tmp_path: Path):
    """Should create the json_folder if it doesn't exist."""
    json_folder = tmp_path / "nested" / "deep" / "test_json"
    assert not json_folder.exists()

    create_caller_config("test_caller", json_folder)

    assert json_folder.exists()


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


@patch("aipass.api.apps.handlers.openrouter.provision.detect_caller_from_stack")
def test_ensure_caller_config_provisions_new(mock_detect, tmp_path: Path):
    """ensure_caller_config() should create config when none exists."""
    json_folder = tmp_path / "caller_json"
    mock_detect.return_value = ("test_caller", json_folder)

    result = ensure_caller_config("test_caller")

    assert result != {}
    assert sorted(p.name for p in json_folder.iterdir()) == ["openrouter_config.json"]


@patch("aipass.api.apps.handlers.openrouter.provision.detect_caller_from_stack")
def test_ensure_caller_config_returns_existing(mock_detect, tmp_path: Path):
    """Second call should return existing config without overwriting."""
    json_folder = tmp_path / "caller_json"
    mock_detect.return_value = ("test_caller", json_folder)

    first_result = ensure_caller_config("test_caller")
    assert first_result != {}

    config_path = json_folder / "openrouter_config.json"
    config = read_json(config_path)
    assert config is not None
    config["config"]["ai_model"] = "test/modified-model"
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)

    second_result = ensure_caller_config("test_caller")
    assert second_result["config"]["ai_model"] == "test/modified-model"


@patch("aipass.api.apps.handlers.openrouter.provision.detect_caller_from_stack")
def test_a_config_that_cannot_be_read_is_never_regenerated_over(mock_detect, tmp_path: Path, monkeypatch):
    """A read error that is not a parse error is never answered by regenerating.

    The folder is writable, so a regeneration would succeed; only the reader fails.
    """
    json_folder = tmp_path / "caller_json"
    json_folder.mkdir()
    config_path = json_folder / "openrouter_config.json"
    config_path.write_text('{"module_name": "kept"}', encoding="utf-8")
    mock_detect.return_value = ("test_caller", json_folder)
    # read_json on a directory raises what the platform raises; ask it rather than assume one.
    unreadable = tmp_path / "unreadable_dir"
    unreadable.mkdir()
    with pytest.raises(OSError) as platform:
        unreadable.open(encoding="utf-8")
    with pytest.raises(type(platform.value)):
        read_json(unreadable)

    def reader_that_fails(path: Path) -> None:
        raise OSError("stand-in read error")

    monkeypatch.setattr("aipass.api.apps.handlers.openrouter.provision.read_json", reader_that_fails)

    assert ensure_caller_config("test_caller") == {}
    assert sorted(p.name for p in json_folder.iterdir()) == ["openrouter_config.json"], "nothing was regenerated"
    assert config_path.read_text(encoding="utf-8") == '{"module_name": "kept"}'


def test_read_json_raises_on_a_file_that_does_not_parse(tmp_path: Path):
    """A parse error raises, never None: None is the absent file's answer only."""
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")

    with pytest.raises(ValueError):
        read_json(broken)


@patch("aipass.api.apps.handlers.openrouter.provision.detect_caller_from_stack")
def test_a_config_that_does_not_parse_is_regenerated(mock_detect, tmp_path: Path):
    """Corrupt is the caller's word: a parse error still regenerates. Mutant: the caller's ValueError catch removed."""
    json_folder = tmp_path / "caller_json"
    json_folder.mkdir()
    (json_folder / "openrouter_config.json").write_text("{not json", encoding="utf-8")
    mock_detect.return_value = ("test_caller", json_folder)

    result = ensure_caller_config("test_caller")

    assert result.get("module_name") == "openrouter", "a corrupt config must be regenerated, not refused"
    assert (json_folder / "openrouter_config.json").read_text(encoding="utf-8") != "{not json"


@patch("aipass.api.apps.handlers.openrouter.provision.detect_caller_from_stack")
def test_ensure_caller_config_no_folder_detected(mock_detect):
    """Should return empty dict when stack detection fails to find json_folder."""
    mock_detect.return_value = (None, None)

    result = ensure_caller_config()

    assert result == {}


def test_get_default_caller_config_structure():
    """Default config should have expected structure."""
    config = get_default_caller_config()

    assert "module_name" in config
    assert "timestamp" in config
    assert "config" in config
    assert isinstance(config["config"], dict)
    assert set(config["config"].keys()) == {"ai_model", "ai_temperature", "ai_max_tokens", "enabled"}


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
    assert '  "name"' in raw
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
    blocker = tmp_path / "blocker"
    blocker.write_text("not a dir", encoding="utf-8")
    target = blocker / "sub" / "data.json"

    result = write_json(target, {"key": "value"})

    assert result is False
