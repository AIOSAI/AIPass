# =================== AIPass ====================
# Name: test_tracking.py
# Description: Tests for usage tracking handler
# Version: 1.0.0
# Created: 2026-04-03
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/usage/tracking.py, the usage tracking handler."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(external) — the live OpenRouter generation endpoint; requests.get is mocked, no network
# seedgo: no-test-needed(constant) — DEFAULT_REQUEST_TIMEOUT's value

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from aipass.api.apps.handlers.usage import tracking
from aipass.api.apps.handlers.usage.tracking import (
    MetricsUnavailable,
    get_generation_metrics,
    store_usage_data,
    track_usage,
)

_TRACKING_MOD = "aipass.api.apps.handlers.usage.tracking"


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

    result = get_generation_metrics("gen-abc-123", "FAKE-sk-or-testkey")

    assert result is not None
    assert result["total_cost"] == 0.0042
    assert result["tokens_prompt"] == 150
    assert result["tokens_completion"] == 80
    assert result["generation_time"] == 1200
    assert result["latency"] == 1500
    assert result["provider_name"] == "anthropic"

    mock_requests.get.assert_called_once()
    call_kwargs = mock_requests.get.call_args
    assert call_kwargs[1]["params"] == {"id": "gen-abc-123"}
    assert "Bearer FAKE-sk-or-testkey" in call_kwargs[1]["headers"]["Authorization"]


@patch(f"{_TRACKING_MOD}.requests")
def test_get_generation_metrics_non_200(mock_requests: MagicMock):
    """A non-200 raises MetricsUnavailable naming the status and the generation."""
    # The reason travels in str(exc) so track_usage can say which of five failures happened.
    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_requests.get.return_value = mock_response

    with pytest.raises(MetricsUnavailable) as refusal:
        get_generation_metrics("gen-missing", "FAKE-sk-or-key")

    assert str(refusal.value) == "OpenRouter answered status 404 for generation gen-missing"


@patch(f"{_TRACKING_MOD}.requests")
def test_get_generation_metrics_invalid_structure_no_data_key(mock_requests: MagicMock):
    """A 200 whose JSON lacks 'data' raises, naming the generation."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"error": "not found"}
    mock_requests.get.return_value = mock_response

    with pytest.raises(MetricsUnavailable) as refusal:
        get_generation_metrics("gen-bad", "FAKE-sk-or-key")

    assert str(refusal.value) == "OpenRouter answered without a data block for generation gen-bad"


@patch(f"{_TRACKING_MOD}.requests")
def test_get_generation_metrics_invalid_structure_empty_response(mock_requests: MagicMock):
    """A 200 whose JSON is empty raises the same refusal as one without 'data'."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = None
    mock_requests.get.return_value = mock_response

    with pytest.raises(MetricsUnavailable) as refusal:
        get_generation_metrics("gen-empty", "FAKE-sk-or-key")

    assert str(refusal.value) == "OpenRouter answered without a data block for generation gen-empty"


@patch(f"{_TRACKING_MOD}.requests")
def test_get_generation_metrics_request_exception(mock_requests: MagicMock):
    """A request error raises with the request's own sentence in it."""
    import requests as real_requests

    mock_requests.get.side_effect = real_requests.exceptions.ConnectionError("refused")
    mock_requests.exceptions = real_requests.exceptions

    with pytest.raises(MetricsUnavailable) as refusal:
        get_generation_metrics("gen-fail", "FAKE-sk-or-key")

    assert str(refusal.value) == "Request error querying generation gen-fail: refused"


@patch(f"{_TRACKING_MOD}.requests")
def test_get_generation_metrics_timeout(mock_requests: MagicMock):
    """A timeout raises, and says it was a timeout rather than any request error."""
    import requests as real_requests

    mock_requests.get.side_effect = real_requests.exceptions.Timeout("timed out")
    mock_requests.exceptions = real_requests.exceptions

    with pytest.raises(MetricsUnavailable) as refusal:
        get_generation_metrics("gen-timeout", "FAKE-sk-or-key")

    assert str(refusal.value) == "Request timeout querying generation gen-timeout: timed out"


@patch(f"{_TRACKING_MOD}.store_usage_data")
@patch(f"{_TRACKING_MOD}.requests")
def test_track_usage_reports_why_the_metrics_were_unavailable(
    mock_requests: MagicMock, mock_store: MagicMock, monkeypatch: pytest.MonkeyPatch
):
    """The caller-facing half: track_usage hands the reason on and stores nothing."""
    monkeypatch.setattr(tracking, "DEFAULT_GENERATION_CHECK_DELAY", 0)
    mock_requests.get.return_value = MagicMock(status_code=404)

    result = track_usage("gen-missing", "flow_mbank", api_key="FAKE-sk-or-key")

    assert result == {"success": False, "error": "OpenRouter answered status 404 for generation gen-missing"}
    mock_store.assert_not_called()


@patch(f"{_TRACKING_MOD}.requests")
def test_get_generation_metrics_defaults_missing_fields(mock_requests: MagicMock):
    """Missing fields in metrics default to 0 / 'unknown'."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"data": {}}
    mock_requests.get.return_value = mock_response

    result = get_generation_metrics("gen-sparse", "FAKE-sk-or-key")

    assert result is not None
    assert result["total_cost"] == 0.0
    assert result["tokens_prompt"] == 0
    assert result["tokens_completion"] == 0
    assert result["generation_time"] == 0
    assert result["latency"] == 0
    assert result["provider_name"] == "unknown"


@patch(f"{_TRACKING_MOD}.API_JSON_DIR")
def test_store_usage_data_creates_new_file(mock_dir: MagicMock, tmp_path: Path):
    """store_usage_data creates initial structure when file doesn't exist."""
    from datetime import datetime

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

    today = datetime.now().date().isoformat()
    assert wrapper["module_name"] == "usage_tracker"
    assert wrapper["created"] == today
    assert wrapper["last_updated"] == today
    data = wrapper["data"]

    assert data["current_session"]["total_requests"] == 1
    assert data["current_session"]["total_cost"] == 0.005
    assert data["current_session"]["total_tokens"] == 150

    assert "test_caller" in data["usage_by_caller"]
    caller_data = data["usage_by_caller"]["test_caller"]
    assert caller_data["requests"] == 1
    assert caller_data["total_cost"] == 0.005
    assert caller_data["total_tokens"] == 150
    assert caller_data["models_used"]["anthropic/claude-3.5-sonnet"] == 1

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

    store_usage_data("caller_a", "openai/gpt-4", "gen-100", metrics)

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
def test_store_usage_data_stores_into_a_data_leg_with_no_data_key(mock_dir: MagicMock, tmp_path: Path):
    """The file is the json service's data leg and may hold no 'data' key: store into it, keep its keys."""
    from datetime import datetime

    mock_dir.__truediv__ = lambda self, other: tmp_path / other
    mock_dir.mkdir = MagicMock()

    data_path = tmp_path / "usage_tracker_data.json"
    service_doc = {
        "module_name": "usage_tracker",
        "created": "2025-11-13",
        "last_updated": "2025-11-13",
        "operations_total": 4,
        "operations_successful": 0,
        "operations_failed": 0,
        "last_operation": "track_usage",
    }
    data_path.write_text(json.dumps(service_doc), encoding="utf-8")

    metrics = {
        "total_cost": 0.003,
        "tokens_prompt": 30,
        "tokens_completion": 10,
        "generation_time": 100,
        "latency": 150,
        "provider_name": "test",
    }

    result = store_usage_data("caller", "model/a", "gen-leg", metrics)

    assert result is True
    document = json.loads(data_path.read_text(encoding="utf-8"))
    for key in ("module_name", "created", "operations_total", "operations_successful", "operations_failed"):
        assert document[key] == service_doc[key]
    assert document["last_operation"] == "track_usage"
    assert document["last_updated"] == datetime.now().date().isoformat()
    assert document["data"]["current_session"]["total_requests"] == 1
    assert list(document["data"]["generation_tracking"]) == ["gen-leg"]


@patch(f"{_TRACKING_MOD}.API_JSON_DIR")
def test_store_usage_data_writes_back_the_keys_it_does_not_own(mock_dir: MagicMock, tmp_path: Path):
    """A store after the service bumped the document keeps the bump (FPLAN-0542)."""
    # The json service keeps lifetime operations_total and last_operation in the same document.
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
    data_path = tmp_path / "usage_tracker_data.json"

    store_usage_data("caller_a", "openai/gpt-4", "gen-100", metrics)
    bumped = json.loads(data_path.read_text(encoding="utf-8"))
    bumped.update({"created": "2025-11-13", "operations_total": 9, "last_operation": "track_usage"})
    data_path.write_text(json.dumps(bumped), encoding="utf-8")

    result = store_usage_data("caller_a", "openai/gpt-4", "gen-101", metrics)

    assert result is True
    document = json.loads(data_path.read_text(encoding="utf-8"))
    assert document["created"] == "2025-11-13"
    assert document["operations_total"] == 9
    assert document["last_operation"] == "track_usage"
    assert document["data"]["current_session"]["total_requests"] == 2


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
