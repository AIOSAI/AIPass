# =================== AIPass ====================
# Name: test_dispatch_status.py
# Description: Tests for dispatch status handler
# Version: 1.0.0
# Created: 2026-03-24
# Modified: 2026-03-24
# =============================================

"""Tests for dispatch status handler -- dispatch log I/O and age calculation."""

import json
import pytest
from datetime import datetime, timedelta

import aipass.ai_mail.apps.handlers.dispatch.status as status_mod
from aipass.ai_mail.apps.handlers.dispatch.status import (
    load_dispatch_log,
    save_dispatch_log,
    log_dispatch,
    calculate_age,
)


# --- Fixtures --------------------------------------------------------


@pytest.fixture
def dispatch_log_file(tmp_path, monkeypatch):
    """Redirect DISPATCH_LOG_FILE to an isolated tmp_path location."""
    log_file = tmp_path / ".ai_mail.local" / "dispatch_log.json"
    monkeypatch.setattr(status_mod, "DISPATCH_LOG_FILE", log_file)
    return log_file


# --- load_dispatch_log tests -----------------------------------------


def test_load_dispatch_log_no_file(dispatch_log_file):
    """Missing file returns empty list."""
    assert not dispatch_log_file.exists()
    result = load_dispatch_log()
    assert result == []
    assert isinstance(result, list)


def test_load_dispatch_log_valid(dispatch_log_file):
    """Valid JSON with dispatches key returns that list."""
    entries = [
        {"branch": "@flow", "pid": 1234, "status": "spawned", "timestamp": "2026-03-24 10:00:00"},
        {"branch": "@backup", "pid": 5678, "status": "spawned", "timestamp": "2026-03-24 10:05:00"},
    ]
    dispatch_log_file.parent.mkdir(parents=True, exist_ok=True)
    dispatch_log_file.write_text(
        json.dumps({"dispatches": entries}, indent=2),
        encoding="utf-8",
    )

    result = load_dispatch_log()
    assert isinstance(result, list)
    assert len(result) == 2
    # Verify ALL keys and values on first entry
    assert result[0]["branch"] == "@flow"
    assert result[0]["pid"] == 1234
    assert result[0]["status"] == "spawned"
    assert result[0]["timestamp"] == "2026-03-24 10:00:00"
    assert set(result[0].keys()) == {"branch", "pid", "status", "timestamp"}
    # Verify ALL keys and values on second entry
    assert result[1]["branch"] == "@backup"
    assert result[1]["pid"] == 5678
    assert result[1]["status"] == "spawned"
    assert result[1]["timestamp"] == "2026-03-24 10:05:00"
    assert set(result[1].keys()) == {"branch", "pid", "status", "timestamp"}


def test_load_dispatch_log_invalid_json(dispatch_log_file):
    """Corrupt JSON returns empty list instead of crashing."""
    dispatch_log_file.parent.mkdir(parents=True, exist_ok=True)
    dispatch_log_file.write_text("{this is not valid json!!!", encoding="utf-8")

    result = load_dispatch_log()
    assert result == []
    assert isinstance(result, list)


# --- save_dispatch_log tests ------------------------------------------


def test_save_dispatch_log(dispatch_log_file):
    """Saving a list creates the file with correct structure."""
    entries = [
        {"branch": "@trigger", "pid": 9999, "status": "spawned", "timestamp": "2026-03-24 12:00:00"},
    ]

    result = save_dispatch_log(entries)
    assert result is True
    assert dispatch_log_file.exists()

    data = json.loads(dispatch_log_file.read_text(encoding="utf-8"))
    assert set(data.keys()) == {"dispatches", "last_updated"}
    # Verify last_updated is a valid parseable timestamp
    datetime.strptime(data["last_updated"], "%Y-%m-%d %H:%M:%S")
    assert isinstance(data["dispatches"], list)
    assert len(data["dispatches"]) == 1
    assert data["dispatches"][0]["branch"] == "@trigger"
    assert data["dispatches"][0]["pid"] == 9999
    assert data["dispatches"][0]["status"] == "spawned"
    assert data["dispatches"][0]["timestamp"] == "2026-03-24 12:00:00"
    assert set(data["dispatches"][0].keys()) == {"branch", "pid", "status", "timestamp"}


def test_save_dispatch_log_truncates_to_50(dispatch_log_file):
    """Saving 60 entries keeps only the last 50."""
    entries = [
        {"branch": f"@branch_{i}", "pid": i, "status": "spawned", "timestamp": "2026-03-24 12:00:00"} for i in range(60)
    ]

    result = save_dispatch_log(entries)
    assert result is True

    data = json.loads(dispatch_log_file.read_text(encoding="utf-8"))
    assert len(data["dispatches"]) == 50
    # Should keep the LAST 50 (indices 10-59)
    assert data["dispatches"][0]["branch"] == "@branch_10"
    assert data["dispatches"][-1]["branch"] == "@branch_59"


# --- log_dispatch tests -----------------------------------------------


def test_log_dispatch_creates_entry(dispatch_log_file, monkeypatch):
    """log_dispatch creates an entry with correct fields."""
    # Mock json_handler.log_operation to avoid side effects
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.dispatch.status.json_handler.log_operation",
        lambda *args, **kwargs: None,
    )

    result = log_dispatch("@flow", 4242, "spawned")
    assert result is True

    data = json.loads(dispatch_log_file.read_text(encoding="utf-8"))
    assert len(data["dispatches"]) == 1

    entry = data["dispatches"][0]
    assert set(entry.keys()) == {"branch", "pid", "status", "timestamp"}
    assert entry["branch"] == "@flow"
    assert entry["pid"] == 4242
    assert entry["status"] == "spawned"
    assert isinstance(entry["timestamp"], str)
    assert len(entry["timestamp"]) == 19  # "YYYY-MM-DD HH:MM:SS"
    # Verify timestamp format is parseable and recent (within last 5 seconds)
    parsed_ts = datetime.strptime(entry["timestamp"], "%Y-%m-%d %H:%M:%S")
    assert (datetime.now() - parsed_ts).total_seconds() < 5


def test_log_dispatch_with_error(dispatch_log_file, monkeypatch):
    """log_dispatch with error_msg includes an 'error' key in the entry."""
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.dispatch.status.json_handler.log_operation",
        lambda *args, **kwargs: None,
    )

    result = log_dispatch("@backup", None, "failed", error_msg="Connection timeout")
    assert result is True

    data = json.loads(dispatch_log_file.read_text(encoding="utf-8"))
    assert len(data["dispatches"]) == 1

    entry = data["dispatches"][0]
    assert entry["branch"] == "@backup"
    assert entry["pid"] is None
    assert entry["status"] == "failed"
    assert entry["error"] == "Connection timeout"


# --- calculate_age tests ----------------------------------------------


def test_calculate_age_seconds():
    """Timestamp from 30 seconds ago returns '30s ago'."""
    ts = (datetime.now() - timedelta(seconds=30)).strftime("%Y-%m-%d %H:%M:%S")
    result = calculate_age(ts)
    assert result.endswith("s ago")
    # Extract numeric part and verify range (allow 1s drift for execution time)
    age_value = int(result.replace("s ago", ""))
    assert 29 <= age_value <= 32


def test_calculate_age_minutes():
    """Timestamp from 5 minutes ago returns '5m ago'."""
    ts = (datetime.now() - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
    result = calculate_age(ts)
    assert result == "5m ago"


def test_calculate_age_hours():
    """Timestamp from 3 hours ago returns '3h ago'."""
    ts = (datetime.now() - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S")
    result = calculate_age(ts)
    assert result == "3h ago"


def test_calculate_age_days():
    """Timestamp from 2 days ago returns '2d ago'."""
    ts = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")
    result = calculate_age(ts)
    assert result == "2d ago"


def test_calculate_age_empty_string():
    """Empty string returns 'unknown'."""
    result = calculate_age("")
    assert result == "unknown"


def test_calculate_age_invalid_format():
    """Unparseable string returns 'unknown'."""
    result = calculate_age("not-a-date")
    assert result == "unknown"
