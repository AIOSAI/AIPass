# =================== AIPass ====================
# Name: test_critical_paths.py
# Description: Critical path tests for API branch core functions
# Version: 1.1.2
# Created: 2026-03-31
# Modified: 2026-10-24
# =============================================

"""Tests for apps/modules/api_key.py and apps/modules/openrouter_client.py, the request pipeline."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(external) — the real OpenRouter request; make_api_request is mocked, no network in tests
# seedgo: no-test-needed(ruff) — that api_key.py and openrouter_client.py parse and import

import threading
from unittest.mock import patch, MagicMock

import pytest
from keyring.errors import KeyringLocked

from aipass.api.apps.modules import api_key
from aipass.api.apps.modules import openrouter_client


FIXTURE_KEY = "sk-or-v1-" + "a" * 40


class TestGetApiKey:
    """Tests for fetch_api_key() — the key read from the keyring entry aipass/<provider>/api_key."""

    @patch("aipass.api.apps.handlers.auth.keys.json_handler", autospec=True)
    def test_key_from_the_keyring_entry(self, mock_jh, keyring_store):
        keyring_store.set_password("aipass", "openrouter/api_key", FIXTURE_KEY)

        assert api_key.fetch_api_key("openrouter") == FIXTURE_KEY
        mock_jh.log_operation.assert_called_once()

    @patch("aipass.api.apps.handlers.auth.keys.json_handler", autospec=True)
    def test_no_entry_returns_none(self, mock_jh):
        assert api_key.fetch_api_key("openrouter") is None

    @patch("aipass.api.apps.handlers.auth.keys.json_handler", autospec=True)
    def test_invalid_key_format_returns_none(self, mock_jh, keyring_store):
        keyring_store.set_password("aipass", "openrouter/api_key", "INVALID-PREFIX-key-that-is-long-enough-to-pass")

        assert api_key.fetch_api_key("openrouter") is None

    @patch("aipass.api.apps.handlers.auth.keys.json_handler", autospec=True)
    def test_a_locked_keyring_raises_naming_the_backend_never_none(self, mock_jh, keyring_store):
        with patch.object(keyring_store, "get_password", side_effect=KeyringLocked("locked")):
            with pytest.raises(api_key.keys.KeyUnavailable) as caught:
                api_key.fetch_api_key("openrouter")

        assert "DictKeyring" in str(caught.value)
        assert caught.value.__cause__ is None
        assert caught.value.__suppress_context__ is True
        mock_jh.log_operation.assert_not_called()


class TestValidateKey:
    """Tests for fetch_validate_key() — key format validation per provider rules."""

    def test_valid_openrouter_key(self):
        """Valid openrouter key with correct prefix and length passes."""
        key = "sk-or-v1-fake-test-key-do-not-use-aabbccdd00110000000000"
        assert api_key.fetch_validate_key(key, "openrouter") is True

    def test_key_too_short(self):
        """Key shorter than min_length fails validation."""
        key = "sk-or-v1-short"
        assert len(key) < 20
        assert api_key.fetch_validate_key(key, "openrouter") is False

    def test_wrong_prefix(self):
        """Key with wrong prefix for provider fails validation."""
        key = "sk-wrong-prefix-but-long-enough-to-pass-length"
        assert api_key.fetch_validate_key(key, "openrouter") is False

    def test_empty_key(self):
        """Empty string key fails validation."""
        assert api_key.fetch_validate_key("", "openrouter") is False

    def test_none_key(self):
        """None key fails validation."""
        assert api_key.fetch_validate_key(None, "openrouter") is False  # type: ignore[arg-type]

    def test_generic_provider_no_prefix_required(self):
        """Generic provider only checks min_length, no prefix required."""
        key = "any-key-that-is-long-enough"
        assert api_key.fetch_validate_key(key, "unknown_provider") is True

    def test_generic_provider_too_short(self):
        """Generic provider rejects keys shorter than 10 chars."""
        assert api_key.fetch_validate_key("short", "unknown_provider") is False


MODULE = "aipass.api.apps.handlers.openrouter.client"


class TestGetResponse:
    """Tests for get_response() — main API call orchestrator."""

    @patch(f"{MODULE}.track_usage")
    @patch(f"{MODULE}.extract_response")
    @patch(f"{MODULE}.make_api_request")
    @patch(f"{MODULE}.get_cached_client")
    @patch(f"{MODULE}.get_api_key")
    @patch(f"{MODULE}.get_caller_info")
    def test_successful_call(
        self,
        mock_caller_info,
        mock_get_key,
        mock_get_client,
        mock_make_req,
        mock_extract,
        mock_track,
    ):
        """Full successful pipeline: detect caller, get key, make request, extract, track."""
        tracked = threading.Event()
        mock_track.side_effect = lambda *a: tracked.set()
        mock_caller_info.return_value = {"caller_name": "test-branch"}
        mock_get_key.return_value = "FAKE-sk-or-v1-testkey"
        mock_get_client.return_value = MagicMock()
        mock_make_req.return_value = MagicMock()
        mock_extract.return_value = {
            "content": "Hello, world!",
            "id": "gen-abc123",
            "model": "anthropic/claude-3.5-sonnet",
        }

        result = openrouter_client.get_response("What is Python?", model="anthropic/claude-3.5-sonnet")

        assert result is not None
        assert result["content"] == "Hello, world!"
        assert result["id"] == "gen-abc123"
        assert tracked.wait(5)
        mock_track.assert_called_once()

    @patch(f"{MODULE}.track_usage")
    @patch(f"{MODULE}.extract_response")
    @patch(f"{MODULE}.make_api_request")
    @patch(f"{MODULE}.get_cached_client")
    @patch(f"{MODULE}.get_api_key")
    def test_the_response_returns_without_waiting_on_tracking(
        self, mock_get_key, mock_get_client, mock_make_req, mock_extract, mock_track
    ):
        """track_usage sleeps and calls OpenRouter; get_response hands it off instead of waiting on it."""
        release, tracked = threading.Event(), threading.Event()
        mock_track.side_effect = lambda *a: (release.wait(5), tracked.set())
        mock_get_key.return_value = "FAKE-sk-or-v1-testkey"
        mock_extract.return_value = {"content": "hi", "id": "gen-bg", "model": "m"}
        answers = []
        caller = threading.Thread(target=lambda: answers.append(openrouter_client.get_response("p", "c", "m")))

        caller.start()
        caller.join(timeout=2)
        returned_first = not caller.is_alive()
        release.set()
        caller.join()

        assert returned_first, "get_response waited on track_usage"
        assert answers[0]["id"] == "gen-bg"
        assert tracked.wait(5)
        mock_track.assert_called_once_with("gen-bg", "c", "m", "FAKE-sk-or-v1-testkey")

    @patch(f"{MODULE}.get_api_key")
    @patch(f"{MODULE}.get_caller_info")
    def test_no_model_returns_none(self, mock_caller_info, mock_get_key):
        """Missing model parameter returns None without making API call."""
        mock_caller_info.return_value = {"caller_name": "test"}

        result = openrouter_client.get_response("What is Python?", model=None)

        assert result is None
        mock_get_key.assert_not_called()

    @patch(f"{MODULE}.get_api_key")
    @patch(f"{MODULE}.get_caller_info")
    def test_no_api_key_returns_none(self, mock_caller_info, mock_get_key):
        """No API key available returns None."""
        mock_caller_info.return_value = {"caller_name": "test"}
        mock_get_key.return_value = None

        result = openrouter_client.get_response("What is Python?", model="anthropic/claude-3.5-sonnet")

        assert result is None


class TestExtractResponse:
    """Tests for extract_response() — response content extraction from OpenAI objects."""

    def test_valid_response(self):
        """Extracts content, id, and model from a well-formed response."""
        choice = MagicMock()
        choice.message.content = "The answer is 42."
        choice.finish_reason = "stop"

        response = MagicMock()
        response.choices = [choice]
        response.id = "gen-xyz789"
        response.model = "anthropic/claude-3.5-sonnet"

        result = openrouter_client.extract_response(response)

        assert result is not None
        assert result["content"] == "The answer is 42."
        assert result["id"] == "gen-xyz789"
        assert result["model"] == "anthropic/claude-3.5-sonnet"

    def test_none_response(self):
        """None response returns None."""
        assert openrouter_client.extract_response(None) is None

    def test_response_no_choices(self):
        """Response with empty choices list returns None."""
        response = MagicMock()
        response.choices = []

        assert openrouter_client.extract_response(response) is None

    def test_response_no_content(self):
        """Response with choice but no content returns None."""
        choice = MagicMock()
        choice.message.content = None

        response = MagicMock()
        response.choices = [choice]
        response.id = "gen-empty"
        response.model = "test/model"

        assert openrouter_client.extract_response(response) is None

    def test_unreadable_response_raises_with_the_reason(self):
        """A response object that fails to read raises OpenRouterUnavailable naming why."""
        # None would read the same as an empty reply.
        response = MagicMock()
        response.choices.__getitem__.side_effect = RuntimeError("bad shape")

        with pytest.raises(openrouter_client.client.OpenRouterUnavailable) as caught:
            openrouter_client.extract_response(response)

        assert str(caught.value) == "OpenRouter response could not be read: bad shape"

    def test_response_missing_message(self):
        """Response choice without message attribute returns None."""
        choice = MagicMock(spec=[])  # No attributes at all
        response = MagicMock()
        response.choices = [choice]

        assert openrouter_client.extract_response(response) is None
