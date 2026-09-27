# =================== AIPass ====================
# Name: test_models_handler.py
# Description: Tests for OpenRouter model fetching handler
# Version: 1.0.0
# Created: 2026-05-12
# Modified: 2026-09-27
# =============================================

"""Tests for apps/handlers/openrouter/models.py, the OpenRouter model fetch."""

# Tests:
# - fetch_models_from_api: success, non-200, timeout, network error,
#   invalid JSON, missing 'data' field

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that models.py parses and imports
# seedgo: no-test-needed(constant) — OPENROUTER_API_URL, DEFAULT_TIMEOUT and MODULE_NAME's values
# seedgo: no-test-needed(network) — a real call to OpenRouter; requests.get is patched at the edge
# seedgo: no-test-needed(hardcoded_key) — any real key; the tests hand the handler a stand-in string

from __future__ import annotations

from unittest.mock import MagicMock, patch

import requests

from aipass.api.apps.handlers.openrouter.models import fetch_models_from_api

_MODELS_MOD = "aipass.api.apps.handlers.openrouter.models"
_FAKE_KEY = "FAKE-sk-or-test"


# =============================================
# fetch_models_from_api
# =============================================


class TestFetchModelsFromApi:
    """Verifies OpenRouter model-list fetching under various conditions."""

    @patch(f"{_MODELS_MOD}.requests.get")
    def test_successful_fetch(self, mock_get: MagicMock) -> None:
        """200 response with valid data returns list of model dicts."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": [{"id": "model1"}, {"id": "model2"}]}
        mock_get.return_value = mock_response

        result = fetch_models_from_api(_FAKE_KEY)

        assert len(result) == 2
        assert result[0]["id"] == "model1"
        mock_get.assert_called_once()

    @patch(f"{_MODELS_MOD}.requests.get")
    def test_non_200_status(self, mock_get: MagicMock) -> None:
        """Non-200 status code returns empty list."""
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_get.return_value = mock_response

        result = fetch_models_from_api(_FAKE_KEY)

        assert result == []

    @patch(f"{_MODELS_MOD}.requests.get")
    def test_timeout(self, mock_get: MagicMock) -> None:
        """Request timeout returns empty list."""
        mock_get.side_effect = requests.exceptions.Timeout("timed out")

        result = fetch_models_from_api(_FAKE_KEY)

        assert result == []

    @patch(f"{_MODELS_MOD}.requests.get")
    def test_network_error(self, mock_get: MagicMock) -> None:
        """General network error returns empty list."""
        mock_get.side_effect = requests.exceptions.ConnectionError("no route")

        result = fetch_models_from_api(_FAKE_KEY)

        assert result == []

    @patch(f"{_MODELS_MOD}.requests.get")
    def test_invalid_json(self, mock_get: MagicMock) -> None:
        """Invalid JSON response returns empty list."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("bad json")
        mock_get.return_value = mock_response

        result = fetch_models_from_api(_FAKE_KEY)

        assert result == []

    @patch(f"{_MODELS_MOD}.requests.get")
    def test_missing_data_field(self, mock_get: MagicMock) -> None:
        """JSON without 'data' key returns empty list."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"models": [{"id": "m1"}]}
        mock_get.return_value = mock_response

        result = fetch_models_from_api(_FAKE_KEY)

        assert result == []
