# =================== AIPass ====================
# Name: test_daemon_state.py
# Description: Tests for the dispatch daemon's config, state file and kill switch
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/dispatch/daemon.py -- the safety config, the daemon state file and the kill switch."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — cold_start_prompt/wake_prompt's exact text; only presence is asserted

import json
import pytest
from datetime import datetime, date, timedelta

import aipass.ai_mail.apps.handlers.dispatch.daemon as daemon_mod
from aipass.ai_mail.apps.handlers.dispatch.daemon import (
    load_config,
    load_daemon_state,
    save_daemon_state,
    is_kill_switch_active,
)
from aipass.ai_mail.apps.handlers.dispatch.wake import JsonUnreadable

pytestmark = pytest.mark.usefixtures("daemon_json_silenced", "daemon_paths_in_tmp")


# _read_json is reached through the daemon state file's public load and save, not called directly.


def _state_read_from(monkeypatch, state_file):
    """load_daemon_state() with its state file at `state_file`."""
    monkeypatch.setattr(daemon_mod, "DAEMON_STATE_FILE", state_file)
    return daemon_mod.load_daemon_state()


def _state_saved_to(monkeypatch, state_file, state) -> dict:
    """save_daemon_state(state) into `state_file`; the file as written, its stamp set aside."""
    monkeypatch.setattr(daemon_mod, "DAEMON_STATE_FILE", state_file)
    daemon_mod.save_daemon_state(state)
    written = json.loads(state_file.read_text(encoding="utf-8"))
    assert set(written) - set(state) == set(), "save writes exactly the state it was handed"
    written.pop("last_updated")
    return written


def test_read_json_valid_file(tmp_path, monkeypatch):
    """Valid JSON file returns parsed dict."""
    target = tmp_path / "data.json"
    stored = {"daily_counts": {"@flow": 2}, "session_cycles": {}, "date": str(date.today())}
    target.write_text(json.dumps(stored), encoding="utf-8")

    result = _state_read_from(monkeypatch, target)

    assert result == stored


def test_read_json_missing_file(tmp_path, monkeypatch):
    """Nonexistent file returns None: the state starts empty."""
    result = _state_read_from(monkeypatch, tmp_path / "does_not_exist.json")

    assert result == {"daily_counts": {}, "session_cycles": {}, "date": str(date.today())}


def test_read_json_invalid_json(tmp_path, monkeypatch):
    """Corrupt JSON raises JsonUnreadable, distinct from a missing file."""
    target = tmp_path / "bad.json"
    target.write_text("{not valid json!!!", encoding="utf-8")

    with pytest.raises(JsonUnreadable):
        _state_read_from(monkeypatch, target)


def test_read_json_empty_file(tmp_path, monkeypatch):
    """An empty file is unreadable too, not absent."""
    target = tmp_path / "empty.json"
    target.write_text("", encoding="utf-8")

    with pytest.raises(JsonUnreadable):
        _state_read_from(monkeypatch, target)


def test_write_json_creates_file(tmp_path, monkeypatch):
    """Writing data creates the file with correct content."""
    target = tmp_path / "output.json"

    written = _state_saved_to(monkeypatch, target, {"branches": ["@flow", "@backup"]})

    assert written == {"branches": ["@flow", "@backup"]}


def test_write_json_creates_parent_dirs(tmp_path, monkeypatch):
    """Writing to a nested path creates intermediate directories."""
    target = tmp_path / "deep" / "nested" / "file.json"

    written = _state_saved_to(monkeypatch, target, {"ok": True})

    assert written == {"ok": True}


def test_write_json_unicode(tmp_path, monkeypatch):
    """Unicode content is preserved (ensure_ascii=False)."""
    target = tmp_path / "unicode.json"
    data = {"message": "Hello from branch \u2014 done"}

    _state_saved_to(monkeypatch, target, data)

    raw = target.read_text(encoding="utf-8")
    assert "\u2014" in raw, "Unicode dash should appear literally, not escaped"
    written = json.loads(raw)
    assert written["message"] == "Hello from branch \u2014 done"


def test_load_config_no_file():
    """Missing config file returns all defaults."""
    result = load_config()

    assert isinstance(result, dict)
    assert result["poll_interval_seconds"] == 300
    assert result["max_depth"] == 3
    assert result["max_turns_per_wake"] == 100
    assert result["max_dispatches_per_branch_per_day"] == 10
    assert result["session_rotation_cycles"] == 12
    assert result["autonomous_branches"] == []
    assert "cold_start_prompt" in result
    assert "wake_prompt" in result
    assert "kill_switch_path" in result


def test_load_config_partial_file(tmp_path):
    """Config with only some keys gets remaining defaults filled in."""
    config_file = tmp_path / "safety_config.json"
    config_file.write_text(
        json.dumps({"poll_interval_seconds": 60, "max_depth": 5}),
        encoding="utf-8",
    )

    result = load_config()

    assert result["poll_interval_seconds"] == 60
    assert result["max_depth"] == 5
    assert result["max_turns_per_wake"] == 100
    assert result["max_dispatches_per_branch_per_day"] == 10
    assert result["autonomous_branches"] == []


def test_load_config_full_file(tmp_path):
    """Complete config file is returned with all user values."""
    config_file = tmp_path / "safety_config.json"
    full_config = {
        "kill_switch_path": str(tmp_path / "test_pause"),
        "poll_interval_seconds": 120,
        "max_depth": 2,
        "max_turns_per_wake": 50,
        "max_dispatches_per_branch_per_day": 5,
        "session_rotation_cycles": 6,
        "cold_start_prompt": "Custom cold start",
        "wake_prompt": "Custom wake",
        "autonomous_branches": ["@flow", "@backup"],
    }
    config_file.write_text(json.dumps(full_config), encoding="utf-8")

    result = load_config()

    assert result["poll_interval_seconds"] == 120
    assert result["max_depth"] == 2
    assert result["max_turns_per_wake"] == 50
    assert result["max_dispatches_per_branch_per_day"] == 5
    assert result["session_rotation_cycles"] == 6
    assert result["cold_start_prompt"] == "Custom cold start"
    assert result["wake_prompt"] == "Custom wake"
    assert result["autonomous_branches"] == ["@flow", "@backup"]
    assert result["kill_switch_path"] == str(tmp_path / "test_pause")


def test_load_config_corrupt_json_refuses(tmp_path):
    """A corrupt safety config raises, never the defaults.

    The defaults are the less safe side: autonomous_branches [] means every
    branch is autonomous, and the kill switch path is the default one.
    """
    config_file = tmp_path / "safety_config.json"
    config_file.write_text("{{broken", encoding="utf-8")

    with pytest.raises(JsonUnreadable):
        load_config()


def test_load_daemon_state_corrupt_refuses(tmp_path):
    """A corrupt state file raises: an empty state would reset today's dispatch counts."""
    (tmp_path / "daemon_state.json").write_text("{{broken", encoding="utf-8")

    with pytest.raises(JsonUnreadable):
        load_daemon_state()


def test_load_daemon_state_no_file():
    """Missing state file returns empty state with today's date."""
    result = load_daemon_state()

    assert isinstance(result, dict)
    assert result["daily_counts"] == {}
    assert result["session_cycles"] == {}
    assert result["date"] == str(date.today())


def test_load_daemon_state_same_day(tmp_path):
    """State from today preserves existing daily counts."""
    state_file = tmp_path / "daemon_state.json"
    state = {
        "daily_counts": {"@flow": 3, "@backup": 1},
        "session_cycles": {},
        "date": str(date.today()),
    }
    state_file.write_text(json.dumps(state), encoding="utf-8")

    result = load_daemon_state()

    assert result["daily_counts"] == {"@flow": 3, "@backup": 1}
    assert result["date"] == str(date.today())


def test_load_daemon_state_new_day_resets_counts(tmp_path):
    """State from a previous day resets daily_counts and updates date."""
    state_file = tmp_path / "daemon_state.json"
    yesterday = str(date.today() - timedelta(days=1))
    state = {
        "daily_counts": {"@flow": 10, "@backup": 5},
        "session_cycles": {"some_branch": 4},
        "date": yesterday,
    }
    state_file.write_text(json.dumps(state), encoding="utf-8")

    result = load_daemon_state()

    assert result["daily_counts"] == {}
    assert result["date"] == str(date.today())
    assert result["session_cycles"] == {"some_branch": 4}


def test_save_daemon_state_writes_file(tmp_path):
    """save_daemon_state writes state with last_updated timestamp."""
    state = {"daily_counts": {"@flow": 2}, "date": str(date.today())}

    save_daemon_state(state)

    state_file = tmp_path / "daemon_state.json"
    assert state_file.exists()
    written = json.loads(state_file.read_text(encoding="utf-8"))
    assert written["daily_counts"] == {"@flow": 2}
    assert written["date"] == str(date.today())
    assert "last_updated" in written
    parsed = datetime.strptime(written["last_updated"], "%Y-%m-%d %H:%M:%S")
    assert (datetime.now() - parsed).total_seconds() < 5


def test_kill_switch_active_when_file_exists(tmp_path):
    """Returns True when the kill switch file exists."""
    pause_file = tmp_path / "autonomous_pause"
    pause_file.touch()

    result = is_kill_switch_active({"kill_switch_path": str(pause_file)})

    assert result is True


def test_kill_switch_inactive_when_no_file(tmp_path):
    """Returns False when the kill switch file does not exist."""
    result = is_kill_switch_active({"kill_switch_path": str(tmp_path / "no_such_file")})

    assert result is False


def test_kill_switch_uses_default_path_when_key_missing(tmp_path, monkeypatch):
    """With no kill_switch_path key it consults <repo root>/.aipass/autonomous_pause.

    _REPO_ROOT is aimed at tmp_path so both answers are observable and the result is machine-independent.
    """
    monkeypatch.setattr(daemon_mod, "_REPO_ROOT", tmp_path)
    default_path = tmp_path / ".aipass" / "autonomous_pause"

    assert is_kill_switch_active({}) is False

    default_path.parent.mkdir(parents=True)
    default_path.touch()

    assert is_kill_switch_active({}) is True
