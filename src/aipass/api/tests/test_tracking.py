# =================== AIPass ====================
# Name: test_tracking.py
# Description: Tests for usage tracking handler
# Version: 1.0.0
# Created: 2026-04-03
# Modified: 2026-04-03
# =============================================

"""
Tests for tracking.py -- usage tracking handler.

Tests:
- get_generation_metrics() HTTP success, non-200, invalid structure, exception
- store_usage_data() new file creation, existing file update, per-caller stats,
  daily totals, newest-first ordering, exception handling
"""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from aipass.api.apps.handlers.usage.tracking import (
    get_generation_metrics,
    store_usage_data,
)

_TRACKING_MOD = "aipass.api.apps.handlers.usage.tracking"


# =============================================
# get_generation_metrics tests
# =============================================


@patch(f"{_TRACKING_MOD}.requests")
def test_get_generation_metrics_success(mock_requests: MagicMock):
    """Returns metrics dict when API returns 200 with valid structure."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": {
            "total_cost": 0.0042,
            "tokens_prompt": 150,
            "tokens_completion": 80,
            "generation_time": 1200,
            "latency": 1500,
            "provider_name": "anthropic",
        }
    }
    mock_requests.get.return_value = mock_response

    result = get_generation_metrics("gen-abc-123", "sk-or-test-key")

    assert result is not None
    assert result["total_cost"] == 0.0042
    assert result["tokens_prompt"] == 150
    assert result["tokens_completion"] == 80
    assert result["generation_time"] == 1200
    assert result["latency"] == 1500
    assert result["provider_name"] == "anthropic"

    # Verify request was made with correct params
    mock_requests.get.assert_called_once()
    call_kwargs = mock_requests.get.call_args
    assert call_kwargs[1]["params"] == {"id": "gen-abc-123"}
    assert "Bearer sk-or-test-key" in call_kwargs[1]["headers"]["Authorization"]


@patch(f"{_TRACKING_MOD}.requests")
def test_get_generation_metrics_non_200(mock_requests: MagicMock):
    """Returns None when API returns non-200 status."""
    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_requests.get.return_value = mock_response

    result = get_generation_metrics("gen-missing", "sk-or-key")

    assert result is None


@patch(f"{_TRACKING_MOD}.requests")
def test_get_generation_metrics_invalid_structure_no_data_key(mock_requests: MagicMock):
    """Returns None when response JSON lacks 'data' key."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"error": "not found"}
    mock_requests.get.return_value = mock_response

    result = get_generation_metrics("gen-bad", "sk-or-key")

    assert result is None


@patch(f"{_TRACKING_MOD}.requests")
def test_get_generation_metrics_invalid_structure_empty_response(mock_requests: MagicMock):
    """Returns None when response JSON is empty/None."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = None
    mock_requests.get.return_value = mock_response

    result = get_generation_metrics("gen-empty", "sk-or-key")

    assert result is None


@patch(f"{_TRACKING_MOD}.requests")
def test_get_generation_metrics_request_exception(mock_requests: MagicMock):
    """Returns None when requests raises an exception."""
    import requests as real_requests

    mock_requests.get.side_effect = real_requests.exceptions.ConnectionError("refused")
    mock_requests.exceptions = real_requests.exceptions

    result = get_generation_metrics("gen-fail", "sk-or-key")

    assert result is None


@patch(f"{_TRACKING_MOD}.requests")
def test_get_generation_metrics_timeout(mock_requests: MagicMock):
    """Returns None on request timeout."""
    import requests as real_requests

    mock_requests.get.side_effect = real_requests.exceptions.Timeout("timed out")
    mock_requests.exceptions = real_requests.exceptions

    result = get_generation_metrics("gen-timeout", "sk-or-key")

    assert result is None


@patch(f"{_TRACKING_MOD}.requests")
def test_get_generation_metrics_defaults_missing_fields(mock_requests: MagicMock):
    """Missing fields in metrics default to 0 / 'unknown'."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"data": {}}
    mock_requests.get.return_value = mock_response

    result = get_generation_metrics("gen-sparse", "sk-or-key")

    assert result is not None
    assert result["total_cost"] == 0.0
    assert result["tokens_prompt"] == 0
    assert result["tokens_completion"] == 0
    assert result["generation_time"] == 0
    assert result["latency"] == 0
    assert result["provider_name"] == "unknown"


# =============================================
# store_usage_data tests
# =============================================


@patch(f"{_TRACKING_MOD}.API_JSON_DIR")
def test_store_usage_data_creates_new_file(mock_dir: MagicMock, tmp_path: Path):
    """store_usage_data creates initial structure when file doesn't exist."""
    mock_dir.__truediv__ = lambda self, other: tmp_path / other
    mock_dir.mkdir = MagicMock()

    metrics = {
        "total_cost": 0.005,
        "tokens_prompt": 100,
        "tokens_completion": 50,
        "generation_time": 800,
        "latency": 1000,
        "provider_name": "anthropic",
    }

    result = store_usage_data("test_caller", "anthropic/claude-3.5-sonnet", "gen-001", metrics)

    assert result is True

    data_path = tmp_path / "usage_tracker_data.json"
    assert data_path.exists()

    with open(data_path, "r", encoding="utf-8") as f:
        wrapper = json.load(f)

    assert wrapper["module_name"] == "api_usage"
    data = wrapper["data"]

    # Session totals
    assert data["current_session"]["total_requests"] == 1
    assert data["current_session"]["total_cost"] == 0.005
    assert data["current_session"]["total_tokens"] == 150

    # Per-caller stats
    assert "test_caller" in data["usage_by_caller"]
    caller_data = data["usage_by_caller"]["test_caller"]
    assert caller_data["requests"] == 1
    assert caller_data["total_cost"] == 0.005
    assert caller_data["total_tokens"] == 150
    assert caller_data["models_used"]["anthropic/claude-3.5-sonnet"] == 1

    # Generation tracking
    assert "gen-001" in data["generation_tracking"]
    entry = data["generation_tracking"]["gen-001"]
    assert entry["caller"] == "test_caller"
    assert entry["model"] == "anthropic/claude-3.5-sonnet"
    assert entry["usage_data"] == metrics


@patch(f"{_TRACKING_MOD}.API_JSON_DIR")
def test_store_usage_data_updates_existing(mock_dir: MagicMock, tmp_path: Path):
    """store_usage_data increments counters in existing file."""
    mock_dir.__truediv__ = lambda self, other: tmp_path / other
    mock_dir.mkdir = MagicMock()

    metrics = {
        "total_cost": 0.01,
        "tokens_prompt": 200,
        "tokens_completion": 100,
        "generation_time": 500,
        "latency": 700,
        "provider_name": "openai",
    }

    # First call creates the file
    store_usage_data("caller_a", "openai/gpt-4", "gen-100", metrics)

    # Second call updates
    result = store_usage_data("caller_a", "openai/gpt-4", "gen-101", metrics)

    assert result is True

    data_path = tmp_path / "usage_tracker_data.json"
    with open(data_path, "r", encoding="utf-8") as f:
        wrapper = json.load(f)

    data = wrapper["data"]
    assert data["current_session"]["total_requests"] == 2
    assert data["current_session"]["total_cost"] == pytest.approx(0.02)
    assert data["current_session"]["total_tokens"] == 600

    caller_data = data["usage_by_caller"]["caller_a"]
    assert caller_data["requests"] == 2
    assert caller_data["models_used"]["openai/gpt-4"] == 2


@patch(f"{_TRACKING_MOD}.API_JSON_DIR")
def test_store_usage_data_newest_first_ordering(mock_dir: MagicMock, tmp_path: Path):
    """Generation tracking stores newest entry first."""
    mock_dir.__truediv__ = lambda self, other: tmp_path / other
    mock_dir.mkdir = MagicMock()

    metrics = {
        "total_cost": 0.001,
        "tokens_prompt": 10,
        "tokens_completion": 5,
        "generation_time": 100,
        "latency": 200,
        "provider_name": "test",
    }

    store_usage_data("caller", "model/a", "gen-first", metrics)
    store_usage_data("caller", "model/a", "gen-second", metrics)

    data_path = tmp_path / "usage_tracker_data.json"
    with open(data_path, "r", encoding="utf-8") as f:
        wrapper = json.load(f)

    tracking_keys = list(wrapper["data"]["generation_tracking"].keys())
    assert tracking_keys[0] == "gen-second"
    assert tracking_keys[1] == "gen-first"


@patch(f"{_TRACKING_MOD}.API_JSON_DIR")
def test_store_usage_data_multiple_callers(mock_dir: MagicMock, tmp_path: Path):
    """store_usage_data tracks multiple callers independently."""
    mock_dir.__truediv__ = lambda self, other: tmp_path / other
    mock_dir.mkdir = MagicMock()

    metrics = {
        "total_cost": 0.003,
        "tokens_prompt": 50,
        "tokens_completion": 25,
        "generation_time": 300,
        "latency": 400,
        "provider_name": "test",
    }

    store_usage_data("caller_x", "model/x", "gen-x1", metrics)
    store_usage_data("caller_y", "model/y", "gen-y1", metrics)

    data_path = tmp_path / "usage_tracker_data.json"
    with open(data_path, "r", encoding="utf-8") as f:
        wrapper = json.load(f)

    by_caller = wrapper["data"]["usage_by_caller"]
    assert "caller_x" in by_caller
    assert "caller_y" in by_caller
    assert by_caller["caller_x"]["requests"] == 1
    assert by_caller["caller_y"]["requests"] == 1
    assert by_caller["caller_x"]["models_used"]["model/x"] == 1
    assert by_caller["caller_y"]["models_used"]["model/y"] == 1


@patch(f"{_TRACKING_MOD}.API_JSON_DIR")
def test_store_usage_data_daily_totals(mock_dir: MagicMock, tmp_path: Path):
    """store_usage_data updates daily totals for today's date."""
    from datetime import datetime

    mock_dir.__truediv__ = lambda self, other: tmp_path / other
    mock_dir.mkdir = MagicMock()

    metrics = {
        "total_cost": 0.002,
        "tokens_prompt": 40,
        "tokens_completion": 20,
        "generation_time": 200,
        "latency": 300,
        "provider_name": "test",
    }

    store_usage_data("caller", "model/a", "gen-daily", metrics)

    data_path = tmp_path / "usage_tracker_data.json"
    with open(data_path, "r", encoding="utf-8") as f:
        wrapper = json.load(f)

    today = datetime.now().date().isoformat()
    daily = wrapper["data"]["daily_totals"]
    assert today in daily
    assert daily[today]["requests"] == 1
    assert daily[today]["cost"] == 0.002
    assert daily[today]["tokens"] == 60


@patch(f"{_TRACKING_MOD}.API_JSON_DIR")
def test_store_usage_data_returns_false_on_exception(mock_dir: MagicMock, tmp_path: Path):
    """store_usage_data returns False when an exception occurs."""
    # Point to a path that will fail (parent is a file, not a dir)
    blocker = tmp_path / "blocker_file"
    blocker.write_text("not a dir", encoding="utf-8")
    mock_dir.__truediv__ = lambda self, other: blocker / other
    mock_dir.mkdir = MagicMock(side_effect=OSError("cannot create"))

    metrics = {
        "total_cost": 0.0,
        "tokens_prompt": 0,
        "tokens_completion": 0,
        "generation_time": 0,
        "latency": 0,
        "provider_name": "test",
    }

    result = store_usage_data("caller", "model", "gen-err", metrics)

    assert result is False
