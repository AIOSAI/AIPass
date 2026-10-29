# =================== AIPass ====================
# Name: test_models_handler.py
# Description: Tests for OpenRouter model fetching handler
# Version: 1.1.0
# Created: 2026-05-12
# Modified: 2026-10-28
# =============================================

"""Tests for apps/handlers/openrouter/models.py, the OpenRouter model fetch."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that models.py parses and imports
# seedgo: no-test-needed(constant) — OPENROUTER_API_URL, DEFAULT_TIMEOUT and MODULE_NAME's values
# seedgo: no-test-needed(network) — a real call to OpenRouter; urlopen is patched at the edge
# seedgo: no-test-needed(hardcoded_key) — any real key; the tests hand the handler a stand-in string

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

import pytest

from aipass.api.apps.handlers.openrouter.models import DEFAULT_TIMEOUT, ModelsUnavailable, fetch_models_from_api

_MODELS_MOD = "aipass.api.apps.handlers.openrouter.models"
_FAKE_KEY = "FAKE-sk-or-test"


def _answer(mock_urlopen: MagicMock, body: bytes) -> None:
    """Make the patched urlopen answer with *body*."""
    mock_urlopen.return_value.__enter__.return_value.read.return_value = body


class TestFetchModelsFromApi:
    """Verifies OpenRouter model-list fetching under various conditions."""

    # Every failure raises ModelsUnavailable with its reason: [] means a reachable endpoint with no models.

    @patch(f"{_MODELS_MOD}.urlopen")
    def test_successful_fetch(self, mock_get: MagicMock) -> None:
        """200 response with valid data returns list of model dicts."""
        _answer(mock_get, json.dumps({"data": [{"id": "model1"}, {"id": "model2"}]}).encode())

        result = fetch_models_from_api(_FAKE_KEY)

        assert len(result) == 2
        assert result[0]["id"] == "model1"
        mock_get.assert_called_once()
        assert mock_get.call_args.kwargs["timeout"] == DEFAULT_TIMEOUT

    @patch(f"{_MODELS_MOD}.urlopen")
    def test_an_empty_model_list_is_an_answer(self, mock_get: MagicMock) -> None:
        """A 200 with an empty data list returns [] and raises nothing."""
        _answer(mock_get, b'{"data": []}')

        assert fetch_models_from_api(_FAKE_KEY) == []

    @patch(f"{_MODELS_MOD}.urlopen")
    def test_non_200_status(self, mock_get: MagicMock) -> None:
        """Non-200 status code raises, naming the status."""
        mock_get.side_effect = HTTPError("https://openrouter.ai/api/v1/models", 401, "Unauthorized", None, None)  # type: ignore[arg-type]

        with pytest.raises(ModelsUnavailable, match="401"):
            fetch_models_from_api(_FAKE_KEY)

    @pytest.mark.parametrize("timeout", [TimeoutError("timed out"), URLError(TimeoutError("timed out"))])
    @patch(f"{_MODELS_MOD}.urlopen")
    def test_timeout(self, mock_get: MagicMock, timeout: Exception) -> None:
        """Request timeout raises, naming the wait: bare on a read, wrapped in URLError on a connect."""
        mock_get.side_effect = timeout

        with pytest.raises(ModelsUnavailable, match="10s"):
            fetch_models_from_api(_FAKE_KEY)

    @patch(f"{_MODELS_MOD}.urlopen")
    def test_network_error(self, mock_get: MagicMock) -> None:
        """General network error raises, carrying the transport's reason."""
        mock_get.side_effect = URLError("no route")

        with pytest.raises(ModelsUnavailable, match="no route"):
            fetch_models_from_api(_FAKE_KEY)

    @patch(f"{_MODELS_MOD}.urlopen")
    def test_invalid_json(self, mock_get: MagicMock) -> None:
        """Invalid JSON response raises."""
        _answer(mock_get, b"<html>not json</html>")

        with pytest.raises(ModelsUnavailable, match="JSON"):
            fetch_models_from_api(_FAKE_KEY)

    @patch(f"{_MODELS_MOD}.urlopen")
    def test_missing_data_field(self, mock_get: MagicMock) -> None:
        """JSON without a 'data' list raises."""
        _answer(mock_get, b'{"models": [{"id": "m1"}]}')

        with pytest.raises(ModelsUnavailable, match="data"):
            fetch_models_from_api(_FAKE_KEY)
