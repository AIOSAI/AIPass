# =================== AIPass ====================
# Name: test_aggregation.py
# Description: Tests for usage aggregation handler
# Version: 1.0.0
# Created: 2026-05-12
# Modified: 2026-05-12
# =============================================

"""
Tests for aggregation.py -- usage aggregation handler.

Tests:
- get_overall_stats() no file, empty data, no usage_by_caller, valid multi-caller, exception
- get_caller_usage() no file, caller not found, valid caller, exception
- get_session_summary() no file, no session data, valid session, exception
"""

import json
from pathlib import Path

import pytest

from aipass.api.apps.handlers.usage.aggregation import (  # seedgo test_coverage detection
    get_overall_stats,
    get_caller_usage,
    get_session_summary,
)

_AGG_MOD = "aipass.api.apps.handlers.usage.aggregation"


# =============================================
# Helpers
# =============================================


def _write_usage_file(directory: Path, data: dict) -> Path:
    """Write a usage tracker JSON file to the given directory."""
    file_path = directory / "usage_tracker_data.json"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return file_path


# =============================================
# get_overall_stats tests
# =============================================


class TestGetOverallStats:
    """Tests for get_overall_stats()."""

    def test_no_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Returns empty dict when usage data file does not exist."""
        monkeypatch.setattr(f"{_AGG_MOD}.API_JSON_DIR", tmp_path)
        result = get_overall_stats()
        assert result == {}

    def test_empty_data(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Returns empty dict when file has no 'data' key."""
        monkeypatch.setattr(f"{_AGG_MOD}.API_JSON_DIR", tmp_path)
        _write_usage_file(tmp_path, {})
        result = get_overall_stats()
        assert result == {}

    def test_no_usage_by_caller(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Returns empty dict when usage_by_caller is empty."""
        monkeypatch.setattr(f"{_AGG_MOD}.API_JSON_DIR", tmp_path)
        _write_usage_file(tmp_path, {"data": {"usage_by_caller": {}}})
        result = get_overall_stats()
        assert result == {}

    def test_valid_data_multiple_callers(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Aggregates requests, cost, tokens, and models across callers."""
        monkeypatch.setattr(f"{_AGG_MOD}.API_JSON_DIR", tmp_path)
        data = {
            "data": {
                "usage_by_caller": {
                    "caller_a": {
                        "requests": 10,
                        "total_cost": 0.50,
                        "total_tokens": 5000,
                        "models_used": ["claude-3", "gpt-4"],
                    },
                    "caller_b": {
                        "requests": 5,
                        "total_cost": 0.25,
                        "total_tokens": 2500,
                        "models_used": ["claude-3"],
                    },
                }
            }
        }
        _write_usage_file(tmp_path, data)

        result = get_overall_stats()

        assert result["total_requests"] == 15
        assert result["total_cost"] == pytest.approx(0.75)
        assert result["total_tokens"] == 7500
        assert result["callers"] == 2
        assert result["models_used"] == ["claude-3", "gpt-4"]

    def test_exception_handling(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Returns empty dict when JSON is malformed."""
        monkeypatch.setattr(f"{_AGG_MOD}.API_JSON_DIR", tmp_path)
        file_path = tmp_path / "usage_tracker_data.json"
        file_path.write_text("not valid json", encoding="utf-8")
        result = get_overall_stats()
        assert result == {}


# =============================================
# get_caller_usage tests
# =============================================


class TestGetCallerUsage:
    """Tests for get_caller_usage()."""

    def test_no_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Returns empty dict when usage data file does not exist."""
        monkeypatch.setattr(f"{_AGG_MOD}.API_JSON_DIR", tmp_path)
        result = get_caller_usage("missing_caller")
        assert result == {}

    def test_caller_not_found(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Returns empty dict when requested caller is not in usage data."""
        monkeypatch.setattr(f"{_AGG_MOD}.API_JSON_DIR", tmp_path)
        data = {
            "data": {
                "usage_by_caller": {
                    "other_caller": {"requests": 1, "total_cost": 0.01},
                }
            }
        }
        _write_usage_file(tmp_path, data)
        result = get_caller_usage("nonexistent")
        assert result == {}

    def test_valid_caller_data(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Returns caller dict with requests, cost, tokens, and models."""
        monkeypatch.setattr(f"{_AGG_MOD}.API_JSON_DIR", tmp_path)
        caller_data = {
            "requests": 42,
            "total_cost": 1.23,
            "total_tokens": 10000,
            "models_used": ["claude-3"],
            "last_request": "2026-05-01T12:00:00",
        }
        data = {"data": {"usage_by_caller": {"my_caller": caller_data}}}
        _write_usage_file(tmp_path, data)

        result = get_caller_usage("my_caller")

        assert result["requests"] == 42
        assert result["total_cost"] == pytest.approx(1.23)
        assert result["total_tokens"] == 10000
        assert result["models_used"] == ["claude-3"]

    def test_exception_returns_empty(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Returns empty dict when JSON is malformed."""
        monkeypatch.setattr(f"{_AGG_MOD}.API_JSON_DIR", tmp_path)
        file_path = tmp_path / "usage_tracker_data.json"
        file_path.write_text("{invalid", encoding="utf-8")
        result = get_caller_usage("any")
        assert result == {}


# =============================================
# get_session_summary tests
# =============================================


class TestGetSessionSummary:
    """Tests for get_session_summary()."""

    def test_no_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Returns empty dict when usage data file does not exist."""
        monkeypatch.setattr(f"{_AGG_MOD}.API_JSON_DIR", tmp_path)
        result = get_session_summary()
        assert result == {}

    def test_no_session_data(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Returns empty dict when current_session is empty."""
        monkeypatch.setattr(f"{_AGG_MOD}.API_JSON_DIR", tmp_path)
        _write_usage_file(tmp_path, {"data": {"current_session": {}}})
        result = get_session_summary()
        assert result == {}

    def test_valid_session_data(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Returns session dict with start_time, requests, cost, and tokens."""
        monkeypatch.setattr(f"{_AGG_MOD}.API_JSON_DIR", tmp_path)
        session_data = {
            "start_time": "2026-05-12T08:00:00",
            "total_requests": 20,
            "total_cost": 0.85,
            "total_tokens": 8000,
        }
        _write_usage_file(tmp_path, {"data": {"current_session": session_data}})

        result = get_session_summary()

        assert result["start_time"] == "2026-05-12T08:00:00"
        assert result["total_requests"] == 20
        assert result["total_cost"] == pytest.approx(0.85)
        assert result["total_tokens"] == 8000

    def test_session_id_param_accepted(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Accepts optional session_id parameter without error."""
        monkeypatch.setattr(f"{_AGG_MOD}.API_JSON_DIR", tmp_path)
        session_data = {"total_requests": 5}
        _write_usage_file(tmp_path, {"data": {"current_session": session_data}})

        result = get_session_summary(session_id="sess-abc")

        assert result["total_requests"] == 5

    def test_exception_returns_empty(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Returns empty dict when JSON is malformed."""
        monkeypatch.setattr(f"{_AGG_MOD}.API_JSON_DIR", tmp_path)
        file_path = tmp_path / "usage_tracker_data.json"
        file_path.write_text("broken json!", encoding="utf-8")
        result = get_session_summary()
        assert result == {}
