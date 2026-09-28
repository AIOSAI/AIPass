# =================== AIPass ====================
# Name: test_aggregation.py
# Description: Tests for usage aggregation handler
# Version: 1.0.0
# Created: 2026-05-12
# Modified: 2026-09-28
# =============================================

"""Tests for apps/handlers/usage/aggregation.py, the usage aggregation handler."""

# Tests:
# - get_overall_stats() no file, empty data, no usage_by_caller, valid multi-caller, exception
# - get_caller_usage() no file, caller not found, valid caller, exception
# - get_session_summary() no file, no session data, valid session, exception

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that aggregation.py parses and imports
# seedgo: no-test-needed(constant) — MODULE_NAME and DATA_FILE's text; the tests read the file by that name
# seedgo: no-test-needed(json_handler) — API_JSON_DIR's real location; every test redirects it into the sandbox

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

    def test_a_store_that_does_not_parse_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """A malformed store raises: {} is the no-data answer, so a failure may not wear it (api, fleet green leg 3)."""
        monkeypatch.setattr(f"{_AGG_MOD}.API_JSON_DIR", tmp_path)
        file_path = tmp_path / "usage_tracker_data.json"
        file_path.write_text("not valid json", encoding="utf-8")
        with pytest.raises(ValueError):
            get_overall_stats()


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

    def test_a_store_that_does_not_parse_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """A malformed store raises rather than answering 'no such caller' (api, fleet green leg 3)."""
        monkeypatch.setattr(f"{_AGG_MOD}.API_JSON_DIR", tmp_path)
        file_path = tmp_path / "usage_tracker_data.json"
        file_path.write_text("{invalid", encoding="utf-8")
        with pytest.raises(ValueError):
            get_caller_usage("any")


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

    def test_a_store_that_does_not_parse_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """A malformed store raises rather than answering 'no session yet' (api, fleet green leg 3)."""
        monkeypatch.setattr(f"{_AGG_MOD}.API_JSON_DIR", tmp_path)
        file_path = tmp_path / "usage_tracker_data.json"
        file_path.write_text("broken json!", encoding="utf-8")
        with pytest.raises(ValueError):
            get_session_summary()
